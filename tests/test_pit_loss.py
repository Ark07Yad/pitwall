from __future__ import annotations

import pytest

from pitwall.models.pit_loss import (
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
