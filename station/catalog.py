"""Spoolman details for lane spools (initial weight, colours, material, grams left), cached and fetched in the
background."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from .spoolman import SpoolmanClient, SpoolmanError, SpoolNotFound, spool_colors

log = logging.getLogger(__name__)


def _positive(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


@dataclass(frozen=True)
class SpoolMeta:
    initial_g: float | None
    colors: tuple[str, ...]
    material: str | None = None
    remaining_g: float | None = None
    archived: bool = False
    # Bambu RFID tray UUID linked to the spool (Spoolman extra.tag), upper case.
    tag: str | None = None


def spool_tag(data: dict[str, Any]) -> str | None:
    """Spoolman keeps extra fields JSON-encoded, so the tag is a quoted string."""
    raw = (data.get("extra") or {}).get("tag")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    return value.strip().upper() or None if isinstance(value, str) else None


def meta_from_api(data: dict[str, Any]) -> SpoolMeta:
    filament = data.get("filament") or {}
    number = _positive(data.get("initial_weight") or filament.get("weight"))
    remaining = _positive(data.get("remaining_weight"))
    material = filament.get("material")
    return SpoolMeta(
        initial_g=number if number and number > 0 else None,
        colors=tuple(spool_colors(filament)),
        material=material.strip() or None if isinstance(material, str) else None,
        remaining_g=round(max(remaining, 0.0), 1) if remaining is not None else None,
        archived=bool(data.get("archived")),
        tag=spool_tag(data),
    )


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

    @property
    def busy(self) -> bool:
        return bool(self._tasks)

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

    def refresh(self, spool_ids: Iterable[int]) -> None:
        """Fetch again now (e.g. after a print used filament); the cached value stays until the answer."""
        for spool_id in spool_ids:
            self._failed.pop(spool_id, None)
            self._fetch(spool_id)

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
