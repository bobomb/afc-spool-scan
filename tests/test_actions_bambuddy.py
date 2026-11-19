"""Actions with a Bambu printer (Hotel, behind the simulated Bambuddy) beside the two AFC printers."""

from __future__ import annotations

from typing import Any

from conftest import wait_until

from station.app import Station


async def act(station: Station, action: str, **args: Any) -> dict[str, Any]:
    return await station.actions.handle(action, args)  # type: ignore[union-attr]


def pending(station: Station) -> dict[str, int | None]:
    return {key: printer.pending_spool for key, printer in station.store.printers.items()}


def hotel_lane(station: Station, lane: str) -> Any:
    return next(item for item in station.store.printers["hotel"].lanes if item.lane == lane)


def bambuddy_posts(station: Station) -> list[Any]:
    return [body for method, url, body in station.sim_bambuddy.requests  # type: ignore[union-attr]
            if method == "POST" and url.endswith("/slot-assignments")]


async def test_load_arms_the_bambu_printer_too(station3: Station) -> None:
    result = await act(station3, "load", spool_id=97)
    assert result["ok"] and result["message"] == "Spool 97: next spool set on Kestrel, Yeti, Heron"
    assert pending(station3) == {"kilo": 97, "yankee": 97, "hotel": 97}
    assert station3.store.printers["hotel"].kind == "bambuddy"
    assert bambuddy_posts(station3) == []


async def test_inserting_into_the_bambu_slot_assigns_and_clears_the_others(station3: Station) -> None:
    await act(station3, "sim.printer", printer="hotel", op="print", state="IDLE")
    await act(station3, "load", spool_id=97)
    await act(station3, "sim.printer", printer="hotel", op="insert", lane="3H-4", material="ABS", color="FFFFFF")
    await wait_until(lambda: station3.store.activity[0]["action"] == "spool_loaded")
    entry = station3.store.activity[0]
    assert entry["message"] == "assigned #97 to Heron 3H-4; next spool cleared on Kestrel, Yeti"
    assert entry["printers"] == ["Heron", "Kestrel", "Yeti"] and entry["ok"] and entry["undoable"]
    assert pending(station3) == {"kilo": None, "yankee": None, "hotel": None}
    assert hotel_lane(station3, "3H-4").spool_id == 97
    assert station3.cues.played[-1] == "success"  # type: ignore[attr-defined]

    undone = await act(station3, "undo", activity_id=entry["id"])
    assert undone["ok"] and undone["message"] == "Undid automatic load of spool 97"
    assert pending(station3) == {"kilo": 97, "yankee": 97, "hotel": 97}
    await wait_until(lambda: hotel_lane(station3, "3H-4").spool_id is None)
    assert ("DELETE", "/api/v1/spoolman/inventory/slot-assignments/97", None) in \
        station3.sim_bambuddy.requests  # type: ignore[union-attr]


async def test_undo_clears_a_slot_whose_old_assignment_bambuddy_still_held(station3: Station) -> None:
    # Live 2026-11-19: #83 was still assigned to its empty slot from a print, went back in, and undo put it back.
    await act(station3, "sim.printer", printer="hotel", op="eject", lane="3H-3")
    await wait_until(lambda: not hotel_lane(station3, "3H-3").prep)
    assert station3.sim_bambuddy.printers[1].assignments[2] == 103  # type: ignore[union-attr]
    await act(station3, "load", spool_id=103)
    await act(station3, "sim.printer", printer="hotel", op="insert", lane="3H-3", material="PETG", color="FF6A13")
    await wait_until(lambda: station3.store.activity[0]["action"] == "spool_loaded")
    undone = await act(station3, "undo", activity_id=station3.store.activity[0]["id"])
    assert undone["ok"] and undone["message"] == "Undid automatic load of spool 103"
    await wait_until(lambda: hotel_lane(station3, "3H-3").spool_id is None)
    assert 2 not in station3.sim_bambuddy.printers[1].assignments  # type: ignore[union-attr]
    assert pending(station3) == {"kilo": 103, "yankee": 103, "hotel": 103}


async def test_a_powered_off_bambu_printer_is_skipped_quietly(station3: Station) -> None:
    await act(station3, "sim.printer", printer="hotel", op="power_off")
    await wait_until(lambda: station3.store.printers["hotel"].off)
    result = await act(station3, "load", spool_id=97)
    assert result["ok"] and result["message"] == "Spool 97: next spool set on Kestrel, Yeti"
    assert station3.cues.played[-1] == "success"  # type: ignore[attr-defined]
    assert pending(station3)["hotel"] is None
    assert station3.store.printers["hotel"].connected is False


async def test_bambuddy_down_is_reported_like_an_offline_printer(station3: Station) -> None:
    await act(station3, "sim.printer", printer="hotel", op="disconnect")
    await wait_until(lambda: not station3.store.printers["hotel"].connected)
    assert not station3.store.printers["hotel"].off
    result = await act(station3, "load", spool_id=97)
    assert not result["ok"] and result["code"] == "printer_offline"
    assert result["message"] == "Spool 97: next spool set on Kestrel, Yeti; Heron: offline"


async def test_rfid_mismatch_is_logged_as_a_printer_notice(station3: Station) -> None:
    await act(station3, "load", spool_id=97)
    await act(station3, "sim.printer", printer="hotel", op="insert", lane="3H-4", rfid="A1" * 16)
    await wait_until(lambda: station3.store.activity[0]["action"] == "printer")
    entry = station3.store.activity[0]
    assert entry["message"] == "Heron 3H-4 holds #101 (RFID), not #97; #97 stays next spool"
    assert entry["ok"] is False and entry["printers"] == ["Heron"] and entry["spool_id"] == 97
    assert pending(station3)["hotel"] == 97


async def test_sleep_disarms_the_bambu_printer(station3: Station) -> None:
    await act(station3, "load", spool_id=97)
    result = await act(station3, "sleep")
    assert result["message"] == "Station asleep: next spool cleared on Kestrel, Yeti, Heron"
    assert pending(station3) == {"kilo": None, "yankee": None, "hotel": None}


async def test_assign_a_bambu_slot_and_undo(station3: Station) -> None:
    await act(station3, "sim.printer", printer="hotel", op="print", state="IDLE")
    result = await act(station3, "assign_lane", spool_id=97, printer="hotel", lane="3H-6")
    assert result["ok"] and result["message"] == "Assigned spool 97 to Heron 3H-6"
    assert hotel_lane(station3, "3H-6").spool_id == 97
    assert bambuddy_posts(station3)[-1] == {"spoolman_spool_id": 97, "printer_id": 1, "ams_id": 32, "tray_id": 5,
                                            "move": True}
    assert (await act(station3, "undo", activity_id=result["activity_id"]))["ok"]
    assert hotel_lane(station3, "3H-6").spool_id is None
