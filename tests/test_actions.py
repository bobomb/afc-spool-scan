from __future__ import annotations

import asyncio
from typing import Any

import pytest

from conftest import wait_until

from station.app import Station
from station.spoolman import SpoolmanError


async def act(station: Station, action: str, **args: Any) -> dict[str, Any]:
    return await station.actions.handle(action, args)  # type: ignore[union-attr]


def sim_spool(station: Station, spool_id: int) -> dict[str, Any]:
    return station.sim_spoolman.spools[spool_id]  # type: ignore[union-attr]


def sim_printer(station: Station, key: str):  # noqa: ANN201
    return station.sim_printers.printers[key]  # type: ignore[union-attr]


async def set_scale(station: Station, grams: float | None = None, status: str | None = None) -> None:
    await act(station, "sim.scale", **({"grams": grams} if grams is not None else {}),
              **({"status": status} if status else {}))


async def test_unknown_action_and_invalid_args(station: Station) -> None:
    assert (await act(station, "fly"))["code"] == "invalid_args"
    for args in ({}, {"spool_id": "abc"}, {"spool_id": 0}, {"spool_id": True}, {"spool_id": -4}):
        assert (await act(station, "lookup", **args))["code"] == "invalid_args"
    assert (await act(station, "weigh", spool_id=97, confirm="yes"))["code"] == "invalid_args"
    assert (await act(station, "load", spool_id=97, target="prusa"))["code"] == "invalid_args"


async def test_lookup_publishes_spool(station: Station) -> None:
    result = await act(station, "lookup", spool_id="97")
    assert result == {"ok": True, "message": "Spool 97: Sunlu ABS White"}
    spool = station.store.spool
    assert spool.id == 97 and spool.expected_gross_g == 634.7 and spool.found
    missing = await act(station, "lookup", spool_id=999)
    assert missing["code"] == "not_found"
    assert station.store.spool.found is False and station.store.spool.id == 999


@pytest.mark.parametrize(
    ("grams", "status", "code"),
    [(None, "absent", "scale_unavailable"), (30.0, None, "below_minimum"), (0, None, "below_minimum"),
     (500.0, "motion", "scale_unstable"), (500.0, "over", "scale_unavailable")],
)
async def test_weigh_requires_stable_weight(station: Station, grams: float | None, status: str | None,
                                            code: str) -> None:
    await set_scale(station, grams, status)
    result = await act(station, "weigh", spool_id=97)
    assert result["code"] == code
    assert station.cues.played == ["error"]
    assert sim_spool(station, 97)["used_weight"] == 545.3
    assert station.store.activity == []


async def test_weigh_waits_for_settling_scale(station: Station) -> None:
    await set_scale(station, 640.0, "motion")
    task = asyncio.create_task(act(station, "weigh", spool_id=97))
    await asyncio.sleep(0.05)
    await set_scale(station, 640.0)
    result = await task
    assert result["ok"] is True


async def test_weigh_saves_and_undo_restores(station: Station) -> None:
    await set_scale(station, 640.0)
    result = await act(station, "weigh", spool_id=97)
    assert result["ok"] is True and result["message"] == "Spool 97: 640 g saved"
    assert sim_spool(station, 97)["remaining_weight"] == pytest.approx(460.0)
    assert station.store.spool.remaining_g == 460.0
    assert station.cues.played == ["weigh", "success"]
    entry = station.store.activity[0]
    assert entry["id"] == result["activity_id"] and entry["undoable"] and entry["action"] == "weigh"

    undo = await act(station, "undo", activity_id=result["activity_id"])
    assert undo["ok"] is True and undo["message"] == "Undid weigh of spool 97"
    assert sim_spool(station, 97)["used_weight"] == pytest.approx(545.3)
    assert station.store.spool.remaining_g == 454.7
    assert station.store.activity[1]["undone"] is True and not station.store.activity[1]["undoable"]
    again = await act(station, "undo", activity_id=result["activity_id"])
    assert again["code"] == "invalid_args"
    assert (await act(station, "undo", activity_id="a-999"))["code"] == "invalid_args"


async def test_weigh_sanity_check_needs_confirm(station: Station) -> None:
    await set_scale(station, 984.0)
    result = await act(station, "weigh", spool_id=97)
    assert result["ok"] is False and result["code"] == "needs_confirm"
    assert result["data"]["delta_g"] == 349.3 and result["data"]["expected_g"] == 634.7
    assert station.cues.played == []
    assert sim_spool(station, 97)["used_weight"] == 545.3
    confirmed = await act(station, "weigh", spool_id=97, confirm=True)
    assert confirmed["ok"] is True
    assert sim_spool(station, 97)["remaining_weight"] == pytest.approx(984 - 180)


