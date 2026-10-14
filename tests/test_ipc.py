from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from station.ipc import IpcServer
from station.state import ScaleState, ServiceInfo, Store


class Client:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    @classmethod
    async def connect(cls, port: int) -> Client:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        return cls(reader, writer)

    async def read(self) -> dict[str, Any]:
        line = await asyncio.wait_for(self.reader.readline(), 2)
        assert line, "connection closed"
        return json.loads(line)

    async def send_raw(self, data: bytes) -> None:
        self.writer.write(data)
        await self.writer.drain()

    async def request(self, request_id: Any, action: str, args: dict[str, Any] | None = None) -> None:
        message = {"type": "request", "id": request_id, "action": action}
        if args is not None:
            message["args"] = args
        await self.send_raw(json.dumps(message).encode() + b"\n")

    async def close(self) -> None:
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except ConnectionError:
            pass


@pytest.fixture
async def server():  # noqa: ANN201
    store = Store(ServiceInfo(version="t", protocol=1, hardware="sim", printers="sim", spoolman="sim", writes=False))
    calls: list[tuple[str, dict[str, Any]]] = []
    release = asyncio.Event()

    async def handler(action: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append((action, args))
        if action == "boom":
            raise RuntimeError("bad")
        if action == "slow":
            await release.wait()
        if action == "weigh":
            store.set_scale(ScaleState(present=True, status="stable", grams=984.0, stable=True))
        return {"ok": True, "message": f"{action} done"}

    ipc = IpcServer(store, handler, port=0, hello_extra={"service_version": "t"})
    await ipc.start()
    yield ipc, store, calls, release
    release.set()
    await ipc.stop()


async def test_hello_snapshot_event_and_result(server) -> None:  # noqa: ANN001
    ipc, store, calls, _ = server
    client = await Client.connect(ipc.port)
    hello = await client.read()
    assert hello == {"type": "hello", "protocol": 1, "service_version": "t"}
    snapshot = await client.read()
    assert snapshot["type"] == "snapshot"
    assert snapshot["data"]["scale"]["status"] == "absent"

    await client.request("u-1", "weigh", {"spool_id": 97})
    event = await client.read()
    assert event == {"type": "event", "topic": "scale", "data": store.snapshot()["scale"]}
    result = await client.read()
    assert result == {"type": "result", "id": "u-1", "ok": True, "message": "weigh done"}
    assert calls == [("weigh", {"spool_id": 97})]
    await client.close()


async def test_malformed_lines_keep_connection_open(server) -> None:  # noqa: ANN001
    ipc, _, calls, _ = server
    client = await Client.connect(ipc.port)
    await client.read()
    await client.read()
    await client.send_raw(b"{not json\n")
    assert (await client.read())["message"] == "malformed JSON"
    await client.send_raw(b'["list"]\n')
    assert (await client.read())["message"] == "expected a request"
    await client.send_raw(b'{"type":"event","id":"x"}\n')
    reply = await client.read()
    assert reply["id"] == "x" and reply["code"] == "invalid_args"
    await client.send_raw(b'{"type":"request","id":true,"action":"lookup"}\n')
    assert (await client.read())["message"] == "request id must be a string or integer"
    await client.send_raw(b'{"type":"request","id":3,"action":"lookup","args":[1]}\n')
    reply = await client.read()
    assert reply["id"] == 3 and reply["ok"] is False
    await client.send_raw(b"\n   \n")
    await client.request(4, "boom")
    reply = await client.read()
    assert reply == {"type": "result", "id": 4, "ok": False, "code": "internal_error",
                     "message": "boom failed unexpectedly"}
    await client.request("u-5", "lookup")
    assert (await client.read())["ok"] is True
    assert calls[-1] == ("lookup", {})
    await client.close()


async def test_events_reach_multiple_clients_and_slow_actions_do_not_block(server) -> None:  # noqa: ANN001
    ipc, store, _, release = server
    first = await Client.connect(ipc.port)
    second = await Client.connect(ipc.port)
    for client in (first, second):
        await client.read()
        await client.read()
    await first.request("slow-1", "slow")
    await first.request("fast-2", "lookup")
    assert (await first.read())["id"] == "fast-2"
    store.set_scale(ScaleState(present=True, status="motion", grams=12.0))
    for client in (first, second):
        event = await client.read()
        assert event["topic"] == "scale" and event["data"]["status"] == "motion"
    release.set()
    assert (await first.read())["id"] == "slow-1"
    await first.close()
    await asyncio.sleep(0.05)
    store.set_scale(ScaleState(present=False))
    assert (await second.read())["data"]["present"] is False
    assert len(ipc.clients) == 1
    await second.close()


async def test_oversized_line_disconnects(server) -> None:  # noqa: ANN001
    ipc, _, _, _ = server
    client = await Client.connect(ipc.port)
    await client.read()
    await client.read()
    await client.send_raw(b"x" * ((1 << 20) + 1) + b"\n")
    reply = await client.read()
    assert reply["message"] == "line too long"
    assert await asyncio.wait_for(client.reader.read(), 2) == b""
    await client.close()


async def test_stop_closes_clients(server) -> None:  # noqa: ANN001
    ipc, _, _, _ = server
    client = await Client.connect(ipc.port)
    await client.read()
    await client.read()
    await ipc.stop()
    assert await asyncio.wait_for(client.reader.read(), 2) == b""
    await client.close()
