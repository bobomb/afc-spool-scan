"""UI-changeable settings, persisted as JSON in the state directory."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "scan_mode": "immediate",
    "theme": "dark",
    "sanity_threshold_g": 50,
    "sanity_threshold_pct": 10,
    "low_stock_g": 100,
    "undo_depth": 20,
    "idle_dim_s": 120,
    "idle_off_s": 300,
}
# Settings that existed once; dropped quietly from older settings files.
RETIRED = {"target"}
SCAN_MODES = ("immediate", "countdown", "fill")
THEMES = ("dark", "light")
NUMERIC: dict[str, tuple[float, float, bool]] = {
    "sanity_threshold_g": (0, 1000, False),
    "sanity_threshold_pct": (0, 100, False),
    "low_stock_g": (0, 5000, False),
    "undo_depth": (1, 100, True),
    "idle_dim_s": (0, 3600, True),
    "idle_off_s": (0, 7200, True),
}


class SettingsError(ValueError):
    pass


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Settings:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.values: dict[str, Any] = dict(DEFAULTS)

    def validate(self, key: str, value: Any) -> Any:
        if key not in DEFAULTS:
            raise SettingsError(f"unknown setting {key!r}")
        if key == "scan_mode":
            if value not in SCAN_MODES:
                raise SettingsError(f"scan_mode must be one of {', '.join(SCAN_MODES)}")
            return value
        if key == "theme":
            if value not in THEMES:
                raise SettingsError(f"theme must be one of {', '.join(THEMES)}")
            return value
        low, high, integer = NUMERIC[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SettingsError(f"{key} must be a number")
        number = float(value)
        if number != number or not low <= number <= high:
            raise SettingsError(f"{key} must be between {low:g} and {high:g}")
        if integer:
            if not number.is_integer():
                raise SettingsError(f"{key} must be a whole number")
            return int(number)
        return int(number) if number.is_integer() else number

    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log.warning("Ignoring unreadable settings file %s: %s", self.path, error)
            return
        if not isinstance(stored, dict):
            return
        for key, value in stored.items():
            if key in RETIRED:
                continue
            try:
                self.values[key] = self.validate(key, value)
            except SettingsError as error:
                log.warning("Ignoring stored setting %s: %s", key, error)

    def save(self) -> None:
        if self.path is not None:
            atomic_write_text(self.path, json.dumps(self.values, indent=2, sort_keys=True) + "\n")

    def set(self, key: str, value: Any) -> bool:
        normalized = self.validate(key, value)
        if self.values.get(key) == normalized:
            return False
        self.values[key] = normalized
        self.save()
        return True

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)
