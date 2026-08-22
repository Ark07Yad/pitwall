from __future__ import annotations

from typing import Any

import pytest

from pitwall.models.safety_car import (
    BUCKETS,
    EventKind,
    HazardModel,
    bucket_for,
    fit_hazard,
    normalise_circuit,
)


def race(
    *,
    circuit: str = "Monza",
    total_laps: int = 50,
    sc_starts: list[int] | None = None,
    sc_laps: list[int] | None = None,
    vsc_starts: list[int] | None = None,
    vsc_laps: list[int] | None = None,
) -> dict[str, Any]:
    starts = sc_starts or []
    return {
        "circuit": circuit,
        "total_laps": total_laps,
        "sc_starts": starts,
        "sc_laps": sc_laps if sc_laps is not None else starts,
        "vsc_starts": vsc_starts or [],
        "vsc_laps": vsc_laps if vsc_laps is not None else (vsc_starts or []),
    }


# -- bucketing ---------------------------------------------------------


def test_lap_one_is_its_own_bucket():
    """A standing start is a different risk regime from a green-flag lap."""
    assert bucket_for(1, 50) == "lap1"
    assert bucket_for(2, 50) != "lap1"


def test_buckets_span_the_race():
    seen = {bucket_for(lap, 60) for lap in range(1, 61)}
    assert seen == set(BUCKETS)


def test_bucket_order_follows_the_race():
    assert bucket_for(5, 60) == "early"
    assert bucket_for(25, 60) == "mid"
    assert bucket_for(40, 60) == "late"
    assert bucket_for(58, 60) == "final"


def test_bucketing_survives_degenerate_races():
    assert bucket_for(1, 1) == "lap1"
    assert bucket_for(2, 1) == "early"


# -- fitting -----------------------------------------------------------


def test_returns_none_without_races():
    assert fit_hazard([]) is None


def test_counts_events_and_races():
    fit = fit_hazard([race(sc_starts=[10]), race(sc_starts=[]), race(sc_starts=[5, 30])])
    assert fit is not None
    assert fit.n_races == 3
    assert fit.n_events == 3


def test_baseline_is_events_over_exposure():
    """One event on lap 1 across ten races is a lap-1 hazard of exactly 0.1."""
    races = [race(sc_starts=[1] if i == 0 else []) for i in range(10)]
    fit = fit_hazard(races, shrinkage=0.0)

    assert fit is not None
    assert fit.baseline["lap1"] == pytest.approx(0.1)


def test_laps_already_under_a_safety_car_are_not_at_risk():
    """A ten-lap safety car is one event, and the nine laps it covers must not
    count as exposure - otherwise circuits with long neutralisations look safer
    purely because their denominators are inflated."""
    long_sc = race(sc_starts=[20], sc_laps=list(range(20, 30)))
    short_sc = race(sc_starts=[20], sc_laps=[20])

    long_fit = fit_hazard([long_sc], shrinkage=0.0)
    short_fit = fit_hazard([short_sc], shrinkage=0.0)

    assert long_fit is not None and short_fit is not None
    assert long_fit.n_events == short_fit.n_events == 1
    # Fewer at-risk laps in the long case means a *higher* fitted hazard.
    assert long_fit.baseline["mid"] > short_fit.baseline["mid"]


def test_a_ten_lap_safety_car_counts_once():
    fit = fit_hazard([race(sc_starts=[20], sc_laps=list(range(20, 30)))])
    assert fit is not None
    assert fit.n_events == 1


def test_two_separate_safety_cars_count_twice():
    fit = fit_hazard([race(sc_starts=[10, 30], sc_laps=[10, 11, 30, 31])])
    assert fit is not None
    assert fit.n_events == 2


# -- shrinkage ---------------------------------------------------------


def test_shrinkage_pulls_a_sparse_circuit_toward_the_field():
    """One race with two safety cars must not brand a circuit twice as dangerous
    as everywhere else."""
    races = [race(circuit="Quiet", sc_starts=[]) for _ in range(20)]
    races.append(race(circuit="Wild", sc_starts=[10, 30]))

    shrunk = fit_hazard(races, shrinkage=3.0)
    raw = fit_hazard(races, shrinkage=0.0)

    assert shrunk is not None and raw is not None
    assert shrunk.circuit_factor["Wild"] < raw.circuit_factor["Wild"]
    assert shrunk.circuit_factor["Wild"] > 1.0