async def test_weigh_reset_initial_weight_is_undone(station: Station) -> None:
    await set_scale(station, 1300.0)
    result = await act(station, "weigh", spool_id=97, confirm=True)
    assert sim_spool(station, 97)["initial_weight"] == 1120.0
    await act(station, "undo", activity_id=result["activity_id"])
    assert sim_spool(station, 97)["initial_weight"] == 1000.0
    assert sim_spool(station, 97)["used_weight"] == pytest.approx(545.3)


async def test_weigh_tare_unknown_and_spoolman_errors(station: Station) -> None:
    await set_scale(station, 900.0)
    result = await act(station, "weigh", spool_id=99)
    assert result["ok"] is True and "(tare unknown)" in result["message"]
    failed = await act(station, "weigh", spool_id=100)
    assert failed["code"] == "spoolman_error" and "Initial weight is not set" in failed["message"]
    assert station.store.activity[0]["ok"] is False
    assert (await act(station, "weigh", spool_id=999))["code"] == "not_found"


async def test_weigh_dry_run_when_writes_off(station: Station) -> None:
    station.spoolman.writes = False
    await set_scale(station, 640.0)
    result = await act(station, "weigh", spool_id=97)
    assert result["ok"] is True and result["dry_run"] is True
    assert result["message"] == "Spool 97: Dry run: would save 640 g"
    assert sim_spool(station, 97)["used_weight"] == 545.3
    assert station.store.activity[0]["dry_run"] and not station.store.activity[0]["undoable"]
    assert station.cues.played == ["success"]


async def test_load_both_and_undo(station: Station) -> None:
    kilo, yankee = sim_printer(station, "kilo"), sim_printer(station, "yankee")
    await act(station, "load", spool_id=84, target="yankee")
    result = await act(station, "load", spool_id=97)
    assert result["ok"] is True
    assert result["message"] == "Spool 97: next spool set on Kilo, Yankee"
    assert kilo.next_spool_id == 97 and yankee.next_spool_id == 97
    printers = station.store.printers
    assert printers["kilo"].pending_spool == 97 and printers["kilo"].pending_confirmed
    assert station.store.spool.id == 97
    await act(station, "undo", activity_id=result["activity_id"])
    assert kilo.next_spool_id is None and yankee.next_spool_id == 84
    assert station.store.printers["yankee"].pending_spool == 84


async def test_load_single_target_and_setting_default(station: Station) -> None:
    await act(station, "set_setting", key="target", value="kilo")
    result = await act(station, "load", spool_id=97)
    assert result["message"] == "Spool 97: next spool set on Kilo"
    assert sim_printer(station, "yankee").next_spool_id is None
    explicit = await act(station, "load", spool_id=90, target="YANKEE")
    assert explicit["ok"] and sim_printer(station, "yankee").next_spool_id == 90
    listed = await act(station, "load", spool_id=86, target="yankee,kilo")
    assert listed["message"] == "Spool 86: next spool set on Kilo, Yankee"
    await act(station, "set_setting", key="target", value="yankee,kilo")
    assert station.store.settings["target"] == "both"
    assert (await act(station, "load", spool_id=97, target="kilo,prusa"))["code"] == "invalid_args"


async def test_lanes_carry_remaining_percent_and_colours(station: Station) -> None:
    def lane(printer: str, index: int):  # noqa: ANN202
        return station.store.printers[printer].lanes[index]

    await wait_until(lambda: lane("kilo", 0).remaining_pct is not None)
    first = lane("kilo", 0)
    spool = sim_spool(station, first.spool_id)
    initial = spool.get("initial_weight") or spool["filament"]["weight"]
    assert first.remaining_pct == round(first.remaining_g / initial * 100, 1)
    assert first.colors == [first.color]
    empty = next(item for item in station.store.printers["kilo"].lanes if item.spool_id is None)
    assert empty.remaining_pct is None and empty.colors == []
    data = station.store.snapshot()["printers"][0]["lanes"][0]
    assert {"remaining_pct", "colors"} <= set(data)


