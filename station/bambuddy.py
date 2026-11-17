"""Bambuddy REST + websocket client for one Bambu printer with an AMS 3H (dev plan §6.6).

Bambuddy owns the printer connection and the slot -> Spoolman spool map; the
station talks MQTT to the printer only for what Bambuddy can't send, a slot's
remaining weight (bambu_mqtt, dev plan §6.7). "Next spool" is an armed spool
the station holds: when a spool goes into an empty AMS 3H slot while armed,
the station assigns the armed spool to that slot (an RFID spool Bambuddy
already knows keeps Bambuddy's match) and reports a LaneLoad, like AFC
loading a lane.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import replace
from typing import Any

import aiohttp

from .bambu_mqtt import WeightSender, WeightTarget, filament_weight, remain_percent
from .catalog import SpoolMeta
from .config import PrinterConfig
from .moonraker import clean_display_name, normalize_color
from .printer_client import (
    CommandResult,
    LaneLoad,
    LaneLoadHandler,
    NoticeHandler,
    PrinterCommandError,
    PrinterNotice,
    PrinterOffline,
)
from .state import LaneState, PrinterState

log = logging.getLogger(__name__)

AMS_3H = 32
SLOTS = 9
TRAY_NOW_BASE = 28
ACTIVE_STATES = frozenset({"RUNNING", "PREPARE", "SLICING", "PAUSE"})
PRINT_STATES = {"RUNNING": "printing", "PREPARE": "printing", "SLICING": "printing", "PAUSE": "paused",
                "FINISH": "complete", "FAILED": "error", "IDLE": "standby", "INIT": "standby"}
# HMS severity: 1 error (stopped), 2 warning (paused), 3 notification.
HMS_SHOWN = (1, 2)
CONFLICT = 409
LANE_PREFIX = "3H-"


def lane_name(slot: int) -> str:
    return f"{LANE_PREFIX}{slot + 1}"


def slot_of(lane: str) -> int | None:
    if not lane.startswith(LANE_PREFIX) or not lane[len(LANE_PREFIX):].isdigit():
        return None
    slot = int(lane[len(LANE_PREFIX):]) - 1
    return slot if 0 <= slot < SLOTS else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def spool_present(tray: dict[str, Any] | None) -> bool:
    """Bambuddy's presence bit (`exists`) when it has one, else the tray state (9/10 = empty)."""
    if not isinstance(tray, dict):
        return False
    exists = tray.get("exists")
    if isinstance(exists, bool):
        return exists
    return bool(tray.get("tray_type")) and tray.get("state") not in (9, 10)


def tray_tag(tray: dict[str, Any] | None) -> str | None:
    """The Bambu RFID tray UUID, or None for a spool without a tag."""
    raw = tray.get("tray_uuid") if isinstance(tray, dict) else None
    if not isinstance(raw, str) or not raw.strip() or set(raw.strip()) == {"0"}:
        return None
    return raw.strip().upper()


def hms_text(errors: Any) -> str | None:
    for error in errors if isinstance(errors, list) else []:
        if isinstance(error, dict) and _int(error.get("severity")) in HMS_SHOWN:
            return str(error.get("description") or f"HMS {error.get('code') or 'error'}")
    return None


def _error_text(status: int, data: Any) -> str:
    detail = data.get("detail") if isinstance(data, dict) else data
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("code")
    elif isinstance(detail, list) and detail and isinstance(detail[0], dict):
        detail = detail[0].get("msg")
    text = str(detail).strip() if detail else ""
    return f"Bambuddy {status}: {text}" if text else f"Bambuddy {status}"


