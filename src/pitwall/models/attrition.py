"""Per-circuit retirement hazard.

Cars break, crash and get collected in someone else's accident. Roughly one car
in ten does not finish, and a simulation in which every car reaches the flag is
therefore wrong in a specific and one-sided way: it never promotes anyone. A car
running P8 gains places when two cars ahead retire, and a model without
attrition treats that as impossible rather than as a one-in-ten event repeated
across seven cars ahead.

Fitted the same way as the safety-car hazard, and for the same reasons.

**Exposure is per car-lap, not per race.** A car that retires on lap 20 was at
risk for twenty laps and then stopped being at risk; counting it as a full race
of exposure would understate the hazard, and counting the race rather than the
car would ignore that twenty-two cars are each rolling the dice.

**Circuit factors are shrunk toward the field mean.** Four races per circuit with
one or two retirements cannot justify a raw ratio.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pitwall.models.safety_car import BUCKETS, bucket_for, normalise_circuit

# Same units as the safety-car prior: expected events before a circuit's own
# history outweighs the field average. Retirements are more common than safety
# cars, so a circuit earns its own estimate sooner.
DEFAULT_SHRINKAGE = 4.0


@dataclass(frozen=True)
class AttritionModel:
    """Per-lap probability that a given car retires."""

    baseline: dict[str, float]
    circuit_factor: dict[str, float]
    circuit_races: dict[str, int]
    n_races: int
    n_starters: int
    n_retirements: int
    shrinkage: float = DEFAULT_SHRINKAGE
    warnings: tuple[str, ...] = field(default=())

    @property
    def rate_per_car(self) -> float:
        """Share of starters that fail to finish."""
        return self.n_retirements / self.n_starters if self.n_starters else 0.0

    def hazard(self, circuit: str, lap: int, total_laps: int) -> float:
        """P(this car retires on this lap | it is still running)."""
        base = self.baseline.get(bucket_for(lap, total_laps), 0.0)
        factor = self.circuit_factor.get(normalise_circuit(circuit), 1.0)
        return min(1.0, base * factor)

    def survival(self, circuit: str, from_lap: int, to_lap: int, total_laps: int) -> float:
        """P(one car is still running at the end of the window)."""
        probability = 1.0
        for lap in range(max(1, from_lap), max(0, to_lap) + 1):
            probability *= 1.0 - self.hazard(circuit, lap, total_laps)
        return probability

    def probability_within(
        self, circuit: str, from_lap: int, to_lap: int, total_laps: int
    ) -> float:
        return 1.0 - self.survival(circuit, from_lap, to_lap, total_laps)

    def expected_retirements(self, circuit: str, total_laps: int, n_cars: int) -> float:
        """How many of `n_cars` are expected not to finish."""
        return n_cars * self.probability_within(circuit, 1, total_laps, total_laps)

    def known_circuit(self, circuit: str) -> bool:
        return normalise_circuit(circuit) in self.circuit_factor

    def __str__(self) -> str:
        lines = [
            f"attrition from {self.n_races} races: {self.n_retirements} retirements "
            f"of {self.n_starters} starters ({self.rate_per_car:.1%} per car)",
            "",
            "  baseline per-car-lap hazard by race phase:",
        ]
        for name in BUCKETS:
            if name in self.baseline:
                lines.append(f"    {name:<6} {self.baseline[name]:.5f}")
        ranked = sorted(self.circuit_factor.items(), key=lambda kv: -kv[1])
        if ranked:
            lines.append("")
            lines.append(f"  circuit factor (shrunk, prior weight {self.shrinkage:g}):")
            for circuit, factor in ranked:
                races = self.circuit_races.get(circuit, 0)
                lines.append(f"    {circuit:<24} {factor:>5.2f}x  ({races} races)")
        for warning in self.warnings:
            lines.append(f"  ! {warning}")
        return "\n".join(lines)


def fit_attrition(
    races: list[dict[str, Any]],
    shrinkage: float = DEFAULT_SHRINKAGE,
) -> AttritionModel | None:
    """Fit the retirement hazard from collected race histories."""
    usable = [r for r in races if r.get("starters") and r.get("total_laps", 0) >= 2]
    if not usable:
        return None

    events: dict[str, int] = defaultdict(int)
    exposure: dict[str, int] = defaultdict(int)
    circuit_events: dict[str, int] = defaultdict(int)
    circuit_exposure: dict[str, list[tuple[int, int]]] = defaultdict(list)
    circuit_races: dict[str, int] = defaultdict(int)

    total_starters = 0
    total_retirements = 0

    for race in usable:
        total = int(race["total_laps"])
        circuit = normalise_circuit(race.get("circuit"))
        starters = int(race["starters"])
        retired = [int(lap) for lap in race.get("retirements", []) if lap >= 1]

        circuit_races[circuit] += 1
        total_starters += starters
        total_retirements += len(retired)

        # Cars that finished were at risk for the whole race.
        for _ in range(max(0, starters - len(retired))):
            for lap in range(1, total + 1):
                bucket = bucket_for(lap, total)
                exposure[bucket] += 1
                circuit_exposure[circuit].append((lap, total))

        # Cars that retired were at risk up to and including the lap they
        # stopped on, and that lap is the event.
        for stop in retired:
            stop = min(stop, total)
            for lap in range(1, stop + 1):
                bucket = bucket_for(lap, total)
                exposure[bucket] += 1
                circuit_exposure[circuit].append((lap, total))
            bucket = bucket_for(stop, total)
            events[bucket] += 1
            circuit_events[circuit] += 1

    if not exposure:
        return None

    baseline = {
        bucket: events[bucket] / exposure[bucket] for bucket in BUCKETS if exposure.get(bucket)
    }

    circuit_factor: dict[str, float] = {}
    for circuit, laps in circuit_exposure.items():
        expected = sum(baseline.get(bucket_for(lap, total), 0.0) for lap, total in laps)
        observed = circuit_events[circuit]
        circuit_factor[circuit] = (observed + shrinkage) / (expected + shrinkage)

    warnings: list[str] = []
    if total_retirements < 40:
        warnings.append(
            f"only {total_retirements} retirements in the sample - phase hazards are noisy"
        )
    thin = [c for c, n in circuit_races.items() if n < 3]
    if thin:
        warnings.append(
            f"{len(thin)} circuits have fewer than 3 races; their factors are "
            "dominated by the prior"
        )

    return AttritionModel(
        baseline=baseline,
        circuit_factor=circuit_factor,
        circuit_races=dict(circuit_races),
        n_races=len(usable),
        n_starters=total_starters,
        n_retirements=total_retirements,
        shrinkage=shrinkage,
        warnings=tuple(warnings),
    )


def load_history(path: Path | str) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
