from __future__ import annotations

from typing import Any

from conftest import wait_until

from station.app import Station


async def act(station: Station, action: str, **args: Any) -> dict[str, Any]:
    return await station.actions.handle(action, args)  # type: ignore[union-attr]


async def test_immediate_scan_weighs_and_loads(station: Station) -> None:
    await act(station, "sim.scale", grams=640.0)
    await act(station, "sim.scan", code="WEB+SPOOLMAN:S-97")
    await wait_until(lambda: station.store.activity and station.store.activity[0]["action"] == "scan")
    entry = station.store.activity[0]
    assert entry["ok"] and entry["message"] == "640 g saved; next spool set on Kestrel, Yeti"
    assert station.store.scan.last_code == "WEB+SPOOLMAN:S-97" and station.store.scan.spool_id == 97
    assert station.cues.played == ["weigh", "success"]
    assert station.sim_printers.printers["kilo"].next_spool_id == 97


async def test_immediate_scan_without_weight_still_loads(station: Station) -> None:
    await act(station, "sim.scan", code="web+spoolman:s-84")
    await wait_until(lambda: bool(station.store.activity))
    entry = station.store.activity[0]
    assert entry["ok"] is True
    assert entry["message"] == "weight not saved (scale is empty); next spool set on Kestrel, Yeti"
    assert station.cues.played == ["success"]


async def test_immediate_scan_sanity_warning_prompts(station: Station) -> None:
    await act(station, "sim.scale", grams=984.0)
    await act(station, "sim.scan", code="web+spoolman:s-97")
    await wait_until(lambda: bool(station.store.activity))
    assert "weight not saved (needs confirmation)" in station.store.activity[0]["message"]
    prompt = station.store.scan.prompt
    assert prompt is not None and prompt.kind == "confirm_weigh" and prompt.delta_g == 349.3
    result = await act(station, "weigh", spool_id=97, confirm=True)
    assert result["ok"] and station.store.scan.prompt is None
    await act(station, "sim.scan", code="web+spoolman:s-97")
    await wait_until(lambda: station.store.scan.prompt is not None or len(station.store.activity) > 2)
    await act(station, "dismiss_prompt")
    assert station.store.scan.prompt is None


async def test_unknown_spool_scan_is_an_error(station: Station) -> None:
    await act(station, "sim.scan", code="web+spoolman:s-999")
    await wait_until(lambda: station.cues.played == ["error"])
    assert station.sim_printers.printers["kilo"].next_spool_id is None


async def test_unrecognized_code_is_ignored(station: Station) -> None:
    await act(station, "sim.scan", code="hello world")
    await wait_until(lambda: station.store.scan.last_code == "hello world")
    assert station.store.scan.spool_id is None
    assert station.store.activity == [] and station.cues.played == []


async def test_countdown_mode_runs_weigh_load(station: Station) -> None:
    await act(station, "set_setting", key="scan_mode", value="countdown")
    seen: list[int] = []
    station.store.subscribe(
        lambda topic, data: seen.append(data["countdown"]["remaining_s"])
        if topic == "scan" and data["countdown"] else None
    )
    await act(station, "sim.scale", grams=640.0)
    await act(station, "sim.scan", code="web+spoolman:s-97")
    await wait_until(lambda: bool(station.store.activity))
    assert seen == [5, 4, 3, 2, 1]
    assert station.store.scan.countdown is None
    assert station.store.activity[0]["message"].startswith("640 g saved")


async def test_countdown_can_be_cancelled(station: Station) -> None:
    await act(station, "set_setting", key="scan_mode", value="countdown")
    station.scan_flow.tick_s = 0.5
    await act(station, "sim.scan", code="web+spoolman:s-97")
    await wait_until(lambda: station.store.scan.countdown is not None)
    assert station.store.spool.id == 97
    result = await act(station, "cancel_countdown")
    assert result["message"] == "Countdown cancelled"
    assert station.store.scan.countdown is None
    assert (await act(station, "cancel_countdown"))["message"] == "No countdown running"
    assert station.store.activity == []


async def test_fill_mode_only_looks_up(station: Station) -> None:
    await act(station, "set_setting", key="scan_mode", value="fill")
    await act(station, "sim.scale", grams=640.0)
    await act(station, "sim.scan", code="web+spoolman:s-86")
    await wait_until(lambda: station.store.spool is not None and station.store.spool.id == 86)
    assert station.store.spool.low_stock is True
    assert station.store.activity == []
    assert station.sim_printers.printers["kilo"].next_spool_id is None
