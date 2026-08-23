from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from pitwall.models.attrition import AttritionModel
from pitwall.models.pace import PaceFit
from pitwall.models.safety_car import BUCKETS, EventKind, HazardModel
from pitwall.sim import (
    CarEntry,
    SimConfig,
    entries_from_state,
    evaluate_actions,
    simulate,
    undercut_threats,
)
from pitwall.state.models import Compound


def pace_fit(
    *,
    race_lap_coef: float = -0.05,
    degradation: dict[Compound, float] | None = None,
    offsets: dict[Compound, float] | None = None,
) -> PaceFit:
    return PaceFit(
        race_lap_coef=race_lap_coef,
        degradation=degradation
        or {Compound.SOFT: 0.12, Compound.MEDIUM: 0.08, Compound.HARD: 0.05},
        compound_offset=offsets or {Compound.SOFT: -0.6, Compound.MEDIUM: -0.3, Compound.HARD: 0.0},
        reference_compound=Compound.HARD,
        compound_phase={},
        driver_pace={},
        n_laps=500,
        n_stints=20,
        residual_std=0.7,
        r_squared=0.8,
    )


def hazard_model(rate: float) -> HazardModel:
    return HazardModel(
        kind=EventKind.SAFETY_CAR,
        baseline=dict.fromkeys(BUCKETS, rate),
        circuit_factor={"Test": 1.0},
        circuit_races={"Test": 5},
        n_races=5,
        n_events=5,
    )


def grid(n: int = 6, *, spread: float = 0.25, gap: float = 2.0) -> list[CarEntry]:
    """A field of n cars, each marginally slower and `gap` seconds behind."""
    return [
        CarEntry(
            driver=str(i),
            tla=f"C{i}",
            base_pace=90.0 + i * spread,
            compound=Compound.MEDIUM,
            tyre_age=10,
            elapsed=i * gap,
        )
        for i in range(n)
    ]


def run(entries, **kwargs):
    defaults = dict(
        from_lap=1,
        total_laps=30,
        circuit="Test",
        pace=pace_fit(),
        config=SimConfig(n_sims=400, seed=1),
    )
    defaults.update(kwargs)
    return simulate(entries, **defaults)


# -- basic correctness -------------------------------------------------


def test_positions_are_a_permutation():
    """Every simulation must classify each car exactly once."""
    result = run(grid(6))
    for row in result.positions:
        assert sorted(row) == list(range(1, 7))


def test_shape_matches_config():
    result = run(grid(5), config=SimConfig(n_sims=123, seed=1))
    assert result.positions.shape == (123, 5)


def test_same_seed_reproduces():
    a = run(grid(6))
    b = run(grid(6))
    assert np.array_equal(a.positions, b.positions)


def test_different_seed_diverges():
    a = run(grid(6), config=SimConfig(n_sims=400, seed=1))
    b = run(grid(6), config=SimConfig(n_sims=400, seed=2))
    assert not np.array_equal(a.positions, b.positions)


def test_empty_grid_rejected():
    with pytest.raises(ValueError, match="no cars"):
        run([])


def test_start_after_the_end_rejected():
    with pytest.raises(ValueError, match="past the end"):
        run(grid(4), from_lap=40, total_laps=30)


# -- racing behaviour --------------------------------------------------


def test_the_faster_car_usually_wins():
    result = run(grid(6))
    assert result.mean_position("0") < result.mean_position("5")


def test_a_big_pace_advantage_is_decisive():
    result = run(grid(6, spread=1.5))
    assert result.probability_top("0", 1) > 0.9


def test_starting_ahead_is_worth_something():
    """Two identical cars: the one starting ahead should finish ahead more often.

    This is the property that makes track position - and therefore pit strategy -
    mean anything at all."""
    entries = grid(2, spread=0.0, gap=3.0)
    result = run(entries)
    assert result.probability_ahead_of("0", "1") > 0.5


