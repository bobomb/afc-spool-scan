from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import socket
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from conftest import sim_config, wait_until

from station import web as web_module
from station.app import Station
from station.spoolman import SpoolmanError, SpoolNotFound
from station.state import ScaleState, ServiceInfo, Store
from station.web import WebServer, spoolman_pages, spoolman_spool_url


@pytest.fixture
async def web():  # noqa: ANN201
    store = Store(ServiceInfo(version="t", protocol=1, hardware="sim", printers="sim", spoolman="sim", writes=False))
    server = WebServer(store, port=0)
    await server.start()
    async with aiohttp.ClientSession(f"http://127.0.0.1:{server.port}") as session:
        yield server, store, session
    await server.stop()


async def receive(socket_: aiohttp.ClientWebSocketResponse) -> dict[str, Any]:
    message = await asyncio.wait_for(socket_.receive(), 2)
    assert message.type == aiohttp.WSMsgType.TEXT, message
    return json.loads(message.data)


async def test_page_and_its_files_are_served_with_safe_headers(web) -> None:  # noqa: ANN001
    _, _, session = web
    async with session.get("/") as response:
        assert response.status == 200 and response.content_type == "text/html"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        page = await response.text()
    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', page)
    assert sorted(assets) == ["/static/app.js", "/static/style.css"]
    for asset in assets:
        async with session.get(asset) as response:
            assert response.status == 200, asset
    async with session.get("/static/../web.py") as response:
        assert response.status in (403, 404)


async def test_state_is_the_store_snapshot(web) -> None:  # noqa: ANN001
    _, store, session = web
    store.set_scale(ScaleState(present=True, status="stable", grams=812.0, stable=True))
    async with session.get("/api/state") as response:
        assert await response.json() == json.loads(json.dumps(store.snapshot()))


async def test_socket_streams_the_state_and_ignores_requests(web) -> None:  # noqa: ANN001
    server, store, session = web
    async with session.ws_connect("/ws") as socket_:
        assert await receive(socket_) == {"type": "hello", "protocol": 1, "read_only": True}
        snapshot = await receive(socket_)
        assert snapshot["type"] == "snapshot" and snapshot["data"]["service"]["version"] == "t"
        await socket_.send_str(json.dumps({"type": "request", "id": 1, "action": "clear_pending", "args": {}}))
        store.set_scale(ScaleState(present=True, status="stable", grams=640.0, stable=True))
        event = await receive(socket_)
        assert (event["type"], event["topic"], event["data"]["grams"]) == ("event", "scale", 640.0)
        assert server.viewers == 1


async def test_another_sites_page_cannot_open_the_socket(web) -> None:  # noqa: ANN001
    server, _, session = web
    with pytest.raises(aiohttp.WSServerHandshakeError) as refused:
        await session.ws_connect("/ws", headers={"Origin": "http://evil.example"})
    assert refused.value.status == 403
    own = f"http://127.0.0.1:{server.port}"
    async with session.ws_connect("/ws", headers={"Origin": own}) as socket_:
        assert (await receive(socket_))["type"] == "hello"


SPOOL_93 = {
    "id": 93, "registered": "2026-02-01T12:00:00Z", "first_used": "2026-03-01T09:00:00Z",
    "last_used": "2026-10-01T07:16:18Z", "remaining_weight": 701.0, "initial_weight": 1000.0, "used_weight": 299.0,
    "spool_weight": None, "location": "Dry box B", "lot_nr": " L-2207 ", "comment": "", "archived": False,
    "filament": {
        "id": 20, "name": "Panchroma Silk Rainbow", "material": "PLA", "diameter": 1.75, "spool_weight": 140.0,
        "settings_extruder_temp": 210, "settings_bed_temp": 60, "multi_color_hexes": "FF0000,00FF00",
        "vendor": {"id": 3, "name": "Polymaker"},
    },
}


