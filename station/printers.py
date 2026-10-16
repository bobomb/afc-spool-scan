"""All configured printers: Moonraker clients and target resolution."""

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
        urls: dict[str, str] | None = None,
        backoff: tuple[float, float] = (1.0, 30.0),
        publish_delay: float = 0.05,
    ) -> None:
        urls = urls or {}
        self.clients: dict[str, MoonrakerClient] = {
            config.key: MoonrakerClient(
                config, session, on_change=on_change, writes=writes, low_stock_g=low_stock_g,
                spool_meta=spool_meta, url=urls.get(config.key), backoff=backoff, publish_delay=publish_delay,
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

    def resolve(self, target: str) -> list[MoonrakerClient]:
        """'both' (every printer), one printer key, or a comma-separated list of keys."""
        if not isinstance(target, str):
            raise UnknownPrinter("target must be 'both' or printer names")
        if target.strip().lower() == "both":
            return list(self.clients.values())
        names = [name for name in target.split(",") if name.strip()]
        if not names:
            raise UnknownPrinter("target must be 'both' or printer names")
        wanted = {self.get(name).key for name in names}
        return [client for key, client in self.clients.items() if key in wanted]

    def refresh(self) -> None:
        for client in self.clients.values():
            client.refresh()
