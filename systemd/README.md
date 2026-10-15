# Spool station systemd user units

Installed as user services, like `usb-qr-scanner.service` (spoolpi has
`Linger=yes`, so they start at boot without a login). `spool-station`
declares `Conflicts=usb-qr-scanner.service`, so starting one stops the other.

Status on spoolpi: cut over on 2026-10-15 — `spool-station.service` and
`spool-station-ui.service` enabled, `usb-qr-scanner.service` disabled.

## Cutover (dev plan P4)

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/afc-spool-scan/systemd/spool-station.service ~/.config/systemd/user/
ln -sf ~/afc-spool-scan/systemd/spool-station-ui.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user disable --now usb-qr-scanner.service
systemctl --user enable --now spool-station.service spool-station-ui.service
journalctl --user-unit=spool-station.service -f
```

`disable` also removes the link of a linked unit, so after the cutover
`~/.config/systemd/user/usb-qr-scanner.service` no longer exists. Enabling a
unit by its full path re-links it.

Rollback:

```bash
systemctl --user disable --now spool-station-ui.service spool-station.service
systemctl --user enable --now ~/afc-spool-scan/usb-qr-scanner.service
```

To return to the station afterwards, repeat the cutover (the `ln` lines are
needed again for the same reason).

## Touch UI (dev plan P5)

The UI needs DRM master and `/dev/input` access as `pi` (groups
`video`, `render`, `input`). Verified on 2026-10-15: as a user service it
becomes DRM master of `/dev/dri/card1` on first open; no system service or
logind seat is needed, and the getty on tty1 does not interfere. The unit
passes `--drm-card /dev/dri/card1` and the touchscreen's stable path
`/dev/input/by-path/platform-fe205000.i2c-event`.
