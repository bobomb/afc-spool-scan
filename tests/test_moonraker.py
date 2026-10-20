from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import aiohttp
import pytest

from station.config import PrinterConfig
from station.moonraker import (
    MoonrakerClient,
    PrinterCommandError,
    PrinterOffline,
    clean_display_name,
    deep_merge,
    normalize_color,
    parse_next_spool,
)
from station.printers import DisplayNames, PrinterManager
from station.sim.printers import SimPrinterServer, parse_gcode
from station.sim.spoolman import SimSpoolman
from station.state import PrinterState


async def wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


@pytest.fixture
async def rig():  # noqa: ANN201
    spoolman = SimSpoolman()
    server = SimPrinterServer.from_fixtures(["kilo", "yankee"], spool_lookup=spoolman.get)
    await server.start()
    session = aiohttp.ClientSession()
    published: list[PrinterState] = []
    client = MoonrakerClient(
        PrinterConfig("Kilo", "127.0.0.1", 1), session, on_change=published.append, writes=True,
        url=server.url_for("kilo"), backoff=(0.02, 0.05), publish_delay=0,
    )
    client.start()
    await wait_until(lambda: client.state.connected)
    yield server.printers["kilo"], client, published
    await client.stop()
    await session.close()
    await server.stop()


def test_helpers() -> None:
    target = {"a": {"b": 1, "c": {"d": 2}}}
    deep_merge(target, {"a": {"c": {"e": 3}}, "x": 1})
    assert target == {"a": {"b": 1, "c": {"d": 2, "e": 3}}, "x": 1}
    assert normalize_color("#ff00aa") == "#FF00AA"
    assert normalize_color("") is None
    assert normalize_color("#12") is None
    assert parse_next_spool("Spool ID set for next load: '97'") == (True, 97)
    assert parse_next_spool("// Spool ID '84' being overwritten for next load: '97'") == (True, 97)
    assert parse_next_spool("Spool ID set for next load: 'None'") == (True, None)
    assert parse_next_spool("something else") == (False, None)
    assert parse_gcode("SET_SPOOL_ID LANE=lane1 SPOOL_ID=") == ("SET_SPOOL_ID", {"LANE": "lane1", "SPOOL_ID": ""})
    assert clean_display_name("  Big \n  Bird ") == "Big Bird"
    assert clean_display_name("   ") is None and clean_display_name(42) is None
    assert clean_display_name("x" * 40) == "x" * 32


async def test_mainsail_name_is_the_label(rig) -> None:  # noqa: ANN001
    _, client, published = rig
    assert (client.state.name, client.state.display_name, client.label) == ("Kilo", "Kestrel", "Kestrel")
    assert published[-1].display_name == "Kestrel" and published[-1].label == "Kestrel"


async def test_mainsail_name_follows_reconnects(rig) -> None:  # noqa: ANN001
    printer, client, _ = rig
    names: list[tuple[str, str | None]] = []
    client.on_display_name = lambda key, name: names.append((key, name))
    printer.mainsail_name = "  Big   Bird "
    await printer.disconnect()
    await wait_until(lambda: not client.state.connected)
    with pytest.raises(PrinterOffline, match="^Kestrel is offline"):
        await client.set_next_spool(97)
    printer.connect()
    await wait_until(lambda: client.state.connected, timeout=3)
    assert client.label == "Big Bird"
    printer.mainsail_name = None
    await printer.disconnect()
    await wait_until(lambda: not client.state.connected)
    printer.connect()
    await wait_until(lambda: client.state.connected, timeout=3)
    assert client.state.display_name is None and client.label == "Kilo"
    assert names == [("kilo", "Big Bird"), ("kilo", None)]


async def test_mainsail_name_kept_when_lookup_fails() -> None:
    async with aiohttp.ClientSession() as session:
        client = MoonrakerClient(PrinterConfig("Kilo", "h"), session, on_change=lambda s: None, writes=False,
                                 display_name="Kestrel")
        assert client.label == "Kestrel"

        async def broken(method: str, params: object = None, timeout: object = None) -> object:
            raise PrinterCommandError("Internal Server Error", 500)

        client.call = broken  # type: ignore[method-assign]
        await client._refresh_display_name()
        assert client.label == "Kestrel"

        async def missing(method: str, params: object = None, timeout: object = None) -> object:
            raise PrinterCommandError("Namespace 'mainsail' not found", 404)

        client.call = missing  # type: ignore[method-assign]
        await client._refresh_display_name()
        assert client.label == "Kilo"


