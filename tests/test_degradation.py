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
