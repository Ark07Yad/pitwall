#!/usr/bin/env bash
#
# Run the live engine for a race, unattended.
#
# One process, one connection to F1's endpoint: it records the raw frames,
# folds them into race state, fits the models, publishes a call every lap, and
# commits each call to the prediction ledger as it is made.
#
#   scripts/race_day.sh "2026-08-23 13:45" 2026-netherlands-race "2026 Dutch GP" LEC 195
#
# Arguments: start time (local), recording basename, ledger session name, the
# TLA to advise (blank = the leader), and minutes to run.
#
# Deliberately NOT run alongside scripts/record.py. That would open a second
# connection to an undocumented endpoint from one address, which is exactly the
# behaviour this project's disclaimer promises to avoid. This records too.
#
# Leave the machine plugged in, on wi-fi, and with the LID OPEN. macOS sleeps on
# lid close no matter what `caffeinate` says, and a sleeping Mac records nothing.

set -uo pipefail

START_AT="${1:?usage: race_day.sh \"YYYY-MM-DD HH:MM\" BASENAME SESSION [TLA] [MINUTES]}"
BASENAME="${2:?missing recording basename}"
SESSION="${3:?missing ledger session name}"
DRIVER="${4:-}"
MINUTES="${5:-195}"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${REPO}/data/raw/${BASENAME}.txt"
LOG="${REPO}/data/raw/${BASENAME}-engine.log"
mkdir -p "$(dirname "$OUTPUT")"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

target_epoch=$(date -j -f "%Y-%m-%d %H:%M" "$START_AT" +%s 2>/dev/null) || {
    echo "could not parse start time: '$START_AT' (expected \"YYYY-MM-DD HH:MM\")" >&2
    exit 1
}

# Fail before the wait, not after it. A dirty tree does not break the ledger -
# each prediction is committed with `--only`, staging just the log file - but a
# detached HEAD or a missing identity means every commit fails silently for two
# hours and the timestamps that are the whole point are lost.
if ! git -C "$REPO" rev-parse --abbrev-ref HEAD >/dev/null 2>&1; then
    echo "not a git repository: $REPO" >&2
    exit 1
fi
if [[ "$(git -C "$REPO" rev-parse --abbrev-ref HEAD)" == "HEAD" ]]; then
    echo "detached HEAD - check out a branch so prediction commits land somewhere" >&2
    exit 1
fi
if ! git -C "$REPO" config user.email >/dev/null; then
    echo "git user.email is unset - every prediction commit would fail" >&2
    exit 1
fi

now_epoch=$(date +%s)
wait_seconds=$(( target_epoch - now_epoch ))
if (( wait_seconds < 0 )); then
    log "start time is $(( -wait_seconds / 60 )) min in the past - starting now"
    wait_seconds=0
fi

caffeinate -ims -w $$ &
CAFFEINATE_PID=$!

cleanup() {
    log "shutting down"
    [[ -n "${ENGINE_PID:-}" ]] && kill "$ENGINE_PID" 2>/dev/null
    kill "$CAFFEINATE_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

log "target    : $START_AT (in $(( wait_seconds / 60 )) min)"
log "recording : $OUTPUT"
log "ledger    : $SESSION"
log "advising  : ${DRIVER:-the leader}"
log "duration  : ${MINUTES} min"
log "dashboard : http://127.0.0.1:8000"

# Poll the clock rather than one long sleep: a single `sleep` is suspended if
# the machine ever naps, so it fires late by however long the nap lasted.
while (( $(date +%s) < target_epoch )); do
    remaining=$(( target_epoch - $(date +%s) ))
    if (( remaining > 60 )); then sleep 60; else sleep "$remaining"; fi
done

log "starting the engine"
"${REPO}/.venv/bin/pitwall" dashboard \
    --record "$OUTPUT" \
    --log-predictions \
    --session "$SESSION" \
    --driver "$DRIVER" \
    >>"$LOG" 2>&1 &
ENGINE_PID=$!

( sleep $(( MINUTES * 60 )); kill -TERM "$ENGINE_PID" 2>/dev/null ) &
TIMER_PID=$!

wait "$ENGINE_PID" 2>/dev/null
kill "$TIMER_PID" 2>/dev/null

if [[ -f "$OUTPUT" ]]; then
    size=$(du -h "$OUTPUT" | cut -f1)
    lines=$(wc -l <"$OUTPUT" | tr -d ' ')
    log "recording finished - $OUTPUT ($size, $lines lines)"
    (( lines < 100 )) && log "WARNING: very few lines; the feed may not have been live"
fi

slug=$(printf '%s' "$SESSION" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]\{1,\}/-/g; s/^-//; s/-$//')
ledger="${REPO}/predictions/${slug}.jsonl"
if [[ -f "$ledger" ]]; then
    log "ledger finished - $ledger ($(wc -l <"$ledger" | tr -d ' ') calls)"
    log "committed: $(git -C "$REPO" rev-list --count HEAD -- "$ledger") commits touch it"
else
    log "WARNING: no ledger written at $ledger"
fi
