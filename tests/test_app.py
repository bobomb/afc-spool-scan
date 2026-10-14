from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from conftest import sim_config, wait_until

from station import __main__ as entry
from station import simctl
from station.app import Station
from station.audio import Audio


class IpcClient:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader, self.writer = reader, writer
        self.events: list[dict[str, Any]] = []
        self._next = 1

    @classmethod
    async def connect(cls, port: int) -> IpcClient:
        return cls(*await asyncio.open_connection("127.0.0.1", port))

    async def read(self) -> dict[str, Any]:
        return json.loads(await asyncio.wait_for(self.reader.readline(), 3))

    async def request(self, action: str, **args: Any) -> dict[str, Any]:
        request_id = f"u-{self._next}"
        self._next += 1
        self.writer.write((json.dumps({"type": "request", "id": request_id, "action": action, "args": args}) + "\n").encode())
        await self.writer.drain()
        while True:
            message = await self.read()
            if message["type"] == "result" and message["id"] == request_id:
                return message
            self.events.append(message)

    async def close(self) -> None:
        self.writer.close()


async def test_ipc_end_to_end(station: Station) -> None:
    client = await IpcClient.connect(station.ipc_port)
    hello = await client.read()
    assert hello["protocol"] == 1 and hello["writes"] is False and hello["printers"] == "sim"
    snapshot = (await client.read())["data"]
    assert snapshot["service"]["dry_run"] is False
    assert [p["name"] for p in snapshot["printers"]] == ["Kilo", "Yankee"]
    assert snapshot["printers"][0]["lanes"][0]["spool_id"] == 84
    assert snapshot["settings"]["target"] == "both"
    assert snapshot["health"]["scale"] is True and snapshot["health"]["scanner"] is True

    await client.request("sim.scale", grams=640.0)
    result = await client.request("weigh_load", spool_id=97)
    assert result["ok"] is True and result["activity_id"]
    topics = [event["topic"] for event in client.events if event["type"] == "event"]
    assert {"scale", "spool", "printer", "activity"} <= set(topics)
    printer_events = [e["data"] for e in client.events if e.get("topic") == "printer"]
    assert any(p["pending_spool"] == 97 for p in printer_events)
    await client.close()


async def test_simctl_against_running_station(station: Station, capsys: pytest.CaptureFixture[str]) -> None:
    port = str(station.ipc_port)
    assert await simctl.run(simctl.build_parser().parse_args(["--port", port, "scale", "12.5", "--oz"])) == 0
    assert "Scale stable 354.4 g (oz)" in capsys.readouterr().out
    assert await simctl.run(simctl.build_parser().parse_args(
        ["--port", port, "printer", "yankee", "--lane", "lane3", "--spool", "93", "--status", "Loaded",
         "--filament-status", "Ready"])) == 0
    await wait_until(lambda: station.store.printers["yankee"].lanes[2].spool_id == 93)
    assert station.store.printers["yankee"].lanes[2].filament_status == "Ready"
    assert await simctl.run(simctl.build_parser().parse_args(["--port", port, "printer", "kilo", "--disconnect"])) == 0
    await wait_until(lambda: not station.store.printers["kilo"].connected)
    assert await simctl.run(simctl.build_parser().parse_args(["--port", port, "printer", "kilo", "--connect"])) == 0
    await wait_until(lambda: station.store.printers["kilo"].connected)
    assert await simctl.run(simctl.build_parser().parse_args(["--port", port, "scan", "WEB+SPOOLMAN:S-97"])) == 0
    await wait_until(lambda: station.store.scan.spool_id == 97)
    assert await simctl.run(simctl.build_parser().parse_args(
        ["--port", port, "request", "weigh", '{"spool_id": 999}'])) == 1
    capsys.readouterr()
    assert await simctl.run(simctl.build_parser().parse_args(["--port", port, "state", "settings"])) == 0
    assert json.loads(capsys.readouterr().out)["scan_mode"] == "immediate"
    assert await simctl.run(simctl.build_parser().parse_args(["--port", port, "spoolman", "--offline"])) == 0
    assert station.sim_spoolman.online is False
    assert await simctl.run(simctl.build_parser().parse_args(
        ["--port", port, "printer", "kilo", "--print", "printing", "--progress", "0.3"])) == 0
    await wait_until(lambda: station.store.printers["kilo"].progress == 0.3)


