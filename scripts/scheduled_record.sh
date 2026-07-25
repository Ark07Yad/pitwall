#!/usr/bin/env bash
#
# Record a session unattended.
#
# Start this before you leave, and it will keep the Mac awake, wait until the
# session, record it, and stop on its own.
#
#   scripts/scheduled_record.sh "2026-07-26 13:50" data/raw/2026-hungary-race.txt 210
#
# Arguments: start time ("YYYY-MM-DD HH:MM", local), output file, minutes to
# record (default 210 - a race plus buffer either side).
#
# Leave the machine plugged in, on wi-fi, and with the LID OPEN. macOS sleeps on
# lid close no matter what `caffeinate` says, and a sleeping Mac records nothing.

set -uo pipefail

START_AT="${1:?usage: scheduled_record.sh \"YYYY-MM-DD HH:MM\" OUTPUT [MINUTES]}"
OUTPUT="${2:?missing output file}"
MINUTES="${3:-210}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${REPO}/data/raw/$(basename "${OUTPUT%.*}")-runner.log"
mkdir -p "$(dirname "$OUTPUT")" "$(dirname "$LOG")"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

target_epoch=$(date -j -f "%Y-%m-%d %H:%M" "$START_AT" +%s 2>/dev/null) || {
    echo "could not parse start time: '$START_AT' (expected \"YYYY-MM-DD HH:MM\")" >&2
    exit 1
}
now_epoch=$(date +%s)
wait_seconds=$(( target_epoch - now_epoch ))

if (( wait_seconds < 0 )); then
    log "start time is $(( -wait_seconds / 60 )) min in the past - starting now"
    wait_seconds=0
fi

# Hold the system awake for as long as this script lives. Without this the Mac
# sleeps after a minute idle and the recording simply stops. The display is
# deliberately allowed to sleep - this may be started the night before, and
# there is no reason to burn the screen until the session starts.
caffeinate -ims -w $$ &
CAFFEINATE_PID=$!

cleanup() {
    log "shutting down"
    [[ -n "${RECORDER_PID:-}" ]] && kill "$RECORDER_PID" 2>/dev/null
    kill "$CAFFEINATE_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

log "target   : $START_AT (in $(( wait_seconds / 60 )) min)"
log "output   : $OUTPUT"
log "duration : ${MINUTES} min"
log "sleep is held off until this script exits"

# Poll against the wall clock rather than one long sleep. A single `sleep` is
# suspended if the machine ever does sleep, so it would fire late by however
# long the nap lasted; re-reading the clock each minute fires on time regardless
# (or immediately, if we woke up already past due).
while (( $(date +%s) < target_epoch )); do
    remaining=$(( target_epoch - $(date +%s) ))
    if (( remaining > 60 )); then sleep 60; else sleep "$remaining"; fi
done

log "starting recorder"
"${REPO}/.venv/bin/python" "${REPO}/scripts/record.py" "$OUTPUT" >>"$LOG" 2>&1 &
RECORDER_PID=$!

# Stop after the window rather than running forever if we are not around to
# Ctrl-C it.
( sleep $(( MINUTES * 60 )); kill -TERM "$RECORDER_PID" 2>/dev/null ) &
TIMER_PID=$!

wait "$RECORDER_PID" 2>/dev/null
kill "$TIMER_PID" 2>/dev/null

if [[ -f "$OUTPUT" ]]; then
    size=$(du -h "$OUTPUT" | cut -f1)
    lines=$(wc -l <"$OUTPUT" | tr -d ' ')
    log "finished - $OUTPUT ($size, $lines lines)"
    if [[ "$lines" -lt 100 ]]; then
        log "WARNING: very few lines captured; the feed may not have been live"
    fi
else
    log "FAILED - no output file was written"
fi
