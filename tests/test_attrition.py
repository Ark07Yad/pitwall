from __future__ import annotations

from typing import Any

import pytest

from pitwall.models.attrition import AttritionModel, fit_attrition
from pitwall.models.safety_car import BUCKETS


def race(
    *,
    circuit: str = "Monza",
    total_laps: int = 50,
    starters: int = 20,
    retirements: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "circuit": circuit,
        "total_laps": total_laps,
        "starters": starters,
        "retirements": retirements or [],
    }


def constant_model(hazard: float, factor: float = 1.0) -> AttritionModel:
    return AttritionModel(
        baseline=dict.fromkeys(BUCKETS, hazard),
        circuit_factor={"Monza": factor},
        circuit_races={"Monza": 5},
        n_races=5,
        n_starters=100,
        n_retirements=10,
    )


# -- fitting -----------------------------------------------------------


def test_returns_none_without_races():
    assert fit_attrition([]) is None


def test_returns_none_without_starter_counts():
    """A race with no `starters` field carries no exposure and must not be
    silently treated as zero attrition."""
    assert fit_attrition([{"circuit": "X", "total_laps": 50}]) is None


def test_counts_starters_and_retirements():
    fit = fit_attrition([race(starters=20, retirements=[10, 30]), race(starters=20)])
    assert fit is not None
    assert fit.n_starters == 40
    assert fit.n_retirements == 2
    assert fit.rate_per_car == pytest.approx(0.05)


def test_baseline_is_events_over_car_laps():
    """One retirement on lap 1 across ten cars is a lap-1 hazard of exactly 0.1."""
    fit = fit_attrition([race(starters=10, total_laps=50, retirements=[1])], shrinkage=0.0)
    assert fit is not None
    assert fit.baseline["lap1"] == pytest.approx(0.1)


def test_a_retired_car_stops_being_exposed():
    """A car that retires on lap 5 was at risk for five laps, not the whole race.

    Counting it for the full distance would understate the hazard, and would do
    so most for the circuits where cars fail earliest."""
    early = fit_attrition([race(starters=2, total_laps=50, retirements=[5])], shrinkage=0.0)
    late = fit_attrition([race(starters=2, total_laps=50, retirements=[45])], shrinkage=0.0)

    assert early is not None and late is not None
    # Same single event, far less exposure in the early case, so a higher rate.
    assert sum(early.baseline.values()) > sum(late.baseline.values())


def test_exposure_is_per_car_not_per_race():
    """Twenty-two cars each roll the dice; a race is not one trial."""
    few = fit_attrition([race(starters=4, total_laps=50, retirements=[25])], shrinkage=0.0)
    many = fit_attrition([race(starters=40, total_laps=50, retirements=[25])], shrinkage=0.0)

    assert few is not None and many is not None
    assert few.baseline["mid"] > many.baseline["mid"]


def test_lap_one_is_separated():
    """First-lap incidents are a different regime from mechanical failures."""
    races = [race(starters=20, retirements=[1]) for _ in range(10)]
    fit = fit_attrition(races, shrinkage=0.0)
    assert fit is not None
    assert fit.baseline["lap1"] > fit.baseline["mid"]


# -- shrinkage ---------------------------------------------------------


def test_shrinkage_pulls_a_sparse_circuit_toward_the_field():
    races = [race(circuit="Reliable") for _ in range(20)]
    races.append(race(circuit="Brutal", retirements=[5, 10, 20, 30]))

    shrunk = fit_attrition(races, shrinkage=4.0)
    raw = fit_attrition(races, shrinkage=0.0)

    assert shrunk is not None and raw is not None
    assert shrunk.circuit_factor["Brutal"] < raw.circuit_factor["Brutal"]
    assert shrunk.circuit_factor["Brutal"] > 1.0


def test_unseen_circuit_falls_back_to_the_baseline():
    fit = fit_attrition([race(circuit="Monza", retirements=[10])])
    assert fit is not None
    assert not fit.known_circuit("Zandvoort")
    assert fit.hazard("Zandvoort", 25, 50) == pytest.approx(fit.baseline["mid"])


def test_circuit_aliases_are_merged():
    """Monaco became "Monte Carlo" in 2026 - the same rename trap as Miami."""
    fit = fit_attrition([race(circuit="Monaco"), race(circuit="Monte Carlo")])
    assert fit is not None
    assert set(fit.circuit_races) == {"Monaco"}


# -- prediction --------------------------------------------------------


def test_survival_compounds_over_the_window():
    model = constant_model(0.10)
    assert model.survival("Monza", 10, 12, 50) == pytest.approx(0.9**3)


def test_longer_windows_are_riskier():
    model = constant_model(0.02)
    assert model.probability_within("Monza", 10, 40, 50) > model.probability_within(
        "Monza", 10, 15, 50
    )


def test_circuit_factor_scales_the_hazard():
    calm = constant_model(0.01, factor=0.5)
    wild = constant_model(0.01, factor=2.0)
    assert wild.hazard("Monza", 20, 50) == pytest.approx(4 * calm.hazard("Monza", 20, 50))


def test_expected_retirements_scales_with_the_field():
    model = constant_model(0.002)
    one = model.expected_retirements("Monza", 50, 1)
    twenty = model.expected_retirements("Monza", 50, 20)
    assert twenty == pytest.approx(20 * one)


def test_hazard_is_capped_at_one():
    model = constant_model(0.9, factor=5.0)
    assert model.hazard("Monza", 20, 50) == 1.0


def test_report_renders():
    fit = fit_attrition([race(retirements=[10]), race(circuit="Spa")])
    assert fit is not None
    text = str(fit)
    assert "retirements" in text
    assert "Monza" in text


def test_small_sample_is_flagged():
    fit = fit_attrition([race(retirements=[10])])
    assert fit is not None
    assert any("noisy" in w for w in fit.warnings)
