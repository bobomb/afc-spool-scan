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

Scan either of these Spoolman formats:

- `web+spoolman:s-123`
- A URL containing `/spool/show/123`

The spool ID is sent to both printers. A successful scan plays the success cue.

## Weigh and scan

1. Put the spool on the scale and wait for its display to settle.
2. Scan [weigh-spool-trigger.svg](weigh-spool-trigger.svg). This QR contains the
    text `afc-weigh-spool` and starts a five-second window.
3. The start cue sounds. Scan the spool's normal Spoolman QR within five seconds.
4. The gross weight is read, converted to grams if needed, and sent to Spoolman.
    The same spool ID is then sent to both printers.
5. A success cue confirms completion. A low timeout cue sounds if no spool QR is
    completed within five seconds; an error cue means an update failed.

A spool QR scanned after a timeout still sets the next spool on both printers,
but it does not alter its Spoolman weight.

Print the supplied SVG or display it near the scale. To generate a replacement:

```bash
qrencode -t SVG -l H -m 4 -o weigh-spool-trigger.svg 'afc-weigh-spool'
```

## Requirements

- Linux/Raspberry Pi OS
- Bash, Python 3, `curl`, and `evtest`
- `alsa-utils` for a USB/HDMI/3.5 mm speaker, or Raspberry Pi `pinctrl` for an
  active GPIO buzzer
- Membership in the `input` group

Install packages and grant scanner access:

```bash
sudo apt update
sudo apt install evtest curl alsa-utils qrencode
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

Defaults are at the top of [usb-qr-scanner-read.sh](usb-qr-scanner-read.sh).
Copy [config.env.example](config.env.example) to `config.env` to override them
without editing the script. Important settings include:

- `EVENT_DEV`: stable `/dev/input/by-id` path for the QR scanner
- `MOONRAKER_HOSTS`: comma-separated Moonraker host names
- `SPOOLMAN_URL`: local Spoolman REST API base URL
- `WEIGH_TRIGGER_CODE` and `WEIGH_WINDOW_SECONDS`
- `SCALE_VENDOR_ID` and comma-separated `SCALE_PRODUCT_IDS`
- `AUDIO_BACKEND` and `BUZZER_GPIO_PIN`

If `WEIGH_TRIGGER_CODE` changes, regenerate the trigger QR with the exact new
text.

## User service

Install and start the service:

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/afc-spool-scan/usb-qr-scanner.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now usb-qr-scanner.service
```

After changing code or configuration:

```bash
systemctl --user restart usb-qr-scanner.service
```

View activity and errors:

```bash
journalctl --user -u usb-qr-scanner.service -f
```
