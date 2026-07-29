from __future__ import annotations

import random

import pytest

from pitwall.laps.records import LapRecord
from pitwall.models import DEFAULT_START_FUEL_KG, FuelModel, fit_pace
from pitwall.models.pace import MIN_LAPS
from pitwall.state.models import Compound, TrackStatus

GREEN = frozenset({TrackStatus.ALL_CLEAR})


# -- fuel model --------------------------------------------------------


def test_burn_rate_spreads_the_tank_over_the_race():
    fuel = FuelModel(total_laps=70, start_fuel_kg=70.0)
    assert fuel.burn_per_lap_kg == pytest.approx(1.0)


def test_fuel_falls_through_the_race():
    fuel = FuelModel(total_laps=70)
    assert fuel.fuel_during_lap(1) > fuel.fuel_during_lap(35) > fuel.fuel_during_lap(70)


def test_fuel_uses_the_midpoint_of_the_lap():
    """A lap run between 70 kg and 69 kg behaves like 69.5 kg, not 70."""
    fuel = FuelModel(total_laps=70, start_fuel_kg=70.0)
    assert fuel.fuel_during_lap(1) == pytest.approx(69.5)


def test_fuel_never_goes_negative():
    """Races run long under safety cars; the model must not invent anti-fuel."""
    fuel = FuelModel(total_laps=70)
    assert fuel.fuel_during_lap(200) == 0.0


def test_penalty_shrinks_as_fuel_burns():
    fuel = FuelModel(total_laps=70)
    assert fuel.penalty(1) > fuel.penalty(60)


def test_correction_makes_early_and_late_laps_comparable():
    """Two laps of equal true pace, run heavy and light, should correct to the
    same value - that is the entire point of the correction."""
    fuel = FuelModel(total_laps=70, start_fuel_kg=70.0, seconds_per_kg=0.035)
    heavy = 85.0
    light = heavy - (fuel.penalty(5) - fuel.penalty(65))

    assert fuel.correct(heavy, 5) == pytest.approx(fuel.correct(light, 65), abs=1e-9)


def test_seconds_per_lap_matches_the_published_scale():
    """70 kg over 70 laps at 0.035 s/kg is ~0.035 s/lap."""
    fuel = FuelModel(total_laps=70)
    assert fuel.seconds_per_lap == pytest.approx(0.035, abs=0.001)


def test_default_fuel_is_the_2026_allowance():
    assert DEFAULT_START_FUEL_KG == 70.0


def test_calibration_takes_the_magnitude_of_a_negative_trend():
    """`fit_pace` reports the trend as negative; the model holds it as a penalty."""
    fuel = FuelModel(total_laps=70, start_fuel_kg=70.0)
    calibrated = fuel.calibrated(-0.050)
    assert calibrated.seconds_per_kg == pytest.approx(0.050)
    assert calibrated.seconds_per_lap == pytest.approx(0.050)


def test_zero_laps_rejected():
    with pytest.raises(ValueError, match="total_laps"):
        FuelModel(total_laps=0)


# -- pace decomposition ------------------------------------------------


def synthetic_race(
    *,
    beta: float = -0.05,
    degradation: dict[Compound, float] | None = None,
    offsets: dict[Compound, float] | None = None,
    noise: float = 0.0,
    stagger: bool = True,
    seed: int = 7,
) -> list[LapRecord]:
    """Build laps from a known model so the fit can be checked against truth.

    `stagger` varies which compound each driver runs in which stint. Without it
    every driver runs the same compound in the same phase of the race, compound
    and race lap become collinear, and no estimator can separate them - which is
    exactly the real-world failure this guards against.
    """
    degradation = degradation or {
        Compound.SOFT: 0.12,
        Compound.MEDIUM: 0.08,
        Compound.HARD: 0.05,
    }
    offsets = offsets or {Compound.SOFT: -0.6, Compound.MEDIUM: -0.3, Compound.HARD: 0.0}
    rng = random.Random(seed)
    order = [Compound.SOFT, Compound.MEDIUM, Compound.HARD]

    laps: list[LapRecord] = []
    for d in range(10):
        base = 84.0 + d * 0.15
        lap_number = 1
        for stint in range(3):
            compound = order[(stint + d) % 3] if stagger else order[stint]
            for age in range(1, 16):
                time = base + beta * lap_number + offsets[compound] + degradation[compound] * age
                if noise:
                    time += rng.gauss(0.0, noise)
                laps.append(
                    LapRecord(
                        driver=str(d),
                        tla=f"D{d:02d}",
                        team="T",
                        lap=lap_number,
                        lap_time=time,
                        compound=compound,
                        tyre_age=age,
                        stint=stint,
                        position=d + 1,
                        interval=5.0,
                        gap_to_leader="+5.0",
                        track_statuses=GREEN,
                        entered_pit=False,
                        exited_pit=False,
                        retired=False,
                    )
                )
                lap_number += 1
    return laps