def test_track_position_holds_a_faster_car_up():
    """A quicker car stuck behind a slower one must not pass straight through.

    With overtaking switched off it should stay behind almost always; with it on
    it should get through more often. If those two are the same number, the
    track-position constraint is not doing anything."""
    entries = [
        CarEntry(driver="slow", tla="SLO", base_pace=91.0, tyre_age=10, elapsed=0.0),
        CarEntry(driver="fast", tla="FST", base_pace=89.5, tyre_age=10, elapsed=0.5),
    ]
    blocked = run(
        entries, config=SimConfig(n_sims=400, seed=3, overtake_base=0.0, overtake_per_second=0.0)
    )
    open_track = run(
        entries, config=SimConfig(n_sims=400, seed=3, overtake_base=0.9, overtake_per_second=0.0)
    )

    assert open_track.probability_ahead_of("fast", "slow") > blocked.probability_ahead_of(
        "fast", "slow"
    )


def test_degradation_punishes_old_tyres():
    """Same car, older rubber, worse result."""
    entries = [
        CarEntry(driver="fresh", tla="FRS", base_pace=90.0, tyre_age=1, elapsed=0.0),
        CarEntry(driver="worn", tla="WRN", base_pace=90.0, tyre_age=30, elapsed=0.0),
    ]
    result = run(entries)
    assert result.mean_position("fresh") < result.mean_position("worn")


# -- pit stops ---------------------------------------------------------


def test_pitting_costs_time_when_there_is_nothing_to_gain():
    """A stop must hurt when fresh tyres buy nothing.

    Degradation is set to ~0 deliberately. At a realistic 0.08 s/lap over 30
    laps a stop genuinely pays for itself - fresh rubber is worth more than the
    twenty seconds it costs - so a naive "pitting is always slower" assertion
    fails against a *correct* simulator. Removing degradation isolates the cost.
    """
    flat = pace_fit(
        degradation=dict.fromkeys(Compound, 0.0),
        offsets=dict.fromkeys(Compound, 0.0),
    )
    entries = grid(2, spread=0.0, gap=0.0)
    stopping = [replace(entries[0], planned_pit=10), entries[1]]
    result = run(stopping, pace=flat, config=SimConfig(n_sims=400, seed=4, min_gap=0.0))
    assert result.probability_ahead_of("1", "0") > 0.9


def test_a_stop_pays_for_itself_when_degradation_is_high():
    """The converse, and the reason teams stop at all: on a punishing tyre the
    same twenty seconds is worth paying."""
    steep = pace_fit(
        degradation=dict.fromkeys(Compound, 0.30),
        offsets=dict.fromkeys(Compound, 0.0),
    )
    entries = grid(2, spread=0.0, gap=0.0)
    entries = [replace(e, tyre_age=25) for e in entries]
    stopping = [replace(entries[0], planned_pit=10), entries[1]]
    result = run(stopping, pace=steep, config=SimConfig(n_sims=400, seed=4, min_gap=0.0))
    assert result.probability_ahead_of("0", "1") > 0.9


def test_the_undercut_works():
    """The core strategic mechanic: stopping first, from close behind, on a
    heavily degraded tyre, should gain the position more often than not.

    If this fails the simulator cannot represent pit strategy at all."""
    pace = pace_fit(degradation={c: 0.30 for c in Compound}, offsets=dict.fromkeys(Compound, 0.0))
    entries = [
        CarEntry(
            driver="ahead",
            tla="AHD",
            base_pace=90.0,
            tyre_age=25,
            elapsed=0.0,
            planned_pit=20,
            planned_compound=Compound.HARD,
        ),
        CarEntry(
            driver="behind",
            tla="BHD",
            base_pace=90.0,
            tyre_age=25,
            elapsed=1.5,
            planned_pit=12,
            planned_compound=Compound.HARD,
        ),
    ]
    result = run(
        entries,
        pace=pace,
        from_lap=10,
        total_laps=40,
        config=SimConfig(n_sims=600, seed=5, rival_pit_jitter=0),
    )

    assert result.probability_ahead_of("behind", "ahead") > 0.5


# -- safety cars -------------------------------------------------------


def test_no_hazard_means_no_safety_cars():
    result = run(grid(4), hazard=None)
    assert result.sc_deployed.sum() == 0


