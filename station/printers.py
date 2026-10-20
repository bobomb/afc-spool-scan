"""All configured printers: Moonraker clients."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from pathlib import Path

import aiohttp

from .catalog import SpoolMeta
from .config import PrinterConfig
from .moonraker import MoonrakerClient
from .settings import atomic_write_text
from .state import PrinterState

log = logging.getLogger(__name__)


class UnknownPrinter(ValueError):
    pass


class DisplayNames:
    """Last known Mainsail names, so a printer that is off keeps its name across restarts."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.names: dict[str, str] = {}

    def load(self) -> dict[str, str]:
        if self.path is None or not self.path.is_file():
            return self.names
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log.warning("Ignoring %s: %s", self.path, error)
            return self.names
        if isinstance(data, dict):
            self.names = {str(k): v for k, v in data.items() if isinstance(v, str) and v.strip()}
        return self.names

    def set(self, key: str, name: str | None) -> None:
        if self.names.get(key) == name:
            return
        if name:
            self.names[key] = name
        else:
            self.names.pop(key, None)
        if self.path is None:
            return
        try:
            atomic_write_text(self.path, json.dumps(self.names, indent=2, sort_keys=True) + "\n")
        except OSError as error:
            log.warning("Could not save %s: %s", self.path, error)


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
        names_path: Path | None = None,
        urls: dict[str, str] | None = None,
        backoff: tuple[float, float] = (1.0, 30.0),
        publish_delay: float = 0.05,
    ) -> None:
        urls = urls or {}
        self.names = DisplayNames(names_path)
        cached = self.names.load()
        self.clients: dict[str, MoonrakerClient] = {
            config.key: MoonrakerClient(
                config, session, on_change=on_change, writes=writes, low_stock_g=low_stock_g,
                spool_meta=spool_meta, on_lane_loaded=on_lane_loaded, display_name=cached.get(config.key),
                on_display_name=self.names.set, url=urls.get(config.key), backoff=backoff,
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
