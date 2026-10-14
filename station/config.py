"""Service configuration: config.env, environment variables and CLI flags.

Precedence (lowest to highest): platform defaults, config.env, environment,
command-line flags.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PRINTERS = "Kilo=192.0.2.11:7125,Yankee=192.0.2.12:7125"
DEFAULT_MOONRAKER_PORT = 7125
DEFAULT_IPC_PORT = 7913


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PrinterConfig:
    name: str
    host: str
    port: int = DEFAULT_MOONRAKER_PORT

    @property
    def key(self) -> str:
        return self.name.lower()

    @property
    def websocket_url(self) -> str:
        return f"ws://{self.host}:{self.port}/websocket"


def default_state_dir(platform: str, environ: Mapping[str, str]) -> Path:
    if platform == "win32":
        base = environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "spool-station"
    base = environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "spool-station"


@dataclass(frozen=True)
class Config:
    hardware: str = "sim"
    printers_mode: str = "sim"
    spoolman_mode: str = "sim"
    writes: bool = False
    ipc_host: str = "127.0.0.1"
    ipc_port: int = DEFAULT_IPC_PORT
    printers: tuple[PrinterConfig, ...] = ()
    spoolman_url: str = "http://127.0.0.1:7912/api/v1"
    spoolman_prefix: str = "web+spoolman:s-"
    event_dev: str = "/dev/input/by-id/usb-TMS_HIDKeyBoard_1234567890abcd-event-kbd"
    scale_vendor_id: str = "0922"
    scale_product_ids: frozenset[str] = frozenset({"8003"})
    scale_read_timeout_s: float = 2.0
    scale_minimum_g: float = 50.0
    audio_backend: str = "auto"
    audio_device: str = ""
    buzzer_gpio_pin: str = ""
    state_dir: Path = field(default_factory=lambda: default_state_dir(sys.platform, os.environ))
    repo_dir: Path = REPO_DIR
    log_level: str = "INFO"
    # Fixture directory (printers/*.json, spoolman/spools.json) for the simulators; None = built-in.
    sim_fixtures: Path | None = None

    def writes_enabled(self, service: str) -> bool:
        """Simulated services are in-memory, so --writes only guards live ones."""
        mode = {"spoolman": self.spoolman_mode, "printers": self.printers_mode}[service]
        return mode == "sim" or self.writes

    @property
    def simulated(self) -> bool:
        return "sim" in (self.hardware, self.printers_mode, self.spoolman_mode)


def platform_defaults(platform: str) -> dict[str, str]:
    if platform == "win32":
        return {"STATION_HARDWARE": "sim", "STATION_PRINTERS": "sim",
                "STATION_SPOOLMAN": "sim", "STATION_WRITES": "off"}
    return {"STATION_HARDWARE": "real", "STATION_PRINTERS": "live",
            "STATION_SPOOLMAN": "live", "STATION_WRITES": "on"}


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    hash_at = raw.find(" #")
    return (raw[:hash_at] if hash_at >= 0 else raw).strip()


def parse_env_text(text: str) -> dict[str, str]:
    """Parse KEY="value" lines as written for bash `source` (no expansion)."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export "):].lstrip()
        key, sep, raw = stripped.partition("=")
        key = key.strip()
        if not sep or not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        values[key] = _unquote(raw)
    return values


def parse_env_file(path: Path) -> dict[str, str]:
    try:
        return parse_env_text(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def parse_printers(spec: str, default_port: int = DEFAULT_MOONRAKER_PORT) -> tuple[PrinterConfig, ...]:
    printers: list[PrinterConfig] = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        name, sep, address = item.partition("=")
        if not sep:
            name, address = "", item
        name, address = name.strip(), address.strip()
        host, colon, port_text = address.rpartition(":")
        if not colon:
            host, port_text = address, str(default_port)
        host = host.strip()
        if not host:
            raise ConfigError(f"printer entry {item!r} has no host")
        try:
            port = int(port_text)
        except ValueError as error:
            raise ConfigError(f"printer entry {item!r} has an invalid port") from error
        if not 0 < port < 65536:
            raise ConfigError(f"printer entry {item!r} has an invalid port")
        printer = PrinterConfig(name=name or host, host=host, port=port)
        if any(existing.key == printer.key for existing in printers):
            raise ConfigError(f"duplicate printer name {printer.name!r}")
        if printer.key == "both":
            raise ConfigError("'both' is reserved and cannot be a printer name")
        printers.append(printer)
    if not printers:
        raise ConfigError("no printers configured")
    return tuple(printers)


def _choice(values: Mapping[str, str], key: str, choices: Sequence[str]) -> str:
    value = values[key].strip().lower()
    if value not in choices:
        raise ConfigError(f"{key} must be one of {', '.join(choices)} (got {values[key]!r})")
    return value


def _bool(values: Mapping[str, str], key: str) -> bool:
    value = values[key].strip().lower()
    if value in {"on", "true", "1", "yes"}:
        return True
    if value in {"off", "false", "0", "no"}:
        return False
    raise ConfigError(f"{key} must be on or off (got {values[key]!r})")


def _number(values: Mapping[str, str], key: str, default: float) -> float:
    raw = values.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise ConfigError(f"{key} must be a number (got {raw!r})") from error


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m station", description="AFC spool station service")
    parser.add_argument("--config", type=Path, help="config.env path (default: repository config.env)")
    parser.add_argument("--hardware", choices=("sim", "real"))
    parser.add_argument("--printers", choices=("sim", "live"))
    parser.add_argument("--spoolman", choices=("sim", "live"))
    parser.add_argument("--writes", choices=("on", "off"))
    parser.add_argument("--ipc-host")
    parser.add_argument("--ipc-port", type=int)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--sim-fixtures", type=Path,
                        help="fixture directory for the simulators, e.g. station/sim/fixtures/captured")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser


