from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from pitwall.models.pace import PaceFit
from pitwall.models.safety_car import BUCKETS, EventKind, HazardModel
from pitwall.sim import CarEntry, SimConfig, evaluate_actions, simulate, undercut_threats
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
