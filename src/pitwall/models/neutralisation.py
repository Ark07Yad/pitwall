"""What a neutralisation does to a pit stop: safety car and VSC, apart.

Until November 2026 the simulation treated every neutralisation as a full safety
car - the field bunched behind it, every stop under it cost 55% of a green one,
and it ended with a 28% chance each lap. All three were set by hand, and a VSC
does none of the first: the cars hold their gaps at a fixed delta, so the field
stays spread out, and stopping under one buys less than under a safety car.

**The discount.** `scripts/fetch_race_dynamics.py` measures every stop against
what the field did on the same two laps, green ones included, so within one race
the ratio of a neutralised stop to a green one has the circuit cancelled out of
it. The race is the unit, as it is for pit loss: the discount is the median over
races of that race's own ratio, so an afternoon with eleven stops under one
safety car counts once.

**Which kind, and for how long.** Both come from the safety-car history the
hazard is fitted on, read the way the hazard reads it: a run of neutralised laps
is one event, a VSC upgraded to a safety car is one event, and an event is a
safety car if a safety car was out at any point in it. The share of events that
were VSC only is per circuit, shrunk toward the pooled share in units of races;
how long each kind lasts is pooled, because a circuit sees too few to say.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pitwall.models.safety_car import normalise_circuit

DEFAULT_SC_DISCOUNT = 0.55
DEFAULT_END_CHANCE = 0.28
DEFAULT_SHRINKAGE = 2.0
# A race enters the discount only with enough green stops to give its own
# baseline; one neutralised stop against it is enough, since the race median of
# the ratio is what is pooled.
MIN_GREEN_STOPS = 5
# Below this many races the measured discount is not used.
MIN_RACES = 5


@dataclass(frozen=True)
class NeutralisationModel:
    sc_discount: float
    vsc_discount: float
    sc_end_chance: float
    vsc_end_chance: float
    vsc_share: float
    circuit_vsc_share: dict[str, float]
    circuit_races: dict[str, int]
    sc_races: int
    vsc_races: int
    sc_stops: int
    vsc_stops: int
    green_check: float | None = None
    shrinkage: float = DEFAULT_SHRINKAGE
    warnings: tuple[str, ...] = field(default=())

    def vsc_share_for(self, circuit: str) -> float:
        return self.circuit_vsc_share.get(normalise_circuit(circuit), self.vsc_share)

    def __str__(self) -> str:
        lines = [
            "neutralisation:",
            f"  stop under a safety car costs {self.sc_discount:.0%} of a green one "
            f"({self.sc_stops} stops, {self.sc_races} races; hand-set before: "
            f"{DEFAULT_SC_DISCOUNT:.0%})",
            f"  stop under a VSC costs {self.vsc_discount:.0%} "
            f"({self.vsc_stops} stops, {self.vsc_races} races)",
            f"  a safety car lasts {1 / self.sc_end_chance:.1f} laps on average, "
            f"a VSC {1 / self.vsc_end_chance:.1f} "
            f"(hand-set before: {1 / DEFAULT_END_CHANCE:.1f} for both)",
            f"  {self.vsc_share:.0%} of neutralisations are VSC only",
        ]
        if self.green_check is not None:
            lines.append(
                f"  check: green stops against the field read {self.green_check:.1f} s, "
                "for comparison with the pit-loss constant"
            )
        lines += [f"  ! {w}" for w in self.warnings]
        return "\n".join(lines)


def load_stops(path: Path | str) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def events(race: dict[str, Any]) -> list[tuple[str, int]]:
    """(kind, laps) for each neutralisation in one race, read as the hazard reads it."""
    sc = set(race.get("sc_laps") or [])
    active = sc | set(race.get("vsc_laps") or [])
    out: list[tuple[str, int]] = []
    for lap in sorted(active):
        if lap - 1 in active:
            continue
        run = []
        while lap in active:
            run.append(lap)
            lap += 1
        out.append(("sc" if sc & set(run) else "vsc", len(run)))
    return out


def fit_neutralisation(
    stops: list[dict[str, Any]],
    history: list[dict[str, Any]],
    *,
    shrinkage: float = DEFAULT_SHRINKAGE,
) -> NeutralisationModel:
    """Discounts from measured stops, kinds and durations from the safety-car history."""
    warnings: list[str] = []

    ratios: dict[str, list[float]] = {"sc": [], "vsc": []}
    counts = {"sc": 0, "vsc": 0}
    green_medians: list[float] = []
    for race in stops:
        green = race.get("green") or []
        if len(green) < MIN_GREEN_STOPS:
            continue
        baseline = statistics.median(green)
        green_medians.append(baseline)
        for kind in ("sc", "vsc"):
            own = race.get(kind) or []
            if own and baseline > 0:
                ratios[kind].append(statistics.median(own) / baseline)
                counts[kind] += len(own)

    def discount(kind: str, fallback: float) -> float:
        if len(ratios[kind]) < MIN_RACES:
            warnings.append(
                f"{kind.upper()} discount rests on {len(ratios[kind])} races, under {MIN_RACES}; "
                f"using {fallback:.0%}"
            )
            return fallback
        return min(1.0, max(0.0, statistics.median(ratios[kind])))

    sc_discount = discount("sc", DEFAULT_SC_DISCOUNT)
    # With too few VSC stops to measure, a VSC is assumed to cost what a safety
    # car does - the old behaviour - rather than something invented.
    vsc_discount = discount("vsc", sc_discount)

    lengths: dict[str, list[int]] = {"sc": [], "vsc": []}
    per_circuit: dict[str, list[tuple[int, int]]] = defaultdict(list)
    vsc_total = all_total = 0
    for race in history:
        found = events(race)
        for kind, length in found:
            lengths[kind].append(length)
        vsc_only = sum(1 for kind, _ in found if kind == "vsc")
        per_circuit[normalise_circuit(race.get("circuit"))].append((vsc_only, len(found)))
        vsc_total += vsc_only
        all_total += len(found)

    def end_chance(kind: str) -> float:
        if not lengths[kind]:
            return DEFAULT_END_CHANCE
        return 1.0 / statistics.mean(lengths[kind])

    pooled_share = vsc_total / all_total if all_total else 0.0
    circuit_share: dict[str, float] = {}
    circuit_races: dict[str, int] = {}
    for circuit, rows in per_circuit.items():
        vsc_here = sum(v for v, _ in rows)
        events_here = sum(t for _, t in rows)
        races_here = len(rows)
        own = vsc_here / events_here if events_here else pooled_share
        # Shrunk in units of races, like every other per-circuit number here; a
        # circuit whose races saw no neutralisation at all says nothing about
        # the mix and keeps the pooled share.
        weight = races_here if events_here else 0
        circuit_share[circuit] = (weight * own + shrinkage * pooled_share) / (weight + shrinkage)
        circuit_races[circuit] = races_here

    return NeutralisationModel(
        sc_discount=sc_discount,
        vsc_discount=vsc_discount,
        sc_end_chance=end_chance("sc"),
        vsc_end_chance=end_chance("vsc"),
        vsc_share=pooled_share,
        circuit_vsc_share=circuit_share,
        circuit_races=circuit_races,
        sc_races=len(ratios["sc"]),
        vsc_races=len(ratios["vsc"]),
        sc_stops=counts["sc"],
        vsc_stops=counts["vsc"],
        green_check=statistics.median(green_medians) if green_medians else None,
        shrinkage=shrinkage,
        warnings=tuple(warnings),
    )
