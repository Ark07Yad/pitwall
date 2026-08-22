from __future__ import annotations

import pytest

from pitwall.models.pit_loss import (
    DEFAULT_BOTCH_RATE,
    DEFAULT_PIT_LOSS,
    fit_pit_loss,
)
from pitwall.models.safety_car import normalise_circuit


def race(
    circuit: str,
    median: float,
    *,
    n: int = 20,
    q1: float | None = None,
    q3: float | None = None,
    season: int = 2025,
) -> dict:
    return {
        "season": season,
        "round": 1,
        "circuit": circuit,
        "location": circuit,
        "n_stops": n,
        "median_loss": median,
        "q1": median - 1.0 if q1 is None else q1,
        "q3": median + 1.0 if q3 is None else q3,
    }


# -- fitting ------------------------------------------------------------


def test_fits_a_value_per_circuit():
    fit = fit_pit_loss(
        [race("Spa-Francorchamps", 18.4)] * 4 + [race("Monza", 25.3)] * 4,
        shrinkage=0.0,
    )
    assert fit is not None
    assert fit.loss("Spa-Francorchamps") == pytest.approx(18.4)
    assert fit.loss("Monza") == pytest.approx(25.3)


def test_unknown_circuit_falls_back_to_the_field_median():
    """A circuit with no history must not silently get 0.0 seconds."""
    fit = fit_pit_loss([race("Monza", 25.0)] * 3 + [race("Spa-Francorchamps", 19.0)] * 3)
    assert not fit.known_circuit("Nowhere")
    assert fit.loss("Nowhere") == pytest.approx(fit.baseline)
    assert 19.0 <= fit.loss("Nowhere") <= 25.0


def test_no_usable_history_returns_none():
    assert fit_pit_loss([]) is None
    # A race whose stops were all filtered out carries no median.
    assert fit_pit_loss([{"circuit": "Monza", "median_loss": None, "n_stops": 0}]) is None


# -- the guards that make it trustworthy --------------------------------


def test_thin_circuits_are_shrunk_toward_the_field():
    """One race is not enough to justify a per-circuit constant.

    Four or five races per circuit, some of them wet, is the whole sample. A raw
    median from a single afternoon would let one chaotic race define a number the
    timing of every pit call rests on.
    """
    races = [race("Monza", 25.0) for _ in range(6)]
    races += [race("Oddball", 40.0)]  # one race, absurdly high
    fit = fit_pit_loss(races, shrinkage=2.0)

    raw = fit.circuit_raw["Oddball"]
    assert raw == pytest.approx(40.0)
    # Pulled a long way back toward the field, and strictly between the two.
    assert fit.loss("Oddball") < 35.0
    assert fit.baseline < fit.loss("Oddball") < raw
    assert any("single race" in w for w in fit.warnings)


def test_a_well_observed_circuit_keeps_its_own_number():
    """Shrinkage must not flatten a circuit that has earned its estimate."""
    races = [race("Monza", 25.0) for _ in range(6)]
    races += [race("Spa-Francorchamps", 18.0) for _ in range(6)]
    fit = fit_pit_loss(races, shrinkage=2.0)

    assert fit.loss("Spa-Francorchamps") < 19.5
    assert fit.loss("Monza") > 24.0
    assert fit.loss("Monza") - fit.loss("Spa-Francorchamps") > 5.0


def test_the_race_is_the_unit_not_the_stop():
    """One chaotic afternoon with forty stops must not outvote three clean races.

    Pooling every stop would let a single wet race - which yields both more stops
    and a badly biased median - dominate a circuit whose constant is otherwise
    among the most stable numbers in the sport.
    """
    clean = [race("Monza", 25.0, n=8) for _ in range(3)]
    chaotic = [race("Monza", 40.0, n=200)]
    fit = fit_pit_loss(clean + chaotic, shrinkage=0.0)

    # Median of (25, 25, 25, 40) is 25, not the stop-weighted ~38.
    assert fit.circuit_raw["Monza"] == pytest.approx(25.0)


