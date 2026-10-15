AFC Spool Scan Utility
======================

This Raspberry Pi utility reads Spoolman QR codes from a USB barcode scanner and
sends `SET_NEXT_SPOOL_ID` to the Moonraker instances for `kilo.local` and
`yankee.local`.

It can also read a DYMO M5/M10 USB postal scale and submit the measured **gross
weight** (spool + filament) to Spoolman. The scale's HID report includes its
current unit and decimal exponent. The reader accepts grams or ounces and always
sends grams to Spoolman's `/api/v1/spool/{id}/measure` endpoint.

## Normal scan

Turn on the scale, put the spool on it, wait for the displayed weight to settle,
and scan either of these Spoolman formats:

- `web+spoolman:s-123`
- A URL containing `/spool/show/123`

The Spoolman prefix and URL path are matched case-insensitively, so scanners
that emit `WEB+SPOOLMAN:S-123` are also supported.

Every valid spool scan checks the scale automatically. If it reports a stable
weight over 50 g, that gross weight is converted to grams and saved in Spoolman.
If the scale is off, disconnected, unstable, empty, or reports 50 g or less, the
Spoolman weight is left unchanged. In either case, the spool ID is sent to both
printers. No trigger QR or timeout window is used.

The weighing cue plays when a qualifying scale reading is found. A success cue
confirms the completed scan; an error cue means Spoolman or a printer update
failed.

## Components

Scale support is isolated from the QR scanner:

- [usb-qr-scanner-read.sh](usb-qr-scanner-read.sh) reads QR input, invokes the
  scale updater, sends the spool ID to Moonraker, and selects audible cues.
- [spool-scale-update.sh](spool-scale-update.sh) owns the automatic scale
  threshold and Spoolman measurement update. It returns `0` when a weight was
  saved, `2` when weighing was safely skipped, and `1` on an actual error.
- [dymo-scale-read.py](dymo-scale-read.py) owns all DYMO USB HID discovery,
  report decoding, unit detection, stability checks, and conversion to grams.

This keeps DYMO protocol and scale policy code out of the QR event loop.
`dymo-scale-read.py` imports its decoder from `station/scale/dymo.py`
(standard library only), so keep the `station/` directory next to it.

## Touch UI and spool-station service

A Python `spool-station` service (`station/`) and an LVGL touch UI in C++
(`ui/`) replace the scanner script; see
[docs/touch-ui-plan.md](docs/touch-ui-plan.md) and
[docs/touch-ui-dev-plan.md](docs/touch-ui-dev-plan.md). On spoolpi they run as
the `spool-station` and `spool-station-ui` user services since the cutover on
2026-10-15; the scripts above remain usable from the CLI and as the rollback
(see [systemd/README.md](systemd/README.md)).

On Windows (PowerShell), everything runs simulated by default and makes no
network calls except to the local simulators:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest

# Service with simulated scale, scanner, printers and Spoolman (IPC on 127.0.0.1:7913)
python -m station --hardware sim --printers sim --spoolman sim --writes off

# In another terminal: drive the simulation
python -m station.simctl scale 984.0
python -m station.simctl scan WEB+SPOOLMAN:S-97
python -m station.simctl printer yankee --disconnect
python -m station.simctl state activity

