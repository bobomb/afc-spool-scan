"""What every printer backend offers the rest of the station (Moonraker/AFC, Bambuddy)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .config import PrinterConfig
from .state import LaneState, PrinterState


class PrinterOffline(Exception):
    pass


class PrinterCommandError(Exception):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CommandResult:
    dry_run: bool
    responses: tuple[str, ...] = ()


GcodeResult = CommandResult


@dataclass(frozen=True)
class LaneLoad:
    """A lane took a spool. `assigned`: the station assigned it there (Bambuddy), so undo unassigns it
    and arms the printer again with `armed`; `previous` is the spool the lane had before."""

    printer: str
    lane: str
    spool_id: int
    assigned: bool = False
    dry_run: bool = False
    armed: int | None = None
    previous: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class PrinterNotice:
    """Something the user should see that no action caused, e.g. an RFID spool that differs from the scan."""

    printer: str
    message: str
    spool_id: int | None = None
    ok: bool = False
    code: str | None = "printer_notice"


LaneLoadHandler = Callable[[LaneLoad], None]
NoticeHandler = Callable[[PrinterNotice], None]


class PrinterClient(Protocol):
    printer: PrinterConfig
    state: PrinterState
    on_lane_loaded: LaneLoadHandler

    @property
    def key(self) -> str: ...

    @property
    def label(self) -> str: ...

    @property
    def online(self) -> bool: ...

    def start(self) -> None: ...

    async def stop(self) -> None: ...

    def refresh(self) -> None: ...

    def lane(self, lane: str) -> LaneState | None: ...

    async def set_next_spool(self, spool_id: int | None) -> CommandResult: ...

    async def set_lane_spool(self, lane: str, spool_id: int | None) -> CommandResult: ...
