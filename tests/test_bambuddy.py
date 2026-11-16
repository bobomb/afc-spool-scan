from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import aiohttp
import pytest

from station.bambuddy import BambuddyClient, hms_text, slot_of, spool_present, tray_tag
from station.catalog import meta_from_api
from station.config import PrinterConfig
from station.printer_client import LaneLoad, PrinterCommandError, PrinterNotice, PrinterOffline
from station.sim.bambuddy import SimBambuddy
from station.sim.spoolman import SimSpoolman
from station.state import PrinterState

KEY = "test-key"
UNKNOWN_TAG = "D4" * 16


async def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


class Rig:
    def __init__(self, sim: SimBambuddy, client: BambuddyClient, spoolman: SimSpoolman) -> None:
        self.sim = sim
        self.client = client
        self.spoolman = spoolman
        self.loads: list[LaneLoad] = []
        self.notices: list[PrinterNotice] = []
        self.refreshed: list[set[int]] = []
        self.published: list[PrinterState] = []
        client.on_lane_loaded = self.loads.append
        client.on_notice = self.notices.append
        client.spool_refresh = lambda ids: self.refreshed.append(set(ids))

    @property
    def printer(self) -> Any:
        return self.sim.printers[1]

    def posts(self, path: str = "/api/v1/spoolman/inventory/slot-assignments") -> list[Any]:
        return [body for method, url, body in self.sim.requests if method == "POST" and url == path]


async def make_rig(writes: bool = True, api_key: str = KEY, **options: Any) -> tuple[Rig, aiohttp.ClientSession]:
    spoolman = SimSpoolman()
    sim = SimBambuddy.from_fixtures({1: "hotel"}, spool_lookup=spoolman.get, api_key=KEY, auto_unassign_s=0.1)
    url = await sim.start()
    session = aiohttp.ClientSession()
    holder: list[Rig] = []
    client = BambuddyClient(
        PrinterConfig("Hotel", "bambuddy", 0, kind="bambuddy", bambuddy_printer_id=1), session,
        on_change=lambda state: holder[0].published.append(state) if holder else None, writes=writes,
        base_url=url, api_key=api_key, spool_meta=lambda sid: meta_from_api(d) if (d := spoolman.get(sid)) else None,
        backoff=(0.02, 0.05), publish_delay=0, **{"insert_settle_s": 0.05, "settings_check_s": 0.05,
                                                 "usage_refresh_s": 0.05, **options},
    )
    rig = Rig(sim, client, spoolman)
    holder.append(rig)
    client.start()
    return rig, session


@pytest.fixture
async def rig():  # noqa: ANN201
    rig, session = await make_rig()
    await wait_until(lambda: rig.client.online)
    yield rig
    await rig.client.stop()
    await session.close()
    await rig.sim.stop()


def test_helpers() -> None:
    assert slot_of("3H-1") == 0 and slot_of("3H-9") == 8
    assert slot_of("3H-10") is None and slot_of("lane1") is None and slot_of("3H-x") is None
    assert spool_present({"exists": True, "state": 9}) is True
    assert spool_present({"exists": False, "state": 27, "tray_type": "PLA"}) is False
    assert spool_present({"state": 27, "tray_type": "PLA"}) is True
    assert spool_present({"state": 9, "tray_type": ""}) is False and spool_present(None) is False
    assert tray_tag({"tray_uuid": "ab" * 16}) == "AB" * 16
    assert tray_tag({"tray_uuid": "0" * 32}) is None and tray_tag({"tray_uuid": None}) is None
    assert hms_text([{"severity": 3, "description": "note"}]) is None
    assert hms_text([{"severity": 2, "code": "0700_2000", "description": ""}]) == "HMS 0700_2000"


