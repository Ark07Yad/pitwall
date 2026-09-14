#!/usr/bin/env python3
"""Find the lap from which the pace fit stays usable, in past races at a circuit.

The engine can only make a decision on a lap where two things are true at once:
the pace fit is usable, and a stop can still pay for itself before the flag. At
Monza the first came at lap 32 and the second ended at lap 22, so all 110 calls
were "stay out" by arithmetic. Nothing noticed. This measures the first half
before a race rather than after it:

    python scripts/fetch_recording.py 2025 17 --out data/raw/2025-baku-archive.txt
    python scripts/window_sweep.py data/raw/202*-baku-archive.txt

and the break-even for the second half comes from the runbook's per-circuit
numbers.

**Stable, not first.** A fit can be usable at one lap and refuse at the next -
at Madring it was usable at lap 12, refused 13-16, and usable from 17. A call
cannot be relied on at 12, so the number reported is the lap after the last
refusal in the sweep, and the first usable lap is shown beside it.

**One fold per recording.** `fold_to_lap` re-reads the file for every lap, which
is minutes per lap on a full race. This reads it once and fits at each lap
boundary, taking the state for lap L at the moment the feed's lap counter first
exceeds L - the same point `fold_to_lap` stops at. Checked against it at Madring
laps 12, 13, 16 and 17: identical.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pitwall.feed.replay import read_events
from pitwall.laps import LapCollector, filter_laps
from pitwall.models import (
    fit_degradation,
    fit_pace,
    load_degradation,
    load_history,
    neutralisation_index,
)


def sweep(path: Path, prior: object, first: int, last: int) -> dict[str, object]:
    collector = LapCollector()
    seen: set[int] = set()
    usable: list[int] = []
    refused: dict[int, str] = {}

    for event in read_events(path):
        collector.apply(event)
        lap = collector.state.lap - 1
        if lap > last:
            break
        if lap < first or lap in seen:
            continue
        seen.add(lap)
        clean, _ = filter_laps(collector.laps)
        pace = fit_pace(clean, prior=prior, circuit=collector.state.circuit)
        if pace is not None and pace.usable:
            usable.append(lap)
        else:
            refused[lap] = "no fit" if pace is None else pace.unusable_reasons[0]

    stable = None
    if seen:
        last_refused = max(refused) if refused else first - 1
        stable = last_refused + 1 if last_refused < max(seen) else None
    return {
        "circuit": collector.state.circuit,
        "total_laps": collector.state.total_laps,
        "first_usable": min(usable) if usable else None,
        "stable_from": stable,
        "usable": usable,
        "refused": refused,
        "checked": sorted(seen),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", type=Path, nargs="+")
    parser.add_argument("--first", type=int, default=8, help="first lap to check")
    parser.add_argument("--last", type=int, default=40, help="last lap to check")
    parser.add_argument("--history", type=Path, default=Path("data/history/safety_car.json"))
    parser.add_argument(
        "--degradation-history", type=Path, default=Path("data/history/degradation.json")
    )
    args = parser.parse_args()

    missing = [p for p in args.recordings if not p.exists()]
    if missing:
        print("no such recording: " + ", ".join(str(p) for p in missing), file=sys.stderr)
        return 1

    history = load_history(args.history)
    prior = fit_degradation(
        load_degradation(args.degradation_history), history=neutralisation_index(history)
    )

    for path in args.recordings:
        result = sweep(path, prior, args.first, args.last)
        refused = result["refused"]
        print(f"\n{path.name}: {result['circuit']}, {result['total_laps']} laps")
        print(
            f"  stable from lap {result['stable_from']}   "
            f"(first usable {result['first_usable']}, "
            f"{len(result['usable'])} of {len(result['checked'])} laps usable)"
        )
        stable = result["stable_from"]
        for lap, reason in sorted(refused.items()):
            if stable is None or lap < stable:
                print(f"    lap {lap:>2} refused: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