async def test_manager_caches_mainsail_names(tmp_path) -> None:  # noqa: ANN001
    path = tmp_path / "printer_names.json"
    path.write_text('{"yankee": "Old Yeti", "gone": ""}', encoding="utf-8")
    server = SimPrinterServer.from_fixtures(["kilo", "yankee"])
    await server.start()
    async with aiohttp.ClientSession() as session:
        published: list[PrinterState] = []
        manager = PrinterManager(
            [PrinterConfig("Kilo", "h"), PrinterConfig("Yankee", "h")], session, on_change=published.append,
            writes=False, low_stock_g=lambda: 100.0, names_path=path,
            urls={key: server.url_for(key) for key in ("kilo", "yankee")}, backoff=(0.02, 0.05), publish_delay=0,
        )
        assert [state.label for state in published] == ["Kilo", "Old Yeti"]
        manager.start()
        await wait_until(lambda: all(client.state.connected for client in manager.all()))
        assert [client.label for client in manager.all()] == ["Kestrel", "Yeti"]
        await manager.stop()
    await server.stop()
    assert json.loads(path.read_text(encoding="utf-8")) == {"kilo": "Kestrel", "yankee": "Yeti"}
    path.write_text("not json", encoding="utf-8")
    assert DisplayNames(path).load() == {}


async def test_initial_state_from_subscription(rig) -> None:  # noqa: ANN001
    _, client, published = rig
    state = client.state
    assert state.connected and state.klippy_state == "ready"
    assert (state.print_state, state.progress, state.filename) == ("complete", 1.0, "bracket_v3.gcode")
    assert state.afc_state == "Idle" and state.afc_error is None
    assert state.current_load == "lane2"
    assert [lane.lane for lane in state.lanes] == ["lane1", "lane2", "lane3", "lane4"]
    lane1, lane2, lane3, lane4 = state.lanes
    assert (lane1.spool_id, lane1.map, lane1.material, lane1.color, lane1.remaining_g) == (84, "T0", "PLA", "#F5F5F5", 888.0)
    assert lane2.tool_loaded and lane2.filament_status == "In Tool"
    assert lane3.low_stock and not lane1.low_stock
    assert lane4.spool_id is None and lane4.remaining_g is None and not lane4.low_stock
    assert published[-1] == state


async def test_status_updates_merge(rig) -> None:  # noqa: ANN001
    printer, client, _ = rig
    await printer.set_print(state="printing", progress=0.25, filename="cube.gcode")
    await wait_until(lambda: client.state.print_state == "printing")
    assert client.state.progress == 0.25
    await printer.set_afc_error("Lane 2 jammed")
    await wait_until(lambda: client.state.afc_error is not None)
    assert client.state.afc_error == "Lane 2 jammed"
    await printer.update({"AFC": {"message": {"message": "", "type": ""}}})
    await asyncio.sleep(0.05)
    assert client.state.afc_error == "Lane 2 jammed"
    await printer.set_afc_error(None)
    await wait_until(lambda: client.state.afc_error is None)


async def test_next_spool_pending_tracking(rig) -> None:  # noqa: ANN001
    printer, client, _ = rig
    result = await client.set_next_spool(97)
    assert result.dry_run is False
    assert "Spool ID set for next load: '97'" in result.responses
    assert (client.state.pending_spool, client.state.pending_confirmed) == (97, True)
    assert printer.next_spool_id == 97
    await client.set_next_spool(98)
    assert client.state.pending_spool == 98
    await client.set_next_spool(None)
    assert (client.state.pending_spool, client.state.pending_confirmed) == (None, False)
    assert printer.gcode_log[-1] == "SET_NEXT_SPOOL_ID"

    await client.set_next_spool(97)
    await printer.insert_lane("lane4")
    await wait_until(lambda: client.lane("lane4").spool_id == 97)
    assert client.state.pending_spool is None
    assert client.lane("lane4").material == "ABS"


async def test_external_next_spool_responses_update_pending(rig) -> None:  # noqa: ANN001
    printer, client, _ = rig
    await printer.respond("Spool ID set for next load: '42'")
    await wait_until(lambda: client.state.pending_spool == 42)
    await printer.restart_klippy()
    await wait_until(lambda: client.state.pending_spool is None and client.state.connected)


async def test_set_lane_spool_and_duplicate_error(rig) -> None:  # noqa: ANN001
    printer, client, _ = rig
    await client.set_lane_spool("lane4", 97)
    await wait_until(lambda: client.lane("lane4").spool_id == 97)
    with pytest.raises(PrinterCommandError, match="already assigned"):
        await client.set_lane_spool("lane1", 85)
    await client.set_lane_spool("lane4", None)
    await wait_until(lambda: client.lane("lane4").spool_id is None)
    with pytest.raises(PrinterCommandError, match="Unknown command"):
        await client.gcode("FIRMWARE_RESTART_NOW")


