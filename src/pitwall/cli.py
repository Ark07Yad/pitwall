"""Command line entry points.

python -m pitwall replay data/raw/hungary_2026_race.txt
python -m pitwall replay <file> --speed 60 --follow
python -m pitwall topics <file>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

from pitwall.feed.replay import ReplayFeed, read_events
from pitwall.feed.signalr import SignalRFeed
from pitwall.laps import CleanLapConfig, LapCollector, filter_laps, fold_to_lap
from pitwall.ledger import (
    PredictionLog,
    finishing_positions,
    prediction_from,
    race_report,
    score_predictions,
)
from pitwall.models import (
    DegradationPrior,
    EventKind,
    FuelModel,
    PitLossModel,
    fit_attrition,
    fit_degradation,
    fit_hazard,
    fit_pace,
    fit_pit_loss,
    load_degradation,
    load_history,
    load_pit_loss,
)
from pitwall.models.pit_loss import DEFAULT_SHRINKAGE as PIT_LOSS_SHRINKAGE
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

    attrition = fit_attrition(races)
    if attrition is not None:
        print()
        print(attrition)

    if args.circuit:
        total = args.laps
        print(f"\n  {args.circuit} over {total} laps:")
        print(f"    expected safety cars  {fit.expected_events(args.circuit, total):.2f}")
        for window in (5, 10, 15):
            start = max(1, total // 2)
            p = fit.probability_within(args.circuit, start, start + window - 1, total)
            print(f"    P(event in laps {start}-{start + window - 1})   {p:.1%}")
        if attrition is not None:
            per_car = attrition.probability_within(args.circuit, 1, total, total)
            dnfs = attrition.expected_retirements(args.circuit, total, 22)
            print(f"    P(a given car retires) {per_car:.1%}")
            print(f"    expected DNFs (22 cars) {dnfs:.1f}")
    return 0


def _degradation(args: argparse.Namespace) -> int:
    """Fit and report the pooled degradation prior."""
    if not args.file.exists():
        print(f"no degradation history: {args.file}", file=sys.stderr)
        print(
            "build one first:  python scripts/fetch_degradation.py --from 2022 --to 2026",
            file=sys.stderr,
        )
        return 1

    fit = fit_degradation(load_degradation(args.file))
    if fit is None:
        print("not enough history to fit a degradation prior", file=sys.stderr)
        return 1

    if args.circuit:
        name = args.circuit
        known = "" if fit.known_circuit(name) else "  (unknown here - unscaled)"
        factor = fit.circuit_factor.get(name, 1.0)
        print(f"{name}: {factor:.2f}x the field average{known}")
        print(f"  {'compound':<10} {'@20':>8} {'@40':>8} {'@55':>8}  evidence to age")
        for compound in sorted(fit.linear, key=lambda c: c.short):
            print(
                f"  {compound.short:<10}"
                f" {fit.degradation_at(compound, 20, name):>+7.2f}s"
                f" {fit.degradation_at(compound, 40, name):>+7.2f}s"
                f" {fit.degradation_at(compound, 55, name):>+7.2f}s"
                f"  {fit.observed_max_age(compound):>14}"
            )
        return 0

    print(fit)
    return 0


def _pitloss(args: argparse.Namespace) -> int:
    """Fit and report per-circuit green-flag pit loss."""
    if not args.file.exists():
        print(f"no pit-loss history: {args.file}", file=sys.stderr)
        print(
            "build one first:  python scripts/fetch_pit_loss.py --from 2022 --to 2026",
            file=sys.stderr,
        )
        return 1

    fit = fit_pit_loss(load_pit_loss(args.file), shrinkage=args.shrinkage)
    if fit is None:
        print("not enough history to fit pit loss", file=sys.stderr)
        return 1

    if args.circuit:
        name = args.circuit
        known = "" if fit.known_circuit(name) else "  (unknown here - field median)"
        print(f"{name}: {fit.loss(name):.2f}s +/- {fit.spread_for(name):.2f}{known}")
        if fit.known_circuit(name):
            print(f"  fitted on {fit.races_at(name)} race(s)")
        return 0

    print(fit)
    return 0


def _strategy(args: argparse.Namespace) -> int:
    """Replay a recording to a given lap and ask what the engine would have said."""
    if not args.file.exists():
        print(f"no such recording: {args.file}", file=sys.stderr)
        return 1

    # Fold only as far as the target lap. Reading the whole file first would
    # put the *final* classification into the simulation and fit the pace model
    # on laps that had not happened yet - neither is information the engine
    # would have had live.
    collector = fold_to_lap(args.file, args.lap)
    if collector.state.lap < args.lap:
        print(f"recording never reached lap {args.lap}", file=sys.stderr)
        return 1

    state = collector.state
    clean, _ = filter_laps(collector.laps)
    prior = _load_degradation(args.degradation_history)
    pace = fit_pace(clean, prior=prior, circuit=state.circuit)
    if pace is None:
        print("not enough clean laps to fit a pace model", file=sys.stderr)
        return 1
    if not pace.usable:
        print(f"the pace fit at lap {args.lap} is not usable:", file=sys.stderr)
        for reason in pace.unusable_reasons:
            print(f"  - {reason}", file=sys.stderr)
        print("no recommendation is offered.", file=sys.stderr)
        return 1

    hazard = attrition = None
    if args.history.exists():
        history = load_history(args.history)
        hazard = fit_hazard(history, kind=EventKind.ANY)
        attrition = fit_attrition(history)
    pit_loss = _load_pit_loss(args.pit_loss_history)

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
        attrition=attrition,
        pit_loss=pit_loss,
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
        attrition=attrition,
        pit_loss=pit_loss,
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


async def _live(args: argparse.Namespace) -> int:
    """Connect to F1's live timing stream and fold it in real time."""
    feed = SignalRFeed(record_to=str(args.record) if args.record else None)
    collector = LapCollector()
    last_draw = 0.0

    if args.record:
        args.record.parent.mkdir(parents=True, exist_ok=True)
        print(f"recording raw frames to {args.record}", file=sys.stderr)
    print("connecting to F1 live timing...", file=sys.stderr)

    async def consume() -> None:
        nonlocal last_draw
        async with feed:
            async for event in feed:
                collector.apply(event)
                now = time.monotonic()
                if now - last_draw >= args.every:
                    last_draw = now
                    print("\033[2J\033[H" + render(collector.state), flush=True)
                    print(f"\n  {feed.latency}", flush=True)

    try:
        # The deadline has to wrap the iteration, not sit inside it. Between
        # sessions the feed sends only keepalive pings, which correctly produce
        # no events, so a check in the loop body would never run and --duration
        # would hang forever.
        if args.duration:
            async with asyncio.timeout(args.duration):
                await consume()
        else:
            await consume()
    except (KeyboardInterrupt, TimeoutError):
        pass
    finally:
        await feed.aclose()

    print("\n" + render(collector.state))
    print(f"\n  {feed.latency}")
    print(f"  {len(collector.laps)} laps extracted")
    return 0


