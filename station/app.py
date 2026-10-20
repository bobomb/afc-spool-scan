"""Wires the station together: state, sims or hardware, clients, actions and IPC."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from dataclasses import replace
from typing import Any

import aiohttp

from . import __version__
from .actions import Actions
from .activity import ActivityLog
from .audio import Audio
from .catalog import SpoolCatalog
from .config import Config
from .ipc import PROTOCOL, IpcServer
from .printers import PrinterManager
from .rules import derive_scale_state
from .scale.sim import SimScale
from .scale.source import ScaleReading, ScaleSource
from .scanflow import ScanFlow
from .scanner.sim import SimScanner
from .settings import Settings
from .sim.printers import FIXTURES as PRINTER_FIXTURES
from .sim.printers import SimPrinterServer
from .sim.spoolman import SimSpoolman, load_spool_fixtures
from .simcontrol import SimControl
from .spoolman import SpoolmanClient
from .state import ServiceInfo, Store

log = logging.getLogger(__name__)

HEALTH_INTERVAL_S = 10.0


class Station:
    def __init__(
        self,
        config: Config,
        *,
        printer_backoff: tuple[float, float] = (1.0, 30.0),
        publish_delay: float = 0.05,
        scale_interval: float = 0.2,
        countdown_tick_s: float = 1.0,
    ) -> None:
        self.config = config
        self.printer_backoff = printer_backoff
        self.publish_delay = publish_delay
        self.scale_interval = scale_interval
        self.countdown_tick_s = countdown_tick_s
        dry_run = not (config.writes_enabled("printers") and config.writes_enabled("spoolman"))
        self.store = Store(ServiceInfo(
            version=__version__, protocol=PROTOCOL, hardware=config.hardware, printers=config.printers_mode,
            spoolman=config.spoolman_mode, writes=config.writes, dry_run=dry_run,
        ))
        self.settings = Settings(config.state_dir / "settings.json")
        mode = (f"printers={config.printers_mode}:{'w' if config.writes_enabled('printers') else 'ro'},"
                f"spoolman={config.spoolman_mode}:{'w' if config.writes_enabled('spoolman') else 'ro'}")
        self.activity = ActivityLog(config.state_dir / "activity.jsonl", mode=mode)
        self.session: aiohttp.ClientSession | None = None
        self.sim_spoolman: SimSpoolman | None = None
        self.sim_printers: SimPrinterServer | None = None
        self.scale: ScaleSource | None = None
        self.scanner: Any = None
        self.printers: PrinterManager | None = None
        self.spoolman: SpoolmanClient | None = None
        self.catalog: SpoolCatalog | None = None
        self.actions: Actions | None = None
        self.scan_flow: ScanFlow | None = None
        self.ipc: IpcServer | None = None
        self._health_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def ipc_port(self) -> int:
        assert self.ipc is not None
        return self.ipc.port

    def _on_scale(self, reading: ScaleReading) -> None:
        self.store.set_scale(derive_scale_state(
            reading, self.store.spool, self.settings["sanity_threshold_g"], self.settings["sanity_threshold_pct"],
        ))
        healthy = reading.present and reading.status not in ("fault", "calibrate")
        self.store.set_health(replace(self.store.health, scale=healthy, scale_status=reading.status))

    def _on_scanner_presence(self, present: bool) -> None:
        self.store.set_health(replace(self.store.health, scanner=present))

    def _on_spoolman_health(self, healthy: bool) -> None:
        self.store.set_health(replace(self.store.health, spoolman=healthy))

    def _on_catalog_update(self) -> None:
        if self.printers is not None:
            self.printers.refresh()

    def _on_lane_loaded(self, printer: str, lane: str, spool_id: int) -> None:
        if self.actions is None:
            return
        try:
            task = asyncio.get_running_loop().create_task(self.actions.spool_loaded(printer, lane, spool_id))
        except RuntimeError:
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _on_scan(self, code: str) -> None:
        if self.scan_flow is not None:
            self.scan_flow.on_scan(code)

    async def _health_loop(self) -> None:
        assert self.spoolman is not None
        while True:
            await self.spoolman.health()
            await asyncio.sleep(HEALTH_INTERVAL_S)

    def _create_hardware(self) -> None:
        if self.config.hardware == "sim":
            self.scale = SimScale(self._on_scale, min_interval=self.scale_interval)
            self.scanner = SimScanner(self._on_scan, self._on_scanner_presence)
            return
        from .scale.hidraw import HidrawScale
        from .scanner.evdev_reader import EvdevScanner

        self.scale = HidrawScale(self._on_scale, self.config.scale_vendor_id, self.config.scale_product_ids,
                                 min_interval=self.scale_interval)
        self.scanner = EvdevScanner(self.config.event_dev, self._on_scan, self._on_scanner_presence)

    async def start(self) -> None:
        config = self.config
        config.state_dir.mkdir(parents=True, exist_ok=True)
        self.settings.load()
        self.store.set_settings(self.settings.as_dict())
        self.activity.undo_depth = self.settings["undo_depth"]
        self.activity.load()
        self.store.set_activity(self.activity.public())

        self.session = aiohttp.ClientSession()
        spoolman_url = config.spoolman_url
        fixtures = config.sim_fixtures
        if config.spoolman_mode == "sim":
            spools = load_spool_fixtures(fixtures / "spoolman" / "spools.json") if fixtures else None
            self.sim_spoolman = SimSpoolman(spools)
            spoolman_url = await self.sim_spoolman.start()
        urls: dict[str, str] = {}
        if config.printers_mode == "sim":
            lookup = self.sim_spoolman.get if self.sim_spoolman else None
            self.sim_printers = SimPrinterServer.from_fixtures(
                [p.key for p in config.printers], spool_lookup=lookup,
                directory=fixtures / "printers" if fixtures else PRINTER_FIXTURES,
            )
            await self.sim_printers.start()
            urls = {p.key: self.sim_printers.url_for(p.key) for p in config.printers}

        self.spoolman = SpoolmanClient(spoolman_url, self.session, writes=config.writes_enabled("spoolman"),
                                       on_health=self._on_spoolman_health)
        self.catalog = SpoolCatalog(self.spoolman, self._on_catalog_update)
        self.printers = PrinterManager(
            config.printers, self.session, on_change=self.store.set_printer,
            writes=config.writes_enabled("printers"), low_stock_g=lambda: self.settings["low_stock_g"],
            spool_meta=self.catalog.get, on_lane_loaded=self._on_lane_loaded,
            names_path=config.state_dir / "printer_names.json", urls=urls,
            backoff=self.printer_backoff, publish_delay=self.publish_delay,
        )
        self._create_hardware()
        assert self.scale is not None
        audio = Audio(
            config.repo_dir / "audible-cue.py",
            enabled=config.hardware == "real" and sys.platform != "win32",
            backend=config.audio_backend, device=config.audio_device, gpio_pin=config.buzzer_gpio_pin,
        )
        sim = None
        if config.simulated:
            sim = SimControl(
                self.scale if isinstance(self.scale, SimScale) else None,
                self.scanner if isinstance(self.scanner, SimScanner) else None,
                self.sim_printers, self.sim_spoolman,
            )
        self.actions = Actions(
            config=config, store=self.store, settings=self.settings, activity=self.activity,
            spoolman=self.spoolman, printers=self.printers, scale=self.scale, cues=audio, sim=sim,
            catalog=self.catalog,
        )
        self.scan_flow = ScanFlow(self.actions, self.store, self.settings, config.spoolman_prefix,
                                  tick_s=self.countdown_tick_s)
        self.actions.scan_flow = self.scan_flow
        self.ipc = IpcServer(
            self.store, self.actions.handle, config.ipc_host, config.ipc_port,
            hello_extra={"service_version": __version__, "hardware": config.hardware,
                         "printers": config.printers_mode, "spoolman": config.spoolman_mode,
                         "writes": config.writes},
        )

        self.scale.start()
        self.scanner.start()
        self.printers.start()
        self.scan_flow.start()
        self._health_task = asyncio.create_task(self._health_loop())
        await self.ipc.start()
        log.info(
            "Station %s started: hardware=%s printers=%s spoolman=%s writes=%s",
            __version__, config.hardware, config.printers_mode, config.spoolman_mode,
            "on" if config.writes else "off",
        )

    async def stop(self) -> None:
        if self.ipc is not None:
            await self.ipc.stop()
        if self._health_task is not None:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
        for task in list(self._tasks):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for component in (self.scan_flow, self.scanner, self.scale, self.printers, self.catalog):
            if component is not None:
                await component.stop()
        if self.sim_printers is not None:
            await self.sim_printers.stop()
        if self.sim_spoolman is not None:
            await self.sim_spoolman.stop()
        if self.session is not None:
            await self.session.close()

    async def run_forever(self) -> None:
        try:
            await self.start()
            await asyncio.Event().wait()
        finally:
            await self.stop()
