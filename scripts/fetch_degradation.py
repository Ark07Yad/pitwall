#!/usr/bin/env python3
"""Collect per-compound tyre degradation across many races, for a pooled prior.

A cliff needs stints long enough to contain one, and no single race provides
them. Zandvoort's longest hard stint was 36 laps; asked what lap 50 looks like,
a straight line fitted to that promises a tyre that lasts forever, and "stay
out" is precisely the option that benefits from the optimism. Teams pit *before*
the cliff, so the steep part of the curve is missing from any one race
*because* it is steep.

Pooling fixes what more data from one afternoon cannot. Somewhere in five
seasons a car ran 55 laps on a hard, and once those stints are in the same
dataset the curvature is identifiable.

**Making laps comparable across circuits.** A lap at Spa and a lap at Monaco
share no scale, so raw times cannot be pooled. What pools is the part of a lap
attributable to tyre age, which is recovered by fitting the nuisance structure
per race and subtracting it:

    delta = lap_time - (driver_pace + β·race_lap + compound_offset)

Everything circuit-specific - the base lap time, the fuel-and-evolution trend,
each compound's baseline - is in the part subtracted. What is left is degradation
plus noise, in seconds, and means the same thing everywhere.

The nuisance fit carries **both** age terms, and that is not a detail. A linear
one looks sufficient - the residual keeps whatever the line missed, so the delta
should still hold the whole age effect - but it is not, because a quadratic in
tyre age is partly *collinear* with the things being subtracted. Its mean is
absorbed by the compound offset, and the part that trends with race lap is
absorbed by the fuel term. Subtract those and a real cliff goes with them.

Measured against synthetic data with a known cliff of 0.00250: a linear-only
nuisance fit recovers 0.00098, losing 61% of the curvature and inflating the
linear rate from 0.040 to 0.093 to compensate. Carrying `age²` through the
nuisance fit and zeroing both age columns recovers 0.00214.

    python scripts/fetch_degradation.py --from 2022 --to 2026

Output: data/history/degradation.json - per race, per compound, per tyre age, a
count and mean delta. Aggregating by age keeps the file small while preserving
everything a weighted fit needs.
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")
logging.getLogger("fastf1").setLevel(logging.ERROR)

import fastf1  # noqa: E402
import numpy as np  # noqa: E402

GREEN = "1"
# Below this a race cannot support a decomposition worth pooling.
MIN_LAPS = 60
# A lap this far from its race's median is a mistake, a spin, or a lift, not a
# tyre. Degradation is a tenths-per-lap effect and these swamp it.
MAX_DELTA = 8.0


def is_rate_limit(exc: Exception) -> bool:
    return type(exc).__name__ == "RateLimitExceededError" or "calls/h" in str(exc)


def clean_laps(laps: Any) -> Any:
    """Green, accurate, non-pit laps with a compound and an age.

    Note this is weaker than the engine's own clean-lap filter, which also drops
    laps run in dirty air. FastF1 does not carry a per-lap gap to the car ahead,
    so traffic cannot be excluded here. It adds noise rather than bias to a
    degradation slope, but it is a real difference from the in-session fit and
    the pooled prior is a little flatter for it.
    """
    return laps[
        (laps.TrackStatus.astype(str).str.strip() == GREEN)
        & laps.IsAccurate
        & laps.PitInTime.isna()
        & laps.PitOutTime.isna()
        & laps.LapTime.notna()
        & laps.Compound.notna()
        & laps.TyreLife.notna()
    ]


def age_deltas(laps: Any) -> dict[str, dict[int, list[float]]]:
    """Time attributable to tyre age, per compound and age, for one race."""
    rows = []
    for _, lap in laps.iterrows():
        compound = str(lap.Compound).upper()
        if compound in {"INTERMEDIATE", "WET", "UNKNOWN", "NAN"}:
            continue
        rows.append(
            (
                str(lap.Driver),
                int(lap.LapNumber),
                compound,
                int(lap.TyreLife),
                float(lap.LapTime.total_seconds()),
            )
        )
    if len(rows) < MIN_LAPS:
        return {}

    drivers = sorted({r[0] for r in rows})
    compounds = sorted({r[2] for r in rows})
    if len(compounds) < 2:
        # One compound cannot separate its own offset from the driver intercepts.
        return {}
    reference = max(compounds, key=lambda c: sum(1 for r in rows if r[2] == c))
    others = [c for c in compounds if c != reference]

    driver_at = {d: i for i, d in enumerate(drivers)}
    lap_col = len(drivers)
    age_at = {c: lap_col + 1 + i for i, c in enumerate(compounds)}
    offset_at = {c: lap_col + 1 + len(compounds) + i for i, c in enumerate(others)}
    base = lap_col + 1 + len(compounds) + len(others)
    curve_at = {c: base + i for i, c in enumerate(compounds)}
    n_cols = base + len(compounds)

    x = np.zeros((len(rows), n_cols))
    y = np.empty(len(rows))
    for i, (driver, lap_no, compound, age, seconds) in enumerate(rows):
        x[i, driver_at[driver]] = 1.0
        x[i, lap_col] = lap_no
        x[i, age_at[compound]] = age
        # Scaled to keep the column on the same order as the linear ones;
        # squared age reaches ~6,000 where lap number reaches 70.
        x[i, curve_at[compound]] = (age * age) / 100.0
        if compound in offset_at:
            x[i, offset_at[compound]] = 1.0
        y[i] = seconds

    coefficients, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    if rank < n_cols:
        return {}

    # Everything except the age terms is nuisance. Both age columns are zeroed,
    # so the delta carries the whole age effect - see the note above on why
    # leaving the quadratic in the nuisance would eat most of the cliff.
    nuisance = x.copy()
    for column in list(age_at.values()) + list(curve_at.values()):
        nuisance[:, column] = 0.0
    deltas = y - nuisance @ coefficients

    out: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (_, _, compound, age, _), delta in zip(rows, deltas, strict=True):
        if abs(delta) <= MAX_DELTA:
            out[compound][age].append(float(delta))
    return out


def wet_share(laps: Any) -> float:
    """Share of the field's laps run on a wet-weather tyre.

    A drying race is worse for this decomposition than a wet one. The wet laps
    themselves are dropped by compound, but the slick laps around them survive,
    and the single linear `race_lap` term then fits the drying trend rather than
    fuel burn. Whatever it fits is subtracted from every lap, and what is left
    over is attributed to tyre age.
    """
    if laps is None or not len(laps):
        return 0.0
    compounds = laps.Compound.astype(str).str.upper()
    return float(compounds.isin({"INTERMEDIATE", "WET"}).mean())


def collect(season: int, rnd: int) -> dict[str, Any] | None:
    session = fastf1.get_session(season, rnd, "R")
    session.load(telemetry=False, weather=False, messages=False)

    try:
        meeting = session.session_info["Meeting"]
        circuit = str(meeting["Circuit"]["ShortName"])
        location = str(meeting["Location"])
    except Exception:  # noqa: BLE001
        circuit = location = str(session.event["Location"])

    deltas = age_deltas(clean_laps(session.laps))
    if not deltas:
        return None

    buckets = []
    for compound, by_age in deltas.items():
        for age, values in sorted(by_age.items()):
            buckets.append(
                {
                    "compound": compound[:3],
                    "age": age,
                    "n": len(values),
                    "mean": round(float(np.mean(values)), 4),
                }
            )
    return {
        "season": season,
        "round": rnd,
        "event": str(session.event["EventName"]),
        "circuit": circuit,
        "location": location,
        "n_laps": sum(b["n"] for b in buckets),
        "max_age": max(b["age"] for b in buckets),
        # Recorded so the fit can exclude a race whose decomposition cannot be
        # trusted, on a criterion measured here rather than on the sign of the
        # number being estimated. See `models/degradation.py`.
        "wet_share": round(wet_share(session.laps), 4),
        "buckets": buckets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="start", type=int, default=2022)
    parser.add_argument("--to", dest="end", type=int, default=2026)
    parser.add_argument("--out", type=Path, default=Path("data/history/degradation.json"))
    parser.add_argument("--cache", default="cache")
    args = parser.parse_args()

    fastf1.Cache.enable_cache(args.cache)
    args.out.parent.mkdir(parents=True, exist_ok=True)

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
                    args.out.write_text(json.dumps(collected), encoding="utf-8")
                    return 0
                continue
            if record is None:
                continue
            collected.append(record)
            args.out.write_text(json.dumps(collected), encoding="utf-8")
            print(
                f"{year} r{rnd:<2} {record['circuit']:<24} "
                f"{record['n_laps']:>5} laps, max age {record['max_age']}"
            )

    print(f"\n{len(collected)} races -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