class FakeSpoolman:
    def __init__(self) -> None:
        self.calls: list[int] = []
        self.gate = asyncio.Event()
        self.gate.set()

    async def get_spool(self, spool_id: int) -> dict[str, Any]:
        self.calls.append(spool_id)
        await self.gate.wait()
        if spool_id == 93:
            return SPOOL_93
        if spool_id == 7:
            raise SpoolmanError("Spoolman unreachable: timeout")
        raise SpoolNotFound(f"Spool {spool_id} not found")


@pytest.fixture
async def spools():  # noqa: ANN201
    store = Store(ServiceInfo(version="t", protocol=1, hardware="sim", printers="sim", spoolman="sim", writes=False))
    spoolman = FakeSpoolman()
    now = [0.0]
    server = WebServer(store, port=0, spool_lookup=spoolman.get_spool, spoolman_web="http://127.0.0.1:7912",
                       clock=lambda: now[0])
    await server.start()
    async with aiohttp.ClientSession(f"http://127.0.0.1:{server.port}") as session:
        yield server, spoolman, session, now
    await server.stop()


async def test_spool_details_come_from_spoolman_with_a_link_for_the_viewer(spools) -> None:  # noqa: ANN001
    _, spoolman, session, now = spools
    spoolman.gate.clear()
    headers = {"Host": "spoolstation.example:7914"}
    pending = [asyncio.ensure_future(session.get("/api/spools/93", headers=headers)) for _ in range(3)]
    await wait_until(lambda: spoolman.calls == [93])
    spoolman.gate.set()
    responses = await asyncio.gather(*pending)
    details = [await response.json() for response in responses]
    assert spoolman.calls == [93] and details[0] == details[2]
    spool = details[0]
    assert spool["spoolman_url"] == "http://spoolstation.example:7912/spool/show/93"
    assert (spool["vendor"], spool["name"], spool["material"], spool["colors"]) == (
        "Polymaker", "Panchroma Silk Rainbow", "PLA", ["#FF0000", "#00FF00"])
    assert (spool["remaining_g"], spool["initial_weight_g"], spool["used_weight_g"]) == (701.0, 1000.0, 299.0)
    assert (spool["spool_weight_g"], spool["tare_source"]) == (140.0, "filament")
    assert (spool["diameter_mm"], spool["extruder_temp"], spool["bed_temp"]) == (1.75, 210.0, 60.0)
    assert (spool["lot_nr"], spool["comment"], spool["location"]) == ("L-2207", None, "Dry box B")
    assert spool["first_used"] == "2026-03-01T09:00:00Z" and spool["low_stock"] is False
    async with session.get("/api/spools/93") as response:
        assert response.status == 200 and spoolman.calls == [93]
    now[0] = 31.0
    async with session.get("/api/spools/93") as response:
        assert response.status == 200 and spoolman.calls == [93, 93]


async def test_spool_errors_are_reported_and_not_cached(spools) -> None:  # noqa: ANN001
    _, spoolman, session, _ = spools
    async with session.get("/api/spools/999") as response:
        assert response.status == 404
        assert await response.json() == {"error": "not_found", "message": "Spool 999 not found in Spoolman"}
    async with session.get("/api/spools/7") as response:
        assert response.status == 502 and (await response.json())["error"] == "spoolman_error"
    async with session.get("/api/spools/7") as response:
        assert response.status == 502
    assert spoolman.calls == [999, 7, 7]
    async with session.get("/api/spools/0") as response:
        assert response.status == 400
    for path in ("/api/spools/abc", "/api/spools/-1", "/api/spools/1234567890"):
        async with session.get(path) as response:
            assert response.status == 404, path
    assert spoolman.calls == [999, 7, 7]


