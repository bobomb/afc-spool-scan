#!/usr/bin/env python3
"""Capture read-only fixtures from the printers and Spoolman for --printers sim.

Writes station/sim/fixtures/printers/<key>.json (AFC, AFC lanes, print_stats,
display_status, object list) and station/sim/fixtures/spoolman/spools.json.
Only read calls are made: server.info, printer.objects.list/query and
GET /spool/{id}. Run it from a machine on the printers' LAN, e.g.:

    python scripts/capture-fixtures.py --spools 97,86,60

With --bambuddy it also writes bambuddy/<key>.json for every `Name=bambuddy:<id>`
printer (status, slot assignments), scrubbed of serials, addresses, tokens, tag
IDs, file names and the printer's name; --bambuddy-ws-seconds N also records the
websocket messages for N seconds to bambuddy/<key>.ws.jsonl (insert or remove
spools meanwhile to capture a sequence). Bambuddy reads only: GET, plus
POST /auth/ws-token for the websocket. Run it where Bambuddy and its API key
(BAMBUDDY_API_KEY or BAMBUDDY_API_KEY_FILE) are, e.g. on spoolpi:

    python scripts/capture-fixtures.py --skip-printers --bambuddy --out /tmp/capture
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from station.config import BAMBUDDY, ConfigError, PrinterConfig, load_config  # noqa: E402
from station.moonraker import LANE_PREFIXES  # noqa: E402
from station.sim.bambuddy import scrub_capture  # noqa: E402

DEFAULT_OUT = REPO / "station" / "sim" / "fixtures"


async def rpc(ws: aiohttp.ClientWebSocketResponse, counter: itertools.count, method: str,
              params: dict[str, Any] | None = None) -> Any:
    request_id = next(counter)
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "id": request_id}
    if params is not None:
        message["params"] = params
    await ws.send_str(json.dumps(message))
    while True:
        reply = await ws.receive(timeout=10)
        if reply.type != aiohttp.WSMsgType.TEXT:
            raise RuntimeError(f"{method}: connection closed")
        data = json.loads(reply.data)
        if data.get("id") != request_id:
            continue
        if "error" in data:
            raise RuntimeError(f"{method}: {data['error']}")
        return data.get("result")


async def capture_printer(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    counter = itertools.count(1)
    async with session.ws_connect(url, timeout=aiohttp.ClientWSTimeout(ws_close=5)) as ws:
        info = await rpc(ws, counter, "server.info")
        listing = await rpc(ws, counter, "printer.objects.list")
        names = listing.get("objects", [])
        wanted = [name for name in names
                  if name in ("AFC", "print_stats", "display_status") or name.startswith(LANE_PREFIXES)]
        result = await rpc(ws, counter, "printer.objects.query", {"objects": {name: None for name in wanted}})
    keep = ("klippy_connected", "klippy_state", "moonraker_version")
    return {
        "server_info": {key: info.get(key) for key in keep if key in info},
        "object_list": names,
        "objects": result.get("status", {}),
    }


async def capture_spools(session: aiohttp.ClientSession, base_url: str, spool_ids: list[int]) -> dict[str, Any]:
    spools = []
    for spool_id in spool_ids:
        async with session.get(f"{base_url.rstrip('/')}/spool/{spool_id}",
                               timeout=aiohttp.ClientTimeout(total=10)) as response:
            response.raise_for_status()
            spools.append(await response.json())
    return {"spools": spools}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


async def capture_bambuddy(session: aiohttp.ClientSession, base_url: str, api_key: str, printer: PrinterConfig,
                           name: str, ws_seconds: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read-only: GET status and assignments, then optionally listen to the websocket."""
    api = f"{base_url.rstrip('/')}/api/v1"
    headers = {"X-API-Key": api_key} if api_key else {}
    timeout = aiohttp.ClientTimeout(total=15)
    printer_id = printer.bambuddy_printer_id

    async def get(path: str) -> Any:
        async with session.get(api + path, headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            return await response.json()

    status = await get(f"/printers/{printer_id}/status")
    rows = await get(f"/spoolman/inventory/slot-assignments/all?printer_id={printer_id}")
    fixture = {
        "name": name,
        "model": status.get("model") or "H3C",
        "status": scrub_capture(status, name),
        "assignments": {str(row["tray_id"]): row["spoolman_spool_id"] for row in rows
                        if row.get("printer_id") == printer_id and row.get("ams_id") == 32},
    }
    messages: list[dict[str, Any]] = []
    if ws_seconds > 0:
        params = {}
        if api_key:
            async with session.post(api + "/auth/ws-token", headers=headers, timeout=timeout) as response:
                response.raise_for_status()
                params["token"] = (await response.json())["token"]
        url = api.replace("http", "ws", 1) + "/ws"
        async with session.ws_connect(url, params=params, timeout=aiohttp.ClientWSTimeout(ws_close=5)) as ws:
            loop = asyncio.get_running_loop()
            start = loop.time()
            while (left := start + ws_seconds - loop.time()) > 0:
                try:
                    message = await asyncio.wait_for(ws.receive(), left)
                except asyncio.TimeoutError:
                    break
                if message.type != aiohttp.WSMsgType.TEXT:
                    break
                data = json.loads(message.data)
                if data.get("printer_id") in (None, printer_id):
                    messages.append({"t": round(loop.time() - start, 2), **scrub_capture(data, name)})
    return fixture, messages


async def capture(printers: dict[str, str], spoolman_url: str | None, spool_ids: list[int], out: Path,
                  bambuddy: list[PrinterConfig] | None = None, bambuddy_url: str = "", api_key: str = "",
                  bambuddy_name: str = "Heron", ws_seconds: float = 0.0) -> list[Path]:
    written = []
    async with aiohttp.ClientSession() as session:
        for key, url in printers.items():
            path = out / "printers" / f"{key}.json"
            write_json(path, await capture_printer(session, url))
            written.append(path)
        if spoolman_url and spool_ids:
            path = out / "spoolman" / "spools.json"
            write_json(path, await capture_spools(session, spoolman_url, spool_ids))
            written.append(path)
        for printer in bambuddy or []:
            fixture, messages = await capture_bambuddy(session, bambuddy_url, api_key, printer, bambuddy_name,
                                                       ws_seconds)
            path = out / "bambuddy" / f"{printer.key}.json"
            write_json(path, {**fixture, "captured": time.strftime("%Y-%m-%d")})
            written.append(path)
            if messages:
                path = out / "bambuddy" / f"{printer.key}.ws.jsonl"
                path.write_text("".join(json.dumps(m) + "\n" for m in messages), encoding="utf-8")
                written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--spools", default="", help="comma-separated spool IDs (normal, low stock, archived)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-printers", action="store_true")
    parser.add_argument("--bambuddy", action="store_true", help="also capture the Bambuddy printers (read-only)")
    parser.add_argument("--bambuddy-name", default="Heron", help="placeholder for the printer's name")
    parser.add_argument("--bambuddy-ws-seconds", type=float, default=0.0,
                        help="record the Bambuddy websocket for this long")
    args = parser.parse_args(argv)
    try:
        config = load_config([])
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    spool_ids = [int(part) for part in args.spools.split(",") if part.strip()]
    printers = {} if args.skip_printers else {p.key: p.websocket_url for p in config.printers if p.kind != BAMBUDDY}
    bambuddy = [p for p in config.printers if p.kind == BAMBUDDY] if args.bambuddy else []
    try:
        written = asyncio.run(capture(printers, config.spoolman_url, spool_ids, args.out, bambuddy,
                                      config.bambuddy_url, config.bambuddy_api_key, args.bambuddy_name,
                                      args.bambuddy_ws_seconds))
    except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, KeyError) as error:
        print(f"Capture failed: {error}", file=sys.stderr)
        return 1
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
