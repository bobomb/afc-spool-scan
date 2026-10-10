#!/bin/bash

set -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SPOOLMAN_COMPOSE_FILE="${SPOOLMAN_COMPOSE_FILE:-$SCRIPT_DIR/../spoolman/docker-compose.yml}"
TAIL_LINES="${1:-50}"

if [[ ! "$TAIL_LINES" =~ ^[0-9]+$ ]]; then
    echo "Usage: $0 [number-of-existing-lines]" >&2
    exit 1
fi

if [[ ! -f "$SPOOLMAN_COMPOSE_FILE" ]]; then
    echo "Spoolman compose file not found: $SPOOLMAN_COMPOSE_FILE" >&2
    exit 1
fi

cleanup() {
    local pid
    for pid in "${pids[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

pids=()

echo "Following scanner/scale and Spoolman logs (Ctrl+C to stop)..."

journalctl --user-unit=usb-qr-scanner.service \
    --follow --lines="$TAIL_LINES" --output=cat 2>&1 \
    | sed -u 's/^/[scanner-scale] /' &
pids+=("$!")

docker compose -f "$SPOOLMAN_COMPOSE_FILE" logs \
    --follow --tail="$TAIL_LINES" --no-log-prefix spoolman 2>&1 \
    | sed -u 's/^/[spoolman]      /' &
pids+=("$!")

wait -n "${pids[@]}"