async def test_status_maps_to_slots(rig: Rig) -> None:
    state = rig.client.state
    assert (state.kind, state.connected, state.off, state.display_name, rig.client.label) == (
        "bambuddy", True, False, "Heron", "Heron")
    assert (state.print_state, state.progress, state.filename) == ("printing", 0.42, "bracket_plate_1")
    assert state.current_load == "3H-2" and state.afc_error is None
    lanes = {lane.lane: lane for lane in state.lanes}
    assert list(lanes) == [f"3H-{n}" for n in range(1, 10)]
    assert [lanes[f"3H-{n}"].spool_id for n in range(1, 10)] == [101, 102, 103, None, 104, None, 105, 106, 107]
    assert lanes["3H-2"].tool_loaded and lanes["3H-2"].filament_status == "In Tool"
    assert lanes["3H-4"].prep is False and lanes["3H-4"].filament_status == "Empty"
    assert lanes["3H-6"].prep is True and lanes["3H-6"].material == "PLA" and lanes["3H-6"].colors == ["#7C594A"]
    hotel3 = lanes["3H-3"]
    assert (hotel3.material, hotel3.remaining_g, hotel3.remaining_pct, hotel3.colors) == ("PETG", 760.0, 76.0,
                                                                                         ["#FF6A13"])
    assert lanes["3H-5"].low_stock and not lanes["3H-1"].low_stock


async def test_wrong_api_key_stays_offline() -> None:
    rig, session = await make_rig(api_key="wrong")
    try:
        await wait_until(lambda: any(url == "/api/v1/auth/ws-token" for _, url, _ in rig.sim.requests))
        await asyncio.sleep(0.1)
        assert not rig.client.online and rig.client.state.klippy_state == "disconnected"
        assert not rig.client.state.off
    finally:
        await rig.client.stop()
        await session.close()
        await rig.sim.stop()


async def test_armed_spool_is_assigned_to_the_slot_it_goes_into(rig: Rig) -> None:
    await rig.sim.set_print(1, "IDLE")
    await rig.client.set_next_spool(97)
    assert (rig.client.state.pending_spool, rig.client.state.pending_confirmed) == (97, True)
    assert rig.posts() == []
    await rig.sim.insert(1, 3, material="ABS", color="FFFFFF")
    await wait_until(lambda: bool(rig.loads))
    load = rig.loads[0]
    assert (load.printer, load.lane, load.spool_id, load.assigned, load.dry_run, load.armed, load.previous) == (
        "hotel", "3H-4", 97, True, False, 97, None)
    assert load.note == "assigned #97 to Heron 3H-4"
    assert rig.posts() == [{"spoolman_spool_id": 97, "printer_id": 1, "ams_id": 32, "tray_id": 3, "move": True}]
    assert rig.client.state.pending_spool is None
    assert rig.client.lane("3H-4").spool_id == 97
    assert len(rig.loads) == 1
    await asyncio.sleep(0.15)
    assert rig.notices == [] and not rig.client.lane("3H-4").settings_pending


async def test_insert_without_armed_spool_changes_nothing(rig: Rig) -> None:
    await rig.sim.insert(1, 3)
    await wait_until(lambda: rig.client.lane("3H-4").prep)
    await asyncio.sleep(0.1)
    assert rig.posts() == [] and rig.loads == []
    assert rig.client.lane("3H-4").spool_id is None


async def test_spool_armed_after_the_insertion_is_not_assigned(rig: Rig) -> None:
    await rig.sim.insert(1, 3)
    await wait_until(lambda: rig.client.lane("3H-4").prep)
    await rig.client.set_next_spool(97)
    await asyncio.sleep(0.15)
    assert rig.posts() == [] and rig.loads == []
    assert rig.client.state.pending_spool == 97


async def test_two_slots_filled_together_assign_the_armed_spool_once(rig: Rig) -> None:
    await rig.sim.set_print(1, "IDLE")
    await rig.sim.eject(1, 5)
    await wait_until(lambda: not rig.client.lane("3H-6").prep)
    await rig.client.set_next_spool(97)
    await rig.sim.insert(1, 3)
    await rig.sim.insert(1, 5)
    await wait_until(lambda: bool(rig.loads))
    await asyncio.sleep(0.15)
    assert len(rig.posts()) == 1 and len(rig.loads) == 1
    assert rig.loads[0].lane == "3H-4"


