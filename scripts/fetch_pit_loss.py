#!/usr/bin/env python3
"""Measure green-flag pit loss per circuit, for the strategy simulation.

Pit loss is the most stable constant in the sport - it is set by pit lane
geometry and a speed limit, not by car performance - and it was the last number
in this engine still hard-coded to a single flat value for every track. That is
a ~7 s spread being modelled as zero: Spa is about 18.4 s and Marina Bay about
27 s, and the *timing* of every pit call rests on which one is true.

What is measured, for each stop, is the quantity the simulation actually adds:
total time lost against having stayed out.

    loss = (in_lap - baseline) + (out_lap - baseline)

where `baseline` is the median of that driver's own green, accurate, non-pit
laps in a window either side of the stop. Using a *local* per-driver baseline is
what makes this work without modelling anything else: fuel load, track
evolution and the driver's own pace are all very nearly constant across a
fifteen-lap window, so they cancel instead of needing correction.

Four filters, each removing a way the number would be wrong rather than noisy:

- **Neutralised stops are excluded.** A stop under a safety car is cheap because
  the field is crawling, which is a real effect the simulation models separately
  with `sc_pit_discount`. Folding those into the green-flag constant would drag
  it down and then discount it twice.
- **Unstable reference windows are excluded.** If the driver's own surrounding
  laps disagree by more than a second and a half, the track was changing -
  drying, or a shower - and the baseline means nothing. This is what keeps wet
  races from poisoning a dry constant.
- **Implausible losses are excluded**, which is mostly drive-through and stop-go
  penalties: they look exactly like a pit stop in the lap data and are not one.
- **Races contribute their median, not their stops.** One chaotic afternoon with
  forty measurable stops should not outvote three clean ones, so the race is the
  unit of observation.

    python scripts/fetch_pit_loss.py --from 2022 --to 2026

Circuits are keyed on F1's `Circuit.ShortName` where the session info provides
it - that is the name the *live feed* sends, so the runtime lookup matches
without a translation step. Output: data/history/pit_loss.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import statistics
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")
logging.getLogger("fastf1").setLevel(logging.ERROR)

import fastf1  # noqa: E402
import pandas as pd  # noqa: E402

# Laps either side of the stop to draw the baseline from. Wide enough to survive
# a few excluded laps, narrow enough that fuel burn barely moves across it.
WINDOW = 5
MIN_REFERENCE_LAPS = 4
# Above this much scatter in the reference laps the track was changing, not the
# driver. A dry green stint sits far inside this.
MAX_REFERENCE_SD = 1.5
# Outside these a "stop" is a penalty, damage, or a red-flag artefact.
MIN_LOSS, MAX_LOSS = 10.0, 60.0
# Below this many measurable stops a race median is not worth carrying.
MIN_STOPS_PER_RACE = 5

GREEN = "1"

# A served time penalty is added to the stationary time, so the stop reads as a
# botched one in lap data. Left in, they roughly double the apparent rate of
# disastrous stops - the tail would then tell the simulation that stopping is
# far riskier than it is, and bias it against pitting at all. The car number
# lives in the message text; `RacingNumber` is null on these.
PENALTY_MESSAGE = re.compile(
    r"(\d+)\s*SECOND\s+TIME\s+PENALTY|DRIVE.?THROUGH|STOP\s*(?:/|\s+AND\s+)?GO", re.I
)
PENALTY_CAR = re.compile(r"CAR\s+(\d+)", re.I)


def penalised_stops(session: Any, laps: pd.DataFrame) -> set[tuple[str, int]]:
    """(car number, lap) for stops that served a penalty.

    A penalty issued on lap L is served at that car's next stop, so that is the
    one to drop.
    """
    try:
        messages = session.race_control_messages
    except Exception:  # noqa: BLE001
        return set()
    if messages is None or len(messages) == 0:
        return set()

    issued: dict[str, list[int]] = {}
    for _, message in messages.iterrows():
        text = str(message.get("Message") or "")
        if not PENALTY_MESSAGE.search(text):
            continue
        car = PENALTY_CAR.search(text)
        lap = message.get("Lap")
        if car is None or lap is None or pd.isna(lap):
            continue
        issued.setdefault(car.group(1), []).append(int(lap))

    flagged: set[tuple[str, int]] = set()
    for number, laps_issued in issued.items():
        driver = laps[laps.DriverNumber.astype(str) == number]
        stops = sorted(int(x) for x in driver[driver.PitInTime.notna()].LapNumber)
        for issued_on in laps_issued:
            served = next((s for s in stops if s >= issued_on), None)
            if served is not None:
                flagged.add((number, served))
    return flagged


def drop_penalised(laps: pd.DataFrame, flagged: set[tuple[str, int]]) -> pd.DataFrame:
    if not flagged:
        return laps
    keep = pd.Series(True, index=laps.index)
    for number, lap in flagged:
        keep &= ~(
            (laps.DriverNumber.astype(str) == number)
            & (laps.LapNumber == lap)
            & laps.PitInTime.notna()
        )
    return laps[keep]


def is_rate_limit(exc: Exception) -> bool:
    return type(exc).__name__ == "RateLimitExceededError" or "calls/h" in str(exc)


def _seconds(value: Any) -> float | None:
    return None if pd.isna(value) else float(value.total_seconds())


def _is_green(value: Any) -> bool:
    return str(value).strip() == GREEN


def stop_losses(laps: pd.DataFrame) -> tuple[list[float], dict[str, int]]:
    """Every measurable green-flag pit loss in one race."""
    losses: list[float] = []
    rejected = {"neutralised": 0, "no_time": 0, "thin_baseline": 0, "unstable": 0, "implausible": 0}

    for _, driver_laps in laps.groupby("Driver"):
        stint = driver_laps.sort_values("LapNumber").reset_index(drop=True)
        reference = stint[
            (stint.TrackStatus.astype(str).str.strip() == GREEN)
            & stint.IsAccurate
            & stint.PitInTime.isna()
            & stint.PitOutTime.isna()
        ]

        for index, lap in stint.iterrows():
            if pd.isna(lap.PitInTime) or index + 1 >= len(stint):
                continue
            out_lap = stint.iloc[index + 1]

            if not _is_green(lap.TrackStatus) or not _is_green(out_lap.TrackStatus):
                rejected["neutralised"] += 1
                continue

            in_time, out_time = _seconds(lap.LapTime), _seconds(out_lap.LapTime)
            if in_time is None or out_time is None:
                rejected["no_time"] += 1
                continue

            nearby = reference[
                (reference.LapNumber >= lap.LapNumber - WINDOW)
                & (reference.LapNumber <= out_lap.LapNumber + WINDOW)
            ]
            times = [t for t in (_seconds(x) for x in nearby.LapTime) if t is not None]
            if len(times) < MIN_REFERENCE_LAPS:
                rejected["thin_baseline"] += 1
                continue
            if statistics.pstdev(times) > MAX_REFERENCE_SD:
                rejected["unstable"] += 1
                continue

            baseline = statistics.median(times)
            loss = (in_time - baseline) + (out_time - baseline)
            if not MIN_LOSS <= loss <= MAX_LOSS:
                rejected["implausible"] += 1
                continue
            losses.append(loss)

    return losses, rejected


def collect(season: int, rnd: int) -> dict[str, Any] | None:
    session = fastf1.get_session(season, rnd, "R")
    # Messages are needed to identify penalty-serving stops.
    session.load(telemetry=False, weather=False, messages=True)

    # The live feed sends `ShortName`, so key on it where it is available and the
    # runtime lookup needs no translation. `Location` is kept alongside because
    # the safety-car history is keyed on it.
    try:
        meeting = session.session_info["Meeting"]
        circuit = str(meeting["Circuit"]["ShortName"])
        location = str(meeting["Location"])
        circuit_key = int(meeting["Circuit"]["Key"])
    except Exception:  # noqa: BLE001
        circuit = location = str(session.event["Location"])
        circuit_key = 0

    flagged = penalised_stops(session, session.laps)
    losses, rejected = stop_losses(drop_penalised(session.laps, flagged))
    rejected["penalty"] = len(flagged)
    if len(losses) < MIN_STOPS_PER_RACE:
        return {
            "season": season,
            "round": rnd,
            "event": str(session.event["EventName"]),
            "circuit": circuit,
            "location": location,
            "circuit_key": circuit_key,
            "n_stops": len(losses),
            "median_loss": None,
            "rejected": rejected,
        }

    ordered = sorted(losses)
    median = statistics.median(ordered)
    return {
        "season": season,
        "round": rnd,
        "event": str(session.event["EventName"]),
        "circuit": circuit,
        "location": location,
        "circuit_key": circuit_key,
        "n_stops": len(losses),
        "median_loss": round(median, 3),
        "q1": round(ordered[len(ordered) // 4], 3),
        "q3": round(ordered[3 * len(ordered) // 4], 3),
        "sd": round(statistics.pstdev(ordered), 3),
        # Each stop's excess over this race's own median. Subtracting the median
        # removes the circuit constant, so excesses pool across the calendar and
        # the tail can be fitted on all of them at once rather than on the five
        # races any one circuit provides.
        "excess": [round(x - median, 3) for x in ordered],
        "rejected": rejected,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=int, default=2022)
    parser.add_argument("--to", dest="end", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=Path("data/history/pit_loss.json"))
    parser.add_argument("--cache", default="cache")
    args = parser.parse_args()

    fastf1.Cache.enable_cache(args.cache)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    # Resumable for the same reason the safety-car fetch is: the F1 API allows
    # 500 calls an hour and a five-season sweep costs more than that from cold.
    existing: list[dict[str, Any]] = []
    if args.out.exists():
        existing = json.loads(args.out.read_text(encoding="utf-8"))
    done = {(r["season"], r["round"]) for r in existing}
    collected = list(existing)

    for year in range(args.start, args.end + 1):
        try:
            schedule = fastf1.get_event_schedule(year, include_testing=False)
        except Exception as exc:  # noqa: BLE001
            print(f"{year}: could not load schedule ({type(exc).__name__})")
            continue

        for _, event in schedule.iterrows():
            rnd = int(event["RoundNumber"])
            if (year, rnd) in done:
                continue
            try:
                record = collect(year, rnd)
            except Exception as exc:  # noqa: BLE001
                if is_rate_limit(exc):
                    print("rate limited - re-run in an hour, progress is saved")
                    args.out.write_text(json.dumps(collected, indent=2), encoding="utf-8")
                    return 0
                continue
            if record is None:
                continue

            collected.append(record)
            args.out.write_text(json.dumps(collected, indent=2), encoding="utf-8")
            median = record["median_loss"]
            shown = f"{median:6.2f}s" if median is not None else "  (thin)"
            print(f"{year} r{rnd:<2} {record['circuit']:<24} {shown}  n={record['n_stops']}")

    usable = [r for r in collected if r.get("median_loss") is not None]
    print(f"\n{len(collected)} races collected, {len(usable)} usable -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
