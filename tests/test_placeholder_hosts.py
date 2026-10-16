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
PLACEHOLDER_HOSTS = {"spoolpi", "kilo", "yankee"}


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
    assert not problems, problems
