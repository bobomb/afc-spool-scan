"""Spoolman details for lane spools (initial weight, colours), cached and fetched in the background."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .spoolman import SpoolmanClient, SpoolmanError, SpoolNotFound, spool_colors

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpoolMeta:
    initial_g: float | None
    colors: tuple[str, ...]


def meta_from_api(data: dict[str, Any]) -> SpoolMeta:
    filament = data.get("filament") or {}
    initial = data.get("initial_weight") or filament.get("weight")
    number = float(initial) if isinstance(initial, (int, float)) and not isinstance(initial, bool) else None
    return SpoolMeta(initial_g=number if number and number > 0 else None, colors=tuple(spool_colors(filament)))


class SpoolCatalog:
    """get() never waits: it returns what is cached and refreshes stale or missing entries in the background."""

    def __init__(
        self,
        spoolman: SpoolmanClient,
        on_update: Callable[[], None],
        *,
        ttl_s: float = 600.0,
        retry_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.spoolman = spoolman
        self.on_update = on_update
        self.ttl_s = ttl_s
        self.retry_s = retry_s
        self.clock = clock
        self._entries: dict[int, tuple[float, SpoolMeta | None]] = {}
        self._failed: dict[int, float] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def get(self, spool_id: int) -> SpoolMeta | None:
        entry = self._entries.get(spool_id)
        now = self.clock()
        stale = entry is None or now - entry[0] > self.ttl_s
        if stale and now - self._failed.get(spool_id, -self.retry_s) >= self.retry_s:
            self._fetch(spool_id)
        return entry[1] if entry else None

    def put(self, data: dict[str, Any]) -> None:
        """Refresh from spool data fetched elsewhere (weigh, look up)."""
        spool_id = data.get("id")
        if isinstance(spool_id, int):
            self._store(spool_id, meta_from_api(data))

    def _store(self, spool_id: int, meta: SpoolMeta | None) -> None:
        previous = self._entries.get(spool_id)
        self._entries[spool_id] = (self.clock(), meta)
        self._failed.pop(spool_id, None)
        if previous is None or previous[1] != meta:
            self.on_update()

    def _fetch(self, spool_id: int) -> None:
        if spool_id in self._tasks:
            return
        try:
            task = asyncio.get_running_loop().create_task(self._load(spool_id))
        except RuntimeError:
            return
        self._tasks[spool_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(spool_id, None))

    async def _load(self, spool_id: int) -> None:
        try:
            data = await self.spoolman.get_spool(spool_id)
        except SpoolNotFound:
            self._store(spool_id, None)
        except SpoolmanError as error:
            self._failed[spool_id] = self.clock()
            log.debug("Spool %d details unavailable: %s", spool_id, error)
        else:
            self._store(spool_id, meta_from_api(data))

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
