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
type 97
key enter
wait 500
tap 554 332
wait 1200
shot weighed
tap 732 452
wait 1200
shot undone
screen printers
shot printers
"""


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
