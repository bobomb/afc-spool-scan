"""python -m station.simctl: drive the simulated hardware of a running station.

Examples (dev plan §4):
  simctl scale 984.0            stable reading in grams
  simctl scale 12.5 --oz        stable reading reported in ounces
  simctl scale --status motion
  simctl scan WEB+SPOOLMAN:S-97
  simctl printer kilo --disconnect / --connect / --restart
  simctl printer yankee --lane lane2 --spool 97 --status Ready
  simctl printer kilo --insert lane4      (AFC tags it with the pending spool)
  simctl spoolman --offline / --online
  simctl request weigh '{"spool_id": 97}'
  simctl state [topic]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from typing import Any

from .scale.sim import STATUSES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m station.simctl", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=os.environ.get("STATION_IPC_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("STATION_IPC_PORT", "7913")))
    sub = parser.add_subparsers(dest="command", required=True)

    scale = sub.add_parser("scale", help="set the simulated scale")
    scale.add_argument("grams", type=float, nargs="?")
    scale.add_argument("--oz", action="store_true", help="the value is in ounces")
    scale.add_argument("--status", choices=STATUSES)

    scan = sub.add_parser("scan", help="inject a QR scan")
    scan.add_argument("code")

    printer = sub.add_parser("printer", help="control a simulated printer")
    printer.add_argument("name")
    group = printer.add_mutually_exclusive_group(required=True)
    group.add_argument("--connect", action="store_true")
    group.add_argument("--disconnect", action="store_true")
    group.add_argument("--restart", action="store_true", help="restart Klipper (clears pending spool)")
    group.add_argument("--lane", help="edit a lane (with --spool/--clear/--status/...)")
    group.add_argument("--insert", metavar="LANE", help="insert filament into a lane")
    group.add_argument("--eject", metavar="LANE", help="eject a lane")
    group.add_argument("--print", dest="print_state", metavar="STATE",
                       help="print_stats state: standby, printing, paused, complete, cancelled, error")
    group.add_argument("--error", metavar="MESSAGE", help="raise an AFC error")
    group.add_argument("--clear-error", action="store_true")
    printer.add_argument("--spool", type=int)
    printer.add_argument("--clear", action="store_true", help="remove the lane's spool")
    printer.add_argument("--status", help="lane status, e.g. Loaded")
    printer.add_argument("--filament-status", help="Ready, In Tool, Prep, Not Ready")
    printer.add_argument("--tool-loaded", action=argparse.BooleanOptionalAction, default=None)
    printer.add_argument("--progress", type=float)
    printer.add_argument("--filename")

    spoolman = sub.add_parser("spoolman", help="take the simulated Spoolman on/offline")
    online = spoolman.add_mutually_exclusive_group(required=True)
    online.add_argument("--online", action="store_true")
    online.add_argument("--offline", action="store_true")

    request = sub.add_parser("request", help="send any protocol action")
    request.add_argument("action")
    request.add_argument("args", nargs="?", default="{}", help="JSON object")

    state = sub.add_parser("state", help="print the state snapshot")
    state.add_argument("topic", nargs="?")
    return parser


def to_request(args: argparse.Namespace) -> tuple[str, dict[str, Any]] | None:
    if args.command == "scale":
        if args.grams is None and args.status is None:
            raise SystemExit("scale needs a weight and/or --status")
        payload: dict[str, Any] = {"unit": "oz" if args.oz else "g"}
        if args.grams is not None:
            payload["grams"] = args.grams
        if args.status is not None:
            payload["status"] = args.status
        return "sim.scale", payload
    if args.command == "scan":
        return "sim.scan", {"code": args.code}
    if args.command == "spoolman":
        return "sim.spoolman", {"online": bool(args.online)}
    if args.command == "request":
        try:
            payload = json.loads(args.args)
        except ValueError as error:
            raise SystemExit(f"args must be JSON: {error}") from error
        if not isinstance(payload, dict):
            raise SystemExit("args must be a JSON object")
        return args.action, payload
    if args.command == "printer":
        payload = {"printer": args.name}
        if args.connect:
            payload["op"] = "connect"
        elif args.disconnect:
            payload["op"] = "disconnect"
        elif args.restart:
            payload["op"] = "restart"
        elif args.insert:
            payload.update(op="insert", lane=args.insert)
        elif args.eject:
            payload.update(op="eject", lane=args.eject)
        elif args.print_state:
            payload.update(op="print", state=args.print_state)
        elif args.error:
            payload.update(op="error", message=args.error)
        elif args.clear_error:
            payload["op"] = "clear_error"
        else:
            payload.update(op="lane", lane=args.lane)
            if args.clear:
                payload["clear"] = True
            elif args.spool is not None:
                payload["spool_id"] = args.spool
            if args.status:
                payload["status"] = args.status
            if args.filament_status:
                payload["filament_status"] = args.filament_status
            if args.tool_loaded is not None:
                payload["tool_loaded"] = args.tool_loaded
        if args.progress is not None:
            payload.setdefault("op", "print")
            payload["progress"] = args.progress
        if args.filename:
            payload["filename"] = args.filename
        return "sim.printer", payload
    return None


async def run(args: argparse.Namespace) -> int:
    try:
        reader, writer = await asyncio.open_connection(args.host, args.port)
    except OSError as error:
        print(f"Cannot connect to the station at {args.host}:{args.port}: {error}", file=sys.stderr)
        return 1
    try:
        hello = json.loads(await reader.readline())
        snapshot = json.loads(await reader.readline())
        if hello.get("protocol") != 1 or snapshot.get("type") != "snapshot":
            print("Unexpected service greeting", file=sys.stderr)
            return 1
        if args.command == "state":
            data = snapshot["data"]
            print(json.dumps(data.get(args.topic) if args.topic else data, indent=2))
            return 0
        request = to_request(args)
        assert request is not None
        action, payload = request
        writer.write((json.dumps({"type": "request", "id": "simctl-1", "action": action, "args": payload}) + "\n").encode())
        await writer.drain()
        while True:
            line = await asyncio.wait_for(reader.readline(), 30)
            if not line:
                print("Connection closed", file=sys.stderr)
                return 1
            message = json.loads(line)
            if message.get("type") == "result" and message.get("id") == "simctl-1":
                status = "ok" if message.get("ok") else f"failed ({message.get('code')})"
                print(f"{status}: {message.get('message', '')}")
                if message.get("data"):
                    print(json.dumps(message["data"], indent=2))
                return 0 if message.get("ok") else 1
    finally:
        writer.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
