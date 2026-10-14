#!/usr/bin/env python3
"""Read a stable gross weight from a DYMO M5/M10 USB HID postal scale."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from station.scale.dymo import (  # noqa: E402
    DEFAULT_PRODUCT_IDS,
    DEFAULT_VENDOR_ID,
    STABLE_STATUSES,
    UNIT_GRAMS,
    UNIT_OUNCES,
    decode_report,
    find_hidraw,
    read_hex,
    read_weight,
    signed_byte,
)

__all__ = [
    "DEFAULT_PRODUCT_IDS",
    "DEFAULT_VENDOR_ID",
    "STABLE_STATUSES",
    "UNIT_GRAMS",
    "UNIT_OUNCES",
    "decode_report",
    "find_hidraw",
    "main",
    "parse_args",
    "read_hex",
    "read_weight",
    "signed_byte",
]


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
