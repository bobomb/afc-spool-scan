#!/bin/bash

set -o pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# These defaults can be overridden in config.env or in the service environment.
EVENT_DEV="${EVENT_DEV:-/dev/input/by-id/usb-TMS_HIDKeyBoard_1234567890abcd-event-kbd}"
MOONRAKER_HOSTS="${MOONRAKER_HOSTS:-kilo.local,yankee.local}"
MOONRAKER_PORT="${MOONRAKER_PORT:-7125}"
SPOOLMAN_URL="${SPOOLMAN_URL:-http://127.0.0.1:7912/api/v1}"
SPOOLMAN_PREFIX="${SPOOLMAN_PREFIX:-web+spoolman:s-}"
WEIGH_TRIGGER_CODE="${WEIGH_TRIGGER_CODE:-afc-weigh-spool}"
WEIGH_WINDOW_SECONDS="${WEIGH_WINDOW_SECONDS:-5}"
SCALE_VENDOR_ID="${SCALE_VENDOR_ID:-0922}"
SCALE_PRODUCT_IDS="${SCALE_PRODUCT_IDS:-8003}"
SCALE_READ_TIMEOUT_SECONDS="${SCALE_READ_TIMEOUT_SECONDS:-2}"
AUDIO_BACKEND="${AUDIO_BACKEND:-auto}"
AUDIO_DEVICE="${AUDIO_DEVICE:-}"
BUZZER_GPIO_PIN="${BUZZER_GPIO_PIN:-}"

if [[ -f "$SCRIPT_DIR/config.env" ]]; then
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/config.env"
fi

log() {
    printf '[%(%Y-%m-%d %H:%M:%S)T] %s\n' -1 "$*"
}

play_cue() {
    local cue="$1"
    local args=("$SCRIPT_DIR/audible-cue.py" "$cue" --backend "$AUDIO_BACKEND")
    if [[ -n "$AUDIO_DEVICE" ]]; then
        args+=(--device "$AUDIO_DEVICE")
    fi
    if [[ -n "$BUZZER_GPIO_PIN" ]]; then
        args+=(--gpio-pin "$BUZZER_GPIO_PIN")
    fi
    "${args[@]}" || log "Warning: the '$cue' audible cue could not be played." &
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        log "Error: $1 is not installed or not in PATH."
        exit 1
    fi
}

require_command evtest
require_command curl
require_command python3

if [[ ! -e "$EVENT_DEV" ]]; then
    log "Error: QR scanner device $EVENT_DEV was not found."
    exit 1
fi

post_next_spool_id() {
    local spool_id="$1"
    local host
    local pid
    local failed=0
    local pids=()

    IFS=',' read -r -a hosts <<< "$MOONRAKER_HOSTS"
    for host in "${hosts[@]}"; do
        host="${host//[[:space:]]/}"
        [[ -z "$host" ]] && continue
        log "Setting next spool $spool_id on $host."
        curl --fail --silent --show-error \
            --connect-timeout 2 --max-time 5 \
            -X POST "http://${host}:${MOONRAKER_PORT}/printer/gcode/script" \
            -H "Content-Type: application/json" \
            -d "{\"script\":\"SET_NEXT_SPOOL_ID SPOOL_ID=${spool_id}\"}" \
            >/dev/null &
        pids+=("$!")
    done

    for pid in "${pids[@]}"; do
        wait "$pid" || failed=1
    done
    return "$failed"
}

update_spool_weight() {
    local spool_id="$1"
    local error_file
    local weight

    error_file="$(mktemp)"
    if ! weight=$("$SCRIPT_DIR/dymo-scale-read.py" \
        --timeout "$SCALE_READ_TIMEOUT_SECONDS" \
        --vendor-id "$SCALE_VENDOR_ID" \
        --product-ids "$SCALE_PRODUCT_IDS" 2>"$error_file"); then
        log "$(<"$error_file")"
        rm -f "$error_file"
        return 1
    fi
    rm -f "$error_file"

    log "Updating Spoolman spool $spool_id with gross weight ${weight} g."
    if ! curl --fail --silent --show-error \
        --connect-timeout 2 --max-time 5 \
        -X PUT "$SPOOLMAN_URL/spool/$spool_id/measure" \
        -H "Content-Type: application/json" \
        -d "{\"weight\":${weight}}" >/dev/null; then
        log "Error: Spoolman rejected the weight for spool $spool_id."
        return 1
    fi
}

