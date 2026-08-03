#!/usr/bin/env python3
"""Download historical safety-car incidence for the hazard model.

No public dataset gives per-circuit safety-car rates, so this builds one. For
every race in a season range it records which laps ran under a safety car, a
virtual safety car or a red flag, and which lap each of those periods *started* -
the starts are what a hazard model is fitted on.

    python scripts/fetch_history.py --from 2022 --to 2026

**The F1 API allows 500 calls an hour and each race costs several.** A full
five-season fetch will not finish in one run. This script is therefore resumable:
it loads whatever it collected before, skips those races, and stops cleanly the
moment it is rate limited. Re-run it an hour later and it picks up where it left
off. Cached races cost nothing on a re-run.

Output: data/history/safety_car.json
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")
logging.getLogger("fastf1").setLevel(logging.ERROR)

import fastf1  # noqa: E402

# FastF1 concatenates every status seen during a lap into one string, so lap
# "1254" ran through green, yellow, red and safety car.
SAFETY_CAR = "4"
VIRTUAL_SAFETY_CAR = "6"
RED_FLAG = "5"


def is_rate_limit(exc: Exception) -> bool:
    """Detect FastF1's rate-limit error without importing its private paths."""
    return type(exc).__name__ == "RateLimitExceededError" or "calls/h" in str(exc)


def laps_with(status: str, by_lap: dict[int, str]) -> list[int]:
    return sorted(lap for lap, codes in by_lap.items() if status in codes)


def starts(active: list[int]) -> list[int]:
    """Reduce a run of active laps to the lap each period began on.

    A ten-lap safety car is one event for hazard purposes, not ten.
    """
    return [lap for lap in active if lap - 1 not in active]


def retirements(session, laps) -> tuple[int, list[int]]:
    """Starters, and the lap each retiring car stopped on.

    `ClassifiedPosition` is "R" for a retirement; "Lapped" cars are classified
    and finished the race, so they are emphatically not attrition. The lap is
    the last one the car completed, which is what a hazard model needs - a
    retirement on lap 50 is a different event from one on lap 2.
    """
    results = getattr(session, "results", None)
    if results is None or results.empty:
        return 0, []

    out: list[int] = []
    for _, row in results.iterrows():
        classified = str(row.get("ClassifiedPosition", "")).strip().upper()
        if classified != "R":
            continue
        driver = str(row.get("Abbreviation", ""))
        theirs = laps[laps["Driver"] == driver]
        last = int(theirs["LapNumber"].max()) if not theirs.empty else 0
        out.append(max(1, last))
    return int(len(results)), sorted(out)


def collect_race(season: int, rnd: int) -> dict[str, Any] | None:
    session = fastf1.get_session(season, rnd, "R")
    session.load(telemetry=False, weather=False, messages=False)

    laps = session.laps
    if laps is None or laps.empty:
        return None

    # A status counts for a lap if any car saw it - a safety car does not care
    # which driver you are.
    by_lap: dict[int, str] = {}
    for lap_number, codes in zip(laps["LapNumber"], laps["TrackStatus"], strict=False):
        if lap_number != lap_number:  # NaN
            continue
        key = int(lap_number)
        by_lap[key] = by_lap.get(key, "") + str(codes or "")

    if not by_lap:
        return None

    starters, retired = retirements(session, laps)
    sc = laps_with(SAFETY_CAR, by_lap)
    vsc = laps_with(VIRTUAL_SAFETY_CAR, by_lap)
    red = laps_with(RED_FLAG, by_lap)
    event = session.event

    return {
        "season": season,
        "round": rnd,
        "event": str(event.get("EventName", "")),
        "circuit": str(event.get("Location", "")),
        "total_laps": max(by_lap),
        "sc_laps": sc,
        "vsc_laps": vsc,
        "red_laps": red,
        "starters": starters,
        "retirements": retired,
        "sc_starts": starts(sc),
        "vsc_starts": starts(vsc),
        "red_starts": starts(red),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=int, default=2022)
    parser.add_argument("--to", dest="end", type=int, default=2026)
    parser.add_argument("--cache", type=Path, default=Path("cache"))
    parser.add_argument("--out", type=Path, default=Path("data/history/safety_car.json"))
    args = parser.parse_args()

    args.cache.mkdir(parents=True, exist_ok=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(args.cache))

    races: list[dict[str, Any]] = []
    if args.out.exists():
        races = json.loads(args.out.read_text(encoding="utf-8"))
        print(f"resuming from {args.out} with {len(races)} races already collected", flush=True)
    # Only skip races that already carry every field. Adding a new one to the
    # schema means the old rows are incomplete, and silently keeping them would
    # fit the model on a subset while reporting the full count.
    have = {(r["season"], r["round"]) for r in races if "retirements" in r and "starters" in r}
    stale = len(races) - len(have)
    if stale:
        print(f"{stale} races predate the current schema and will be re-collected", flush=True)
        races = [r for r in races if (r["season"], r["round"]) in have]

    def save() -> None:
        races.sort(key=lambda r: (r["season"], r["round"]))
        args.out.write_text(json.dumps(races, indent=2), encoding="utf-8")

    rate_limited = False
    for season in range(args.start, args.end + 1):
        if rate_limited:
            break
        try:
            schedule = fastf1.get_event_schedule(season, include_testing=False)
        except Exception as exc:
            if is_rate_limit(exc):
                rate_limited = True
                break
            print(f"[{season}] schedule unavailable: {exc}", flush=True)
            continue

        for rnd in schedule["RoundNumber"]:
            rnd = int(rnd)
            if (season, rnd) in have:
                continue
            try:
                race = collect_race(season, rnd)
            except Exception as exc:
                if is_rate_limit(exc):
                    # Stop immediately rather than burning the rest of the
                    # schedule on calls that cannot succeed.
                    rate_limited = True
                    break
                # Rounds that have not happened yet also raise here; that is
                # expected mid-season and is not worth a stack trace.
                print(f"[{season} r{rnd:>2}] skipped ({type(exc).__name__})", flush=True)
                continue
            if race is None:
                continue
            races.append(race)
            have.add((season, rnd))
            # Save as we go: a rate limit or a crash should never cost work
            # already paid for in API calls.
            save()
            print(
                f"[{season} r{rnd:>2}] {race['circuit']:<22} "
                f"{race['total_laps']:>3} laps  "
                f"SC={len(race['sc_starts'])} VSC={len(race['vsc_starts'])} "
                f"RED={len(race['red_starts'])} DNF={len(race['retirements'])}/{race['starters']}",
                flush=True,
            )

    save()
    sc_total = sum(len(r["sc_starts"]) for r in races)
    vsc_total = sum(len(r["vsc_starts"]) for r in races)
    seasons = sorted({r["season"] for r in races})
    print(
        f"\nwrote {args.out}: {len(races)} races "
        f"({seasons[0]}-{seasons[-1]} covered), "
        f"{sc_total} safety cars, {vsc_total} VSCs",
        flush=True,
    )
    if rate_limited:
        print(
            "\nstopped early: the F1 API allows 500 calls an hour.\n"
            "re-run this exact command in an hour and it will resume from here.",
            flush=True,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
