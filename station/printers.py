"""All configured printers: Moonraker clients."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import aiohttp

from .config import PrinterConfig
from .moonraker import MoonrakerClient
from .state import PrinterState


class UnknownPrinter(ValueError):
    pass


class PrinterManager:
    def __init__(
        self,
        configs: Iterable[PrinterConfig],
        session: aiohttp.ClientSession,
        *,
        on_change: Callable[[PrinterState], None],
        writes: bool,
        low_stock_g: Callable[[], float],
        spool_meta: Callable[[int], SpoolMeta | None] = lambda spool_id: None,
        on_lane_loaded: Callable[[str, str, int], None] = lambda printer, lane, spool_id: None,
        urls: dict[str, str] | None = None,
        backoff: tuple[float, float] = (1.0, 30.0),
        publish_delay: float = 0.05,
    ) -> None:
        urls = urls or {}
        self.clients: dict[str, MoonrakerClient] = {
            config.key: MoonrakerClient(
                config, session, on_change=on_change, writes=writes, low_stock_g=low_stock_g,
                spool_meta=spool_meta, on_lane_loaded=on_lane_loaded, url=urls.get(config.key), backoff=backoff,
                publish_delay=publish_delay,
            )
            for config in configs
        }
        for client in self.clients.values():
            on_change(client.state)

    @property
    def keys(self) -> list[str]:
        return list(self.clients)

    def start(self) -> None:
        for client in self.clients.values():
            client.start()

    async def stop(self) -> None:
        for client in self.clients.values():
            await client.stop()

    def get(self, name: str) -> MoonrakerClient:
        if not isinstance(name, str):
            raise UnknownPrinter("printer must be a name")
        client = self.clients.get(name.strip().lower())
        if client is None:
            raise UnknownPrinter(f"unknown printer {name!r}")
        return client

    def all(self) -> list[MoonrakerClient]:
        """Load and Weigh + Load always set the next spool on every printer."""
        return list(self.clients.values())

    def refresh(self) -> None:
        for client in self.clients.values():
            client.refresh()
