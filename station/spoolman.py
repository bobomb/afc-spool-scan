"""Spoolman REST client with a writes guard (dry run when writes are off)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import aiohttp

from .state import SpoolInfo

log = logging.getLogger(__name__)


class SpoolmanError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class SpoolNotFound(SpoolmanError):
    pass


@dataclass(frozen=True)
class WriteResult:
    dry_run: bool
    spool: dict[str, Any] | None


def _error_message(data: Any) -> str:
    if isinstance(data, dict):
        if isinstance(data.get("message"), str):
            return data["message"]
        detail = data.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list) and detail and isinstance(detail[0], dict):
            return str(detail[0].get("msg", detail[0]))
    return str(data)[:200]


class SpoolmanClient:
    def __init__(
        self,
        base_url: str,
        session: aiohttp.ClientSession,
        writes: bool,
        timeout: float = 5.0,
        on_health: Callable[[bool], None] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.writes = writes
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.on_health = on_health

    def _health(self, healthy: bool) -> None:
        if self.on_health is not None:
            self.on_health(healthy)

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with self.session.request(method, url, json=payload, timeout=self.timeout) as response:
                try:
                    data = await response.json(content_type=None)
                except ValueError:
                    data = await response.text()
                self._health(response.status < 500)
                if response.status == 404:
                    raise SpoolNotFound(_error_message(data), response.status)
                if response.status >= 400:
                    raise SpoolmanError(f"Spoolman error {response.status}: {_error_message(data)}", response.status)
                return data
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            self._health(False)
            raise SpoolmanError(f"Spoolman unreachable: {error or type(error).__name__}") from error

    async def health(self) -> bool:
        try:
            await self._request("GET", "/health")
        except SpoolmanError:
            return False
        return True

    async def get_spool(self, spool_id: int) -> dict[str, Any]:
        try:
            data = await self._request("GET", f"/spool/{spool_id}")
        except SpoolNotFound as error:
            raise SpoolNotFound(f"Spool {spool_id} not found", error.status) from error
        if not isinstance(data, dict):
            raise SpoolmanError("Spoolman returned an unexpected response")
        return data

    async def measure(self, spool_id: int, weight: float) -> WriteResult:
        if not self.writes:
            log.info("Writes off: would PUT /spool/%d/measure weight=%.1f", spool_id, weight)
            return WriteResult(dry_run=True, spool=None)
        data = await self._request("PUT", f"/spool/{spool_id}/measure", {"weight": weight})
        return WriteResult(dry_run=False, spool=data if isinstance(data, dict) else None)

    async def patch(self, spool_id: int, fields: dict[str, Any]) -> WriteResult:
        if not self.writes:
            log.info("Writes off: would PATCH /spool/%d %s", spool_id, fields)
            return WriteResult(dry_run=True, spool=None)
        data = await self._request("PATCH", f"/spool/{spool_id}", fields)
        return WriteResult(dry_run=False, spool=data if isinstance(data, dict) else None)


def spool_color(filament: dict[str, Any]) -> str | None:
    multi = filament.get("multi_color_hexes")
    raw = multi.split(",")[0] if isinstance(multi, str) and multi else filament.get("color_hex")
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip().lstrip("#")[:6]
    return f"#{raw.upper()}"


def spool_tare(data: dict[str, Any]) -> tuple[float | None, str | None]:
    """Empty spool weight, resolved like Spoolman: spool, filament, then vendor."""
    filament = data.get("filament") or {}
    vendor = filament.get("vendor") or {}
    for value, source in (
        (data.get("spool_weight"), "spool"),
        (filament.get("spool_weight"), "filament"),
        (vendor.get("empty_spool_weight"), "vendor"),
    ):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), source
    return None, None


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 1)
    return None


def spool_info_from_api(data: dict[str, Any], low_stock_g: float) -> SpoolInfo:
    filament = data.get("filament") or {}
    vendor = filament.get("vendor") or {}
    remaining = _number(data.get("remaining_weight"))
    tare, tare_source = spool_tare(data)
    initial = _number(data.get("initial_weight")) or _number(filament.get("weight"))
    return SpoolInfo(
        id=int(data["id"]),
        found=True,
        vendor=vendor.get("name"),
        name=filament.get("name"),
        material=filament.get("material"),
        color=spool_color(filament),
        remaining_g=remaining,
        spool_weight_g=None if tare is None else round(tare, 1),
        expected_gross_g=None if tare is None or remaining is None else round(tare + remaining, 1),
        initial_weight_g=initial,
        used_weight_g=_number(data.get("used_weight")),
        tare_source=tare_source,
        location=data.get("location") or None,
        last_used=data.get("last_used"),
        archived=bool(data.get("archived", False)),
        low_stock=remaining is not None and remaining < low_stock_g,
    )