async def test_lookup_publishes_all_colours(station: Station) -> None:
    await act(station, "lookup", spool_id=93)
    assert station.store.spool.colors == ["#C94CE0", "#33B5E5", "#F2C14E"]
    assert station.store.spool.color == "#C94CE0"


async def test_printer_going_offline_clears_its_pending_spool(station: Station) -> None:
    await act(station, "load", spool_id=97)
    printers = station.store.printers
    assert printers["kilo"].pending_spool == 97 and printers["yankee"].pending_spool == 97
    await act(station, "sim.printer", printer="yankee", op="disconnect")
    await wait_until(lambda: not station.store.printers["yankee"].connected)
    assert station.store.printers["yankee"].pending_spool is None
    assert station.store.printers["kilo"].pending_spool == 97
    await act(station, "sim.printer", printer="yankee", op="connect")
    await wait_until(lambda: station.store.printers["yankee"].connected, timeout=5)
    assert station.store.printers["yankee"].pending_spool is None


async def test_load_partial_failure_when_printer_offline(station: Station) -> None:
    await act(station, "sim.printer", printer="yankee", op="disconnect")
    await wait_until(lambda: not station.store.printers["yankee"].connected)
    result = await act(station, "load", spool_id=97)
    assert result["ok"] is False and result["code"] == "printer_offline"
    assert result["message"] == "Spool 97: next spool set on Kilo; Yankee: offline"
    assert station.cues.played[-1] == "error"
    assert station.store.activity[0]["undoable"]
    await act(station, "sim.printer", printer="yankee", op="connect")
    await wait_until(lambda: station.store.printers["yankee"].connected)


async def test_load_rejects_unknown_spool_but_tolerates_spoolman_outage(station: Station) -> None:
    assert (await act(station, "load", spool_id=999))["code"] == "not_found"
    assert sim_printer(station, "kilo").next_spool_id is None
    await act(station, "sim.spoolman", online=False)
    result = await act(station, "load", spool_id=97)
    assert result["ok"] is True
    assert station.store.health.spoolman is False


async def test_weigh_load_from_ui(station: Station) -> None:
    result = await act(station, "weigh_load", spool_id=97)
    assert result["code"] == "below_minimum"
    assert sim_printer(station, "kilo").next_spool_id is None
    await set_scale(station, 640.0)
    result = await act(station, "weigh_load", spool_id=97, target="kilo")
    assert result["ok"] is True
    assert result["message"] == "Spool 97: 640 g saved; next spool set on Kilo"
    assert station.cues.played[-2:] == ["weigh", "success"]
    await act(station, "undo", activity_id=result["activity_id"])
    assert sim_spool(station, 97)["used_weight"] == pytest.approx(545.3)
    assert sim_printer(station, "kilo").next_spool_id is None


async def test_clear_pending_and_undo(station: Station) -> None:
    await act(station, "load", spool_id=97, target="kilo")
    result = await act(station, "clear_pending", printer="Kilo")
    assert result["ok"] and result["message"] == "Cleared next spool on Kilo"
    assert sim_printer(station, "kilo").next_spool_id is None
    assert station.store.printers["kilo"].pending_spool is None
    await act(station, "undo", activity_id=result["activity_id"])
    assert sim_printer(station, "kilo").next_spool_id == 97
    assert (await act(station, "clear_pending", printer="nope"))["code"] == "invalid_args"


async def test_assign_lane_and_undo(station: Station) -> None:
    result = await act(station, "assign_lane", spool_id=97, printer="kilo", lane="lane4")
    assert result["ok"] and result["message"] == "Assigned spool 97 to Kilo lane4"
    await wait_until(lambda: station.store.printers["kilo"].lanes[3].spool_id == 97)
    assert station.store.printers["kilo"].lanes[3].material == "ABS"
    duplicate = await act(station, "assign_lane", spool_id=97, printer="kilo", lane="lane1")
    assert duplicate["code"] == "invalid_args" and "already in lane4" in duplicate["message"]
    await act(station, "undo", activity_id=result["activity_id"])
    await wait_until(lambda: station.store.printers["kilo"].lanes[3].spool_id is None)
    replaced = await act(station, "assign_lane", spool_id=97, printer="kilo", lane="lane1")
    await wait_until(lambda: station.store.printers["kilo"].lanes[0].spool_id == 97)
    await act(station, "undo", activity_id=replaced["activity_id"])
    await wait_until(lambda: station.store.printers["kilo"].lanes[0].spool_id == 84)
    assert (await act(station, "assign_lane", spool_id=97, printer="kilo", lane="lane9"))["code"] == "invalid_args"
    assert (await act(station, "assign_lane", spool_id=999, printer="kilo", lane="lane4"))["code"] == "not_found"


