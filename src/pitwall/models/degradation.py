"""A tyre-degradation prior pooled across races.

The engine's in-session pace fit can only see the race it is in, and a single
race cannot identify a cliff. Teams pit *before* a tyre falls away, so the steep
part of the curve is missing from any one afternoon precisely *because* it is
steep - Zandvoort's longest hard stint was 36 laps, and a straight line fitted to
that promises a tyre that lasts forever. "Stay out" is the option that benefits
from the optimism, which is how the engine came to recommend running 46 laps on
one set.

More laps from the same race do not fix that; they are all from the same
truncated range. What fixes it is other races. Somewhere in five seasons a car
ran a hard tyre 63 laps, and with those stints pooled the curvature becomes
identifiable.

**What is pooled is not lap times.** A lap at Monaco and a lap at Monza share no
scale. `scripts/fetch_degradation.py` strips each race down to the part of a lap
attributable to tyre age - subtracting driver pace, the fuel-and-evolution trend
and each compound's baseline - and it is those deltas, in seconds, that mean the
same thing everywhere.

**Circuits differ, and get one number to say so.** Rather than a separate curve
per circuit, which five races cannot support, each circuit gets a single scalar
multiplying the shared shape, shrunk toward 1.0 by how many races back it. A
circuit has to earn its distance from the field, the same reasoning the
safety-car and pit-loss models use.

**Pooling does not reveal a cliff, and the reason is the finding.** With 95 races
and 85,000 laps out to a tyre age of 78, the pooled curve rises, flattens, and on
the soft actually *falls*: +0.37s at age 15 against -0.61s at age 30. A tyre does
not get faster the longer it runs. What that measures is survivorship - a car
whose tyres are going away gets pitted, so the sample still running at age 40 is
made of exactly the stints that were not degrading. The selection strengthens
with age, and pooling more races sharpens the artifact rather than removing it.

So the curve is *concave* where physics says convex, and an unconstrained
quadratic fitted to it comes back negative - a tyre improving with age - which
the non-negativity constraint then floors at zero. The zero is not "no cliff
exists"; it is the constraint refusing to encode a nonsense.

The model therefore fits only up to `reliable_max_age`, the age past which the
binned curve stops rising, and **continues linearly beyond it rather than
flattening**. Flattening is the artifact; a straight line is the smallest claim
that is not knowingly wrong. Beyond that age the estimate is reported as
selection-contaminated, because it is.

The prior is used two ways. It supplies a shape and a per-circuit scale the
in-session fit cannot pin down from one afternoon, and - the more important one -
it says how far the evidence honestly reaches.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from pitwall.models.safety_car import normalise_circuit
from pitwall.state.models import Compound

# Weight of the prior when blending with an in-session fit, in laps. A compound
# needs roughly this much in-race evidence before its own estimate outweighs
# five seasons of pooled history.
DEFAULT_BLEND_LAPS = 200.0

# Races a circuit needs before its own scale factor outweighs the field average.
DEFAULT_CIRCUIT_SHRINKAGE = 3.0
# Above this a race's decomposition is not trusted. It sits in a gap in the data
# rather than on a knife edge: seven races ran 24% or more of their laps on wet
# tyres and the next one down is 1.2%. See `disruption`.
MAX_WET_SHARE = 0.05

# Same physical bounds the in-session fit uses.
MAX_DEGRADATION = 1.0
MAX_CURVATURE = 0.01

# Bin width for detecting where the observed curve stops rising. Wide enough
# that a single noisy age does not end the range, narrow enough to locate the
# turn within a pit window.
RELIABLE_BIN = 5
# A bin below this many laps is too thin to judge the trend from.
MIN_BIN_LAPS = 50

_BY_SHORT = {c.short: c for c in Compound}


def _reliable_age(rows: list[tuple[int, float, int]]) -> int:
    """Largest tyre age before the pooled curve stops rising.

    Degradation is monotone - tyres do not recover - so an observed curve that
    turns over is measuring selection, not rubber. The turning point is where
    the sample stops being trustworthy, and it is found rather than assumed
    because it differs by compound: the soft turns around age 20, the hard nearer
    30.
    """
    if not rows:
        return 0
    binned: dict[int, list[float]] = defaultdict(list)
    counts: dict[int, int] = defaultdict(int)
    for age, mean, n in rows:
        bin_lo = (age // RELIABLE_BIN) * RELIABLE_BIN
        binned[bin_lo].append(mean * n)
        counts[bin_lo] += n

    ordered = sorted(b for b in binned if counts[b] >= MIN_BIN_LAPS)
    if len(ordered) < 2:
        return max((age for age, _, _ in rows), default=0)

    best = ordered[0]
    peak = sum(binned[ordered[0]]) / counts[ordered[0]]
    for bin_lo in ordered[1:]:
        value = sum(binned[bin_lo]) / counts[bin_lo]
        if value < peak:
            break
        peak = value
        best = bin_lo
    return best + RELIABLE_BIN - 1


@dataclass(frozen=True)
class DegradationPrior:
    """Pooled degradation shape, and how far the evidence for it reaches."""

    linear: dict[Compound, float]
    curvature: dict[Compound, float]
    max_age: dict[Compound, int]
    # Age past which the pooled curve stops rising. Beyond it the sample is
    # survivorship - the stints still running are the ones that were not
    # degrading - so the shape is fitted only up to here and continued linearly.
    reliable_max_age: dict[Compound, int]
    circuit_factor: dict[str, float]
    circuit_races: dict[str, int]
    n_races: int
    n_laps: int
    blend_laps: float = DEFAULT_BLEND_LAPS
    warnings: tuple[str, ...] = field(default=())

    def degradation_at(self, compound: Compound, age: float, circuit: str = "") -> float:
        """Seconds lost to tyre age, scaled to the circuit where one is known.

        Past `reliable_max_age` the curve is continued at the slope it had
        there, rather than following the fitted shape. The observed shape
        flattens out there and flattening is the survivorship artifact; a
        straight line is the smallest claim that is not knowingly wrong, and it
        does not tell the engine a tyre lasts forever.
        """
        linear = self.linear.get(compound, 0.0)
        curvature = self.curvature.get(compound, 0.0)
        limit = self.reliable_max_age.get(compound)

        if limit is not None and age > limit:
            value_at_limit = linear * limit + curvature * limit * limit
            slope_at_limit = linear + 2.0 * curvature * limit
            shape = value_at_limit + slope_at_limit * (age - limit)
        else:
            shape = linear * age + curvature * age * age
        return shape * self.circuit_factor.get(normalise_circuit(circuit), 1.0)

    def selection_contaminated(self, compound: Compound, age: float) -> bool:
        """Whether an age sits past where the sample stops being trustworthy."""
        limit = self.reliable_max_age.get(compound)
        return limit is not None and age > limit

    def observed_max_age(self, compound: Compound) -> int:
        return self.max_age.get(compound, 0)

    def known_circuit(self, circuit: str) -> bool:
        return normalise_circuit(circuit) in self.circuit_factor

    def __str__(self) -> str:
        lines = [
            f"Pooled degradation from {self.n_races} races, {self.n_laps:,} laps",
            "",
            f"  {'compound':<10} {'linear':>10} {'cliff':>11} {'trusted':>8}"
            f" {'seen':>5} {'@20':>7} {'@40':>7} {'@55':>7}",
        ]
        for compound in sorted(self.linear, key=lambda c: c.short):
            lines.append(
                f"  {compound.short:<10} {self.linear[compound]:>+9.4f}"
                f" {self.curvature.get(compound, 0.0):>+10.5f}"
                f" {self.reliable_max_age.get(compound, 0):>8}"
                f" {self.max_age.get(compound, 0):>5}"
                f" {self.degradation_at(compound, 20):>+6.2f}s"
                f" {self.degradation_at(compound, 40):>+6.2f}s"
                f" {self.degradation_at(compound, 55):>+6.2f}s"
            )
        ranked = sorted(self.circuit_factor.items(), key=lambda kv: -kv[1])
        if ranked:
            lines.append("")
            lines.append("  circuit factor (shrunk toward 1.0):")
            for circuit, factor in ranked:
                races = self.circuit_races.get(circuit, 0)
                lines.append(f"    {circuit:<24} {factor:>5.2f}x  ({races} races)")
        for warning in self.warnings:
            lines.append(f"  ! {warning}")
        return "\n".join(lines)


def load_degradation(path: Path | str) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def neutralisation_index(history: list[dict[str, Any]]) -> dict[tuple[int, int], Any]:
    """Key the safety-car history by (season, round) so the fit can join on it.

    The two datasets are collected by separate scripts and neither is the
    other's source of truth, so the join is by race identity rather than by
    position. A race missing from one side simply fails the neutralisation test
    and is kept; the wet-share test still applies to it.
    """
    return {(int(r["season"]), int(r["round"])): r for r in history if "season" in r}


def _fit_shape(ages: np.ndarray, deltas: np.ndarray, weights: np.ndarray) -> tuple[float, float]:
    """Weighted least squares of `delta ≈ α·age + γ·age²`, through the origin.

    No intercept: the deltas are built by subtracting each compound's own
    baseline, so a fresh tyre is zero by construction. Fitting one anyway would
    let a spurious level soak up part of the slope.

    `γ` is constrained non-negative. A negative quadratic is a tyre that gets
    faster the longer it runs; extrapolating one rewards never stopping, which is
    the failure this whole model exists to prevent.
    """
    if len(ages) < 3:
        return 0.0, 0.0
    sqrt_w = np.sqrt(weights)
    design = np.column_stack([ages, ages**2 / 100.0]) * sqrt_w[:, None]
    target = deltas * sqrt_w

    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    linear, curvature = float(coefficients[0]), float(coefficients[1]) / 100.0

    if curvature < 0.0:
        # Refit without the term rather than clamping, so the linear rate is not
        # left carrying the bias the quadratic was absorbing.
        linear_only = (ages * sqrt_w)[:, None]
        coefficients, *_ = np.linalg.lstsq(linear_only, target, rcond=None)
        return float(coefficients[0]), 0.0

    return linear, curvature


def disruption(race: dict[str, Any], history: dict[tuple[int, int], Any] | None) -> str:
    """Why this race's decomposition cannot be trusted, or "" if it can.

    The per-race fit subtracts one straight line in race lap - fuel burn and
    track evolution together - before anything is attributed to tyre age. Three
    things break that line, and all of them dump the break into the age terms:

    - a **red flag**, which resets fuel load and track state mid-race;
    - **wet running**, where the surviving slick laps sit either side of a
      drying trend far steeper than fuel burn.

    Measured rather than assumed: across the 95-race pool, races whose fitted
    scale came out negative - a tyre getting *faster* with age, which is not a
    tyre - were six times as likely to be red-flagged (29% against 5%), had
    three times the safety-car starts (1.41 against 0.47) and ran twice the
    share of the race neutralised (17.6% against 7.9%).

    **A neutralisation test was tried on that evidence and is deliberately not
    here.** Excluding races above a 20% neutralised share cost twelve more races
    and changed the fitted shape by under 0.002 s/lap on every compound; it took
    Silverstone from two usable races to one and Zandvoort from three to two,
    while Zandvoort's factor moved 1.046 to 1.026. The correlation is real but
    it is not independent - a race neutralised that heavily is usually also
    red-flagged or wet - so the test was removed rather than kept for the sake
    of the evidence that motivated it.

    This is also deliberately *not* "drop the races whose answer looks wrong".
    Excluding on the sign of the estimate would systematically overstate every
    circuit whose true degradation is near zero, because noise there scatters
    the estimate either side of it and only one side would be kept - and those
    low-degradation circuits are exactly the ones this scale matters most for.
    """
    if float(race.get("wet_share") or 0.0) > MAX_WET_SHARE:
        return f"{float(race['wet_share']):.0%} of laps run on wet tyres"
    entry = (history or {}).get((int(race.get("season", 0)), int(race.get("round", 0))))
    if entry is not None and entry.get("red_starts"):
        return "red-flagged"
    return ""


def fit_degradation(
    races: list[dict[str, Any]],
    *,
    circuit_shrinkage: float = DEFAULT_CIRCUIT_SHRINKAGE,
    blend_laps: float = DEFAULT_BLEND_LAPS,
    history: dict[tuple[int, int], Any] | None = None,
) -> DegradationPrior | None:
    """Fit the pooled shape and per-circuit scales.

    `history` is the safety-car history keyed by (season, round), which is where
    the red-flag test reads from. Without it only the wet-share test can run, so
    the fit is more contaminated but still works - the caller that has it should
    pass it.

    A disrupted race is dropped from **both** the pooled shape and the circuit
    scales, not just the scales. The contamination is one mechanism and it does
    not respect that distinction: on the unfiltered pool the fitted shape put
    the soft at -0.015 s/lap against the hard at +0.037, which is a soft tyre
    that improves with age and wears slower than a hard - both false, and both
    the wrong way round. Filtered, the ordering comes out soft > medium > hard,
    which is the only ordering a tyre compound admits.
    """
    if not races:
        return None

    by_compound: dict[Compound, list[tuple[int, float, int]]] = defaultdict(list)
    per_circuit: dict[str, list[tuple[Compound, int, float, int]]] = defaultdict(list)
    # One entry per race, so a scale can be fitted per race and combined
    # robustly. Pooling every bucket row at a circuit into a single
    # least-squares lets one broken race move the whole circuit.
    per_race: dict[str, list[list[tuple[Compound, int, float, int]]]] = defaultdict(list)
    circuit_races: dict[str, int] = defaultdict(int)
    excluded: list[str] = []
    total_laps = 0

    for race in races:
        circuit = normalise_circuit(race.get("circuit"))
        reason = disruption(race, history)
        if reason:
            excluded.append(f"{race.get('season')} {race.get('event', circuit)} ({reason})")
            continue
        circuit_races[circuit] += 1
        race_rows: list[tuple[Compound, int, float, int]] = []
        for bucket in race.get("buckets") or ():
            compound = _BY_SHORT.get(str(bucket.get("compound")))
            if compound is None or compound is Compound.UNKNOWN:
                continue
            age = int(bucket["age"])
            mean = float(bucket["mean"])
            n = int(bucket["n"])
            if age <= 0 or n <= 0:
                continue
            by_compound[compound].append((age, mean, n))
            per_circuit[circuit].append((compound, age, mean, n))
            race_rows.append((compound, age, mean, n))
            total_laps += n
        if race_rows:
            per_race[circuit].append(race_rows)

    if not by_compound:
        return None

    linear: dict[Compound, float] = {}
    curvature: dict[Compound, float] = {}
    max_age: dict[Compound, int] = {}
    warnings: list[str] = []

    reliable: dict[Compound, int] = {}
    for compound, rows in by_compound.items():
        limit = _reliable_age(rows)
        reliable[compound] = limit
        # Fit only where the sample is not selection-dominated. Including the
        # flattened tail drags the slope down and is what made the pooled soft
        # look like it degraded at a fifth the rate of the hard.
        inside = [r for r in rows if r[0] <= limit] or rows
        ages = np.array([r[0] for r in inside], dtype=float)
        deltas = np.array([r[1] for r in inside], dtype=float)
        weights = np.array([r[2] for r in inside], dtype=float)
        slope, curve = _fit_shape(ages, deltas, weights)

        if not -MAX_DEGRADATION <= slope <= MAX_DEGRADATION:
            warnings.append(
                f"{compound.short} pooled slope of {slope:+.3f} s/lap is out of range; dropped"
            )
            continue
        if curve > MAX_CURVATURE:
            warnings.append(
                f"{compound.short} pooled curvature of {curve:+.5f} s/lap² is not physical; "
                "using a linear shape for it"
            )
            curve = 0.0

        linear[compound] = slope
        curvature[compound] = curve
        max_age[compound] = int(max(r[0] for r in rows))

    if not linear:
        return None

    flat = sorted(c.short for c in linear if not curvature.get(c))
    if flat:
        # `PLAN.md` §5.2 asks for a cliff and the table prints "+0.00000" for
        # one that was never fitted, which reads as a measurement of zero rather
        # than the absence of one. On the clean pool no compound identifies a
        # cliff at all: teams pit before the tyre falls off, so the steep part
        # is missing from the observations *because* it is steep.
        warnings.append(
            "no cliff term is identified for " + ", ".join(flat) + " - the quadratic came back "
            "negative and was refit without it, so a long stint on those compounds is modelled "
            "as a straight line, which is the optimistic direction"
        )

    # One scalar per circuit against the shared shape. A whole curve per circuit
    # is not supportable on five races; a single scale is.
    #
    # Fitted per race and combined by median, not pooled into one least-squares
    # over every bucket row at the circuit. The pooled form has no defence
    # against a single race whose decomposition failed: at Zandvoort the 2023
    # race alone pulled the scale from ~1.0 to 0.505, and the per-compound
    # breakdown showed why - hard 0.92x and medium 1.30x, both plausible,
    # against a soft at -1.48x that outweighed them. The engine then believed a
    # Zandvoort tyre wore at half the field rate, which is what made a second
    # stop unable to pay for itself there before lap 48 of 72.
    circuit_factor: dict[str, float] = {}
    unreliable: list[str] = []

    def scale_of(rows: list[tuple[Compound, int, float, int]]) -> float | None:
        numerator = denominator = 0.0
        for compound, age, mean, n in rows:
            if compound not in linear:
                continue
            predicted = linear[compound] * age + curvature[compound] * age * age
            numerator += n * mean * predicted
            denominator += n * predicted * predicted
        return numerator / denominator if denominator > 0 else None

    for circuit, races_at in per_race.items():
        scales = [s for s in (scale_of(rows) for rows in races_at) if s is not None]
        if not scales:
            continue
        # The median keeps a circuit whose true degradation is near zero honest:
        # noise there lands either side, and a mean would follow whichever side
        # happened to be larger.
        raw = float(np.median(scales))
        if raw < 0.0:
            # A negative scale says tyres get *faster* with age at this circuit.
            # Shrinking it toward 1.0 would launder that into a small positive
            # number that looks entirely plausible - Melbourne came out at 0.06x
            # off a raw -0.64 - and the engine would then believe a tyre there
            # barely wears. The decomposition failed here; say so and use the
            # field average rather than a number built on a sign error.
            unreliable.append(circuit)
            continue
        races_here = len(scales)
        # Shrink toward the field, in units of *usable* races - races excluded
        # as disrupted must not buy a circuit confidence it has not earned.
        circuit_factor[circuit] = (races_here * raw + circuit_shrinkage) / (
            races_here + circuit_shrinkage
        )
        circuit_races[circuit] = races_here

    if excluded:
        warnings.append(
            f"{len(excluded)} of {len(races)} races excluded from the fit as disrupted "
            "(a red flag or wet running breaks the single race-lap trend "
            "the decomposition subtracts): " + "; ".join(sorted(excluded))
        )

    if unreliable:
        warnings.append(
            "degradation could not be scaled for "
            + ", ".join(sorted(unreliable))
            + " (the fitted scale came out negative, which is not a tyre); "
            "the field average is used there instead"
        )

    spread = max(circuit_factor.values()) - min(circuit_factor.values()) if circuit_factor else 0.0
    if spread > 3.0:
        warnings.append(
            f"circuit factors span {spread:.1f}x, which is more than tyre wear plausibly varies"
        )

    turned = [c.short for c, a in reliable.items() if a < max_age.get(c, 0)]
    if turned:
        warnings.append(
            "pooled curve turns over with age for "
            + ", ".join(sorted(turned))
            + " - tyres do not recover, so beyond the reliable age the sample is "
            "survivorship and the shape is continued linearly rather than fitted"
        )

    return DegradationPrior(
        linear=linear,
        curvature=curvature,
        max_age=max_age,
        reliable_max_age={c: reliable[c] for c in linear},
        circuit_factor=circuit_factor,
        circuit_races=dict(circuit_races),
        n_races=len(races) - len(excluded),
        n_laps=total_laps,
        blend_laps=blend_laps,
        warnings=tuple(warnings),
    )
