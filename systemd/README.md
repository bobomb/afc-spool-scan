# Spool station systemd user units

Installed as user services, like `usb-qr-scanner.service`. `spool-station`
declares `Conflicts=usb-qr-scanner.service`, so starting one stops the other.

## Cutover (dev plan P4)

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/afc-spool-scan/systemd/spool-station.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user disable --now usb-qr-scanner.service
systemctl --user enable --now spool-station.service
journalctl --user-unit=spool-station.service -f
```

Rollback:

```bash
systemctl --user disable --now spool-station.service
systemctl --user enable --now usb-qr-scanner.service
```

## Touch UI (after panel bring-up, dev plan P5)

```bash
ln -sf ~/afc-spool-scan/systemd/spool-station-ui.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now spool-station-ui.service
```

The UI needs DRM master and `/dev/input` access as `pi`
(`sudo usermod -aG video,render,input pi`). If a user service cannot
take DRM master, convert it to a system service with `User=pi`.
