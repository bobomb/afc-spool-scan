"""Protocol actions (dev plan §5.3) with rules (§6.4), activity and undo."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from .activity import ActivityLog, UndoStep
from .config import Config
from .moonraker import MoonrakerClient, PrinterCommandError, PrinterOffline
from .printers import PrinterManager, UnknownPrinter
from .rules import (
    EMPTY_MINIMUM_G,
    SKIPPABLE_SCALE_CODES,
    derive_scale_state,
    empty_spool_check,
    fmt_g,
    sanity_check,
    scale_problem,
)
from .scale.source import ScaleReading, ScaleSource
from .settings import Settings, SettingsError
from .spoolman import SpoolmanClient, SpoolmanError, SpoolNotFound, spool_info_from_api
from .state import Prompt, SpoolInfo, Store

log = logging.getLogger(__name__)

NO_REPLY = "no reply in time; the command may still apply"

UNDO_LABELS = {
    "weigh_load": "weigh + load",
    "assign_lane": "lane assignment",
    "empty_spool": "empty spool",
    "clear_pending": "clear pending",
}


class Cues(Protocol):
    def play(self, cue: str) -> None: ...


class ActionError(Exception):
    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass
class Outcome:
    ok: bool
    message: str
    code: str | None = None
    activity_id: str | None = None
    dry_run: bool = False
    data: dict[str, Any] | None = None

    def to_result(self) -> dict[str, Any]:
        result: dict[str, Any] = {"ok": self.ok, "message": self.message}
        if self.code:
            result["code"] = self.code
        if self.activity_id:
            result["activity_id"] = self.activity_id
        if self.dry_run:
            result["dry_run"] = True
        if self.data is not None:
            result["data"] = self.data
        return result


@dataclass
class StepResult:
    message: str
    ok: bool = True
    code: str | None = None
    dry_run: bool = False
    printers: list[str] = field(default_factory=list)
    undo: list[UndoStep] = field(default_factory=list)


def _spool_id(args: dict[str, Any], key: str = "spool_id") -> int:
    value = args.get(key)
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value < 10**9:
        raise ActionError("invalid_args", "A spool ID is required")
    return value


def _bool(args: dict[str, Any], key: str) -> bool:
    value = args.get(key, False)
    if not isinstance(value, bool):
        raise ActionError("invalid_args", f"{key} must be true or false")
    return value


def _join(names: list[str]) -> str:
    return ", ".join(names)


class Actions:
    def __init__(
        self,
        *,
        config: Config,
        store: Store,
        settings: Settings,
        activity: ActivityLog,
        spoolman: SpoolmanClient,
        printers: PrinterManager,
        scale: ScaleSource,
        cues: Cues,
        sim: Any | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.settings = settings
        self.activity = activity
        self.spoolman = spoolman
        self.printers = printers
        self.scale = scale
        self.cues = cues
        self.sim = sim
        self.scan_flow: Any | None = None
        self._lock = asyncio.Lock()
        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[Outcome]]] = {
            "lookup": self.lookup,
            "weigh": self.weigh,
            "weigh_load": self.weigh_load,
            "load": self.load,
            "clear_pending": self.clear_pending,
            "assign_lane": self.assign_lane,
            "empty_spool": self.empty_spool,
            "undo": self.undo,
            "set_setting": self.set_setting,
            "cancel_countdown": self.cancel_countdown,
            "dismiss_prompt": self.dismiss_prompt,
        }

    async def handle(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(action)
        if handler is None and action.startswith("sim.") and self.sim is not None:
            handler = lambda a: self.sim.handle(action, a)  # noqa: E731
        if handler is None:
            return Outcome(False, f"Unknown action {action!r}", code="invalid_args").to_result()
        try:
            outcome = await handler(args)
        except ActionError as error:
            outcome = Outcome(False, error.message, code=error.code, data=error.data)
        return outcome.to_result()

    # ---- state helpers -------------------------------------------------

    def refresh_scale(self) -> None:
        self.store.set_scale(
            derive_scale_state(
                self.scale.current, self.store.spool,
                self.settings["sanity_threshold_g"], self.settings["sanity_threshold_pct"],
            )
        )

    def _publish_spool(self, data: dict[str, Any]) -> SpoolInfo:
        info = spool_info_from_api(data, self.settings["low_stock_g"])
        self.store.set_spool(info)
        self.refresh_scale()
        return info

    def _publish_activity(self) -> None:
        self.store.set_activity(self.activity.public())

    def _record(self, action: str, spool_id: int | None, step: StepResult) -> str:
        entry = self.activity.add(
            action, spool_id, step.printers, step.ok, step.message, code=step.code,
            dry_run=step.dry_run, undo=step.undo,
        )
        self._publish_activity()
        return entry.id

    async def _fetch_spool(self, spool_id: int, publish: bool = True) -> dict[str, Any]:
        try:
            data = await self.spoolman.get_spool(spool_id)
        except SpoolNotFound as error:
            if publish:
                self.store.set_spool(SpoolInfo(id=spool_id, found=False, message=str(error)))
                self.refresh_scale()
            raise ActionError("not_found", str(error)) from error
        except SpoolmanError as error:
            raise ActionError("spoolman_error", str(error)) from error
        if publish:
            self._publish_spool(data)
        return data

    async def _stable_weight(self, minimum_g: float) -> float:
        reading: ScaleReading = self.scale.current
        if reading.present and reading.status == "motion":
            reading = await self.scale.wait_for(
                lambda r: r.status != "motion", self.config.scale_read_timeout_s
            )
        problem = scale_problem(reading, minimum_g)
        if problem:
            raise ActionError(*problem)
        assert reading.grams is not None
        return reading.grams

    def _client(self, name: Any) -> MoonrakerClient:
        try:
            return self.printers.get(name)
        except UnknownPrinter as error:
            raise ActionError("invalid_args", str(error)) from error

    def _targets(self, args: dict[str, Any]) -> list[MoonrakerClient]:
        target = args.get("target") or self.settings["target"]
        try:
            return self.printers.resolve(target)
        except UnknownPrinter as error:
            raise ActionError("invalid_args", str(error)) from error

    def _fail(self, error: ActionError) -> None:
        if error.code != "needs_confirm":
            self.cues.play("error")

    # ---- steps -----------------------------------------------------------

    async def _weigh_step(self, spool_id: int, confirm: bool) -> tuple[StepResult, float]:
        grams = await self._stable_weight(self.config.scale_minimum_g)
        data = await self._fetch_spool(spool_id)
        info = spool_info_from_api(data, self.settings["low_stock_g"])
        check = sanity_check(grams, info, self.settings["sanity_threshold_g"], self.settings["sanity_threshold_pct"])
        if check.status == "warn" and not confirm:
            raise ActionError("needs_confirm", check.message(spool_id), {"spool_id": spool_id, **check.as_dict()})
        try:
            result = await self.spoolman.measure(spool_id, grams)
        except SpoolmanError as error:
            raise ActionError("spoolman_error", f"Weight not saved: {error}") from error
        if result.dry_run:
            return StepResult(f"Dry run: would save {fmt_g(grams)} g", dry_run=True), grams
        previous: dict[str, Any] = {"used_weight": data.get("used_weight")}
        if result.spool is not None:
            if result.spool.get("initial_weight") != data.get("initial_weight"):
                previous["initial_weight"] = data.get("initial_weight")
            self._publish_spool(result.spool)
        suffix = " (tare unknown)" if check.status == "tare_unknown" else ""
        return StepResult(
            f"{fmt_g(grams)} g saved{suffix}",
            undo=[UndoStep(kind="spool_patch", spool_id=spool_id, fields=previous)],
        ), grams

    async def _load_step(self, spool_id: int, clients: list[MoonrakerClient]) -> StepResult:
        async def one(client: MoonrakerClient) -> tuple[MoonrakerClient, str | None, bool, int | None]:
            previous = client.state.pending_spool
            try:
                result = await client.set_next_spool(spool_id)
            except PrinterOffline:
                return client, "offline", False, previous
            except asyncio.TimeoutError:
                return client, NO_REPLY, False, previous
            except PrinterCommandError as error:
                return client, str(error) or "command failed", False, previous
            return client, None, result.dry_run, previous

        outcomes = await asyncio.gather(*(one(client) for client in clients))
        done = [c.printer.name for c, error, _, _ in outcomes if error is None]
        failed = [(c.printer.name, error) for c, error, _, _ in outcomes if error is not None]
        dry_run = any(dry for _, error, dry, _ in outcomes if error is None)
        undo = [
            UndoStep(kind="pending", printer=c.key, spool_id=previous)
            for c, error, dry, previous in outcomes
            if (error is None and not dry) or error == NO_REPLY
        ]
        parts = []
        if done:
            parts.append(("Dry run: would set next spool on " if dry_run else "next spool set on ") + _join(done))
        for name, error in failed:
            parts.append(f"{name}: {error}")
        code = None
        if failed:
            code = "printer_offline" if any(error == "offline" for _, error in failed) else "printer_error"
        return StepResult(
            "; ".join(parts), ok=not failed, code=code, dry_run=dry_run,
            printers=[c.printer.name for c in clients], undo=undo,
        )

    async def _ensure_known_spool(self, spool_id: int) -> None:
        """Reject unknown spools; proceed if Spoolman is unreachable (parity with scanning)."""
        try:
            await self._fetch_spool(spool_id)
        except ActionError as error:
            if error.code != "spoolman_error":
                raise
            log.warning("Spool %d not verified: %s", spool_id, error.message)

    # ---- actions ---------------------------------------------------------

    async def lookup(self, args: dict[str, Any]) -> Outcome:
        spool_id = _spool_id(args)
        data = await self._fetch_spool(spool_id)
        filament = data.get("filament") or {}
        vendor = (filament.get("vendor") or {}).get("name")
        name = " ".join(part for part in (vendor, filament.get("name")) if part)
        return Outcome(True, f"Spool {spool_id}: {name or 'found'}")

    async def weigh(self, args: dict[str, Any]) -> Outcome:
        spool_id = _spool_id(args)
        confirm = _bool(args, "confirm")
        async with self._lock:
            try:
                step, _ = await self._weigh_step(spool_id, confirm)
            except ActionError as error:
                self._fail(error)
                if error.code == "spoolman_error":
                    self._record("weigh", spool_id, StepResult(error.message, ok=False, code=error.code))
                raise
            self._clear_prompt(spool_id)
            if not step.dry_run:
                self.cues.play("weigh")
            self.cues.play("success")
            activity_id = self._record("weigh", spool_id, step)
            return Outcome(True, f"Spool {spool_id}: {step.message}", activity_id=activity_id, dry_run=step.dry_run)

    async def load(self, args: dict[str, Any]) -> Outcome:
        spool_id = _spool_id(args)
        clients = self._targets(args)
        async with self._lock:
            try:
                await self._ensure_known_spool(spool_id)
            except ActionError as error:
                self._fail(error)
                raise
            step = await self._load_step(spool_id, clients)
            self.cues.play("success" if step.ok else "error")
            activity_id = self._record("load", spool_id, step)
            return Outcome(step.ok, f"Spool {spool_id}: {step.message}", code=step.code,
                           activity_id=activity_id, dry_run=step.dry_run)

    async def weigh_load(self, args: dict[str, Any], *, source: str = "ui") -> Outcome:
        """Weigh then load. From a scan, a missing weight is skipped like the bash scanner."""
        spool_id = _spool_id(args)
        confirm = _bool(args, "confirm")
        clients = self._targets(args)
        from_scan = source == "scan"
        async with self._lock:
            weigh: StepResult | None = None
            skipped: ActionError | None = None
            try:
                weigh, _ = await self._weigh_step(spool_id, confirm)
            except ActionError as error:
                if not from_scan or error.code == "not_found":
                    self._fail(error)
                    if error.code == "spoolman_error":
                        self._record("weigh_load", spool_id, StepResult(error.message, ok=False, code=error.code))
                    raise
                skipped = error
                if error.code == "needs_confirm":
                    self._set_prompt(spool_id, error)
            if weigh is None:
                try:
                    await self._ensure_known_spool(spool_id)
                except ActionError as error:
                    self._fail(error)
                    raise
            load = await self._load_step(spool_id, clients)
            parts: list[str] = []
            if weigh is not None:
                parts.append(weigh.message)
            elif skipped is not None:
                reason = "needs confirmation" if skipped.code == "needs_confirm" else skipped.message.lower()
                parts.append(f"weight not saved ({reason})")
            parts.append(load.message)
            weigh_failed = skipped is not None and skipped.code not in SKIPPABLE_SCALE_CODES | {"needs_confirm"}
            ok = load.ok and not weigh_failed
            step = StepResult(
                "; ".join(parts),
                ok=ok,
                code=load.code or (skipped.code if weigh_failed and skipped else None),
                dry_run=load.dry_run or bool(weigh and weigh.dry_run),
                printers=load.printers,
                undo=(weigh.undo if weigh else []) + load.undo,
            )
            if weigh is not None:
                self._clear_prompt(spool_id)
                if not weigh.dry_run:
                    self.cues.play("weigh")
            self.cues.play("success" if ok else "error")
            activity_id = self._record("scan" if from_scan else "weigh_load", spool_id, step)
            return Outcome(ok, f"Spool {spool_id}: {step.message}", code=step.code,
                           activity_id=activity_id, dry_run=step.dry_run)

    async def clear_pending(self, args: dict[str, Any]) -> Outcome:
        client = self._client(args.get("printer"))
        async with self._lock:
            previous = client.state.pending_spool
            try:
                result = await client.set_next_spool(None)
            except PrinterOffline as error:
                self.cues.play("error")
                raise ActionError("printer_offline", str(error)) from error
            except PrinterCommandError as error:
                self.cues.play("error")
                raise ActionError("printer_error", str(error)) from error
            except asyncio.TimeoutError as error:
                self.cues.play("error")
                undo = [] if previous is None else [UndoStep(kind="pending", printer=client.key, spool_id=previous)]
                step = StepResult(f"Clear on {client.printer.name}: {NO_REPLY}", ok=False, code="printer_error",
                                  printers=[client.printer.name], undo=undo)
                activity_id = self._record("clear_pending", previous, step)
                return Outcome(False, step.message, code=step.code, activity_id=activity_id)
            undo = [] if result.dry_run or previous is None else [
                UndoStep(kind="pending", printer=client.key, spool_id=previous)
            ]
            prefix = "Dry run: would clear" if result.dry_run else "Cleared"
            step = StepResult(f"{prefix} next spool on {client.printer.name}", dry_run=result.dry_run,
                              printers=[client.printer.name], undo=undo)
            activity_id = self._record("clear_pending", previous, step)
            return Outcome(True, step.message, activity_id=activity_id, dry_run=result.dry_run)

    async def assign_lane(self, args: dict[str, Any]) -> Outcome:
        spool_id = _spool_id(args)
        client = self._client(args.get("printer"))
        lane_name = args.get("lane")
        lane = client.lane(lane_name) if isinstance(lane_name, str) else None
        if lane is None:
            raise ActionError("invalid_args", f"{client.printer.name} has no lane {lane_name!r}")
        if not client.online:
            raise ActionError("printer_offline", f"{client.printer.name} is offline")
        other = next((item for item in client.state.lanes if item.spool_id == spool_id and item.lane != lane.lane), None)
        if other is not None:
            raise ActionError("invalid_args", f"Spool {spool_id} is already in {other.lane} on {client.printer.name}")
        async with self._lock:
            try:
                await self._ensure_known_spool(spool_id)
            except ActionError as error:
                self._fail(error)
                raise
            previous = lane.spool_id
            try:
                result = await client.set_lane_spool(lane.lane, spool_id)
            except PrinterOffline as error:
                self.cues.play("error")
                raise ActionError("printer_offline", str(error)) from error
            except PrinterCommandError as error:
                self.cues.play("error")
                step = StepResult(f"Assign failed: {error}", ok=False, code="printer_error",
                                  printers=[client.printer.name])
                self._record("assign_lane", spool_id, step)
                raise ActionError("printer_error", step.message) from error
            except asyncio.TimeoutError:
                self.cues.play("error")
                step = StepResult(
                    f"Assign spool {spool_id} to {client.printer.name} {lane.lane}: {NO_REPLY}", ok=False,
                    code="printer_error", printers=[client.printer.name],
                    undo=[UndoStep(kind="lane", printer=client.key, lane=lane.lane, spool_id=previous)],
                )
                activity_id = self._record("assign_lane", spool_id, step)
                return Outcome(False, step.message, code=step.code, activity_id=activity_id)
            prefix = "Dry run: would assign" if result.dry_run else "Assigned"
            undo = [] if result.dry_run else [
                UndoStep(kind="lane", printer=client.key, lane=lane.lane, spool_id=previous)
            ]
            step = StepResult(f"{prefix} spool {spool_id} to {client.printer.name} {lane.lane}",
                              dry_run=result.dry_run, printers=[client.printer.name], undo=undo)
            self.cues.play("success")
            activity_id = self._record("assign_lane", spool_id, step)
            return Outcome(True, step.message, activity_id=activity_id, dry_run=result.dry_run)

    async def empty_spool(self, args: dict[str, Any]) -> Outcome:
        spool_id = _spool_id(args)
        confirm = _bool(args, "confirm")
        async with self._lock:
            try:
                grams = await self._stable_weight(EMPTY_MINIMUM_G)
                data = await self._fetch_spool(spool_id)
                info = spool_info_from_api(data, self.settings["low_stock_g"])
                warning = empty_spool_check(grams, info, self.settings["sanity_threshold_g"],
                                            self.settings["sanity_threshold_pct"])
                if warning and not confirm:
                    raise ActionError("needs_confirm", warning, {
                        "spool_id": spool_id, "gross_g": grams, "tare_g": info.spool_weight_g,
                    })
                try:
                    result = await self.spoolman.patch(
                        spool_id, {"spool_weight": grams, "remaining_weight": 0, "archived": True}
                    )
                except SpoolmanError as error:
                    raise ActionError("spoolman_error", f"Empty spool not recorded: {error}") from error
            except ActionError as error:
                self._fail(error)
                if error.code == "spoolman_error":
                    self._record("empty_spool", spool_id, StepResult(error.message, ok=False, code=error.code))
                raise
            if result.dry_run:
                step = StepResult(f"Dry run: would record {fmt_g(grams)} g tare and archive", dry_run=True)
            else:
                if result.spool is not None:
                    self._publish_spool(result.spool)
                previous = {key: data.get(key) for key in ("spool_weight", "used_weight", "archived")}
                step = StepResult(f"empty spool {fmt_g(grams)} g recorded; archived",
                                  undo=[UndoStep(kind="spool_patch", spool_id=spool_id, fields=previous)])
            self.cues.play("success")
            activity_id = self._record("empty_spool", spool_id, step)
            return Outcome(True, f"Spool {spool_id}: {step.message}", activity_id=activity_id, dry_run=step.dry_run)

    async def _apply_undo(self, step: UndoStep) -> bool:
        """Apply one inverse step; returns True when it was only a dry run."""
        if step.kind == "spool_patch":
            assert step.spool_id is not None
            result = await self.spoolman.patch(step.spool_id, dict(step.fields or {}))
            if result.spool is not None and self.store.spool is not None and self.store.spool.id == step.spool_id:
                self._publish_spool(result.spool)
            return result.dry_run
        if step.kind == "pending":
            return (await self.printers.get(step.printer or "").set_next_spool(step.spool_id)).dry_run
        if step.kind == "lane":
            return (await self.printers.get(step.printer or "").set_lane_spool(step.lane or "", step.spool_id)).dry_run
        raise ActionError("invalid_args", f"unknown undo step {step.kind!r}")

    async def undo(self, args: dict[str, Any]) -> Outcome:
        activity_id = args.get("activity_id")
        entry = self.activity.get(activity_id) if isinstance(activity_id, str) else None
        if entry is None:
            raise ActionError("invalid_args", f"Unknown activity {activity_id!r}")
        if not self.activity.is_undoable(entry):
            raise ActionError("invalid_args", "That action can no longer be undone")
        async with self._lock:
            failures: list[str] = []
            dry_run = False
            for step in reversed(entry.undo):
                try:
                    dry_run = await self._apply_undo(step) or dry_run
                except asyncio.TimeoutError:
                    failures.append(NO_REPLY)
                except (SpoolmanError, PrinterOffline, PrinterCommandError, UnknownPrinter, ActionError) as error:
                    failures.append(str(error) or type(error).__name__)
            label = UNDO_LABELS.get(entry.action, entry.action.replace("_", " "))
            if dry_run and not failures:
                step = StepResult(f"Dry run: would undo {label}", dry_run=True, printers=entry.printers)
                new_id = self._record("undo", entry.spool_id, step)
                return Outcome(True, step.message, activity_id=new_id, dry_run=True)
            if failures:
                self.cues.play("error")
                step = StepResult(f"Undo {label} incomplete: {'; '.join(failures)}", ok=False, code="undo_failed",
                                  printers=entry.printers)
            else:
                self.activity.mark_undone(entry)
                self.cues.play("success")
                step = StepResult(f"Undid {label}" + (f" of spool {entry.spool_id}" if entry.spool_id else ""),
                                  printers=entry.printers)
            new_id = self._record("undo", entry.spool_id, step)
            return Outcome(not failures, step.message, code=step.code, activity_id=new_id)

    async def set_setting(self, args: dict[str, Any]) -> Outcome:
        key = args.get("key")
        if not isinstance(key, str):
            raise ActionError("invalid_args", "key is required")
        try:
            changed = self.settings.set(key, args.get("value"))
        except SettingsError as error:
            raise ActionError("invalid_args", str(error)) from error
        if changed:
            self.store.set_settings(self.settings.as_dict())
            if key == "low_stock_g":
                if self.store.spool is not None and self.store.spool.found:
                    remaining = self.store.spool.remaining_g
                    self.store.set_spool(replace(
                        self.store.spool, low_stock=remaining is not None and remaining < self.settings["low_stock_g"]
                    ))
                self.printers.refresh()
            elif key in ("sanity_threshold_g", "sanity_threshold_pct"):
                self.refresh_scale()
            elif key == "undo_depth":
                self.activity.undo_depth = self.settings["undo_depth"]
                self._publish_activity()
        return Outcome(True, f"{key} set to {self.settings[key]}")

    def _set_prompt(self, spool_id: int, error: ActionError) -> None:
        data = error.data or {}
        prompt = Prompt(
            kind="confirm_weigh", spool_id=spool_id, message=error.message,
            gross_g=data.get("gross_g"), tare_g=data.get("tare_g"), net_g=data.get("net_g"),
            expected_g=data.get("expected_g"), delta_g=data.get("delta_g"),
        )
        self.store.set_scan(replace(self.store.scan, prompt=prompt))

    def _clear_prompt(self, spool_id: int | None = None) -> None:
        prompt = self.store.scan.prompt
        if prompt is not None and (spool_id is None or prompt.spool_id == spool_id):
            self.store.set_scan(replace(self.store.scan, prompt=None))

    async def cancel_countdown(self, args: dict[str, Any]) -> Outcome:
        if self.scan_flow is not None and self.scan_flow.cancel():
            return Outcome(True, "Countdown cancelled")
        return Outcome(True, "No countdown running")

    async def dismiss_prompt(self, args: dict[str, Any]) -> Outcome:
        self._clear_prompt()
        return Outcome(True, "Dismissed")
