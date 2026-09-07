#!/usr/bin/env python3
"""Ask whether a degradation prior change alters decisions, across many races.

Three races in a row failed to answer this. Zandvoort could not separate the old
prior from the new one because staying out wins under both. Monza could not speak
until lap 32, ten laps after its own break-even had passed. Madrid is a new
circuit whose fit may be slow for the same reason. Waiting for a race to
cooperate is not a method.

The archive makes the corpus available instead: `fetch_recording.py` rebuilds any
past race, and a rebuild was checked against two live captures at 52 of 52
identical calls. So the question can be asked across a season rather than an
afternoon.

    python scripts/prior_corpus.py --rounds 3,5,6,7,9,10,12,13 --season 2026

**Both priors are run through the same path on the same folded state.** The state
is folded once per lap and handed to each prior in turn - same laps, same cars,
same everything except the model. Anything else compares two races.

**The baseline is the real old model, not a reconstruction of it.** `--baseline`
points at a `degradation.py` extracted from git, loaded as a module, and fitted on
the dataset from the same commit. Both are checked on load: the old fit must
reproduce Zandvoort at 0.505x and a soft tyre at -0.0148 s/lap, which are the
numbers recorded in the logbook on 28 August. If it does not, the comparison is
against a fiction and the script refuses to run.
"""

from __future__ import annotations

import argparse
import importlib.util
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
    fit_pace,
    fit_pit_loss,
    load_degradation,
    load_history,
    load_pit_loss,
    neutralisation_index,
    normalise_circuit,
)
from pitwall.sim import SimConfig, entries_from_state, evaluate_actions

# The old fit, as recorded in the logbook on 28 August. If a reconstruction does
# not reproduce these it is not the model that produced those findings.
BASELINE_CHECKS = {"Zandvoort": 0.505, "_sof_linear": -0.0148}


def load_baseline(module_path: Path, data_path: Path) -> Any:
    """Fit the pre-change prior from a module extracted out of git history."""
    spec = importlib.util.spec_from_file_location("baseline_degradation", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["baseline_degradation"] = module
    spec.loader.exec_module(module)
    prior = module.fit_degradation(module.load_degradation(str(data_path)))
    if prior is None:
        raise RuntimeError("baseline prior did not fit")

    got = round(prior.circuit_factor.get("Zandvoort", float("nan")), 3)
    want = BASELINE_CHECKS["Zandvoort"]
    if got != want:
        raise RuntimeError(f"baseline Zandvoort factor is {got}, expected {want}")
    sof = next((v for c, v in prior.linear.items() if c.short == "SOF"), None)
    if sof is None or round(sof, 4) != BASELINE_CHECKS["_sof_linear"]:
        raise RuntimeError(
            f"baseline SOF slope is {sof}, expected {BASELINE_CHECKS['_sof_linear']}"
        )
    return prior


def call_of(rec: Any) -> str:
    best = rec.best
    return (
        f"stay/{best.compound.short}"
        if not best.stop
        else f"pit{best.pit_lap}/{best.compound.short}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--rounds", required=True, help="comma separated")
    parser.add_argument("--fractions", default="0.40,0.55,0.70,0.85", help="of race distance")
    parser.add_argument("--drivers", type=int, default=4, help="top N by position at that lap")
    parser.add_argument("--sims", type=int, default=1500)
    parser.add_argument("--baseline", type=Path, required=True, help="old degradation.py")
    parser.add_argument("--baseline-data", type=Path, required=True, help="old degradation.json")
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("reports/prior-corpus.json"))
    args = parser.parse_args()

    baseline = load_baseline(args.baseline, args.baseline_data)
    history = load_history("data/history/safety_car.json")
    hazard = fit_hazard(history, kind=EventKind.ANY)
    attrition = fit_attrition(history)
    pit_loss = fit_pit_loss(load_pit_loss("data/history/pit_loss.json"))
    current = fit_degradation(
        load_degradation("data/history/degradation.json"),
        history=neutralisation_index(history),
    )
    print(
        f"baseline verified: Zandvoort {baseline.circuit_factor['Zandvoort']:.3f}x, "
        f"{baseline.n_races} races"
    )
    print(
        f"current:           Zandvoort {current.circuit_factor['Zandvoort']:.3f}x, "
        f"{current.n_races} races\n"
    )

    cfg = SimConfig(n_sims=args.sims)
    fractions = [float(f) for f in args.fractions.split(",")]
    results: list[dict[str, Any]] = []

    for rnd in [int(r) for r in args.rounds.split(",")]:
        recording = next(args.raw.glob(f"*r{rnd}-archive.txt"), None)
        if recording is None:
            print(f"round {rnd}: no recording, skipping (fetch it first)", file=sys.stderr)
            continue

        total = fold_to_lap(recording, 10**9).state.total_laps
        if not total:
            print(f"round {rnd}: no lap count in recording, skipping", file=sys.stderr)
            continue

        for fraction in fractions:
            lap = max(1, int(total * fraction))
            collector = fold_to_lap(recording, lap)
            state = collector.state
            circuit = normalise_circuit(state.circuit)
            clean, _ = filter_laps(collector.laps)
            order = {
                car.number: car.position
                for car in state.running_order()
                if car.position is not None
            }

            row_base: dict[str, Any] = {
                "round": rnd,
                "circuit": circuit,
                "lap": lap,
                "total_laps": total,
                "factor_old": baseline.circuit_factor.get(circuit),
                "factor_new": current.circuit_factor.get(circuit),
            }

            # One fold, two priors. The pace fit blends toward the prior, so it
            # is refitted per prior rather than shared - the prior reaches a
            # decision through both the fit and the simulation.
            calls: dict[str, dict[str, str]] = {}
            usable = True
            for name, prior in (("old", baseline), ("new", current)):
                pace = fit_pace(clean, prior=prior, circuit=state.circuit)
                if pace is None or not pace.usable:
                    usable = False
                    break
                entries = entries_from_state(state, pace)
                # `CarEntry` carries elapsed time, not classification, so the
                # order comes from race state. Ranking by `elapsed` would put
                # a lapped car ahead of the leader.
                ranked = sorted(entries, key=lambda e: order.get(e.driver, 99))[: args.drivers]
                calls[name] = {}
                for entry in ranked:
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
                        config=cfg,
                    )
                    calls[name][entry.tla] = call_of(rec)

            if not usable:
                results.append({**row_base, "skipped": "fit not usable"})
                print(f"  r{rnd:>2} {circuit:<18} lap {lap:>2}/{total}  fit not usable", flush=True)
                continue

            shared = sorted(set(calls["old"]) & set(calls["new"]))
            changed = [t for t in shared if calls["old"][t] != calls["new"][t]]
            results.append(
                {
                    **row_base,
                    "n": len(shared),
                    "changed": len(changed),
                    "old": calls["old"],
                    "new": calls["new"],
                }
            )
            mark = f"  {len(changed)}/{len(shared)} changed" if changed else "  no change"
            print(f"  r{rnd:>2} {circuit:<18} lap {lap:>2}/{total}{mark}", flush=True)
            for tla in changed:
                print(f"       {tla}: {calls['old'][tla]} -> {calls['new'][tla]}", flush=True)

    scored = [r for r in results if "n" in r]
    total_calls = sum(r["n"] for r in scored)
    total_changed = sum(r["changed"] for r in scored)
    print(f"\n{len(scored)} decision points scored, {len(results) - len(scored)} skipped")
    print(f"{total_changed} of {total_calls} calls changed", end="")
    print(f" ({total_changed / total_calls:.1%})" if total_calls else "")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
