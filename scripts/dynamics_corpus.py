#!/usr/bin/env python3
"""Do the measured passing and safety-car numbers change any calls?

The same question `prior_corpus.py` asked of the degradation prior, asked of the
two things that replaced hand-set numbers in November 2026: how hard it is to
pass at each circuit, and what a neutralisation does to a stop. Each recording
is folded once per decision lap and every call is made twice from that one
state - with the hand-set numbers the engine ran on until then, and with the
measured ones. Nothing else differs.

    python scripts/dynamics_corpus.py data/raw/2026-r1[0-4]-archive.txt ...

**Cars from across the field, not the front.** Passing decides most for cars
that are not leading: the leader has nobody to pass. `--every 3` takes P1, P4,
P7 and so on.

**And the noise floor.** `--noise` compares the hand-set numbers against
themselves with a different random seed. A call whose options are a few
hundredths apart flips on any perturbation at all, and a VSC draws random
numbers the old model did not, so some changes are the simulation's own noise.
That count is what the real comparison has to clear.

**Run the control.** `--control` adds a third run with passing switched off
entirely. If that changes nothing either, the harness cannot see this kind of
change and "no change" means nothing; if it changes a lot, a small number from
the real comparison is a finding.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

from pitwall.laps import filter_laps, fold_to_lap
from pitwall.models import (
    EventKind,
    fit_attrition,
    fit_degradation,
    fit_hazard,
    fit_neutralisation,
    fit_overtaking,
    fit_pace,
    fit_pit_loss,
    load_degradation,
    load_history,
    load_overtaking,
    load_pit_loss,
    load_stops,
    neutralisation_index,
)
from pitwall.sim import SimConfig, entries_from_state, evaluate_actions, tuned


def call_of(rec: Any) -> str:
    best = rec.best
    return (
        f"stay/{best.compound.short}"
        if not best.stop
        else f"pit+{best.delay}/{best.compound.short}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", nargs="+", type=Path)
    parser.add_argument("--fractions", default="0.40,0.55,0.70,0.85", help="of race distance")
    parser.add_argument("--every", type=int, default=3, help="advise every Nth car in the order")
    parser.add_argument("--sims", type=int, default=1500)
    parser.add_argument("--control", action="store_true", help="also run with passing switched off")
    parser.add_argument(
        "--noise",
        action="store_true",
        help="compare the hand-set numbers with themselves at another seed, instead",
    )
    parser.add_argument("--out", type=Path, default=Path("reports/dynamics-corpus.json"))
    args = parser.parse_args()

    history = load_history("data/history/safety_car.json")
    hazard = fit_hazard(history, kind=EventKind.ANY)
    attrition = fit_attrition(history)
    pit_loss = fit_pit_loss(load_pit_loss("data/history/pit_loss.json"))
    prior = fit_degradation(
        load_degradation("data/history/degradation.json"), history=neutralisation_index(history)
    )
    overtaking = fit_overtaking(load_overtaking("data/history/overtaking.json"))
    neutralisation = fit_neutralisation(load_stops("data/history/neutralised_stops.json"), history)
    base = SimConfig(n_sims=args.sims)
    fractions = [float(f) for f in args.fractions.split(",")]

    results: list[dict[str, Any]] = []
    for recording in args.recordings:
        if not recording.exists():
            print(f"{recording}: missing, skipping", file=sys.stderr)
            continue
        total = fold_to_lap(recording, 10**9).state.total_laps
        if not total:
            print(f"{recording.name}: no lap count, skipping", file=sys.stderr)
            continue
        for fraction in fractions:
            lap = max(1, int(total * fraction))
            collector = fold_to_lap(recording, lap)
            state = collector.state
            clean, _ = filter_laps(collector.laps)
            pace = fit_pace(clean, prior=prior, circuit=state.circuit, total_laps=state.total_laps)
            head = {
                "recording": recording.name,
                "circuit": state.circuit,
                "lap": lap,
                "total": total,
            }
            if pace is None or not pace.usable:
                results.append({**head, "skipped": "fit not usable"})
                print(f"  {recording.name:<28} lap {lap:>2}/{total}  fit not usable", flush=True)
                continue

            configs = {
                "hand-set": base,
                "measured": (
                    dataclasses.replace(base, seed=(base.seed or 0) + 1)
                    if args.noise
                    else tuned(
                        base, state.circuit, overtaking=overtaking, neutralisation=neutralisation
                    )
                ),
            }
            if args.control:
                configs["no passing"] = dataclasses.replace(
                    base, overtake_base=0.0, overtake_per_second=0.0
                )

            order = {c.number: c.position for c in state.running_order() if c.position is not None}
            entries = entries_from_state(state, pace)
            ranked = sorted(entries, key=lambda e: order.get(e.driver, 99))
            advised = ranked[:: args.every]
            calls: dict[str, dict[str, str]] = {name: {} for name in configs}
            for entry in advised:
                for name, config in configs.items():
                    rec = evaluate_actions(
                        entries,
                        our_driver=entry.driver,
                        from_lap=lap,
                        total_laps=total,
                        circuit=state.circuit,
                        pace=pace,
                        hazard=hazard,
                        attrition=attrition,
                        pit_loss=pit_loss,
                        config=config,
                    )
                    calls[name][entry.tla] = call_of(rec)

            changed = [t for t in calls["hand-set"] if calls["hand-set"][t] != calls["measured"][t]]
            row = {**head, "n": len(advised), "changed": changed, "calls": calls}
            if args.control:
                row["control_changed"] = [
                    t for t in calls["hand-set"] if calls["hand-set"][t] != calls["no passing"][t]
                ]
            results.append(row)
            mark = f"{len(changed)}/{len(advised)} changed"
            if args.control:
                mark += f"   control {len(row['control_changed'])}/{len(advised)}"
            print(f"  {recording.name:<28} lap {lap:>2}/{total}  {mark}", flush=True)
            for tla in changed:
                print(
                    f"      {tla}: {calls['hand-set'][tla]} -> {calls['measured'][tla]}", flush=True
                )

    scored = [r for r in results if "n" in r]
    n = sum(r["n"] for r in scored)
    changed = sum(len(r["changed"]) for r in scored)
    print(f"\n{len(scored)} decision points, {len(results) - len(scored)} skipped")
    if n:
        print(f"measured vs hand-set: {changed} of {n} calls changed ({changed / n:.0%})")
        if args.control:
            control = sum(len(r["control_changed"]) for r in scored)
            print(f"control, passing off: {control} of {n} changed ({control / n:.0%})")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
