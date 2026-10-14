"""DYMO scale reader over Linux hidraw (non-blocking, via loop.add_reader)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import AsyncContextManager

from .dymo import find_hidraw
from .source import ABSENT, ScaleReading, ScaleSource, reading_from_report

log = logging.getLogger(__name__)

Opener = Callable[[Path], AsyncContextManager[AsyncIterator[bytes]]]


@contextlib.asynccontextmanager
async def open_hidraw(path: Path) -> AsyncIterator[AsyncIterator[bytes]]:
    loop = asyncio.get_running_loop()
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)  # type: ignore[attr-defined]
    queue: asyncio.Queue[bytes | BaseException] = asyncio.Queue()

    def readable() -> None:
        try:
            queue.put_nowait(os.read(fd, 64))
        except BlockingIOError:
            pass
        except OSError as error:
            loop.remove_reader(fd)
            queue.put_nowait(error)

    async def reports() -> AsyncIterator[bytes]:
        while True:
            item = await queue.get()
            if isinstance(item, BaseException):
                raise item
            if not item:
                raise OSError("scale device closed")
            yield item

    loop.add_reader(fd, readable)
    try:
        yield reports()
    finally:
        loop.remove_reader(fd)
        os.close(fd)


class HidrawScale(ScaleSource):
    def __init__(
        self,
        on_reading: Callable[[ScaleReading], None],
        vendor_id: str,
        product_ids: set[str] | frozenset[str],
        *,
        finder: Callable[[str, set[str]], Path] = find_hidraw,
        opener: Opener = open_hidraw,
        retry_s: float = 2.0,
        **kwargs: object,
    ) -> None:
        super().__init__(on_reading, **kwargs)  # type: ignore[arg-type]
        self.vendor_id = vendor_id
        self.product_ids = set(product_ids)
        self.finder = finder
        self.opener = opener
        self.retry_s = retry_s
        self._warned: str | None = None

    def _warn_once(self, message: str) -> None:
        if message != self._warned:
            log.warning("%s", message)
            self._warned = message

    async def run(self) -> None:
        while True:
            try:
                path = self.finder(self.vendor_id, self.product_ids)
            except RuntimeError as error:
                self._warn_once(f"Scale: {error}")
                self.update(ABSENT)
                await asyncio.sleep(self.retry_s)
                continue
            try:
                async with self.opener(path) as reports:
                    log.info("Scale connected at %s", path)
                    self._warned = None
                    async for report in reports:
                        try:
                            self.update(reading_from_report(report))
                        except ValueError as error:
                            log.debug("Ignoring scale report: %s", error)
            except PermissionError:
                self._warn_once(f"Scale: permission denied opening {path}; install 99-dymo-scale.rules")
            except OSError as error:
                self._warn_once(f"Scale disconnected: {error}")
            self.update(ABSENT)
            await asyncio.sleep(self.retry_s)
