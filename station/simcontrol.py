"""`sim.*` IPC actions that drive the simulated scale, scanner, printers, Bambuddy and Spoolman."""

from __future__ import annotations

from typing import Any

from .actions import ActionError, Outcome
from .bambuddy import slot_of
from .scale.sim import SimScale
from .scanner.sim import SimScanner
from .sim.bambuddy import SimBambuddy
from .sim.printers import SimPrinterServer
from .sim.spoolman import SimSpoolman

PRINTER_OPS = ("connect", "disconnect", "restart", "lane", "insert", "eject", "print", "error", "clear_error")
BAMBU_OPS = ("connect", "disconnect", "power_on", "power_off", "insert", "eject", "print", "tool", "error",
             "clear_error")


def _optional_int(args: dict[str, Any], key: str) -> int | None:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ActionError("invalid_args", f"{key} must be an integer")
    return value


class SimControl:
    def __init__(
        self,
        scale: SimScale | None,
        scanner: SimScanner | None,
        printers: SimPrinterServer | None,
        spoolman: SimSpoolman | None,
        bambuddy: SimBambuddy | None = None,
        bambuddy_ids: dict[str, int] | None = None,
    ) -> None:
        self.scale = scale
        self.scanner = scanner
        self.printers = printers
        self.spoolman = spoolman
        self.bambuddy = bambuddy
        self.bambuddy_ids = bambuddy_ids or {}

    async def handle(self, action: str, args: dict[str, Any]) -> Outcome:
        handler = {
            "sim.scale": self._scale,
            "sim.scan": self._scan,
            "sim.printer": self._printer,
            "sim.spoolman": self._spoolman,
        }.get(action)
        if handler is None:
            raise ActionError("invalid_args", f"Unknown action {action!r}")
        return await handler(args)

    async def _scale(self, args: dict[str, Any]) -> Outcome:
        if self.scale is None:
            raise ActionError("invalid_args", "The scale is not simulated (--hardware real)")
        grams = args.get("grams")
        if grams is not None and (isinstance(grams, bool) or not isinstance(grams, (int, float))):
            raise ActionError("invalid_args", "grams must be a number")
        try:
            reading = self.scale.set(grams, unit=args.get("unit", "g"), status=args.get("status"))
        except ValueError as error:
            raise ActionError("invalid_args", str(error)) from error
        weight = "" if reading.grams is None else f" {reading.grams} g ({reading.source_unit})"
        return Outcome(True, f"Scale {reading.status}{weight}")

    async def _scan(self, args: dict[str, Any]) -> Outcome:
        if self.scanner is None:
            raise ActionError("invalid_args", "The scanner is not simulated (--hardware real)")
        code = args.get("code")
        if not isinstance(code, str) or not code:
            raise ActionError("invalid_args", "code is required")
        self.scanner.inject(code)
        return Outcome(True, f"Scanned {code}")

    async def _spoolman(self, args: dict[str, Any]) -> Outcome:
        if self.spoolman is None:
            raise ActionError("invalid_args", "Spoolman is not simulated (--spoolman live)")
        online = args.get("online")
        if not isinstance(online, bool):
            raise ActionError("invalid_args", "online must be true or false")
        self.spoolman.online = online
        return Outcome(True, f"Spoolman {'online' if online else 'offline'}")

    async def _printer(self, args: dict[str, Any]) -> Outcome:
        key = str(args.get("printer", "")).lower()
        if key in self.bambuddy_ids and self.bambuddy is not None:
            return await self._bambu(key, self.bambuddy_ids[key], args)
        if self.printers is None:
            raise ActionError("invalid_args", "Printers are not simulated (--printers live)")
        printer = self.printers.printers.get(key)
        if printer is None:
            raise ActionError("invalid_args", f"Unknown printer {args.get('printer')!r}")
        op = args.get("op")
        if op not in PRINTER_OPS:
            raise ActionError("invalid_args", f"op must be one of {', '.join(PRINTER_OPS)}")
        lane = args.get("lane")
        if op in ("lane", "insert", "eject") and lane not in printer.lanes:
            raise ActionError("invalid_args", f"{key} has no lane {lane!r}")
        if op == "connect":
            printer.connect()
        elif op == "disconnect":
            await printer.disconnect()
        elif op == "restart":
            await printer.restart_klippy()
        elif op == "insert":
            await printer.insert_lane(lane)
        elif op == "eject":
            await printer.eject_lane(lane)
        elif op == "lane":
            spool: int | None | str = "keep"
            if args.get("clear"):
                spool = None
            elif "spool_id" in args:
                spool = _optional_int(args, "spool_id")
            tool_loaded = args.get("tool_loaded")
            await printer.set_lane(
                lane, spool, status=args.get("status"), filament_status=args.get("filament_status"),
                tool_loaded=tool_loaded if isinstance(tool_loaded, bool) else None,
            )
        elif op == "print":
            progress = args.get("progress")
            if progress is not None and (isinstance(progress, bool) or not isinstance(progress, (int, float))):
                raise ActionError("invalid_args", "progress must be a number")
            await printer.set_print(state=args.get("state"), progress=progress, filename=args.get("filename"))
        elif op == "error":
            await printer.set_afc_error(str(args.get("message") or "AFC error"))
        elif op == "clear_error":
            await printer.set_afc_error(None)
        return Outcome(True, f"{key}: {op} done")

    async def _bambu(self, key: str, printer_id: int, args: dict[str, Any]) -> Outcome:
        """A Bambu printer behind the simulated Bambuddy; lanes are AMS 3H slots 3H-1 ... 3H-9."""
        sim = self.bambuddy
        assert sim is not None
        op = args.get("op")
        if op not in BAMBU_OPS:
            raise ActionError("invalid_args", f"op must be one of {', '.join(BAMBU_OPS)}")
        lane = args.get("lane")
        slot = slot_of(lane) if isinstance(lane, str) else None
        if op in ("insert", "eject") and slot is None:
            raise ActionError("invalid_args", f"{key} has no slot {lane!r} (3H-1 ... 3H-9)")
        if op == "connect":
            sim.connect()
        elif op == "disconnect":
            await sim.disconnect()
        elif op in ("power_on", "power_off"):
            await sim.power(printer_id, op == "power_on")
        elif op == "insert":
            assert slot is not None
            rfid = args.get("rfid")
            await sim.insert(printer_id, slot, material=str(args.get("material") or "PLA"),
                             color=str(args.get("color") or "808080"),
                             tray_uuid=str(rfid) if isinstance(rfid, str) and rfid else None)
        elif op == "eject":
            assert slot is not None
            await sim.eject(printer_id, slot)
        elif op == "print":
            progress = args.get("progress")
            if progress is not None and (isinstance(progress, bool) or not isinstance(progress, (int, float))):
                raise ActionError("invalid_args", "progress must be a number")
            state = args.get("state")
            await sim.set_print(printer_id, state=str(state) if state else None,
                                progress=None if progress is None else float(progress) * 100.0,
                                filename=args.get("filename"))
        elif op == "tool":
            await sim.set_tool(printer_id, slot)
        elif op == "error":
            await sim.set_hms(printer_id, str(args.get("message") or "HMS warning"))
        elif op == "clear_error":
            await sim.set_hms(printer_id, None)
        return Outcome(True, f"{key}: {op} done")
