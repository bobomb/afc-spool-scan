"""python -m station: run the spool station service."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Sequence

from .app import Station
from .config import ConfigError, load_config

log = logging.getLogger("station")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        config = load_config(argv)
    except ConfigError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if config.writes and "live" in (config.printers_mode, config.spoolman_mode):
        log.warning("Writes are ON: Spoolman updates and G-code will be sent to live services")
    try:
        asyncio.run(Station(config).run_forever())
    except KeyboardInterrupt:
        pass
    except OSError as error:
        log.error("Station failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
