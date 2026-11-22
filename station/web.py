"""Read-only web view: the station's state as a page, JSON and a WebSocket (dev plan §5.4)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aiohttp import WSCloseCode, WSMsgType, web

from .ipc import PROTOCOL
from .state import Store

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "webui"
QUEUE_LIMIT = 512
HEARTBEAT_S = 30.0
CLOSE_TIMEOUT_S = 2.0
SHUTDOWN_TIMEOUT_S = 5.0
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


@dataclass
class _Viewer:
    queue: asyncio.Queue[str | None]
    transport: asyncio.BaseTransport | None
    task: asyncio.Task[Any] | None


class WebServer:
    """Serves `webui/` and pushes the same snapshot and topic events as the IPC protocol, without actions."""

    def __init__(self, store: Store, host: str = "127.0.0.1", port: int = 7914, static_dir: Path = STATIC_DIR) -> None:
        self.store = store
        self.host = host
        self.requested_port = port
        self.static_dir = static_dir
        self._viewers: dict[web.WebSocketResponse, _Viewer] = {}
        self._runner: web.AppRunner | None = None
        self._unsubscribe: Callable[[], None] | None = None

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