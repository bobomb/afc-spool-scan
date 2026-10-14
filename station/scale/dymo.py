"""DYMO M5/M10 USB HID postal scale: discovery, report decoding and reads.

Standard library only: dymo-scale-read.py imports this with the system python3.
"""

from __future__ import annotations

import os
import select
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VENDOR_ID = "0922"
DEFAULT_PRODUCT_IDS = {"8003"}
UNIT_GRAMS = 2
UNIT_OUNCES = 11
GRAMS_PER_OUNCE = 28.349523125
STABLE_STATUSES = {2, 4}

STATUS_FAULT = 1
STATUS_ZERO = 2
STATUS_MOTION = 3
STATUS_STABLE = 4
STATUS_UNDER = 5
STATUS_OVER = 6
STATUS_CALIBRATE = 7
STATUS_REZERO = 8

STATUS_NAMES = {
    STATUS_FAULT: "fault",
    STATUS_ZERO: "zero",
    STATUS_MOTION: "motion",
    STATUS_STABLE: "stable",
    STATUS_UNDER: "under",
    STATUS_OVER: "over",
    STATUS_CALIBRATE: "calibrate",
    STATUS_REZERO: "rezero",
}
UNIT_NAMES = {UNIT_GRAMS: "g", UNIT_OUNCES: "oz"}

HIDRAW_CLASS_DIR = Path("/sys/class/hidraw")
DEV_DIR = Path("/dev")


@dataclass(frozen=True)
class Reading:
    grams: float
    status: int
    unit: int

    @property
    def status_name(self) -> str:
        return STATUS_NAMES.get(self.status, "fault")

    @property
    def unit_name(self) -> str:
        return UNIT_NAMES.get(self.unit, "?")


def read_hex(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").strip().lower()
    except OSError:
        return ""


def find_hidraw(
    vendor_id: str,
    product_ids: set[str],
    class_dir: Path = HIDRAW_CLASS_DIR,
    dev_dir: Path = DEV_DIR,
) -> Path:
    for hidraw_class in sorted(class_dir.glob("hidraw*")):
        current = hidraw_class.resolve()
        while current != current.parent:
            if (
                read_hex(current / "idVendor") == vendor_id
                and read_hex(current / "idProduct") in product_ids
            ):
                return dev_dir / hidraw_class.name
            current = current.parent
    products = ", ".join(sorted(product_ids))
    raise RuntimeError(
        f"DYMO scale {vendor_id}:{products} was not found; reconnect it and try again"
    )


def signed_byte(value: int) -> int:
    return value - 256 if value > 127 else value


def decode_report(report: bytes) -> tuple[float, int, int]:
    if len(report) < 6:
        raise ValueError(f"short HID report ({len(report)} bytes)")

    status = report[1]
    unit = report[2]
    exponent = signed_byte(report[3])
    raw_weight = report[4] | (report[5] << 8)
    value = raw_weight * (10**exponent)

    if unit == UNIT_GRAMS:
        grams = value
    elif unit == UNIT_OUNCES:
        grams = value * GRAMS_PER_OUNCE
    else:
        raise ValueError(f"unsupported DYMO unit code {unit}")

    return grams, status, unit


def decode_reading(report: bytes) -> Reading:
    grams, status, unit = decode_report(report)
    return Reading(grams=grams, status=status, unit=unit)


def read_weight(device: Path, timeout: float) -> tuple[float, int]:
    deadline = time.monotonic() + timeout
    try:
        fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    except PermissionError as error:
        raise RuntimeError(
            f"permission denied opening {device}; install 99-dymo-scale.rules"
        ) from error

    last_problem = "no HID report received"
    try:
        while (remaining := deadline - time.monotonic()) > 0:
            readable, _, _ = select.select([fd], [], [], remaining)
            if not readable:
                break
            try:
                report = os.read(fd, 64)
                grams, status, unit = decode_report(report)
            except (BlockingIOError, ValueError) as error:
                last_problem = str(error)
                continue

            if status not in STABLE_STATUSES:
                last_problem = f"scale reading is not stable (status {status})"
                continue
            if grams < 0:
                last_problem = "scale reported a negative weight"
                continue
            return grams, unit
    finally:
        os.close(fd)

    raise RuntimeError(f"no stable scale reading before timeout: {last_problem}")
