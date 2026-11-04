"""How hard it is to pass, per circuit.

The simulation keeps a car behind the one it has caught unless it wins a roll,
once a lap, at

    chance = base + per_second * advantage

where `advantage` is its edge in clear-air pace, seconds a lap. Until November
2026 those were two numbers set by hand - 0.18 and 0.35 - and the same at Monaco
as at Monza. They decide whether a car that stops can get back past the cars it
drops behind, which is most of what an undercut, an overcut or a second stop is
worth.

**What is measured.** `scripts/fetch_race_dynamics.py` takes every green lap a
car starts within a second of the one ahead, neither pitting, and records whether
it was ahead at the line and how much quicker it was by a pace fit of the race on
clear-air laps. Five seasons give tens of thousands of these.

**What is fitted is the simulation's own rule, not a summary of it.** A car the
simulation fails to pass with is pinned `min_gap` behind, and only rolls again on
a lap it closes back inside that - which, with lap-time noise of `lap_noise` on
each car, happens with probability `Phi(advantage / (sqrt(2) * lap_noise))`. So
the rate a real follower passes at corresponds to `chance * Phi(...)` in the
simulation, and that product is what is fitted to the observations by maximum
likelihood. Fitting `chance` to the raw rate would have the simulation pass about
half as often as the races it was fitted on.

**The level belongs to the cars, the ratio to the track.** 2026 changed the
rules, and passing with it: fitted on 2022-25 alone the pooled rule is 0.084 a
lap plus 0.231 per second of edge, on 2026 alone 0.169 plus 0.122 - easier to
pass, and less of it down to pace. Pooling the two would have this season's
races simulated with last season's cars. So the level and the slope come from
the current era, and what five seasons are used for is how much harder or
easier each track is *than its own era's average*.

**Shrunk by as much as the data says, on the scale ratios live on.** One race
says little: Baku reads 0.02 of its era's average in two seasons and 1.5 in the
other two. The ratio is shrunk toward one on a log scale, by a weight of
`n / (n + K)` in races, with `K` the ratio of race-to-race variance within a
circuit to the variance between circuits, both estimated from the same races -
1.7 on the 2022-26 data, where pit loss borrows a flat 2.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import ndtr

from pitwall.models.safety_car import normalise_circuit

DEFAULT_BASE = 0.18
DEFAULT_PER_SECOND = 0.35
DEFAULT_SHRINKAGE = 2.0
# The simulation's lap-to-lap scatter (`SimConfig.lap_noise`), which sets how
# often a pinned car gets close enough to roll again.
LAP_NOISE = 0.7
MAX_CHANCE = 0.95
# A race contributes to a circuit's estimate only with this many following laps;
# fewer cannot place a base rate of one in ten.
MIN_FOLLOWERS = 40
# The first season of the current rules. Its races set the level and the slope.
CURRENT_ERA = 2026
# Below this many current-era races the level is taken from every season.
MIN_CURRENT_RACES = 8
# A race with no passes at all fits a base of zero, and the log of that is not
# a ratio; this is "almost never", about one pass in fifty following laps.
RATIO_FLOOR = 0.02
MIN_SHRINKAGE, MAX_SHRINKAGE = 0.5, 10.0


@dataclass(frozen=True)
class OvertakingModel:
    base: float
    per_second: float
    circuit_factor: dict[str, float]
    circuit_raw: dict[str, float]
    circuit_races: dict[str, int]
    n_races: int
    n_followers: int
    n_passes: int
    era: dict[str, tuple[float, float, int]] = field(default_factory=dict)
    shrinkage: float = DEFAULT_SHRINKAGE
    warnings: tuple[str, ...] = field(default=())

    def base_for(self, circuit: str) -> float:
        factor = self.circuit_factor.get(normalise_circuit(circuit), 1.0)
        return min(MAX_CHANCE, self.base * factor)

    @property
    def circuit_base(self) -> dict[str, float]:
        return {c: min(MAX_CHANCE, self.base * f) for c, f in self.circuit_factor.items()}

    def known_circuit(self, circuit: str) -> bool:
        return normalise_circuit(circuit) in self.circuit_factor

    def races_at(self, circuit: str) -> int:
        return self.circuit_races.get(normalise_circuit(circuit), 0)

    def __str__(self) -> str:
        lines = [
            f"overtaking: {self.n_passes:,} passes in {self.n_followers:,} following laps, "
            f"{self.n_races} dry races",
        ]
        for name, (base, slope, races) in self.era.items():
            lines.append(
                f"  {name:<10} base {base:.3f}/lap, +{slope:.3f} per s/lap  ({races} races)"
            )
        lines += [
            f"  used: base {self.base:.3f}, +{self.per_second:.3f} per s/lap "
            f"(hand-set before: {DEFAULT_BASE}, {DEFAULT_PER_SECOND})",
            "",
            f"  shrinkage: {self.shrinkage:.2f} races, estimated from the race-to-race scatter",
            "",
            f"  {'circuit':<20}{'races':>6}{'vs era':>8}{'factor':>8}{'base':>8}",
        ]
        bases = self.circuit_base
        for circuit, factor in sorted(self.circuit_factor.items(), key=lambda kv: kv[1]):
            lines.append(
                f"  {circuit:<20}{self.circuit_races[circuit]:>6}"
                f"{self.circuit_raw[circuit]:>8.2f}{factor:>8.2f}{bases[circuit]:>8.3f}"
            )
        lines += [f"  ! {w}" for w in self.warnings]
        return "\n".join(lines)


def load_overtaking(path: Path | str) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _cells(races: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x, n, k = [], [], []
    for race in races:
        x += race["advantage"]
        n += race["n"]
        k += race["passed"]
    return np.array(x, float), np.array(n, float), np.array(k, float)


def reach(advantage: np.ndarray, lap_noise: float = LAP_NOISE) -> np.ndarray:
    """Chance a pinned car closes back inside `min_gap` on a given lap."""
    return ndtr(advantage / (math.sqrt(2.0) * lap_noise))


def _neg_log_likelihood(
    base: float, per_second: float, x: np.ndarray, n: np.ndarray, k: np.ndarray, closes: np.ndarray
) -> float:
    chance = np.clip(base + per_second * np.maximum(x, 0.0), 1e-4, MAX_CHANCE)
    p = np.clip(chance * closes, 1e-9, 1 - 1e-9)
    return float(-(k * np.log(p) + (n - k) * np.log(1 - p)).sum())


def _pooled(races: list[dict[str, Any]], lap_noise: float) -> tuple[float, float, bool]:
    x, n, k = _cells(races)
    closes = reach(x, lap_noise)
    fit = minimize(
        lambda v: _neg_log_likelihood(v[0], v[1], x, n, k, closes),
        x0=[DEFAULT_BASE, DEFAULT_PER_SECOND],
        bounds=[(1e-3, MAX_CHANCE), (0.0, 3.0)],
        method="L-BFGS-B",
    )
    return float(fit.x[0]), float(fit.x[1]), bool(fit.success)


def _base_given(races: list[dict[str, Any]], per_second: float, lap_noise: float) -> float:
    x, n, k = _cells(races)
    closes = reach(x, lap_noise)
    return float(
        minimize_scalar(
            lambda b: _neg_log_likelihood(b, per_second, x, n, k, closes),
            bounds=(1e-3, MAX_CHANCE),
            method="bounded",
        ).x
    )


def _shrinkage_from(per_race: dict[str, list[float]]) -> float | None:
    """Race-to-race variance within a circuit over variance between circuits."""
    repeated = [v for v in per_race.values() if len(v) > 1]
    if len(repeated) < 5:
        return None
    within = statistics.mean(statistics.variance(v) for v in repeated)
    means = [statistics.mean(v) for v in per_race.values()]
    noise = statistics.mean(within / len(v) for v in per_race.values())
    between = statistics.variance(means) - noise
    if between <= 0:
        return None
    return float(min(MAX_SHRINKAGE, max(MIN_SHRINKAGE, within / between)))


def fit_overtaking(
    races: list[dict[str, Any]],
    *,
    shrinkage: float = DEFAULT_SHRINKAGE,
    lap_noise: float = LAP_NOISE,
    current_era: int = CURRENT_ERA,
) -> OvertakingModel | None:
    """Fit the simulation's passing rule to observed following laps."""
    usable = [
        r for r in races if r.get("advantage") and int(r.get("followers") or 0) >= MIN_FOLLOWERS
    ]
    if not usable:
        return None
    warnings: list[str] = []

    eras = {
        "earlier": [r for r in usable if int(r["season"]) < current_era],
        "current": [r for r in usable if int(r["season"]) >= current_era],
    }
    params: dict[str, tuple[float, float]] = {}
    summary: dict[str, tuple[float, float, int]] = {}
    for name, own in eras.items():
        if not own:
            continue
        base, slope, ok = _pooled(own, lap_noise)
        if not ok:
            warnings.append(f"{name}-era fit did not converge")
        params[name] = (base, slope)
        span = f"{current_era}+" if name == "current" else f"<{current_era}"
        summary[f"{name} ({span})"] = (base, slope, len(own))

    if len(eras["current"]) >= MIN_CURRENT_RACES:
        base, per_second = params["current"]
    else:
        base, per_second, _ = _pooled(usable, lap_noise)
        warnings.append(
            f"only {len(eras['current'])} races since {current_era}; level taken from every season"
        )

    # Each track measured against its own era's level at its own era's slope,
    # so a 2023 Monaco and a 2026 Monaco are both read as "this much harder than
    # the field that year". Per circuit for the estimate; per race for how much
    # one race can be trusted.
    pooled: dict[str, list[float]] = defaultdict(list)
    per_race: dict[str, list[float]] = defaultdict(list)
    for name, own in eras.items():
        if name not in params:
            continue
        era_base, era_slope = params[name]
        by_circuit: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for race in own:
            by_circuit[normalise_circuit(race["circuit"])].append(race)
        for circuit, here in by_circuit.items():
            ratio = max(RATIO_FLOOR, _base_given(here, era_slope, lap_noise) / era_base)
            pooled[circuit] += [math.log(ratio)] * len(here)
            for race in here:
                one = max(RATIO_FLOOR, _base_given([race], era_slope, lap_noise) / era_base)
                per_race[circuit].append(math.log(one))

    strength = _shrinkage_from(per_race)
    if strength is None:
        strength = shrinkage
        warnings.append(f"too few circuits to estimate shrinkage; using {shrinkage}")

    circuit_factor: dict[str, float] = {}
    circuit_raw: dict[str, float] = {}
    circuit_races: dict[str, int] = {}
    for circuit, logs in pooled.items():
        n_here = len(logs)
        raw = sum(logs) / n_here
        circuit_raw[circuit] = math.exp(raw)
        circuit_factor[circuit] = math.exp(n_here / (n_here + strength) * raw)
        circuit_races[circuit] = n_here

    _, n, k = _cells(usable)
    return OvertakingModel(
        base=base,
        per_second=per_second,
        circuit_factor=circuit_factor,
        circuit_raw=circuit_raw,
        circuit_races=circuit_races,
        n_races=len(usable),
        n_followers=int(n.sum()),
        n_passes=int(k.sum()),
        era=summary,
        shrinkage=strength,
        warnings=tuple(warnings),
    )
