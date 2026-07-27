"""Joint decomposition of lap time into pace, fuel trend and tyre degradation.

Fuel and degradation cannot be estimated one after the other. Within a single
stint they are perfectly collinear - the car gets a lap lighter at exactly the
rate the tyre gets a lap older - so no amount of data from one stint can tell
them apart.

What separates them is the *stint structure*. Fuel depends on the race lap and
falls monotonically all afternoon; tyre age resets to zero at every pit stop. Fit
both at once against laps spanning multiple stints and the two are identified:

    lap_time = pace(driver) + β·race_lap + Σ_c δ_c + Σ_c α_c·tyre_age + ε

`β` is negative - cars get faster. It absorbs everything that trends with race
lap, which is fuel burn *plus* track evolution as rubber goes down, so it is not
purely fuel and is not named as though it were. `α_c` is the degradation rate per
compound, and is what the strategy model actually needs.

`δ_c` is the compound's baseline offset, and leaving it out is a trap worth
describing because the fit looks fine without it. A hard tyre is inherently
slower than a soft at the *same* age. With no intercept per compound the model
predicts identical times for every compound at age zero, so the only way it can
push hard-tyre predictions up is to inflate `α_hard`. The first version of this
module did exactly that and reported the hard degrading faster than the soft -
a plausible-looking number that was pure misspecification. Offsets are measured
against a reference compound, since one of them is collinear with the driver
intercepts.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from pitwall.laps.records import LapRecord
from pitwall.state.models import Compound

# Below this many laps the fit is not worth reporting; coefficients swing wildly.
MIN_LAPS = 30
# Distinct stints needed before fuel and degradation are separable at all.
MIN_STINTS = 2
# If two compounds' median race laps sit further apart than this fraction of the
# race, each one effectively occupies its own phase and its degradation cannot be
# told apart from whatever else trends with race lap.
PHASE_SEPARATION_LIMIT = 0.35


@dataclass(frozen=True)
class PaceFit:
    """Result of decomposing a set of clean laps."""

    race_lap_coef: float
    degradation: dict[Compound, float]
    compound_offset: dict[Compound, float]
    reference_compound: Compound
    compound_phase: dict[Compound, float]
    driver_pace: dict[str, float]
    n_laps: int
    n_stints: int
    residual_std: float
    r_squared: float
    warnings: tuple[str, ...] = field(default=())

    @property
    def seconds_per_lap_from_fuel(self) -> float:
        """Magnitude of the per-lap gain. Positive for readability."""
        return abs(self.race_lap_coef)

    def implied_seconds_per_kg(self, burn_per_lap_kg: float) -> float:
        """Convert the fitted trend into a fuel sensitivity for cross-checking.

        Published values sit around 0.030-0.040 s/kg. Landing far outside that
        means the trend is picking up more than fuel - most likely heavy track
        evolution, or a race whose stint structure was too uniform to separate
        the two cleanly.
        """
        if burn_per_lap_kg <= 0:
            return float("nan")
        return self.seconds_per_lap_from_fuel / burn_per_lap_kg

    def degradation_for(self, compound: Compound) -> float | None:
        return self.degradation.get(compound)

    def __str__(self) -> str:
        lines = [
            f"fitted on {self.n_laps:,} clean laps across {self.n_stints} stints",
            f"  race-lap trend   {self.race_lap_coef:+.4f} s/lap (fuel burn + track evolution)",
            f"  residual std     {self.residual_std:.3f} s",
            f"  r-squared        {self.r_squared:.3f}",
            "",
            f"  degradation (s per lap of tyre age), offset vs {self.reference_compound.short}:",
        ]
        for compound, rate in sorted(self.degradation.items(), key=lambda kv: -kv[1]):
            offset = self.compound_offset.get(compound, 0.0)
            lines.append(f"    {compound.short}  {rate:+.4f} s/lap   baseline {offset:+.3f} s")
        for warning in self.warnings:
            lines.append(f"  ! {warning}")
        return "\n".join(lines)


def fit_pace(laps: list[LapRecord]) -> PaceFit | None:
    """Fit the decomposition. Returns None if there is not enough to fit.

    Expects laps that have already been through the clean-lap filter; feeding it
    in-laps or safety-car laps produces confident nonsense.
    """
    usable = [lap for lap in laps if lap.lap_time is not None and lap.lap >= 1]
    if len(usable) < MIN_LAPS:
        return None

    drivers = sorted({lap.driver for lap in usable})
    compounds = sorted(
        {lap.compound for lap in usable if lap.compound is not Compound.UNKNOWN},
        key=lambda c: c.value,
    )
    if not compounds:
        return None

    stints = {(lap.driver, lap.stint) for lap in usable}
    warnings: list[str] = []
    if len(stints) < MIN_STINTS:
        warnings.append(
            "only one stint in the data - fuel and degradation are collinear "
            "and cannot be separated"
        )

    # The most-used compound is the reference: its offset is folded into the
    # driver intercepts, and every other offset is measured against it. Picking
    # the best-sampled compound keeps that baseline as stable as possible.
    usage = Counter(lap.compound for lap in usable if lap.compound in set(compounds))
    reference = usage.most_common(1)[0][0]
    offset_compounds = [c for c in compounds if c is not reference]

    driver_index = {d: i for i, d in enumerate(drivers)}
    lap_col = len(drivers)
    age_index = {c: lap_col + 1 + i for i, c in enumerate(compounds)}
    offset_index = {c: lap_col + 1 + len(compounds) + i for i, c in enumerate(offset_compounds)}
    n_cols = lap_col + 1 + len(compounds) + len(offset_compounds)

    x = np.zeros((len(usable), n_cols))
    y = np.empty(len(usable))

    for row, lap in enumerate(usable):
        x[row, driver_index[lap.driver]] = 1.0
        x[row, lap_col] = lap.lap
        age_column = age_index.get(lap.compound)
        if age_column is not None:
            x[row, age_column] = lap.tyre_age
        offset_column = offset_index.get(lap.compound)
        if offset_column is not None:
            x[row, offset_column] = 1.0
        y[row] = lap.lap_time

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

    race_lap_coef = float(coefficients[lap_col])
    if race_lap_coef > 0:
        warnings.append(
            f"race-lap trend is positive ({race_lap_coef:+.4f} s/lap) - cars "
            "should get faster as fuel burns off; check the input laps"
        )

    degradation = {c: float(coefficients[i]) for c, i in age_index.items()}
    compound_offset = {reference: 0.0}
    compound_offset.update({c: float(coefficients[i]) for c, i in offset_index.items()})

    # Teams do not scatter compounds evenly through a race - they run one early
    # and another late. When they do, "degradation on the soft" and "whatever
    # happens late in the race" are the same column of the design matrix, and no
    # amount of data from a single race separates them.
    phase = {
        c: float(np.median([lap.lap for lap in usable if lap.compound is c])) for c in compounds
    }
    race_span = max((lap.lap for lap in usable), default=0)
    if race_span > 0 and len(phase) > 1:
        spread = (max(phase.values()) - min(phase.values())) / race_span
        if spread > PHASE_SEPARATION_LIMIT:
            ordered = ", ".join(
                f"{c.short} lap {int(m)}" for c, m in sorted(phase.items(), key=lambda kv: kv[1])
            )
            warnings.append(
                f"compound usage is separated by race phase ({ordered}) - per-compound "
                f"degradation is confounded with the race-lap trend and should not be "
                f"trusted from a single race"
            )
    for compound, rate in degradation.items():
        if rate < 0:
            warnings.append(
                f"{compound.short} degradation is negative ({rate:+.4f} s/lap) - "
                "usually too few laps on that compound"
            )

    return PaceFit(
        race_lap_coef=race_lap_coef,
        degradation=degradation,
        compound_offset=compound_offset,
        reference_compound=reference,
        compound_phase=phase,
        driver_pace={d: float(coefficients[i]) for d, i in driver_index.items()},
        n_laps=len(usable),
        n_stints=len(stints),
        residual_std=float(np.std(residuals, ddof=min(n_cols, len(usable) - 1))),
        r_squared=(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0,
        warnings=tuple(warnings),
    )
