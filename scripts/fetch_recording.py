#!/usr/bin/env python3
"""Rebuild a replayable recording of a past race from F1's live-timing archive.

The live path records raw SignalR frames as a race happens. Miss the race and
that capture cannot be made again — but the *data* is not lost. F1 keeps the same
per-topic streams the socket pushed at
`livetiming.formula1.com/static/<year>/<event>/<session>/`, FastF1 already knows
how to fetch them, and `feed/replay.py` already reads FastF1's `[topic, data,
timestamp]` line format alongside the raw one. This joins those three facts.

    python scripts/fetch_recording.py 2026 13 --out data/raw/2026-italy-race.txt

**This is not a substitute for recording the race.** The file contains the whole
session including the result, so any call made from it is post-hoc by
construction — `backtest` stamps every row `backtest of <file>`, and the ledger
refuses to commit from a replay. What it cannot do is restore a track record: the
value of a live ledger is the commit timestamp proving the call preceded the
outcome, and nothing rebuilt afterwards can carry that.

What it *is* good for is analysis, and it changes the scale of what is possible.
Backtests used to be limited to races that happened to be recorded — two of them.
Every race in the archive is now available, which is the difference between
"here is a model that worked on my two recordings" and a corpus.

**Checked against races that were recorded.** Zandvoort and Hungary exist both as
live captures and in the archive. Rebuilt, both fold to the same circuit, lap
count, track status and — across all 22 cars — the same final classification. A
backtest at six laps for four drivers produced **24 of 24 identical calls**, with
expected positions agreeing to two decimals. The reconstruction is not an
approximation of a capture; it is the same race arriving by a different route.

**What is deliberately not fetched.** `Position.z` and `CarData.z` are the big
streams and are compressed telemetry the reducer never reads; pulling them would
multiply the file size for nothing. The result is smaller than a live capture
(7.3 MB against 13.7 MB for Zandvoort) and carries every topic that reaches race
state.
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.getLogger("fastf1").setLevel(logging.ERROR)

import fastf1  # noqa: E402
from fastf1 import _api  # noqa: E402

# FastF1's stream key -> the topic name the live feed sends, which is what the
# reducer dispatches on. Getting this mapping wrong produces a file that folds to
# an empty race rather than an error, so it is written out rather than derived.
TOPICS: dict[str, str] = {
    "session_info": "SessionInfo",
    "driver_list": "DriverList",
    "lap_count": "LapCount",
    "track_status": "TrackStatus",
    "session_status": "SessionStatus",
    "timing_data": "TimingData",
    "timing_app_data": "TimingAppData",
    "timing_stats": "TimingStats",
    "race_control_messages": "RaceControlMessages",
    "weather_data": "WeatherData",
    "extrapolated_clock": "ExtrapolatedClock",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("season", type=int)
    parser.add_argument("round", type=int)
    parser.add_argument("--session", default="R", help="R, Q, FP1, FP2, FP3")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", default="cache")
    args = parser.parse_args()

    fastf1.Cache.enable_cache(args.cache)
    try:
        session = fastf1.get_session(args.season, args.round, args.session)
        session.load(telemetry=False, weather=False, messages=False, laps=False)
    except Exception as exc:  # noqa: BLE001
        print(f"could not load {args.season} r{args.round} {args.session}: {exc}", file=sys.stderr)
        return 1

    print(f"{session.event['EventName']} — {args.session}")
    print(f"  archive: {session.api_path}")

    rows: list[tuple[str, str, object]] = []
    missing: list[str] = []
    for key, topic in TOPICS.items():
        try:
            page = _api.fetch_page(session.api_path, key)
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{topic} ({type(exc).__name__})")
            continue
        if not page:
            missing.append(f"{topic} (empty)")
            continue
        for entry in page:
            # Streams are [timestamp, data]; a malformed line is skipped rather
            # than allowed to shift every later event's ordering.
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                continue
            timestamp, data = entry
            rows.append((str(timestamp), topic, data))
        print(f"  {topic:<22}{len(page):>7} entries")

    if missing:
        print(f"  not available: {', '.join(missing)}")
    if not rows:
        print("nothing fetched; the archive may not have this session yet", file=sys.stderr)
        return 1

    # Sorted by session timestamp, because the reducer is order-dependent: a
    # stint announced after the lap it covers leaves a car on an unknown
    # compound. The streams arrive per topic, so this is the step that turns
    # them back into one chronological feed.
    rows.sort(key=lambda r: r[0])

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for timestamp, topic, data in rows:
            handle.write(repr([topic, data, timestamp]) + "\n")

    size = args.out.stat().st_size
    print(f"\nwrote {len(rows):,} events, {size / 1e6:.1f} MB -> {args.out}")
    print("Rebuilt from the archive, so it already contains the result:")
    print("  backtest against it — never a live ledger.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
