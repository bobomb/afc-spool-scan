"""Simulated scale driven by simctl (`python -m station.simctl scale …`)."""

from __future__ import annotations

from collections.abc import Callable

from .dymo import GRAMS_PER_OUNCE, STATUS_NAMES
from .source import ABSENT, ScaleReading, ScaleSource

STATUSES = ("absent", *STATUS_NAMES.values())


class SimScale(ScaleSource):
    def __init__(self, on_reading: Callable[[ScaleReading], None], **kwargs: object) -> None:
        super().__init__(on_reading, **kwargs)  # type: ignore[arg-type]
        self._initial = ScaleReading(present=True, status="zero", grams=0.0, source_unit="g")

    async def run(self) -> None:
        self.update(self._initial)
        await super().run()

    def set(self, grams: float | None = None, unit: str = "g", status: str | None = None) -> ScaleReading:
        if unit not in ("g", "oz"):
            raise ValueError("unit must be g or oz")
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        if status == "absent":
            self.update(ABSENT)
            return ABSENT
        previous = self.current if self.current.present else self._initial
        if grams is None:
            value = previous.grams
            source_unit = previous.source_unit
        else:
            value = round(grams * GRAMS_PER_OUNCE if unit == "oz" else grams, 1)
            source_unit = unit
        if status is None:
            status = "zero" if not value else ("under" if value < 0 else "stable")
        reading = ScaleReading(present=True, status=status, grams=value, source_unit=source_unit)
        self.update(reading)
        return reading
