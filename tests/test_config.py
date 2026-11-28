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


@pytest.mark.parametrize("spec", ["", "A=:7125", "A=host:x", "A=host:70000", "A=h1,a=h2", "Both=h",
                                  "H=bambuddy", "H=bambuddy:0", "H=bambuddy:x", "H=BAMBUDDY:-1"])
def test_parse_printers_rejects_bad_entries(spec: str) -> None:
    with pytest.raises(ConfigError):
        parse_printers(spec)


def test_parse_printers_bambuddy_entries() -> None:
    kilo, hotel = parse_printers("Kilo=192.0.2.11:7125,Hotel=Bambuddy:3")
    assert kilo.kind == "moonraker" and kilo.bambuddy_printer_id is None
    assert (hotel.name, hotel.kind, hotel.bambuddy_printer_id) == ("Hotel", "bambuddy", 3)


def test_bambuddy_settings_and_key_file(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets.env"
    secrets.write_text("# Bambuddy\nBAMBUDDY_ADMIN_USER=admin\nBAMBUDDY_API_KEY=bb_secret_value\n", encoding="utf-8")
    environ = {"PRINTERS": "Kilo=192.0.2.11:7125,Hotel=bambuddy:1", "BAMBUDDY_API_KEY_FILE": str(secrets),
               "BAMBUDDY_URL": "http://192.0.2.10:8010/", "BAMBUDDY_WRITES": "off"}
    config = load_config([], environ=environ, platform="linux", repo_dir=tmp_path)
    assert config.bambuddy_api_key == "bb_secret_value"
    assert "bb_secret_value" not in repr(config)
    assert config.bambuddy_url == "http://192.0.2.10:8010"
    assert config.writes_enabled("printers") is True and config.writes_enabled("bambuddy") is False
    assert config.has_bambuddy
    on = load_config(["--bambuddy-writes", "on", "--writes", "off"], environ=environ, platform="linux",
                     repo_dir=tmp_path)
    assert on.writes_enabled("printers") is False and on.writes_enabled("bambuddy") is True
    direct = load_config([], environ={**environ, "BAMBUDDY_API_KEY": "direct"}, platform="linux", repo_dir=tmp_path)
    assert direct.bambuddy_api_key == "direct"


def test_bambuddy_key_file_problems(tmp_path: Path) -> None:
    environ = {"PRINTERS": "Hotel=bambuddy:1", "BAMBUDDY_API_KEY_FILE": str(tmp_path / "missing.env")}
    with pytest.raises(ConfigError, match="cannot be read"):
        load_config([], environ=environ, platform="linux", repo_dir=tmp_path)
    (tmp_path / "empty.env").write_text("OTHER=1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="no BAMBUDDY_API_KEY"):
        load_config([], environ={**environ, "BAMBUDDY_API_KEY_FILE": str(tmp_path / "empty.env")},
                    platform="linux", repo_dir=tmp_path)
    simulated = load_config([], environ=environ, platform="win32", repo_dir=tmp_path)
    assert simulated.bambuddy_api_key == "" and simulated.writes_enabled("bambuddy") is True


def test_bambu_access_code(tmp_path: Path) -> None:
    secrets = tmp_path / "bambu.env"
    secrets.write_text("BAMBU_ACCESS_CODE=test-code\n", encoding="utf-8")
    environ = {"PRINTERS": "Hotel=bambuddy:1", "BAMBUDDY_API_KEY": "key", "BAMBU_ACCESS_CODE_FILE": str(secrets)}
    config = load_config([], environ=environ, platform="linux", repo_dir=tmp_path)
    assert config.bambu_access_code == "test-code" and "test-code" not in repr(config)
    direct = load_config([], environ={**environ, "BAMBU_ACCESS_CODE": "direct"}, platform="linux", repo_dir=tmp_path)
    assert direct.bambu_access_code == "direct"
    without = load_config([], environ={"PRINTERS": "Hotel=bambuddy:1", "BAMBUDDY_API_KEY": "key"}, platform="linux",
                          repo_dir=tmp_path)
    assert without.bambu_access_code == ""
    simulated = load_config([], environ={**environ, "BAMBU_ACCESS_CODE_FILE": str(tmp_path / "missing.env")},
                            platform="win32", repo_dir=tmp_path)
    assert simulated.bambu_access_code == ""
    with pytest.raises(ConfigError, match="BAMBU_ACCESS_CODE_FILE"):
        load_config([], environ={**environ, "BAMBU_ACCESS_CODE_FILE": str(tmp_path / "missing.env")},
                    platform="linux", repo_dir=tmp_path)


def test_windows_defaults_are_safe(tmp_path: Path) -> None:
    config = load_config([], environ={"LOCALAPPDATA": str(tmp_path)}, platform="win32", repo_dir=tmp_path)
    assert (config.hardware, config.printers_mode, config.spoolman_mode, config.writes) == (
        "sim", "sim", "sim", False,
    )
    assert config.state_dir == tmp_path / "spool-station"
    assert [p.name for p in config.printers] == ["Kilo", "Yankee"]
    assert config.ipc_host == "127.0.0.1"
    assert config.ipc_port == 7913
    assert (config.web_host, config.web_port) == ("127.0.0.1", 7914)


def test_linux_defaults_use_real_services(tmp_path: Path) -> None:
    config = load_config([], environ={"XDG_STATE_HOME": str(tmp_path)}, platform="linux", repo_dir=tmp_path)
    assert (config.hardware, config.printers_mode, config.spoolman_mode, config.writes) == (
        "real", "live", "live", True,
    )
    assert config.state_dir == tmp_path / "spool-station"
    assert (config.web_host, config.web_port) == ("0.0.0.0", 7914)


def test_web_view_port_and_off(tmp_path: Path) -> None:
    def load(argv: list[str], environ: dict[str, str]) -> Config:
        return load_config(argv, environ=environ, platform="linux", repo_dir=tmp_path)

    assert load([], {"STATION_WEB_PORT": "off"}).web_port is None
    assert load(["--web-port", "8100", "--web-host", "127.0.0.1"], {"STATION_WEB_PORT": "off"}).web_port == 8100
    assert load(["--web-port", "off"], {}).web_port is None
    with pytest.raises(ConfigError, match="STATION_WEB_PORT must be an integer or off"):
        load([], {"STATION_WEB_PORT": "web"})
    with pytest.raises(ConfigError, match="STATION_WEB_PORT is out of range"):
        load([], {"STATION_WEB_PORT": "70000"})


def test_spoolman_web_url(tmp_path: Path) -> None:
    def load(environ: dict[str, str]) -> Config:
        return load_config([], environ=environ, platform="linux", repo_dir=tmp_path)

    assert load({}).spoolman_web_url == ""
    configured = load({"SPOOLMAN_WEB_URL": " https://spoolman.example/sm/ "})
    assert configured.spoolman_web_url == "https://spoolman.example/sm"
    for bad in ("spoolman.example", "ftp://spoolman.example", "http://"):
        with pytest.raises(ConfigError, match="SPOOLMAN_WEB_URL must be an http"):
            load({"SPOOLMAN_WEB_URL": bad})


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
