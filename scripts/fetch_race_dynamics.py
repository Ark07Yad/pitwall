#!/usr/bin/env python3
"""Measure how hard it is to pass, and what a stop costs under a safety car.

Two numbers in the strategy simulation were set by hand and applied to every
circuit alike, and they sit where pit decisions are closest: whether a car that
stops can get back past the cars it drops behind, and how much cheaper a stop is
while the field is neutralised. This reads both out of every cached race.

    python scripts/fetch_race_dynamics.py --from 2022 --to 2026

**Passing.** A *follower* is a car that starts a green lap within `FOLLOW`
seconds of the car ahead, neither of them pitting on that lap or the one before.
For each, record whether it was ahead at the end of the lap, and how much quicker
it was than the car it was following - not on that lap, where a held-up car
laps at the speed of the car holding it, but by a pace fit of the whole race on
laps in clear air: driver, compound, tyre age and race lap. That is the quantity
the simulation compares when it decides a pass, so the two are measured alike.

**Neutralised stops.** A green stop is measured against the driver's own
surrounding laps (`fetch_pit_loss.py`). Under a safety car there are no such
laps, so every stop here - green, SC and VSC alike - is measured against the
*field on the same two laps*: in-lap plus out-lap, less the median of the same
two laps for every car that did not stop. The green ones are the check that the
method agrees with the established constant; the ratio of neutralised to green
within one race is the discount, with the circuit cancelling.

A stop counts as SC if the safety car was out at some point on both its in-lap
and its out-lap - which takes in the commonest case, the car that dives in on
the lap it is deployed - and as VSC on the same terms with no safety car on
either lap. The field's same two laps carry the same mix of statuses, so the
comparison stays like for like. A stop with green on one side is neither, and is
dropped rather than guessed at.

Output: data/history/overtaking.json and data/history/neutralised_stops.json,
one record per race, resumable, keyed on the circuit name the live feed sends.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np

warnings.filterwarnings("ignore")
logging.getLogger("fastf1").setLevel(logging.ERROR)

import fastf1  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_pit_loss import drop_penalised, is_rate_limit, penalised_stops  # noqa: E402

# Within this of the car ahead at the line is following: inside the range where
# a pass is on, and where the simulation pins a car that fails one.
FOLLOW = 1.0
# A lap starting further than this behind anyone is clear air, and only those
# laps feed the pace fit - a held-up lap measures the car in front.
CLEAR_AIR = 2.0
# Advantage is recorded in bins this wide; enough resolution for a slope, and
# small files.
BIN = 0.05
DRY = ("SOFT", "MEDIUM", "HARD")
# A race with more running than this on intermediates or wets is not a dry race
# with a shower in it, and its passes are a different sport.
MAX_WET_SHARE = 0.10
MIN_FIELD = 5
MIN_STOPS = 1

GREEN, SC = {"1"}, {"4"}
VSC = {"6", "7"}


def _codes(value: Any) -> set[str]:
    return set(str(value).strip()) if not pd.isna(value) else set()


def _seconds(value: Any) -> float:
    return float("nan") if pd.isna(value) else float(value.total_seconds())


def prepare(laps: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "driver": laps.DriverNumber.astype(str),
            "lap": laps.LapNumber.astype(int),
            "time": [_seconds(t) for t in laps.Time],
            "lap_time": [_seconds(t) for t in laps.LapTime],
            "compound": laps.Compound.astype(str).str.upper(),
            "age": pd.to_numeric(laps.TyreLife, errors="coerce"),
            "pit_in": laps.PitInTime.notna(),
            "pit_out": laps.PitOutTime.notna(),
            "codes": [_codes(s) for s in laps.TrackStatus],
            "accurate": laps.IsAccurate.fillna(False).astype(bool),
        }
    )
    return frame.sort_values(["lap", "time"]).reset_index(drop=True)


def gaps_ahead(frame: pd.DataFrame) -> pd.Series:
    """Seconds to the car ahead at the end of each lap, on the same lap number."""
    ordered = frame.sort_values(["lap", "time"])
    return ordered.groupby("lap")["time"].diff().reindex(frame.index)


def fit_race_pace(frame: pd.DataFrame) -> dict[str, Any] | None:
    """Clear-air pace by driver, compound, tyre age and race lap."""
    frame = frame.copy()
    # Whether a lap *started* in clear air is the gap at the end of the lap before.
    gap = gaps_ahead(frame)
    frame["gap_end"] = gap
    previous = frame[["driver", "lap", "gap_end"]].copy()
    previous["lap"] += 1
    frame = frame.merge(
        previous.rename(columns={"gap_end": "gap_start"}), on=["driver", "lap"], how="left"
    )

    times = frame.lap_time
    clean = frame[
        frame.codes.apply(lambda c: c == GREEN)
        & frame.accurate
        & ~frame.pit_in
        & ~frame.pit_out
        & (frame.lap > 1)
        & frame.compound.isin(DRY)
        & frame.age.notna()
        & times.notna()
        & (frame.gap_start.isna() | (frame.gap_start > CLEAR_AIR))
    ]
    if len(clean) < 200:
        return None
    clean = clean[clean.lap_time < 1.07 * clean.lap_time.median()]

    drivers = sorted(clean.driver.unique())
    compounds = [c for c in DRY if (clean.compound == c).any()]
    columns = len(drivers) + 2 * len(compounds) - 1 + 1
    design = np.zeros((len(clean), columns))
    d_index = {d: i for i, d in enumerate(drivers)}
    for row, (driver, compound, age, lap) in enumerate(
        zip(clean.driver, clean.compound, clean.age, clean.lap, strict=True)
    ):
        design[row, d_index[driver]] = 1.0
        c = compounds.index(compound)
        if c > 0:
            design[row, len(drivers) + c - 1] = 1.0
        design[row, len(drivers) + len(compounds) - 1 + c] = age
        design[row, -1] = lap
    coef, *_ = np.linalg.lstsq(design, clean.lap_time.to_numpy(), rcond=None)
    return {
        "driver": {d: coef[i] for d, i in d_index.items()},
        "offset": {c: (coef[len(drivers) + i - 1] if i else 0.0) for i, c in enumerate(compounds)},
        "slope": {c: coef[len(drivers) + len(compounds) - 1 + i] for i, c in enumerate(compounds)},
        "trend": coef[-1],
    }


def predicted(fit: dict[str, Any], driver: str, compound: str, age: float, lap: int) -> float:
    if driver not in fit["driver"] or compound not in fit["offset"] or pd.isna(age):
        return float("nan")
    return (
        fit["driver"][driver]
        + fit["offset"][compound]
        + fit["slope"][compound] * age
        + fit["trend"] * lap
    )


def followers(frame: pd.DataFrame, fit: dict[str, Any]) -> list[tuple[float, bool]]:
    """(advantage over the car ahead, passed it) for every green following lap."""
    rows_by = zip(frame.driver, frame.lap, frame.itertuples(), strict=True)
    by_key = {(d, n): row for d, n, row in rows_by}
    out: list[tuple[float, bool]] = []
    for lap in sorted(frame.lap.unique()):
        if lap < 3:
            continue
        before = frame[(frame.lap == lap - 1) & frame.time.notna()].sort_values("time")
        drivers = list(before.driver)
        times = list(before.time)
        for i in range(1, len(drivers)):
            ahead, behind = drivers[i - 1], drivers[i]
            if times[i] - times[i - 1] >= FOLLOW:
                continue
            rows = [by_key.get((d, n)) for d in (ahead, behind) for n in (lap - 1, lap)]
            if any(r is None for r in rows):
                continue
            if any(r.pit_in or r.pit_out or r.codes != GREEN for r in rows):
                continue
            a_now, b_now = rows[1], rows[3]
            if pd.isna(a_now.time) or pd.isna(b_now.time):
                continue
            advantage = predicted(fit, ahead, a_now.compound, a_now.age, lap) - predicted(
                fit, behind, b_now.compound, b_now.age, lap
            )
            if np.isnan(advantage):
                continue
            out.append((float(advantage), bool(b_now.time < a_now.time)))
    return out


def binned(pairs: list[tuple[float, bool]]) -> dict[str, list[float]]:
    counts: dict[float, list[int]] = {}
    for advantage, passed in pairs:
        centre = round(round(advantage / BIN) * BIN, 3)
        cell = counts.setdefault(centre, [0, 0])
        cell[0] += 1
        cell[1] += int(passed)
    keys = sorted(counts)
    return {
        "advantage": keys,
        "n": [counts[k][0] for k in keys],
        "passed": [counts[k][1] for k in keys],
    }


def stop_losses(frame: pd.DataFrame) -> dict[str, list[float]]:
    """Each stop against the field on its own two laps, split by track status."""
    by_lap = {lap: group for lap, group in frame.groupby("lap")}
    out: dict[str, list[float]] = {"green": [], "sc": [], "vsc": []}
    for row in frame[frame.pit_in].itertuples():
        nxt = frame[(frame.driver == row.driver) & (frame.lap == row.lap + 1)]
        if nxt.empty:
            continue
        out_lap = nxt.iloc[0]
        codes = (row.codes, out_lap.codes)
        if all(c == GREEN for c in codes):
            kind = "green"
        elif all(c & SC for c in codes):
            kind = "sc"
        elif all(c & VSC for c in codes) and not any(c & SC for c in codes):
            kind = "vsc"
        else:
            continue
        own = row.lap_time + out_lap.lap_time
        if np.isnan(own):
            continue
        first, second = by_lap.get(row.lap), by_lap.get(row.lap + 1)
        if first is None or second is None:
            continue
        stayed = (
            first[~first.pit_in & ~first.pit_out][["driver", "lap_time"]]
            .merge(second[~second.pit_in & ~second.pit_out][["driver", "lap_time"]], on="driver")
            .dropna()
        )
        stayed = stayed[stayed.driver != row.driver]
        if len(stayed) < MIN_FIELD:
            continue
        field = float((stayed.lap_time_x + stayed.lap_time_y).median())
        loss = own - field
        # Penalties and damage read as enormous stops; anything over a minute is
        # not a tyre change.
        if -5.0 <= loss <= 60.0:
            out[kind].append(round(loss, 3))
    return out


def collect(season: int, rnd: int) -> tuple[dict[str, Any], dict[str, Any]] | None:
    session = fastf1.get_session(season, rnd, "R")
    session.load(telemetry=False, weather=False, messages=True)
    laps = session.laps
    if laps is None or laps.empty:
        return None
    try:
        meeting = session.session_info["Meeting"]
        circuit = str(meeting["Circuit"]["ShortName"])
    except Exception:  # noqa: BLE001
        circuit = str(session.event["Location"])
    event = str(session.event["EventName"])
    head = {"season": season, "round": rnd, "event": event, "circuit": circuit}

    laps = drop_penalised(laps, penalised_stops(session, laps))
    frame = prepare(laps)
    wet = frame.compound.isin(("INTERMEDIATE", "WET")).mean()

    passing: dict[str, Any] = {**head, "wet_share": round(float(wet), 3)}
    if wet > MAX_WET_SHARE:
        passing["skipped"] = "wet"
    else:
        fit = fit_race_pace(frame)
        if fit is None:
            passing["skipped"] = "too few clear-air laps to fit pace"
        else:
            pairs = followers(frame, fit)
            passing.update(
                {
                    "followers": len(pairs),
                    "passes": sum(p for _, p in pairs),
                    **binned(pairs),
                }
            )

    stops = {**head, **stop_losses(frame)}
    return passing, stops


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=int, default=2022)
    parser.add_argument("--to", dest="end", type=int, default=2026)
    parser.add_argument("--overtaking", type=Path, default=Path("data/history/overtaking.json"))
    parser.add_argument("--stops", type=Path, default=Path("data/history/neutralised_stops.json"))
    parser.add_argument("--cache", default="cache")
    args = parser.parse_args()

    fastf1.Cache.enable_cache(args.cache)

    def read(path: Path) -> list[dict[str, Any]]:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    passing, stops = read(args.overtaking), read(args.stops)
    done = {(r["season"], r["round"]) for r in passing}

    def save() -> None:
        for path, rows in ((args.overtaking, passing), (args.stops, stops)):
            ordered = sorted(rows, key=lambda r: (r["season"], r["round"]))
            path.write_text(json.dumps(ordered, indent=1) + "\n", encoding="utf-8")

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
                    save()
                    return 0
                print(f"{year} r{rnd:<2} skipped ({type(exc).__name__}: {exc})"[:120])
                continue
            if record is None:
                continue
            p, s = record
            passing.append(p)
            stops.append(s)
            save()
            note = p.get("skipped") or f"{p['passes']}/{p['followers']} passes"
            print(
                f"{year} r{rnd:<2} {p['circuit']:<22} {note:<34} "
                f"stops green {len(s['green'])} sc {len(s['sc'])} vsc {len(s['vsc'])}"
            )
    save()
    print(f"\n{len(passing)} races -> {args.overtaking}, {args.stops}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
