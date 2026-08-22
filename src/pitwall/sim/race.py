"""Monte Carlo race simulation.

Rolls the remainder of a race forward thousands of times and returns a
distribution over finishing positions. Everything the earlier phases fitted -
pace, fuel, degradation, safety-car hazard - feeds in here, and a pit
recommendation falls out of comparing distributions between candidate actions.

Vectorised over simulations rather than looped: state is held in `(n_sims,
n_cars)` arrays and every lap advances all of them at once. A pure-Python
implementation would run ~3M car-laps for a single decision, which is far too
slow to sit inside a live race; this runs a full race for 2,000 simulations in
well under a second.

Three modelling choices carry most of the realism.

**Track position is enforced.** Cars cannot pass through each other. A car that
catches the one ahead is held within `min_gap` unless it wins an overtake roll,
so a fast car stuck behind a slow one stays stuck - which is the entire reason
track position is worth anything, and the reason an undercut works.

**Safety cars compress the field.** When one deploys, gaps collapse to a few
seconds. That is what makes safety cars the dominant strategic risk: a
twenty-second lead evaporates, and a stop taken under one costs a fraction of
its usual price. Modelling the neutralisation without the bunching would miss
the point of it entirely.

**Rivals are not static.** Their stops are sampled from a policy distribution,
so the answer accounts for the possibility that they cover, or attack.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from pitwall.models.attrition import AttritionModel
from pitwall.models.fuel import FuelModel
from pitwall.models.pace import PaceFit
from pitwall.models.pit_loss import PitLossModel
from pitwall.models.safety_car import HazardModel
from pitwall.state.models import Compound

RACING_COMPOUNDS: tuple[Compound, ...] = (Compound.SOFT, Compound.MEDIUM, Compound.HARD)

# Seconds to place a car behind for each lap it is down. Approximate on purpose -
# a lapped car is out of strategic contention and only its ordering matters.
LAPPED_PENALTY = 40.0
# Spacing used when the feed gives no usable gap for a car.
UNKNOWN_GAP_SPACING = 1.5

# Elapsed time assigned to a retired car so it sorts behind every finisher. Far
# larger than any plausible race, and retirements are then ordered among
# themselves by how far they got.
RETIRED_SENTINEL = 1e9


@dataclass(frozen=True)
class CarEntry:
    """A car's state at the moment the simulation takes over."""

    driver: str
    tla: str
    base_pace: float
    compound: Compound = Compound.MEDIUM
    tyre_age: int = 0
    stops: int = 0
    elapsed: float = 0.0
    # Lap this car is expected to pit next; None means it is not planning to.
    planned_pit: int | None = None
    planned_compound: Compound = Compound.HARD


@dataclass(frozen=True)
class SimConfig:
    n_sims: int = 2000
    seed: int | None = 7

    # Time lost pitting under green: pit lane transit plus the stop itself.
    # Circuit-specific and the most stable constant in the sport.
    pit_loss: float = 20.0
    pit_loss_sd: float = 1.2
    # A stop under a safety car costs far less, because the field is crawling.
    sc_pit_discount: float = 0.55

    # Residual lap-time scatter, from the pace fit.
    lap_noise: float = 0.7

    # Following closer than this is not possible without passing.
    min_gap: float = 0.8
    # Per-lap chance of clearing the car ahead, before the pace-delta term.
    overtake_base: float = 0.18
    # Extra chance per second per lap of pace advantage.
    overtake_per_second: float = 0.35

    # A safety car lap costs roughly this much over a green one.
    sc_lap_penalty: float = 32.0
    # Once out, the chance it comes in at the end of any given lap.
    sc_end_chance: float = 0.28
    # Spacing the field is bunched to behind the safety car.
    sc_gap: float = 1.6

    # Spread on when rivals actually take their planned stop.
    rival_pit_jitter: int = 3
    # Chance a rival reacts to our stop by covering it on the next lap.
    rival_cover_chance: float = 0.35

    # Retirement risk is far lower behind a safety car: the field is crawling in
    # single file, which is when cars are least likely to be lost.
    sc_attrition_factor: float = 0.25


