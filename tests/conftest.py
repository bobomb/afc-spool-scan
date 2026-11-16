from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from station.app import Station
from station.config import DEFAULT_PRINTERS, Config, parse_printers


async def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


class RecordingCues:
    def __init__(self) -> None:
        self.played: list[str] = []

    def play(self, cue: str) -> None:
        self.played.append(cue)


def sim_config(state_dir: Path, **overrides: object) -> Config:
    values = dict(
        hardware="sim", printers_mode="sim", spoolman_mode="sim", writes=False, ipc_port=0,
        state_dir=state_dir, printers=parse_printers(DEFAULT_PRINTERS), scale_read_timeout_s=0.2,
    )
    values.update(overrides)
    return Config(**values)  # type: ignore[arg-type]


@pytest.fixture
async def station(tmp_path: Path):  # noqa: ANN201
    station = Station(sim_config(tmp_path), printer_backoff=(0.02, 0.05), publish_delay=0,
                      scale_interval=0, countdown_tick_s=0.01)
    await station.start()
    await wait_until(lambda: all(p.connected for p in station.store.printers.values()))
    await wait_until(lambda: not station.catalog.busy)  # type: ignore[union-attr]
    cues = RecordingCues()
    station.actions.cues = cues  # type: ignore[union-attr]
    station.cues = cues  # type: ignore[attr-defined]
    yield station
    await station.stop()


THREE_PRINTERS = DEFAULT_PRINTERS + ",Hotel=bambuddy:1"
FAST_BAMBUDDY = {"insert_settle_s": 0.05, "settings_check_s": 0.05, "usage_refresh_s": 0.05}


@pytest.fixture
async def station3(tmp_path: Path):  # noqa: ANN201
    """Kilo and Yankee (Moonraker) plus Hotel, a Bambu H3C behind the simulated Bambuddy."""
    station = Station(sim_config(tmp_path, printers=parse_printers(THREE_PRINTERS)), printer_backoff=(0.02, 0.05),
                      publish_delay=0, scale_interval=0, countdown_tick_s=0.01, bambuddy_options=FAST_BAMBUDDY)
    await station.start()
    await wait_until(lambda: all(p.connected for p in station.store.printers.values()))
    await wait_until(lambda: not station.catalog.busy)  # type: ignore[union-attr]
    cues = RecordingCues()
    station.actions.cues = cues  # type: ignore[union-attr]
    station.cues = cues  # type: ignore[attr-defined]
    yield station
    await station.stop()