extract_spool_id() {
    local code="$1"
    local spool_id=""

    if [[ "$code" == "$SPOOLMAN_PREFIX"* ]]; then
        spool_id="${code#"$SPOOLMAN_PREFIX"}"
    elif [[ "$code" =~ /spool/show/([0-9]+)([/\?\#]|$) ]]; then
        spool_id="${BASH_REMATCH[1]}"
    fi

    if [[ "$spool_id" =~ ^[0-9]+$ ]]; then
        printf '%s\n' "$spool_id"
        return 0
    fi
    return 1
}

now_ms() {
    date +%s%3N
}

weigh_mode=0
weigh_deadline_ms=0

expire_weigh_mode() {
    weigh_mode=0
    weigh_deadline_ms=0
    log "The weighing scan window timed out; the next spool will not be weighed."
    play_cue timeout
}

process_scan() {
    local code="$1"
    local spool_id
    local failed=0
    local current_ms

    log "Scanned code: $code"
    if [[ "$code" == "$WEIGH_TRIGGER_CODE" ]]; then
        weigh_mode=1
        weigh_deadline_ms=$(( $(now_ms) + WEIGH_WINDOW_SECONDS * 1000 ))
        log "Weighing mode active: scan a Spoolman spool within $WEIGH_WINDOW_SECONDS seconds."
        play_cue weigh
        return
    fi

    if ! spool_id="$(extract_spool_id "$code")"; then
        log "Ignored unrecognized QR code."
        return
    fi

    if (( weigh_mode )); then
        current_ms="$(now_ms)"
        if (( current_ms >= weigh_deadline_ms )); then
            expire_weigh_mode
        else
            weigh_mode=0
            weigh_deadline_ms=0
            update_spool_weight "$spool_id" || failed=1
        fi
    fi

    post_next_spool_id "$spool_id" || failed=1
    if (( failed )); then
        log "Spool $spool_id was scanned, but one or more updates failed."
        play_cue error
    else
        log "Spool $spool_id was accepted."
        play_cue success
    fi
}

# Linux input keycode to character mapping for common USB barcode scanners.
KEYS=( "" "ESC" "1" "2" "3" "4" "5" "6" "7" "8" "9" "0" "-" "=" "BACKSPACE" "TAB"
    "q" "w" "e" "r" "t" "y" "u" "i" "o" "p" "[" "]" "ENTER" "CTRL"
    "a" "s" "d" "f" "g" "h" "j" "k" "l" ";" "'" "\`" "LSHIFT" "\\" "z" "x"
    "c" "v" "b" "n" "m" "," "." "/" "RSHIFT" "*" "ALT" "SPACE" )

append_key() {
    local keyname="$1"
    if (( shift_active )); then
        case "$keyname" in
            [a-z]) keyname="${keyname^^}" ;;
            1) keyname="!" ;; 2) keyname="@" ;; 3) keyname="#" ;; 4) keyname="$" ;;
            5) keyname="%" ;; 6) keyname="^" ;; 7) keyname="&" ;; 8) keyname="*" ;;
            9) keyname="(" ;; 0) keyname=")" ;; -) keyname="_" ;; =) keyname="+" ;;
            \[) keyname="{" ;; \]) keyname="}" ;; \\) keyname="|" ;; \;) keyname=":" ;;
            "'") keyname='"' ;; ,) keyname="<" ;; .) keyname=">" ;; /) keyname="?" ;;
        esac
    fi
    buffer+="$keyname"
}

handle_input_event() {
    local line="$1"
    local keycode
    local keyname

    [[ "$line" == *"EV_KEY"* ]] || return
    keycode="$(sed -n 's/.*code \([0-9]\+\) (.*/\1/p' <<< "$line")"
    [[ "$keycode" =~ ^[0-9]+$ ]] || return
    keyname="${KEYS[$keycode]:-}"

    if [[ "$line" == *"value 0"* ]]; then
        if [[ "$keyname" == "LSHIFT" || "$keyname" == "RSHIFT" ]]; then
            shift_active=0
        fi
        return
    fi
    [[ "$line" == *"value 1"* ]] || return

    case "$keyname" in
        LSHIFT|RSHIFT) shift_active=1 ;;
        ENTER)
            process_scan "$buffer"
            buffer=""
            ;;
        BACKSPACE) buffer="${buffer%?}" ;;
        SPACE) buffer+=" " ;;
        ESC|TAB|CTRL|ALT|"") ;;
        *) append_key "$keyname" ;;
    esac
}

log "Reading QR codes from $EVENT_DEV."
log "Weighing trigger QR contents: $WEIGH_TRIGGER_CODE"

buffer=""
shift_active=0

exec {evtest_fd}< <(evtest "$EVENT_DEV" 2>/dev/null)
while true; do
    if (( weigh_mode )); then
        current_ms="$(now_ms)"
        if (( current_ms >= weigh_deadline_ms )); then
            expire_weigh_mode
            continue
        fi
        remaining_ms=$(( weigh_deadline_ms - current_ms ))
        printf -v read_timeout '%d.%03d' $(( remaining_ms / 1000 )) $(( remaining_ms % 1000 ))
        if IFS= read -r -t "$read_timeout" -u "$evtest_fd" line; then
            handle_input_event "$line"
        else
            read_status=$?
            if (( read_status > 128 )); then
                expire_weigh_mode
            else
                log "Error: evtest stopped reading the QR scanner."
                exit 1
            fi
        fi
    elif IFS= read -r -u "$evtest_fd" line; then
        handle_input_event "$line"
    else
        log "Error: evtest stopped reading the QR scanner."
        exit 1
    fi
done