def test_higher_hazard_produces_more_safety_cars():
    low = run(grid(4), hazard=hazard_model(0.01))
    high = run(grid(4), hazard=hazard_model(0.15))
    assert high.sc_deployed.mean() > low.sc_deployed.mean()


def test_safety_cars_compress_the_field():
    """A safety car bunches the pack, so a large lead should survive far less
    often than it would under green. This is why safety cars dominate strategy."""
    entries = [
        CarEntry(driver="leader", tla="LDR", base_pace=90.0, tyre_age=10, elapsed=0.0),
        CarEntry(driver="chaser", tla="CHS", base_pace=90.0, tyre_age=10, elapsed=25.0),
    ]
    calm = run(entries, hazard=None, config=SimConfig(n_sims=500, seed=6))
    chaotic = run(entries, hazard=hazard_model(0.20), config=SimConfig(n_sims=500, seed=6))

    assert calm.probability_ahead_of("leader", "chaser") > chaotic.probability_ahead_of(
        "leader", "chaser"
    )


def test_stopping_under_a_safety_car_is_cheaper():
    """The discount is the whole reason teams scramble to pit under one."""
    entries = [
        CarEntry(
            driver="stopper", tla="STP", base_pace=90.0, tyre_age=10, elapsed=0.0, planned_pit=5
        ),
        CarEntry(driver="stayer", tla="STY", base_pace=90.0, tyre_age=10, elapsed=0.0),
    ]
    green = run(entries, hazard=None, config=SimConfig(n_sims=500, seed=7, min_gap=0.0))
    neutralised = run(
        entries,
        hazard=hazard_model(0.9),
        config=SimConfig(n_sims=500, seed=7, min_gap=0.0, sc_pit_discount=0.1),
    )

    assert neutralised.probability_ahead_of("stopper", "stayer") > green.probability_ahead_of(
        "stopper", "stayer"
    )


# -- decision layer ----------------------------------------------------


def test_recommendation_ranks_every_option():
    entries = grid(6)
    rec = evaluate_actions(
        entries,
        our_driver="2",
        from_lap=10,
        total_laps=40,
        circuit="Test",
        pace=pace_fit(),
        compounds=(Compound.SOFT, Compound.HARD),
        delays=(0, 5),
        config=SimConfig(n_sims=200, seed=8),
    )
    assert len(rec.outcomes) == 4
    means = [o.mean_position for o in rec.outcomes]
    assert means == sorted(means), "outcomes must be ranked best first"
    assert rec.best is rec.outcomes[0]


def test_recommendation_knows_our_position():
    rec = evaluate_actions(
        grid(6),
        our_driver="3",
        from_lap=10,
        total_laps=40,
        circuit="Test",
        pace=pace_fit(),
        delays=(0,),
        compounds=(Compound.HARD,),
        config=SimConfig(n_sims=200, seed=8),
    )
    assert rec.current_position == 4


def test_unknown_driver_rejected():
    with pytest.raises(ValueError, match="not in the entry list"):
        evaluate_actions(
            grid(4),
            our_driver="nobody",
            from_lap=1,
            total_laps=20,
            circuit="Test",
            pace=pace_fit(),
            config=SimConfig(n_sims=50, seed=9),
        )


def test_margin_and_decisiveness():
    rec = evaluate_actions(
        grid(6),
        our_driver="2",
        from_lap=5,
        total_laps=40,
        circuit="Test",
        pace=pace_fit(),
        compounds=(Compound.SOFT, Compound.HARD),
        delays=(0, 20),
        config=SimConfig(n_sims=400, seed=10),
    )
    assert rec.margin >= 0.0
    assert rec.decisive == (rec.margin >= 0.15)
    assert str(rec)


def test_threats_only_look_behind_and_within_the_window():
    entries = grid(6, gap=2.0)
    threats = undercut_threats(
        entries,
        our_driver="2",
        from_lap=10,
        total_laps=40,
        circuit="Test",
        pace=pace_fit(),
        window=3.0,
        config=SimConfig(n_sims=200, seed=11),
    )
    # Cars 3 (+2s) is inside the window; 4 (+4s) and 5 (+6s) are not, and
    # 0/1 are ahead of us rather than behind.
    assert [t.rival for t in threats] == ["3"]
    assert 0 < threats[0].probability < 1


