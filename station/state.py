"""Typed service state (dev plan §5.2) and topic change notifications."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

TOPICS = ("scale", "scan", "spool", "printer", "activity", "health", "settings")

Listener = Callable[[str, Any], None]


@dataclass
class ScaleState:
    present: bool = False
    status: str = "absent"
    grams: float | None = None
    source_unit: str | None = None
    stable: bool = False
    tare_g: float | None = None
    net_g: float | None = None
    expected_g: float | None = None
    delta_g: float | None = None
    check: str | None = None


@dataclass
class Countdown:
    spool_id: int
    action: str
    remaining_s: int


@dataclass
class Prompt:
    kind: str
    spool_id: int
    message: str
    gross_g: float | None = None
    tare_g: float | None = None
    net_g: float | None = None
    expected_g: float | None = None
    delta_g: float | None = None


@dataclass
class ScanState:
    last_code: str | None = None
    spool_id: int | None = None
    at: str | None = None
    countdown: Countdown | None = None
    prompt: Prompt | None = None


@dataclass
class SpoolInfo:
    id: int
    found: bool = True
    vendor: str | None = None
    name: str | None = None
    material: str | None = None
    color: str | None = None
    remaining_g: float | None = None
    spool_weight_g: float | None = None
    expected_gross_g: float | None = None
    initial_weight_g: float | None = None
    used_weight_g: float | None = None
    tare_source: str | None = None
    location: str | None = None
    last_used: str | None = None
    archived: bool = False
    low_stock: bool = False
    message: str | None = None


@dataclass
class LaneState:
    lane: str
    map: str | None = None
    spool_id: int | None = None
    material: str | None = None
    color: str | None = None
    remaining_g: float | None = None
    filament_status: str | None = None
    status: str | None = None
    prep: bool = False
    load: bool = False
    tool_loaded: bool = False
    low_stock: bool = False


@dataclass
class PrinterState:
    key: str
    name: str
    connected: bool = False
    klippy_state: str | None = None
    print_state: str | None = None
    progress: float | None = None
    filename: str | None = None
    afc_state: str | None = None
    afc_error: str | None = None
    current_load: str | None = None
    pending_spool: int | None = None
    pending_confirmed: bool = False
    lanes: list[LaneState] = field(default_factory=list)


@dataclass
class HealthState:
    spoolman: bool = False
    scale: bool = False
    scanner: bool = False
    scale_status: str = "absent"


@dataclass
class ServiceInfo:
    version: str
    protocol: int
    hardware: str
    printers: str
    spoolman: str
    writes: bool


def to_data(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value


class Store:
    """Holds the published state and notifies listeners of topic changes.

    Each event's data replaces that topic's subtree; `printer` events carry one
    printer and replace the entry with the same key.
    """

    def __init__(self, service: ServiceInfo) -> None:
        self.service = service
        self.scale = ScaleState()
        self.scan = ScanState()
        self.spool: SpoolInfo | None = None
        self.printers: dict[str, PrinterState] = {}
        self.health = HealthState()
        self.activity: list[dict[str, Any]] = []
        self.settings: dict[str, Any] = {}
        self._listeners: list[Listener] = []
        self._last: dict[tuple[str, str | None], Any] = {}

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def snapshot(self) -> dict[str, Any]:
        return {
            "service": to_data(self.service),
            "scale": to_data(self.scale),
            "scan": to_data(self.scan),
            "spool": to_data(self.spool),
            "printers": [to_data(printer) for printer in self.printers.values()],
            "health": to_data(self.health),
            "activity": list(self.activity),
            "settings": dict(self.settings),
        }

    def _emit(self, topic: str, data: Any, key: str | None = None, force: bool = False) -> bool:
        if not force and self._last.get((topic, key), object()) == data:
            return False
        self._last[(topic, key)] = data
        for listener in list(self._listeners):
            listener(topic, data)
        return True

    def set_scale(self, scale: ScaleState) -> bool:
        self.scale = scale
        return self._emit("scale", to_data(scale))

    def set_scan(self, scan: ScanState) -> bool:
        self.scan = scan
        return self._emit("scan", to_data(scan))

    def set_spool(self, spool: SpoolInfo | None) -> bool:
        self.spool = spool
        return self._emit("spool", to_data(spool))

    def set_printer(self, printer: PrinterState) -> bool:
        self.printers[printer.key] = printer
        return self._emit("printer", to_data(printer), key=printer.key)

    def set_health(self, health: HealthState) -> bool:
        self.health = health
        return self._emit("health", to_data(health))

    def set_activity(self, entries: list[dict[str, Any]]) -> bool:
        self.activity = entries
        return self._emit("activity", list(entries))

    def set_settings(self, settings: dict[str, Any]) -> bool:
        self.settings = dict(settings)
        return self._emit("settings", dict(settings))
