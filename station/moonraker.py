"""Moonraker WebSocket JSON-RPC client for one AFC printer (dev plan §6.3)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import aiohttp

from .catalog import SpoolMeta
from .config import PrinterConfig
from .state import LaneState, PrinterState

log = logging.getLogger(__name__)

NEXT_SPOOL_PATTERN = re.compile(
    r"Spool ID (?:'[^']*' being overwritten for next load|set for next load): '([^']*)'"
)
LANE_PREFIXES = ("AFC_stepper ", "AFC_lane ")
# With writes off only these JSON-RPC methods may reach Moonraker (second guard behind gcode()).
READ_ONLY_METHODS = frozenset(
    {"server.info", "printer.objects.list", "printer.objects.query", "printer.objects.subscribe"}
)


class PrinterOffline(Exception):
    pass


class PrinterCommandError(Exception):
    pass


@dataclass(frozen=True)
class GcodeResult:
    dry_run: bool
    responses: tuple[str, ...] = ()


def deep_merge(target: dict[str, Any], diff: dict[str, Any]) -> None:
    for key, value in diff.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = value


def normalize_color(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#")
    if len(text) < 6 or any(c not in "0123456789abcdefABCDEF" for c in text[:6]):
        return None
    return f"#{text[:6].upper()}"


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 1)
    return None


def parse_next_spool(line: str) -> tuple[bool, int | None]:
    """Return (matched, spool_id) for an AFC next-spool confirmation line."""
    match = NEXT_SPOOL_PATTERN.search(line)
    if not match:
        return False, None
    return True, _int_or_none(match.group(1))


class MoonrakerClient:
    def __init__(
        self,
        printer: PrinterConfig,
        session: aiohttp.ClientSession,
        *,
        on_change: Callable[[PrinterState], None],
        writes: bool,
        low_stock_g: Callable[[], float] = lambda: 100.0,
        spool_meta: Callable[[int], SpoolMeta | None] = lambda spool_id: None,
        on_lane_loaded: Callable[[str, str, int], None] = lambda printer, lane, spool_id: None,
        url: str | None = None,
        request_timeout: float = 10.0,
        backoff: tuple[float, float] = (1.0, 30.0),
        publish_delay: float = 0.05,
    ) -> None:
        self.printer = printer
        self.session = session
        self.on_change = on_change
        self.writes = writes
        self.low_stock_g = low_stock_g
        self.spool_meta = spool_meta
        self.on_lane_loaded = on_lane_loaded
        self.url = url or printer.websocket_url
        self.request_timeout = request_timeout
        self.backoff = backoff
        self.publish_delay = publish_delay
        self.state = PrinterState(key=printer.key, name=printer.name)
        self._status: dict[str, dict[str, Any]] = {}
        self._lane_objects: dict[str, str] = {}
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._rpc: dict[int, asyncio.Future[Any]] = {}
        self._next_id = 1
        self._collectors: list[list[str]] = []
        self._publish_handle: asyncio.TimerHandle | None = None
        self._task: asyncio.Task[None] | None = None
        self._subscribe_task: asyncio.Task[None] | None = None
        self._last_error: str | None = None

    @property
    def key(self) -> str:
        return self.printer.key

    @property
    def online(self) -> bool:
        return self._ws is not None and not self._ws.closed and self.state.connected

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._publish_handle is not None:
            self._publish_handle.cancel()
            self._publish_handle = None

    async def run(self) -> None:
        delay = self.backoff[0]
        while True:
            try:
                async with self.session.ws_connect(self.url, heartbeat=30) as ws:
                    self._ws = ws
                    delay = self.backoff[0]
                    log.info("%s: connected to %s", self.printer.name, self.url)
                    reader = asyncio.create_task(self._read_loop(ws))
                    try:
                        await self._initialize()
                    except (PrinterOffline, PrinterCommandError, asyncio.TimeoutError) as error:
                        log.warning("%s: setup failed: %s", self.printer.name, error)
                        await ws.close()
                    await reader
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as error:
                log.debug("%s: connection failed: %s", self.printer.name, error)
            finally:
                self._ws = None
                self._fail_pending(PrinterOffline(f"{self.printer.name} disconnected"))
                if self._subscribe_task is not None:
                    self._subscribe_task.cancel()
                    self._subscribe_task = None
            self._mark_offline("disconnected")
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.backoff[1])

    def _mark_offline(self, klippy_state: str | None) -> None:
        """Offline usually means a shutdown or reboot, which also drops AFC's pending next spool."""
        pending = self.state.pending_spool
        if self.state.connected or self.state.klippy_state != klippy_state or pending is not None:
            if pending is not None:
                log.info("%s: offline (%s); cleared pending next spool %d", self.printer.name, klippy_state, pending)
            self.state = replace(self.state, connected=False, klippy_state=klippy_state,
                                 pending_spool=None, pending_confirmed=False)
            self._publish_now()

    def _fail_pending(self, error: Exception) -> None:
        for future in self._rpc.values():
            if not future.done():
                future.set_exception(error)
        self._rpc.clear()

    async def call(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        if not self.writes and method not in READ_ONLY_METHODS:
            raise PrinterCommandError(f"writes are off; refusing {method}")
        ws = self._ws
        if ws is None or ws.closed:
            raise PrinterOffline(f"{self.printer.name} is offline")
        request_id = self._next_id
        self._next_id += 1
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._rpc[request_id] = future
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": request_id}
        if params is not None:
            message["params"] = params
        try:
            await ws.send_str(json.dumps(message))
            return await asyncio.wait_for(future, timeout or self.request_timeout)
        except (ConnectionError, aiohttp.ClientError) as error:
            raise PrinterOffline(f"{self.printer.name} is offline") from error
        finally:
            self._rpc.pop(request_id, None)

    async def _initialize(self) -> None:
        info = await self.call("server.info")
        state = info.get("klippy_state") if isinstance(info, dict) else None
        if state == "ready":
            await self._subscribe()
        else:
            self._mark_offline(state or "unknown")

    async def _subscribe(self) -> None:
        listing = await self.call("printer.objects.list")
        objects = listing.get("objects", []) if isinstance(listing, dict) else []
        self._lane_objects = {
            name.split(" ", 1)[1]: name for name in objects if name.startswith(LANE_PREFIXES)
        }
        wanted: dict[str, list[str] | None] = {
            "print_stats": ["state", "filename"],
            "display_status": ["progress"],
        }
        if "AFC" in objects:
            wanted["AFC"] = None
        for name in self._lane_objects.values():
            wanted[name] = None
        result = await self.call("printer.objects.subscribe", {"objects": wanted})
        self._status = dict(result.get("status", {})) if isinstance(result, dict) else {}
        self.state = replace(self.state, connected=True, klippy_state="ready")
        self._rebuild()
        self._publish_now()

    async def _read_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for message in ws:
            if message.type != aiohttp.WSMsgType.TEXT:
                if message.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break
                continue
            try:
                data = json.loads(message.data)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            if "id" in data and data["id"] in self._rpc:
                future = self._rpc[data["id"]]
                if future.done():
                    continue
                if "error" in data:
                    error = data["error"] or {}
                    future.set_exception(PrinterCommandError(str(error.get("message", error))))
                else:
                    future.set_result(data.get("result"))
            elif "method" in data:
                self._notification(data["method"], data.get("params") or [])

    def _notification(self, method: str, params: list[Any]) -> None:
        if method == "notify_status_update" and params and isinstance(params[0], dict):
            for name, diff in params[0].items():
                if isinstance(diff, dict):
                    deep_merge(self._status.setdefault(name, {}), diff)
            if self.state.connected:
                self._rebuild()
                self._schedule_publish()
        elif method == "notify_gcode_response" and params:
            line = str(params[0])
            for collector in self._collectors:
                collector.append(line)
            matched, spool_id = parse_next_spool(line)
            if matched:
                self.state = replace(self.state, pending_spool=spool_id, pending_confirmed=spool_id is not None)
                self._publish_now()
        elif method == "notify_klippy_ready":
            if self._subscribe_task is None or self._subscribe_task.done():
                self._subscribe_task = asyncio.create_task(self._resubscribe())
        elif method in ("notify_klippy_shutdown", "notify_klippy_disconnected"):
            self._mark_offline("shutdown" if method == "notify_klippy_shutdown" else "disconnected")

    async def _resubscribe(self) -> None:
        try:
            await self._subscribe()
        except (PrinterOffline, PrinterCommandError, asyncio.TimeoutError) as error:
            log.warning("%s: resubscribe failed: %s", self.printer.name, error)

    def _rebuild(self) -> None:
        afc = self._status.get("AFC", {})
        print_stats = self._status.get("print_stats", {})
        display = self._status.get("display_status", {})
        order = [lane for lane in afc.get("lanes") or [] if lane in self._lane_objects]
        order += sorted(lane for lane in self._lane_objects if lane not in order)
        threshold = self.low_stock_g()
        lanes = []
        for lane in order:
            raw = self._status.get(self._lane_objects[lane], {})
            spool_id = _int_or_none(raw.get("spool_id"))
            remaining = _float_or_none(raw.get("weight")) if spool_id is not None else None
            color = normalize_color(raw.get("color"))
            meta = self.spool_meta(spool_id) if spool_id is not None else None
            pct = None
            if meta is not None and meta.initial_g and remaining is not None:
                pct = round(max(0.0, min(100.0, remaining / meta.initial_g * 100.0)), 1)
            colors = list(meta.colors) if meta is not None and meta.colors else ([color] if color else [])
            lanes.append(
                LaneState(
                    lane=lane,
                    map=raw.get("map") or None,
                    spool_id=spool_id,
                    material=raw.get("material") or None,
                    color=color,
                    remaining_g=remaining,
                    filament_status=raw.get("filament_status") or None,
                    status=raw.get("status") or None,
                    prep=bool(raw.get("prep")),
                    load=bool(raw.get("load")),
                    tool_loaded=bool(raw.get("tool_loaded")),
                    low_stock=remaining is not None and remaining < threshold,
                    remaining_pct=pct,
                    colors=colors,
                )
            )
        message = afc.get("message")
        if isinstance(message, dict) and message.get("type") == "error" and message.get("message"):
            self._last_error = str(message["message"])
        if not afc.get("error_state"):
            self._last_error = None
        afc_error = (self._last_error or "AFC error") if afc.get("error_state") else None

        pending = self.state.pending_spool
        confirmed = self.state.pending_confirmed
        previous = {lane.lane: lane.spool_id for lane in self.state.lanes}
        if pending is not None and any(
            lane.spool_id == pending and previous.get(lane.lane) != pending for lane in lanes
        ):
            pending, confirmed = None, False
        # Lanes known before that now hold a different spool (AFC loaded the pending one, or an assignment).
        loaded = [(lane.lane, lane.spool_id) for lane in lanes
                  if lane.spool_id is not None and lane.lane in previous and previous[lane.lane] != lane.spool_id]

        progress = display.get("progress")
        self.state = replace(
            self.state,
            print_state=print_stats.get("state") or None,
            filename=print_stats.get("filename") or None,
            progress=round(float(progress), 3) if isinstance(progress, (int, float)) else None,
            afc_state=afc.get("current_state") or None,
            afc_error=afc_error,
            current_load=afc.get("current_load") or None,
            pending_spool=pending,
            pending_confirmed=confirmed,
            lanes=lanes,
        )
        for lane_name, spool_id in loaded:
            self.on_lane_loaded(self.key, lane_name, spool_id)

    def refresh(self) -> None:
        """Recompute derived fields (e.g. low stock after a threshold change)."""
        if self.state.connected:
            self._rebuild()
        self._publish_now()

    def _schedule_publish(self) -> None:
        if self.publish_delay <= 0:
            self._publish_now()
        elif self._publish_handle is None:
            self._publish_handle = asyncio.get_running_loop().call_later(self.publish_delay, self._publish_now)

    def _publish_now(self) -> None:
        if self._publish_handle is not None:
            self._publish_handle.cancel()
            self._publish_handle = None
        self.on_change(self.state)

    def lane(self, lane: str) -> LaneState | None:
        return next((item for item in self.state.lanes if item.lane == lane), None)

    async def gcode(self, script: str) -> GcodeResult:
        if not self.writes:
            log.info("%s: writes off, would send %r", self.printer.name, script)
            return GcodeResult(dry_run=True)
        if not self.online:
            raise PrinterOffline(f"{self.printer.name} is offline")
        collector: list[str] = []
        self._collectors.append(collector)
        try:
            await self.call("printer.gcode.script", {"script": script})
        finally:
            self._collectors.remove(collector)
        errors = [line for line in collector if line.lstrip().startswith("!!")]
        if errors:
            raise PrinterCommandError(errors[0].lstrip()[2:].strip())
        log.info("%s: sent %r", self.printer.name, script)
        return GcodeResult(dry_run=False, responses=tuple(collector))

    async def set_next_spool(self, spool_id: int | None) -> GcodeResult:
        script = "SET_NEXT_SPOOL_ID" if spool_id is None else f"SET_NEXT_SPOOL_ID SPOOL_ID={spool_id}"
        result = await self.gcode(script)
        if not result.dry_run and (self.state.pending_spool != spool_id or spool_id is None):
            self.state = replace(self.state, pending_spool=spool_id, pending_confirmed=False)
            self._publish_now()
        return result

    async def set_lane_spool(self, lane: str, spool_id: int | None) -> GcodeResult:
        value = "" if spool_id is None else str(spool_id)
        return await self.gcode(f"SET_SPOOL_ID LANE={lane} SPOOL_ID={value}")