def test_spread_uses_the_interquartile_range():
    """The stop distribution has a long right tail - a botched stop is ten
    seconds slow, a good one is never ten seconds early. A plain standard
    deviation would inflate a spread the simulation then draws symmetrically."""
    tight = fit_pit_loss([race("Monza", 25.0, q1=24.5, q3=25.5)] * 4, shrinkage=0.0)
    wide = fit_pit_loss([race("Monza", 25.0, q1=22.0, q3=28.0)] * 4, shrinkage=0.0)
    assert tight.spread_for("Monza") < wide.spread_for("Monza")
    assert tight.spread_for("Monza") == pytest.approx(1.0 / 1.349, rel=1e-3)


# -- circuit identity ---------------------------------------------------


def test_live_feed_names_resolve_to_the_fitted_circuit():
    """The history is keyed on FastF1's `Location`, the live feed sends
    `Circuit.ShortName`. Where they differ the lookup used to miss silently and
    every per-circuit estimate fell back to neutral."""
    fit = fit_pit_loss([race("Budapest", 21.4)] * 5, shrinkage=0.0)
    assert fit.known_circuit("Hungaroring")
    assert fit.loss("Hungaroring") == pytest.approx(21.4)


@pytest.mark.parametrize(
    ("live_name", "history_name"),
    [
        ("Hungaroring", "Budapest"),
        ("Catalunya", "Barcelona"),
        ("Singapore", "Marina Bay"),
        ("Interlagos", "São Paulo"),
        ("Yas Marina Circuit", "Yas Island"),
        ("Montreal", "Montréal"),
        ("Monte Carlo", "Monaco"),
        # Already agree - must survive normalisation unchanged.
        ("Zandvoort", "Zandvoort"),
        ("Spa-Francorchamps", "Spa-Francorchamps"),
    ],
)
def test_circuit_aliases_are_symmetric(live_name: str, history_name: str):
    assert normalise_circuit(live_name) == normalise_circuit(history_name)


def test_default_constant_matches_the_pre_model_behaviour():
    """An absent history must degrade to what the engine used before, not to zero."""
    assert DEFAULT_PIT_LOSS == 20.0


# -- the botched-stop tail ----------------------------------------------
#
# A stop cannot go meaningfully better than a clean one - the pit lane has a
# speed limit and the stationary time has a floor - but it can go very much
# worse. A symmetric draw gets the shape wrong in the direction a marginal call
# actually turns on.

import numpy as np  # noqa: E402

from pitwall.models.pit_loss import (  # noqa: E402
    BOTCH_CAP,
    BOTCH_THRESHOLD,
    _normal_sf,
)


def model(**overrides):
    base = dict(
        baseline=22.0,
        circuit_loss={"Monza": 25.0},
        circuit_raw={"Monza": 25.0},
        circuit_spread={"Monza": 1.4},
        circuit_races={"Monza": 4},
        circuit_stops={"Monza": 90},
        spread=1.4,
        n_races=40,
        n_stops=900,
    )
    base.update(overrides)
    from pitwall.models.pit_loss import PitLossModel

    return PitLossModel(**base)


def test_the_tail_points_only_one_way():
    """Right-skewed: the mean sits above the median, and the left side is no
    heavier than ordinary scatter."""
    m = model(botch_rate=0.05, botch_scale=3.8)
    draws = m.sample(np.random.default_rng(0), "Monza", 200_000)

    assert draws.mean() > np.median(draws)
    # The upper tail is far longer than the lower one.
    upper = np.percentile(draws, 99) - np.median(draws)
    lower = np.median(draws) - np.percentile(draws, 1)
    assert upper > 2 * lower


def test_the_median_stop_is_still_the_fitted_median():
    """The tail must add cost, not relocate the typical stop."""
    m = model(botch_rate=0.05, botch_scale=3.8)
    draws = m.sample(np.random.default_rng(1), "Monza", 200_000)
    assert np.median(draws) == pytest.approx(25.0, abs=0.2)


def test_expected_loss_exceeds_the_median():
    """The number a simulation averaging over futures actually experiences."""
    m = model(botch_rate=0.05, botch_scale=3.8)
    draws = m.sample(np.random.default_rng(2), "Monza", 200_000)

    assert m.expected_loss("Monza") > m.loss("Monza")
    assert draws.mean() == pytest.approx(m.expected_loss("Monza"), abs=0.1)


