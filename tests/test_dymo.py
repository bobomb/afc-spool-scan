from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from station.scale import dymo

REPO = Path(__file__).resolve().parent.parent


def report(status: int, unit: int, exponent: int, raw: int) -> bytes:
    return bytes([3, status, unit, exponent & 0xFF, raw & 0xFF, (raw >> 8) & 0xFF])


def test_decode_grams() -> None:
    assert dymo.decode_report(report(4, dymo.UNIT_GRAMS, 0, 984)) == (984, 4, 2)


def test_decode_ounces_converts_to_grams() -> None:
    grams, status, unit = dymo.decode_report(report(4, dymo.UNIT_OUNCES, -1, 125))
    assert unit == dymo.UNIT_OUNCES
    assert status == 4
    assert grams == pytest.approx(12.5 * 28.349523125)


def test_decode_negative_exponent() -> None:
    grams, _, _ = dymo.decode_report(report(4, dymo.UNIT_GRAMS, -1, 9841))
    assert grams == pytest.approx(984.1)


def test_decode_uses_little_endian_weight() -> None:
    grams, _, _ = dymo.decode_report(bytes([3, 4, 2, 0, 0x10, 0x27]))
    assert grams == 10000


def test_decode_short_report() -> None:
    with pytest.raises(ValueError, match="short HID report"):
        dymo.decode_report(b"\x03\x04\x02\x00\x10")


def test_decode_unsupported_unit() -> None:
    with pytest.raises(ValueError, match="unsupported DYMO unit"):
        dymo.decode_report(report(4, 7, 0, 10))


@pytest.mark.parametrize(
    ("status", "name"),
    [
        (1, "fault"),
        (2, "zero"),
        (3, "motion"),
        (4, "stable"),
        (5, "under"),
        (6, "over"),
        (7, "calibrate"),
        (8, "rezero"),
    ],
)
def test_every_status_byte(status: int, name: str) -> None:
    reading = dymo.decode_reading(report(status, dymo.UNIT_GRAMS, 0, 10))
    assert reading.status == status
    assert reading.status_name == name


def test_unknown_status_maps_to_fault() -> None:
    assert dymo.decode_reading(report(42, dymo.UNIT_GRAMS, 0, 1)).status_name == "fault"


def test_signed_byte() -> None:
    assert dymo.signed_byte(0xFF) == -1
    assert dymo.signed_byte(0x7F) == 127
    assert dymo.signed_byte(0x80) == -128


def test_find_hidraw_walks_parent_devices(tmp_path: Path) -> None:
    usb = tmp_path / "devices" / "usb1" / "1-1"
    hid = usb / "1-1.0" / "0003-0922-8003.0001" / "hidraw"
    (hid / "hidraw3").mkdir(parents=True)
    (usb / "idVendor").write_text("0922\n", encoding="ascii")
    (usb / "idProduct").write_text("8003\n", encoding="ascii")
    other = tmp_path / "devices" / "usb2" / "2-1"
    (other / "hid" / "hidraw").mkdir(parents=True)
    (other / "hid" / "hidraw" / "hidraw0").mkdir()
    (other / "idVendor").write_text("046d\n", encoding="ascii")
    (other / "idProduct").write_text("c52b\n", encoding="ascii")

    found = dymo.find_hidraw("0922", {"8003"}, class_dir=hid, dev_dir=Path("/dev"))
    assert found == Path("/dev") / "hidraw3"
    with pytest.raises(RuntimeError, match="was not found"):
        dymo.find_hidraw("0922", {"8003"}, class_dir=other / "hid" / "hidraw")


class FakeHid:
    def __init__(self, reports: list[bytes]) -> None:
        self.reports = list(reports)
        self.closed = False

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(os, "O_NONBLOCK", getattr(os, "O_NONBLOCK", 0x800), raising=False)
        monkeypatch.setattr(dymo.os, "open", lambda *_: 99)
        monkeypatch.setattr(dymo.os, "close", self.close)
        monkeypatch.setattr(dymo.os, "read", self.read)
        monkeypatch.setattr(dymo.select, "select", self.select)

    def close(self, fd: int) -> None:
        self.closed = True

    def read(self, fd: int, size: int) -> bytes:
        return self.reports.pop(0)

    def select(self, r, w, x, timeout):  # noqa: ANN001, ANN201
        return (r, [], []) if self.reports else ([], [], [])


def test_read_weight_skips_unstable_and_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeHid(
        [
            report(3, dymo.UNIT_GRAMS, 0, 500),
            b"\x03",
            report(4, dymo.UNIT_GRAMS, 0, 984),
        ]
    )
    fake.install(monkeypatch)
    assert dymo.read_weight(Path("/dev/hidraw0"), 1.0) == (984, dymo.UNIT_GRAMS)
    assert fake.closed


def test_read_weight_times_out_without_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeHid([report(3, dymo.UNIT_GRAMS, 0, 500)])
    fake.install(monkeypatch)
    with pytest.raises(RuntimeError, match="not stable"):
        dymo.read_weight(Path("/dev/hidraw0"), 0.2)


def load_cli():  # noqa: ANN201
    spec = importlib.util.spec_from_file_location("dymo_scale_read", REPO / "dymo-scale-read.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_reexports_decoder() -> None:
    cli = load_cli()
    assert cli.decode_report is dymo.decode_report
    assert cli.find_hidraw is dymo.find_hidraw


def test_cli_prints_grams(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cli = load_cli()
    monkeypatch.setattr(sys, "argv", ["dymo-scale-read.py", "--verbose"])
    monkeypatch.setattr(cli, "find_hidraw", lambda vendor, products: Path("/dev/hidraw0"))
    monkeypatch.setattr(cli, "read_weight", lambda device, timeout: (354.369, dymo.UNIT_OUNCES))
    assert cli.main() == 0
    captured = capsys.readouterr()
    assert captured.out == "354.4\n"
    assert captured.err == f"Read 354.4 g from {Path('/dev/hidraw0')} (source unit: oz)\n"


def test_cli_passes_options(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cli = load_cli()
    seen: dict[str, object] = {}

    def fake_find(vendor: str, products: set[str]) -> Path:
        seen.update(vendor=vendor, products=products)
        return Path("/dev/hidraw1")

    def fake_read(device: Path, timeout: float) -> tuple[float, int]:
        seen.update(device=device, timeout=timeout)
        return 984.0, dymo.UNIT_GRAMS

    monkeypatch.setattr(
        sys,
        "argv",
        ["dymo-scale-read.py", "--timeout", "3", "--vendor-id", "0922", "--product-ids", "8003, 8004"],
    )
    monkeypatch.setattr(cli, "find_hidraw", fake_find)
    monkeypatch.setattr(cli, "read_weight", fake_read)
    assert cli.main() == 0
    assert seen == {
        "vendor": "0922",
        "products": {"8003", "8004"},
        "device": Path("/dev/hidraw1"),
        "timeout": 3.0,
    }
    assert capsys.readouterr().out == "984.0\n"


def test_cli_reports_errors(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    cli = load_cli()
    monkeypatch.setattr(sys, "argv", ["dymo-scale-read.py"])

    def missing(vendor: str, products: set[str]) -> Path:
        raise RuntimeError("DYMO scale 0922:8003 was not found; reconnect it and try again")

    monkeypatch.setattr(cli, "find_hidraw", missing)
    assert cli.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Scale error: DYMO scale 0922:8003 was not found; reconnect it and try again\n"
