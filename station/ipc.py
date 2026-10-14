"""Protocol v1 server: TCP, UTF-8 newline-delimited JSON (dev plan §5)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .state import Store

log = logging.getLogger(__name__)

PROTOCOL = 1
MAX_LINE = 1 << 20
QUEUE_LIMIT = 4096

Handler = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


def encode(message: dict[str, Any]) -> bytes:
    return (json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode()


class _Client:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(QUEUE_LIMIT)
        self.tasks: set[asyncio.Task[None]] = set()
        self.closed = False
        peer = writer.get_extra_info("peername")
        self.name = f"{peer[0]}:{peer[1]}" if isinstance(peer, tuple) else str(peer)

    def send(self, line: bytes) -> None:
        if self.closed:
            return
        try:
            self.queue.put_nowait(line)
        except asyncio.QueueFull:
            log.warning("IPC client %s is not reading; disconnecting", self.name)
            self.close(force=True)

    def close(self, force: bool = False) -> None:
        """Stop accepting messages; queued lines are flushed unless forced."""
        if not self.closed:
            self.closed = True
            try:
                self.queue.put_nowait(None)
            except asyncio.QueueFull:
                force = True
        if force:
            self.writer.close()

    async def write_loop(self) -> None:
        try:
            while (line := await self.queue.get()) is not None:
                self.writer.write(line)
                await self.writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            self.closed = True
            self.writer.close()


class IpcServer:
    def __init__(
        self,
        store: Store,
        handler: Handler,
        host: str = "127.0.0.1",
        port: int = 7913,
        hello_extra: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.handler = handler
        self.host = host
        self.requested_port = port
        self.hello_extra = dict(hello_extra or {})
        self.clients: set[_Client] = set()
        self._server: asyncio.Server | None = None
        self._unsubscribe: Callable[[], None] | None = None

    @property
    def port(self) -> int:
        assert self._server is not None
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._serve, self.host, self.requested_port, limit=MAX_LINE
        )
        self._unsubscribe = self.store.subscribe(self._broadcast)
        log.info("IPC listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        for client in list(self.clients):
            for task in client.tasks:
                task.cancel()
            client.close()
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 2)
            self._server = None

    def _broadcast(self, topic: str, data: Any) -> None:
        if not self.clients:
            return
        line = encode({"type": "event", "topic": topic, "data": data})
        for client in list(self.clients):
            client.send(line)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = _Client(reader, writer)
        self.clients.add(client)
        log.info("IPC client %s connected", client.name)
        writer_task = asyncio.create_task(client.write_loop())
        client.send(encode({"type": "hello", "protocol": PROTOCOL, **self.hello_extra}))
        client.send(encode({"type": "snapshot", "data": self.store.snapshot()}))
        try:
            while not client.closed:
                try:
                    raw = await reader.readuntil(b"\n")
                except asyncio.IncompleteReadError:
                    break
                except asyncio.LimitOverrunError:
                    client.send(encode(self._error(None, "line too long")))
                    break
                self._dispatch(client, raw)
        except (ConnectionError, OSError):
            pass
        finally:
            self.clients.discard(client)
            for task in client.tasks:
                task.cancel()
            client.close()
            try:
                await asyncio.wait_for(writer_task, 2)
            except (asyncio.TimeoutError, ConnectionError, OSError):
                client.close(force=True)
            log.info("IPC client %s disconnected", client.name)

    @staticmethod
    def _error(request_id: Any, message: str, code: str = "invalid_args") -> dict[str, Any]:
        return {"type": "result", "id": request_id, "ok": False, "code": code, "message": message}

    def _dispatch(self, client: _Client, raw: bytes) -> None:
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            return
        try:
            message = json.loads(text)
        except ValueError:
            client.send(encode(self._error(None, "malformed JSON")))
            return
        if not isinstance(message, dict) or message.get("type") != "request":
            client.send(encode(self._error(message.get("id") if isinstance(message, dict) else None,
                                           "expected a request")))
            return
        request_id = message.get("id")
        if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
            client.send(encode(self._error(None, "request id must be a string or integer")))
            return
        action = message.get("action")
        args = message.get("args", {})
        if args is None:
            args = {}
        if not isinstance(action, str) or not action or not isinstance(args, dict):
            client.send(encode(self._error(request_id, "request needs an action and object args")))
            return
        task = asyncio.create_task(self._run(client, request_id, action, args))
        client.tasks.add(task)
        task.add_done_callback(client.tasks.discard)

    async def _run(self, client: _Client, request_id: Any, action: str, args: dict[str, Any]) -> None:
        try:
            result = await self.handler(action, args)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("IPC action %s failed", action)
            result = {"ok": False, "code": "internal_error", "message": f"{action} failed unexpectedly"}
        client.send(encode({"type": "result", "id": request_id, **result}))