async def test_arming_again_during_the_assignment_is_kept(rig: Rig) -> None:
    await rig.sim.set_print(1, "IDLE")
    await rig.client.set_next_spool(97)
    original = rig.client._post_assignment  # noqa: SLF001

    async def slow_post(slot: int, spool_id: int) -> None:
        await rig.client.set_next_spool(84)
        await original(slot, spool_id)

    rig.client._post_assignment = slow_post  # type: ignore[method-assign]  # noqa: SLF001
    await rig.sim.insert(1, 3)
    await wait_until(lambda: bool(rig.loads))
    assert rig.loads[0].spool_id == 97 and rig.client.state.pending_spool == 84


async def test_print_end_while_bambuddy_was_down_resends_pending_settings(rig: Rig) -> None:
    await rig.client.set_next_spool(97)
    await rig.sim.insert(1, 3)
    await wait_until(lambda: rig.client.lane("3H-4").settings_pending)
    await rig.sim.disconnect()
    await wait_until(lambda: not rig.client.state.connected)
    await rig.sim.set_print(1, "FINISH")
    rig.sim.connect()
    await wait_until(lambda: len(rig.posts()) == 2, timeout=3)
    await wait_until(lambda: not rig.client.lane("3H-4").settings_pending)
    assert rig.printer.tray(3)["tray_color"] == "FFFFFFFF"
    assert rig.refreshed


async def test_writes_off_reports_a_dry_run() -> None:
    rig, session = await make_rig(writes=False)
    try:
        await wait_until(lambda: rig.client.online)
        await rig.client.set_next_spool(97)
        await rig.sim.insert(1, 3)
        await wait_until(lambda: bool(rig.loads))
        assert rig.loads[0].dry_run and rig.loads[0].note == "Dry run: would assign #97 to Heron 3H-4"
        assert rig.client.state.pending_spool is None
        writes = [(method, url) for method, url, _ in rig.sim.requests
                  if method != "GET" and url != "/api/v1/auth/ws-token"]
        assert writes == []
        assert (await rig.client.set_lane_spool("3H-6", 97)).dry_run is True
        with pytest.raises(PrinterCommandError, match="writes are off"):
            await rig.client._request("DELETE", "/spoolman/inventory/slot-assignments/97")  # noqa: SLF001
    finally:
        await rig.client.stop()
        await session.close()
        await rig.sim.stop()


async def test_known_rfid_spool_keeps_bambuddys_match(rig: Rig) -> None:
    await rig.client.set_next_spool(102)
    await rig.sim.eject(1, 1)
    await wait_until(lambda: rig.client.lane("3H-2").spool_id is None)
    await rig.sim.insert(1, 1, tray_uuid="B2" * 16)
    await wait_until(lambda: rig.client.state.pending_spool is None)
    assert rig.loads[-1].spool_id == 102 and not rig.loads[-1].assigned
    assert rig.posts() == [] and rig.notices == []


async def test_rfid_spool_that_differs_from_the_scan_warns_and_stays_armed(rig: Rig) -> None:
    await rig.client.set_next_spool(97)
    await rig.sim.insert(1, 3, tray_uuid="A1" * 16)
    await wait_until(lambda: bool(rig.notices))
    assert rig.notices[0].message == "Heron 3H-4 holds #101 (RFID), not #97; #97 stays next spool"
    assert rig.client.state.pending_spool == 97
    assert rig.posts() == []
    assert rig.client.lane("3H-4").spool_id == 101


async def test_unknown_rfid_tag_is_learned_by_the_scanned_spool(rig: Rig) -> None:
    await rig.client.set_next_spool(97)
    await rig.sim.insert(1, 3, tray_uuid=UNKNOWN_TAG.lower())
    await wait_until(lambda: bool(rig.loads))
    assert rig.posts("/api/v1/spoolman/inventory/spools/97/tag") == []
    patches = [body for method, url, body in rig.sim.requests if method == "PATCH"]
    assert patches == [{"tray_uuid": UNKNOWN_TAG}]
    assert rig.sim.tags[UNKNOWN_TAG] == 97
    assert rig.loads[0].note == "assigned #97 to Heron 3H-4 (RFID tag learned)"
    assert rig.client.lane("3H-4").spool_id == 97