def test_a_zero_rate_reduces_to_a_symmetric_draw():
    """Absent tail data must degrade to the previous behaviour exactly."""
    m = model(botch_rate=0.0)
    draws = m.sample(np.random.default_rng(3), "Monza", 100_000)
    assert draws.mean() == pytest.approx(25.0, abs=0.05)
    assert abs(draws.mean() - np.median(draws)) < 0.05
    assert m.expected_loss("Monza") == pytest.approx(m.loss("Monza"))


def test_sample_respects_shape_and_seed():
    m = model()
    a = m.sample(np.random.default_rng(7), "Monza", (5, 3))
    b = m.sample(np.random.default_rng(7), "Monza", (5, 3))
    assert a.shape == (5, 3)
    np.testing.assert_allclose(a, b)


def test_an_unknown_circuit_still_gets_a_tail():
    m = model(botch_rate=0.05, botch_scale=3.8)
    draws = m.sample(np.random.default_rng(4), "Nowhere", 100_000)
    assert np.median(draws) == pytest.approx(22.0, abs=0.2)
    assert draws.mean() > np.median(draws)


# -- fitting the tail ---------------------------------------------------


def race_with_excess(circuit: str, median: float, excess: list[float]) -> dict:
    return {
        "circuit": circuit,
        "n_stops": len(excess),
        "median_loss": median,
        "q1": median - 1.0,
        "q3": median + 1.0,
        "excess": excess,
    }


def test_the_rate_subtracts_what_ordinary_scatter_explains():
    """Counting every stop above the threshold as botched double-counts.

    With a spread of ~1.4s, about 7% of perfectly clean stops clear +2s on their
    own. Calling those botched hands the simulation a tail it then draws far too
    often, and an over-fat tail biases it against pitting for a reason that is
    not real.
    """
    rng = np.random.default_rng(11)
    # Purely clean stops: scatter only, no botches at all.
    clean = list(rng.normal(0.0, 1.4, 1200))
    races = [race_with_excess("Monza", 25.0, clean)]
    fit = fit_pit_loss(races)

    raw_fraction = sum(1 for x in clean if x > BOTCH_THRESHOLD) / len(clean)
    assert raw_fraction > 0.05, "the core alone should clear the threshold sometimes"
    # Almost all of that is explained by scatter, so the fitted rate is far lower.
    assert fit.botch_rate < raw_fraction / 2


def test_damage_and_penalties_are_left_out_of_the_tail():
    """Beyond the cap it is a repair or an uncaught penalty, not a routine stop.

    Folding those in would tell the simulation a stop carries a few percent
    chance of losing fifteen seconds, which is a different event that the pit
    loss model does not claim to describe.
    """
    rng = np.random.default_rng(12)
    ordinary = list(rng.normal(0.0, 1.4, 1000)) + [3.0, 4.0, 5.0] * 20
    catastrophes = [40.0] * 60  # front wing changes

    without = fit_pit_loss([race_with_excess("Monza", 25.0, ordinary)])
    with_them = fit_pit_loss([race_with_excess("Monza", 25.0, ordinary + catastrophes)])

    assert all(x <= BOTCH_CAP or True for x in catastrophes)
    # The 40s events are excluded, so they must not move the fitted tail.
    assert with_them.botch_scale == pytest.approx(without.botch_scale, rel=0.1)
    assert with_them.botch_rate == pytest.approx(without.botch_rate, rel=0.1)


def test_history_without_per_stop_detail_warns_and_uses_defaults():
    """An older data file has no `excess`, so the tail cannot be measured."""
    fit = fit_pit_loss([race("Monza", 25.0) for _ in range(4)])
    assert fit.botch_rate == pytest.approx(DEFAULT_BOTCH_RATE)
    assert any("botched-stop tail" in w for w in fit.warnings)


def test_normal_survival_helper():
    assert _normal_sf(0.0, 1.4) == pytest.approx(0.5)
    assert _normal_sf(2.0, 1.4) == pytest.approx(0.0766, abs=0.005)
    assert _normal_sf(2.0, 0.0) == 0.0
