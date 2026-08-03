"""Per-circuit safety-car hazard.

Safety cars are the largest single source of strategic variance in a race. A stop
taken under one costs perhaps half its usual time, so "how likely is a safety car
in the next ten laps" changes whether a pit window is worth taking - and no
public dataset publishes per-circuit rates, so this fits one.

Two things make the estimate honest.

**It is a discrete-time hazard, not a rate.** For every lap the question is "given
no safety car is out, does one get deployed on this lap?" Laps that are already
running under one are *not at risk* and are excluded from exposure entirely.
Counting them would inflate every circuit that happens to have long safety-car
periods, which is precisely backwards.

**Circuit estimates are shrunk toward the global mean.** Five seasons gives about
five races per circuit and often one or two safety cars. Taking that at face
value produces nonsense like "Jeddah 3x more dangerous than Monza" off a
difference of two events. A Gamma-Poisson empirical-Bayes shrinkage pulls
sparsely-observed circuits back toward the field average, and only lets a circuit
move the estimate once it has the exposure to earn it.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# Lap 1 is its own bucket: a standing start with a full field into turn 1 is a
# different risk regime from anything that follows, and lumping it into "early"
# smears that spike across a quarter of the race.
BUCKETS: tuple[str, ...] = ("lap1", "early", "mid", "late", "final")

# Strength of the shrinkage prior, in units of expected events. A circuit needs
# roughly this much exposure before its own history outweighs the field average.
DEFAULT_SHRINKAGE = 3.0

# FastF1's `Location` is not a stable circuit identity, and this keeps happening:
# Miami was "Miami" through 2024 and "Miami Gardens" from 2025, and Monaco became
# "Monte Carlo" in 2026. Each rename silently splits a circuit's history into two
# under-sampled entries that shrinkage then flattens toward the mean - no error,
# just a quietly worse model. Check this table whenever a season is added.
#
# Normalising here rather than in the fetcher means existing data files are
# corrected without re-spending API calls against a 500/hour limit.
CIRCUIT_ALIASES: dict[str, str] = {
    "Miami Gardens": "Miami",
    "Monte Carlo": "Monaco",
}


def normalise_circuit(name: object) -> str:
    cleaned = str(name or "unknown").strip()
    return CIRCUIT_ALIASES.get(cleaned, cleaned)


class EventKind(Enum):
    SAFETY_CAR = "sc"
    VIRTUAL_SAFETY_CAR = "vsc"
    ANY = "any"

    @property
    def starts_key(self) -> str:
        return {"sc": "sc_starts", "vsc": "vsc_starts"}.get(self.value, "")

    @property
    def active_key(self) -> str:
        return {"sc": "sc_laps", "vsc": "vsc_laps"}.get(self.value, "")


def bucket_for(lap: int, total_laps: int) -> str:
    """Which phase of the race a lap belongs to."""
    if lap <= 1:
        return "lap1"
    if total_laps <= 1:
        return "early"
    fraction = (lap - 1) / max(1, total_laps - 1)
    if fraction < 0.25:
        return "early"
    if fraction < 0.50:
        return "mid"
    if fraction < 0.75:
        return "late"
    return "final"


def _event_laps(race: dict[str, Any], kind: EventKind) -> tuple[set[int], set[int]]:
    """Return (starts, active) lap sets for the requested event type."""
    if kind is EventKind.ANY:
        starts: set[int] = set()
        active: set[int] = set()
        for sub in (EventKind.SAFETY_CAR, EventKind.VIRTUAL_SAFETY_CAR):
            s, a = _event_laps(race, sub)
            starts |= s
            active |= a
        # A VSC upgraded to a full safety car on the next lap is one event, not
        # two, so a "start" that continues an already-active period is dropped.
        return {lap for lap in starts if lap - 1 not in active}, active
    return set(race.get(kind.starts_key, [])), set(race.get(kind.active_key, []))


@dataclass(frozen=True)
class HazardModel:
    """Per-lap probability that a safety car is deployed."""

    kind: EventKind
    baseline: dict[str, float]
    circuit_factor: dict[str, float]
    circuit_races: dict[str, int]
    n_races: int
    n_events: int
    shrinkage: float = DEFAULT_SHRINKAGE
    warnings: tuple[str, ...] = field(default=())

    def hazard(self, circuit: str, lap: int, total_laps: int) -> float:
        """P(deployment on this lap | none currently active)."""
        base = self.baseline.get(bucket_for(lap, total_laps), 0.0)
        factor = self.circuit_factor.get(normalise_circuit(circuit), 1.0)
        return min(1.0, base * factor)

    def survival(self, circuit: str, from_lap: int, to_lap: int, total_laps: int) -> float:
        """P(no deployment over laps `from_lap`..`to_lap` inclusive)."""
        probability = 1.0
        for lap in range(max(1, from_lap), max(0, to_lap) + 1):
            probability *= 1.0 - self.hazard(circuit, lap, total_laps)
        return probability

    def probability_within(
        self, circuit: str, from_lap: int, to_lap: int, total_laps: int
    ) -> float:
        """P(at least one deployment in the window) - the strategy-facing number."""
        return 1.0 - self.survival(circuit, from_lap, to_lap, total_laps)

    def expected_events(self, circuit: str, total_laps: int) -> float:
        return sum(self.hazard(circuit, lap, total_laps) for lap in range(1, total_laps + 1))

    def known_circuit(self, circuit: str) -> bool:
        return normalise_circuit(circuit) in self.circuit_factor

    def __str__(self) -> str:
        lines = [
            f"{self.kind.value.upper()} hazard from {self.n_races} races, {self.n_events} events",
            "",
            "  baseline per-lap hazard by race phase:",
        ]
        for name in BUCKETS:
            if name in self.baseline:
                lines.append(f"    {name:<6} {self.baseline[name]:.4f}")
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


def load_history(path: Path | str) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fit_hazard(
    races: list[dict[str, Any]],
    kind: EventKind = EventKind.SAFETY_CAR,
    shrinkage: float = DEFAULT_SHRINKAGE,
) -> HazardModel | None:
    """Fit the hazard from collected race histories."""
    if not races:
        return None

    events_by_bucket: dict[str, int] = defaultdict(int)
    exposure_by_bucket: dict[str, int] = defaultdict(int)
    circuit_events: dict[str, int] = defaultdict(int)
    circuit_laps: dict[str, list[tuple[int, int]]] = defaultdict(list)
    circuit_races: dict[str, int] = defaultdict(int)

    for race in races:
        total = int(race.get("total_laps") or 0)
        if total < 2:
            continue
        circuit = normalise_circuit(race.get("circuit"))
        starts, active = _event_laps(race, kind)
        circuit_races[circuit] += 1

        for lap in range(1, total + 1):
            # Already neutralised: not at risk of a *new* deployment.
            if lap in active and lap not in starts:
                continue
            bucket = bucket_for(lap, total)
            exposure_by_bucket[bucket] += 1
            circuit_laps[circuit].append((lap, total))
            if lap in starts:
                events_by_bucket[bucket] += 1
                circuit_events[circuit] += 1

    total_events = sum(events_by_bucket.values())
    total_exposure = sum(exposure_by_bucket.values())
    if total_exposure == 0:
        return None

    baseline = {
        bucket: events_by_bucket[bucket] / exposure_by_bucket[bucket]
        for bucket in BUCKETS
        if exposure_by_bucket.get(bucket)
    }

    # Expected events per circuit under the global baseline, then shrink the
    # observed/expected ratio toward 1.
    circuit_factor: dict[str, float] = {}
    for circuit, laps in circuit_laps.items():
        expected = sum(baseline.get(bucket_for(lap, total), 0.0) for lap, total in laps)
        observed = circuit_events[circuit]
        circuit_factor[circuit] = (observed + shrinkage) / (expected + shrinkage)

    warnings: list[str] = []
    if total_events < 20:
        warnings.append(f"only {total_events} events in the sample - baseline hazards are noisy")
    thin = [c for c, n in circuit_races.items() if n < 3]
    if thin:
        warnings.append(
            f"{len(thin)} circuits have fewer than 3 races; their factors are "
            "dominated by the prior and carry little information"
        )

    return HazardModel(
        kind=kind,
        baseline=baseline,
        circuit_factor=circuit_factor,
        circuit_races=dict(circuit_races),
        n_races=len(races),
        n_events=total_events,
        shrinkage=shrinkage,
        warnings=tuple(warnings),
    )