def test_more_shrinkage_pulls_harder():
    races = [race(circuit="Quiet", sc_starts=[]) for _ in range(20)]
    races.append(race(circuit="Wild", sc_starts=[10, 30]))

    light = fit_hazard(races, shrinkage=1.0)
    heavy = fit_hazard(races, shrinkage=20.0)

    assert light is not None and heavy is not None
    assert abs(heavy.circuit_factor["Wild"] - 1.0) < abs(light.circuit_factor["Wild"] - 1.0)


def test_unseen_circuit_falls_back_to_the_baseline():
    """A circuit with no history gets a factor of 1.0, not a zero hazard."""
    fit = fit_hazard([race(circuit="Monza", sc_starts=[10])])
    assert fit is not None
    assert not fit.known_circuit("Zandvoort")
    expected = fit.baseline[bucket_for(10, 50)]
    assert fit.hazard("Zandvoort", 10, 50) == pytest.approx(expected)


# -- combining event types ---------------------------------------------


def test_any_combines_safety_car_and_vsc():
    fit = fit_hazard([race(sc_starts=[10], vsc_starts=[30])], kind=EventKind.ANY)
    assert fit is not None
    assert fit.n_events == 2


def test_a_vsc_upgraded_to_a_safety_car_is_one_event():
    """VSC on lap 20, escalated to a full safety car on 21: one incident."""
    r = race(sc_starts=[21], sc_laps=[21, 22], vsc_starts=[20], vsc_laps=[20])
    fit = fit_hazard([r], kind=EventKind.ANY)
    assert fit is not None
    assert fit.n_events == 1


def test_vsc_only_fit_ignores_safety_cars():
    fit = fit_hazard([race(sc_starts=[10], vsc_starts=[30])], kind=EventKind.VIRTUAL_SAFETY_CAR)
    assert fit is not None
    assert fit.n_events == 1


# -- prediction --------------------------------------------------------


def constant_model(hazard: float) -> HazardModel:
    return HazardModel(
        kind=EventKind.SAFETY_CAR,
        baseline=dict.fromkeys(BUCKETS, hazard),
        circuit_factor={"Monza": 1.0},
        circuit_races={"Monza": 5},
        n_races=5,
        n_events=5,
    )


def test_survival_compounds_over_the_window():
    model = constant_model(0.10)
    assert model.survival("Monza", 10, 12, 50) == pytest.approx(0.9**3)


def test_probability_within_is_the_complement():
    model = constant_model(0.10)
    window = model.probability_within("Monza", 10, 12, 50)
    assert window == pytest.approx(1 - 0.9**3)


def test_longer_windows_are_riskier():
    model = constant_model(0.05)
    short = model.probability_within("Monza", 10, 15, 50)
    long = model.probability_within("Monza", 10, 30, 50)
    assert long > short


def test_circuit_factor_scales_the_hazard():
    model = HazardModel(
        kind=EventKind.SAFETY_CAR,
        baseline=dict.fromkeys(BUCKETS, 0.02),
        circuit_factor={"Calm": 0.5, "Wild": 2.0},
        circuit_races={"Calm": 5, "Wild": 5},
        n_races=10,
        n_events=10,
    )
    assert model.hazard("Wild", 20, 50) == pytest.approx(4 * model.hazard("Calm", 20, 50))


def test_hazard_is_capped_at_one():
    model = HazardModel(
        kind=EventKind.SAFETY_CAR,
        baseline=dict.fromkeys(BUCKETS, 0.8),
        circuit_factor={"Wild": 5.0},
        circuit_races={"Wild": 1},
        n_races=1,
        n_events=1,
    )
    assert model.hazard("Wild", 20, 50) == 1.0


def test_expected_events_sums_the_hazard():
    model = constant_model(0.02)
    assert model.expected_events("Monza", 50) == pytest.approx(1.0)