async def test_writes_off_does_not_send(rig) -> None:  # noqa: ANN001
    printer, client, _ = rig
    client.writes = False
    before = list(printer.gcode_log)
    result = await client.set_next_spool(97)
    assert result.dry_run is True
    assert printer.gcode_log == before
    assert client.state.pending_spool is None
    with pytest.raises(PrinterCommandError, match="writes are off"):
        await client.call("printer.gcode.script", {"script": "SET_NEXT_SPOOL_ID SPOOL_ID=1"})
    with pytest.raises(PrinterCommandError, match="writes are off"):
        await client.call("printer.emergency_stop")
    assert printer.gcode_log == before
    assert (await client.call("server.info"))["klippy_state"] == "ready"
    item = await client.call("server.database.get_item", {"namespace": "mainsail", "key": "general.printername"})
    assert item["value"] == "Kestrel"


async def test_disconnect_and_reconnect(rig) -> None:  # noqa: ANN001
    printer, client, published = rig
    await client.set_next_spool(97)
    assert client.state.pending_spool == 97
    await printer.disconnect()
    await wait_until(lambda: not client.state.connected)
    assert (client.state.pending_spool, client.state.pending_confirmed) == (None, False)
    assert published[-1].connected is False and published[-1].pending_spool is None
    with pytest.raises(PrinterOffline):
        await client.set_next_spool(97)
    printer.connect()
    await wait_until(lambda: client.state.connected, timeout=3)
    assert client.state.lanes[0].spool_id == 84
    assert client.state.pending_spool is None


async def test_lane_loaded_events_only_for_real_changes(rig) -> None:  # noqa: ANN001
    printer, client, _ = rig
    events: list[tuple[str, str, int]] = []
    client.on_lane_loaded = lambda *event: events.append(event)
    await client.set_next_spool(97)
    await printer.insert_lane("lane4")
    await wait_until(lambda: events == [("kilo", "lane4", 97)])
    await printer.disconnect()
    await wait_until(lambda: not client.state.connected)
    printer.connect()
    await wait_until(lambda: client.state.connected, timeout=3)
    await printer.eject_lane("lane4")
    await wait_until(lambda: client.lane("lane4").spool_id is None)
    assert events == [("kilo", "lane4", 97)]


async def test_klippy_shutdown_clears_pending(rig) -> None:  # noqa: ANN001
    printer, client, published = rig
    await client.set_next_spool(97)
    await printer.notify("notify_klippy_shutdown", [])
    await wait_until(lambda: client.state.klippy_state == "shutdown")
    assert not client.state.connected and client.state.pending_spool is None
    assert published[-1].pending_spool is None


async def test_low_stock_threshold_refresh(rig) -> None:  # noqa: ANN001
    _, client, _ = rig
    client.low_stock_g = lambda: 900.0
    client.refresh()
    assert [lane.low_stock for lane in client.state.lanes] == [True, True, True, False]


async def test_klippy_not_ready_until_notified() -> None:
    server = SimPrinterServer.from_fixtures(["yankee"])
    printer = server.printers["yankee"]
    printer.klippy_state = "startup"
    await server.start()
    async with aiohttp.ClientSession() as session:
        client = MoonrakerClient(PrinterConfig("Yankee", "h"), session, on_change=lambda s: None, writes=True,
                                 url=server.url_for("yankee"), backoff=(0.02, 0.05), publish_delay=0)
        client.start()
        await wait_until(lambda: client.state.klippy_state == "startup")
        assert not client.state.connected
        printer.klippy_state = "ready"
        await printer.notify("notify_klippy_ready", [])
        await wait_until(lambda: client.state.connected)
        assert client.state.print_state == "printing"
        await client.stop()
    await server.stop()


async def test_unreachable_printer_stays_offline() -> None:
    async with aiohttp.ClientSession() as session:
        published: list[PrinterState] = []
        client = MoonrakerClient(PrinterConfig("Ghost", "127.0.0.1", 9), session, on_change=published.append,
                                 writes=True, backoff=(0.01, 0.02), publish_delay=0)
        client.start()
        await asyncio.sleep(0.1)
        await client.stop()
        assert not client.state.connected
        with pytest.raises(PrinterOffline):
            await client.gcode("SET_NEXT_SPOOL_ID")
