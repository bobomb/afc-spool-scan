"""Fixture-driven fake Moonraker + AFC for --printers sim and tests.

Mimics the JSON-RPC subset the station uses and AFC v1.1.0 semantics for
SET_NEXT_SPOOL_ID / SET_SPOOL_ID (messages, consume-on-load, duplicate check).
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import shlex
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "printers"

SpoolLookup = Callable[[int], "dict[str, Any] | None"]


def load_printer_fixture(key: str, directory: Path = FIXTURES) -> dict[str, Any]:
    return json.loads((directory / f"{key}.json").read_text(encoding="utf-8"))


class RpcError(Exception):
    def __init__(self, message: str, code: int = 400) -> None:
        super().__init__(message)
        self.code = code


def parse_gcode(line: str) -> tuple[str, dict[str, str]]:
    parts = shlex.split(line.strip())
    if not parts:
        return "", {}
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, _, value = part.partition("=")
        params[key.upper()] = value
    return parts[0].upper(), params


class SimPrinter:
    def __init__(self, key: str, fixture: dict[str, Any], spool_lookup: SpoolLookup | None = None) -> None:
        self.key = key
        self.objects: dict[str, dict[str, Any]] = copy.deepcopy(fixture["objects"])
        self.object_list: list[str] = list(fixture.get("object_list") or self.objects)
        self.server_info: dict[str, Any] = dict(fixture.get("server_info") or {})
        self.spool_lookup = spool_lookup
        self.next_spool_id: int | None = None
        self.online = True
        self.klippy_state = "ready"
        self.sockets: dict[web.WebSocketResponse, dict[str, list[str] | None]] = {}
        self.gcode_log: list[str] = []
        self.lane_prefix = next(
            (name.split(" ", 1)[0] for name in self.objects if name.startswith(("AFC_stepper ", "AFC_lane "))),
            "AFC_stepper",
        )

    def lane_object(self, lane: str) -> dict[str, Any]:
        name = f"{self.lane_prefix} {lane}"
        if name not in self.objects:
            raise KeyError(lane)
        return self.objects[name]

    @property
    def lanes(self) -> list[str]:
        return list(self.objects.get("AFC", {}).get("lanes", []))

    def _filtered(self, objects: dict[str, list[str] | None]) -> dict[str, Any]:
        status: dict[str, Any] = {}
        for name, fields in objects.items():
            if name not in self.objects:
                continue
            data = self.objects[name]
            status[name] = copy.deepcopy(data if fields is None else {f: data[f] for f in fields if f in data})
        return status

    async def _send(self, ws: web.WebSocketResponse, message: dict[str, Any]) -> None:
        with contextlib.suppress(ConnectionError, RuntimeError):
            await ws.send_str(json.dumps(message))

    async def notify(self, method: str, params: list[Any]) -> None:
        for ws in list(self.sockets):
            await self._send(ws, {"jsonrpc": "2.0", "method": method, "params": params})

    async def respond(self, line: str) -> None:
        await self.notify("notify_gcode_response", [line])

    async def update(self, diff: dict[str, dict[str, Any]]) -> None:
        for name, fields in diff.items():
            self.objects.setdefault(name, {}).update(copy.deepcopy(fields))
        for ws, subscription in list(self.sockets.items()):
            filtered = {
                name: {k: v for k, v in fields.items() if subscription.get(name) is None or k in subscription[name]}
                for name, fields in diff.items()
                if name in subscription
            }
            if filtered:
                await self._send(ws, {"jsonrpc": "2.0", "method": "notify_status_update",
                                      "params": [filtered, time.monotonic()]})

    def _lane_fields_for_spool(self, spool_id: int | None) -> dict[str, Any]:
        if spool_id is None:
            return {"spool_id": None, "material": "", "color": "", "weight": 0}
        spool = self.spool_lookup(spool_id) if self.spool_lookup else None
        if not spool:
            return {"spool_id": spool_id}
        filament = spool.get("filament") or {}
        multi = filament.get("multi_color_hexes")
        color = multi.split(",")[0] if multi else filament.get("color_hex", "")
        return {
            "spool_id": spool_id,
            "material": filament.get("material", ""),
            "color": f"#{color}" if color else "",
            "weight": spool.get("remaining_weight") or 0,
        }

    async def run_gcode(self, script: str) -> None:
        for raw in script.splitlines():
            if not raw.strip():
                continue
            self.gcode_log.append(raw.strip())
            command, params = parse_gcode(raw)
            if command == "SET_NEXT_SPOOL_ID":
                await self._set_next_spool_id(params.get("SPOOL_ID", ""))
            elif command == "SET_SPOOL_ID":
                await self._set_spool_id(params.get("LANE"), params.get("SPOOL_ID", ""))
            else:
                raise RpcError(f'Unknown command:"{command}"')

    async def _set_next_spool_id(self, value: str) -> None:
        previous = self.next_spool_id
        if value != "":
            try:
                self.next_spool_id = int(value)
            except ValueError:
                await self.respond(f"!! Invalid spool ID: {value}")
                self.next_spool_id = None
        else:
            self.next_spool_id = None
        if previous:
            await self.respond(f"Spool ID '{previous}' being overwritten for next load: '{self.next_spool_id}'")
        else:
            await self.respond(f"Spool ID set for next load: '{self.next_spool_id}'")

    async def _set_spool_id(self, lane: str | None, value: str) -> None:
        if lane is None:
            await self.respond("No LANE Defined")
            return
        if lane not in self.lanes:
            await self.respond(f"{lane} Unknown")
            return
        spool_id: int | None = None
        if value != "":
            try:
                spool_id = int(value)
            except ValueError:
                await self.respond(f"!! Invalid spool ID: {value}")
                return
            current = self.lane_object(lane).get("spool_id")
            others = [self.lane_object(other).get("spool_id") for other in self.lanes if other != lane]
            if current != spool_id and spool_id in others:
                await self.respond(f"!! SpoolId {spool_id} already assigned to a lane, cannot assign to {lane}.")
                return
        await self.update({f"{self.lane_prefix} {lane}": self._lane_fields_for_spool(spool_id)})

    async def set_lane(self, lane: str, spool_id: int | None | str = "keep", **fields: Any) -> None:
        diff: dict[str, Any] = {}
        if spool_id != "keep":
            diff.update(self._lane_fields_for_spool(spool_id))  # type: ignore[arg-type]
        diff.update({k: v for k, v in fields.items() if v is not None})
        await self.update({f"{self.lane_prefix} {lane}": diff})

    async def insert_lane(self, lane: str) -> None:
        """Simulate inserting filament: AFC tags the lane with the pending next spool."""
        diff: dict[str, Any] = {"prep": True, "load": True, "filament_status": "Ready", "status": "Loaded"}
        if self.next_spool_id is not None:
            diff.update(self._lane_fields_for_spool(self.next_spool_id))
            self.next_spool_id = None
        await self.update({f"{self.lane_prefix} {lane}": diff})

    async def eject_lane(self, lane: str) -> None:
        diff = {"prep": False, "load": False, "tool_loaded": False, "filament_status": "Not Ready",
                "status": "None", **self._lane_fields_for_spool(None)}
        await self.update({f"{self.lane_prefix} {lane}": diff})

    async def set_print(self, state: str | None = None, progress: float | None = None,
                        filename: str | None = None) -> None:
        diff: dict[str, dict[str, Any]] = {}
        if state is not None or filename is not None:
            diff["print_stats"] = {k: v for k, v in (("state", state), ("filename", filename)) if v is not None}
        if progress is not None:
            diff["display_status"] = {"progress": progress}
        await self.update(diff)

    async def set_afc_error(self, message: str | None) -> None:
        if message:
            await self.update({"AFC": {"error_state": True, "current_state": "Error",
                                       "message": {"message": message, "type": "error"}}})
        else:
            await self.update({"AFC": {"error_state": False, "current_state": "Idle",
                                       "message": {"message": "", "type": ""}}})

    async def disconnect(self) -> None:
        """Simulates a power-off or reboot: Moonraker goes away and AFC forgets the pending spool."""
        self.online = False
        self.next_spool_id = None
        for ws in list(self.sockets):
            await ws.close()

    def connect(self) -> None:
        self.online = True

    async def restart_klippy(self) -> None:
        self.klippy_state = "startup"
        self.next_spool_id = None
        await self.notify("notify_klippy_disconnected", [])
        await asyncio.sleep(0)
        self.klippy_state = "ready"
        await self.notify("notify_klippy_ready", [])

    async def handle(self, request: web.Request) -> web.StreamResponse:
        if not self.online:
            return web.Response(status=503, text="printer offline (simulated)")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets[ws] = {}
        tasks: set[asyncio.Task[None]] = set()
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(message.data)
                except ValueError:
                    continue
                task = asyncio.create_task(self._dispatch(ws, data))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            self.sockets.pop(ws, None)
            for task in tasks:
                task.cancel()
        return ws

    async def _dispatch(self, ws: web.WebSocketResponse, data: dict[str, Any]) -> None:
        request_id = data.get("id")
        try:
            result = await self._call(ws, data.get("method", ""), data.get("params") or {})
            reply: dict[str, Any] = {"jsonrpc": "2.0", "result": result, "id": request_id}
        except RpcError as error:
            reply = {"jsonrpc": "2.0", "error": {"code": error.code, "message": str(error)}, "id": request_id}
        await self._send(ws, reply)

    async def _call(self, ws: web.WebSocketResponse, method: str, params: dict[str, Any]) -> Any:
        if method == "server.info":
            return {**self.server_info, "klippy_connected": True, "klippy_state": self.klippy_state}
        if method == "server.connection.identify":
            return {"connection_id": id(ws)}
        if self.klippy_state != "ready" and method.startswith("printer."):
            raise RpcError("Klippy Disconnected", 503)
        if method == "printer.objects.list":
            return {"objects": list(self.object_list)}
        if method in ("printer.objects.query", "printer.objects.subscribe"):
            objects = params.get("objects") or {}
            if method == "printer.objects.subscribe":
                self.sockets[ws] = dict(objects)
            return {"eventtime": time.monotonic(), "status": self._filtered(objects)}
        if method == "printer.gcode.script":
            await self.run_gcode(str(params.get("script", "")))
            return "ok"
        raise RpcError(f"Method not found: {method}", -32601)


class SimPrinterServer:
    def __init__(self, printers: dict[str, SimPrinter]) -> None:
        self.printers = printers
        self._runner: web.AppRunner | None = None
        self.base_url = ""

    @classmethod
    def from_fixtures(cls, keys: list[str], spool_lookup: SpoolLookup | None = None,
                      directory: Path = FIXTURES) -> SimPrinterServer:
        printers = {}
        available = sorted(path.stem for path in directory.glob("*.json"))
        for index, key in enumerate(keys):
            fixture_key = key if key in available else available[index % len(available)]
            printers[key] = SimPrinter(key, load_printer_fixture(fixture_key, directory), spool_lookup)
        return cls(printers)

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        printer = self.printers.get(request.match_info["key"])
        if printer is None:
            raise web.HTTPNotFound()
        return await printer.handle(request)

    def url_for(self, key: str) -> str:
        return f"{self.base_url}/{key}/websocket"

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> str:
        app = web.Application()
        app.router.add_get("/{key}/websocket", self._handle)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        bound = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self.base_url = f"ws://{host}:{bound}"
        return self.base_url

    async def stop(self) -> None:
        for printer in self.printers.values():
            for ws in list(printer.sockets):
                await ws.close()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
