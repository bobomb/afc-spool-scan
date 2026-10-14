from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from station.scale.hidraw import HidrawScale
from station.scale.sim import SimScale
from station.scale.source import ABSENT, ScaleReading, ScaleSource, reading_from_report


def report(status: int, unit: int, exponent: int, raw: int) -> bytes:
    return bytes([3, status, unit, exponent & 0xFF, raw & 0xFF, raw >> 8])


def test_reading_from_report_maps_status_and_unit() -> None:
    assert reading_from_report(report(4, 2, 0, 984)) == ScaleReading(True, "stable", 984.0, "g")
    reading = reading_from_report(report(3, 11, -1, 125))
    assert reading.status == "motion"
    assert reading.source_unit == "oz"
    assert reading.grams == 354.4
    assert not reading.stable
    assert ScaleReading(True, "stable", 1.0, "g").stable
    assert not ABSENT.stable


async def test_publishes_changes_at_most_every_interval() -> None:
    published: list[ScaleReading] = []
    now = [0.0]
    source = ScaleSource(published.append, min_interval=0.05, clock=lambda: now[0])
    first = ScaleReading(True, "motion", 100.0, "g")
    source.update(first)
    assert published == [first]
    source.update(first)
    assert published == [first]
    second = ScaleReading(True, "motion", 200.0, "g")
    third = ScaleReading(True, "stable", 300.0, "g")
    source.update(second)
    source.update(third)
    assert published == [first]
    now[0] = 0.06
    await asyncio.sleep(0.08)
    assert published == [first, third]
    await source.stop()


async def test_reverting_before_flush_cancels_publish() -> None:
    published: list[ScaleReading] = []
    now = [0.0]
    source = ScaleSource(published.append, min_interval=0.05, clock=lambda: now[0])
    first = ScaleReading(True, "stable", 100.0, "g")
    source.update(first)
    source.update(ScaleReading(True, "motion", 101.0, "g"))
    source.update(first)
    await asyncio.sleep(0.08)
    assert published == [first]


async def test_wait_for_stable() -> None:
    source = ScaleSource(lambda reading: None, min_interval=0)
    source.update(ScaleReading(True, "motion", 10.0, "g"))
    waiter = asyncio.create_task(source.wait_for(lambda r: r.stable, 1.0))
    await asyncio.sleep(0.01)
    source.update(ScaleReading(True, "motion", 11.0, "g"))
    await asyncio.sleep(0.01)
    assert not waiter.done()
    source.update(ScaleReading(True, "stable", 984.0, "g"))
    assert (await waiter).grams == 984.0
    timed_out = await source.wait_for(lambda r: r.grams == 1.0, 0.02)
    assert timed_out.grams == 984.0


async def test_sim_scale_set_values() -> None:
    published: list[ScaleReading] = []
    scale = SimScale(published.append, min_interval=0)
    scale.start()
    await asyncio.sleep(0)
    assert scale.current == ScaleReading(True, "zero", 0.0, "g")
    assert scale.set(984.0) == ScaleReading(True, "stable", 984.0, "g")
    assert scale.set(12.5, unit="oz") == ScaleReading(True, "stable", 354.4, "oz")
    assert scale.set(status="motion") == ScaleReading(True, "motion", 354.4, "oz")
    assert scale.set(0) == ScaleReading(True, "zero", 0.0, "g")
    assert scale.set(status="absent") == ABSENT
    assert scale.set(status="over") == ScaleReading(True, "over", 0.0, "g")
    with pytest.raises(ValueError):
        scale.set(1, unit="lb")
    with pytest.raises(ValueError):
        scale.set(status="wobbly")
    assert published[-1].status == "over"
    await scale.stop()


class FakeDevice:
    def __init__(self, reports: list[bytes | Exception]) -> None:
        self.reports = reports
        self.opened = 0

    @contextlib.asynccontextmanager
    async def open(self, path: Path) -> AsyncIterator[AsyncIterator[bytes]]:
        self.opened += 1

        async def iterate() -> AsyncIterator[bytes]:
            for item in self.reports:
                await asyncio.sleep(0)
                if isinstance(item, Exception):
                    raise item
                yield item
            await asyncio.Event().wait()

        yield iterate()


async def test_hidraw_scale_reads_reports_and_reconnects() -> None:
    published: list[ScaleReading] = []
    attempts = {"n": 0}

    def finder(vendor: str, products: set[str]) -> Path:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("DYMO scale 0922:8003 was not found")
        return Path("/dev/hidraw0")

    device = FakeDevice([report(3, 2, 0, 500), b"\x01", report(4, 2, 0, 984), OSError("unplugged")])
    scale = HidrawScale(published.append, "0922", {"8003"}, finder=finder, opener=device.open,
                        retry_s=0.01, min_interval=0)
    scale.start()
    for _ in range(100):
        await asyncio.sleep(0.005)
        if device.opened >= 2:
            break
    await scale.stop()
    statuses = [reading.status for reading in published]
    assert statuses[:4] == ["absent", "motion", "stable", "absent"]
    assert published[2].grams == 984.0
    assert device.opened >= 2


async def test_hidraw_scale_permission_error_marks_absent() -> None:
    published: list[ScaleReading] = []

    @contextlib.asynccontextmanager
    async def denied(path: Path) -> AsyncIterator[AsyncIterator[bytes]]:
        raise PermissionError("denied")
        yield  # pragma: no cover

    scale = HidrawScale(published.append, "0922", {"8003"}, finder=lambda v, p: Path("/dev/hidraw0"),
                        opener=denied, retry_s=0.01, min_interval=0)
    scale.current = ScaleReading(True, "stable", 1.0, "g")
    scale.start()
    await asyncio.sleep(0.03)
    await scale.stop()
    assert published and published[-1] == ABSENT


@pytest.mark.skipif(sys.platform == "win32", reason="add_reader needs a selector loop on a POSIX fd")
async def test_open_hidraw_with_pipe() -> None:  # pragma: no cover - Linux only
    import os

    from station.scale.hidraw import open_hidraw

    read_fd, write_fd = os.pipe()
    path = Path(f"/proc/self/fd/{read_fd}")
    os.write(write_fd, report(4, 2, 0, 984))
    async with open_hidraw(path) as reports:
        assert await asyncio.wait_for(reports.__anext__(), 1) == report(4, 2, 0, 984)
    os.close(write_fd)
    os.close(read_fd)
