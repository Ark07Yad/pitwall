"""Joint decomposition of lap time into pace, fuel trend and tyre degradation.

Fuel and degradation cannot be estimated one after the other. Within a single
stint they are perfectly collinear - the car gets a lap lighter at exactly the
rate the tyre gets a lap older - so no amount of data from one stint can tell
them apart.

What separates them is the *stint structure*. Fuel depends on the race lap and
falls monotonically all afternoon; tyre age resets to zero at every pit stop. Fit
both at once against laps spanning multiple stints and the two are identified:

    lap_time = pace(driver) + β·race_lap + Σ_c δ_c + Σ_c α_c·age + Σ_c γ_c·age² + ε

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

`γ_c` is the cliff. Degradation is not linear - a tyre wears gently and then
falls away - and a purely linear fit cannot say so. It matters because the
simulation asks what a tyre will be doing twenty laps from now, and a straight
line extrapolated from the gentle part promises a tyre that lasts forever. At
Zandvoort the medium's median lap loss went +0.93s, +1.44s, +2.42s across
successive five-lap age buckets; that acceleration is the whole strategic
question and a linear model reports it as a constant.

**`γ_c` is constrained to be non-negative.** A negative quadratic describes a
tyre that gets faster the longer it runs, which is not a thing, and extrapolating
one is worse than having no curvature at all - it actively rewards never
stopping. Where the unconstrained fit wants a negative γ, that compound is refit
without the term rather than clamped afterwards, so its α is not left carrying
the bias.

**What this still cannot do is see past the data.** Teams pit before the cliff,
so the steepest part of the curve is barely observed - the longest hard stint at
Zandvoort was 36 laps, and nothing says what lap 50 would have looked like. That
is truncation of the covariate, not noise, and no amount of curve-fitting fixes
it. `observed_max_age` records where the evidence stops so a caller can tell an
interpolation from a guess.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pitwall.laps.records import LapRecord
from pitwall.models.safety_car import normalise_circuit
from pitwall.state.models import Compound

# Below this many laps the fit is not worth reporting; coefficients swing wildly.
MIN_LAPS = 30
# Distinct stints needed before fuel and degradation are separable at all.
MIN_STINTS = 2
# If two compounds' median race laps sit further apart than this fraction of the
# race, each one effectively occupies its own phase and its degradation cannot be
# told apart from whatever else trends with race lap.
PHASE_SEPARATION_LIMIT = 0.35
# A modern grid is covered by a couple of seconds a lap. Anything near this is a
# degenerate fit, not a slow car.
MAX_PACE_SPREAD = 10.0
# Even a tyre falling off a cliff does not lose a second a lap, every lap.
MAX_DEGRADATION = 1.0
# A compound needs this many laps, spanning this much tyre age, before a
# quadratic is worth fitting. Below it the curvature is noise wearing a cliff's
# clothes, and it extrapolates violently.
MIN_LAPS_FOR_CLIFF = 40
MIN_AGE_SPAN_FOR_CLIFF = 12
# Curvature above this is not a tyre. At 0.01 a thirty-lap stint would already
# have lost nine seconds to the quadratic term alone.
MAX_CURVATURE = 0.01


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
    # The cliff, per compound. Absent or zero means no curvature was
    # identifiable and the compound is modelled as linear.
    degradation_curvature: dict[Compound, float] = field(default_factory=dict)
    # Longest tyre age actually observed on each compound. Beyond it the model
    # is extrapolating, which is a different claim from interpolating.
    observed_max_age: dict[Compound, int] = field(default_factory=dict)
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

    def degradation_at(self, compound: Compound, age: float) -> float:
        """Seconds lost to tyre wear at this age, cliff included."""
        linear = self.degradation.get(compound, 0.0)
        curvature = self.degradation_curvature.get(compound, 0.0)
        return linear * age + curvature * age * age

    def extrapolating(self, compound: Compound, age: float) -> bool:
        """Whether this age is past anything actually observed on this compound.

        Teams pit before the cliff, so the long-stint end of the curve is barely
        in the data. A caller asking about lap 50 of a compound never run past 36
        is not reading a measurement, and should be able to tell.
        """
        seen = self.observed_max_age.get(compound)
        return seen is not None and age > seen

    @property
    def unusable_reasons(self) -> tuple[str, ...]:
        """Why this fit should not be simulated from, if it should not be.

        Early in a race the design is degenerate - few laps, one stint per car,
        fuel and degradation perfectly collinear - and least squares answers
        anyway. It returned a 67-second spread in driver pace and +28 s/lap of
        hard-tyre degradation at lap 16 of the 2026 Hungarian GP. Nothing
        errored; the simulation simply produced confident nonsense from it.

        A fit that fails these checks is not a weaker signal, it is noise, and
        the honest response is to publish no prediction rather than a bad one.
        """
        reasons: list[str] = []
        if any("rank deficient" in w for w in self.warnings):
            reasons.append("effects are not separately identified")
        if self.race_lap_coef > 0:
            reasons.append(
                f"race-lap trend is positive ({self.race_lap_coef:+.4f} s/lap); "
                "cars get faster as fuel burns off"
            )
        spread = (
            max(self.driver_pace.values()) - min(self.driver_pace.values())
            if self.driver_pace
            else 0.0
        )
        if spread > MAX_PACE_SPREAD:
            reasons.append(f"driver pace spread of {spread:.1f}s is not physical")
        for compound, rate in self.degradation.items():
            if not -MAX_DEGRADATION <= rate <= MAX_DEGRADATION:
                reasons.append(f"{compound.short} degradation of {rate:+.2f} s/lap is out of range")
        return tuple(reasons)

    @property
    def usable(self) -> bool:
        """Whether this fit is sound enough to simulate from."""
        return not self.unusable_reasons

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
            curvature = self.degradation_curvature.get(compound, 0.0)
            seen = self.observed_max_age.get(compound)
            cliff = f"  cliff {curvature:+.5f} s/lap²" if curvature else "  no cliff term"
            at_seen = f", {self.degradation_at(compound, seen):+.2f}s by age {seen}" if seen else ""
            lines.append(
                f"    {compound.short}  {rate:+.4f} s/lap   baseline {offset:+.3f} s"
                f"{cliff}{at_seen}"
            )
        for warning in self.warnings:
            lines.append(f"  ! {warning}")
        for reason in self.unusable_reasons:
            lines.append(f"  ✗ UNUSABLE: {reason}")
        return "\n".join(lines)


def _blend_with_prior(
    *,
    degradation: dict[Compound, float],
    curvature: dict[Compound, float],
    observed_max_age: dict[Compound, int],
    laps_per_compound: Counter,
    prior: Any,
    circuit: str,
) -> tuple[dict[Compound, float], dict[Compound, float], dict[Compound, int], list[str]]:
    """Shrink an in-race fit toward the pooled prior, in units of laps.

    The weight is the compound's own lap count against the prior's, so a
    compound with three hundred clean laps keeps its own rate and one with thirty
    borrows most of the pooled shape. The alternative - a fixed blend - would
    either drown a well-observed race or leave a thin one on noise.

    Curvature is treated differently from the slope. A single race almost never
    identifies a cliff, so where the in-race fit found none the prior's is taken
    outright rather than averaged with a zero that means "could not tell" rather
    than "is not there".
    """
    notes: list[str] = []
    blend_laps = float(getattr(prior, "blend_laps", 200.0))
    blended = dict(degradation)
    blended_curve = dict(curvature)
    extended = dict(observed_max_age)

    for compound, rate in degradation.items():
        prior_rate = prior.linear.get(compound)
        if prior_rate is None:
            continue
        # The prior's linear rate at this circuit. Taken directly rather than
        # via `degradation_at(1.0)`, which is the slope at age one and not the
        # same thing once curvature is present.
        factor = prior.circuit_factor.get(normalise_circuit(circuit), 1.0)
        scaled = prior_rate * factor
        n = float(laps_per_compound.get(compound, 0))
        blended[compound] = (n * rate + blend_laps * scaled) / (n + blend_laps)

        own_curve = curvature.get(compound, 0.0)
        prior_curve = prior.curvature.get(compound, 0.0) * prior.circuit_factor.get(
            normalise_circuit(circuit), 1.0
        )
        if own_curve <= 0.0:
            blended_curve[compound] = prior_curve
        else:
            blended_curve[compound] = (n * own_curve + blend_laps * prior_curve) / (n + blend_laps)

        # The prior's evidence reaches further than this race's, which is the
        # whole reason for having it.
        pooled_age = prior.observed_max_age(compound)
        if pooled_age > extended.get(compound, 0):
            extended[compound] = pooled_age

    if not prior.known_circuit(circuit):
        notes.append(
            f"no pooled degradation history for {circuit or 'this circuit'}; "
            "the prior is applied unscaled"
        )
    return blended, blended_curve, extended, notes


def fit_pace(
    laps: list[LapRecord],
    *,
    prior: Any = None,
    circuit: str = "",
) -> PaceFit | None:
    """Fit the decomposition. Returns None if there is not enough to fit.

    Expects laps that have already been through the clean-lap filter; feeding it
    in-laps or safety-car laps produces confident nonsense.

    `prior` is an optional pooled `DegradationPrior`. One race cannot identify a
    cliff - teams pit before a tyre falls away, so the steep part is missing
    precisely because it is steep - and the prior supplies the shape that many
    races can see. Each compound's in-race estimate is blended toward it in
    proportion to how many laps back it, so a well-observed compound keeps its
    own number and a thin one borrows.

    It also extends `observed_max_age`: a 49-lap tyre is extrapolation against
    one afternoon and ordinary interpolation against five seasons.
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

    # How far the evidence actually reaches, per compound. Everything the model
    # says beyond this is extrapolation.
    observed_max_age = {
        c: max(lap.tyre_age for lap in usable if lap.compound is c) for c in compounds
    }

    # Which compounds have enough spread in tyre age to support a cliff term.
    # Fitting curvature on a narrow age range does not find a cliff, it finds
    # noise - and then extrapolates it hard.
    def supports_cliff(compound: Compound) -> bool:
        ages = [lap.tyre_age for lap in usable if lap.compound is compound]
        if len(ages) < MIN_LAPS_FOR_CLIFF:
            return False
        return (max(ages) - min(ages)) >= MIN_AGE_SPAN_FOR_CLIFF

    curved = [c for c in compounds if supports_cliff(c)]

    driver_index = {d: i for i, d in enumerate(drivers)}
    lap_col = len(drivers)

    def solve(with_curvature: list[Compound]):
        age_index = {c: lap_col + 1 + i for i, c in enumerate(compounds)}
        base = lap_col + 1 + len(compounds)
        offset_index = {c: base + i for i, c in enumerate(offset_compounds)}
        base += len(offset_compounds)
        curve_index = {c: base + i for i, c in enumerate(with_curvature)}
        n_cols = base + len(with_curvature)

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
            curve_column = curve_index.get(lap.compound)
            if curve_column is not None:
                # Scaled by 100 so the quadratic column sits on the same order as
                # the linear ones. Squared tyre age reaches ~2,300 where lap
                # number reaches 72, and that conditioning alone is enough to
                # trip the rank check into a spurious warning.
                x[row, curve_column] = (lap.tyre_age**2) / 100.0
            y[row] = lap.lap_time

        coefficients, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
        return coefficients, age_index, offset_index, curve_index, rank, n_cols, x, y

    coefficients, age_index, offset_index, curve_index, rank, n_cols, x, y = solve(curved)

    # A negative quadratic is a tyre that gets faster the longer it runs.
    # Extrapolating one actively rewards never stopping, which is the exact
    # failure this term exists to prevent. Refit without it rather than clamping
    # after the fact, so the linear rate is not left carrying the bias.
    negative = [c for c, i in curve_index.items() if coefficients[i] < 0]
    if negative:
        curved = [c for c in curved if c not in negative]
        coefficients, age_index, offset_index, curve_index, rank, n_cols, x, y = solve(curved)

    if rank < n_cols:
        warnings.append(
            f"design matrix is rank deficient ({rank} of {n_cols}) - "
            "some effects are not separately identified"
        )

    degradation_curvature = {c: float(coefficients[i]) / 100.0 for c, i in curve_index.items()}
    for compound, curvature in list(degradation_curvature.items()):
        if curvature > MAX_CURVATURE:
            warnings.append(
                f"{compound.short} curvature of {curvature:+.5f} s/lap² is not physical; "
                "dropping the cliff term for it"
            )
            degradation_curvature[compound] = 0.0

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

    if prior is not None:
        degradation, degradation_curvature, observed_max_age, prior_notes = _blend_with_prior(
            degradation=degradation,
            curvature=degradation_curvature,
            observed_max_age=observed_max_age,
            laps_per_compound=Counter(lap.compound for lap in usable),
            prior=prior,
            circuit=circuit,
        )
        warnings.extend(prior_notes)

    return PaceFit(
        race_lap_coef=race_lap_coef,
        degradation=degradation,
        compound_offset=compound_offset,
        reference_compound=reference,
        compound_phase=phase,
        driver_pace={d: float(coefficients[i]) for d, i in driver_index.items()},
        n_laps=len(usable),
        degradation_curvature=degradation_curvature,
        observed_max_age=observed_max_age,
        n_stints=len(stints),
        residual_std=float(np.std(residuals, ddof=min(n_cols, len(usable) - 1))),
        r_squared=(1.0 - ss_res / ss_tot) if ss_tot > 0 else 0.0,
        warnings=tuple(warnings),
    )