@dataclass
class SimResult:
    """Finishing-position distribution for every car."""

    drivers: list[str]
    tlas: list[str]
    positions: np.ndarray  # (n_sims, n_cars), 1-based finishing position
    sc_deployed: np.ndarray  # (n_sims,) count of safety cars in the run
    retired: np.ndarray | None = None  # (n_sims, n_cars) bool, did not finish
    config: SimConfig = field(default_factory=SimConfig)

    def index_of(self, driver: str) -> int:
        return self.drivers.index(driver)

    def mean_position(self, driver: str) -> float:
        return float(self.positions[:, self.index_of(driver)].mean())

    def position_probabilities(self, driver: str) -> dict[int, float]:
        column = self.positions[:, self.index_of(driver)]
        values, counts = np.unique(column, return_counts=True)
        return {int(v): float(c / len(column)) for v, c in zip(values, counts, strict=False)}

    def probability_top(self, driver: str, n: int) -> float:
        return float((self.positions[:, self.index_of(driver)] <= n).mean())

    def probability_ahead_of(self, driver: str, rival: str) -> float:
        ours = self.positions[:, self.index_of(driver)]
        theirs = self.positions[:, self.index_of(rival)]
        return float((ours < theirs).mean())

    def probability_retired(self, driver: str) -> float:
        if self.retired is None:
            return 0.0
        return float(self.retired[:, self.index_of(driver)].mean())

    def probability_finished(self, driver: str) -> float:
        return 1.0 - self.probability_retired(driver)


def _compound_index(compound: Compound) -> int:
    try:
        return RACING_COMPOUNDS.index(compound)
    except ValueError:
        return RACING_COMPOUNDS.index(Compound.MEDIUM)


