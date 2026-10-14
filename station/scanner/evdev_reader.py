"""QR scanner reader over python-evdev (Linux only; imported lazily)."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import logging
from collections.abc import Callable
from types import ModuleType
from typing import Any

from .keymap import KeyDecoder

log = logging.getLogger(__name__)


class EvdevScanner:
    def __init__(
        self,
        path: str,
        on_scan: Callable[[str], None],
        on_presence: Callable[[bool], None],
        *,
        evdev_module: ModuleType | Any | None = None,
        retry_s: float = 2.0,
        grab: bool = True,
    ) -> None:
        self.path = path
        self.on_scan = on_scan
        self.on_presence = on_presence
        self._evdev = evdev_module
        self.retry_s = retry_s
        self.grab = grab
        self._task: asyncio.Task[None] | None = None
        self._warned: str | None = None

    def _warn_once(self, message: str) -> None:
        if message != self._warned:
            log.warning("%s", message)
            self._warned = message

    async def run(self) -> None:
        evdev = self._evdev or importlib.import_module("evdev")
        while True:
            try:
                device = evdev.InputDevice(self.path)
            except OSError as error:
                self._warn_once(f"QR scanner {self.path} unavailable: {error}")
                self.on_presence(False)
                await asyncio.sleep(self.retry_s)
                continue
            self._warned = None
            self.on_presence(True)
            log.info("Reading QR codes from %s", self.path)
            grabbed = False
            try:
                if self.grab:
                    try:
                        device.grab()
                        grabbed = True
                    except OSError as error:
                        log.warning("Could not grab QR scanner (scans may leak to the console): %s", error)
                decoder = KeyDecoder()
                async for event in device.async_read_loop():
                    if event.type != evdev.ecodes.EV_KEY:
                        continue
                    code = decoder.feed(event.code, event.value)
                    if code is not None:
                        self.on_scan(code)
            except OSError as error:
                log.warning("QR scanner disconnected: %s", error)
            finally:
                if grabbed:
                    with contextlib.suppress(OSError):
                        device.ungrab()
                with contextlib.suppress(OSError):
                    device.close()
            self.on_presence(False)
            await asyncio.sleep(self.retry_s)

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
