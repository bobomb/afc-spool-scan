#!/bin/bash
# Install or update the spool station on spoolpi (Debian 13 Lite, Raspberry Pi 4).
#
#   scripts/install-spoolpi.sh            apt packages, Python venv, touch UI build
#   scripts/install-spoolpi.sh --update   same without apt (used by deploy-spoolpi.ps1)
#
# Idempotent. Does not enable or restart services; see systemd/README.md.

set -euo pipefail

REPO="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO/.venv"
UPDATE=0

log() {
    printf '[install-spoolpi] %s\n' "$*"
}

usage() {
    sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

for arg in "$@"; do
    case "$arg" in
        --update) UPDATE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) log "Unknown option: $arg"; usage; exit 2 ;;
    esac
done

if (( ! UPDATE )); then
    log "Installing build and runtime packages"
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential cmake ninja-build pkg-config libdrm-dev libevdev-dev python3-venv python3-dev
fi

if [[ ! -x "$VENV/bin/python" ]]; then
    log "Creating $VENV"
    python3 -m venv "$VENV"
fi
log "Installing the station service into the venv"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -e "$REPO[linux]"

log "Building the touch UI (pi preset: DRM/KMS + evdev)"
(
    cd "$REPO/ui"
    cmake --preset pi
    cmake --build --preset pi
)

log "Station: $VENV/bin/python -m station"
log "Touch UI: $REPO/ui/build/pi/station-ui"
log "Done."