def _backtest(args: argparse.Namespace) -> int:
    """Log predictions at a series of laps, each fitted only on what was known then."""
    if not args.file.exists():
        print(f"no such recording: {args.file}", file=sys.stderr)
        return 1

    hazard = attrition = None
    if args.history.exists():
        history = load_history(args.history)
        hazard = fit_hazard(history, kind=EventKind.ANY)
        attrition = fit_attrition(history)
    pit_loss = _load_pit_loss(args.pit_loss_history)
    prior = _load_degradation(args.degradation_history)

    laps = [int(x) for x in args.laps.split(",") if x.strip()]
    wanted = {d.strip().upper() for d in args.drivers.split(",") if d.strip()}
    cfg = SimConfig(n_sims=args.sims)
    log = None
    total = 0

    for lap in laps:
        # Re-fold from scratch for every lap. Slower than snapshotting, and the
        # only way to be certain no later event has leaked into this decision.
        collector = fold_to_lap(args.file, lap)
        state = collector.state
        if state.lap < lap:
            print(f"lap {lap}: recording never got there, skipping", file=sys.stderr)
            continue

        clean, _ = filter_laps(collector.laps)
        pace = fit_pace(clean, prior=prior, circuit=state.circuit)
        if pace is None:
            print(f"lap {lap}: too few clean laps to fit yet, skipping", file=sys.stderr)
            continue
        if not pace.usable:
            # Better no prediction than a confident one drawn from a degenerate
            # fit. Early in a race the design simply is not identified yet.
            print(f"lap {lap}: fit not usable, skipping", file=sys.stderr)
            for reason in pace.unusable_reasons:
                print(f"         - {reason}", file=sys.stderr)
            continue

        if log is None:
            log = PredictionLog(
                args.session or f"{state.session_name} {state.circuit}",
                directory=args.out,
                commit=not args.no_commit,
            )

        entries = entries_from_state(state, pace)
        for entry in entries:
            if wanted and entry.tla.upper() not in wanted:
                continue
            rec = evaluate_actions(
                entries,
                our_driver=entry.driver,
                from_lap=lap,
                total_laps=state.total_laps or lap + 20,
                circuit=state.circuit,
                pace=pace,
                hazard=hazard,
                attrition=attrition,
                pit_loss=pit_loss,
                config=cfg,
            )
            log.record(
                prediction_from(
                    rec,
                    session=log.session,
                    circuit=state.circuit,
                    total_laps=state.total_laps or lap + 20,
                    horizon=args.horizon,
                )
            )
            total += 1
        print(f"lap {lap}: {len(clean)} clean laps known, logged predictions", file=sys.stderr)

    if log is None:
        print("nothing logged", file=sys.stderr)
        return 1
    print(f"\n{total} predictions -> {log.path}")
    if log.commit_failures:
        print(f"  {log.commit_failures} commits failed (predictions are still on disk)")
    return 0


