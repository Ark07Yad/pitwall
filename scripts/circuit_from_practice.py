#!/usr/bin/env python3
"""Read a circuit's tyre picture off practice long runs, and say what it is worth.

For a circuit with no racing history every per-circuit model falls back to the
field average, and practice is the only source of laps on that surface before
the race. Round 16 of 2026 is exactly that case: the Bahrain Grand Prix, held at
Kuala Lumpur, a circuit with nothing in a 2022-2026 history.

    python scripts/circuit_from_practice.py data/raw/2026-r16-fp2.txt
    python scripts/circuit_from_practice.py data/raw/2026-r16-fp2.txt --calibrate

**The first version of this script asked `fit_pace` and got nothing**, correctly:
that fit reads the race-lap number as a proxy for fuel load, and practice resets
fuel between runs, so a low-fuel qualifying simulation sitting between two long
runs makes lap number meaningless. Against the 2026 Spanish GP it returned trends
of +0.71 and +1.54 s/lap and refused both sessions.

It now asks `fit_long_runs`, which fits what practice can support - long runs
only, fuel subtracted at the published sensitivity rather than estimated, an
intercept per run, no race-lap term. That returns a number at Kuala Lumpur where
the old path returned nothing.

**And `--calibrate` is why the number is still not written anywhere.** Run
against four circuits whose factor *is* fitted from races, the practice estimate
overstated them by between 1.6x and 12x, and the median of that ratio moves from
4.6x to 8.0x depending on where the long-run cutoff is put. A conversion factor
that moves with an arbitrary threshold on three or four points is not a
conversion factor. What survives every variant is the *direction*: Kuala Lumpur
reads 0.6-0.9x of the field average, so this is a mid-to-low degradation circuit
and not a Sakhir. Carry that as an expectation, not as a number in the model.
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

from pitwall.feed.replay import read_events
from pitwall.laps import LapCollector, filter_laps
from pitwall.models import (
    fit_degradation,
    fit_long_runs,
    load_degradation,
    load_history,
    neutralisation_index,
    normalise_circuit,
)
from pitwall.models.long_run import MIN_RUN_LAPS


def fold(path: Path) -> tuple[str, str, list, object]:
    collector = LapCollector()
    for event in read_events(path):
        collector.apply(event)
    clean, report = filter_laps(collector.laps)
    state = collector.state
    return state.circuit or "?", state.session_name or "session", clean, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="a recorded practice session")
    parser.add_argument(
        "--degradation-history", type=Path, default=Path("data/history/degradation.json")
    )
    parser.add_argument("--history", type=Path, default=Path("data/history/safety_car.json"))
    parser.add_argument("--min-run-laps", type=int, default=MIN_RUN_LAPS)
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="score this estimator against every other practice recording whose "
        "circuit has a race-fitted factor, and report the ratio",
    )
    parser.add_argument(
        "--practice-glob",
        default="data/raw/*-fp[12].txt",
        help="where --calibrate looks for other practice recordings",
    )
    args = parser.parse_args()

    if not args.file.exists():
        print(f"no such recording: {args.file}", file=sys.stderr)
        return 1
    if not args.degradation_history.exists():
        print("no pooled prior to scale against; build it first", file=sys.stderr)
        return 1

    prior = fit_degradation(
        load_degradation(args.degradation_history),
        history=neutralisation_index(load_history(args.history)) if args.history.exists() else None,
    )

    circuit, session, clean, report = fold(args.file)
    print(f"{session} @ {circuit}")
    print(report)
    if not clean:
        print("\nno clean laps survived the filter; nothing to fit", file=sys.stderr)
        return 1

    fit = fit_long_runs(clean, min_run_laps=args.min_run_laps)
    if fit is None:
        print(
            f"\nfewer than two runs of {args.min_run_laps}+ clean laps; nothing to fit.\n"
            "A wet or red-flagged session is mostly three-lap runs, and a slope "
            "through those is noise.",
            file=sys.stderr,
        )
        return 1

    print(f"\n{fit}")
    factor, ratios = fit.factor_against(prior)
    if factor is None:
        print("\nno compound could be compared against the pooled shape")
        return 1

    print("\n  against the pooled shape:\n")
    print(f"  {'compound':<10}{'here':>12}{'pooled':>12}{'ratio':>9}{'laps':>7}")
    for compound, ratio, n in sorted(ratios, key=lambda r: r[0].short):
        print(
            f"  {compound.short:<10}{fit.degradation[compound]:>+11.4f}"
            f"{prior.linear[compound]:>+12.4f}{ratio:>9.2f}{n:>7}"
        )

    key = normalise_circuit(circuit)
    current = prior.circuit_factor.get(key)
    in_model = "unfitted, uses 1.00x" if current is None else f"{current:.2f}x"
    if current is not None and key != circuit:
        in_model += f"  (as {key})"
    print(f"\n  lap-weighted practice factor: {factor:.2f}x   on {fit.n_laps} laps")
    print(f"  currently in the model:       {in_model}")

    if not args.calibrate:
        print(
            "\n  A practice factor is not a race factor. Run --calibrate to see by how\n"
            "  much this estimator overstates circuits whose factor is known."
        )
        return 0

    print("\n  --- calibration against circuits with a race-fitted factor ---\n")
    scored: list[tuple[str, float, float]] = []
    for other in sorted(Path().glob(args.practice_glob)):
        if other.resolve() == args.file.resolve():
            continue
        other_circuit, _, other_clean, _ = fold(other)
        other_key = normalise_circuit(other_circuit)
        race_factor = prior.circuit_factor.get(other_key)
        if not race_factor:
            continue
        other_fit = fit_long_runs(other_clean, min_run_laps=args.min_run_laps)
        if other_fit is None:
            print(f"  {other_circuit:<20} no runs that long")
            continue
        other_factor, _ = other_fit.factor_against(prior)
        if other_factor is None:
            continue
        scored.append((other_circuit, other_factor, race_factor))
        flag = "" if other_fit.usable else "   (fit refused)"
        print(
            f"  {other_circuit:<20} practice {other_factor:>6.2f}x   race {race_factor:>5.2f}x"
            f"   ratio {other_factor / race_factor:>6.2f}x{flag}"
        )

    if len(scored) < 2:
        print("\n  too few calibration circuits to say anything")
        return 0

    found = [p / r for _, p, r in scored]
    median = statistics.median(found)
    print(
        f"\n  ratio: median {median:.2f}x, spread {min(found):.2f}-{max(found):.2f}"
        f" ({max(found) / min(found):.1f}-fold across {len(found)} circuits)"
    )
    print(
        f"  {circuit} at that median would be {factor / median:.2f}x,"
        f" and across the spread {factor / max(found):.2f}-{factor / min(found):.2f}x"
    )
    print(
        "\n  Read the spread, not the median. A conversion that varies several-fold\n"
        "  across circuits - and whose median moves with the long-run cutoff - cannot\n"
        "  set a factor. The direction is the usable part: whether this circuit reads\n"
        "  above or below the others measured the same way.\n"
        "\n  Nothing is written to degradation.json. Folding one Friday into a\n"
        "  five-season pool is a judgement call for whoever reads this."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