# Build and run the touch UI (LVGL Windows driver, 800x480 window).
# Use the windows-vs2026 preset instead with Visual Studio 2026 and CMake 4.2+.
cd ui
cmake --preset windows
cmake --build --preset windows
ctest --preset windows
.\build\windows\Release\station-ui.exe
```

With live printers and Spoolman but no writes (reads only; Spoolman updates and
G-code are logged as dry runs and refused by the clients):

```powershell
$env:SPOOLMAN_URL = 'http://192.0.2.10:7912/api/v1'
python -m station --hardware sim --printers live --spoolman live --writes off
```

The simulators can also replay data captured from the real printers and
Spoolman (`scripts/capture-fixtures.py`, read-only):
`python -m station --sim-fixtures station/sim/fixtures/captured`.
In the simulator window the PC keyboard digits, Backspace, Enter and Esc
drive the numpad.

Headless screenshots (no window, no service needed):

```powershell
.\ui\build\windows\Release\station-ui.exe --snapshot out\main --state ui\samples\main.json
.\ui\build\windows\Release\station-ui.exe --snapshot out\tour --connect --script ui\scripts\tour.script
```

`scripts/make-ui-samples.py` regenerates `ui/samples/` from the simulator.
Deployment to spoolpi (`scripts/install-spoolpi.sh`, `systemd/`,
`scripts/deploy-spoolpi.ps1`) is prepared but not yet done.

## Requirements

- Linux/Raspberry Pi OS
- Bash, Python 3, `curl`, and `evtest`
- `alsa-utils` for a USB/HDMI/3.5 mm speaker, or Raspberry Pi `pinctrl` for an
  active GPIO buzzer
- Membership in the `input` group

Install packages and grant scanner access:

```bash
sudo apt update
sudo apt install evtest curl alsa-utils
sudo usermod -aG input "$(whoami)"
```

Log out and back in (or reboot) after changing group membership.

## DYMO scale setup

The included udev rule grants the `input` group access to a DYMO scale with USB
ID `0922:8003`:

```bash
sudo install -m 0644 99-dymo-scale.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
```

Reconnect the scale after installing the rule. Verify it directly while a
stable object is on it:

```bash
./dymo-scale-read.py --verbose
```

The final stdout value is grams. The diagnostic message identifies whether the
scale reported grams or ounces.

## Audible cues

The default `auto` backend uses ALSA and therefore works with a speaker already
selected as the Raspberry Pi's default playback device. Test it with:

```bash
./audible-cue.py success
```

The Raspberry Pi has an audio output but **does not contain a built-in speaker**.
For its 3.5 mm jack, connect powered speakers (not a bare passive speaker) and
set `AUDIO_DEVICE="plughw:CARD=Headphones,DEV=0"`. HDMI audio requires a
connected display or receiver with speakers. Playback failures are written to
the service journal.

For a simple **active** buzzer, connect its signal through suitable driver
hardware to a free BCM GPIO and its ground to Pi ground. Do not drive a buzzer
that exceeds a GPIO pin's current rating directly. Copy the example config and
select the GPIO backend (GPIO 18 shown only as an example):

```bash
cp config.env.example config.env
```

Then set:

```text
AUDIO_BACKEND="gpio"
BUZZER_GPIO_PIN="18"
```

An active buzzer can only be switched on and off, so the pattern timing differs
but pitch does not. A passive piezo needs PWM/extra hardware and is not handled
by this simple GPIO backend. Set `AUDIO_BACKEND="none"` to disable all cues.

## Configuration

Defaults are defined in the module that uses each setting. Copy
[config.env.example](config.env.example) to `config.env` to override them from
one shared configuration file without editing the scripts. Important settings
include:

- `EVENT_DEV`: stable `/dev/input/by-id` path for the QR scanner
- `MOONRAKER_HOSTS`: comma-separated Moonraker host names or LAN IP addresses;
  use reserved IP addresses if `.local`/mDNS resolution is unreliable
- `SPOOLMAN_URL`: local Spoolman REST API base URL
- `SCALE_VENDOR_ID` and comma-separated `SCALE_PRODUCT_IDS`
- `SCALE_MINIMUM_WEIGHT_GRAMS`: weight must be greater than this value to update
- `AUDIO_BACKEND` and `BUZZER_GPIO_PIN`

## User service

Since the 2026-10-15 cutover spoolpi runs `spool-station.service` and
`spool-station-ui.service` instead (installed by `scripts/install-spoolpi.sh`,
updated by `scripts/deploy-spoolpi.ps1`; units and rollback in
[systemd/README.md](systemd/README.md)). The original scanner service is kept
as the rollback:

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/afc-spool-scan/usb-qr-scanner.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now usb-qr-scanner.service
```

After changing code or configuration:

```bash
systemctl --user restart spool-station.service   # or usb-qr-scanner.service after a rollback
```

## Logs

The station service (scanner, scale, Spoolman and printers) writes to the
`spool-station` user service journal (`usb-qr-scanner` before the cutover).
On this Raspberry Pi, query user-service records from the system journal with
`--user-unit`:

```bash
journalctl --user-unit=spool-station.service -f
```

Spoolman writes its application log to `~/spoolman/data/spoolman.log` and its
console/API access log to Docker. Follow the complete Docker log with:

```bash
docker compose -f ~/spoolman/docker-compose.yml logs -f --tail=50 spoolman
```

Or follow only Spoolman's application log file with:

```bash
tail -F ~/spoolman/data/spoolman.log
```

To follow scanner, scale, and Spoolman output together, use the supplied helper:

```bash
cd ~/afc-spool-scan
./tail-logs.sh
```

It prints `[station]` and `[spoolman]` prefixes. Pass a number to change
how many existing lines are shown before following, for example
`./tail-logs.sh 100`. Press Ctrl+C to stop.

The log reports Spoolman and each Moonraker printer separately. An error cue can
therefore mean that the weight was saved successfully but one or both printers
were powered off or their `.local` names could not be resolved. Check Spoolman
itself with:

```bash
curl http://127.0.0.1:7912/api/v1/health
```
