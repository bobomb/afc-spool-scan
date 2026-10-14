"""In-memory fake Spoolman (REST subset) seeded from fixtures.

Measure and PATCH follow Spoolman's own rules (tare: spool, filament, vendor).
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PATCHABLE = {"spool_weight", "archived", "used_weight", "remaining_weight", "initial_weight", "location", "comment"}


def load_spool_fixtures(path: Path = FIXTURES / "spoolman" / "spools.json") -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["spools"]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_error(status: int, message: str) -> web.Response:
    return web.json_response({"message": message}, status=status)


class SimSpoolman:
    def __init__(self, spools: list[dict[str, Any]] | None = None) -> None:
        source = load_spool_fixtures() if spools is None else spools
        self.spools: dict[int, dict[str, Any]] = {int(s["id"]): copy.deepcopy(s) for s in source}
        self.online = True
        self.requests: list[tuple[str, str, Any]] = []
        self._runner: web.AppRunner | None = None
        self.base_url = ""

    def get(self, spool_id: int) -> dict[str, Any] | None:
        spool = self.spools.get(spool_id)
        return copy.deepcopy(spool) if spool else None

    def _initial(self, spool: dict[str, Any]) -> float | None:
        initial = spool.get("initial_weight")
        if not initial:
            initial = (spool.get("filament") or {}).get("weight")
        return float(initial) if initial else None

    def _tare(self, spool: dict[str, Any]) -> float:
        filament = spool.get("filament") or {}
        for value in (spool.get("spool_weight"), filament.get("spool_weight"),
                      (filament.get("vendor") or {}).get("empty_spool_weight")):
            if value is not None:
                return float(value)
        return 0.0

    def _recompute(self, spool: dict[str, Any]) -> None:
        initial = self._initial(spool)
        used = float(spool.get("used_weight") or 0.0)
        spool["used_weight"] = round(used, 2)
        spool["remaining_weight"] = None if initial is None else round(max(initial - used, 0.0), 2)

    def measure(self, spool_id: int, weight: float) -> dict[str, Any]:
        spool = self.spools[spool_id]
        initial = self._initial(spool)
        if initial is None:
            raise ValueError("Initial weight is not set.")
        tare = self._tare(spool)
        gross_full = initial + tare
        if weight > gross_full:
            spool["initial_weight"] = round(weight - tare, 2)
            spool["used_weight"] = 0.0
        else:
            spool["used_weight"] = max(gross_full - weight, 0.0)
        now = _now()
        spool["last_used"] = now
        spool.setdefault("first_used", now)
        self._recompute(spool)
        return copy.deepcopy(spool)

    def patch(self, spool_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        spool = self.spools[spool_id]
        unknown = set(fields) - PATCHABLE
        if unknown:
            raise ValueError(f"Unsupported fields: {', '.join(sorted(unknown))}")
        if "used_weight" in fields and "remaining_weight" in fields:
            raise ValueError("Cannot specify both used and remaining weight.")
        for key in ("spool_weight", "initial_weight", "location", "comment", "archived", "used_weight"):
            if key in fields:
                spool[key] = fields[key]
        if "remaining_weight" in fields:
            initial = self._initial(spool)
            if initial is None:
                raise ValueError("Cannot set remaining weight without an initial weight.")
            spool["used_weight"] = max(initial - float(fields["remaining_weight"]), 0.0)
        self._recompute(spool)
        return copy.deepcopy(spool)

    @web.middleware
    async def _middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        body = None
        if request.can_read_body:
            try:
                body = await request.json()
            except ValueError:
                return _json_error(400, "Invalid JSON")
        self.requests.append((request.method, request.path, body))
        if not self.online:
            return _json_error(503, "Spoolman is offline (simulated)")
        return await handler(request)

    @staticmethod
    async def _body(request: web.Request) -> Any:
        return await request.json() if request.body_exists else None

    def _spool_id(self, request: web.Request) -> int | None:
        try:
            spool_id = int(request.match_info["spool_id"])
        except ValueError:
            return None
        return spool_id if spool_id in self.spools else None

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "healthy"})

    async def _get(self, request: web.Request) -> web.Response:
        spool_id = self._spool_id(request)
        if spool_id is None:
            return _json_error(404, f"No spool with ID {request.match_info['spool_id']} found.")
        return web.json_response(self.spools[spool_id])

    async def _measure(self, request: web.Request) -> web.Response:
        spool_id = self._spool_id(request)
        if spool_id is None:
            return _json_error(404, f"No spool with ID {request.match_info['spool_id']} found.")
        body = await self._body(request) or {}
        weight = body.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            return web.json_response({"detail": [{"msg": "weight must be a number"}]}, status=422)
        try:
            return web.json_response(self.measure(spool_id, float(weight)))
        except ValueError as error:
            return _json_error(400, str(error))

    async def _patch(self, request: web.Request) -> web.Response:
        spool_id = self._spool_id(request)
        if spool_id is None:
            return _json_error(404, f"No spool with ID {request.match_info['spool_id']} found.")
        body = await self._body(request)
        if not isinstance(body, dict):
            return _json_error(400, "Expected an object")
        try:
            return web.json_response(self.patch(spool_id, body))
        except ValueError as error:
            return _json_error(400, str(error))

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self._middleware])
        app.router.add_get("/api/v1/health", self._health)
        app.router.add_get("/api/v1/spool/{spool_id}", self._get)
        app.router.add_put("/api/v1/spool/{spool_id}/measure", self._measure)
        app.router.add_patch("/api/v1/spool/{spool_id}", self._patch)
        return app

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> str:
        self._runner = web.AppRunner(self.app(), access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host, port)
        await site.start()
        sockets = site._server.sockets  # type: ignore[union-attr]
        bound = sockets[0].getsockname()[1]
        self.base_url = f"http://{host}:{bound}/api/v1"
        return self.base_url

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
