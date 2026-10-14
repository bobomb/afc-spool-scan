"""Spool ID extraction from scanned QR codes (port of usb-qr-scanner-read.sh)."""

from __future__ import annotations

import re

DEFAULT_PREFIX = "web+spoolman:s-"
_URL_PATTERN = re.compile(r"/spool/show/([0-9]+)(?:[/?#]|$)")
_DIGITS = re.compile(r"[0-9]+")


def extract_spool_id(code: str, prefix: str = DEFAULT_PREFIX) -> int | None:
    """Return the spool ID in a Spoolman QR code, or None if it has none.

    Prefixes and URLs are matched case-insensitively, like the bash scanner.
    """
    normalized = code.lower()
    candidate = ""
    if prefix and normalized.startswith(prefix.lower()):
        candidate = code[len(prefix):]
    else:
        match = _URL_PATTERN.search(normalized)
        if match:
            candidate = match.group(1)
    if _DIGITS.fullmatch(candidate):
        return int(candidate)
    return None