async def test_assign_lane_offline(station: Station) -> None:
    await act(station, "sim.printer", printer="kilo", op="disconnect")
    await wait_until(lambda: not station.store.printers["kilo"].connected)
    result = await act(station, "assign_lane", spool_id=97, printer="kilo", lane="lane4")
    assert result["code"] == "printer_offline"


async def test_empty_spool(station: Station) -> None:
    await set_scale(station, 8.0)
    assert (await act(station, "empty_spool", spool_id=97))["code"] == "below_minimum"
    await set_scale(station, 640.0)
    warn = await act(station, "empty_spool", spool_id=97)
    assert warn["code"] == "needs_confirm" and "should weigh about 180 g" in warn["message"]
    await set_scale(station, 176.5)
    result = await act(station, "empty_spool", spool_id=97)
    assert result["ok"] and result["message"] == "Spool 97: empty 176.5 g set as spool + filament tare; archived"
    spool = sim_spool(station, 97)
    assert (spool["spool_weight"], spool["remaining_weight"], spool["archived"]) == (176.5, 0.0, True)
    assert spool["filament"]["spool_weight"] == 176.5
    assert ("PATCH", "/api/v1/filament/11", {"spool_weight": 176.5}) in station.sim_spoolman.requests  # type: ignore[union-attr]
    assert station.store.spool.archived is True
    assert station.cues.played[-1] == "success"
    await act(station, "undo", activity_id=result["activity_id"])
    spool = sim_spool(station, 97)
    assert (spool["spool_weight"], spool["archived"]) == (180.0, False)
    assert spool["filament"]["spool_weight"] == 180.0
    assert spool["remaining_weight"] == pytest.approx(454.7)


async def test_empty_spool_sets_unset_filament_tare_and_undo_unsets_it(station: Station) -> None:
    await set_scale(station, 245.0)
    result = await act(station, "empty_spool", spool_id=92)
    assert result["ok"] and sim_spool(station, 92)["filament"]["spool_weight"] == 245.0
    assert station.actions.activity.get(result["activity_id"]).undo[-1].fields == {"spool_weight": None}
    await act(station, "undo", activity_id=result["activity_id"])
    assert sim_spool(station, 92)["filament"]["spool_weight"] is None
    assert sim_spool(station, 92)["spool_weight"] is None


async def test_empty_spool_skips_filament_already_at_that_tare(station: Station) -> None:
    await set_scale(station, 157.0)
    result = await act(station, "empty_spool", spool_id=84)
    assert result["message"] == "Spool 84: empty 157 g set as spool + filament tare; archived"
    assert not [r for r in station.sim_spoolman.requests if r[1].startswith("/api/v1/filament")]  # type: ignore[union-attr]
    assert [step.kind for step in station.actions.activity.get(result["activity_id"]).undo] == ["spool_patch"]


