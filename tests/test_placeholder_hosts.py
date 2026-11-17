"""Guard: tracked files use placeholder hosts only (real ones live in git-ignored config.env/deploy.env)."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PRIVATE_IP = re.compile(r"\b(?:192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b")
LOCAL_HOST = re.compile(r"\b([\w-]+)\.local\b")
USER_PATH = re.compile(r"\b[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+|/home/(?!pi\b)[\w.-]+")
PLACEHOLDER_HOSTS = {"spoolpi", "kilo", "yankee"}
# Bambuddy API keys are "bb_" plus a long token; Bambu serials and access codes never belong in the repo.
API_KEY = re.compile(r"\bbb_[A-Za-z0-9_-]{24,}")
DEVICE_SECRET = re.compile(r"\"(serial_number|access_code|ip_address)\"\s*:\s*\"([^\"]+)\"")
ACCESS_CODE = re.compile(r"BAMBU_ACCESS_CODE\s*=\s*[\"']?[A-Za-z0-9]{8}\b")


def tracked_text_files() -> Iterator[tuple[str, str]]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    for name in listed.decode("utf-8").split("\0"):
        path = REPO / name
        if name and path.is_file():
            data = path.read_bytes()
            if b"\0" not in data[:8192]:
                yield name, data.decode("utf-8", "replace")


@pytest.mark.skipif(shutil.which("git") is None or not (REPO / ".git").exists(), reason="needs a git checkout")
def test_tracked_files_use_placeholder_hosts() -> None:
    problems: list[str] = []
    for name, text in tracked_text_files():
        problems += [f"{name}: {ip}" for ip in PRIVATE_IP.findall(text)]
        problems += [f"{name}: {host}.local" for host in LOCAL_HOST.findall(text)
                     if host.lower() not in PLACEHOLDER_HOSTS]
        problems += [f"{name}: {path}" for path in USER_PATH.findall(text)]
        problems += [f"{name}: Bambuddy API key" for _ in API_KEY.findall(text)]
        problems += [f"{name}: {key}" for key, _ in DEVICE_SECRET.findall(text)]
        problems += [f"{name}: Bambu access code" for _ in ACCESS_CODE.findall(text)]
    assert not problems, problems


def test_capture_scrubber_removes_device_secrets() -> None:
    from station.sim.bambuddy import scrub_capture

    raw = dict(name="My H3C", serial_number="01P00A000000000", ip_address="192.0.2.50",
               current_print="secret_project.3mf",
               ams=[dict(id=32, serial_number="X", tray=[dict(id=0, tray_uuid="AB" * 16, tag_uid=None)])])
    scrubbed = scrub_capture(raw, "Heron")
    text = repr(scrubbed)
    assert "serial_number" not in text and "ip_address" not in text and "secret_project" not in text
    assert scrubbed["name"] == "Heron" and scrubbed["current_print"] == "capture_plate_1"
    tag = scrubbed["ams"][0]["tray"][0]["tray_uuid"]
    assert len(tag) == 32 and tag != "AB" * 16 and tag == scrub_capture(raw, "Heron")["ams"][0]["tray"][0]["tray_uuid"]