def test_recovers_known_coefficients():
    """The estimator must return the model it was given, noise-free."""
    truth = {Compound.SOFT: 0.12, Compound.MEDIUM: 0.08, Compound.HARD: 0.05}
    fit = fit_pace(synthetic_race(beta=-0.05, degradation=truth))

    assert fit is not None
    assert fit.race_lap_coef == pytest.approx(-0.05, abs=1e-6)
    for compound, rate in truth.items():
        assert fit.degradation[compound] == pytest.approx(rate, abs=1e-6)
    assert fit.r_squared > 0.99


def test_recovers_coefficients_through_noise():
    truth = {Compound.SOFT: 0.12, Compound.MEDIUM: 0.08, Compound.HARD: 0.05}
    fit = fit_pace(synthetic_race(beta=-0.05, degradation=truth, noise=0.25))

    assert fit is not None
    assert fit.race_lap_coef == pytest.approx(-0.05, abs=0.02)
    for compound, rate in truth.items():
        assert fit.degradation[compound] == pytest.approx(rate, abs=0.02)


def test_recovers_compound_ordering():
    """Softer compounds degrade faster; the fit must reproduce that ordering."""
    fit = fit_pace(synthetic_race())
    assert fit is not None
    assert (
        fit.degradation[Compound.SOFT]
        > fit.degradation[Compound.MEDIUM]
        > fit.degradation[Compound.HARD]
    )


def test_compound_offsets_are_recovered_relative_to_reference():
    """Regression: without per-compound intercepts the baseline pace difference
    is absorbed into the slope, which reverses the degradation ordering."""
    fit = fit_pace(
        synthetic_race(offsets={Compound.SOFT: -0.6, Compound.MEDIUM: -0.3, Compound.HARD: 0.0})
    )
    assert fit is not None
    reference = fit.reference_compound
    assert fit.compound_offset[reference] == 0.0

    expected = {Compound.SOFT: -0.6, Compound.MEDIUM: -0.3, Compound.HARD: 0.0}
    for compound, offset in fit.compound_offset.items():
        relative = expected[compound] - expected[reference]
        assert offset == pytest.approx(relative, abs=1e-6)


def test_warns_when_compound_usage_tracks_race_phase():
    """Every driver on the same compound in the same phase: unidentifiable."""
    fit = fit_pace(synthetic_race(stagger=False))
    assert fit is not None
    assert any("separated by race phase" in w for w in fit.warnings)


def test_no_phase_warning_when_usage_is_staggered():
    fit = fit_pace(synthetic_race(stagger=True))
    assert fit is not None
    assert not any("separated by race phase" in w for w in fit.warnings)


def test_returns_none_below_the_minimum():
    assert fit_pace(synthetic_race()[: MIN_LAPS - 1]) is None


def test_returns_none_without_usable_laps():
    assert fit_pace([]) is None


def test_implied_sensitivity_matches_the_burn_rate():
    fit = fit_pace(synthetic_race(beta=-0.05))
    assert fit is not None
    assert fit.implied_seconds_per_kg(1.0) == pytest.approx(0.05, abs=1e-6)
    assert fit.implied_seconds_per_kg(0.0) != fit.implied_seconds_per_kg(0.0)  # nan


def test_report_renders():
    fit = fit_pace(synthetic_race())
    assert fit is not None
    text = str(fit)
    assert "race-lap trend" in text
    assert "degradation" in text


# -- refusing to simulate from a degenerate fit ------------------------


def unusable_fit(**overrides):
    from pitwall.models.pace import PaceFit

    defaults = dict(
        race_lap_coef=-0.05,
        degradation={Compound.HARD: 0.08},
        compound_offset={Compound.HARD: 0.0},
        reference_compound=Compound.HARD,
        compound_phase={},
        driver_pace={"1": 0.0, "2": 1.0},
        n_laps=200,
        n_stints=20,
        residual_std=0.5,
        r_squared=0.8,
        warnings=(),
    )
    defaults.update(overrides)
    return PaceFit(**defaults)


def test_a_sound_fit_is_usable():
    assert unusable_fit().usable


def test_rank_deficient_fit_is_refused():
    """If the effects are not separately identified the coefficients are
    arbitrary, and least squares returns them anyway."""
    fit = unusable_fit(warnings=("design matrix is rank deficient (20 of 23) - ...",))
    assert not fit.usable


def test_positive_race_lap_trend_is_refused():
    """Cars get faster as fuel burns off. A positive trend means the fit is
    describing something other than a race."""
    assert not unusable_fit(race_lap_coef=+0.03).usable


def test_absurd_pace_spread_is_refused():
    """Regression: at lap 16 of Hungary the fit reported a 67-second spread in
    driver pace and +28 s/lap of hard-tyre degradation. Nothing errored - the
    simulation just produced confident nonsense from it."""
    assert not unusable_fit(driver_pace={"1": 0.0, "2": 67.2}).usable


def test_absurd_degradation_is_refused():
    assert not unusable_fit(degradation={Compound.HARD: 28.16}).usable


def test_refusal_explains_itself():
    reasons = unusable_fit(race_lap_coef=+0.03).unusable_reasons
    assert reasons and "positive" in reasons[0]