# -- building a grid from live state -----------------------------------


class _Car:
    def __init__(self, number, tla, position, gap, compound=Compound.MEDIUM, age=10, stops=1):
        self.number, self.tla, self.position = number, tla, position
        self.gap_to_leader, self.compound, self.tyre_age, self.pit_count = gap, compound, age, stops


class _State:
    def __init__(self, cars):
        self._cars = cars

    def running_order(self):
        return self._cars


def test_leader_is_placed_at_the_front_not_the_back():
    """Regression, and a severe one. `GapToLeader` is not reliably a gap: the
    leader's carries "LAP 17" - the lap it is on. An earlier version parsed that,
    got nothing, and dropped the car to the back of the grid, so every simulation
    started with the race leader 112 seconds behind the field. The engine then
    correctly reported that a car running last would not finish on the podium."""
    state = _State(
        [
            _Car("1", "NOR", 1, "LAP 17"),
            _Car("81", "PIA", 2, None),
            _Car("16", "LEC", 3, "+7.386"),
        ]
    )
    entries = entries_from_state(state, pace_fit())

    assert [e.tla for e in entries] == ["NOR", "PIA", "LEC"]
    assert entries[0].elapsed == 0.0, "the leader defines the reference"
    assert entries[0].elapsed < entries[1].elapsed < entries[2].elapsed


def test_elapsed_never_contradicts_the_running_order():
    """A car classified P4 must never be simulated ahead of P3, whatever the
    gap field says."""
    state = _State(
        [
            _Car("1", "A", 1, ""),
            _Car("2", "B", 2, "+5.0"),
            _Car("3", "C", 3, "+2.0"),  # inconsistent with the order
            _Car("4", "D", 4, "+9.0"),
        ]
    )
    elapsed = [e.elapsed for e in entries_from_state(state, pace_fit())]
    assert elapsed == sorted(elapsed)


def test_lapped_cars_are_placed_well_behind():
    state = _State([_Car("1", "A", 1, ""), _Car("2", "B", 2, "+3.0"), _Car("3", "C", 3, "2L")])
    entries = entries_from_state(state, pace_fit())
    assert entries[2].elapsed > entries[1].elapsed + 30


def test_gaps_are_used_when_they_are_sane():
    state = _State([_Car("1", "A", 1, ""), _Car("2", "B", 2, "+7.386")])
    entries = entries_from_state(state, pace_fit())
    assert entries[1].elapsed == pytest.approx(7.386)


# -- attrition ---------------------------------------------------------
#
# Roughly one car in ten does not finish. A simulation where everyone reaches
# the flag is wrong in a one-sided way: it can never promote anyone, so it
# systematically understates the chances of cars further back.


def attrition_model(hazard: float) -> AttritionModel:
    return AttritionModel(
        baseline=dict.fromkeys(BUCKETS, hazard),
        circuit_factor={"Test": 1.0},
        circuit_races={"Test": 5},
        n_races=5,
        n_starters=100,
        n_retirements=10,
    )


def test_nobody_retires_without_a_model():
    result = run(grid(6))
    assert result.retired is not None
    assert not result.retired.any()


def test_cars_retire_when_the_model_says_so():
    result = run(grid(6), attrition=attrition_model(0.02))
    assert result.retired.any()
    assert 0.0 < result.probability_retired("0") < 1.0


def test_more_hazard_means_more_retirements():
    low = run(grid(6), attrition=attrition_model(0.002))
    high = run(grid(6), attrition=attrition_model(0.05))
    assert high.retired.sum() > low.retired.sum()


