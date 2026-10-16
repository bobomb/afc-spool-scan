# Project Guidelines

AFC spool scanning for two Klipper/AFC printers (Kilo, Yankee) with a DYMO
scale, a USB QR scanner and Spoolman, running on `spoolpi` (Raspberry Pi 4,
Debian 13 Lite). A touch UI (LVGL) and a Python `spool-station` service are
being built.

Host names, printer names, IPs (192.0.2.x) and the user `pi` in this repo are
placeholders. Real values live only in git-ignored files: `config.env` on the
Pi and `deploy.env` on the PC. Never commit real hostnames, IPs or usernames.

- Product decisions (source of truth): [docs/touch-ui-plan.md](../docs/touch-ui-plan.md)
- Development plan, task list, protocol, runtime modes: [docs/touch-ui-dev-plan.md](../docs/touch-ui-dev-plan.md)
- Existing scripts and operations: [README.md](../README.md)

When a task is completed, tick it in the dev plan. When the user decides
something, update the product plan section and its decision log. Never
silently change a **Decided** item.

## Architecture

- `station/` (Python, asyncio) owns all hardware and integrations: scale,
  QR scanner, Spoolman, Moonraker WebSockets, actions, activity/undo, audio.
- `ui/` (C++20, LVGL v9.6) is a thin client over TCP `127.0.0.1:7913`
  newline-delimited JSON (dev plan §5). It holds no business logic and makes
  no network calls other than the IPC connection.
- Existing bash/Python scripts in the repo root are in production on spoolpi;
  keep them working until the cutover task P4.

## Environments

- Development: Windows PC. Run the service with `--hardware sim`, and with
  either `--printers sim`, or `--printers live` plus `--writes off`. Build
  the UI with the LVGL Windows driver.
- Runtime: spoolpi (Linux). Real hardware via hidraw/evdev, UI via DRM + evdev.
- Linux-only imports (`evdev`, hidraw/ioctl code) must be lazy, so Windows
  can import every module.

## Build and Test (Windows PowerShell)

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
python -m station --hardware sim --printers sim --spoolman sim
cd ui; cmake --preset windows; cmake --build --preset windows; ctest --preset windows
```

Visual checks: `station-ui --snapshot <dir> --state ui/samples/<name>.json`
or `--connect --script ui/scripts/tour.script` writes PNG screenshots.

## Conventions

- Safety: tests never touch the network or hardware; use fakes and
  `station/sim/fixtures`. Do not send G-code or Spoolman writes unless the
  user explicitly asks to run with `--writes on`.
- Python 3.13, type hints, `aiohttp`, `pytest` + `pytest-asyncio`.
- C++: LVGL v9 APIs only (no v8 names such as `lv_disp_*` or
  `lv_obj_set_style_local_*`); one source file per screen or widget.
- Line endings are LF (see `.gitattributes`); scripts run on Linux.
- Never commit `config.env` (machine-specific). Add new keys to
  `config.env.example`.
- Weights are grams everywhere; a weight is accepted only from a stable
  reading > 50 g.
- Comments only where code can't explain itself; keep them to one line.