async def test_empty_spool_reports_filament_failure(station: Station, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise SpoolmanError("Spoolman error 500: boom", 500)

    monkeypatch.setattr(station.spoolman, "patch_filament", fail)
    await set_scale(station, 176.5)
    result = await act(station, "empty_spool", spool_id=97)
    assert result["ok"] is False and result["code"] == "spoolman_error"
    assert result["message"] == ("Spool 97: empty 176.5 g set as spool tare; archived; "
                                 "filament tare not updated: Spoolman error 500: boom")
    assert sim_spool(station, 97)["archived"] is True and sim_spool(station, 97)["filament"]["spool_weight"] == 180.0
    assert station.cues.played[-1] == "error"
    entry = station.actions.activity.get(result["activity_id"])
    assert [step.kind for step in entry.undo] == ["spool_patch"] and station.store.activity[0]["undoable"]
    assert (await act(station, "undo", activity_id=entry.id))["ok"] is True
    assert sim_spool(station, 97)["archived"] is False


async def test_empty_spool_dry_run_when_writes_off(station: Station) -> None:
    station.spoolman.writes = False
    await set_scale(station, 176.5)
    before = len(station.sim_spoolman.requests)  # type: ignore[union-attr]
    result = await act(station, "empty_spool", spool_id=97)
    assert result["ok"] and result["dry_run"]
    assert result["message"] == "Spool 97: Dry run: would set 176.5 g as spool + filament tare and archive"
    assert [r[0] for r in station.sim_spoolman.requests[before:]] == ["GET"]  # type: ignore[union-attr]
    assert sim_spool(station, 97)["filament"]["spool_weight"] == 180.0


async def test_clear_spool_deselects_and_resets_scale_check(station: Station) -> None:
    await set_scale(station, 640.0)
    await act(station, "lookup", spool_id=97)
    assert station.store.scale.check == "ok" and station.store.scale.tare_g == 180.0
    result = await act(station, "clear_spool")
    assert result == {"ok": True, "message": "Spool cleared"}
    assert station.store.spool is None
    scale = station.store.scale
    assert (scale.check, scale.tare_g, scale.expected_g, scale.grams) == (None, None, None, 640.0)
    assert (await act(station, "clear_spool"))["ok"] is True
    assert station.store.activity == [] and station.cues.played == []
    assert sim_spool(station, 97)["used_weight"] == 545.3


async def test_set_setting_side_effects(station: Station) -> None:
    await act(station, "lookup", spool_id=97)
    assert station.store.spool.low_stock is False
    result = await act(station, "set_setting", key="low_stock_g", value=500)
    assert result["ok"] and station.store.settings["low_stock_g"] == 500
    assert station.store.spool.low_stock is True
    await wait_until(lambda: station.store.printers["yankee"].lanes[1].low_stock)
    assert (await act(station, "set_setting", key="theme", value="neon"))["code"] == "invalid_args"
    assert (await act(station, "set_setting", value=1))["code"] == "invalid_args"
    await act(station, "set_setting", key="undo_depth", value=1)
    await set_scale(station, 640.0)
    first = await act(station, "weigh", spool_id=97)
    second = await act(station, "weigh", spool_id=97)
    assert not station.actions.activity.is_undoable(station.actions.activity.get(first["activity_id"]))
    assert station.store.activity[0]["id"] == second["activity_id"] and station.store.activity[0]["undoable"]


async def test_settings_and_activity_persist(station: Station, tmp_path) -> None:  # noqa: ANN001
    await act(station, "set_setting", key="scan_mode", value="fill")
    await act(station, "load", spool_id=97)
    assert (tmp_path / "settings.json").exists()
    assert (tmp_path / "activity.jsonl").read_text(encoding="utf-8").count("\n") == 1


async def test_default_paths_only_set_next_spool(station: Station) -> None:
    await set_scale(station, 640.0)
    await act(station, "weigh_load", spool_id=97)
    await act(station, "load", spool_id=90)
    await act(station, "clear_pending", printer="kilo")
    expected = len(station.store.activity)
    for mode in ("immediate", "countdown"):
        await act(station, "set_setting", key="scan_mode", value=mode)
        await act(station, "sim.scan", code="web+spoolman:s-84")
        expected += 1
        await wait_until(lambda: len(station.store.activity) == expected)
    lookups = lambda: sum(path == "/api/v1/spool/84" for _, path, _ in station.sim_spoolman.requests)  # noqa: E731
    before = lookups()
    await act(station, "set_setting", key="scan_mode", value="fill")
    await act(station, "sim.scan", code="web+spoolman:s-84")
    await wait_until(lambda: lookups() > before)
    await asyncio.sleep(0.05)
    assert station.store.activity[0]["action"] == "scan"
    for key in ("kilo", "yankee"):
        log = sim_printer(station, key).gcode_log
        assert log and all(line.startswith("SET_NEXT_SPOOL_ID") for line in log), log
    await act(station, "assign_lane", spool_id=97, printer="kilo", lane="lane4")
    assert sim_printer(station, "kilo").gcode_log[-1] == "SET_SPOOL_ID LANE=lane4 SPOOL_ID=97"


async def test_undo_with_writes_off_is_a_dry_run(station: Station) -> None:
    await set_scale(station, 640.0)
    result = await act(station, "weigh", spool_id=97)
    station.spoolman.writes = False
    undo = await act(station, "undo", activity_id=result["activity_id"])
    assert undo["ok"] is True and undo["dry_run"] is True
    assert undo["message"] == "Dry run: would undo weigh"
    assert sim_spool(station, 97)["remaining_weight"] == pytest.approx(460.0)
    assert station.actions.activity.get(result["activity_id"]).undone is False
    station.spoolman.writes = True
    assert (await act(station, "undo", activity_id=result["activity_id"]))["ok"] is True
    assert sim_spool(station, 97)["used_weight"] == pytest.approx(545.3)


async def test_entries_from_another_mode_are_not_undoable(station: Station) -> None:
    await set_scale(station, 640.0)
    result = await act(station, "weigh", spool_id=97)
    log = station.actions.activity
    entry = log.get(result["activity_id"])
    assert entry.mode == log.mode and log.is_undoable(entry)
    entry.mode = "printers=live:w,spoolman=live:w"
    assert not log.is_undoable(entry)
    assert (await act(station, "undo", activity_id=entry.id))["code"] == "invalid_args"
    assert sim_spool(station, 97)["remaining_weight"] == pytest.approx(460.0)


async def test_printer_timeouts_are_recorded_with_undo(station: Station, monkeypatch: pytest.MonkeyPatch) -> None:
    kilo = station.printers.get("kilo")

    async def no_reply(*args: Any, **kwargs: Any) -> Any:
        raise asyncio.TimeoutError

    await act(station, "load", spool_id=97, target="kilo")
    monkeypatch.setattr(kilo, "call", no_reply)
    cleared = await act(station, "clear_pending", printer="kilo")
    assert cleared["ok"] is False and cleared["code"] == "printer_error"
    assert "may still apply" in cleared["message"]
    assert station.store.activity[0]["undoable"]
    assigned = await act(station, "assign_lane", spool_id=97, printer="kilo", lane="lane4")
    assert assigned["code"] == "printer_error" and assigned["activity_id"]
    assert station.store.activity[0]["action"] == "assign_lane" and station.store.activity[0]["undoable"]
    loaded = await act(station, "load", spool_id=90, target="kilo")
    assert loaded["code"] == "printer_error" and station.store.activity[0]["undoable"]


async def test_disconnecting_client_does_not_abort_a_write(station: Station,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    kilo = station.printers.get("kilo")
    original = kilo.set_next_spool

    async def slow(spool_id: int | None) -> Any:
        await asyncio.sleep(0.3)
        return await original(spool_id)

    monkeypatch.setattr(kilo, "set_next_spool", slow)
    await set_scale(station, 640.0)
    reader, writer = await asyncio.open_connection("127.0.0.1", station.ipc_port)
    await reader.readline()
    await reader.readline()
    request = {"type": "request", "id": "x", "action": "weigh_load", "args": {"spool_id": 97, "target": "kilo"}}
    writer.write((json.dumps(request) + "\n").encode())
    await writer.drain()
    await asyncio.sleep(0.1)
    writer.close()
    await wait_until(lambda: bool(station.store.activity))
    assert station.store.activity[0]["action"] == "weigh_load" and station.store.activity[0]["ok"]
    assert sim_printer(station, "kilo").next_spool_id == 97


async def test_sim_actions_validate(station: Station) -> None:
    assert (await act(station, "sim.scale", grams="heavy"))["code"] == "invalid_args"
    assert (await act(station, "sim.scale", status="wobbly"))["code"] == "invalid_args"
    assert (await act(station, "sim.scan"))["code"] == "invalid_args"
    assert (await act(station, "sim.printer", printer="kilo", op="explode"))["code"] == "invalid_args"
    assert (await act(station, "sim.printer", printer="kilo", op="lane", lane="lane9"))["code"] == "invalid_args"
    assert (await act(station, "sim.printer", printer="nobody", op="connect"))["code"] == "invalid_args"
    assert (await act(station, "sim.spoolman", online="no"))["code"] == "invalid_args"
    assert (await act(station, "sim.nothing"))["code"] == "invalid_args"
    ok = await act(station, "sim.printer", printer="kilo", op="print", state="printing", progress=0.5)
    assert ok["ok"]
    await wait_until(lambda: station.store.printers["kilo"].progress == 0.5)
    await act(station, "sim.printer", printer="kilo", op="error", message="Jam")
    await wait_until(lambda: station.store.printers["kilo"].afc_error == "Jam")
    await act(station, "sim.printer", printer="kilo", op="clear_error")
    await act(station, "sim.printer", printer="kilo", op="lane", lane="lane4", spool_id=93, status="Loaded")
    await wait_until(lambda: station.store.printers["kilo"].lanes[3].color == "#C94CE0")
    await act(station, "sim.printer", printer="kilo", op="eject", lane="lane4")
    await wait_until(lambda: station.store.printers["kilo"].lanes[3].spool_id is None)
