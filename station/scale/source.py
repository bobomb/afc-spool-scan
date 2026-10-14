"""Scale readings, change publishing (max ~5 Hz) and waiting for stable weight."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass

from .dymo import decode_reading


@dataclass(frozen=True)
class ScaleReading:
    present: bool
    status: str
    grams: float | None
    source_unit: str | None

    @property
    def stable(self) -> bool:
        return self.present and self.status == "stable"


ABSENT = ScaleReading(present=False, status="absent", grams=None, source_unit=None)


def reading_from_report(report: bytes) -> ScaleReading:
    reading = decode_reading(report)
    return ScaleReading(
        present=True,
        status=reading.status_name,
        grams=round(reading.grams, 1),
        source_unit=reading.unit_name,
    )


class ScaleSource:
    """Base for scale backends: tracks the current reading and throttles publishing."""

    def __init__(
        self,
        on_reading: Callable[[ScaleReading], None],
        min_interval: float = 0.2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.on_reading = on_reading
        self.min_interval = min_interval
        self.clock = clock
        self.current: ScaleReading = ABSENT
        self._published: ScaleReading | None = None
        self._last_publish = float("-inf")
        self._timer: asyncio.TimerHandle | None = None
        self._waiters: set[asyncio.Future[None]] = set()
        self._task: asyncio.Task[None] | None = None

    def update(self, reading: ScaleReading) -> None:
        self.current = reading
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)
        self._waiters.clear()
        self._schedule()

    def _schedule(self) -> None:
        if self.current == self._published:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            return
        delay = self._last_publish + self.min_interval - self.clock()
        if delay <= 0:
            self._publish()
        elif self._timer is None:
            self._timer = asyncio.get_running_loop().call_later(delay, self._flush)

    def _flush(self) -> None:
        self._timer = None
        if self.current != self._published:
            self._publish()

    def _publish(self) -> None:
        self._published = self.current
        self._last_publish = self.clock()
        self.on_reading(self.current)

    async def wait_for(
        self, predicate: Callable[[ScaleReading], bool], timeout: float
    ) -> ScaleReading:
        """Return the first reading matching predicate, or the latest one after timeout."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not predicate(self.current):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            waiter: asyncio.Future[None] = loop.create_future()
            self._waiters.add(waiter)
            try:
                await asyncio.wait_for(waiter, remaining)
            except asyncio.TimeoutError:
                break
            finally:
                self._waiters.discard(waiter)
        return self.current

    async def run(self) -> None:
        await asyncio.Event().wait()

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