def test_report_renders():
    fit = fit_hazard([race(sc_starts=[10]), race(circuit="Spa", sc_starts=[])])
    assert fit is not None
    text = str(fit)
    assert "hazard from 2 races" in text
    assert "Monza" in text


def test_small_sample_is_flagged():
    fit = fit_hazard([race(sc_starts=[10])])
    assert fit is not None
    assert any("noisy" in w for w in fit.warnings)


# -- circuit identity --------------------------------------------------


def test_alias_merges_a_renamed_circuit():
    """FastF1 recorded Miami as "Miami" through 2024 and "Miami Gardens" from
    2025. Left unmerged that is two thin circuits instead of one usable one."""
    races = [
        race(circuit="Miami", sc_starts=[10]),
        race(circuit="Miami Gardens", sc_starts=[20]),
    ]
    fit = fit_hazard(races)

    assert fit is not None
    assert set(fit.circuit_races) == {"Miami"}
    assert fit.circuit_races["Miami"] == 2


def test_alias_applies_to_lookups_too():
    fit = fit_hazard([race(circuit="Miami", sc_starts=[10])])
    assert fit is not None
    assert fit.known_circuit("Miami Gardens")
    assert fit.hazard("Miami Gardens", 20, 50) == fit.hazard("Miami", 20, 50)


def test_normalise_leaves_unknown_names_alone():
    assert normalise_circuit("Zandvoort") == "Zandvoort"
    assert normalise_circuit("  Monza  ") == "Monza"
    assert normalise_circuit(None) == "unknown"


def test_monaco_rename_is_merged():
    """FastF1 called it "Monaco" through 2025 and "Monte Carlo" in 2026. The
    second instance of this rename pattern, hence the alias table."""
    races = [
        race(circuit="Monaco", sc_starts=[10]),
        race(circuit="Monte Carlo", sc_starts=[20]),
    ]
    fit = fit_hazard(races)
    assert fit is not None
    assert set(fit.circuit_races) == {"Monaco"}
    assert fit.circuit_races["Monaco"] == 2


# -- circuit identity, from both sides ---------------------------------


def test_live_feed_short_names_reach_the_fitted_history():
    """Regression: the models are fitted on FastF1's `Location` but queried with
    the name the live feed sends, `Meeting.Circuit.ShortName`.

    Nine of twenty-seven circuits spell those differently, and the mismatch was
    silent - `circuit_factor.get(name, 1.0)` simply returned the neutral default,
    so the model declined to use what it knew and nothing reported it. The 2026
    Hungarian GP ran on a 1.0x safety-car factor when the fitted value was
    0.58x.
    """
    races = [
        {
            "circuit": "Budapest",
            "total_laps": 70,
            "sc_starts": [],
            "sc_laps": [],
            "vsc_starts": [],
            "vsc_laps": [],
        }
        for _ in range(5)
    ]
    races += [
        {
            "circuit": "Melbourne",
            "total_laps": 58,
            "sc_starts": [1, 20],
            "sc_laps": [1, 2, 20, 21],
            "vsc_starts": [],
            "vsc_laps": [],
        }
        for _ in range(5)
    ]
    fit = fit_hazard(races)
    assert fit is not None

    # The name the live feed actually sends at the Hungaroring.
    assert fit.known_circuit("Hungaroring")
    assert fit.hazard("Hungaroring", 30, 70) == pytest.approx(fit.hazard("Budapest", 30, 70))
    assert fit.hazard("Hungaroring", 30, 70) < fit.baseline["mid"]


@pytest.mark.parametrize(
    ("live_name", "history_name"),
    [
        ("Hungaroring", "Budapest"),
        ("Catalunya", "Barcelona"),
        ("Singapore", "Marina Bay"),
        ("Interlagos", "São Paulo"),
        ("Yas Marina Circuit", "Yas Island"),
        ("Montreal", "Montréal"),
        ("Paul Ricard", "Le Castellet"),
        ("Monte Carlo", "Monaco"),
    ],
)
def test_every_known_rename_resolves(live_name: str, history_name: str):
    """Derived from F1's own session info by `scripts/circuit_aliases.py`, not
    written from memory - a wrong entry maps one circuit's history onto another
    and nothing errors."""
    assert normalise_circuit(live_name) == normalise_circuit(history_name)
