"""Command line entry points.

python -m pitwall replay data/raw/hungary_2026_race.txt
python -m pitwall replay <file> --speed 60 --follow
python -m pitwall topics <file>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

from pitwall.feed.replay import ReplayFeed, read_events
from pitwall.laps import CleanLapConfig, LapCollector, filter_laps
from pitwall.models import EventKind, FuelModel, fit_hazard, fit_pace, load_history
from pitwall.sim import SimConfig, entries_from_state, evaluate_actions, undercut_threats
from pitwall.state.models import RaceState
from pitwall.state.reducer import RaceStateReducer


def _format_gap(car: object, attr: str) -> str:
    value = getattr(car, attr, None)
    return str(value) if value else "-"


def render(state: RaceState, *, limit: int | None = None) -> str:
    """Render the timing screen. `limit` defaults to the whole field.

    Do not hardcode a grid size here - 2026 runs 22 cars, and a fixed 20 silently
    truncated the last two.
    """
    lines = [
        f"{state.session_name or 'Session'} @ {state.circuit or '?'}"
        f"   lap {state.lap}/{state.total_laps or '?'}"
        f"   {state.track_status.name}"
        f"   ({state.events_applied} events)"
    ]
    header = (
        f"{'P':>3}  {'CAR':<4} {'TYRE':<4} {'AGE':>3}  "
        f"{'LAST':>8}  {'GAP':>9}  {'INT':>8}  {'ST':>2}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    order = state.running_order()
    for car in order[:limit] if limit else order:
        if car.position is None and not car.tla:
            continue
        last = f"{car.last_lap_time:.3f}" if car.last_lap_time else "-"
        flags = ""
        if car.in_pit:
            flags = " PIT"
        elif car.retired or car.stopped:
            flags = " OUT"
        lines.append(
            f"{car.position or 0:>3}  {car.tla or car.number:<4} "
            f"{car.compound.short:<4} {car.tyre_age:>3}  "
            f"{last:>8}  {_format_gap(car, 'gap_to_leader'):>9}  "
            f"{_format_gap(car, 'interval'):>8}  {car.pit_count:>2}{flags}"
        )
    return "\n".join(lines)


async def _replay(args: argparse.Namespace) -> int:
    if not args.file.exists():
        print(f"no such recording: {args.file}", file=sys.stderr)
        print("record one first:  python scripts/record.py data/raw/session.txt", file=sys.stderr)
        return 1

    reducer = RaceStateReducer()
    feed = ReplayFeed(args.file, speed=args.speed)
    every = max(1, args.every)

    async with feed:
        async for event in feed:
            state = reducer.apply(event)
            if args.follow and state.events_applied % every == 0:
                print("\033[2J\033[H" + render(state), flush=True)

    print(render(reducer.state))
    print(f"\nfolded {reducer.state.events_applied} events from {args.file.name}")
    return 0


def _topics(args: argparse.Namespace) -> int:
    if not args.file.exists():
        print(f"no such recording: {args.file}", file=sys.stderr)
        return 1
    counts: Counter[str] = Counter(event.topic for event in read_events(args.file))
    width = max((len(t) for t in counts), default=10)
    for topic, count in counts.most_common():
        print(f"{topic:<{width}}  {count:>8,}")
    print(f"\n{sum(counts.values()):,} events across {len(counts)} topics")
    return 0


def _laps(args: argparse.Namespace) -> int:
    if not args.file.exists():
        print(f"no such recording: {args.file}", file=sys.stderr)
        return 1

    collector = LapCollector()
    for event in read_events(args.file):
        collector.apply(event)

    config = CleanLapConfig(
        traffic_threshold=args.traffic,
        outlier_ratio=args.outlier,
    )
    clean, report = filter_laps(collector.laps, config)
    print(report)

    if not clean:
        return 0

    by_compound: dict[str, list[tuple[int, float]]] = {}
    for lap in clean:
        if lap.lap_time is not None:
            by_compound.setdefault(lap.compound.short, []).append((lap.tyre_age, lap.lap_time))

    print("\nclean laps by compound:")
    for compound, points in sorted(by_compound.items(), key=lambda kv: -len(kv[1])):
        ages = [a for a, _ in points]
        times = [t for _, t in points]
        print(
            f"  {compound}  n={len(points):>4}   "
            f"age {min(ages):>2}-{max(ages):<2}   "
            f"fastest {min(times):.3f}s"
        )

    if args.no_fit:
        return 0

    fit = fit_pace(clean)
    if fit is None:
        print("\nnot enough clean laps to fit the pace decomposition")
        return 0

    print()
    print(fit)

    total_laps = collector.state.total_laps
    if total_laps > 0:
        fuel = FuelModel(total_laps=total_laps)
        print(
            f"\n  physics prior    -{fuel.seconds_per_lap:.4f} s/lap "
            f"({fuel.start_fuel_kg:.0f}kg / {total_laps} laps @ {fuel.seconds_per_kg} s/kg)"
        )
        print(
            f"  implied          {fit.implied_seconds_per_kg(fuel.burn_per_lap_kg):.4f} s/kg "
            f"(published 0.030-0.040, plus track evolution)"
        )
    return 0


def _hazard(args: argparse.Namespace) -> int:
    if not args.file.exists():
        print(f"no history file: {args.file}", file=sys.stderr)
        print(
            "build one first:  python scripts/fetch_history.py --from 2022 --to 2026",
            file=sys.stderr,
        )
        return 1

    races = load_history(args.file)
    fit = fit_hazard(races, kind=EventKind(args.kind), shrinkage=args.shrinkage)
    if fit is None:
        print("not enough history to fit a hazard model", file=sys.stderr)
        return 1

    print(fit)

    if args.circuit:
        total = args.laps
        print(f"\n  {args.circuit} over {total} laps:")
        print(f"    expected events   {fit.expected_events(args.circuit, total):.2f}")
        for window in (5, 10, 15):
            start = max(1, total // 2)
            p = fit.probability_within(args.circuit, start, start + window - 1, total)
            print(f"    P(event in laps {start}-{start + window - 1})  {p:.1%}")
    return 0


def _strategy(args: argparse.Namespace) -> int:
    """Replay a recording to a given lap and ask what the engine would have said."""
    if not args.file.exists():
        print(f"no such recording: {args.file}", file=sys.stderr)
        return 1

    collector = LapCollector()
    snapshot = None
    for event in read_events(args.file):
        collector.apply(event)
        if snapshot is None and collector.state.lap >= args.lap:
            snapshot = collector.state.running_order()
    if snapshot is None:
        print(f"recording never reached lap {args.lap}", file=sys.stderr)
        return 1

    state = collector.state
    clean, _ = filter_laps(collector.laps)
    pace = fit_pace(clean)
    if pace is None:
        print("not enough clean laps to fit a pace model", file=sys.stderr)
        return 1

    hazard = None
    if args.history.exists():
        hazard = fit_hazard(load_history(args.history), kind=EventKind.ANY)

    entries = entries_from_state(state, pace)
    target = next(
        (e for e in entries if e.tla.upper() == args.driver.upper() or e.driver == args.driver),
        None,
    )
    if target is None:
        print(f"{args.driver} not found; have: {' '.join(e.tla for e in entries)}", file=sys.stderr)
        return 1

    total = state.total_laps or args.lap + 20
    cfg = SimConfig(n_sims=args.sims)
    print(f"{state.session_name} @ {state.circuit}  lap {args.lap}/{total}")
    if hazard is None:
        print("  (no safety-car history loaded - risk is not modelled)")
    print()

    rec = evaluate_actions(
        entries,
        our_driver=target.driver,
        from_lap=args.lap,
        total_laps=total,
        circuit=state.circuit,
        pace=pace,
        hazard=hazard,
        config=cfg,
    )
    print(rec)

    threats = undercut_threats(
        entries,
        our_driver=target.driver,
        from_lap=args.lap,
        total_laps=total,
        circuit=state.circuit,
        pace=pace,
        hazard=hazard,
        our_pit_lap=rec.best.pit_lap,
        config=cfg,
    )
    if threats:
        print("\n  undercut threats:")
        for threat in threats:
            print(
                f"    {threat.tla}  {threat.gap:+.1f}s behind   "
                f"P(jumps us) {threat.probability:.1%}"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pitwall")
    sub = parser.add_subparsers(dest="command", required=True)

    replay = sub.add_parser("replay", help="fold a recording into race state")
    replay.add_argument("file", type=Path)
    replay.add_argument(
        "--speed",
        type=float,
        default=None,
        help="1.0 is real time, 60 runs a race in ~2 min, omit for as-fast-as-possible",
    )
    replay.add_argument("--follow", action="store_true", help="redraw the timing screen")
    replay.add_argument("--every", type=int, default=50, help="redraw every N events")

    topics = sub.add_parser("topics", help="count events by topic in a recording")
    topics.add_argument("file", type=Path)

    # Read defaults off an instance, not the class: `slots=True` replaces class
    # attributes with descriptors, so `CleanLapConfig.traffic_threshold` is a
    # member_descriptor rather than 2.0.
    defaults = CleanLapConfig()

    laps = sub.add_parser("laps", help="extract laps and report clean-lap filtering")
    laps.add_argument("file", type=Path)
    laps.add_argument(
        "--traffic",
        type=float,
        default=defaults.traffic_threshold,
        help="seconds behind the car ahead below which a lap counts as dirty air",
    )
    laps.add_argument(
        "--outlier",
        type=float,
        default=defaults.outlier_ratio,
        help="reject laps slower than this multiple of the session best",
    )
    laps.add_argument(
        "--no-fit",
        action="store_true",
        help="report filtering only, without fitting the pace decomposition",
    )

    hazard = sub.add_parser("hazard", help="fit the per-circuit safety-car hazard")
    hazard.add_argument("file", type=Path, nargs="?", default=Path("data/history/safety_car.json"))
    hazard.add_argument(
        "--kind", choices=[k.value for k in EventKind], default=EventKind.SAFETY_CAR.value
    )
    hazard.add_argument(
        "--shrinkage",
        type=float,
        default=3.0,
        help="prior weight in expected events; higher pulls sparse circuits harder",
    )
    hazard.add_argument("--circuit", help="report window probabilities for one circuit")
    hazard.add_argument("--laps", type=int, default=60, help="race length for --circuit")

    strategy = sub.add_parser("strategy", help="ask for a pit call at a given lap")
    strategy.add_argument("file", type=Path)
    strategy.add_argument("--lap", type=int, required=True)
    strategy.add_argument("--driver", required=True, help="TLA or car number")
    strategy.add_argument("--sims", type=int, default=3000)
    strategy.add_argument("--history", type=Path, default=Path("data/history/safety_car.json"))

    args = parser.parse_args(argv)
    if args.command == "replay":
        return asyncio.run(_replay(args))
    if args.command == "topics":
        return _topics(args)
    if args.command == "laps":
        return _laps(args)
    if args.command == "hazard":
        return _hazard(args)
    if args.command == "strategy":
        return _strategy(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
