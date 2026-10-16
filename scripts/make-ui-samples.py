#!/usr/bin/env python3
"""Generate ui/samples/*.json state files from the simulated station.

The samples drive the UI snapshot mode (`station-ui --snapshot DIR --state FILE`)
and the C++ model tests, so they always match the live protocol. Runs fully
in-process against the simulators; no network or hardware is used.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from station import __version__  # noqa: E402
from station.app import Station  # noqa: E402
from station.config import DEFAULT_PRINTERS, Config, parse_printers  # noqa: E402

OUT = REPO / "ui" / "samples"


async def wait_until(predicate: Any, timeout: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise RuntimeError("timed out waiting for the simulated station")
        await asyncio.sleep(0.01)


async def build() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        config = Config(hardware="sim", printers_mode="sim", spoolman_mode="sim", writes=False, ipc_port=0,
                        state_dir=Path(tmp), printers=parse_printers(DEFAULT_PRINTERS))
        station = Station(config, printer_backoff=(0.02, 0.05), publish_delay=0, scale_interval=0)
        await station.start()
        try:
            await wait_until(lambda: all(p.connected for p in station.store.printers.values()))
            minutes = iter(range(60))
            station.activity.clock = lambda: f"2026-10-13T20:{next(minutes):02d}:12Z"

            async def act(action: str, **args: Any) -> dict[str, Any]:
                result = await station.actions.handle(action, args)
                return result

            await act("sim.scale", grams=1057.0)
            await act("weigh", spool_id=84)
            await act("load", spool_id=93, target="yankee")
            await act("sim.printer", printer="yankee", op="insert", lane="lane3")
            await act("sim.scale", grams=176.5)
            await act("empty_spool", spool_id=60, confirm=True)
            await act("sim.spoolman", online=False)
            await act("sim.scale", grams=702.0)
            await act("weigh", spool_id=86)
            await act("sim.spoolman", online=True)
            await act("sim.scale", grams=640.0)
            undo_me = await act("weigh_load", spool_id=97, target="kilo")
            await act("undo", activity_id=undo_me["activity_id"])
            await act("sim.scale", grams=1102.0)
            await act("weigh_load", spool_id=90)
            await act("set_setting", key="sanity_threshold_g", value=50)
            await act("sim.printer", printer="yankee", op="print", state="printing", progress=0.42,
                      filename="enclosure_hinge.gcode")
            await act("sim.printer", printer="yankee", op="error", message="lane4: filament jam detected at hub")
            await act("load", spool_id=91, target="yankee")
            await act("lookup", spool_id=97)
            await act("sim.scale", grams=984.0)
            await wait_until(lambda: station.store.printers["yankee"].afc_error is not None)
            await wait_until(lambda: all(lane.remaining_pct is not None for p in station.store.printers.values()
                                         for lane in p.lanes if lane.spool_id is not None))
            snapshot = copy.deepcopy(station.store.snapshot())
            snapshot["scan"].update(last_code="WEB+SPOOLMAN:S-97", spool_id=97, at="2026-10-13T20:59:58Z")
            await act("lookup", spool_id=93)
            await act("sim.scale", grams=841.0)
            multicolor = {"spool": copy.deepcopy(station.store.snapshot()["spool"]),
                          "scale": copy.deepcopy(station.store.snapshot()["scale"])}
            hello = {"type": "hello", "protocol": 1, "service_version": __version__, "hardware": "sim",
                     "printers": "sim", "spoolman": "sim", "writes": False}
            return {"hello": hello, "snapshot": json.loads(json.dumps(snapshot)),
                    "multicolor": json.loads(json.dumps(multicolor))}
        finally:
            await station.stop()


def sample(base: dict[str, Any], screens: list[str], **changes: Any) -> dict[str, Any]:
    data = {key: copy.deepcopy(value) for key, value in base.items() if key != "multicolor"}
    data["screens"] = screens
    for key, value in changes.items():
        data[key] = value
    return data


def main() -> int:
    base = asyncio.run(build())
    snap = base["snapshot"]
    samples: dict[str, dict[str, Any]] = {
        "main": sample(base, ["main"]),
        "printers": sample(base, ["printers"]),
        "log": sample(base, ["log"]),
        "settings": sample(base, ["settings"]),
    }

    multicolor = sample(base, ["main"])
    multicolor["snapshot"].update(base["multicolor"])
    samples["multicolor"] = multicolor

    keypad = sample(base, ["main"], keypad="93")
    samples["keypad"] = keypad

    prompt = sample(base, ["main"])
    prompt["snapshot"]["scan"]["prompt"] = {
        "kind": "confirm_weigh", "spool_id": 97,
        "message": "Spool 97: measured 984 g differs from expected 634.7 g by +349.3 g",
        "gross_g": 984.0, "tare_g": 180.0, "net_g": 804.0, "expected_g": 634.7, "delta_g": 349.3,
    }
    samples["prompt"] = prompt

    countdown = sample(base, ["main"])
    countdown["snapshot"]["scan"]["countdown"] = {"spool_id": 97, "action": "weigh_load", "remaining_s": 3}
    countdown["snapshot"]["settings"]["scan_mode"] = "countdown"
    samples["countdown"] = countdown

    light = sample(base, ["main", "printers", "log", "settings"])
    light["snapshot"]["settings"]["theme"] = "light"
    samples["light"] = light

    empty = sample(base, ["main"])
    empty["snapshot"]["spool"] = None
    empty["snapshot"]["scale"] = {"present": True, "status": "zero", "grams": 0.0, "source_unit": "g",
                                  "stable": False, "tare_g": None, "net_g": None, "expected_g": None,
                                  "delta_g": None, "check": None}
    empty["snapshot"]["activity"] = []
    samples["empty"] = empty

    low = sample(base, ["main"])
    low["snapshot"]["spool"] = {**snap["spool"], "id": 86, "vendor": "eSun", "name": "PETG Solid Blue",
                                "material": "PETG", "color": "#1E5AA8", "colors": ["#1E5AA8"], "remaining_g": 74.2,
                                "spool_weight_g": 224.0, "expected_gross_g": 298.2, "location": "Kilo",
                                "initial_weight_g": 1000.0, "low_stock": True}
    low["snapshot"]["scale"] = {"present": True, "status": "motion", "grams": 301.6, "source_unit": "oz",
                                "stable": False, "tare_g": 224.0, "net_g": 77.6, "expected_g": 298.2,
                                "delta_g": 3.4, "check": "ok"}
    samples["low_stock"] = low

    missing = sample(base, ["main"])
    missing["snapshot"]["spool"] = {"id": 999, "found": False, "message": "Spool 999 not found"}
    missing["snapshot"]["scale"] = {"present": False, "status": "absent", "grams": None, "source_unit": None,
                                    "stable": False, "tare_g": None, "net_g": None, "expected_g": None,
                                    "delta_g": None, "check": None}
    missing["snapshot"]["health"]["scale"] = False
    missing["snapshot"]["health"]["scale_status"] = "absent"
    samples["not_found"] = missing

    offline = sample(base, ["main"], connected=False)
    samples["offline"] = offline

    dry_run = sample(base, ["main", "printers"])
    dry_run["hello"].update(printers="live", spoolman="live", writes=False)
    dry_run["snapshot"]["service"].update(printers="live", spoolman="live", writes=False, dry_run=True,
                                          hardware="sim")
    dry_run["snapshot"]["printers"][1]["connected"] = False
    dry_run["snapshot"]["printers"][1]["klippy_state"] = "disconnected"
    samples["dry_run"] = dry_run

    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in samples.items():
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {OUT / (name + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