def _lap_time_terms(
    entries: list[CarEntry], pace: PaceFit
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Base pace per car, plus degradation slope and offset per compound."""
    base = np.array([e.base_pace for e in entries], dtype=float)
    degradation = np.array([pace.degradation.get(c, 0.05) for c in RACING_COMPOUNDS], dtype=float)
    offset = np.array([pace.compound_offset.get(c, 0.0) for c in RACING_COMPOUNDS], dtype=float)
    return base, degradation, offset


def _apply_track_position(
    elapsed: np.ndarray,
    order: np.ndarray,
    pace_delta: np.ndarray,
    free_pass: np.ndarray,
    config: SimConfig,
    rng: np.random.Generator,
) -> None:
    """Stop cars driving through each other.

    `order` must be the running order from the *start* of the lap, before this
    lap's times were added. Re-deriving it from the updated times instead lets
    any car that gained more than the gap in a single lap swap position for
    free - no overtake required - which quietly removes the entire cost of being
    stuck in traffic.

    Walks that order from the front. A car inside `min_gap` of the one ahead
    either completes an overtake, with odds rising in its pace advantage, or is
    pinned just behind.

    `free_pass` marks cars that pitted this lap. They are in the pit lane and
    defend nothing, so everyone streams past without a roll; without the
    exemption a car that had just stopped would still hold up the field it was
    nominally ahead of.

    One approximation: the order is only walked once, so a car that drops many
    places in a single lap is not re-compared against its new neighbours. The
    error is bounded by one lap of movement and matters far less than the
    constraint it is enforcing.
    """
    n_sims, n_cars = elapsed.shape
    rows = np.arange(n_sims)

    for rank in range(1, n_cars):
        ahead = order[:, rank - 1]
        behind = order[:, rank]
        gap = elapsed[rows, behind] - elapsed[rows, ahead]

        caught = (gap < config.min_gap) & ~free_pass[rows, ahead]
        if not caught.any():
            continue

        advantage = np.maximum(0.0, pace_delta[rows, ahead] - pace_delta[rows, behind])
        chance = np.clip(config.overtake_base + config.overtake_per_second * advantage, 0.0, 0.95)
        passes = caught & (rng.random(n_sims) < chance)
        held = caught & ~passes

        # Held up: pinned to the minimum following distance.
        if held.any():
            elapsed[rows[held], behind[held]] = elapsed[rows[held], ahead[held]] + config.min_gap
        # Through: emerges just in front, and the pair swap in the order.
        if passes.any():
            elapsed[rows[passes], behind[passes]] = elapsed[rows[passes], ahead[passes]] - 0.1
            order[rows[passes], rank - 1], order[rows[passes], rank] = (
                behind[passes],
                ahead[passes],
            )


def simulate(
    entries: list[CarEntry],
    *,
    from_lap: int,
    total_laps: int,
    circuit: str,
    pace: PaceFit,
    hazard: HazardModel | None = None,
    attrition: AttritionModel | None = None,
    fuel: FuelModel | None = None,
    pit_loss: PitLossModel | None = None,
    config: SimConfig | None = None,
) -> SimResult:
    """Run the race from `from_lap` to the flag, `config.n_sims` times."""
    cfg = config or SimConfig()
    if not entries:
        raise ValueError("no cars to simulate")
    if from_lap > total_laps:
        raise ValueError("from_lap is past the end of the race")

    rng = np.random.default_rng(cfg.seed)
    n_sims, n_cars = cfg.n_sims, len(entries)

    base, degradation, offset = _lap_time_terms(entries, pace)

    # Pit loss is circuit-specific and varies by about nine seconds across the
    # calendar, which is far more than the margin most pit calls turn on. A
    # fitted model supplies it; without one, fall back to the flat config value.
    stop_cost = pit_loss.loss(circuit) if pit_loss is not None else cfg.pit_loss
    stop_cost_sd = pit_loss.spread_for(circuit) if pit_loss is not None else cfg.pit_loss_sd

    # Two ways to get the per-lap trend, and which one is right depends on what
    # is known. A fitted `race_lap_coef` is measured from this race and absorbs
    # track evolution as well as fuel, so prefer it. Passing a `FuelModel`
    # overrides it with physics - the live case on lap 5, where no fit exists
    # yet but the tank is still emptying.
    lap_trend = (
        [fuel.penalty(lap) for lap in range(from_lap, total_laps + 1)]
        if fuel is not None
        else [pace.race_lap_coef * lap for lap in range(from_lap, total_laps + 1)]
    )

    elapsed = np.tile(np.array([e.elapsed for e in entries], dtype=float), (n_sims, 1))
    age = np.tile(np.array([e.tyre_age for e in entries], dtype=float), (n_sims, 1))
    compound = np.tile(
        np.array([_compound_index(e.compound) for e in entries], dtype=int), (n_sims, 1)
    )
    stops = np.tile(np.array([e.stops for e in entries], dtype=int), (n_sims, 1))

    # Rivals do not execute a plan to the lap. Jitter each intended stop so the
    # answer reflects a spread of opponent behaviour rather than one guess.
    planned = np.full((n_sims, n_cars), -1, dtype=int)
    planned_compound = np.tile(
        np.array([_compound_index(e.planned_compound) for e in entries], dtype=int),
        (n_sims, 1),
    )
    for i, entry in enumerate(entries):
        if entry.planned_pit is None:
            continue
        jitter = rng.integers(-cfg.rival_pit_jitter, cfg.rival_pit_jitter + 1, size=n_sims)
        planned[:, i] = np.clip(entry.planned_pit + jitter, from_lap, total_laps)

    sc_active = np.zeros(n_sims, dtype=bool)
    sc_count = np.zeros(n_sims, dtype=int)
    # Cars that have retired. Without this every car reaches the flag, and the
    # simulation can never promote anyone - which understates the chances of a
    # car further back precisely because roughly one in ten does not finish.
    retired = np.zeros((n_sims, n_cars), dtype=bool)
    retired_on = np.zeros((n_sims, n_cars), dtype=float)

    for lap in range(from_lap, total_laps + 1):
        # --- safety car ---
        if hazard is not None:
            rate = hazard.hazard(circuit, lap, total_laps)
            deployed = (~sc_active) & (rng.random(n_sims) < rate)
            sc_active |= deployed
            sc_count += deployed
        else:
            deployed = np.zeros(n_sims, dtype=bool)

        # --- lap time ---
        green_pace = (
            base[None, :]
            + lap_trend[lap - from_lap]
            + offset[compound]
            + degradation[compound] * age
        )
        lap_time = green_pace + rng.normal(0.0, cfg.lap_noise, size=(n_sims, n_cars))
        lap_time[sc_active] += cfg.sc_lap_penalty

        # Running order *before* this lap is added. The track-position rule is
        # enforced against this, not against the updated times.
        order_before = np.argsort(elapsed, axis=1)

        # --- pit stops ---
        pitting = (planned == lap) & (planned >= 0)
        if pitting.any():
            cost = rng.normal(stop_cost, stop_cost_sd, size=(n_sims, n_cars))
            cost = np.where(sc_active[:, None], cost * cfg.sc_pit_discount, cost)
            lap_time = np.where(pitting, lap_time + cost, lap_time)

        # A retired car is parked: it stops accumulating time, so its lap time
        # must not be added and it cannot be overtaken or hold anyone up.
        lap_time = np.where(retired, 0.0, lap_time)
        elapsed += lap_time

        if pitting.any():
            age = np.where(pitting, 0.0, age + 1.0)
            compound = np.where(pitting, planned_compound, compound)
            stops = stops + pitting.astype(int)
            planned = np.where(pitting, -1, planned)
        else:
            age += 1.0

        # --- retirements ---
        if attrition is not None:
            rate = attrition.hazard(circuit, lap, total_laps)
            # A neutralised race is slow and single file, so cars are far less
            # likely to be lost while it is out.
            effective = np.where(sc_active, rate * cfg.sc_attrition_factor, rate)
            failing = (~retired) & (rng.random((n_sims, n_cars)) < effective[:, None])
            if failing.any():
                retired |= failing
                retired_on = np.where(failing, float(lap), retired_on)

        # --- track position ---
        # Pace delta drives overtaking odds: how much quicker a car would be on
        # clear track, ignoring the noise it happened to draw this lap.
        # Retired cars are off the track entirely, so they defend nothing.
        _apply_track_position(elapsed, order_before, -green_pace, pitting | retired, cfg, rng)

        # --- safety car bunching and restart ---
        if deployed.any():
            rows = np.flatnonzero(deployed)
            order = np.argsort(elapsed[rows], axis=1)
            ranks = np.argsort(order, axis=1)
            leader = elapsed[rows].min(axis=1, keepdims=True)
            elapsed[rows] = leader + ranks * cfg.sc_gap
        if sc_active.any():
            ending = sc_active & (rng.random(n_sims) < cfg.sc_end_chance)
            sc_active &= ~ending

    # Retired cars classify behind every finisher, ordered among themselves by
    # how far they got - which is how F1 actually classifies them.
    final = np.where(retired, RETIRED_SENTINEL + (total_laps - retired_on), elapsed)
    order = np.argsort(final, axis=1)
    positions = np.argsort(order, axis=1) + 1

    return SimResult(
        retired=retired,
        drivers=[e.driver for e in entries],
        tlas=[e.tla for e in entries],
        positions=positions,
        sc_deployed=sc_count,
        config=cfg,
    )


def entries_from_pace(
    pace: PaceFit,
    *,
    drivers: dict[str, str] | None = None,
    default_compound: Compound = Compound.MEDIUM,
) -> list[CarEntry]:
    """Build a starting grid from a fitted pace model, quickest car first."""
    names = drivers or {}
    ordered = sorted(pace.driver_pace.items(), key=lambda kv: kv[1])
    return [
        CarEntry(
            driver=driver,
            tla=names.get(driver, driver),
            base_pace=value,
            compound=default_compound,
            elapsed=index * 0.6,
        )
        for index, (driver, value) in enumerate(ordered)
    ]


def with_pit_plan(
    entries: list[CarEntry], lap: int, compound: Compound = Compound.HARD
) -> list[CarEntry]:
    """Give every car the same intended stop - a neutral baseline to vary from."""
    return [replace(e, planned_pit=lap, planned_compound=compound) for e in entries]


def entries_from_state(state, pace: PaceFit) -> list[CarEntry]:
    """Build a simulation grid from live race state.

    The **running order is authoritative**; gaps only refine the spacing within
    it. That ordering matters more than it looks, because `GapToLeader` is not
    reliably a gap: the leader's is blank or carries `"LAP 17"` (the lap it is
    on, not a deficit), a lapped car's is `"2L"`, and a car yet to be timed has
    none at all. An earlier version parsed the field and dropped anything
    unparseable to the back of the grid, which put the race leader 112 seconds
    behind the field in every simulation - and the engine then correctly
    concluded that a car running last would not finish on the podium.

    Elapsed times are therefore forced to be non-decreasing down the order: a
    car classified P4 can never be simulated ahead of P3.
    """
    from pitwall.laps.records import parse_interval, parse_laps_down

    cars = [c for c in state.running_order() if c.tla or c.number]
    entries: list[CarEntry] = []
    last = 0.0

    for index, car in enumerate(cars):
        gap = parse_interval(car.gap_to_leader)
        laps_down = parse_laps_down(car.gap_to_leader)

        if index == 0:
            # The leader defines the reference; its gap field never holds one.
            elapsed = 0.0
        elif laps_down:
            elapsed = last + LAPPED_PENALTY * laps_down
        elif gap is not None and gap >= last:
            elapsed = gap
        else:
            # No usable gap, or one that contradicts the order. Fall back to a
            # nominal spacing rather than trusting a field that disagrees with
            # the classification.
            elapsed = last + UNKNOWN_GAP_SPACING

        last = elapsed
        entries.append(
            CarEntry(
                driver=car.number,
                tla=car.tla or car.number,
                base_pace=pace.driver_pace.get(car.number, 0.0),
                compound=car.compound,
                tyre_age=car.tyre_age,
                stops=car.pit_count,
                elapsed=elapsed,
            )
        )
    return entries
