"""Turning simulated distributions into a pit call.

The simulation answers "what happens if". This turns that into "so do this",
which is the only output a pit wall actually wants.

The question is mostly framed as *when*, not *whether*. "Should we pit?" has no
meaningful answer while a mandatory tyre change is still outstanding - the stop
is happening, and what matters is whether it happens now or in five laps, and on
what. So options are (delay, compound) pairs, evaluated on identical footing.

**But once the car has made its stop, "whether" becomes a real question**, and
treating staying out as "a stop with a larger delay" stops being harmless. Every
delay clamps at the flag, so late in a race all twelve options collapse onto the
same lap and the engine recommends a stop nobody would make. At the 2026 Dutch
GP it advised pitting the leader on lap 71 of 72 and put his expected finish at
P4.90; he won. Across 49 logged calls that cost it 167% negative skill against
a baseline of assuming nothing changes.

So a `stay out` option is offered whenever the car has already stopped at least
once - which is exactly the condition under which it is legal, and the condition
under which the old framing's premise expires.

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
from pitwall.models.pit_loss import PitLossModel
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
    # True when the option requires running a tyre older than anything observed
    # on that compound in this race. The model is then guessing, not measuring:
    # teams pit before the cliff, so the long-stint end of the curve is barely in
    # the data, and a linear rate extrapolated through it promises a tyre that
    # lasts forever. Staying out is the option that most often needs this, and it
    # is exactly the option that benefits from the optimism.
    extrapolated: bool = False
    # False for the option of not stopping again. `pit_lap` is then the flag,
    # which is where a car that never stops "pits" as far as the sim is
    # concerned - but the two are different calls and must not read alike.
    stop: bool = True
    # P(finishing at each position). The simulation computes a whole
    # distribution and reporting only its mean throws away the part that says
    # how *uncertain* the call is - a tight spread around P4 and a coin-flip
    # between P2 and P8 have the same mean and mean very different things.
    distribution: dict[int, float] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if not self.stop:
            return "stay out"
        when = "now" if self.delay == 0 else f"lap +{self.delay}"
        return f"{when} on {self.compound.short}"

    @property
    def caveat(self) -> str:
        return " (beyond observed tyre life)" if self.extrapolated else ""


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
            f"  → PIT {self.best.label}{self.best.caveat}"
            if self.decisive
            else f"  → {self.best.label} marginally ahead; no clear call{self.best.caveat}"
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
                f"{'  ?' if outcome.extrapolated else ''}"
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
    pit_loss: PitLossModel | None = None,
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

    def evaluate(*, planned_pit: int | None, compound: Compound, delay: int, stop: bool) -> Outcome:
        # How old the tyre this option finishes on will be at the flag. Staying
        # out carries the current tyre all the way; stopping starts a fresh one.
        if stop and planned_pit is not None:
            final_age = total_laps - planned_pit
        else:
            final_age = entries[index].tyre_age + (total_laps - from_lap)
        extrapolated = pace.extrapolating(compound, final_age)

        ours = replace(entries[index], planned_pit=planned_pit, planned_compound=compound)
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
            pit_loss=pit_loss,
            config=cfg,
        )
        positions = result.positions[:, index]
        values, counts = np.unique(positions, return_counts=True)
        return Outcome(
            distribution={
                int(v): float(c / len(positions)) for v, c in zip(values, counts, strict=False)
            },
            delay=delay,
            compound=compound,
            pit_lap=planned_pit if planned_pit is not None else total_laps,
            mean_position=float(positions.mean()),
            p_top3=float((positions <= 3).mean()),
            p_points=float((positions <= 10).mean()),
            p_gain=float((positions < start_position).mean()),
            p_retire=result.probability_retired(our_driver),
            extrapolated=extrapolated,
            stop=stop,
        )

    outcomes: list[Outcome] = []
    for delay in delays:
        pit_lap = min(from_lap + delay, total_laps)
        for compound in compounds:
            outcomes.append(
                evaluate(planned_pit=pit_lap, compound=compound, delay=delay, stop=True)
            )

    # Running to the flag on the current tyre. Only offered once the car has
    # stopped at least once: before that the tyre-change requirement makes it
    # illegal, and offering an option the car cannot take is worse than not
    # modelling it. `planned_pit=None` is how the simulation already expresses
    # "not planning to stop", so this needs no new machinery underneath.
    if entries[index].stops > 0:
        outcomes.append(
            evaluate(
                planned_pit=None,
                compound=entries[index].compound,
                delay=0,
                stop=False,
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
    pit_loss: PitLossModel | None = None,
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
            pit_loss=pit_loss,
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
