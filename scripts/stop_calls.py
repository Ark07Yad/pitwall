#!/usr/bin/env python3
"""When the engine said "stop soon", did the team?

The ledger's scores grade a *forecast*: how likely each car was to finish in the
top three or the points. That is the thing a recording can settle, and it is not
what the engine is for. The engine is for the call, and a call has no
counterfactual - nobody ran the race both ways.

What can be checked is agreement with the people who do this for a living. A
team's stop is not ground truth, but twenty-two cars' worth of them is the best
evidence there is of when stopping was reasonable.

    python scripts/stop_calls.py predictions/2026-azerbaijan-gp.jsonl:data/raw/2026-baku-race.txt

Each argument is `ledger:recording`. Several may be given and are pooled.

**Only the imminent call is scored.** The engine names a stop at most ten laps
ahead and decides again every lap, so "lap +10" is "not yet" rather than a
forecast of the stop lap. Scoring the named lap against the real one builds in a
bias - at lap 10 the furthest it can say is lap 20, whatever the team does at 30.
What it can be held to is "stop now or within `--window` laps", against whether
the car then did.

**Decisive calls are reported separately**, and they are the number to read. A
row whose best option leads the next by two hundredths of a place is the engine
saying it does not know, and the dashboard prints it as "no clear call".

First used on 5 October 2026, to decide whether to let the engine speak while a
field is still on its first stint by holding the race-lap trend with a prior.
On laps it already spoke on, a decisive "stop within three laps" was followed by
the team doing so 44% of the time. On the laps the prior would have opened, 10%.
It was not switched on.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from pitwall.feed.replay import read_events
from pitwall.laps import LapCollector

BANDS = ("first quarter", "second quarter", "after half")


def band_for(lap: int, total: int) -> str:
    fraction = lap / total if total else 0.0
    if fraction < 0.25:
        return BANDS[0]
    return BANDS[1] if fraction < 0.5 else BANDS[2]


def pit_laps(recording: Path) -> dict[str, list[int]]:
    """Race laps on which each driver entered the pits."""
    collector = LapCollector()
    for event in read_events(recording):
        collector.apply(event)
    stops: dict[str, list[int]] = defaultdict(list)
    for lap in collector.laps:
        if lap.entered_pit:
            stops[lap.driver].append(lap.lap)
    return stops


def tally(pairs: list[tuple[Path, Path]], window: int, decisive_only: bool) -> dict[str, list[int]]:
    """Per race phase: [said and did, said and did not, did and not said, neither]."""
    counts: dict[str, list[int]] = {band: [0, 0, 0, 0] for band in BANDS}
    for ledger, recording in pairs:
        stops = pit_laps(recording)
        for line in ledger.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if decisive_only and not row.get("decisive"):
                continue
            lap = int(row["lap"])
            said = bool(row.get("stop")) and int(row.get("pit_lap") or 0) - lap <= window
            did = any(lap <= stop <= lap + window for stop in stops[str(row["driver"])])
            cell = 0 if said and did else 1 if said else 2 if did else 3
            counts[band_for(lap, int(row.get("total_laps") or 0))][cell] += 1
    return counts


def show(title: str, counts: dict[str, list[int]]) -> None:
    print(f"\n{title}")
    print(
        f"  {'when':<15}{'rows':>6}{'said stop soon':>16}{'team then did':>18}"
        f"{'team stopped soon':>20}{'engine had said so':>20}"
    )
    total = [0, 0, 0, 0]
    for band in (*BANDS, "all"):
        cells = total if band == "all" else counts[band]
        if band != "all":
            total = [a + b for a, b in zip(total, cells, strict=True)]
        said_did, said_not, did_not_said, neither = cells
        said, did = said_did + said_not, said_did + did_not_said
        if not sum(cells):
            continue
        right = f"{said_did}/{said} ({100 * said_did / said:.0f}%)" if said else "-"
        caught = f"{said_did}/{did} ({100 * said_did / did:.0f}%)" if did else "-"
        print(f"  {band:<15}{sum(cells):>6}{said:>16}{right:>18}{did:>20}{caught:>20}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pairs", nargs="+", help="ledger.jsonl:recording.txt")
    parser.add_argument(
        "--window", type=int, default=3, help="laps that count as 'soon' (default 3)"
    )
    args = parser.parse_args()

    pairs: list[tuple[Path, Path]] = []
    for text in args.pairs:
        ledger, _, recording = text.partition(":")
        if not recording:
            print(f"expected ledger:recording, got {text!r}", file=sys.stderr)
            return 1
        pairs.append((Path(ledger), Path(recording)))
    missing = [str(p) for pair in pairs for p in pair if not p.exists()]
    if missing:
        print("no such file: " + ", ".join(missing), file=sys.stderr)
        return 1

    print(f"{len(pairs)} race(s); 'soon' is within {args.window} laps")
    show("decisive calls only - the number to read", tally(pairs, args.window, True))
    show("every row, including 'no clear call'", tally(pairs, args.window, False))
    print(
        "\n  A team's stop is not ground truth, and agreement is not correctness: the\n"
        "  engine may be right where a team was not. Read differences between two sets\n"
        "  of calls scored the same way, not the absolute level."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
