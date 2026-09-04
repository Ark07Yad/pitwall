#!/usr/bin/env python3
"""Re-run a race's calls against the current models, matched to the live ledger.

A model change is only worth anything if it would have changed the calls, and
the only honest way to ask that is to re-run the *same* decisions - same lap,
same car, same state - with one thing different. Anything else compares two
races rather than two models.

    python scripts/rescore.py --log predictions/2026-dutch-gp.jsonl \\
        --recording data/raw/2026-netherlands-race.txt \\
        --out reports/rescore/pooled-prior-v2.jsonl \\
        --note "degradation refit per race, disrupted races excluded"

**Nothing this writes is a prediction.** It runs against a recording that already
contains the result, so every row is stamped `rescore of <recording>` and the
report will refuse to read it as a live ledger. The live log is opened read-only
and never written back: a ledger you rewrite when it embarrasses you is not
evidence of anything.

The 23 August rescore was done by hand, which is why the numbers in
`reports/rescore/README.md` could not be regenerated when the degradation model
changed six days later. This exists so the next one is a command.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pitwall.laps import filter_laps, fold_to_lap
from pitwall.ledger import (
    PredictionLog,
    finishing_positions,
    prediction_from,
    score_predictions,
)
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
)
from pitwall.sim import SimConfig, entries_from_state, evaluate_actions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True, help="the live ledger to match")
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--note", default="", help="what changed, recorded on every row")
    parser.add_argument("--sims", type=int, default=1500)
    parser.add_argument("--history", type=Path, default=Path("data/history/safety_car.json"))
    parser.add_argument(
        "--degradation-history", type=Path, default=Path("data/history/degradation.json")
    )
    parser.add_argument("--pit-loss-history", type=Path, default=Path("data/history/pit_loss.json"))
    args = parser.parse_args()

    for path in (args.log, args.recording):
        if not path.exists():
            print(f"no such file: {path}", file=sys.stderr)
            return 1

    live = [json.loads(line) for line in args.log.read_text().splitlines() if line.strip()]
    if not live:
        print(f"{args.log} is empty", file=sys.stderr)
        return 1

    hazard = attrition = None
    if args.history.exists():
        history = load_history(args.history)
        hazard = fit_hazard(history, kind=EventKind.ANY)
        attrition = fit_attrition(history)
    pit_loss = (
        fit_pit_loss(load_pit_loss(args.pit_loss_history))
        if args.pit_loss_history.exists()
        else None
    )
    prior = None
    if args.degradation_history.exists():
        prior = fit_degradation(
            load_degradation(args.degradation_history),
            history=neutralisation_index(load_history(args.history))
            if args.history.exists()
            else None,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()
    log = PredictionLog(
        args.out.stem,
        directory=args.out.parent,
        commit=False,
        source=f"rescore of {args.recording.name}",
    )
    log.path = args.out

    cfg = SimConfig(n_sims=args.sims)
    matched: list[dict] = []
    skipped: list[str] = []

    for row in live:
        lap, driver = int(row["lap"]), str(row["driver"])
        # Re-fold from scratch for every lap, as the backtest does. Slower than
        # snapshotting and the only way to be sure no later event leaked into a
        # decision that is supposed to predate it.
        collector = fold_to_lap(args.recording, lap)
        state = collector.state
        if state.lap < lap:
            skipped.append(f"lap {lap}: recording never got there")
            continue

        clean, _ = filter_laps(collector.laps)
        pace = fit_pace(clean, prior=prior, circuit=state.circuit)
        if pace is None or not pace.usable:
            skipped.append(f"lap {lap}: fit not usable")
            continue

        entries = entries_from_state(state, pace)
        target = next((e for e in entries if e.driver == driver), None)
        if target is None:
            skipped.append(f"lap {lap}: {row.get('tla', driver)} not in state")
            continue

        total = state.total_laps or lap + 20
        rec = evaluate_actions(
            entries,
            our_driver=target.driver,
            from_lap=lap,
            total_laps=total,
            circuit=state.circuit,
            pace=pace,
            hazard=hazard,
            attrition=attrition,
            pit_loss=pit_loss,
            config=cfg,
        )
        written = log.record(
            prediction_from(
                rec,
                session=str(row.get("session") or args.out.stem),
                circuit=state.circuit,
                total_laps=total,
                note=args.note,
            )
        )
        matched.append({"live": row, "rescored": json.loads(written.to_json())})
        print(
            f"  lap {lap:>2} {row.get('tla', driver):<4} "
            f"live {row.get('pit_lap'):>3} {'stop ' if row.get('stop', True) else 'stay '}"
            f"-> now {written.pit_lap:>3} {'stop ' if written.stop else 'stay '}"
            f"  E[pos] {row.get('expected_position', 0):.2f} -> {written.expected_position:.2f}",
            flush=True,
        )

    if not matched:
        print("nothing could be rescored", file=sys.stderr)
        return 1

    final = finishing_positions(fold_to_lap(args.recording, 10**9).state)
    live_card = score_predictions([m["live"] for m in matched], final)
    new_card = score_predictions([m["rescored"] for m in matched], final)

    changed = sum(
        1
        for m in matched
        if m["live"].get("stop", True) != m["rescored"]["stop"]
        or m["live"].get("pit_lap") != m["rescored"]["pit_lap"]
    )
    extrap_live = sum(1 for m in matched if m["live"].get("extrapolated"))
    extrap_new = sum(1 for m in matched if m["rescored"].get("extrapolated"))

    print(f"\n  {len(matched)} of {len(live)} calls rescored, {changed} changed")
    for line in skipped:
        print(f"    skipped: {line}")
    print(f"\n  {'metric':<26}{'live':>10}{'rescored':>12}")
    print(f"  {'Brier (top 3)':<26}{live_card.brier_top3:>10.4f}{new_card.brier_top3:>12.4f}")
    print(f"  {'Brier (points)':<26}{live_card.brier_points:>10.4f}{new_card.brier_points:>12.4f}")
    print(
        f"  {'skill vs baseline':<26}"
        f"{live_card.format_skill(live_card.skill_top3):>10}"
        f"{new_card.format_skill(new_card.skill_top3):>12}"
    )
    print(
        f"  {'mean position error':<26}"
        f"{live_card.position_error:>10.2f}{new_card.position_error:>12.2f}"
    )
    print(f"  {'on unobserved tyre ages':<26}{extrap_live:>10}{extrap_new:>12}")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