class BambuddyClient:
    def __init__(
        self,
        printer: PrinterConfig,
        session: aiohttp.ClientSession,
        *,
        on_change: Callable[[PrinterState], None],
        writes: bool,
        base_url: str,
        api_key: str = "",
        low_stock_g: Callable[[], float] = lambda: 100.0,
        spool_meta: Callable[[int], SpoolMeta | None] = lambda spool_id: None,
        on_lane_loaded: LaneLoadHandler = lambda load: None,
        on_notice: NoticeHandler = lambda notice: None,
        spool_refresh: Callable[[Iterable[int]], None] = lambda spool_ids: None,
        display_name: str | None = None,
        on_display_name: Callable[[str, str | None], None] = lambda key, name: None,
        request_timeout: float = 10.0,
        backoff: tuple[float, float] = (1.0, 30.0),
        publish_delay: float = 0.05,
        insert_settle_s: float = 3.0,
        settings_check_s: float = 10.0,
        usage_refresh_s: float = 30.0,
        ping_s: float = 30.0,
        weight_sender: WeightSender | None = None,
        weight_retry_s: float = 300.0,
    ) -> None:
        if printer.bambuddy_printer_id is None:
            raise ValueError(f"{printer.name} has no Bambuddy printer id")
        self.printer = printer
        self.printer_id = printer.bambuddy_printer_id
        self.session = session
        self.on_change = on_change
        self.writes = writes
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.low_stock_g = low_stock_g
        self.spool_meta = spool_meta
        self.on_lane_loaded = on_lane_loaded
        self.on_notice = on_notice
        self.spool_refresh = spool_refresh
        self.on_display_name = on_display_name
        self.request_timeout = request_timeout
        self.backoff = backoff
        self.publish_delay = publish_delay
        self.insert_settle_s = insert_settle_s
        self.settings_check_s = settings_check_s
        self.usage_refresh_s = usage_refresh_s
        self.ping_s = ping_s
        self.weight_sender = weight_sender
        self.weight_retry_s = weight_retry_s
        self.state = PrinterState(key=printer.key, name=printer.name, kind="bambuddy",
                                  display_name=clean_display_name(display_name))
        self._status: dict[str, Any] = {}
        self._assignments: dict[int, int] = {}
        self._present: dict[int, bool] = {}
        self._primed = False
        self._was_active = False
        self._own: dict[int, int] = {}
        self._pending_settings: set[int] = set()
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._inserts: dict[int, asyncio.Task[None]] = {}
        self._insert_lock = asyncio.Lock()
        self._assignments_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._publish_handle: asyncio.TimerHandle | None = None
        self._last_failure: str | None = None
        self._target = WeightTarget(self.printer_id)
        # slot -> ((spool, total g, remain g), loop time before which that value is not sent again).
        self._weight_sent: dict[int, tuple[tuple[int, int, int], float]] = {}
        self._weight_tasks: dict[int, asyncio.Task[None]] = {}
        self._weight_lock = asyncio.Lock()
        self._weight_hold: dict[int, float] = {}
        self._weights_hold_until = 0.0
        self._weight_timer: asyncio.TimerHandle | None = None

    def __repr__(self) -> str:
        return f"BambuddyClient({self.printer.name!r}, printer_id={self.printer_id})"

    @property
    def key(self) -> str:
        return self.printer.key

    @property
    def label(self) -> str:
        return self.state.label

    @property
    def online(self) -> bool:
        return self._ws is not None and not self._ws.closed and self.state.connected

    @property
    def active(self) -> bool:
        return str(self._status.get("state") or "").upper() in ACTIVE_STATES

    def lane(self, lane: str) -> LaneState | None:
        return next((item for item in self.state.lanes if item.lane == lane), None)

    # ---- lifecycle ---------------------------------------------------------------

    def start(self) -> None:
        self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        tasks = [t for t in (self._task, self._refresh_task, *self._tasks, *self._inserts.values(),
                             *self._weight_tasks.values()) if t is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._task = self._refresh_task = None
        self._tasks.clear()
        self._inserts.clear()
        self._weight_tasks.clear()
        for handle in (self._publish_handle, self._weight_timer):
            if handle is not None:
                handle.cancel()
        self._publish_handle = self._weight_timer = None

    def _spawn(self, coro: Any) -> asyncio.Task[None]:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def run(self) -> None:
        delay = self.backoff[0]
        while True:
            try:
                token = await self._ws_token()
                url = self.base_url.replace("http", "ws", 1) + "/api/v1/ws"
                params = {"token": token} if token else None
                async with self.session.ws_connect(url, params=params,
                                                   timeout=aiohttp.ClientWSTimeout(ws_close=5)) as ws:
                    self._ws = ws
                    self._primed = False
                    pinger = asyncio.create_task(self._ping(ws))
                    try:
                        await self._seed()
                        delay = self.backoff[0]
                        self._last_failure = None
                        log.info("%s: connected to Bambuddy at %s", self.printer.name, self.base_url)
                        await self._read(ws)
                    finally:
                        pinger.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await pinger
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError, PrinterCommandError, PrinterOffline) as error:
                failure = str(error) or type(error).__name__
                if failure != self._last_failure:
                    log.warning("%s: Bambuddy unavailable: %s", self.printer.name, failure)
                    self._last_failure = failure
            finally:
                self._ws = None
            self._mark_offline("disconnected")
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.backoff[1])

    async def _ws_token(self) -> str | None:
        if not self._api_key:
            return None
        data = await self._request("POST", "/auth/ws-token")
        token = data.get("token") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            raise PrinterCommandError("Bambuddy gave no websocket token")
        return token

    async def _ping(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        while not ws.closed:
            await asyncio.sleep(self.ping_s)
            with contextlib.suppress(ConnectionError, RuntimeError, aiohttp.ClientError):
                await ws.send_str(json.dumps({"type": "ping"}))

    async def _seed(self) -> None:
        status = await self._request("GET", f"/printers/{self.printer_id}/status")
        if not isinstance(status, dict):
            raise PrinterCommandError("Bambuddy sent no printer status")
        self._update_name(status.get("name"))
        if self.weight_sender is not None and self.weight_sender.needs_address:
            await self._load_target()
        await self._load_assignments(announce=False)
        self._apply_status(status)

    async def _load_target(self) -> None:
        """The printer's LAN address and serial for the weight command (never logged or published)."""
        rows = await self._request("GET", "/printers/")
        row = next((r for r in rows if isinstance(r, dict) and _int(r.get("id")) == self.printer_id), None) \
            if isinstance(rows, list) else None
        host = row.get("ip_address") if row else None
        serial = row.get("serial_number") if row else None
        self._target = WeightTarget(self.printer_id, host if isinstance(host, str) and host else None,
                                    serial if isinstance(serial, str) and serial else None)
        if self._target.host is None or self._target.serial is None:
            log.warning("%s: Bambuddy gave no printer address; remaining weights are not sent", self.printer.name)

    async def _read(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for message in ws:
            if message.type != aiohttp.WSMsgType.TEXT:
                if message.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break
                continue
            try:
                data = json.loads(message.data)
            except ValueError:
                continue
            if not isinstance(data, dict) or _int(data.get("printer_id")) != self.printer_id:
                continue
            kind = data.get("type")
            if kind == "printer_status" and isinstance(data.get("data"), dict):
                self._apply_status(data["data"])
            elif kind == "spool_assignment_changed":
                self._schedule_assignments()
            elif kind == "unknown_tag":
                log.info("%s: unknown RFID tag in %s", self.printer.name, lane_name(_int(data.get("tray_id")) or 0))

    # ---- HTTP -------------------------------------------------------------------

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        if method != "GET" and path != "/auth/ws-token" and not self.writes:
            raise PrinterCommandError(f"writes are off; refusing {method} {path}")
        headers = {"X-API-Key": self._api_key} if self._api_key else {}
        try:
            async with self.session.request(
                method, f"{self.base_url}/api/v1{path}", json=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.request_timeout),
            ) as response:
                text = await response.text()
                try:
                    data = json.loads(text) if text else None
                except ValueError:
                    data = text
                if response.status >= 400:
                    raise PrinterCommandError(_error_text(response.status, data), response.status)
                return data
        except aiohttp.ClientResponseError as error:
            raise PrinterCommandError(f"Bambuddy {error.status}", error.status) from error
        except (aiohttp.ClientError, OSError) as error:
            raise PrinterOffline(f"Bambuddy is unreachable ({type(error).__name__})") from error

    async def _load_assignments(self, announce: bool = True) -> None:
        """Bambuddy's slot -> spool map; a spool newly in a filled slot is reported as a LaneLoad."""
        async with self._assignments_lock:
            rows = await self._request("GET", f"/spoolman/inventory/slot-assignments/all?printer_id={self.printer_id}")
            fresh: dict[int, int] = {}
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict) or _int(row.get("printer_id")) != self.printer_id:
                    continue
                slot, spool_id = _int(row.get("tray_id")), _int(row.get("spoolman_spool_id"))
                if _int(row.get("ams_id")) == AMS_3H and slot is not None and 0 <= slot < SLOTS and spool_id:
                    fresh[slot] = spool_id
            old, self._assignments = self._assignments, fresh
        for slot in set(old) | set(fresh):
            if old.get(slot) != fresh.get(slot):
                self._hold_weight(slot)
        if not announce or not self._primed:
            return
        for slot, spool_id in fresh.items():
            if old.get(slot) == spool_id or not self._present.get(slot):
                continue
            if self._own.get(slot) == spool_id:
                del self._own[slot]
                continue
            self._disarm(spool_id)
            self.on_lane_loaded(LaneLoad(self.key, lane_name(slot), spool_id, previous=old.get(slot)))

    def _schedule_assignments(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.get_running_loop().create_task(self._refresh_assignments())

    async def _refresh_assignments(self) -> None:
        try:
            await self._load_assignments()
        except (PrinterCommandError, PrinterOffline, asyncio.TimeoutError) as error:
            log.warning("%s: slot assignments not refreshed: %s", self.printer.name, error)
            return
        self._rebuild()
        self._publish_now()
        self._reconcile_weights()

    # ---- state ------------------------------------------------------------------

    def _update_name(self, value: Any) -> None:
        name = clean_display_name(value)
        if name is None or name == self.state.display_name:
            return
        log.info("%s: Bambuddy name %r", self.printer.name, name)
        self.state = replace(self.state, display_name=name)
        self.on_display_name(self.key, name)

    def _trays(self) -> dict[int, dict[str, Any]] | None:
        units = self._status.get("ams")
        for unit in units if isinstance(units, list) else []:
            if isinstance(unit, dict) and _int(unit.get("id")) == AMS_3H:
                return {slot: tray for tray in unit.get("tray") or []
                        if isinstance(tray, dict) and (slot := _int(tray.get("id"))) is not None}
        return None

    def _tray(self, slot: int) -> dict[str, Any]:
        return (self._trays() or {}).get(slot) or {}

    def _apply_status(self, data: dict[str, Any]) -> None:
        if data.get("connected") is False:
            self._status = data
            self._mark_off()
            return
        self._status = data
        presence = {slot: spool_present(self._tray(slot)) for slot in range(SLOTS)} if self._trays() else {}
        if self._primed:
            for slot, present in presence.items():
                before = self._present.get(slot)
                if present != bool(before):
                    self._hold_weight(slot)
                if present and before is False:
                    self._on_inserted(slot)
                elif not present and before:
                    self._on_removed(slot)
        self._present = presence
        active = self.active
        # _was_active survives reconnects and Off, so a print that ended meanwhile is still handled.
        print_ended = self._was_active and not active
        self._was_active = active
        self._primed = True
        self.state = replace(self.state, connected=True, off=False, klippy_state="ready")
        self._rebuild()
        self._schedule_publish()
        if print_ended:
            self._on_print_end()
        self._reconcile_weights()

    def _rebuild(self) -> None:
        trays = self._trays()
        tray_now = _int(self._status.get("tray_now"))
        loaded = tray_now - TRAY_NOW_BASE if tray_now is not None and 0 <= tray_now - TRAY_NOW_BASE < SLOTS else None
        threshold = self.low_stock_g()
        lanes = []
        for slot in range(SLOTS) if trays is not None else []:
            tray = trays.get(slot) or {}
            present = spool_present(tray)
            spool_id = self._assignments.get(slot) if present else None
            meta = self.spool_meta(spool_id) if spool_id is not None else None
            tray_color = normalize_color(tray.get("tray_color")) if present else None
            colors = list(meta.colors) if meta is not None and meta.colors else ([tray_color] if tray_color else [])
            remaining = meta.remaining_g if meta is not None else None
            pct = None
            if meta is not None and meta.initial_g and remaining is not None:
                pct = round(max(0.0, min(100.0, remaining / meta.initial_g * 100.0)), 1)
            material = (meta.material if meta is not None else None) or (str(tray.get("tray_type") or "") or None
                                                                          if present else None)
            state = _int(tray.get("state"))
            lanes.append(LaneState(
                lane=lane_name(slot),
                spool_id=spool_id,
                material=material,
                color=colors[0] if colors else None,
                remaining_g=remaining,
                filament_status="In Tool" if slot == loaded else ("Ready" if present else "Empty"),
                status=str(state) if state is not None else None,
                prep=present,
                load=present,
                tool_loaded=slot == loaded,
                low_stock=remaining is not None and remaining < threshold,
                remaining_pct=pct,
                colors=colors,
                settings_pending=slot in self._pending_settings and spool_id is not None,
            ))
        state_text = str(self._status.get("state") or "").upper()
        progress = self._status.get("progress")
        filename = self._status.get("subtask_name") or self._status.get("current_print")
        self.state = replace(
            self.state,
            print_state=PRINT_STATES.get(state_text, state_text.lower() or None),
            progress=round(float(progress) / 100.0, 3) if isinstance(progress, (int, float)) else None,
            filename=str(filename) if filename else None,
            afc_state=None,
            afc_error=hms_text(self._status.get("hms_errors")),
            current_load=lane_name(loaded) if loaded is not None else None,
            lanes=lanes,
        )

    def refresh(self) -> None:
        """Recompute derived fields (spool details from the catalog, low stock)."""
        if self._status:
            self._rebuild()
        self._publish_now()
        self._reconcile_weights()

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

    def _cancel_inserts(self) -> None:
        for task in self._inserts.values():
            task.cancel()
        self._inserts.clear()

    def _mark_offline(self, reason: str) -> None:
        """Bambuddy is unreachable: an error, like Moonraker offline. Disarms (dev plan §6.3)."""
        self._primed = False
        self._cancel_inserts()
        if self.state.connected or self.state.off or self.state.klippy_state != reason \
                or self.state.pending_spool is not None:
            if self.state.pending_spool is not None:
                log.info("%s: offline (%s); disarmed next spool %d", self.printer.name, reason,
                         self.state.pending_spool)
            self.state = replace(self.state, connected=False, off=False, klippy_state=reason,
                                 pending_spool=None, pending_confirmed=False)
            self._publish_now()

    def _mark_off(self) -> None:
        """The printer is switched off while Bambuddy runs: shown as Off, skipped by Load, disarmed."""
        self._primed = False
        self._cancel_inserts()
        if not self.state.off or self.state.connected or self.state.pending_spool is not None:
            self.state = replace(self.state, connected=False, off=True, klippy_state="off",
                                 pending_spool=None, pending_confirmed=False)
            self._publish_now()

    # ---- next spool (armed) -------------------------------------------------------

    async def set_next_spool(self, spool_id: int | None) -> CommandResult:
        """Arm (or disarm) locally; nothing is sent until a spool goes into a slot."""
        if spool_id is not None and not self.online:
            raise PrinterOffline(f"{self.label} is {'off' if self.state.off else 'offline'}")
        if self.state.pending_spool != spool_id or self.state.pending_confirmed != (spool_id is not None):
            self.state = replace(self.state, pending_spool=spool_id, pending_confirmed=spool_id is not None)
            self._publish_now()
        return CommandResult(dry_run=False)

    def _disarm(self, expected: int | None = None) -> None:
        """Clear the armed spool; with `expected`, only if that spool is still the one armed."""
        if self.state.pending_spool is not None and (expected is None or self.state.pending_spool == expected):
            self.state = replace(self.state, pending_spool=None, pending_confirmed=False)
            self._publish_now()

    def _on_inserted(self, slot: int) -> None:
        """A slot filled. Only a spool armed at that moment may go there, never one armed during the settle."""
        task = self._inserts.pop(slot, None)
        if task is not None:
            task.cancel()
        armed = self.state.pending_spool
        if armed is None:
            return
        task = asyncio.get_running_loop().create_task(self._handle_insert(slot, armed))
        self._inserts[slot] = task
        task.add_done_callback(lambda done, slot=slot: self._inserts.pop(slot, None)
                               if self._inserts.get(slot) is done else None)

    def _on_removed(self, slot: int) -> None:
        task = self._inserts.pop(slot, None)
        if task is not None:
            task.cancel()
        self._pending_settings.discard(slot)

    def _notice(self, message: str, spool_id: int | None = None) -> None:
        log.warning("%s: %s", self.printer.name, message)
        self.on_notice(PrinterNotice(self.key, message, spool_id=spool_id))

    def _still_armed(self, slot: int, armed: int) -> bool:
        return self.online and bool(self._present.get(slot)) and self.state.pending_spool == armed

    async def _handle_insert(self, slot: int, armed: int) -> None:
        # Give Bambuddy time to match an RFID spool it knows before the armed spool is used.
        await asyncio.sleep(self.insert_settle_s)
        # One insertion at a time claims the armed spool: two slots filled together never both get it.
        async with self._insert_lock:
            if not self._still_armed(slot, armed):
                return
            lane = lane_name(slot)
            try:
                await self._load_assignments()
            except (PrinterCommandError, PrinterOffline, asyncio.TimeoutError) as error:
                self._notice(f"{lane}: slot assignments not read ({error}); next spool kept")
                return
            if not self._still_armed(slot, armed):
                return
            assigned = self._assignments.get(slot)
            tag = tray_tag(self._tray(slot))
            if tag is not None and assigned is not None:
                if assigned != armed:
                    self._notice(f"{self.label} {lane} holds #{assigned} (RFID), not #{armed}; "
                                 f"#{armed} stays next spool", spool_id=armed)
                else:
                    self._disarm(armed)
                    self.on_lane_loaded(LaneLoad(self.key, lane, armed, previous=assigned))
                return
            if tag is not None and not await self._link_tag(slot, tag, armed):
                return
            await self._assign_inserted(slot, armed, previous=assigned, linked=tag is not None)

    async def _link_tag(self, slot: int, tag: str, spool_id: int) -> bool:
        """An RFID spool Spoolman doesn't know yet: record its tag on the scanned spool (learned for next time)."""
        if not self.writes:
            return True
        try:
            await self._request("PATCH", f"/spoolman/inventory/spools/{spool_id}/tag", {"tray_uuid": tag})
        except PrinterCommandError as error:
            if error.code == CONFLICT:
                self._notice(f"The RFID tag in {self.label} {lane_name(slot)} belongs to another spool ({error}); "
                             f"#{spool_id} not assigned", spool_id=spool_id)
            else:
                self._notice(f"RFID tag in {lane_name(slot)} not linked to #{spool_id}: {error}", spool_id=spool_id)
            return False
        except (PrinterOffline, asyncio.TimeoutError) as error:
            self._notice(f"RFID tag in {lane_name(slot)} not linked to #{spool_id}: {error or 'no reply'}",
                         spool_id=spool_id)
            return False
        return True

    async def _assign_inserted(self, slot: int, spool_id: int, *, previous: int | None, linked: bool) -> None:
        lane = lane_name(slot)
        what = f"#{spool_id} to {self.label} {lane}" + (" (RFID tag learned)" if linked else "")
        if not self.writes:
            log.info("%s: writes off, would assign %s", self.printer.name, what)
            self._disarm(spool_id)
            self.on_lane_loaded(LaneLoad(self.key, lane, spool_id, assigned=True, dry_run=True, armed=spool_id,
                                         previous=previous, note=f"Dry run: would assign {what}"))
            return
        self._own[slot] = spool_id
        try:
            await self._post_assignment(slot, spool_id)
        except (PrinterCommandError, PrinterOffline, asyncio.TimeoutError) as error:
            self._own.pop(slot, None)
            self._notice(f"#{spool_id} not assigned to {lane}: {error or 'no reply'}; it stays next spool",
                         spool_id=spool_id)
            return
        self._disarm(spool_id)
        self._after_assign(slot, spool_id)
        self.on_lane_loaded(LaneLoad(self.key, lane, spool_id, assigned=True, armed=spool_id, previous=previous,
                                     note=f"assigned {what}"))

    async def _post_assignment(self, slot: int, spool_id: int) -> None:
        await self._request("POST", "/spoolman/inventory/slot-assignments", {
            "spoolman_spool_id": spool_id, "printer_id": self.printer_id, "ams_id": AMS_3H, "tray_id": slot,
            "move": True,
        })
        await self._load_assignments()
        self._rebuild()
        self._publish_now()

    # ---- slot settings (refused while printing) -----------------------------------

    def _settings_match(self, slot: int, spool_id: int) -> bool:
        meta = self.spool_meta(spool_id)
        tray_color = normalize_color(self._tray(slot).get("tray_color"))
        if meta is None or not meta.colors or tray_color is None:
            return True
        return meta.colors[0].upper() == tray_color.upper()

    def _after_assign(self, slot: int, spool_id: int) -> None:
        if self.active:
            self._mark_settings_pending(slot)
        else:
            self._spawn(self._check_settings(slot, spool_id, retried=False))

    def _mark_settings_pending(self, slot: int) -> None:
        self._pending_settings.add(slot)
        self._rebuild()
        self._publish_now()

    async def _check_settings(self, slot: int, spool_id: int, *, retried: bool) -> None:
        await asyncio.sleep(self.settings_check_s)
        if self._assignments.get(slot) != spool_id or not self._present.get(slot):
            return
        if self._settings_match(slot, spool_id):
            return
        if self.active and not retried:
            self._mark_settings_pending(slot)
        else:
            self._notice(f"{self.label} {lane_name(slot)} did not take the settings of #{spool_id}; "
                         f"set the slot in Bambuddy", spool_id=spool_id)

    def _on_print_end(self) -> None:
        spools = set(self._assignments.values())
        self.spool_refresh(spools)
        self._spawn(self._refresh_later(spools))
        # Spoolman learns the print's usage later; until then its grams are older than the printer's.
        self._weights_hold_until = self._now() + self.usage_refresh_s + self.settings_check_s
        pending, self._pending_settings = self._pending_settings, set()
        for slot in sorted(pending):
            spool_id = self._assignments.get(slot)
            if spool_id is not None and self._present.get(slot):
                self._spawn(self._resend_settings(slot, spool_id))
        if pending:
            self._rebuild()
            self._publish_now()

    async def _refresh_later(self, spool_ids: set[int]) -> None:
        await asyncio.sleep(self.usage_refresh_s)
        self.spool_refresh(spool_ids)

    async def _resend_settings(self, slot: int, spool_id: int) -> None:
        if not self.writes:
            log.info("%s: writes off, would resend %s settings", self.printer.name, lane_name(slot))
            return
        try:
            await self._post_assignment(slot, spool_id)
        except (PrinterCommandError, PrinterOffline, asyncio.TimeoutError) as error:
            self._notice(f"{lane_name(slot)} settings not resent: {error or 'no reply'}", spool_id=spool_id)
            return
        await self._check_settings(slot, spool_id, retried=True)

    # ---- remaining weight on the printer (MQTT, Bambuddy can't send it) --------------

    def _now(self) -> float:
        return asyncio.get_running_loop().time()

    def _hold_weight(self, slot: int) -> None:
        """A slot changed: let Bambuddy's filament settings land first (Bambu Studio sends the weight after them)."""
        if self.weight_sender is not None:
            self._weight_hold[slot] = self._now() + self.settings_check_s

    def _wake_weights(self, delay: float) -> None:
        when = self._now() + max(delay, 0.0) + 0.01
        if self._weight_timer is not None:
            if self._weight_timer.when() <= when:
                return
            self._weight_timer.cancel()
        self._weight_timer = asyncio.get_running_loop().call_at(when, self._on_weight_timer)

    def _on_weight_timer(self) -> None:
        self._weight_timer = None
        self._reconcile_weights()

    def _desired_weight(self, slot: int) -> tuple[int, int, int] | None:
        """(spool, total g, remain g) from Spoolman for an untagged spool; the printer tracks RFID spools itself."""
        tray = self._tray(slot)
        spool_id = self._assignments.get(slot)
        if spool_id is None or not spool_present(tray) or tray_tag(tray) is not None or slot in self._pending_settings:
            return None
        meta = self.spool_meta(spool_id)
        if meta is None or meta.archived:
            return None
        weights = filament_weight(meta.remaining_g, meta.initial_g)
        return (spool_id, *weights) if weights is not None else None

    def _reconcile_weights(self) -> None:
        """Send Spoolman's grams to slots whose `remain` % disagrees, while the printer is idle.

        A value the printer accepted is not sent again until Spoolman's grams change, so the printer's own
        count-down is never fought; a failed send is retried after `weight_retry_s`.
        """
        if self.weight_sender is None or not self.online or self.active or not self._primed:
            return
        now = self._now()
        if now < self._weights_hold_until:
            self._wake_weights(self._weights_hold_until - now)
            return
        wake: float | None = None
        for slot in range(SLOTS):
            hold = self._weight_hold.get(slot, 0.0)
            if now < hold:
                wake = hold if wake is None else min(wake, hold)
                continue
            desired = self._desired_weight(slot)
            if desired is None or slot in self._weight_tasks:
                continue
            _, total, remain = desired
            if _int(self._tray(slot).get("remain")) == remain_percent(total, remain):
                continue
            last = self._weight_sent.get(slot)
            if last is not None and last[0] == desired and now < last[1]:
                if last[1] != math.inf:
                    wake = last[1] if wake is None else min(wake, last[1])
                continue
            self._weight_sent[slot] = (desired, math.inf)
            task = asyncio.get_running_loop().create_task(self._send_weight(slot, desired))
            self._weight_tasks[slot] = task
            task.add_done_callback(lambda done, slot=slot: self._weight_tasks.pop(slot, None)
                                   if self._weight_tasks.get(slot) is done else None)
        if wake is not None:
            self._wake_weights(wake - now)

    def _weight_still_wanted(self, slot: int, desired: tuple[int, int, int]) -> bool:
        now = self._now()
        return (self.online and not self.active and now >= self._weights_hold_until
                and now >= self._weight_hold.get(slot, 0.0) and self._desired_weight(slot) == desired)

    async def _send_weight(self, slot: int, desired: tuple[int, int, int]) -> None:
        # One at a time, and checked again once its turn comes: the slot may hold another spool by then.
        async with self._weight_lock:
            await self._send_weight_now(slot, desired)
        self._wake_weights(0.0)

    async def _send_weight_now(self, slot: int, desired: tuple[int, int, int]) -> None:
        assert self.weight_sender is not None
        if not self._weight_still_wanted(slot, desired):
            if self._weight_sent.get(slot, (None, 0.0))[0] == desired:
                del self._weight_sent[slot]
            return
        spool_id, total, remain = desired
        what = f"{self.label} {lane_name(slot)}: #{spool_id} {remain} g of {total} g"
        if not self.writes:
            log.info("%s: writes off, would send the remaining weight %s", self.printer.name, what)
            return
        try:
            await self.weight_sender.set_filament_weight(self._target, AMS_3H, slot, total, remain)
        except (PrinterCommandError, PrinterOffline, asyncio.TimeoutError, OSError) as error:
            self._weight_sent[slot] = (desired, self._now() + self.weight_retry_s)
            log.warning("%s: remaining weight not sent (%s): %s", self.printer.name, what, error or "no reply")
            return
        log.info("%s: remaining weight sent to the printer, %s", self.printer.name, what)

    # ---- lane assignment ------------------------------------------------------------

    async def set_lane_spool(self, lane: str, spool_id: int | None) -> CommandResult:
        slot = slot_of(lane)
        if slot is None:
            raise PrinterCommandError(f"{self.label} has no slot {lane!r}")
        if not self.writes:
            log.info("%s: writes off, would %s %s", self.printer.name,
                     "unassign" if spool_id is None else f"assign #{spool_id} to", lane)
            return CommandResult(dry_run=True)
        if not self.online:
            raise PrinterOffline(f"{self.label} is offline")
        if spool_id is None:
            current = self._assignments.get(slot)
            if current is not None:
                await self._request("DELETE", f"/spoolman/inventory/slot-assignments/{current}")
                await self._load_assignments()
        else:
            await self._post_assignment(slot, spool_id)
            self._pending_settings.discard(slot)
            self._after_assign(slot, spool_id)
        self._rebuild()
        self._publish_now()
        return CommandResult(dry_run=False)
