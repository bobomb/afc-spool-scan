"""Pure business rules: weight acceptance and the sanity check (dev plan §6.4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .scale.source import ScaleReading
from .state import ScaleState, SpoolInfo

EMPTY_MINIMUM_G = 10.0
SKIPPABLE_SCALE_CODES = frozenset({"scale_unavailable", "scale_unstable", "below_minimum"})


def fmt_g(grams: float) -> str:
    text = f"{grams:.1f}"
    return text[:-2] if text.endswith(".0") else text


def fmt_delta(grams: float) -> str:
    return ("+" if grams >= 0 else "-") + fmt_g(abs(grams))


def scale_problem(reading: ScaleReading, minimum_g: float) -> tuple[str, str] | None:
    """Return (code, message) when the reading cannot be accepted, else None."""
    status = reading.status
    if not reading.present or status == "absent":
        return "scale_unavailable", "Scale is off or disconnected"
    if status in ("fault", "calibrate"):
        return "scale_unavailable", f"Scale reports {status}; check the scale"
    if status == "over":
        return "scale_unavailable", "Scale is overloaded"
    if status in ("under", "rezero"):
        return "scale_unavailable", "Scale needs re-zeroing"
    if status == "motion":
        return "scale_unstable", "Scale is still settling"
    if status == "zero" or reading.grams is None:
        return "below_minimum", "Scale is empty"
    if status != "stable":
        return "scale_unavailable", f"Scale status {status}"
    if reading.grams <= minimum_g:
        return "below_minimum", f"Scale reads {fmt_g(reading.grams)} g (must be over {fmt_g(minimum_g)} g)"
    return None


@dataclass(frozen=True)
class SanityResult:
    status: str
    gross_g: float
    tare_g: float | None = None
    net_g: float | None = None
    expected_g: float | None = None
    delta_g: float | None = None
    limit_g: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "gross_g": self.gross_g,
            "tare_g": self.tare_g,
            "net_g": self.net_g,
            "expected_g": self.expected_g,
            "delta_g": self.delta_g,
            "limit_g": self.limit_g,
        }

    def message(self, spool_id: int) -> str:
        if self.status != "warn" or self.delta_g is None or self.expected_g is None:
            return ""
        return (
            f"Spool {spool_id}: measured {fmt_g(self.gross_g)} g differs from expected "
            f"{fmt_g(self.expected_g)} g by {fmt_delta(self.delta_g)} g"
        )


def sanity_check(gross_g: float, spool: SpoolInfo | None, threshold_g: float, threshold_pct: float) -> SanityResult:
    gross_g = round(gross_g, 1)
    if spool is None or not spool.found or spool.spool_weight_g is None:
        return SanityResult(status="tare_unknown", gross_g=gross_g)
    tare = spool.spool_weight_g
    net = round(gross_g - tare, 1)
    if spool.expected_gross_g is None:
        return SanityResult(status="ok", gross_g=gross_g, tare_g=tare, net_g=net)
    expected = spool.expected_gross_g
    delta = round(gross_g - expected, 1)
    limit = round(max(threshold_g, threshold_pct / 100.0 * expected), 1)
    status = "warn" if abs(delta) > limit else "ok"
    return SanityResult(status=status, gross_g=gross_g, tare_g=tare, net_g=net, expected_g=expected,
                        delta_g=delta, limit_g=limit)


def derive_scale_state(
    reading: ScaleReading, spool: SpoolInfo | None, threshold_g: float, threshold_pct: float
) -> ScaleState:
    state = ScaleState(
        present=reading.present,
        status=reading.status,
        grams=reading.grams,
        source_unit=reading.source_unit,
        stable=reading.stable,
    )
    if not reading.present or reading.grams is None or reading.grams <= 0 or spool is None or not spool.found:
        return state
    check = sanity_check(reading.grams, spool, threshold_g, threshold_pct)
    state.tare_g = check.tare_g
    state.net_g = check.net_g
    state.expected_g = check.expected_g
    state.delta_g = check.delta_g
    state.check = check.status
    return state


def empty_spool_check(gross_g: float, spool: SpoolInfo, threshold_g: float, threshold_pct: float) -> str | None:
    """Message when the measured empty spool is far from the known tare, else None."""
    if spool.spool_weight_g is None:
        return None
    tare = spool.spool_weight_g
    limit = max(threshold_g, threshold_pct / 100.0 * tare)
    if abs(gross_g - tare) <= limit:
        return None
    return (
        f"Spool {spool.id}: measured {fmt_g(gross_g)} g but the empty spool should weigh about "
        f"{fmt_g(tare)} g. Record it as empty anyway?"
    )
