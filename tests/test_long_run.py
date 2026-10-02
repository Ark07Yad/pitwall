"""Degradation read off practice long runs.

`fit_pace` cannot read a practice session: it takes race lap as a fuel proxy and
practice resets fuel between runs. These check the thing that replaces it - long
runs only, fuel subtracted at the physics prior rather than fitted, an intercept
per run, no race-lap term - against data built from a known model.
"""

from __future__ import annotations

import random

import pytest

from pitwall.laps.records import LapRecord
from pitwall.models import fit_long_runs, long_runs
from pitwall.models.long_run import (
    MIN_RUN_LAPS,
    NOMINAL_BURN_PER_LAP_KG,
)
from pitwall.models.long_run import (
    fit_long_runs as fit_direct,
)
from pitwall.state.models import Compound, TrackStatus

GREEN = frozenset({TrackStatus.ALL_CLEAR})
FUEL_PER_LAP = 0.035 * NOMINAL_BURN_PER_LAP_KG


def practice(
    *,
    degradation: dict[Compound, float] | None = None,
    run_laps: int = 10,
    n_drivers: int = 6,
    start_age: int = 0,
    noise: float = 0.0,
    fuel_per_lap: float = FUEL_PER_LAP,
    seed: int = 11,
) -> list[LapRecord]:
    """Laps from a known model, with fuel reset between runs as in practice.

    Each driver does two runs on different compounds, separated by a gap in lap
    number so the session looks like a real Friday: a long run, a break, another
    long run. Fuel falls *within* each run and resets at the start of the next,
    which is exactly the structure that defeats a race-lap term.
    """
    degradation = degradation or {Compound.MEDIUM: 0.08, Compound.SOFT: 0.12}
    order = list(degradation)
    rng = random.Random(seed)

    laps: list[LapRecord] = []
    for d in range(n_drivers):
        base = 90.0 + d * 0.2
        lap_number = 1
        for stint, compound in enumerate(order):
            # A fresh set each run, and a different baseline per run: new tyres
            # late in a session are not the same level as scrubbed ones early.
            level = base - stint * 0.35
            for i in range(run_laps):
                age = start_age + i + 1
                time = level + degradation[compound] * age - fuel_per_lap * i
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
            # The car sits in the garage for a while between runs.
            lap_number += 8
    return laps


def test_long_runs_are_found_and_short_ones_ignored():
    laps = practice(run_laps=MIN_RUN_LAPS + 2, n_drivers=3) + practice(
        run_laps=MIN_RUN_LAPS - 2, n_drivers=3, seed=4
    )
    runs = long_runs(laps)

    assert all(run.laps >= MIN_RUN_LAPS for run in runs)


def test_it_recovers_the_degradation_it_was_built_from():
    """The whole point: a within-run slope, with fuel removed rather than fitted."""
    truth = {Compound.MEDIUM: 0.08, Compound.SOFT: 0.12}
    fit = fit_long_runs(practice(degradation=truth))

    assert fit is not None
    assert fit.usable, fit.unusable_reasons
    for compound, rate in truth.items():
        assert fit.degradation[compound] == pytest.approx(rate, abs=0.005)


def test_it_survives_noise():
    truth = {Compound.MEDIUM: 0.08, Compound.SOFT: 0.12}
    fit = fit_long_runs(practice(degradation=truth, noise=0.3, n_drivers=10))

    assert fit.degradation[Compound.SOFT] == pytest.approx(0.12, abs=0.03)


def test_a_used_set_does_not_shift_the_slope():
    """Fuel depends on laps into the run and degradation on tyre age, and on a
    scrubbed set those differ by a constant. The run's own intercept absorbs it;
    if the fit used age for both, this would come out wrong."""
    truth = {Compound.MEDIUM: 0.08, Compound.SOFT: 0.12}
    fresh = fit_long_runs(practice(degradation=truth, start_age=0))
    scrubbed = fit_long_runs(practice(degradation=truth, start_age=12))

    assert scrubbed.degradation[Compound.SOFT] == pytest.approx(
        fresh.degradation[Compound.SOFT], abs=0.005
    )


def test_ignoring_fuel_would_understate_degradation():
    """Why the correction is there at all. Fitting the same laps with no fuel
    correction leaves the burn in the slope, and the tyre looks kinder than it
    is by roughly the fuel effect."""
    truth = {Compound.MEDIUM: 0.08, Compound.SOFT: 0.12}
    laps = practice(degradation=truth)
    corrected = fit_long_runs(laps)
    uncorrected = fit_long_runs(laps, seconds_per_kg=0.0)

    gap = corrected.degradation[Compound.SOFT] - uncorrected.degradation[Compound.SOFT]
    assert gap == pytest.approx(FUEL_PER_LAP, abs=0.005)


def test_the_slope_is_conditional_on_the_fuel_figure():
    """Inside a run the two effects are one column, so an error in the assumed
    fuel effect passes straight into the slope. The fit reports that width
    rather than presenting the number as unconditional."""
    fit = fit_long_runs(practice())
    low, high = fit.sensitivity(0.25)[Compound.SOFT]

    assert high - low == pytest.approx(2 * 0.25 * FUEL_PER_LAP, abs=1e-6)
    assert low < fit.degradation[Compound.SOFT] < high


def test_one_run_is_not_enough():
    """One run gives one slope with nothing to check it against. A single driver
    on a single compound is that case - note the default fixture gives each
    driver two runs, so this has to ask for one compound explicitly."""
    one = practice(degradation={Compound.SOFT: 0.12}, n_drivers=1, run_laps=12)

    assert len(long_runs(one)) == 1
    assert fit_long_runs(one) is None


def test_a_session_of_short_runs_gives_nothing():
    """A wet or red-flagged session is mostly three-lap runs. Returning None is
    the right answer there, not a slope through out laps."""
    assert fit_long_runs(practice(run_laps=3, n_drivers=8)) is None


def test_a_negative_slope_is_refused_with_the_reason():
    """A tyre that improves with age means the fuel correction is carrying the
    run, not that the compound is magic."""
    fit = fit_direct(practice(degradation={Compound.SOFT: -0.10, Compound.MEDIUM: -0.08}))

    assert not fit.usable
    assert any("improves with age" in r for r in fit.unusable_reasons)


def test_the_factor_is_lap_weighted_against_the_pooled_shape():
    class Prior:
        linear = {Compound.MEDIUM: 0.04, Compound.SOFT: 0.06}

    fit = fit_long_runs(practice(degradation={Compound.MEDIUM: 0.08, Compound.SOFT: 0.12}))
    factor, ratios = fit.factor_against(Prior())

    assert factor == pytest.approx(2.0, abs=0.1)
    assert {c for c, _, _ in ratios} == {Compound.MEDIUM, Compound.SOFT}