def load_config(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    platform: str | None = None,
    repo_dir: Path = REPO_DIR,
) -> Config:
    environ = dict(os.environ if environ is None else environ)
    platform = platform or sys.platform
    args = build_arg_parser().parse_args(argv)

    config_path = args.config or Path(environ.get("STATION_CONFIG") or repo_dir / "config.env")
    values: dict[str, str] = platform_defaults(platform)
    values.update(parse_env_file(config_path))
    values.update(environ)
    cli = {
        "STATION_HARDWARE": args.hardware,
        "STATION_PRINTERS": args.printers,
        "STATION_SPOOLMAN": args.spoolman,
        "STATION_WRITES": args.writes,
        "STATION_IPC_HOST": args.ipc_host,
        "STATION_IPC_PORT": None if args.ipc_port is None else str(args.ipc_port),
        "STATION_STATE_DIR": None if args.state_dir is None else str(args.state_dir),
        "STATION_SIM_FIXTURES": None if args.sim_fixtures is None else str(args.sim_fixtures),
        "STATION_LOG_LEVEL": args.log_level,
    }
    values.update({key: value for key, value in cli.items() if value is not None})

    moonraker_port = int(_number(values, "MOONRAKER_PORT", DEFAULT_MOONRAKER_PORT))
    if values.get("PRINTERS", "").strip():
        printers = parse_printers(values["PRINTERS"], moonraker_port)
    elif values.get("MOONRAKER_HOSTS", "").strip():
        printers = parse_printers(values["MOONRAKER_HOSTS"], moonraker_port)
    else:
        printers = parse_printers(DEFAULT_PRINTERS, moonraker_port)

    try:
        ipc_port = int(values.get("STATION_IPC_PORT", DEFAULT_IPC_PORT))
    except ValueError as error:
        raise ConfigError("STATION_IPC_PORT must be an integer") from error
    if not 0 <= ipc_port < 65536:
        raise ConfigError("STATION_IPC_PORT is out of range")

    product_ids = frozenset(
        part.strip().lower() for part in values.get("SCALE_PRODUCT_IDS", "8003").split(",") if part.strip()
    )
    state_dir_text = values.get("STATION_STATE_DIR", "").strip()
    state_dir = Path(state_dir_text) if state_dir_text else default_state_dir(platform, environ)
    fixtures_text = values.get("STATION_SIM_FIXTURES", "").strip()
    sim_fixtures: Path | None = None
    if fixtures_text:
        sim_fixtures = Path(fixtures_text)
        if not sim_fixtures.is_absolute():
            sim_fixtures = repo_dir / sim_fixtures
        if not (sim_fixtures / "printers").is_dir() or not (sim_fixtures / "spoolman" / "spools.json").is_file():
            raise ConfigError(f"STATION_SIM_FIXTURES {fixtures_text!r} needs printers/*.json and spoolman/spools.json")

    config = Config(
        hardware=_choice(values, "STATION_HARDWARE", ("sim", "real")),
        printers_mode=_choice(values, "STATION_PRINTERS", ("sim", "live")),
        spoolman_mode=_choice(values, "STATION_SPOOLMAN", ("sim", "live")),
        writes=_bool(values, "STATION_WRITES"),
        ipc_host=values.get("STATION_IPC_HOST", "127.0.0.1").strip() or "127.0.0.1",
        ipc_port=ipc_port,
        printers=printers,
        spoolman_url=values.get("SPOOLMAN_URL", "http://127.0.0.1:7912/api/v1").strip().rstrip("/"),
        spoolman_prefix=values.get("SPOOLMAN_PREFIX", "web+spoolman:s-"),
        event_dev=values.get("EVENT_DEV", Config.event_dev),
        scale_vendor_id=values.get("SCALE_VENDOR_ID", "0922").strip().lower(),
        scale_product_ids=product_ids or frozenset({"8003"}),
        scale_read_timeout_s=_number(values, "SCALE_READ_TIMEOUT_SECONDS", 2.0),
        scale_minimum_g=_number(values, "SCALE_MINIMUM_WEIGHT_GRAMS", 50.0),
        audio_backend=values.get("AUDIO_BACKEND", "auto").strip() or "auto",
        audio_device=values.get("AUDIO_DEVICE", "").strip(),
        buzzer_gpio_pin=values.get("BUZZER_GPIO_PIN", "").strip(),
        state_dir=state_dir,
        repo_dir=repo_dir,
        log_level=values.get("STATION_LOG_LEVEL", "INFO").strip().upper() or "INFO",
        sim_fixtures=sim_fixtures,
    )
    return config


def with_overrides(config: Config, **changes: object) -> Config:
    return replace(config, **changes)
