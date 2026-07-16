#!/usr/bin/env python3
"""Play scanner workflow cues through ALSA or an active GPIO buzzer."""

from __future__ import annotations

import argparse
import math
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

PATTERNS = {
    "weigh": [(700, 0.10), (0, 0.06), (950, 0.14)],
    "success": [(1050, 0.08), (0, 0.04), (1400, 0.16)],
    "error": [(220, 0.45)],
}


def play_gpio(pattern: list[tuple[int, float]], pin: int) -> None:
    pinctrl = shutil.which("pinctrl")
    if not pinctrl:
        raise RuntimeError("pinctrl is not installed")
    try:
        for frequency, duration in pattern:
            subprocess.run(
                [pinctrl, "set", str(pin), "op", "dh" if frequency else "dl"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(duration)
    finally:
        subprocess.run(
            [pinctrl, "set", str(pin), "op", "dl"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def create_wave(path: Path, pattern: list[tuple[int, float]]) -> None:
    sample_rate = 44100
    amplitude = 10000
    frames = bytearray()
    for frequency, duration in pattern:
        sample_count = int(sample_rate * duration)
        for sample in range(sample_count):
            value = (
                int(amplitude * math.sin(2 * math.pi * frequency * sample / sample_rate))
                if frequency
                else 0
            )
            frames.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, sample_rate, len(frames) // 2, "NONE", "not compressed"))
        output.writeframes(frames)


def play_alsa(pattern: list[tuple[int, float]], device: str | None) -> None:
    aplay = shutil.which("aplay")
    if not aplay:
        raise RuntimeError("aplay is not installed")
    with tempfile.NamedTemporaryFile(suffix=".wav") as audio:
        create_wave(Path(audio.name), pattern)
        command = [aplay, "-q"]
        if device:
            command.extend(("--device", device))
        command.append(audio.name)
        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cue", choices=PATTERNS)
    parser.add_argument("--backend", choices=("auto", "alsa", "gpio", "none"), default="auto")
    parser.add_argument("--device", help="ALSA output, such as plughw:CARD=Headphones,DEV=0")
    parser.add_argument("--gpio-pin", type=int)
    args = parser.parse_args()

    if args.backend == "none":
        return 0

    pattern = PATTERNS[args.cue]
    try:
        if args.backend == "gpio" or (args.backend == "auto" and args.gpio_pin is not None):
            if args.gpio_pin is None:
                raise RuntimeError("--gpio-pin is required for the GPIO backend")
            play_gpio(pattern, args.gpio_pin)
        else:
            play_alsa(pattern, args.device)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Audio cue error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
