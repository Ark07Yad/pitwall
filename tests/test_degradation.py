from __future__ import annotations

import dataclasses

import pytest

from pitwall.models.degradation import (
    DegradationPrior,
    _reliable_age,
    fit_degradation,
)
from pitwall.state.models import Compound


def race(circuit: str, buckets: list[tuple[str, int, int, float]], season: int = 2025) -> dict:
    return {
        "season": season,
        "round": 1,
        "circuit": circuit,
        "buckets": [{"compound": c, "age": a, "n": n, "mean": m} for c, a, n, m in buckets],
    }


def curve(compound: str, linear: float, curvature: float, max_age: int, n: int = 40):
    return [
        (compound, age, n, linear * age + curvature * age * age) for age in range(1, max_age + 1)
    ]


# -- fitting the shape --------------------------------------------------


def test_recovers_a_pooled_shape():
    races = [race("Monza", curve("HAR", 0.04, 0.002, 30)) for _ in range(6)]
    prior = fit_degradation(races)
    assert prior is not None
    assert prior.linear[Compound.HARD] == pytest.approx(0.04, abs=0.01)
    assert prior.curvature[Compound.HARD] == pytest.approx(0.002, abs=0.0008)


def test_curvature_is_never_negative():
    """A tyre that gets faster with age is not a tyre, and extrapolating one
    rewards never stopping."""
    # A concave curve - what survivorship actually produces.
    buckets = [("HAR", age, 40, 0.08 * age - 0.0015 * age * age) for age in range(1, 30)]
    prior = fit_degradation([race("Monza", buckets) for _ in range(5)])
    assert prior.curvature[Compound.HARD] >= 0.0


def test_no_history_returns_none():
    assert fit_degradation([]) is None
    assert fit_degradation([race("Monza", [])]) is None


# -- survivorship -------------------------------------------------------


def test_finds_where_the_curve_turns_over():
    """Degradation is monotone; an observed curve that turns over is measuring
    which stints survived, not what rubber does."""
    rising = [(age, 0.04 * age, 200) for age in range(1, 26)]
    falling = [(age, 1.0 - 0.02 * (age - 25), 200) for age in range(26, 50)]
    assert 20 <= _reliable_age(rising + falling) <= 34


def test_a_monotone_curve_keeps_its_whole_range():
    rows = [(age, 0.04 * age, 200) for age in range(1, 40)]
    assert _reliable_age(rows) >= 34


def test_the_tail_does_not_flatten_the_slope():
    """Fitting through the survivorship plateau is what made the pooled soft
    look like it degraded at a fifth the rate of the hard."""
    honest = curve("HAR", 0.05, 0.0, 25, n=200)
    # A flat, heavily-populated tail of exactly the kind selection produces.
    plateau = [("HAR", age, 200, 1.25 - 0.004 * (age - 25)) for age in range(26, 60)]

    with_tail = fit_degradation([race("Monza", honest + plateau) for _ in range(5)])
    assert with_tail.linear[Compound.HARD] == pytest.approx(0.05, abs=0.012)
    assert with_tail.reliable_max_age[Compound.HARD] < 40
    assert any("survivorship" in w for w in with_tail.warnings)


def test_beyond_the_trusted_age_it_continues_rather_than_flattens():
    """Flattening is the artifact. A straight line is the smallest claim that is
    not knowingly wrong, and it does not promise a tyre that lasts forever."""
    honest = curve("HAR", 0.05, 0.0, 25, n=200)
    plateau = [("HAR", age, 200, 1.25 - 0.004 * (age - 25)) for age in range(26, 60)]
    prior = fit_degradation([race("Monza", honest + plateau) for _ in range(5)])

    at_25 = prior.degradation_at(Compound.HARD, 25)
    at_50 = prior.degradation_at(Compound.HARD, 50)
    # Still climbing well past the plateau, not stuck at its level.
    assert at_50 > at_25 * 1.7
    assert prior.selection_contaminated(Compound.HARD, 50)
    assert not prior.selection_contaminated(Compound.HARD, 10)


# -- circuits -----------------------------------------------------------


def test_circuit_factors_scale_the_shared_shape():
    gentle = [race("Melbourne", curve("HAR", 0.02, 0.0, 30)) for _ in range(6)]
    harsh = [race("Sakhir", curve("HAR", 0.08, 0.0, 30)) for _ in range(6)]
    prior = fit_degradation(gentle + harsh)

    assert prior.circuit_factor["Sakhir"] > prior.circuit_factor["Melbourne"]
    assert prior.degradation_at(Compound.HARD, 20, "Sakhir") > prior.degradation_at(
        Compound.HARD, 20, "Melbourne"
    )


def test_a_thin_circuit_is_shrunk_toward_the_field():
    """One race cannot justify its own tyre-wear multiplier."""
    field = [race("Monza", curve("HAR", 0.04, 0.0, 30)) for _ in range(10)]
    outlier = [race("Oddball", curve("HAR", 0.20, 0.0, 30))]
    prior = fit_degradation(field + outlier, circuit_shrinkage=3.0)

    assert prior.circuit_factor["Oddball"] < 3.0
    assert prior.circuit_factor["Oddball"] > prior.circuit_factor["Monza"]


def test_an_unknown_circuit_is_unscaled():
    prior = fit_degradation([race("Monza", curve("HAR", 0.04, 0.0, 30)) for _ in range(5)])
    assert not prior.known_circuit("Nowhere")
    assert prior.degradation_at(Compound.HARD, 20, "Nowhere") == pytest.approx(
        prior.degradation_at(Compound.HARD, 20), rel=1e-9
    )


