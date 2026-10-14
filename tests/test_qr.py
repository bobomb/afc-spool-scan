from __future__ import annotations

import pytest

from station.qr import extract_spool_id


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("web+spoolman:s-97", 97),
        ("WEB+SPOOLMAN:S-97", 97),
        ("Web+Spoolman:S-123", 123),
        ("http://192.0.2.10:7912/spool/show/97", 97),
        ("HTTP://SPOOLPI:7912/SPOOL/SHOW/97", 97),
        ("https://spoolman.example/spool/show/42/", 42),
        ("https://spoolman.example/spool/show/42?tab=info", 42),
        ("https://spoolman.example/spool/show/42#top", 42),
    ],
)
def test_recognized_codes(code: str, expected: int) -> None:
    assert extract_spool_id(code) == expected


@pytest.mark.parametrize(
    "code",
    [
        "",
        "web+spoolman:s-",
        "web+spoolman:s-abc",
        "web+spoolman:s-97x",
        "web+spoolman:s- 97",
        "web+spoolman:f-97",
        "http://host/spool/show/abc",
        "http://host/spool/show/97abc",
        "http://host/filament/show/97",
        "97",
        "web+spoolman:s-٩٧",
    ],
)
def test_rejected_codes(code: str) -> None:
    assert extract_spool_id(code) is None


def test_custom_prefix() -> None:
    assert extract_spool_id("SPOOL:12", prefix="spool:") == 12
    assert extract_spool_id("web+spoolman:s-12", prefix="spool:") is None
