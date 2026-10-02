"""Degradation from practice long runs, the way a team reads a Friday.

For a circuit with no racing history every per-circuit model falls back to the
field average, and the only laps that exist on that surface before the race are
practice laps. `fit_pace` cannot read them: it takes the race-lap number as a
proxy for fuel load, and in practice fuel is reset between runs - a low-fuel
qualifying simulation sits between two high-fuel long runs - so lap number
carries no fuel information at all. Run against the 2026 Spanish GP practice it
returned trends of +0.71 and +1.54 s/lap and refused, correctly.

This fits the thing practice can actually support:

- **Long runs only.** A three-lap run is a push lap, an out lap and an in lap.
  Degradation is a within-run slope and needs a run to be a slope over.
- **Fuel corrected from the physics prior, not fitted.** Within one run, laps
  into the run and tyre age advance together, so no estimator can separate fuel
  burn from tyre wear inside it. The fuel effect is therefore *subtracted* at the
  published sensitivity rather than estimated, and what remains is attributed to
  the tyre.
- **An intercept per run.** Runs start on different fuel loads and different
  tyre conditions, and a new set at the end of the session is not the same
  baseline as a scrubbed one at the start. Pooling their levels would read the
  difference between runs as degradation.
- **No race-lap term.** There is no race.

**The fuel correction is an assumption, and the result is conditional on it.**
Laps into a run and tyre age are the same column inside a run, so the slope this
returns moves one-for-one with the correction applied: a fuel figure 0.01 s/lap
too small leaves 0.01 s/lap of fuel in the degradation estimate. `sensitivity`
reports that directly instead of leaving the reader to assume the number is
unconditional. It is the reason this is a Friday estimate and not a measurement.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pitwall.laps.records import LapRecord
from pitwall.models.fuel import DEFAULT_SECONDS_PER_KG, DEFAULT_START_FUEL_KG
from pitwall.state.models import Compound

# Clean laps a run needs before it counts as a long run. Below this the "run" is
# an out lap, a push lap and an in lap, and its slope is noise.
MIN_RUN_LAPS = 5
# Long runs needed in total. One run gives one slope with nothing to check it
# against; the spread across runs is the only error bar available here.
MIN_RUNS = 2
# Distinct tyre ages a compound needs before a slope exists for it at all - the
# same rank condition `fit_pace` applies, for the same reason.
MIN_AGES_FOR_SLOPE = 2
# Fuel burn to assume per lap. A 2026 car's allowance over a mid-length race;
# practice runs are not fuelled to a race distance but the burn *rate* is set by
# the flow limit, not by how much is in the tank.
NOMINAL_RACE_LAPS = 54
NOMINAL_BURN_PER_LAP_KG = DEFAULT_START_FUEL_KG / NOMINAL_RACE_LAPS
# A practice long run that reads steeper than this is not a tyre. Sepang in
# September is 1.0 s/lap of nothing; the cap is the same one `fit_pace` uses.
MAX_DEGRADATION = 1.0


@dataclass(frozen=True)
class LongRun:
    """One driver's stint, long enough to carry a slope."""

    driver: str
    stint: int
    compound: Compound
    laps: int
    first_age: int
    last_age: int