def test_live_feed_circuit_names_resolve():
    prior = fit_degradation([race("Budapest", curve("HAR", 0.06, 0.0, 30)) for _ in range(5)])
    assert prior.known_circuit("Hungaroring")


def test_degradation_at_is_zero_for_a_fresh_tyre():
    prior = fit_degradation([race("Monza", curve("HAR", 0.04, 0.001, 30)) for _ in range(5)])
    assert prior.degradation_at(Compound.HARD, 0) == pytest.approx(0.0, abs=1e-9)


def test_prior_is_frozen():
    prior = fit_degradation([race("Monza", curve("HAR", 0.04, 0.0, 30)) for _ in range(5)])
    assert isinstance(prior, DegradationPrior)
    with pytest.raises(dataclasses.FrozenInstanceError):
        prior.linear = {}


def test_a_negative_circuit_scale_is_rejected_not_shrunk():
    """Shrinking a negative scale toward 1.0 launders nonsense into a plausible
    number. Melbourne came out at 0.06x off a raw -0.64, which would have told
    the engine tyres there barely wear."""
    field = [race("Monza", curve("HAR", 0.05, 0.0, 30)) for _ in range(8)]
    # Deltas that fall with age - the decomposition failing, not a gentle track.
    backwards = [
        race("Backwards", [("HAR", age, 60, -0.05 * age) for age in range(1, 31)]) for _ in range(4)
    ]
    prior = fit_degradation(field + backwards)

    assert not prior.known_circuit("Backwards")
    # Falls back to the field average rather than a small positive number.
    assert prior.degradation_at(Compound.HARD, 20, "Backwards") == pytest.approx(
        prior.degradation_at(Compound.HARD, 20), rel=1e-9
    )
    assert any("negative" in w for w in prior.warnings)


# -- contamination ------------------------------------------------------


def races_at(circuit, n, linear=0.04, start_round=1):
    """`n` honest races at one circuit, each a distinct (season, round)."""
    return [
        dict(race(circuit, curve("HAR", linear, 0.0, 30)), season=2020 + i, round=start_round)
        for i in range(n)
    ]


def test_one_broken_race_does_not_move_the_circuit():
    """The bug this replaced: pooling every bucket row at a circuit into one
    least-squares gave a single failed decomposition a vote proportional to its
    lap count. At Zandvoort the 2023 race alone pulled the scale from ~1.0 to
    0.505 - hard 0.92x and medium 1.30x outvoted by a soft at -1.48x."""
    field = [r for c in ("Monza", "Sakhir", "Suzuka", "Austin") for r in races_at(c, 3)]
    # Zandvoort and the control are identical apart from the broken race, so
    # comparing them holds the pooled shape constant - a broken race moves that
    # too, and this test is about the circuit scale.
    honest = races_at("Zandvoort", 4) + races_at("Silverstone", 4)
    broken = dict(race("Zandvoort", curve("HAR", -0.12, 0.0, 30)), season=2019, round=1)

    prior = fit_degradation(field + honest + [broken])
    assert prior.circuit_factor["Zandvoort"] == pytest.approx(
        prior.circuit_factor["Silverstone"], abs=0.05
    )


def test_a_red_flagged_race_is_excluded_and_named():
    history = {
        (2019, 1): {
            "red_starts": [2],
            "sc_laps": [],
            "vsc_laps": [],
            "red_laps": [2],
            "total_laps": 70,
        }
    }
    races = races_at("Monza", 3) + [
        dict(race("Monza", curve("HAR", -0.2, 0.0, 30)), season=2019, round=1)
    ]
    prior = fit_degradation(races, history=history)
    assert prior.n_races == 3
    assert prior.circuit_races["Monza"] == 3
    assert any("red-flagged" in w for w in prior.warnings)


def test_a_wet_race_is_excluded_on_its_own_measurement():
    """No history file needed: the wet share is recorded with the race."""
    races = races_at("Monza", 3)
    races.append(
        dict(race("Monza", curve("HAR", -0.2, 0.0, 30)), season=2019, round=1, wet_share=0.62)
    )
    prior = fit_degradation(races)
    assert prior.n_races == 3
    assert any("62% of laps run on wet tyres" in w for w in prior.warnings)


def test_a_dry_green_race_is_not_excluded():
    """The filter must not quietly eat the ordinary case."""
    races = races_at("Monza", 4)
    for r in races:
        r["wet_share"] = 0.0
    prior = fit_degradation(races, history={})
    assert prior.n_races == 4
    assert not any("excluded" in w for w in prior.warnings)


def test_shrinkage_counts_usable_races_not_collected_ones():
    """A circuit whose races were nearly all thrown out must not keep the
    confidence of the ones it lost."""
    races = races_at("Monza", 4, linear=0.08)
    for r in races[1:]:
        r["wet_share"] = 0.62
    prior = fit_degradation(races)
    assert prior.circuit_races["Monza"] == 1
    # One race against a shrinkage of 3: three quarters of the way back to 1.0.
    assert prior.circuit_factor["Monza"] == pytest.approx(1.0, abs=0.3)


def test_absent_cliff_is_reported_not_printed_as_zero():
    """ "+0.00000" in the table reads as a measured zero rather than the absence
    of a measurement, and PLAN.md 5.2 asks for a cliff."""
    prior = fit_degradation([race("Monza", curve("HAR", 0.04, 0.0, 30)) for _ in range(5)])
    assert prior.curvature[Compound.HARD] == 0.0
    assert any("no cliff term is identified" in w for w in prior.warnings)