def test_retired_cars_classify_behind_finishers():
    """A car that stops is out of the results, not merely slow.

    Isolated to runs where the *other* car actually finished. When both retire
    the quick one may legitimately classify ahead - retirements are ordered by
    distance covered - so asserting over every run it retired in tests the
    wrong thing.
    """
    entries = [
        CarEntry(driver="quick", tla="QCK", base_pace=88.0, tyre_age=10, elapsed=0.0),
        CarEntry(driver="slow", tla="SLO", base_pace=95.0, tyre_age=10, elapsed=60.0),
    ]
    result = run(entries, attrition=attrition_model(0.06), config=SimConfig(n_sims=600, seed=12))

    quick, slow = result.index_of("quick"), result.index_of("slow")
    only_quick_stopped = result.retired[:, quick] & ~result.retired[:, slow]

    assert only_quick_stopped.any(), "expected some runs where only the quick car retired"
    assert (result.positions[only_quick_stopped, quick] == 2).all(), (
        "a retirement must classify behind a car that finished, however slow"
    )


def test_a_later_retirement_classifies_ahead_of_an_earlier_one():
    """F1 classifies retirements by distance covered, so lasting longer counts."""
    entries = grid(2, spread=0.0, gap=0.0)
    result = run(
        entries,
        attrition=attrition_model(0.15),
        config=SimConfig(n_sims=800, seed=13, min_gap=0.0),
    )
    both = result.retired.all(axis=1)
    assert both.any(), "expected some runs where both cars retired"
    # Neither ordering should be impossible: whoever got further classifies ahead,
    # and which car that is varies run to run.
    winners = set(result.positions[both, 0].tolist())
    assert winners <= {1, 2} and len(winners) == 2


def test_a_retired_car_stops_accumulating_time():
    """Parked cars do not keep lapping, and must not keep holding others up."""
    entries = grid(3, spread=0.0, gap=1.0)
    result = run(entries, attrition=attrition_model(0.08), config=SimConfig(n_sims=400, seed=14))
    for row in result.positions:
        assert sorted(row) == [1, 2, 3], "classification must stay a permutation"


def test_attrition_promotes_the_cars_behind():
    """The whole point: when cars ahead fail, someone further back gains.

    Without this the simulation treats promotion as impossible rather than as a
    one-in-ten event repeated across everyone ahead."""
    entries = grid(8, spread=0.4)
    without = run(entries, config=SimConfig(n_sims=1500, seed=15))
    with_dnf = run(entries, attrition=attrition_model(0.03), config=SimConfig(n_sims=1500, seed=15))

    # A car starting sixth has a better shot at the podium when the field can break.
    assert with_dnf.probability_top("5", 3) > without.probability_top("5", 3)


def test_a_safety_car_lowers_retirement_risk():
    """Cars are least likely to be lost while crawling in single file."""
    entries = grid(4)
    calm = run(
        entries,
        attrition=attrition_model(0.03),
        hazard=None,
        config=SimConfig(n_sims=800, seed=16),
    )
    neutralised = run(
        entries,
        attrition=attrition_model(0.03),
        hazard=hazard_model(0.5),
        config=SimConfig(n_sims=800, seed=16, sc_attrition_factor=0.0),
    )
    assert neutralised.retired.sum() < calm.retired.sum()


def test_finished_and_retired_probabilities_are_complementary():
    result = run(grid(4), attrition=attrition_model(0.02))
    for entry in grid(4):
        p = result.probability_retired(entry.driver)
        assert result.probability_finished(entry.driver) == pytest.approx(1 - p)


# -- per-circuit pit loss ----------------------------------------------
#
# Pit loss was a flat 20.0 s everywhere until the calendar was measured and the
# real spread turned out to be about nine seconds, Spa to Marina Bay. Since the
# simulation's whole job is weighing time lost in the pits against time gained
# on fresher tyres, that constant is load-bearing for every call.

from pitwall.models.pit_loss import PitLossModel  # noqa: E402


def pit_loss_model(botch_rate: float = 0.0, botch_scale: float = 3.8, **circuits: float):
    """A fitted model over the named circuits. The tail is off by default so a
    test that is not about the tail is not perturbed by it."""
    return PitLossModel(
        botch_rate=botch_rate,
        botch_scale=botch_scale,
        baseline=22.0,
        circuit_loss=dict(circuits),
        circuit_raw=dict(circuits),
        circuit_spread={c: 1.5 for c in circuits},
        circuit_races={c: 4 for c in circuits},
        circuit_stops={c: 80 for c in circuits},
        spread=1.5,
        n_races=len(circuits) * 4,
        n_stops=len(circuits) * 80,
    )