@dataclass
class LongRunFit:
    """Per-compound degradation read off practice long runs."""

    degradation: dict[Compound, float]
    runs: tuple[LongRun, ...]
    laps_per_compound: Counter
    seconds_per_lap_of_fuel: float
    residual_std: float
    r_squared: float
    n_laps: int
    warnings: tuple[str, ...] = field(default=())

    @property
    def n_runs(self) -> int:
        return len(self.runs)

    def sensitivity(self, fraction: float = 0.25) -> dict[Compound, tuple[float, float]]:
        """How far each slope moves if the assumed fuel effect is off.

        Inside a run the two effects are one column, so an error in the
        correction passes straight into the slope. This returns what the slope
        would have been with the fuel figure `fraction` smaller and larger -
        the honest width of a Friday number.
        """
        delta = self.seconds_per_lap_of_fuel * fraction
        return {c: (rate - delta, rate + delta) for c, rate in self.degradation.items()}

    def factor_against(self, prior: Any) -> tuple[float | None, list[tuple[Compound, float, int]]]:
        """Lap-weighted scale against a pooled prior's shape.

        Weighted by laps, because a compound seen on six laps should not vote as
        loudly as one seen on sixty.
        """
        ratios: list[tuple[Compound, float, int]] = []
        for compound, rate in self.degradation.items():
            pooled = prior.linear.get(compound)
            n = int(self.laps_per_compound.get(compound, 0))
            if not pooled or n == 0:
                continue
            ratios.append((compound, rate / pooled, n))
        if not ratios:
            return None, []
        total = sum(n for _, _, n in ratios)
        return sum(r * n for _, r, n in ratios) / total, ratios

    @property
    def unusable_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if any("rank deficient" in w for w in self.warnings):
            reasons.append("run intercepts and tyre age are not separately identified")
        for compound, rate in self.degradation.items():
            if rate < 0:
                reasons.append(
                    f"{compound.short} degradation of {rate:+.4f} s/lap is negative - a tyre "
                    "that improves with age, so the fuel correction is carrying the run"
                )
            elif rate > MAX_DEGRADATION:
                reasons.append(f"{compound.short} degradation of {rate:+.2f} s/lap is out of range")
        return tuple(reasons)

    @property
    def usable(self) -> bool:
        return not self.unusable_reasons

    def __str__(self) -> str:
        lines = [
            f"fitted on {self.n_laps:,} clean laps in {self.n_runs} long runs"
            f" (fuel removed at {self.seconds_per_lap_of_fuel:.4f} s/lap)",
            f"  residual std     {self.residual_std:.3f} s",
            f"  r-squared        {self.r_squared:.3f}",
            "",
            "  degradation (s per lap of tyre age), by compound:",
        ]
        spread = self.sensitivity()
        for compound, rate in sorted(self.degradation.items(), key=lambda kv: -kv[1]):
            low, high = spread[compound]
            n = int(self.laps_per_compound.get(compound, 0))
            lines.append(
                f"    {compound.short}  {rate:+.4f} s/lap   on {n:>3} laps"
                f"   ±25% fuel: {low:+.4f} to {high:+.4f}"
            )
        for run in sorted(self.runs, key=lambda r: (r.compound.short, r.driver)):
            lines.append(
                f"    run  {run.driver:>3} stint {run.stint}  {run.compound.short}"
                f"  {run.laps:>2} laps, age {run.first_age}-{run.last_age}"
            )
        for warning in self.warnings:
            lines.append(f"  ! {warning}")
        for reason in self.unusable_reasons:
            lines.append(f"  ✗ UNUSABLE: {reason}")
        return "\n".join(lines)


def long_runs(laps: list[LapRecord], *, min_run_laps: int = MIN_RUN_LAPS) -> list[LongRun]:
    """The stints in this session with enough clean laps to carry a slope."""
    grouped: dict[tuple[str, int], list[LapRecord]] = defaultdict(list)
    for lap in laps:
        if lap.lap_time is None or lap.compound is Compound.UNKNOWN:
            continue
        grouped[(lap.driver, lap.stint)].append(lap)

    found: list[LongRun] = []
    for (driver, stint), run in sorted(grouped.items()):
        if len(run) < min_run_laps:
            continue
        ages = [lap.tyre_age for lap in run]
        found.append(
            LongRun(
                driver=driver,
                stint=stint,
                compound=run[0].compound,
                laps=len(run),
                first_age=min(ages),
                last_age=max(ages),
            )
        )
    return found


