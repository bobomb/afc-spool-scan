"""Fixture-driven fake Bambuddy (REST + websocket subset) for --printers sim and tests.

Mimics Bambuddy 1.3.1 as the station uses it: printer status with an AMS 3H
(ams_id 32, trays 0-8), Spoolman slot assignments (move, archived check,
spool_assignment_changed), the RFID tag link (409 when another spool holds
the tag), ws-token auth and the websocket push of printer_status. Slot
settings are refused while printing, and a slot left empty is unassigned
after `auto_unassign_s` unless a print runs.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bambuddy"
AMS_3H = 32
SLOTS = 9
TRAY_NOW_BASE = 28
ACTIVE = frozenset({"RUNNING", "PREPARE", "SLICING", "PAUSE"})
WS_UNAUTHORIZED = 4401

SpoolLookup = Callable[[int], "dict[str, Any] | None"]


def load_bambuddy_fixture(key: str, directory: Path = FIXTURES) -> dict[str, Any]:
    return json.loads((directory / f"{key}.json").read_text(encoding="utf-8"))


SECRET_KEYS = frozenset({"serial_number", "sn", "ip_address", "access_code", "dev_id", "token", "api_key",
                         "cover_url", "external_camera_url"})
TAG_KEYS = frozenset({"tray_uuid", "tag_uid"})
FILE_KEYS = frozenset({"current_print", "subtask_name", "gcode_file", "filename"})


def scrub_capture(value: Any, name: str, key: str = "") -> Any:
    """Captured Bambuddy data without serials, addresses, tokens, real tag IDs, file names or the real name.

    Tags map to stable fake IDs of the same length, so a tag seen twice still matches itself.
    """
    if isinstance(value, dict):
        return {k: scrub_capture(v, name, k) for k, v in value.items() if k not in SECRET_KEYS}
    if isinstance(value, list):
        return [scrub_capture(item, name, key) for item in value]
    if isinstance(value, str) and value:
        if key in TAG_KEYS and set(value) != {"0"}:
            digest = hashlib.sha256(f"station-capture:{value.upper()}".encode()).hexdigest().upper()
            return digest[: len(value)]
        if key in FILE_KEYS:
            return "capture_plate_1"
        if key in ("name", "printer_name"):
            return name
    return value


def empty_tray(slot: int) -> dict[str, Any]:
    return {"id": slot, "tray_color": None, "tray_type": None, "tray_sub_brands": None, "tray_uuid": None,
            "tag_uid": None, "remain": 0, "state": 9, "exists": False}


def _error(status: int, detail: Any) -> web.Response:
    return web.json_response({"detail": detail}, status=status)


class SimBambuddyPrinter:
    def __init__(self, printer_id: int, fixture: dict[str, Any]) -> None:
        self.id = printer_id
        self.name: str = fixture.get("name") or f"Printer {printer_id}"
        self.model: str = fixture.get("model") or "H3C"
        self.status: dict[str, Any] = copy.deepcopy(fixture["status"])
        self.status.setdefault("connected", True)
        self.assignments: dict[int, int] = {int(k): int(v) for k, v in (fixture.get("assignments") or {}).items()}
        self.refused: list[int] = []
        trays = {int(t["id"]): t for t in self.unit().get("tray") or []}
        self.unit()["tray"] = [trays.get(slot) or empty_tray(slot) for slot in range(SLOTS)]

    def unit(self) -> dict[str, Any]:
        for unit in self.status.setdefault("ams", []):
            if unit.get("id") == AMS_3H:
                return unit
        unit = {"id": AMS_3H, "tray": []}
        self.status["ams"].append(unit)
        return unit

    def tray(self, slot: int) -> dict[str, Any]:
        return self.unit()["tray"][slot]

    @property
    def printing(self) -> bool:
        return str(self.status.get("state") or "").upper() in ACTIVE

    def status_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, **copy.deepcopy(self.status)}

    def assignment_rows(self) -> list[dict[str, Any]]:
        return [{"printer_id": self.id, "printer_name": self.name, "ams_id": AMS_3H, "tray_id": slot,
                 "spoolman_spool_id": spool, "ams_label": None, "printer_model": self.model}
                for slot, spool in sorted(self.assignments.items())]


class SimBambuddy:
    def __init__(
        self,
        printers: dict[int, SimBambuddyPrinter],
        spool_lookup: SpoolLookup | None = None,
        *,
        api_key: str | None = None,
        tags: dict[str, int] | None = None,
        auto_unassign_s: float = 120.0,
        rfid_delay_s: float = 0.0,
    ) -> None:
        self.printers = printers
        self.spool_lookup = spool_lookup
        self.api_key = api_key
        self.tags: dict[str, int] = {k.upper(): v for k, v in (tags or {}).items()}
        self.auto_unassign_s = auto_unassign_s
        self.rfid_delay_s = rfid_delay_s
        self.online = True
        self.requests: list[tuple[str, str, Any]] = []
        self.sockets: set[web.WebSocketResponse] = set()
        self._tokens: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._unassign: dict[tuple[int, int], asyncio.Task[None]] = {}
        self._runner: web.AppRunner | None = None
        self.base_url = ""

    @classmethod
    def from_fixtures(cls, printers: dict[int, str], spool_lookup: SpoolLookup | None = None,
                      directory: Path = FIXTURES, **options: Any) -> SimBambuddy:
        """`printers` maps Bambuddy printer ids to fixture names (falls back to the first fixture)."""
        available = sorted(path.stem for path in directory.glob("*.json"))
        built: dict[int, SimBambuddyPrinter] = {}
        tags: dict[str, int] = dict(options.pop("tags", None) or {})
        for printer_id, key in printers.items():
            fixture = load_bambuddy_fixture(key if key in available else available[0], directory)
            built[printer_id] = SimBambuddyPrinter(printer_id, fixture)
            tags.update({k: int(v) for k, v in (fixture.get("tags") or {}).items()})
        return cls(built, spool_lookup, tags=tags, **options)

    # ---- helpers -------------------------------------------------------------

    def _spawn(self, coro: Any) -> asyncio.Task[None]:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def broadcast(self, message: dict[str, Any]) -> None:
        for ws in list(self.sockets):
            with contextlib.suppress(ConnectionError, RuntimeError):
                await ws.send_str(json.dumps(message))

    async def push(self, printer: SimBambuddyPrinter) -> None:
        await self.broadcast({"type": "printer_status", "printer_id": printer.id, "data": printer.status_dict()})

    async def _announce(self, printer_id: int, slots: list[int]) -> None:
        for slot in slots:
            await self.broadcast({"type": "spool_assignment_changed", "printer_id": printer_id, "ams_id": AMS_3H,
                                  "tray_id": slot})

    def _printer(self, printer_id: int) -> SimBambuddyPrinter:
        printer = self.printers.get(printer_id)
        if printer is None:
            raise KeyError(printer_id)
        return printer

    def _spool(self, spool_id: int) -> dict[str, Any] | None:
        return self.spool_lookup(spool_id) if self.spool_lookup else {"id": spool_id, "filament": {}}

    def _apply_settings(self, printer: SimBambuddyPrinter, slot: int, spool: dict[str, Any]) -> None:
        """The MQTT push of material/colour; the printer refuses it during a print, as the H3C does."""
        tray = printer.tray(slot)
        if not tray.get("exists"):
            return
        if not printer.status.get("connected", True) or printer.printing:
            printer.refused.append(slot)
            return
        filament = spool.get("filament") or {}
        multi = filament.get("multi_color_hexes")
        color = (multi.split(",")[0] if isinstance(multi, str) and multi else filament.get("color_hex")) or "FFFFFF"
        tray.update(tray_type=filament.get("material") or "PLA", tray_color=f"{color.upper()}FF",
                    tray_sub_brands=filament.get("name") or "")

    async def assign(self, printer_id: int, slot: int, spool_id: int, move: bool = True) -> list[int]:
        printer = self._printer(printer_id)
        changed = [slot]
        if move:
            for other in [s for s, sid in printer.assignments.items() if sid == spool_id and s != slot]:
                del printer.assignments[other]
                changed.append(other)
        printer.assignments[slot] = spool_id
        self._cancel_unassign(printer_id, slot)
        await self._announce(printer_id, changed)
        spool = self._spool(spool_id)
        if spool is not None:
            self._apply_settings(printer, slot, spool)
        await self.push(printer)
        return changed

    def _cancel_unassign(self, printer_id: int, slot: int) -> None:
        task = self._unassign.pop((printer_id, slot), None)
        if task is not None:
            task.cancel()

    async def _auto_unassign(self, printer: SimBambuddyPrinter, slot: int) -> None:
        await asyncio.sleep(self.auto_unassign_s)
        self._unassign.pop((printer.id, slot), None)
        if printer.tray(slot).get("exists") or printer.printing or slot not in printer.assignments:
            return
        del printer.assignments[slot]
        await self._announce(printer.id, [slot])

    # ---- simulation controls ------------------------------------------------

    async def insert(self, printer_id: int, slot: int, *, material: str = "PLA", color: str = "808080",
                     tray_uuid: str | None = None) -> None:
        """A spool goes into an AMS 3H slot. An RFID spool reports its tag; Bambuddy matches known tags."""
        printer = self._printer(printer_id)
        tag = tray_uuid.upper() if tray_uuid else None
        printer.tray(slot).update(
            tray_type=material, tray_color=f"{color.lstrip('#').upper()[:6]}FF", tray_sub_brands="",
            tray_uuid=tag, tag_uid=tag[:16] if tag else None, remain=100 if tag else -1,
            state=283 if tag else 27, exists=True,
        )
        self._cancel_unassign(printer_id, slot)
        await self.push(printer)
        if tag is None:
            return
        if tag in self.tags:
            self._spawn(self._rfid_match(printer, slot, self.tags[tag]))
        else:
            tray = printer.tray(slot)
            await self.broadcast({"type": "unknown_tag", "printer_id": printer_id, "ams_id": AMS_3H, "tray_id": slot,
                                  "tag_uid": tray["tag_uid"], "tray_uuid": tag, "tray_type": tray["tray_type"],
                                  "tray_color": tray["tray_color"], "tray_sub_brands": ""})

    async def _rfid_match(self, printer: SimBambuddyPrinter, slot: int, spool_id: int) -> None:
        await asyncio.sleep(self.rfid_delay_s)
        if printer.tray(slot).get("exists"):
            await self.assign(printer.id, slot, spool_id)

    async def eject(self, printer_id: int, slot: int) -> None:
        printer = self._printer(printer_id)
        printer.tray(slot).update(empty_tray(slot))
        if printer.status.get("tray_now") == TRAY_NOW_BASE + slot:
            printer.status["tray_now"] = 255
        await self.push(printer)
        if slot in printer.assignments:
            self._cancel_unassign(printer_id, slot)
            self._unassign[(printer_id, slot)] = self._spawn(self._auto_unassign(printer, slot))

    async def set_print(self, printer_id: int, state: str | None = None, progress: float | None = None,
                        filename: str | None = None) -> None:
        printer = self._printer(printer_id)
        if state is not None:
            printer.status["state"] = state.upper()
        if progress is not None:
            printer.status["progress"] = progress
        if filename is not None:
            printer.status["subtask_name"] = printer.status["current_print"] = filename
        await self.push(printer)

    async def set_tool(self, printer_id: int, slot: int | None) -> None:
        printer = self._printer(printer_id)
        printer.status["tray_now"] = 255 if slot is None else TRAY_NOW_BASE + slot
        await self.push(printer)

    async def set_hms(self, printer_id: int, description: str | None, severity: int = 2) -> None:
        printer = self._printer(printer_id)
        printer.status["hms_errors"] = [] if not description else [
            {"code": "0700_2000", "attr": 0, "module": 7, "severity": severity, "actions": [], "job_id": None,
             "full_code": "0700200000020001", "description": description}]
        await self.push(printer)

    async def power(self, printer_id: int, on: bool) -> None:
        """The printer is switched off or on; Bambuddy stays up and reports it disconnected."""
        printer = self._printer(printer_id)
        printer.status["connected"] = on
        await self.push(printer)

    async def disconnect(self) -> None:
        """Bambuddy itself goes away."""
        self.online = False
        for ws in list(self.sockets):
            await ws.close()

    def connect(self) -> None:
        self.online = True

    # ---- HTTP ------------------------------------------------------------------

    @web.middleware
    async def _middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        if request.path == "/api/v1/ws":
            return await handler(request)
        body = None
        if request.can_read_body:
            try:
                body = await request.json()
            except ValueError:
                return _error(400, "Invalid JSON")
        self.requests.append((request.method, request.path_qs, body))
        if not self.online:
            return _error(503, "Bambuddy is offline (simulated)")
        if self.api_key is not None and request.headers.get("X-API-Key") != self.api_key:
            return _error(401, "Not authenticated")
        return await handler(request)

    def _printer_from(self, request: web.Request, key: str = "printer_id") -> SimBambuddyPrinter | None:
        raw = request.match_info.get(key) or request.query.get(key) or ""
        return self.printers.get(int(raw)) if raw.isdigit() else None

    async def _printers(self, request: web.Request) -> web.Response:
        return web.json_response([{"id": p.id, "name": p.name, "model": p.model} for p in self.printers.values()])

    async def _status(self, request: web.Request) -> web.Response:
        printer = self._printer_from(request)
        if printer is None:
            return _error(404, "Printer not found")
        return web.json_response(printer.status_dict())

    async def _assignments(self, request: web.Request) -> web.Response:
        printer_id = request.query.get("printer_id")
        rows = [row for p in self.printers.values() if printer_id is None or str(p.id) == printer_id
                for row in p.assignment_rows()]
        return web.json_response(rows)

    @staticmethod
    async def _body(request: web.Request) -> Any:
        return await request.json() if request.body_exists else None

    async def _assign(self, request: web.Request) -> web.Response:
        body = await self._body(request)
        if not isinstance(body, dict):
            return _error(422, "Expected an object")
        spool_id, printer_id = body.get("spoolman_spool_id"), body.get("printer_id")
        ams_id, slot = body.get("ams_id"), body.get("tray_id")
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in (spool_id, printer_id, ams_id, slot)):
            return _error(422, "spoolman_spool_id, printer_id, ams_id and tray_id are required")
        if ams_id != AMS_3H or not 0 <= slot < SLOTS:
            return _error(422, "Invalid slot")
        if printer_id not in self.printers:
            return _error(404, "Printer not found")
        spool = self._spool(spool_id)
        if spool is None:
            return _error(404, f"Spool {spool_id} not found")
        if spool.get("archived"):
            return _error(400, "Cannot assign an archived spool")
        await self.assign(printer_id, slot, spool_id, move=bool(body.get("move")))
        return web.json_response({"id": spool_id, "material": (spool.get("filament") or {}).get("material")})

    async def _unassign_spool(self, request: web.Request) -> web.Response:
        spool_id = int(request.match_info["spool_id"])
        for printer in self.printers.values():
            slots = [slot for slot, sid in printer.assignments.items() if sid == spool_id]
            for slot in slots:
                del printer.assignments[slot]
            if slots:
                await self._announce(printer.id, slots)
        return web.json_response({"status": "ok"})

    async def _link_tag(self, request: web.Request) -> web.Response:
        spool_id = int(request.match_info["spool_id"])
        body = await self._body(request)
        body = body if isinstance(body, dict) else {}
        raw = body.get("tray_uuid") or body.get("tag_uid")
        if not isinstance(raw, str) or not raw:
            return _error(422, "tray_uuid or tag_uid is required")
        tag = raw.upper()
        if self._spool(spool_id) is None:
            return _error(404, f"Spool {spool_id} not found")
        holder = self.tags.get(tag)
        if holder is not None and holder != spool_id:
            field = "tray_uuid" if body.get("tray_uuid") else "tag_uid"
            return _error(409, {"code": "tag_already_linked", "field": field, "spool_id": holder,
                                "message": f"{field} is already linked to spool {holder}"})
        self.tags[tag] = spool_id
        return web.json_response({"id": spool_id, "tag": tag})

    async def _ws_token(self, request: web.Request) -> web.Response:
        token = secrets.token_hex(16)
        self._tokens.add(token)
        return web.json_response({"token": token})

    async def _ws(self, request: web.Request) -> web.StreamResponse:
        if not self.online:
            return web.Response(status=503, text="Bambuddy is offline (simulated)")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        if self.api_key is not None and request.query.get("token") not in self._tokens:
            await ws.close(code=WS_UNAUTHORIZED, message=b"unauthorized")
            return ws
        self.sockets.add(ws)
        try:
            for printer in self.printers.values():
                await ws.send_str(json.dumps({"type": "printer_status", "printer_id": printer.id,
                                              "data": printer.status_dict()}))
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                with contextlib.suppress(ValueError):
                    if json.loads(message.data).get("type") == "ping":
                        await ws.send_str(json.dumps({"type": "pong"}))
        finally:
            self.sockets.discard(ws)
        return ws

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self._middleware])
        base = "/api/v1"
        app.router.add_get(f"{base}/printers/", self._printers)
        app.router.add_get(f"{base}/printers/{{printer_id}}/status", self._status)
        app.router.add_get(f"{base}/spoolman/inventory/slot-assignments/all", self._assignments)
        app.router.add_post(f"{base}/spoolman/inventory/slot-assignments", self._assign)
        app.router.add_delete(f"{base}/spoolman/inventory/slot-assignments/{{spool_id:\\d+}}", self._unassign_spool)
        app.router.add_patch(f"{base}/spoolman/inventory/spools/{{spool_id:\\d+}}/tag", self._link_tag)
        app.router.add_post(f"{base}/auth/ws-token", self._ws_token)
        app.router.add_get(f"{base}/ws", self._ws)
        return app

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> str:
        self._runner = web.AppRunner(self.app(), access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        bound = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self.base_url = f"http://{host}:{bound}"
        return self.base_url

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for ws in list(self.sockets):
            await ws.close()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
