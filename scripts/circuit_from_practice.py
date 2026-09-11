#!/usr/bin/env python3
"""Estimate a circuit's degradation scale from a practice recording.

For a circuit that has never been raced there is no history to fit, and every
per-circuit model falls back to the field average. Practice is the only source of
laps on that surface before the race, and long runs in FP2 are how a real team
builds its tyre picture at a new track.

    python scripts/circuit_from_practice.py data/raw/2026-madrid-fp2.txt

**What this recovers, as tested - which is less than it first claimed.** Three of
the four per-circuit models were never obtainable from practice: stops there are
not racing stops, and a safety-car or attrition rate needs races rather than
laps. The fourth, degradation, is the reason this script exists, and on the one
real test it has had it produced nothing.

Madrid, 11 September 2026: FP1 and FP2 both refused. Race-lap trends of +0.71
and +1.54 s/lap, residual spreads of 10.2 and 6.4 seconds, r-squared of 0.21 and
0.37, and 146-174 laps excluded as implausible for a racing lap. The cause is the
premise, not the data. The decomposition reads race lap as a proxy for fuel burn,
and in practice fuel is reset between runs - a low-fuel qualifying simulation
sits between two high-fuel long runs - so lap number carries no fuel information.
The first version of this docstring said the number would "read low" and should be
treated "as a lower bound". It had only ever been run against a race recording,
where the premise holds.

**What would work instead, and is not built:** fuel-corrected long-run analysis,
the way teams read practice. Keep only long runs, correct each lap by the physics
fuel prior for laps into the stint, give every stint its own intercept, and fit
the per-compound slope within stints. No race-lap term, because there is no race.

**Nothing is written into `degradation.json`.** If a fit ever does come back
usable it prints a factor and what it rests on; folding one practice session into
a five-season pool is a judgement call for whoever reads it.
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
    normalise_circuit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="a recorded practice session")
    parser.add_argument(
        "--degradation-history", type=Path, default=Path("data/history/degradation.json")
    )
    parser.add_argument("--history", type=Path, default=Path("data/history/safety_car.json"))
    args = parser.parse_args()

    if not args.file.exists():
        print(f"no such recording: {args.file}", file=sys.stderr)
        return 1

    prior = None
    if args.degradation_history.exists():
        prior = fit_degradation(
            load_degradation(args.degradation_history),
            history=neutralisation_index(load_history(args.history))
            if args.history.exists()
            else None,
        )
    if prior is None:
        print("no pooled prior to scale against; build it first", file=sys.stderr)
        return 1

    collector = LapCollector()
    for event in read_events(args.file):
        collector.apply(event)
    state = collector.state
    circuit = state.circuit or "?"

    clean, report = filter_laps(collector.laps)
    print(f"{state.session_name or 'session'} @ {circuit}")
    print(report)
    if not clean:
        print("\nno clean laps survived the filter; nothing to fit", file=sys.stderr)
        return 1

    # Fitted with no prior, deliberately. Blending toward the pooled shape here
    # would make the answer partly the field average, and the field average is
    # exactly what this is trying to replace.
    pace = fit_pace(clean, prior=None, circuit=circuit)
    if pace is None:
        print("\nnot enough clean laps to fit a pace decomposition", file=sys.stderr)
        return 1

    print(f"\n{pace}")
    if not pace.usable:
        print("\nthe fit is not usable; the reasons above are the answer, not a number.")
        print("From practice this is the expected outcome: fuel is reset between runs, so")
        print("race lap is not a fuel proxy and the decomposition has nothing to stand on.")
        return 1

    print(f"\n  implied {circuit} degradation against the pooled shape:\n")
    print(f"  {'compound':<10}{'here':>12}{'pooled':>12}{'ratio':>9}{'laps':>7}")
    ratios: list[tuple[float, int]] = []
    for compound, rate in sorted(pace.degradation.items(), key=lambda kv: kv[0].short):
        pooled = prior.linear.get(compound)
        n = sum(1 for lap in clean if lap.compound is compound)
        if not pooled:
            print(f"  {compound.short:<10}{rate:>+11.4f}{'-':>12}{'-':>9}{n:>7}")
            continue
        ratio = rate / pooled
        ratios.append((ratio, n))
        print(f"  {compound.short:<10}{rate:>+11.4f}{pooled:>+12.4f}{ratio:>9.2f}{n:>7}")

    if not ratios:
        print("\nno compound could be compared against the pooled shape")
        return 1

    # Weighted by laps, because a compound seen on four laps should not carry the
    # same vote as one seen on forty.
    total = sum(n for _, n in ratios)
    factor = sum(r * n for r, n in ratios) / total
    # Through the alias table, not the raw feed name. The models are keyed on
    # FastF1's `Location` and the feed sends `Circuit.ShortName`; querying with
    # the wrong one returns the neutral default and reports a fitted circuit as
    # unfitted. Nine of twenty-seven circuits disagree.
    current = prior.circuit_factor.get(normalise_circuit(circuit))

    in_model = "unfitted, uses 1.00x" if current is None else f"{current:.2f}x"
    if current is not None and normalise_circuit(circuit) != circuit:
        in_model += f"  (as {normalise_circuit(circuit)})"
    print(f"\n  lap-weighted factor: {factor:.2f}x   on {total} clean laps")
    print(f"  currently in the model: {in_model}")
    print(
        "\n  Provisional, and not written to disk. Practice resets fuel between runs, so\n"
        "  the race-lap term this fit leans on means little here; a usable result from\n"
        "  practice is the exception, not the expected case."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
