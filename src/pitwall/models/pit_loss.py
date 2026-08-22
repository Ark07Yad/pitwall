"""Per-circuit pit loss.

The time a stop costs is the most stable constant in the sport: it is fixed by
pit lane geometry and a speed limit, not by car performance. Monza measures
25.2, 25.3, 25.8 and 25.3 seconds across four consecutive seasons. That
stability is exactly why modelling it as one flat number for every circuit was
expensive - the constant is reliable, it is just *different everywhere*, and the
spread across the calendar is around nine seconds from Spa to Marina Bay.

It is also the number the timing of every pit call rests on. The simulation asks
whether the track position lost by stopping is repaid before the flag; get the
cost wrong by two seconds and the answer to "now or in three laps" moves with
it. A flat 20.0 s was overstating how cheap a stop is at most of the calendar
and understating it at Spa.

**What the number means here** is total time lost against staying out - in-lap
delta plus out-lap delta - because that is precisely what the simulation adds to
a pitting car's lap. It is measured on green-flag stops only; a stop under a
safety car is cheaper, and the simulation applies that discount separately.

**Circuits are shrunk toward the field median.** Four or five races per circuit,
and some of those wet, is not enough to justify a raw per-circuit number. A
circuit has to earn its distance from the field average with observations, on
the same empirical-Bayes reasoning the safety-car hazard uses - and for the same
reason: the alternative is letting one chaotic afternoon define a constant.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pitwall.models.safety_car import normalise_circuit

# Fallback when there is no history at all. The value the engine used for every
# circuit before this model existed, kept so an empty data file degrades to the
# old behaviour rather than to zero.
DEFAULT_PIT_LOSS = 20.0
DEFAULT_SPREAD = 1.2

# Races, not stops. A circuit needs roughly this much history before its own
# median outweighs the field's.
DEFAULT_SHRINKAGE = 2.0

# IQR to standard deviation for a normal distribution. Used instead of a plain
# standard deviation because the stop distribution has a long right tail - a
# botched stop is ten seconds, a good one is never ten seconds early - and that
# tail would inflate a symmetric spread the simulation then draws both ways.
IQR_TO_SD = 1.349


@dataclass(frozen=True)
class PitLossModel:
    """Green-flag time lost to a pit stop, per circuit."""

    baseline: float
    circuit_loss: dict[str, float]
    circuit_raw: dict[str, float]
    circuit_spread: dict[str, float]
    circuit_races: dict[str, int]
    circuit_stops: dict[str, int]
    spread: float
    n_races: int
    n_stops: int
    shrinkage: float = DEFAULT_SHRINKAGE
    warnings: tuple[str, ...] = field(default=())

    def loss(self, circuit: str) -> float:
        """Seconds lost by pitting under green here."""
        return self.circuit_loss.get(normalise_circuit(circuit), self.baseline)

    def spread_for(self, circuit: str) -> float:
        """Lap-to-lap scatter in that cost, for the simulation to draw against."""
        return self.circuit_spread.get(normalise_circuit(circuit), self.spread)

    def known_circuit(self, circuit: str) -> bool:
        return normalise_circuit(circuit) in self.circuit_loss

    def races_at(self, circuit: str) -> int:
        return self.circuit_races.get(normalise_circuit(circuit), 0)

    def __str__(self) -> str:
        lines = [
            f"Green-flag pit loss from {self.n_races} races, {self.n_stops} stops",
            "",
            f"  field median {self.baseline:.2f}s  (spread {self.spread:.2f}s)",
        ]
        ranked = sorted(self.circuit_loss.items(), key=lambda kv: kv[1])
        if ranked:
            lines.append("")
            lines.append(f"  per circuit (shrunk, prior weight {self.shrinkage:g} races):")
            lines.append(f"    {'circuit':<24} {'shrunk':>7} {'raw':>7} {'sd':>6}  races  stops")
            for circuit, value in ranked:
                raw = self.circuit_raw.get(circuit, value)
                sd = self.circuit_spread.get(circuit, self.spread)
                races = self.circuit_races.get(circuit, 0)
                stops = self.circuit_stops.get(circuit, 0)
                lines.append(
                    f"    {circuit:<24} {value:>6.2f}s {raw:>6.2f}s {sd:>5.2f}s"
                    f" {races:>6} {stops:>6}"
                )
        for warning in self.warnings:
            lines.append(f"  ! {warning}")
        return "\n".join(lines)


def load_pit_loss(path: Path | str) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fit_pit_loss(
    races: list[dict[str, Any]],
    shrinkage: float = DEFAULT_SHRINKAGE,
) -> PitLossModel | None:
    """Fit per-circuit pit loss from collected race medians.

    The unit of observation is the race, not the stop. A single wet afternoon can
    yield forty measurable stops and a median two seconds off; letting it outvote
    three clean races at the same circuit is how a stable constant gets an
    unstable estimate.
    """
    usable = [r for r in races if r.get("median_loss") is not None]
    if not usable:
        return None

    by_circuit: dict[str, list[float]] = defaultdict(list)
    spreads: dict[str, list[float]] = defaultdict(list)
    stops: dict[str, int] = defaultdict(int)

    all_medians: list[float] = []
    all_spreads: list[float] = []
    total_stops = 0

    for race in usable:
        circuit = normalise_circuit(race.get("circuit"))
        median = float(race["median_loss"])
        by_circuit[circuit].append(median)
        all_medians.append(median)

        n = int(race.get("n_stops") or 0)
        stops[circuit] += n
        total_stops += n

        q1, q3 = race.get("q1"), race.get("q3")
        if q1 is not None and q3 is not None and q3 >= q1:
            robust = (float(q3) - float(q1)) / IQR_TO_SD
            spreads[circuit].append(robust)
            all_spreads.append(robust)

    baseline = statistics.median(all_medians)
    global_spread = statistics.median(all_spreads) if all_spreads else DEFAULT_SPREAD

    circuit_loss: dict[str, float] = {}
    circuit_raw: dict[str, float] = {}
    circuit_spread: dict[str, float] = {}
    circuit_races: dict[str, int] = {}

    for circuit, medians in by_circuit.items():
        n = len(medians)
        raw = statistics.median(medians)
        # Shrink toward the field median in units of races.
        circuit_loss[circuit] = (n * raw + shrinkage * baseline) / (n + shrinkage)
        circuit_raw[circuit] = raw
        circuit_races[circuit] = n

        own = spreads.get(circuit)
        if own:
            circuit_spread[circuit] = (n * statistics.median(own) + shrinkage * global_spread) / (
                n + shrinkage
            )
        else:
            circuit_spread[circuit] = global_spread

    warnings: list[str] = []
    thin = sorted(c for c, n in circuit_races.items() if n < 2)
    if thin:
        warnings.append(
            f"{len(thin)} circuit(s) fitted on a single race, held near the field median: "
            + ", ".join(thin)
        )

    return PitLossModel(
        baseline=baseline,
        circuit_loss=circuit_loss,
        circuit_raw=circuit_raw,
        circuit_spread=circuit_spread,
        circuit_races=circuit_races,
        circuit_stops=dict(stops),
        spread=global_spread,
        n_races=len(usable),
        n_stops=total_stops,
        shrinkage=shrinkage,
        warnings=tuple(warnings),
    )