@pytest.mark.parametrize(
    ("pages", "viewer", "link"),
    [
        ("http://127.0.0.1:7912", "spoolstation.example", "http://spoolstation.example:7912/spool/show/5"),
        ("http://localhost:7912/spoolman", "192.0.2.20", "http://192.0.2.20:7912/spoolman/spool/show/5"),
        ("http://127.0.0.1:7912", "::1", "http://[::1]:7912/spool/show/5"),
        ("https://spoolman.example", "spoolstation.example", "https://spoolman.example/spool/show/5"),
        ("http://127.0.0.1:7912", None, "http://127.0.0.1:7912/spool/show/5"),
    ],
)
def test_spoolman_links_use_the_viewers_host_for_a_local_spoolman(pages: str, viewer: str | None,
                                                                   link: str) -> None:
    assert spoolman_spool_url(pages, 5, viewer) == link


def test_spoolman_pages_are_the_api_without_its_path() -> None:
    assert spoolman_pages("http://127.0.0.1:7912/api/v1") == "http://127.0.0.1:7912"
    assert spoolman_pages("http://h:7912/spoolman/api/v1/") == "http://h:7912/spoolman"


async def test_a_viewer_that_falls_behind_gets_a_fresh_snapshot(web) -> None:  # noqa: ANN001
    server, store, _ = web
    queue: asyncio.Queue[str | None] = asyncio.Queue(2)
    viewer: Any = object()
    server._viewers[viewer] = web_module._Viewer(queue, None, None)
    for grams in (1.0, 2.0, 3.0):
        store.set_scale(ScaleState(present=True, status="stable", grams=grams, stable=True))
    server._viewers.pop(viewer)
    lines = [json.loads(queue.get_nowait() or "") for _ in range(queue.qsize())]
    assert [line["type"] for line in lines] == ["snapshot"]
    assert lines[0]["data"]["scale"]["grams"] == 3.0


async def test_stop_closes_open_viewers(web) -> None:  # noqa: ANN001
    server, _, session = web
    async with session.ws_connect("/ws") as socket_:
        await receive(socket_)
        await receive(socket_)
        await server.stop()
        message = await asyncio.wait_for(socket_.receive(), 2)
        assert message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED)


async def test_stop_drops_a_viewer_that_stopped_reading(web, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    server, store, _ = web
    monkeypatch.setattr(web_module, "CLOSE_TIMEOUT_S", 0.2)
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    key = base64.b64encode(os.urandom(16)).decode()
    writer.write(f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                 f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
    await writer.drain()
    assert b" 101 " in await asyncio.wait_for(reader.readline(), 2)
    writer.transport.pause_reading()  # type: ignore[attr-defined]
    for i in range(100):  # 20 MB, more than the socket buffers hold
        store.set_activity([{"id": i, "message": "x" * 200_000}])
    await asyncio.sleep(0.5)
    await asyncio.wait_for(server.stop(), 5)
    assert server.viewers == 0
    writer.close()


async def test_station_serves_the_web_view(tmp_path: Path) -> None:
    station = Station(sim_config(tmp_path, web_port=0), printer_backoff=(0.02, 0.05), publish_delay=0,
                      scale_interval=0)
    await station.start()
    try:
        await wait_until(lambda: all(p.connected for p in station.store.printers.values()))
        assert station.web is not None
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{station.web.port}/api/state") as response:
                state = await response.json()
            async with session.get(f"http://127.0.0.1:{station.web.port}/api/spools/97") as response:
                spool = await response.json()
        assert [p["key"] for p in state["printers"]] == ["kilo", "yankee"]
        assert (spool["vendor"], spool["name"], spool["diameter_mm"]) == ("Sunlu", "ABS White", 1.75)
        # A simulated Spoolman has no pages to link to, and looking a spool up doesn't select it.
        assert "spoolman_url" not in spool
        assert station.store.spool is None and station.store.activity == []
    finally:
        await station.stop()


async def test_a_taken_web_port_does_not_stop_the_station(tmp_path: Path) -> None:
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        station = Station(sim_config(tmp_path, web_port=busy.getsockname()[1]), printer_backoff=(0.02, 0.05),
                          publish_delay=0, scale_interval=0)
        await station.start()
        try:
            assert station.web is None and station.ipc is not None
        finally:
            await station.stop()