def two_cars() -> list[CarEntry]:
    return [
        CarEntry(driver="a", tla="AAA", base_pace=90.0, tyre_age=20, elapsed=0.0),
        CarEntry(driver="b", tla="BBB", base_pace=90.0, tyre_age=20, elapsed=30.0),
    ]


def test_an_expensive_pit_lane_makes_stopping_worse():
    """The same race at Monza and at Spa should not produce the same call."""
    cheap = evaluate_actions(
        two_cars(),
        our_driver="a",
        from_lap=20,
        total_laps=50,
        circuit="Spa-Francorchamps",
        pace=pace_fit(),
        pit_loss=pit_loss_model(**{"Spa-Francorchamps": 18.4}),
        config=SimConfig(n_sims=400, seed=3),
    )
    dear = evaluate_actions(
        two_cars(),
        our_driver="a",
        from_lap=20,
        total_laps=50,
        circuit="Lusail",
        pace=pace_fit(),
        pit_loss=pit_loss_model(Lusail=27.8),
        config=SimConfig(n_sims=400, seed=3),
    )
    # Identical everything except the cost of the stop, so any difference in the
    # expected finish is that cost propagating through.
    assert dear.best.mean_position >= cheap.best.mean_position


def contested_field() -> list[CarEntry]:
    """Three cars close enough that a few seconds in the pits changes the order.

    A field spread by more than a pit stop cannot show a pit-loss effect at all -
    the leader wins every simulation whatever a stop costs, and the expected
    position saturates at 1.0. Any assertion about pit loss has to be made where
    track position is actually contested.
    """
    return [
        CarEntry(driver="a", tla="AAA", base_pace=90.0, tyre_age=22, elapsed=0.0),
        CarEntry(driver="b", tla="BBB", base_pace=90.1, tyre_age=8, elapsed=2.0),
        CarEntry(driver="c", tla="CCC", base_pace=90.2, tyre_age=8, elapsed=5.0),
    ]


def test_the_model_overrides_the_flat_config_constant():
    kwargs = dict(
        our_driver="a",
        from_lap=20,
        total_laps=50,
        circuit="Monza",
        pace=pace_fit(),
        config=SimConfig(n_sims=1500, seed=11),
    )
    flat = evaluate_actions(contested_field(), **kwargs)
    fitted = evaluate_actions(contested_field(), pit_loss=pit_loss_model(Monza=32.0), **kwargs)
    # A 32s pit lane against the config's 20s must make stopping visibly worse.
    assert fitted.best.mean_position > flat.best.mean_position


def test_the_botched_stop_tail_makes_stopping_dearer():
    """Same median cost, different shape: the tail adds expected loss."""
    kwargs = dict(
        our_driver="a",
        from_lap=20,
        total_laps=50,
        circuit="Monza",
        pace=pace_fit(),
        config=SimConfig(n_sims=3000, seed=5),
    )
    symmetric = evaluate_actions(
        contested_field(),
        pit_loss=pit_loss_model(Monza=25.0, botch_rate=0.0),
        **kwargs,
    )
    tailed = evaluate_actions(
        contested_field(),
        pit_loss=pit_loss_model(Monza=25.0, botch_rate=0.12, botch_scale=5.0),
        **kwargs,
    )
    assert tailed.best.mean_position >= symmetric.best.mean_position


def test_an_unknown_circuit_uses_the_field_median_not_zero():
    """A circuit missing from the fit must never make stopping free."""
    model = pit_loss_model(Monza=25.0)
    assert model.loss("Nowhere") == pytest.approx(22.0)

    result = simulate(
        two_cars(),
        from_lap=20,
        total_laps=50,
        circuit="Nowhere",
        pace=pace_fit(),
        pit_loss=model,
        config=SimConfig(n_sims=200, seed=5),
    )
    assert result is not None


