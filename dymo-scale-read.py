#!/usr/bin/env python3
"""Read a stable gross weight from a DYMO M5/M10 USB HID postal scale."""

from __future__ import annotations

import argparse
import os
import select
import sys
import time
from pathlib import Path

DEFAULT_VENDOR_ID = "0922"
DEFAULT_PRODUCT_IDS = {"8003"}
UNIT_GRAMS = 2
UNIT_OUNCES = 11
STABLE_STATUSES = {2, 4}


def read_hex(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii").strip().lower()
    except OSError:
        return ""


def find_hidraw(vendor_id: str, product_ids: set[str]) -> Path:
    for hidraw_class in sorted(Path("/sys/class/hidraw").glob("hidraw*")):
        current = hidraw_class.resolve()
        while current != current.parent:
            if (
                read_hex(current / "idVendor") == vendor_id
                and read_hex(current / "idProduct") in product_ids
            ):
                return Path("/dev") / hidraw_class.name
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
        grams = value * 28.349523125
    else:
        raise ValueError(f"unsupported DYMO unit code {unit}")

    return grams, status, unit


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=Path, help="explicit /dev/hidraw device")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--vendor-id", default=DEFAULT_VENDOR_ID)
    parser.add_argument(
        "--product-ids",
        default=",".join(sorted(DEFAULT_PRODUCT_IDS)),
        help="comma-separated USB product IDs",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="include source unit on stderr"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    product_ids = {
        value.strip().lower() for value in args.product_ids.split(",") if value.strip()
    }
    try:
        device = args.device or find_hidraw(args.vendor_id.lower(), product_ids)
        grams, unit = read_weight(device, args.timeout)
    except (OSError, RuntimeError) as error:
        print(f"Scale error: {error}", file=sys.stderr)
        return 1

    if args.verbose:
        source_unit = "g" if unit == UNIT_GRAMS else "oz"
        print(f"Read {grams:.1f} g from {device} (source unit: {source_unit})", file=sys.stderr)
    print(f"{grams:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
