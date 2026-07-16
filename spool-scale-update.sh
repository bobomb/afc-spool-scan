#!/bin/bash

# Read the DYMO scale and, when appropriate, update one Spoolman spool.
# Exit status: 0 = updated, 1 = update/error, 2 = no qualifying scale reading.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

SPOOLMAN_URL="${SPOOLMAN_URL:-http://127.0.0.1:7912/api/v1}"
SCALE_VENDOR_ID="${SCALE_VENDOR_ID:-0922}"
SCALE_PRODUCT_IDS="${SCALE_PRODUCT_IDS:-8003}"
SCALE_READ_TIMEOUT_SECONDS="${SCALE_READ_TIMEOUT_SECONDS:-2}"
SCALE_MINIMUM_WEIGHT_GRAMS="${SCALE_MINIMUM_WEIGHT_GRAMS:-50}"
SCALE_READER="${SCALE_READER:-$SCRIPT_DIR/dymo-scale-read.py}"

if [[ -f "$SCRIPT_DIR/config.env" ]]; then
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/config.env"
fi

log() {
    printf '[%(%Y-%m-%d %H:%M:%S)T] %s\n' -1 "$*"
}

if (( $# != 1 )) || [[ ! "$1" =~ ^[0-9]+$ ]]; then
    log "Error: usage: $0 SPOOL_ID"
    exit 1
fi

if [[ ! -x "$SCALE_READER" ]]; then
    log "Error: scale reader $SCALE_READER is missing or not executable."
    exit 1
fi

for command in curl awk python3; do
    if ! command -v "$command" >/dev/null 2>&1; then
        log "Error: $command is not installed or not in PATH."
        exit 1
    fi
done

spool_id="$1"
error_file="$(mktemp)"
trap 'rm -f "$error_file"' EXIT

if ! weight=$("$SCALE_READER" \
    --timeout "$SCALE_READ_TIMEOUT_SECONDS" \
    --vendor-id "$SCALE_VENDOR_ID" \
    --product-ids "$SCALE_PRODUCT_IDS" 2>"$error_file"); then
    log "Scale is unavailable or has no stable reading; not updating spool $spool_id."
    exit 2
fi

if ! awk -v weight="$weight" -v minimum="$SCALE_MINIMUM_WEIGHT_GRAMS" \
    'BEGIN { exit !(weight > minimum) }'; then
    log "Scale reports ${weight} g (must be over ${SCALE_MINIMUM_WEIGHT_GRAMS} g); not updating spool $spool_id."
    exit 2
fi

log "Updating Spoolman spool $spool_id with gross weight ${weight} g."
if ! curl --fail --silent --show-error \
    --connect-timeout 2 --max-time 5 --retry 1 --retry-all-errors \
    -X PUT "$SPOOLMAN_URL/spool/$spool_id/measure" \
    -H "Content-Type: application/json" \
    -d "{\"weight\":${weight}}" >/dev/null; then
    log "Error: Spoolman rejected the weight for spool $spool_id."
    exit 1
fi

log "Spoolman accepted ${weight} g for spool $spool_id."