async def test_simctl_reports_connection_failure(capsys: pytest.CaptureFixture[str]) -> None:
    assert await simctl.run(simctl.build_parser().parse_args(["--port", "9", "scale", "1"])) == 1
    assert "Cannot connect" in capsys.readouterr().err


def test_simctl_request_mapping() -> None:
    parse = simctl.build_parser().parse_args
    assert simctl.to_request(parse(["scale", "--status", "motion"])) == ("sim.scale", {"unit": "g", "status": "motion"})
    assert simctl.to_request(parse(["printer", "kilo", "--insert", "lane4"])) == (
        "sim.printer", {"printer": "kilo", "op": "insert", "lane": "lane4"})
    assert simctl.to_request(parse(["printer", "kilo", "--lane", "lane1", "--clear", "--no-tool-loaded"])) == (
        "sim.printer", {"printer": "kilo", "op": "lane", "lane": "lane1", "clear": True, "tool_loaded": False})
    assert simctl.to_request(parse(["spoolman", "--online"])) == ("sim.spoolman", {"online": True})
    with pytest.raises(SystemExit):
        simctl.to_request(parse(["scale"]))
    with pytest.raises(SystemExit):
        simctl.to_request(parse(["request", "weigh", "[1]"]))


async def test_station_restores_state_on_restart(tmp_path: Path) -> None:
    first = Station(sim_config(tmp_path), printer_backoff=(0.02, 0.05), publish_delay=0, scale_interval=0)
    await first.start()
    await wait_until(lambda: all(p.connected for p in first.store.printers.values()))
    await first.actions.handle("set_setting", {"key": "theme", "value": "light"})
    await first.actions.handle("load", {"spool_id": 97})
    await first.stop()
    second = Station(sim_config(tmp_path), printer_backoff=(0.02, 0.05), publish_delay=0, scale_interval=0)
    await second.start()
    try:
        assert second.store.settings["theme"] == "light"
        assert second.store.activity[0]["action"] == "load"
    finally:
        await second.stop()


def test_main_rejects_bad_config(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("STATION_WRITES", "sometimes")
    assert entry.main([]) == 2
    assert "Configuration error" in capsys.readouterr().err


def test_main_reports_port_in_use(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        monkeypatch.setenv("STATION_STATE_DIR", str(tmp_path))
        code = entry.main(["--hardware", "sim", "--printers", "sim", "--spoolman", "sim", "--writes", "off",
                           "--ipc-port", str(port)])
    assert code == 1


async def test_audio_commands_and_disabled() -> None:
    commands: list[list[str]] = []

    async def runner(command: list[str]) -> int:
        commands.append(command)
        return 0

    audio = Audio(Path("/repo/audible-cue.py"), enabled=True, backend="alsa", device="plughw:CARD=Headphones,DEV=0",
                  gpio_pin="18", runner=runner)
    audio.play("weigh")
    await asyncio.sleep(0.01)
    assert commands == [[sys.executable, str(Path("/repo/audible-cue.py")), "weigh", "--backend", "alsa",
                         "--device", "plughw:CARD=Headphones,DEV=0", "--gpio-pin", "18"]]
    with pytest.raises(ValueError):
        audio.play("fanfare")
    silent = Audio(Path("x"), enabled=True, backend="none", runner=runner)
    silent.play("error")
    await asyncio.sleep(0.01)
    assert len(commands) == 1

    async def broken(command: list[str]) -> int:
        raise FileNotFoundError("python3")

    failing = Audio(Path("x"), enabled=True, runner=broken)
    failing.play("success")
    await asyncio.sleep(0.01)
