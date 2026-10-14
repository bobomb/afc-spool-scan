"""Simulated QR scanner driven by simctl (`python -m station.simctl scan …`)."""

from __future__ import annotations

from collections.abc import Callable


class SimScanner:
    def __init__(self, on_scan: Callable[[str], None], on_presence: Callable[[bool], None]) -> None:
        self.on_scan = on_scan
        self.on_presence = on_presence

    def start(self) -> None:
        self.on_presence(True)

    async def stop(self) -> None:
        return None

    def inject(self, code: str) -> None:
        self.on_scan(code)
