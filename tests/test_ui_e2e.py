"""End-to-end: the built station-ui drives the simulated service over IPC.

Skipped unless the UI has been built (ui/build/<preset>/...station-ui[.exe]).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from station.app import Station

REPO = Path(__file__).resolve().parent.parent
CANDIDATES = [
    REPO / "ui" / "build" / "windows" / "Release" / "station-ui.exe",
    REPO / "ui" / "build" / "windows" / "Debug" / "station-ui.exe",
    REPO / "ui" / "build" / "headless" / "station-ui",
    REPO / "ui" / "build" / "sdl" / "station-ui",
    REPO / "ui" / "build" / "pi" / "station-ui",
]


def find_ui() -> Path | None:
    override = os.environ.get("STATION_UI_EXE")
    if override:
        return Path(override)
    return next((path for path in CANDIDATES if path.exists()), None)


FLOW = """
request sim.scale {"grams": 640}
tap 300 76
type 97
key enter
wait 500
tap 646 394
wait 1200
shot weighed
tap 732 452
wait 1200
shot undone
screen printers
shot printers
"""


@pytest.mark.e2e
async def test_ui_confirmation_applies_to_the_original_spool(station: Station, tmp_path: Path) -> None:
    exe = find_ui()
    if exe is None:
        pytest.skip("station-ui is not built")
    script = tmp_path / "confirm.script"
    script.write_text(
        'request sim.scale {"grams": 984}\n'
        "tap 300 76\ntype 97\nkey enter\nwait 500\n"
        "tap 267 394\nwait 800\nshot confirm\n"
        'request set_setting {"key": "scan_mode", "value": "fill"}\n'
        'request sim.scan {"code": "web+spoolman:s-86"}\nwait 800\n'
        "tap 514 377\nwait 1000\nshot saved\n",
        encoding="utf-8",
    )
    process = await asyncio.create_subprocess_exec(
        str(exe), "--snapshot", str(tmp_path / "shots"), "--connect", "--port", str(station.ipc_port),
        "--script", str(script), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(process.communicate(), 90)
    assert process.returncode == 0, stderr.decode(errors="replace")
    spools = station.sim_spoolman.spools
    assert spools[97]["remaining_weight"] == pytest.approx(984 - 180)
    assert spools[86]["remaining_weight"] == pytest.approx(74.2)
    assert [(e["action"], e["spool_id"]) for e in station.store.activity] == [("weigh", 97)]


@pytest.mark.e2e
async def test_ui_lane_assignment_needs_explicit_confirm(station: Station, tmp_path: Path) -> None:
    exe = find_ui()
    if exe is None:
        pytest.skip("station-ui is not built")
    script = tmp_path / "assign.script"
    script.write_text(
        "tap 300 76\ntype 97\nkey enter\nwait 400\n"
        "screen printers\ntap 260 328\nwait 400\nshot dialog\n"
        "tap 196 404\nwait 500\n"
        "tap 260 328\nwait 400\ntap 554 404\nwait 800\n",
        encoding="utf-8",
    )
    process = await asyncio.create_subprocess_exec(
        str(exe), "--snapshot", str(tmp_path / "shots"), "--connect", "--port", str(station.ipc_port),
        "--script", str(script), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(process.communicate(), 90)
    assert process.returncode == 0, stderr.decode(errors="replace")
    assert (tmp_path / "shots" / "dialog.png").exists()
    assert station.sim_printers.printers["kilo"].gcode_log == ["SET_SPOOL_ID LANE=lane4 SPOOL_ID=97"]
    assert [entry["action"] for entry in station.store.activity] == ["assign_lane"]


@pytest.mark.e2e
async def test_ui_numpad_clear_deselects_the_spool(station: Station, tmp_path: Path) -> None:
    exe = find_ui()
    if exe is None:
        pytest.skip("station-ui is not built")
    script = tmp_path / "clear.script"
    script.write_text(
        'request sim.scale {"grams": 640}\n'
        "tap 300 76\ntype 97\nkey enter\nwait 600\nshot selected\n"
        "tap 300 76\nwait 300\ntap 280 398\nwait 300\ntap 560 52\nwait 600\nshot cleared\n"
        "tap 267 394\nwait 600\n",
        encoding="utf-8",
    )
    process = await asyncio.create_subprocess_exec(
        str(exe), "--snapshot", str(tmp_path / "shots"), "--connect", "--port", str(station.ipc_port),
        "--script", str(script), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(process.communicate(), 90)
    assert process.returncode == 0, stderr.decode(errors="replace")
    assert station.store.spool is None and station.store.scale.check is None
    assert station.store.activity == []
    assert station.sim_spoolman.spools[97]["used_weight"] == pytest.approx(545.3)


@pytest.mark.e2e
async def test_ui_load_goes_to_both_printers_and_sleep_resets(station: Station, tmp_path: Path) -> None:
    exe = find_ui()
    if exe is None:
        pytest.skip("station-ui is not built")
    script = tmp_path / "sleep.script"
    script.write_text(
        "tap 300 76\ntype 93\nkey enter\nwait 500\n"
        "tap 614 200\nwait 300\n"
        "tap 425 394\nwait 900\nshot loaded\n"
        "idle off\nwait 900\nidle wake\nwait 300\nshot woken\n",
        encoding="utf-8",
    )
    process = await asyncio.create_subprocess_exec(
        str(exe), "--snapshot", str(tmp_path / "shots"), "--connect", "--port", str(station.ipc_port),
        "--script", str(script), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(process.communicate(), 90)
    assert process.returncode == 0, stderr.decode(errors="replace")
    actions = [(e["action"], e["spool_id"]) for e in station.store.activity]
    assert actions == [("sleep", None), ("load", 93)]
    assert station.store.activity[1]["printers"] == ["Kestrel", "Yeti"]
    assert station.store.spool is None
    assert station.sim_printers.printers["kilo"].next_spool_id is None
    assert station.sim_printers.printers["yankee"].next_spool_id is None
    assert all(p.pending_spool is None for p in station.store.printers.values())


@pytest.mark.e2e
async def test_ui_weigh_load_and_undo(station: Station, tmp_path: Path) -> None:
    exe = find_ui()
    if exe is None:
        pytest.skip("station-ui is not built")
    script = tmp_path / "flow.script"
    script.write_text(FLOW, encoding="utf-8")
    shots = tmp_path / "shots"
    process = await asyncio.create_subprocess_exec(
        str(exe), "--snapshot", str(shots), "--connect", "--port", str(station.ipc_port),
        "--script", str(script), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), 90)
    assert process.returncode == 0, stderr.decode(errors="replace")

    actions = [(entry["action"], entry["undone"]) for entry in station.store.activity]
    assert actions == [("undo", False), ("weigh_load", True)]
    assert station.sim_spoolman.spools[97]["used_weight"] == pytest.approx(545.3)
    assert station.sim_printers.printers["kilo"].next_spool_id is None
    for name in ("weighed", "undone", "printers"):
        data = (shots / f"{name}.png").read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(data) > 800 * 480 * 3
    assert "weighed.png" in stdout.decode()
