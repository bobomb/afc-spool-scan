"""Scan handling by scan_mode: immediate, countdown or fill (dev plan §6.4)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import replace

from .activity import utc_now_iso
from .actions import Actions
from .qr import extract_spool_id
from .settings import Settings
from .state import Countdown, ScanState, Store

log = logging.getLogger(__name__)

COUNTDOWN_S = 5


class ScanFlow:
    def __init__(
        self,
        actions: Actions,
        store: Store,
        settings: Settings,
        prefix: str,
        *,
        countdown_s: int = COUNTDOWN_S,
        tick_s: float = 1.0,
        clock: Callable[[], str] = utc_now_iso,
    ) -> None:
        self.actions = actions
        self.store = store
        self.settings = settings
        self.prefix = prefix
        self.countdown_s = countdown_s
        self.tick_s = tick_s
        self.clock = clock
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._countdown: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.cancel()
        for task in (self._worker, self._countdown):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._worker = self._countdown = None

    def on_scan(self, code: str) -> None:
        self._queue.put_nowait(code)

    async def _run(self) -> None:
        while True:
            code = await self._queue.get()
            try:
                await self.process(code)
            except Exception:
                log.exception("Scan handling failed for %r", code)

    async def process(self, code: str) -> None:
        code = code.strip()
        if not code:
            return
        log.info("Scanned code: %s", code)
        spool_id = extract_spool_id(code, self.prefix)
        self.cancel()
        self.store.set_scan(ScanState(last_code=code, spool_id=spool_id, at=self.clock()))
        if spool_id is None:
            log.info("Ignored unrecognized QR code.")
            return
        mode = self.settings["scan_mode"]
        if mode == "immediate":
            outcome = await self.actions.weigh_load({"spool_id": spool_id}, source="scan")
            log.info("Scan of spool %d: %s", spool_id, outcome.message)
            return
        result = await self.actions.handle("lookup", {"spool_id": spool_id})
        if not result["ok"]:
            self.actions.cues.play("error")
            log.info("Scan of spool %d: %s", spool_id, result["message"])
            return
        if mode == "countdown":
            self._countdown = asyncio.create_task(self._run_countdown(spool_id))

    def _set_countdown(self, countdown: Countdown | None) -> None:
        self.store.set_scan(replace(self.store.scan, countdown=countdown))

    async def _run_countdown(self, spool_id: int) -> None:
        for remaining in range(self.countdown_s, 0, -1):
            self._set_countdown(Countdown(spool_id=spool_id, action="weigh_load", remaining_s=remaining))
            await asyncio.sleep(self.tick_s)
        self._set_countdown(None)
        self._countdown = None
        outcome = await self.actions.weigh_load({"spool_id": spool_id}, source="scan")
        log.info("Countdown for spool %d: %s", spool_id, outcome.message)

    def cancel(self) -> bool:
        task = self._countdown
        self._countdown = None
        if task is None or task.done():
            return False
        task.cancel()
        self._set_countdown(None)
        return True