def test_no_model_falls_back_to_the_config_value():
    """Absent history degrades to the old behaviour, not to a broken one."""
    cfg = SimConfig(n_sims=300, seed=7, pit_loss=25.0)
    with_none = evaluate_actions(
        two_cars(),
        our_driver="a",
        from_lap=20,
        total_laps=50,
        circuit="Anywhere",
        pace=pace_fit(),
        pit_loss=None,
        config=cfg,
    )
    explicit = evaluate_actions(
        two_cars(),
        our_driver="a",
        from_lap=20,
        total_laps=50,
        circuit="Anywhere",
        pace=pace_fit(),
        pit_loss=pit_loss_model(Anywhere=25.0),
        config=cfg,
    )
    assert with_none.best.mean_position == pytest.approx(explicit.best.mean_position, abs=0.25)


# -- the stay-out option ------------------------------------------------
#
# Framing every option as (delay, compound) meant the engine could only ever say
# "pit". Late in a race every delay clamps at the flag, so all twelve options
# collapse onto the same lap and it recommends a stop nobody would make. At the
# 2026 Dutch GP it advised pitting the leader on lap 71 of 72 and put his
# expected finish at P4.90; he won.


def test_a_car_that_has_stopped_may_run_to_the_flag():
    entries = contested_field()
    entries[0] = replace(entries[0], stops=1)
    rec = evaluate_actions(
        entries,
        our_driver="a",
        from_lap=45,
        total_laps=50,
        circuit="Zandvoort",
        pace=pace_fit(),
        config=SimConfig(n_sims=800, seed=3),
    )
    labels = [o.label for o in rec.outcomes]
    assert "stay out" in labels
    assert sum(1 for o in rec.outcomes if not o.stop) == 1


def test_no_stay_out_before_the_mandatory_stop():
    """Offering an option the car is not allowed to take is worse than not
    modelling it: a dry race requires two compounds, so a car yet to stop cannot
    run to the flag."""
    entries = contested_field()
    entries[0] = replace(entries[0], stops=0)
    rec = evaluate_actions(
        entries,
        our_driver="a",
        from_lap=20,
        total_laps=50,
        circuit="Zandvoort",
        pace=pace_fit(),
        config=SimConfig(n_sims=400, seed=3),
    )
    assert all(o.stop for o in rec.outcomes)
    assert "stay out" not in [o.label for o in rec.outcomes]


def test_late_in_a_race_a_leader_is_told_to_stay_out():
    """The regression this exists for. On the penultimate lap, a car leading on
    a serviceable tyre should not be sent to the pits."""
    entries = [
        CarEntry(driver="a", tla="AAA", base_pace=90.0, tyre_age=20, elapsed=0.0, stops=2),
        CarEntry(driver="b", tla="BBB", base_pace=90.2, tyre_age=18, elapsed=12.0, stops=2),
        CarEntry(driver="c", tla="CCC", base_pace=90.3, tyre_age=18, elapsed=25.0, stops=2),
    ]
    rec = evaluate_actions(
        entries,
        our_driver="a",
        from_lap=71,
        total_laps=72,
        circuit="Zandvoort",
        pace=pace_fit(),
        config=SimConfig(n_sims=1200, seed=9),
    )
    assert not rec.best.stop, f"recommended {rec.best.label} on the penultimate lap"
    # And it should expect to hold the lead, not finish mid-pack.
    assert rec.best.mean_position < 1.5


def test_staying_out_loses_to_stopping_on_dead_tyres():
    """The option must be evaluated, not preferred. A car far from the flag on a
    worn tyre should still be told to pit."""
    entries = [
        CarEntry(driver="a", tla="AAA", base_pace=90.0, tyre_age=40, elapsed=0.0, stops=1),
        CarEntry(driver="b", tla="BBB", base_pace=90.0, tyre_age=5, elapsed=8.0, stops=1),
    ]
    rec = evaluate_actions(
        entries,
        our_driver="a",
        from_lap=20,
        total_laps=60,
        circuit="Zandvoort",
        pace=pace_fit(degradation={Compound.SOFT: 0.3, Compound.MEDIUM: 0.25, Compound.HARD: 0.2}),
        config=SimConfig(n_sims=1200, seed=4),
    )
    assert rec.best.stop, "40 laps of tyre with 40 to run should still be a stop"