async def test_rfid_tag_of_another_spool_is_not_assigned(rig: Rig) -> None:
    await rig.client.set_next_spool(97)
    await rig.sim.insert(1, 3, tray_uuid=UNKNOWN_TAG)
    rig.sim.tags[UNKNOWN_TAG] = 84
    await wait_until(lambda: bool(rig.notices))
    assert "belongs to another spool" in rig.notices[0].message and "#97 not assigned" in rig.notices[0].message
    assert rig.posts() == [] and rig.client.state.pending_spool == 97


async def test_settings_refused_while_printing_are_sent_again_after_the_print(rig: Rig) -> None:
    await rig.client.set_next_spool(97)
    await rig.sim.insert(1, 3)
    await wait_until(lambda: rig.client.lane("3H-4").spool_id == 97)
    assert rig.client.lane("3H-4").settings_pending
    assert rig.printer.refused == [3] and rig.printer.tray(3)["tray_color"] == "808080FF"
    await rig.sim.set_print(1, "FINISH")
    await wait_until(lambda: len(rig.posts()) == 2)
    await wait_until(lambda: not rig.client.lane("3H-4").settings_pending)
    assert rig.printer.tray(3)["tray_color"] == "FFFFFFFF"
    await wait_until(lambda: len(rig.refreshed) == 2)
    assert 97 in rig.refreshed[0] and 101 in rig.refreshed[0]
    await asyncio.sleep(0.1)
    assert rig.notices == []


async def test_empty_slot_is_unassigned_by_bambuddy(rig: Rig) -> None:
    await rig.sim.set_print(1, "IDLE")
    await rig.sim.eject(1, 2)
    await wait_until(lambda: rig.client.lane("3H-3").prep is False)
    assert rig.client.lane("3H-3").spool_id is None
    await wait_until(lambda: 2 not in rig.client._assignments)  # noqa: SLF001
    assert rig.loads == []


async def test_powered_off_printer_is_off_not_offline(rig: Rig) -> None:
    await rig.client.set_next_spool(97)
    await rig.sim.power(1, False)
    await wait_until(lambda: rig.client.state.off)
    state = rig.client.state
    assert (state.connected, state.klippy_state, state.pending_spool) == (False, "off", None)
    with pytest.raises(PrinterOffline, match="Heron is off"):
        await rig.client.set_next_spool(97)
    await rig.client.set_next_spool(None)
    await rig.sim.power(1, True)
    await wait_until(lambda: rig.client.online)
    assert not rig.client.state.off


async def test_bambuddy_down_is_offline_and_reconnects(rig: Rig) -> None:
    await rig.client.set_next_spool(97)
    await rig.sim.disconnect()
    await wait_until(lambda: not rig.client.state.connected)
    assert (rig.client.state.off, rig.client.state.klippy_state, rig.client.state.pending_spool) == (
        False, "disconnected", None)
    rig.sim.connect()
    await wait_until(lambda: rig.client.online, timeout=3)


async def test_set_lane_spool_assigns_and_unassigns(rig: Rig) -> None:
    await rig.sim.set_print(1, "IDLE")
    result = await rig.client.set_lane_spool("3H-6", 97)
    assert result.dry_run is False and rig.client.lane("3H-6").spool_id == 97
    assert rig.posts()[-1]["tray_id"] == 5
    await wait_until(lambda: bool(rig.loads))
    assert rig.loads[0].lane == "3H-6" and not rig.loads[0].assigned
    await rig.client.set_lane_spool("3H-6", None)
    assert rig.client.lane("3H-6").spool_id is None
    assert ("DELETE", "/api/v1/spoolman/inventory/slot-assignments/97", None) in rig.sim.requests
    with pytest.raises(PrinterCommandError, match="no slot"):
        await rig.client.set_lane_spool("lane1", 97)


async def test_hms_warning_is_the_printer_error(rig: Rig) -> None:
    await rig.sim.set_hms(1, "AMS slot 4 is stuck")
    await wait_until(lambda: rig.client.state.afc_error == "AMS slot 4 is stuck")
    await rig.sim.set_hms(1, None)
    await wait_until(lambda: rig.client.state.afc_error is None)
