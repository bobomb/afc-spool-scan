"""Contract tests: the service parses data captured from the real printers and Spoolman.

The fixtures in station/sim/fixtures/captured/ come from
`scripts/capture-fixtures.py` (read-only) run against Kilo, Yankee and
Spoolman on 2026-10-14, and against Bambuddy (Hotel) on 2026-11-16. No network:
they are replayed through the simulators.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import THREE_PRINTERS, sim_config, wait_until

from station.app import Station
from station.bambuddy import AMS_3H, spool_present
from station.config import ConfigError, load_config, parse_printers
from station.moonraker import NEXT_SPOOL_PATTERN, normalize_color
from station.sim.spoolman import load_spool_fixtures
from station.spoolman import spool_info_from_api

CAPTURED = Path(__file__).resolve().parent.parent / "station" / "sim" / "fixtures" / "captured"


def test_captured_spools_map_to_spool_info() -> None:
    spools = load_spool_fixtures(CAPTURED / "spoolman" / "spools.json")
    assert len(spools) >= 3
    infos = [spool_info_from_api(spool, low_stock_g=100) for spool in spools]
    assert any(info.archived for info in infos)
    assert any(info.low_stock and not info.archived for info in infos)
    assert any(not info.low_stock and not info.archived for info in infos)
    for info, raw in zip(infos, spools):
        assert info.id == raw["id"] and info.found
        assert info.color is None or normalize_color(info.color) == info.color
        if info.spool_weight_g is not None and info.remaining_g is not None:
            assert info.expected_gross_g == pytest.approx(info.spool_weight_g + info.remaining_g, abs=0.11)


def test_captured_printers_have_the_objects_we_subscribe_to() -> None:
    for path in sorted((CAPTURED / "printers").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        objects = data["objects"]
        afc = objects["AFC"]
        assert {"current_load", "current_state", "error_state", "lanes", "message"} <= set(afc)
        for lane in afc["lanes"]:
            fields = objects[f"AFC_stepper {lane}"]
            assert {"spool_id", "material", "color", "weight", "filament_status", "map", "prep", "load",
                    "tool_loaded"} <= set(fields)
        assert "state" in objects["print_stats"] and "progress" in objects["display_status"]
    assert NEXT_SPOOL_PATTERN.search("Spool ID set for next load: '99'")


async def test_station_replays_captured_data(tmp_path: Path) -> None:
    station = Station(sim_config(tmp_path, sim_fixtures=CAPTURED), printer_backoff=(0.02, 0.05),
                      publish_delay=0, scale_interval=0)
    await station.start()
    try:
        await wait_until(lambda: all(p.connected for p in station.store.printers.values()))
        spools = {spool["id"] for spool in load_spool_fixtures(CAPTURED / "spoolman" / "spools.json")}
        for printer in station.store.printers.values():
            assert printer.lanes and printer.current_load
            for lane in printer.lanes:
                assert lane.map and lane.map.startswith("T")
                if lane.spool_id is None:
                    assert lane.remaining_g is None and not lane.low_stock
                else:
                    assert lane.spool_id in spools
                    assert lane.color is not None and lane.remaining_g is not None
        untagged = [lane for p in station.store.printers.values() for lane in p.lanes
                    if lane.spool_id is None and lane.prep]
        assert untagged, "the capture includes a loaded but untagged lane"
        tagged = next(lane.spool_id for p in station.store.printers.values() for lane in p.lanes if lane.spool_id)
        result = await station.actions.handle("lookup", {"spool_id": tagged})
        assert result["ok"] is True
    finally:
        await station.stop()


def test_captured_bambuddy_has_the_fields_we_read() -> None:
    data = json.loads((CAPTURED / "bambuddy" / "hotel.json").read_text(encoding="utf-8"))
    status = data["status"]
    assert {"connected", "state", "progress", "hms_errors", "tray_now", "ams"} <= set(status)
    unit = next(unit for unit in status["ams"] if unit["id"] == AMS_3H)
    trays = {tray["id"]: tray for tray in unit["tray"]}
    assert set(trays) == set(range(9))
    for tray in trays.values():
        assert {"exists", "state", "tray_type", "tray_color", "tray_uuid", "tag_uid"} <= set(tray)
    assert any(spool_present(tray) for tray in trays.values())
    assert any(not spool_present(tray) for tray in trays.values())
    messages = [json.loads(line) for line in
                (CAPTURED / "bambuddy" / "hotel.ws.jsonl").read_text(encoding="utf-8").splitlines() if line]
    status_messages = [message for message in messages if message["type"] == "printer_status"]
    assert status_messages and all({"printer_id", "data"} <= set(message) for message in status_messages)
    assert "ams" in status_messages[0]["data"]


async def test_station_replays_captured_bambuddy(tmp_path: Path) -> None:
    data = json.loads((CAPTURED / "bambuddy" / "hotel.json").read_text(encoding="utf-8"))
    station = Station(sim_config(tmp_path, sim_fixtures=CAPTURED, printers=parse_printers(THREE_PRINTERS)),
                      printer_backoff=(0.02, 0.05), publish_delay=0, scale_interval=0)
    await station.start()
    try:
        await wait_until(lambda: all(p.connected for p in station.store.printers.values()))
        printer = station.store.printers["hotel"]
        trays = {tray["id"]: tray for unit in data["status"]["ams"] if unit["id"] == AMS_3H
                 for tray in unit["tray"]}
        assert len(printer.lanes) == 9
        for slot, lane in enumerate(printer.lanes):
            present = spool_present(trays[slot])
            assert lane.prep is present
            expected = data["assignments"].get(str(slot)) if present else None
            assert lane.spool_id == expected
            if present:
                assert lane.material and lane.color
        assert [lane.map for lane in printer.lanes] == [f"T{slot}" for slot in range(1, 10)]
        assert [lane.nozzle for lane in printer.lanes] == ["0.4"] * 7 + ["0.4 HT", "0.4"]
    finally:
        await station.stop()


def test_sim_fixtures_option(tmp_path: Path) -> None:
    config = load_config(["--sim-fixtures", "station/sim/fixtures/captured"], environ={}, platform="win32")
    assert config.sim_fixtures == CAPTURED
    with pytest.raises(ConfigError, match="needs printers"):
        load_config(["--sim-fixtures", str(tmp_path)], environ={}, platform="win32")
