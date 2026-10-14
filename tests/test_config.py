from __future__ import annotations

from pathlib import Path

import pytest

from station.config import (
    Config,
    ConfigError,
    PrinterConfig,
    default_state_dir,
    load_config,
    parse_env_text,
    parse_printers,
)


def test_parse_env_text_handles_bash_style_lines() -> None:
    text = """
# comment
EVENT_DEV="/dev/input/by-id/scanner"
export SPOOLMAN_URL='http://spoolman:7912/api/v1'
MOONRAKER_PORT=7125 # trailing comment
EMPTY=""
QUOTED="say \\"hi\\""
not a line
1BAD=x
"""
    assert parse_env_text(text) == {
        "EVENT_DEV": "/dev/input/by-id/scanner",
        "SPOOLMAN_URL": "http://spoolman:7912/api/v1",
        "MOONRAKER_PORT": "7125",
        "EMPTY": "",
        "QUOTED": 'say "hi"',
    }


def test_parse_printers() -> None:
    printers = parse_printers("Kilo=192.0.2.11:7125, Yankee=192.0.2.12")
    assert printers == (
        PrinterConfig("Kilo", "192.0.2.11", 7125),
        PrinterConfig("Yankee", "192.0.2.12", 7125),
    )
    assert printers[0].key == "kilo"
    assert printers[0].websocket_url == "ws://192.0.2.11:7125/websocket"


def test_parse_printers_from_moonraker_hosts_uses_host_as_name() -> None:
    printers = parse_printers("kilo.local,yankee.local", default_port=7126)
    assert [p.name for p in printers] == ["kilo.local", "yankee.local"]
    assert {p.port for p in printers} == {7126}


@pytest.mark.parametrize("spec", ["", "A=:7125", "A=host:x", "A=host:70000", "A=h1,a=h2", "Both=h"])
def test_parse_printers_rejects_bad_entries(spec: str) -> None:
    with pytest.raises(ConfigError):
        parse_printers(spec)


def test_windows_defaults_are_safe(tmp_path: Path) -> None:
    config = load_config([], environ={"LOCALAPPDATA": str(tmp_path)}, platform="win32", repo_dir=tmp_path)
    assert (config.hardware, config.printers_mode, config.spoolman_mode, config.writes) == (
        "sim", "sim", "sim", False,
    )
    assert config.state_dir == tmp_path / "spool-station"
    assert [p.name for p in config.printers] == ["Kilo", "Yankee"]
    assert config.ipc_host == "127.0.0.1"
    assert config.ipc_port == 7913


def test_linux_defaults_use_real_services(tmp_path: Path) -> None:
    config = load_config([], environ={"XDG_STATE_HOME": str(tmp_path)}, platform="linux", repo_dir=tmp_path)
    assert (config.hardware, config.printers_mode, config.spoolman_mode, config.writes) == (
        "real", "live", "live", True,
    )
    assert config.state_dir == tmp_path / "spool-station"


def test_precedence_env_file_then_environment_then_cli(tmp_path: Path) -> None:
    (tmp_path / "config.env").write_text(
        'STATION_WRITES="on"\nSTATION_IPC_PORT="8000"\nPRINTERS="A=10.0.0.1:1"\n'
        'SCALE_MINIMUM_WEIGHT_GRAMS="60"\nSCALE_PRODUCT_IDS="8003, 8004"\n',
        encoding="utf-8",
    )
    config = load_config(
        ["--ipc-port", "9000"],
        environ={"STATION_IPC_PORT": "8500", "STATION_WRITES": "off"},
        platform="win32",
        repo_dir=tmp_path,
    )
    assert config.writes is False
    assert config.ipc_port == 9000
    assert config.printers == (PrinterConfig("A", "10.0.0.1", 1),)
    assert config.scale_minimum_g == 60
    assert config.scale_product_ids == frozenset({"8003", "8004"})


def test_moonraker_hosts_fallback(tmp_path: Path) -> None:
    config = load_config(
        [], environ={"MOONRAKER_HOSTS": "192.0.2.11,192.0.2.12", "MOONRAKER_PORT": "7125"},
        platform="win32", repo_dir=tmp_path,
    )
    assert [p.name for p in config.printers] == ["192.0.2.11", "192.0.2.12"]


def test_cli_flags_and_explicit_config(tmp_path: Path) -> None:
    other = tmp_path / "other.env"
    other.write_text('STATION_LOG_LEVEL="DEBUG"\n', encoding="utf-8")
    config = load_config(
        ["--config", str(other), "--hardware", "real", "--printers", "live", "--writes", "on",
         "--spoolman", "live", "--state-dir", str(tmp_path / "s")],
        environ={}, platform="win32", repo_dir=tmp_path,
    )
    assert (config.hardware, config.printers_mode, config.spoolman_mode, config.writes) == (
        "real", "live", "live", True,
    )
    assert config.log_level == "DEBUG"
    assert config.state_dir == tmp_path / "s"


@pytest.mark.parametrize(
    "environ",
    [{"STATION_WRITES": "maybe"}, {"STATION_HARDWARE": "fake"}, {"STATION_IPC_PORT": "x"},
     {"SCALE_MINIMUM_WEIGHT_GRAMS": "lots"}],
)
def test_invalid_values_raise(environ: dict[str, str], tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config([], environ=environ, platform="win32", repo_dir=tmp_path)


def test_writes_guard_only_applies_to_live_services() -> None:
    config = Config(printers_mode="sim", spoolman_mode="live", writes=False)
    assert config.writes_enabled("printers") is True
    assert config.writes_enabled("spoolman") is False
    assert Config(spoolman_mode="live", writes=True).writes_enabled("spoolman") is True


def test_default_state_dir_without_env() -> None:
    assert default_state_dir("linux", {}) == Path.home() / ".local" / "state" / "spool-station"
    assert default_state_dir("win32", {}) == Path.home() / "AppData" / "Local" / "spool-station"
