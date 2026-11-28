"""Read-only web view: the station's state as a page, JSON and a WebSocket (dev plan §5.4)."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aiohttp import WSCloseCode, WSMsgType, web
from yarl import URL

from .ipc import PROTOCOL
from .settings import DEFAULTS as SETTING_DEFAULTS
from .spoolman import SpoolmanError, SpoolNotFound, spool_info_from_api
from .state import Store

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "webui"
QUEUE_LIMIT = 512
HEARTBEAT_S = 30.0
CLOSE_TIMEOUT_S = 2.0
SHUTDOWN_TIMEOUT_S = 5.0
# Spool details for the popover: hovering a spool again within this reuses the last answer.
SPOOL_TTL_S = 30.0
SPOOL_CACHE_MAX = 200
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0", "::"})
HEADERS = {
    "Content-Security-Policy": "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
                               "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",
}


def dumps(message: Any) -> str:
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def same_origin(request: web.Request) -> bool:
    """Browsers send Origin on WebSockets; another site's page must not read the station's state."""
    origin = request.headers.get("Origin")
    return origin is None or urlsplit(origin).netloc.lower() == request.host.lower()


SpoolLookup = Callable[[int], Awaitable[dict[str, Any]]]


def spoolman_pages(api_url: str) -> str:
    """Spoolman serves its web pages where its API lives, without /api/v1."""
    url = api_url.rstrip("/")
    return url[: -len("/api/v1")] if url.endswith("/api/v1") else url


def spoolman_spool_url(pages: str, spool_id: int, viewer_host: str | None) -> str | None:
    """The spool's page in Spoolman. Spoolman on the station itself (127.0.0.1) is reached through the host name
    the viewer opened this page with."""
    try:
        url = URL(pages)
        if url.host in LOOPBACK_HOSTS and viewer_host:
            url = url.with_host(viewer_host)
        return str(url / "spool" / "show" / str(spool_id))
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _text(value: Any) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def spool_details(data: dict[str, Any], low_stock_g: float) -> dict[str, Any]:
    """What the spool popover shows: the station's spool fields plus Spoolman fields the station doesn't keep."""
    filament = data.get("filament") or {}
    details = asdict(spool_info_from_api(data, low_stock_g))
    del details["message"]
    details.update(
        diameter_mm=_number(filament.get("diameter")),
        extruder_temp=_number(filament.get("settings_extruder_temp")),
        bed_temp=_number(filament.get("settings_bed_temp")),
        lot_nr=_text(data.get("lot_nr")),
        comment=_text(data.get("comment")),
        first_used=_text(data.get("first_used")),
        registered=_text(data.get("registered")),
    )
    return details


def _viewer_host(request: web.Request) -> str | None:
    try:
        return request.url.host
    except ValueError:
        return None


def _error(status: int, code: str, message: str) -> web.Response:
    return web.json_response({"error": code, "message": message}, status=status, dumps=dumps)


@dataclass
class _Viewer:
    queue: asyncio.Queue[str | None]
    transport: asyncio.BaseTransport | None
    task: asyncio.Task[Any] | None


class WebServer:
    """Serves `webui/` and pushes the same snapshot and topic events as the IPC protocol, without actions.

    `/api/spools/<id>` reads one spool from Spoolman for the spool popover (GET only, cached briefly); it never
    changes the station's state.
    """

    def __init__(
        self,
        store: Store,
        host: str = "127.0.0.1",
        port: int = 7914,
        static_dir: Path = STATIC_DIR,
        *,
        spool_lookup: SpoolLookup | None = None,
        spoolman_web: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.store = store
        self.host = host
        self.requested_port = port
        self.static_dir = static_dir
        self.spool_lookup = spool_lookup
        self.spoolman_web = spoolman_web
        self.clock = clock
        self._viewers: dict[web.WebSocketResponse, _Viewer] = {}
        self._runner: web.AppRunner | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._spools: dict[int, tuple[float, dict[str, Any]]] = {}
        self._fetches: dict[int, asyncio.Task[dict[str, Any]]] = {}

    @property
    def port(self) -> int:
        assert self._runner is not None
        return int(self._runner.addresses[0][1])

    @property
    def viewers(self) -> int:
        return len(self._viewers)

    async def start(self) -> None:
        app = web.Application()
        app.on_response_prepare.append(self._add_headers)
        app.router.add_get("/", self._index)
        app.router.add_get("/api/state", self._state)
        app.router.add_get(r"/api/spools/{spool_id:\d{1,9}}", self._spool)
        app.router.add_get("/ws", self._socket)
        app.router.add_static("/static/", self.static_dir)
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=SHUTDOWN_TIMEOUT_S)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.requested_port)
        try:
            await site.start()
        except BaseException:
            await runner.cleanup()
            raise
        self._runner = runner
        self._unsubscribe = self.store.subscribe(self._broadcast)
        log.info("Web view on http://%s:%d/", self.host, self.port)

    async def stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        viewers = list(self._viewers.items())
        dropped = await asyncio.gather(*(self._close(socket, viewer) for socket, viewer in viewers))
        for (_, viewer), gone in zip(viewers, dropped):
            # A close that never finished leaves the viewer's handler waiting for a message that won't come.
            if gone and viewer.task is not None:
                viewer.task.cancel()
        fetches = list(self._fetches.values())
        for task in fetches:
            task.cancel()
        await asyncio.gather(*fetches, return_exceptions=True)
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    @staticmethod
    async def _close(socket: web.WebSocketResponse, viewer: _Viewer) -> bool:
        """Close a viewer; one that stopped reading (asleep, off Wi-Fi) is dropped instead. True if dropped."""
        try:
            await asyncio.wait_for(socket.close(code=WSCloseCode.GOING_AWAY, message=b"station stopping"),
                                   CLOSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            if viewer.transport is not None and not viewer.transport.is_closing():
                viewer.transport.abort()
            return True
        except (ConnectionError, RuntimeError):
            pass
        return False

    @staticmethod
    async def _add_headers(request: web.Request, response: web.StreamResponse) -> None:
        for name, value in HEADERS.items():
            response.headers.setdefault(name, value)

    async def _index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(self.static_dir / "index.html")

    async def _state(self, request: web.Request) -> web.Response:
        return web.json_response(self.store.snapshot(), dumps=dumps)

    async def _spool(self, request: web.Request) -> web.Response:
        spool_id = int(request.match_info["spool_id"])
        if spool_id <= 0:
            return _error(400, "invalid_args", "Spool IDs start at 1")
        if self.spool_lookup is None:
            return _error(503, "unavailable", "Spool details are not available")
        try:
            data = await self._spool_data(spool_id)
        except SpoolNotFound:
            return _error(404, "not_found", f"Spool {spool_id} not found in Spoolman")
        except SpoolmanError as error:
            return _error(502, "spoolman_error", str(error))
        low_stock_g = self.store.settings.get("low_stock_g", SETTING_DEFAULTS["low_stock_g"])
        try:
            details = spool_details(data, low_stock_g)
        except (KeyError, TypeError, ValueError):
            return _error(502, "spoolman_error", "Spoolman returned an unexpected spool")
        if self.spoolman_web:
            link = spoolman_spool_url(self.spoolman_web, spool_id, _viewer_host(request))
            if link:
                details["spoolman_url"] = link
        return web.json_response(details, dumps=dumps)

    async def _spool_data(self, spool_id: int) -> dict[str, Any]:
        """Cached for SPOOL_TTL_S; viewers asking at once share one Spoolman request, which a viewer leaving
        doesn't cancel."""
        cached = self._spools.get(spool_id)
        if cached is not None and self.clock() - cached[0] < SPOOL_TTL_S:
            return cached[1]
        task = self._fetches.get(spool_id)
        if task is None:
            task = asyncio.ensure_future(self._fetch_spool(spool_id))
            self._fetches[spool_id] = task
            task.add_done_callback(functools.partial(self._fetched, spool_id))
        return await asyncio.shield(task)

    async def _fetch_spool(self, spool_id: int) -> dict[str, Any]:
        assert self.spool_lookup is not None
        data = await self.spool_lookup(spool_id)
        self._spools[spool_id] = (self.clock(), data)
        if len(self._spools) > SPOOL_CACHE_MAX:
            del self._spools[min(self._spools, key=lambda key: self._spools[key][0])]
        return data

    def _fetched(self, spool_id: int, task: asyncio.Task[dict[str, Any]]) -> None:
        if self._fetches.get(spool_id) is task:
            del self._fetches[spool_id]
        if not task.cancelled():
            task.exception()

    def _broadcast(self, topic: str, data: Any) -> None:
        if not self._viewers:
            return
        line = dumps({"type": "event", "topic": topic, "data": data})
        for viewer in list(self._viewers.values()):
            try:
                viewer.queue.put_nowait(line)
            except asyncio.QueueFull:
                # A viewer that fell behind gets the whole state again instead of a gap.
                while not viewer.queue.empty():
                    viewer.queue.get_nowait()
                viewer.queue.put_nowait(dumps({"type": "snapshot", "data": self.store.snapshot()}))

    async def _socket(self, request: web.Request) -> web.StreamResponse:
        if not same_origin(request):
            raise web.HTTPForbidden(text="This page can only be read from the station's own address")
        socket = web.WebSocketResponse(heartbeat=HEARTBEAT_S)
        await socket.prepare(request)
        viewer = _Viewer(asyncio.Queue(QUEUE_LIMIT), request.transport, asyncio.current_task())
        viewer.queue.put_nowait(dumps({"type": "hello", "protocol": PROTOCOL, "read_only": True}))
        viewer.queue.put_nowait(dumps({"type": "snapshot", "data": self.store.snapshot()}))
        self._viewers[socket] = viewer
        sender = asyncio.create_task(self._send(socket, viewer.queue))
        try:
            async for message in socket:
                if message.type == WSMsgType.ERROR:
                    break
                # Read-only: anything a viewer sends is ignored.
        finally:
            self._viewers.pop(socket, None)
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sender
            await self._close(socket, viewer)
        return socket

    @staticmethod
    async def _send(socket: web.WebSocketResponse, queue: asyncio.Queue[str | None]) -> None:
        try:
            while (line := await queue.get()) is not None:
                await socket.send_str(line)
        except (ConnectionError, RuntimeError):
            with contextlib.suppress(Exception):
                await socket.close()