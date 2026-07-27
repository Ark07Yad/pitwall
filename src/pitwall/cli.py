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

    args = parser.parse_args(argv)
    if args.command == "replay":
        return asyncio.run(_replay(args))
    if args.command == "topics":
        return _topics(args)
    if args.command == "laps":
        return _laps(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
