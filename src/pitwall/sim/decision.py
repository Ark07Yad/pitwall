"""Turning simulated distributions into a pit call.

The simulation answers "what happens if". This turns that into "so do this",
which is the only output a pit wall actually wants.

The question is deliberately framed as *when*, not *whether*. "Should we pit?"
has no meaningful answer in a race with a mandatory tyre change - the stop is
happening. What matters is whether it happens now or in five laps, and on what.
So every option here is a (delay, compound) pair, and staying out is just a stop
with a larger delay, evaluated on exactly the same footing.

Options are compared on expected finishing position rather than expected race
time. Time is what the model computes, but position is what scores points, and
the two come apart precisely when it matters - two seconds is worth nothing in
clear air and everything when it decides a pit exit.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from pitwall.models.attrition import AttritionModel
from pitwall.models.pace import PaceFit
from pitwall.models.safety_car import HazardModel
from pitwall.sim.race import CarEntry, SimConfig, simulate
from pitwall.state.models import Compound

DEFAULT_COMPOUNDS: tuple[Compound, ...] = (Compound.SOFT, Compound.MEDIUM, Compound.HARD)
DEFAULT_DELAYS: tuple[int, ...] = (0, 3, 6, 10)

# Below this gap in expected position, two options are not meaningfully
# different given the noise a few thousand simulations carry.
DECISIVE_MARGIN = 0.15


@dataclass(frozen=True)
class Outcome:
    """How one candidate stop is expected to turn out."""

    delay: int
    compound: Compound
    pit_lap: int
    mean_position: float
    p_top3: float
    p_points: float
    p_gain: float
    p_retire: float = 0.0
    # P(finishing at each position). The simulation computes a whole
    # distribution and reporting only its mean throws away the part that says
    # how *uncertain* the call is - a tight spread around P4 and a coin-flip
    # between P2 and P8 have the same mean and mean very different things.
    distribution: dict[int, float] = field(default_factory=dict)

    @property
    def label(self) -> str:
        when = "now" if self.delay == 0 else f"lap +{self.delay}"
        return f"{when} on {self.compound.short}"


@dataclass(frozen=True)
class Recommendation:
    driver: str
    tla: str
    lap: int
    current_position: int
    outcomes: tuple[Outcome, ...]
    n_sims: int

    @property
    def best(self) -> Outcome:
        return self.outcomes[0]

    @property
    def margin(self) -> float:
        """Gap in expected position between the best option and the next."""
        if len(self.outcomes) < 2:
            return 0.0
        return self.outcomes[1].mean_position - self.outcomes[0].mean_position

    @property
    def decisive(self) -> bool:
        return self.margin >= DECISIVE_MARGIN

    def __str__(self) -> str:
        head = f"{self.tla} P{self.current_position}, lap {self.lap} ({self.n_sims:,} sims)"
        verdict = (
            f"  → PIT {self.best.label}"
            if self.decisive
            else f"  → {self.best.label} marginally ahead; no clear call"
        )
        lines = [
            head,
            verdict,
            f"     expected P{self.best.mean_position:.2f}, "
            f"margin {self.margin:+.2f} to next option",
            "",
            f"  {'option':<18} {'exp. pos':>9} {'top3':>7} {'points':>7} {'gain':>7}",
        ]
        for outcome in self.outcomes:
            lines.append(
                f"  {outcome.label:<18} {outcome.mean_position:>9.2f} "
                f"{outcome.p_top3:>6.1%} {outcome.p_points:>7.1%} {outcome.p_gain:>7.1%}"
            )
        return "\n".join(lines)


def evaluate_actions(
    entries: list[CarEntry],
    *,
    our_driver: str,
    from_lap: int,
    total_laps: int,
    circuit: str,
    pace: PaceFit,
    hazard: HazardModel | None = None,
    attrition: AttritionModel | None = None,
    compounds: tuple[Compound, ...] = DEFAULT_COMPOUNDS,
    delays: tuple[int, ...] = DEFAULT_DELAYS,
    config: SimConfig | None = None,
) -> Recommendation:
    """Simulate every candidate stop and rank them by expected finish."""
    cfg = config or SimConfig()
    index = next((i for i, e in enumerate(entries) if e.driver == our_driver), None)
    if index is None:
        raise ValueError(f"{our_driver} is not in the entry list")

    start_position = sorted(range(len(entries)), key=lambda i: entries[i].elapsed).index(index) + 1

    outcomes: list[Outcome] = []
    for delay in delays:
        pit_lap = min(from_lap + delay, total_laps)
        for compound in compounds:
            ours = replace(entries[index], planned_pit=pit_lap, planned_compound=compound)
            grid = list(entries)
            grid[index] = ours

            # Same seed for every option: the candidates then face identical
            # safety cars and identical rival scatter, so the difference between
            # them is the decision rather than the luck of the draw.
            result = simulate(
                grid,
                from_lap=from_lap,
                total_laps=total_laps,
                circuit=circuit,
                pace=pace,
                hazard=hazard,
                attrition=attrition,
                config=cfg,
            )
            positions = result.positions[:, index]
            values, counts = np.unique(positions, return_counts=True)
            outcomes.append(
                Outcome(
                    distribution={
                        int(v): float(c / len(positions))
                        for v, c in zip(values, counts, strict=False)
                    },
                    delay=delay,
                    compound=compound,
                    pit_lap=pit_lap,
                    mean_position=float(positions.mean()),
                    p_top3=float((positions <= 3).mean()),
                    p_points=float((positions <= 10).mean()),
                    p_gain=float((positions < start_position).mean()),
                    p_retire=result.probability_retired(our_driver),
                )
            )

    outcomes.sort(key=lambda o: o.mean_position)
    return Recommendation(
        driver=our_driver,
        tla=entries[index].tla,
        lap=from_lap,
        current_position=start_position,
        outcomes=tuple(outcomes),
        n_sims=cfg.n_sims,
    )


@dataclass(frozen=True)
class UndercutThreat:
    rival: str
    tla: str
    gap: float
    probability: float


def undercut_threats(
    entries: list[CarEntry],
    *,
    our_driver: str,
    from_lap: int,
    total_laps: int,
    circuit: str,
    pace: PaceFit,
    hazard: HazardModel | None = None,
    attrition: AttritionModel | None = None,
    window: float = 4.0,
    our_pit_lap: int | None = None,
    config: SimConfig | None = None,
) -> list[UndercutThreat]:
    """Which cars behind could jump us by stopping now, and how likely.

    `our_pit_lap` is the stop we intend to make, and it has to be supplied for
    the number to mean anything. Leaving our own car with no plan compares "they
    stop" against "we never stop", which is not an undercut - it is just the
    inevitable result of staying out on dead tyres, and it reports alarming
    probabilities for threats that do not exist.

    Only cars within `window` seconds are considered; beyond that a single stop
    cannot bridge the gap, so simulating them is wasted work.
    """
    cfg = config or SimConfig()
    index = next((i for i, e in enumerate(entries) if e.driver == our_driver), None)
    if index is None:
        raise ValueError(f"{our_driver} is not in the entry list")

    ours = entries[index]
    if our_pit_lap is not None:
        ours = replace(ours, planned_pit=our_pit_lap)
    threats: list[UndercutThreat] = []

    for i, rival in enumerate(entries):
        gap = rival.elapsed - ours.elapsed
        if i == index or not 0 < gap <= window:
            continue

        grid = list(entries)
        grid[index] = ours
        grid[i] = replace(rival, planned_pit=from_lap, planned_compound=Compound.HARD)
        result = simulate(
            grid,
            from_lap=from_lap,
            total_laps=total_laps,
            circuit=circuit,
            pace=pace,
            hazard=hazard,
            attrition=attrition,
            config=cfg,
        )
        threats.append(
            UndercutThreat(
                rival=rival.driver,
                tla=rival.tla,
                gap=gap,
                probability=result.probability_ahead_of(rival.driver, our_driver),
            )
        )

    threats.sort(key=lambda t: -t.probability)
    return threats