def _report(args: argparse.Namespace) -> int:
    """Score a prediction log against the finish and write a markdown report."""
    if not args.log.exists():
        print(f"no prediction log: {args.log}", file=sys.stderr)
        return 1
    if not args.file.exists():
        print(f"no such recording: {args.file}", file=sys.stderr)
        return 1

    log = PredictionLog("scored", directory=args.log.parent, commit=False)
    log.path = args.log
    entries = log.entries()

    collector = LapCollector()
    for event in read_events(args.file):
        collector.apply(event)
    state = collector.state
    finish = finishing_positions(state)

    card = score_predictions(entries, finish)
    print(card)

    session = entries[0].get("session") if entries else state.session_name
    text = race_report(
        entries,
        finish,
        session=str(session),
        circuit=state.circuit,
        tla_by_driver={n: c.tla for n, c in state.cars.items()},
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


def _load_degradation(path: Path) -> DegradationPrior | None:
    """The pooled degradation prior, or None if the history is not built.

    Absence is not fatal: the in-session fit runs alone, which is what it did
    before the prior existed.
    """
    if not path.exists():
        return None
    return fit_degradation(load_degradation(path))


def _load_pit_loss(path: Path) -> PitLossModel | None:
    """Per-circuit pit loss, or None if the history has not been built.

    Absence is not fatal: the simulation falls back to the flat config constant,
    which is what it used before this model existed.
    """
    if not path.exists():
        return None
    return fit_pit_loss(load_pit_loss(path))


def _dashboard(args: argparse.Namespace) -> int:
    """Serve the live dashboard, from the live feed or a recording."""
    from pitwall.dashboard import Engine, serve

    if args.replay:
        if not args.replay.exists():
            print(f"no such recording: {args.replay}", file=sys.stderr)
            return 1
        # Warp rather than skip: fast-forwarding applies all the earlier state
        # (driver list, stints, compounds), where skipping would silently drop it.
        warp = timedelta(minutes=args.skip) if args.skip else None
        feed = ReplayFeed(args.replay, speed=args.speed, warp_until=warp)
        source = f"replay of {args.replay.name} at {args.speed or 'max'}x"
        if warp:
            source += f", from {args.skip:g} min in"
    else:
        feed = SignalRFeed(record_to=str(args.record) if args.record else None)
        source = "F1 live timing"

    hazard = attrition = None
    if args.history.exists():
        history = load_history(args.history)
        hazard = fit_hazard(history, kind=EventKind.ANY)
        attrition = fit_attrition(history)
    pit_loss = _load_pit_loss(args.pit_loss_history)
    prior = _load_degradation(args.degradation_history)

    log = None
    if args.log_predictions:
        # A replayed race is a rehearsal, and its calls are made with the result
        # already on disk. Committing them into the same ledger as live ones
        # would destroy the only thing that makes the ledger worth anything -
        # that a commit timestamp proves the call preceded the outcome. So a
        # replay may be logged, but never committed.
        if args.replay and not args.no_commit:
            print(
                "refusing to commit predictions from a replay: the recording already "
                "contains the outcome.\n"
                "re-run with --no-commit to rehearse the ledger, or drop --replay to go live.",
                file=sys.stderr,
            )
            return 1
        log = PredictionLog(
            args.session or f"{args.replay.stem if args.replay else 'live'}",
            directory=args.out,
            commit=not args.no_commit,
        )
        print(f"  ledger -> {log.path}" + ("" if log.commit_enabled else " (not committing)"))

    engine = Engine(
        feed,
        hazard=hazard,
        attrition=attrition,
        pit_loss=pit_loss,
        degradation=prior,
        driver=args.driver,
        sims=args.sims,
        log=log,
        horizon=args.horizon,
    )
    print(f"pitwall dashboard - {source}")
    print(f"  http://{args.host}:{args.port}")
    serve(engine, host=args.host, port=args.port)
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

    degradation = sub.add_parser("degradation", help="fit the pooled tyre-degradation prior")
    degradation.add_argument(
        "file", type=Path, nargs="?", default=Path("data/history/degradation.json")
    )
    degradation.add_argument("--circuit", default="", help="scale to one circuit")

    pitloss = sub.add_parser("pitloss", help="fit per-circuit green-flag pit loss")
    pitloss.add_argument("file", type=Path, nargs="?", default=Path("data/history/pit_loss.json"))
    pitloss.add_argument("--shrinkage", type=float, default=PIT_LOSS_SHRINKAGE)
    pitloss.add_argument("--circuit", default="", help="report one circuit")

    strategy = sub.add_parser("strategy", help="ask for a pit call at a given lap")
    strategy.add_argument("file", type=Path)
    strategy.add_argument("--lap", type=int, required=True)
    strategy.add_argument("--driver", required=True, help="TLA or car number")
    strategy.add_argument("--sims", type=int, default=3000)
    strategy.add_argument("--history", type=Path, default=Path("data/history/safety_car.json"))
    strategy.add_argument(
        "--degradation-history",
        type=Path,
        default=Path("data/history/degradation.json"),
        help="pooled tyre-degradation prior; a single race cannot identify a cliff",
    )
    strategy.add_argument(
        "--pit-loss-history",
        type=Path,
        default=Path("data/history/pit_loss.json"),
        help="per-circuit pit loss; falls back to a flat constant if absent",
    )

    live = sub.add_parser("live", help="connect to F1 live timing and fold it in real time")
    live.add_argument(
        "--record",
        type=Path,
        help="also write raw frames here; live data cannot be recovered later",
    )
    live.add_argument("--every", type=float, default=2.0, help="seconds between screen redraws")
    live.add_argument(
        "--duration", type=float, default=0.0, help="stop after N seconds (0 = forever)"
    )

    backtest = sub.add_parser("backtest", help="log leak-free predictions at a series of laps")
    backtest.add_argument("file", type=Path)
    backtest.add_argument("--laps", default="16,24,32,40,48")
    backtest.add_argument("--drivers", default="", help="TLAs, comma separated; blank = all")
    backtest.add_argument("--sims", type=int, default=2000)
    backtest.add_argument("--horizon", type=int, default=10)
    backtest.add_argument("--session", default="", help="label for the log file")
    backtest.add_argument("--out", type=Path, default=Path("predictions"))
    backtest.add_argument("--no-commit", action="store_true")
    backtest.add_argument("--history", type=Path, default=Path("data/history/safety_car.json"))
    backtest.add_argument(
        "--degradation-history",
        type=Path,
        default=Path("data/history/degradation.json"),
        help="pooled tyre-degradation prior; a single race cannot identify a cliff",
    )
    backtest.add_argument(
        "--pit-loss-history",
        type=Path,
        default=Path("data/history/pit_loss.json"),
        help="per-circuit pit loss; falls back to a flat constant if absent",
    )

    report = sub.add_parser("report", help="score a prediction log and write a race report")
    report.add_argument("file", type=Path, help="the recording, for final classification")
    report.add_argument("--log", type=Path, required=True)
    report.add_argument("--out", type=Path, default=Path("reports/race.md"))

    dashboard = sub.add_parser("dashboard", help="serve the live dashboard")
    dashboard.add_argument("--replay", type=Path, help="drive it from a recording instead of live")
    dashboard.add_argument("--speed", type=float, default=30.0, help="replay speed multiplier")
    dashboard.add_argument(
        "--skip",
        type=float,
        default=0.0,
        help="minutes to fast-forward through before pacing begins",
    )
    dashboard.add_argument("--driver", default="", help="TLA to advise; blank = the leader")
    dashboard.add_argument("--sims", type=int, default=1500)
    dashboard.add_argument("--host", default="127.0.0.1")
    dashboard.add_argument("--port", type=int, default=8000)
    dashboard.add_argument("--record", type=Path, help="also write raw frames (live only)")
    dashboard.add_argument("--history", type=Path, default=Path("data/history/safety_car.json"))
    dashboard.add_argument(
        "--degradation-history",
        type=Path,
        default=Path("data/history/degradation.json"),
        help="pooled tyre-degradation prior; a single race cannot identify a cliff",
    )
    dashboard.add_argument(
        "--pit-loss-history",
        type=Path,
        default=Path("data/history/pit_loss.json"),
        help="per-circuit pit loss; falls back to a flat constant if absent",
    )
    dashboard.add_argument(
        "--log-predictions",
        action="store_true",
        help="write each call to the prediction ledger and commit it as it is made",
    )
    dashboard.add_argument("--out", type=Path, default=Path("predictions"), help="ledger directory")
    dashboard.add_argument("--session", default="", help="ledger session name")
    dashboard.add_argument("--horizon", type=int, default=10, help="laps a call is claimed for")
    dashboard.add_argument(
        "--no-commit", action="store_true", help="write the ledger but do not git commit"
    )

    args = parser.parse_args(argv)
    if args.command == "replay":
        return asyncio.run(_replay(args))
    if args.command == "topics":
        return _topics(args)
    if args.command == "laps":
        return _laps(args)
    if args.command == "hazard":
        return _hazard(args)
    if args.command == "pitloss":
        return _pitloss(args)
    if args.command == "degradation":
        return _degradation(args)
    if args.command == "strategy":
        return _strategy(args)
    if args.command == "live":
        return asyncio.run(_live(args))
    if args.command == "backtest":
        return _backtest(args)
    if args.command == "report":
        return _report(args)
    if args.command == "dashboard":
        return _dashboard(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
