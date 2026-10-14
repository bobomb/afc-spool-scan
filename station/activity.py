"""Activity log with undo records, persisted as JSONL in the state directory."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .settings import atomic_write_text

log = logging.getLogger(__name__)

MAX_ENTRIES = 200
PUBLISHED_ENTRIES = 50


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class UndoStep:
    """One inverse operation; executed newest-first when undoing.

    kind: "spool_patch" (spool_id, fields), "pending" (printer, spool_id = previous
    pending or None), "lane" (printer, lane, spool_id = previous lane spool or None).
    """

    kind: str
    spool_id: int | None = None
    printer: str | None = None
    lane: str | None = None
    fields: dict[str, Any] | None = None


@dataclass
class ActivityEntry:
    id: str
    at: str
    action: str
    spool_id: int | None
    printers: list[str]
    ok: bool
    message: str
    code: str | None = None
    dry_run: bool = False
    undone: bool = False
    undo: list[UndoStep] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActivityEntry:
        steps = [UndoStep(**step) for step in data.get("undo") or []]
        return cls(
            id=str(data["id"]),
            at=str(data["at"]),
            action=str(data["action"]),
            spool_id=data.get("spool_id"),
            printers=list(data.get("printers") or []),
            ok=bool(data.get("ok")),
            message=str(data.get("message", "")),
            code=data.get("code"),
            dry_run=bool(data.get("dry_run", False)),
            undone=bool(data.get("undone", False)),
            undo=steps,
        )


class ActivityLog:
    def __init__(
        self,
        path: Path | None,
        undo_depth: int = 20,
        clock: Callable[[], str] = utc_now_iso,
    ) -> None:
        self.path = path
        self.undo_depth = undo_depth
        self.clock = clock
        self.entries: list[ActivityEntry] = []
        self._next = 1

    def load(self) -> None:
        if self.path is None or not self.path.exists():
            return
        loaded: list[ActivityEntry] = []
        for number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                loaded.append(ActivityEntry.from_dict(json.loads(line)))
            except (ValueError, KeyError, TypeError) as error:
                log.warning("Skipping activity line %d: %s", number, error)
        self.entries = loaded[-MAX_ENTRIES:][::-1]
        for entry in self.entries:
            if entry.id.startswith("a-") and entry.id[2:].isdigit():
                self._next = max(self._next, int(entry.id[2:]) + 1)

    def save(self) -> None:
        if self.path is None:
            return
        lines = [json.dumps(asdict(entry), separators=(",", ":")) for entry in reversed(self.entries)]
        atomic_write_text(self.path, "".join(line + "\n" for line in lines))

    def add(
        self,
        action: str,
        spool_id: int | None,
        printers: list[str],
        ok: bool,
        message: str,
        code: str | None = None,
        dry_run: bool = False,
        undo: list[UndoStep] | None = None,
    ) -> ActivityEntry:
        entry = ActivityEntry(
            id=f"a-{self._next}",
            at=self.clock(),
            action=action,
            spool_id=spool_id,
            printers=printers,
            ok=ok,
            message=message,
            code=code,
            dry_run=dry_run,
            undo=list(undo or []),
        )
        self._next += 1
        self.entries.insert(0, entry)
        del self.entries[MAX_ENTRIES:]
        self.save()
        return entry

    def get(self, activity_id: str) -> ActivityEntry | None:
        return next((entry for entry in self.entries if entry.id == activity_id), None)

    def _undoable_ids(self) -> set[str]:
        candidates = [entry for entry in self.entries if entry.undo and not entry.dry_run]
        return {entry.id for entry in candidates[: self.undo_depth] if not entry.undone}

    def is_undoable(self, entry: ActivityEntry) -> bool:
        return entry.id in self._undoable_ids()

    def mark_undone(self, entry: ActivityEntry) -> None:
        entry.undone = True
        self.save()

    def public(self) -> list[dict[str, Any]]:
        undoable = self._undoable_ids()
        return [
            {
                "id": entry.id,
                "at": entry.at,
                "action": entry.action,
                "spool_id": entry.spool_id,
                "printers": entry.printers,
                "ok": entry.ok,
                "message": entry.message,
                "code": entry.code,
                "dry_run": entry.dry_run,
                "undone": entry.undone,
                "undoable": entry.id in undoable,
            }
            for entry in self.entries[:PUBLISHED_ENTRIES]
        ]