def fit_long_runs(
    laps: list[LapRecord],
    *,
    min_run_laps: int = MIN_RUN_LAPS,
    seconds_per_kg: float = DEFAULT_SECONDS_PER_KG,
    burn_per_lap_kg: float = NOMINAL_BURN_PER_LAP_KG,
) -> LongRunFit | None:
    """Fit per-compound degradation from the long runs in a practice session.

    Expects laps already through the clean-lap filter. Returns None when there
    are not two long runs to fit, which at a wet or disrupted session is the
    ordinary outcome rather than a fault.
    """
    runs = long_runs(laps, min_run_laps=min_run_laps)
    if len(runs) < MIN_RUNS:
        return None

    keep = {(run.driver, run.stint) for run in runs}
    usable = [
        lap
        for lap in laps
        if (lap.driver, lap.stint) in keep
        and lap.lap_time is not None
        and lap.compound is not Compound.UNKNOWN
    ]
    if not usable:
        return None

    # Laps into the run, which is what fuel depends on - not tyre age, which may
    # start partway up on a scrubbed set. The two differ by a constant inside a
    # run, and the run's own intercept absorbs the constant.
    first_lap: dict[tuple[str, int], int] = {}
    for lap in usable:
        key = (lap.driver, lap.stint)
        first_lap[key] = min(first_lap.get(key, lap.lap), lap.lap)

    fuel_per_lap = seconds_per_kg * burn_per_lap_kg
    warnings: list[str] = []

    compounds = sorted({lap.compound for lap in usable}, key=lambda c: c.value)
    ages_seen = {c: {lap.tyre_age for lap in usable if lap.compound is c} for c in compounds}
    flat = [c for c in compounds if len(ages_seen[c]) < MIN_AGES_FOR_SLOPE]
    if flat:
        names = ", ".join(sorted(c.short for c in flat))
        warnings.append(
            f"{names} has fewer than {MIN_AGES_FOR_SLOPE} distinct tyre ages across its runs, "
            "so no slope exists for it; it is left out of the fit"
        )
    aged = [c for c in compounds if c not in flat]
    if not aged:
        return None

    run_keys = sorted({(lap.driver, lap.stint) for lap in usable if lap.compound in set(aged)})
    run_index = {key: i for i, key in enumerate(run_keys)}
    age_index = {c: len(run_keys) + i for i, c in enumerate(aged)}
    n_cols = len(run_keys) + len(aged)

    rows = [lap for lap in usable if lap.compound in set(aged)]
    x = np.zeros((len(rows), n_cols))
    y = np.empty(len(rows))
    for row, lap in enumerate(rows):
        key = (lap.driver, lap.stint)
        x[row, run_index[key]] = 1.0
        x[row, age_index[lap.compound]] = lap.tyre_age
        # Add the fuel gain back on, so what is left to explain is the tyre.
        # Later laps in a run were run lighter and are faster for that reason.
        into_run = lap.lap - first_lap[key]
        y[row] = lap.lap_time + fuel_per_lap * into_run

    coefficients, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    if rank < n_cols:
        warnings.append(
            f"design matrix is rank deficient ({rank} of {n_cols}) - "
            "some effects are not separately identified"
        )

    predicted = x @ coefficients
    residuals = y - predicted
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))

    degradation = {c: float(coefficients[i]) for c, i in age_index.items()}
    kept_runs = tuple(run for run in runs if (run.driver, run.stint) in run_index)
    if len({run.compound for run in kept_runs}) == 1:
        warnings.append(
            "every long run is on the same compound, so the circuit scale rests on one tyre"
        )

    return LongRunFit(
        degradation=degradation,
        runs=kept_runs,
        laps_per_compound=Counter(lap.compound for lap in rows),
        seconds_per_lap_of_fuel=fuel_per_lap,
        residual_std=float(np.std(residuals, ddof=min(n_cols, len(rows) - 1))),
        r_squared=(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0,
        n_laps=len(rows),
        warnings=tuple(warnings),
    )
