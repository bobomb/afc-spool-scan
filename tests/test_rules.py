from __future__ import annotations

import pytest

from station.rules import (
    derive_scale_state,
    empty_spool_check,
    fmt_delta,
    fmt_g,
    sanity_check,
    scale_problem,
)
from station.scale.source import ABSENT, ScaleReading
from station.state import SpoolInfo

SPOOL = SpoolInfo(id=97, remaining_g=454.7, spool_weight_g=180.0, expected_gross_g=634.7)


def reading(status: str, grams: float | None = 984.0) -> ScaleReading:
    return ScaleReading(present=True, status=status, grams=grams, source_unit="g")


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (ABSENT, "scale_unavailable"),
        (reading("fault"), "scale_unavailable"),
        (reading("calibrate"), "scale_unavailable"),
        (reading("over"), "scale_unavailable"),
        (reading("under"), "scale_unavailable"),
        (reading("rezero"), "scale_unavailable"),
        (reading("motion"), "scale_unstable"),
        (reading("zero", 0.0), "below_minimum"),
        (reading("stable", 50.0), "below_minimum"),
        (reading("stable", 12.0), "below_minimum"),
    ],
)
def test_scale_problems(value: ScaleReading, code: str) -> None:
    problem = scale_problem(value, 50)
    assert problem is not None and problem[0] == code


def test_stable_reading_over_minimum_is_accepted() -> None:
    assert scale_problem(reading("stable", 50.1), 50) is None
    assert scale_problem(reading("stable", 11.0), 10) is None


def test_sanity_check_warns_beyond_threshold() -> None:
    result = sanity_check(984.0, SPOOL, threshold_g=50, threshold_pct=10)
    assert result.status == "warn"
    assert (result.tare_g, result.net_g, result.expected_g, result.delta_g, result.limit_g) == (
        180.0, 804.0, 634.7, 349.3, 63.5,
    )
    assert result.message(97) == "Spool 97: measured 984 g differs from expected 634.7 g by +349.3 g"


def test_sanity_check_within_threshold() -> None:
    assert sanity_check(680.0, SPOOL, 50, 10).status == "ok"
    assert sanity_check(580.0, SPOOL, 50, 10).status == "ok"
    assert sanity_check(560.0, SPOOL, 50, 10).status == "warn"
    assert sanity_check(560.0, SPOOL, 100, 0).status == "ok"
    assert sanity_check(560.0, SPOOL, 100, 0).message(97) == ""


def test_sanity_check_unknown_tare() -> None:
    assert sanity_check(900.0, SpoolInfo(id=99, remaining_g=812.0), 50, 10).status == "tare_unknown"
    assert sanity_check(900.0, None, 50, 10).status == "tare_unknown"
    no_remaining = SpoolInfo(id=1, spool_weight_g=200.0)
    result = sanity_check(900.0, no_remaining, 50, 10)
    assert (result.status, result.net_g, result.delta_g) == ("ok", 700.0, None)


def test_derive_scale_state() -> None:
    state = derive_scale_state(reading("stable"), SPOOL, 50, 10)
    assert (state.stable, state.net_g, state.delta_g, state.check) == (True, 804.0, 349.3, "warn")
    assert derive_scale_state(reading("zero", 0.0), SPOOL, 50, 10).check is None
    assert derive_scale_state(ABSENT, SPOOL, 50, 10).present is False
    assert derive_scale_state(reading("motion"), None, 50, 10).net_g is None
    missing = SpoolInfo(id=5, found=False)
    assert derive_scale_state(reading("stable"), missing, 50, 10).check is None


def test_empty_spool_check() -> None:
    assert empty_spool_check(185.0, SPOOL, 50, 10) is None
    assert "should weigh about 180 g" in empty_spool_check(950.0, SPOOL, 50, 10)
    assert empty_spool_check(950.0, SpoolInfo(id=99), 50, 10) is None


def test_formatting() -> None:
    assert fmt_g(984.0) == "984"
    assert fmt_g(984.04) == "984"
    assert fmt_g(984.25) == "984.2"
    assert fmt_delta(-12.5) == "-12.5"
    assert fmt_delta(0) == "+0"
