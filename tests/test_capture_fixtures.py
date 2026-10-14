from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from station.sim.printers import SimPrinterServer, load_printer_fixture
from station.sim.spoolman import SimSpoolman

REPO = Path(__file__).resolve().parent.parent


def load_script():  # noqa: ANN201
    spec = importlib.util.spec_from_file_location("capture_fixtures", REPO / "scripts" / "capture-fixtures.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_capture_round_trips_simulated_services(tmp_path: Path) -> None:
    capture = load_script()
    printers = SimPrinterServer.from_fixtures(["kilo", "yankee"])
    spoolman = SimSpoolman()
    await printers.start()
    spoolman_url = await spoolman.start()
    try:
        written = await capture.capture(
            {key: printers.url_for(key) for key in ("kilo", "yankee")}, spoolman_url, [97, 86, 60], tmp_path,
        )
    finally:
        await printers.stop()
        await spoolman.stop()
    assert sorted(path.name for path in written) == ["kilo.json", "spools.json", "yankee.json"]
    captured = json.loads((tmp_path / "printers" / "kilo.json").read_text(encoding="utf-8"))
    original = load_printer_fixture("kilo")
    assert captured["objects"] == original["objects"]
    assert captured["object_list"] == original["object_list"]
    assert captured["server_info"]["klippy_state"] == "ready"
    spools = json.loads((tmp_path / "spoolman" / "spools.json").read_text(encoding="utf-8"))["spools"]
    assert [spool["id"] for spool in spools] == [97, 86, 60]
    assert spoolman.requests and all(method == "GET" for method, _, _ in spoolman.requests)
    assert printers.printers["kilo"].gcode_log == []
