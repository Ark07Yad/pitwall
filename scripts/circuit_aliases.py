#!/usr/bin/env python3
"""Derive the circuit alias table from F1's own session info.

These models are fitted on FastF1's `Location` but queried at runtime with the
name the live feed sends, `Meeting.Circuit.ShortName`. Where the two disagree
the lookup misses and the per-circuit estimate silently falls back to neutral.
Nine of twenty-seven circuits disagree, so this is not an edge case.

The mapping must never be written from memory - a wrong entry maps one circuit's
history onto another and nothing errors. F1's session info carries both spellings
for every race, so this reads them out of the cache and prints the pairs that
differ, ready to paste into `CIRCUIT_ALIASES` in `models/safety_car.py`.

    python scripts/circuit_aliases.py --from 2022 --to 2026

Re-run it whenever a season is added. `Circuit.Key` is printed alongside because
it is the only genuinely stable identity here: if two spellings share a key they
are the same track, whatever either side calls it.
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings

warnings.filterwarnings("ignore")
logging.getLogger("fastf1").setLevel(logging.ERROR)

import fastf1  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=int, default=2022)
    parser.add_argument("--to", dest="end", type=int, default=2026)
    parser.add_argument("--cache", default="cache")
    args = parser.parse_args()

    fastf1.Cache.enable_cache(args.cache)

    seen: dict[tuple[str, str, int], list[int]] = {}
    for year in range(args.start, args.end + 1):
        try:
            schedule = fastf1.get_event_schedule(year, include_testing=False)
        except Exception as exc:  # noqa: BLE001
            print(f"{year}: could not load schedule ({type(exc).__name__})")
            continue
        for _, event in schedule.iterrows():
            try:
                session = fastf1.get_session(year, int(event["RoundNumber"]), "R")
                session.load(telemetry=False, weather=False, messages=False, laps=False)
                meeting = session.session_info["Meeting"]
                key = (
                    meeting["Circuit"]["ShortName"],
                    meeting["Location"],
                    int(meeting["Circuit"]["Key"]),
                )
            except Exception:  # noqa: BLE001, S112
                continue
            seen.setdefault(key, []).append(year)

    if not seen:
        print("no session info available - is the cache populated?")
        return 1

    print(f"{'ShortName (live feed)':<26} {'Location (history)':<22} {'key':<5} years")
    for (short, location, key), years in sorted(seen.items()):
        flag = "" if short == location else "   <-- differs"
        print(f"{short:<26} {location:<22} {key:<5} {min(years)}-{max(years)}{flag}")

    aliases = {short: loc for (short, loc, _) in seen if short != loc}
    print(f"\n{len(aliases)} of {len(seen)} differ\n")
    print("CIRCUIT_ALIASES entries (ShortName -> Location):")
    print(json.dumps(aliases, indent=4, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
