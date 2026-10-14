"""Audible cues via audible-cue.py (weigh, success, error); fire-and-forget."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

log = logging.getLogger(__name__)

CUES = ("weigh", "success", "error")
Runner = Callable[[list[str]], Awaitable[int]]


async def run_subprocess(command: list[str]) -> int:
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode:
        log.warning("Audio cue failed: %s", stderr.decode(errors="replace").strip())
    return process.returncode or 0


class Audio:
    def __init__(
        self,
        script: Path,
        *,
        enabled: bool,
        backend: str = "auto",
        device: str = "",
        gpio_pin: str = "",
        runner: Runner = run_subprocess,
    ) -> None:
        self.script = script
        self.enabled = enabled and backend != "none"
        self.backend = backend
        self.device = device
        self.gpio_pin = gpio_pin
        self.runner = runner
        self._tasks: set[asyncio.Task[int]] = set()

    def command(self, cue: str) -> list[str]:
        command = [sys.executable, str(self.script), cue, "--backend", self.backend]
        if self.device:
            command += ["--device", self.device]
        if self.gpio_pin:
            command += ["--gpio-pin", self.gpio_pin]
        return command

    def play(self, cue: str) -> None:
        if cue not in CUES:
            raise ValueError(f"unknown cue {cue!r}")
        log.debug("Cue: %s", cue)
        if not self.enabled:
            return
        task = asyncio.create_task(self._run(cue))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, cue: str) -> int:
        try:
            return await self.runner(self.command(cue))
        except OSError as error:
            log.warning("The %r audible cue could not be played: %s", cue, error)
            return 1
