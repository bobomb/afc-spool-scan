from __future__ import annotations

import json
from pathlib import Path

import pytest

from station.activity import ActivityLog, UndoStep
from station.settings import DEFAULTS, Settings, SettingsError
from station.state import LaneState, PrinterState, ScaleState, ServiceInfo, SpoolInfo, Store


def make_store() -> Store:
    return Store(ServiceInfo(version="t", protocol=1, hardware="sim", printers="sim", spoolman="sim", writes=False))


def test_snapshot_matches_protocol_shape() -> None:
    store = make_store()
    store.set_printer(PrinterState(key="kilo", name="Kilo", lanes=[LaneState(lane="lane1", map="T0")]))
    store.set_spool(SpoolInfo(id=97, vendor="Sunlu"))
    snapshot = store.snapshot()
    assert set(snapshot) == {"service", "scale", "scan", "spool", "printers", "health", "activity", "settings"}
    assert snapshot["printers"][0]["lanes"][0]["lane"] == "lane1"
    assert snapshot["spool"]["vendor"] == "Sunlu"
    assert snapshot["scale"]["status"] == "absent"
    json.dumps(snapshot, allow_nan=False)


def test_store_emits_only_changes() -> None:
    store = make_store()
    events: list[tuple[str, object]] = []
    unsubscribe = store.subscribe(lambda topic, data: events.append((topic, data)))
    assert store.set_scale(ScaleState(present=True, status="stable", grams=984.0, source_unit="g", stable=True))
    assert not store.set_scale(ScaleState(present=True, status="stable", grams=984.0, source_unit="g", stable=True))
    store.set_printer(PrinterState(key="kilo", name="Kilo"))
    store.set_printer(PrinterState(key="yankee", name="Yankee"))
    assert [topic for topic, _ in events] == ["scale", "printer", "printer"]
    assert events[2][1]["key"] == "yankee"
    unsubscribe()
    store.set_spool(None)
    store.set_spool(SpoolInfo(id=1))
    assert len(events) == 3


def test_settings_defaults_and_validation(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "settings.json", ["kilo", "yankee"])
    assert settings.as_dict() == DEFAULTS
    assert settings.set("target", "Kilo") is True
    assert settings["target"] == "kilo"
    assert settings.set("target", "kilo") is False
    assert settings.set("sanity_threshold_g", 75.0) is True
    assert settings["sanity_threshold_g"] == 75
    assert settings.set("sanity_threshold_pct", 12.5) is True
    for key, value in [
        ("target", "prusa"), ("scan_mode", "later"), ("theme", "blue"), ("undo_depth", 0),
        ("undo_depth", 2.5), ("low_stock_g", True), ("low_stock_g", "100"), ("idle_off_s", -1),
        ("nope", 1),
    ]:
        with pytest.raises(SettingsError):
            settings.set(key, value)
    reloaded = Settings(tmp_path / "settings.json", ["kilo", "yankee"])
    reloaded.load()
    assert reloaded["target"] == "kilo"
    assert reloaded["sanity_threshold_pct"] == 12.5


def test_settings_target_subsets() -> None:
    settings = Settings(None, ["kilo", "yankee", "zulu"])
    assert settings.validate("target", "Yankee, kilo") == "kilo,yankee"
    assert settings.validate("target", "zulu") == "zulu"
    assert settings.validate("target", "kilo,yankee,zulu") == "both"
    assert settings.validate("target", " BOTH ") == "both"
    for bad in ("", ",", "kilo,kilo", "kilo,prusa", None, 3):
        with pytest.raises(SettingsError):
            settings.validate("target", bad)


def test_settings_ignore_invalid_stored_values(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"target": "gone", "theme": "light", "junk": 1}), encoding="utf-8")
    settings = Settings(path, ["kilo"])
    settings.load()
    assert settings["target"] == "both"
    assert settings["theme"] == "light"
    path.write_text("{not json", encoding="utf-8")
    broken = Settings(path, ["kilo"])
    broken.load()
    assert broken.as_dict() == DEFAULTS


def test_activity_log_persists_and_limits_undo(tmp_path: Path) -> None:
    path = tmp_path / "activity.jsonl"
    times = iter(f"2026-10-13T21:00:{n:02d}Z" for n in range(60))
    log = ActivityLog(path, undo_depth=2, clock=lambda: next(times))
    step = UndoStep(kind="spool_patch", spool_id=97, fields={"used_weight": 545.3})
    first = log.add("weigh", 97, [], True, "984 g saved", undo=[step])
    second = log.add("load", 97, ["Kilo"], True, "next spool set", undo=[UndoStep(kind="pending", printer="kilo")])
    log.add("lookup", 97, [], True, "found")
    third = log.add("weigh", 98, [], True, "500 g saved", undo=[step])
    dry = log.add("weigh", 99, [], True, "Dry run", dry_run=True, undo=[step])
    public = {entry["id"]: entry for entry in log.public()}
    assert public[third.id]["undoable"] and public[second.id]["undoable"]
    assert not public[first.id]["undoable"]
    assert not public[dry.id]["undoable"]
    assert [entry["id"] for entry in log.public()][0] == dry.id

    log.mark_undone(third)
    assert not log.is_undoable(third)
    assert log.is_undoable(second)

    reloaded = ActivityLog(path, undo_depth=2)
    reloaded.load()
    assert [entry.id for entry in reloaded.entries] == [entry.id for entry in log.entries]
    assert reloaded.get(third.id).undone is True
    assert reloaded.get(first.id).undo[0].fields == {"used_weight": 545.3}
    assert reloaded.add("weigh", 1, [], True, "x").id == "a-6"


def test_activity_log_skips_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "activity.jsonl"
    path.write_text('{"id":"a-3","at":"t","action":"weigh","ok":true,"message":"m"}\nnot json\n\n', encoding="utf-8")
    log = ActivityLog(path)
    log.load()
    assert [entry.id for entry in log.entries] == ["a-3"]
    assert log.add("load", 1, [], True, "m").id == "a-4"


def test_activity_log_round_trips_filament_undo(tmp_path: Path) -> None:
    path = tmp_path / "activity.jsonl"
    log = ActivityLog(path)
    steps = [UndoStep(kind="spool_patch", spool_id=97, fields={"spool_weight": 180.0}),
             UndoStep(kind="filament_patch", filament_id=11, fields={"spool_weight": None})]
    entry = log.add("empty_spool", 97, [], True, "empty", undo=steps)
    reloaded = ActivityLog(path)
    reloaded.load()
    assert reloaded.get(entry.id).undo == steps
    old = '{"id":"a-1","at":"t","action":"weigh","ok":true,"message":"m","undo":[{"kind":"spool_patch","spool_id":1}]}'
    path.write_text(old + "\n", encoding="utf-8")
    reloaded.load()
    assert reloaded.get("a-1").undo[0].filament_id is None
