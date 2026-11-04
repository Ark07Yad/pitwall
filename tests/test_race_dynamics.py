"""Passing and neutralisation, measured rather than set by hand.

Both models are fitted on records `scripts/fetch_race_dynamics.py` writes. These
build records from a known answer and check the fit finds it.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.special import ndtr

from pitwall.models.neutralisation import events, fit_neutralisation
from pitwall.models.overtaking import LAP_NOISE, fit_overtaking

# -- passing -------------------------------------------------------------


def race(
    circuit: str,
    *,
    base: float,
    per_second: float,
    season: int = 2026,
    followers_per_bin: int = 400,
) -> dict:
    """Following laps whose pass rate is exactly the simulation's rule."""
    advantage = [round(x, 2) for x in np.arange(-1.0, 2.01, 0.25)]
    n, passed = [], []
    for x in advantage:
        chance = min(0.95, base + per_second * max(x, 0.0))
        rate = chance * float(ndtr(x / (math.sqrt(2) * LAP_NOISE)))
        n.append(followers_per_bin)
        passed.append(round(rate * followers_per_bin))
    return {
        "season": season,
        "round": 1,
        "circuit": circuit,
        "followers": sum(n),
        "passes": sum(passed),
        "advantage": advantage,
        "n": n,
        "passed": passed,
    }


def field(**kwargs) -> list[dict]:
    """Ten 2026 races at an ordinary track and a few at a hard and an easy one."""
    return (
        [race("Average", base=0.16, per_second=0.12, **kwargs) for _ in range(10)]
        + [race("Monte Carlo", base=0.02, per_second=0.12, **kwargs) for _ in range(3)]
        + [race("Catalunya", base=0.32, per_second=0.12, **kwargs) for _ in range(3)]
    )


def test_it_recovers_the_rule_it_was_built_from():
    model = fit_overtaking([race("Average", base=0.16, per_second=0.12) for _ in range(10)])

    assert model.base == pytest.approx(0.16, abs=0.01)
    assert model.per_second == pytest.approx(0.12, abs=0.02)


def test_fitting_the_raw_rate_would_halve_the_base():
    """The reason for the `reach` term: a pinned car only rolls on laps it
    closes back in, about half of them for an evenly matched pair."""
    data = race("Average", base=0.16, per_second=0.0)
    even = data["advantage"].index(0.0)
    raw_rate = data["passed"][even] / data["n"][even]

    assert raw_rate == pytest.approx(0.08, abs=0.005)
    assert fit_overtaking([data] * 10).base == pytest.approx(0.16, abs=0.01)


def test_a_hard_track_reads_hard_and_an_easy_one_easy():
    model = fit_overtaking(field())

    # Keyed as the feed and the history spell them, through the alias table.
    assert model.base_for("Monte Carlo") < model.base_for("Average") < model.base_for("Catalunya")
    assert model.known_circuit("Monaco") and model.known_circuit("Barcelona")
    assert not model.known_circuit("Nowhere")
    assert model.base_for("Nowhere") == pytest.approx(model.base)


def test_the_level_comes_from_the_current_era():
    """2026 changed the rules. Races from before it say how hard each track is
    against its own era, not what the level is now."""
    earlier = [race("Average", base=0.08, per_second=0.23, season=2024) for _ in range(20)]
    current = [race("Average", base=0.17, per_second=0.12) for _ in range(10)]
    model = fit_overtaking(earlier + current)

    assert model.base == pytest.approx(0.17, abs=0.015)
    assert model.per_second == pytest.approx(0.12, abs=0.03)


def test_too_few_current_races_falls_back_to_every_season_and_says_so():
    earlier = [race("Average", base=0.08, per_second=0.23, season=2024) for _ in range(20)]
    current = [race("Average", base=0.17, per_second=0.12) for _ in range(2)]
    model = fit_overtaking(earlier + current)

    assert any("level taken from every season" in w for w in model.warnings)


def test_one_race_is_shrunk_further_than_five():
    one = [race("Average", base=0.16, per_second=0.12) for _ in range(10)] + [
        race("Rare", base=0.02, per_second=0.12)
    ]
    five = [race("Average", base=0.16, per_second=0.12) for _ in range(10)] + [
        race("Rare", base=0.02, per_second=0.12) for _ in range(5)
    ]

    assert fit_overtaking(one).circuit_factor["Rare"] > fit_overtaking(five).circuit_factor["Rare"]


def test_a_race_with_too_few_following_laps_is_left_out():
    thin = race("Average", base=0.16, per_second=0.12, followers_per_bin=2)
    assert fit_overtaking([thin]) is None


# -- neutralisation ----------------------------------------------------------


def test_a_vsc_upgraded_to_a_safety_car_is_one_safety_car():
    """Read the way the hazard reads it, or the share and the hazard disagree."""
    bahrain_2022 = {"sc_laps": [44, 45, 46, 47, 48, 49, 50], "vsc_laps": [44, 45, 46]}
    vsc_only = {"sc_laps": [], "vsc_laps": [10, 11]}

    assert events(bahrain_2022) == [("sc", 7)]
    assert events(vsc_only) == [("vsc", 2)]
    assert events({"sc_laps": [5, 6], "vsc_laps": [20]}) == [("sc", 2), ("vsc", 1)]


def stops(green: float, sc: list[float], vsc: list[float], circuit: str = "Test") -> dict:
    return {"circuit": circuit, "green": [green] * 8, "sc": sc, "vsc": vsc}


def test_the_discount_is_measured_against_the_same_race():
    """A slow-pit-lane circuit has slow neutralised stops too; the ratio within
    the race is what cancels the circuit."""
    races = [stops(20.0, [14.0], [16.0]) for _ in range(4)] + [
        stops(30.0, [21.0], [24.0]) for _ in range(4)
    ]
    model = fit_neutralisation(races, [])

    assert model.sc_discount == pytest.approx(0.70)
    assert model.vsc_discount == pytest.approx(0.80)


def test_too_few_races_keep_the_old_discount_and_say_so():
    model = fit_neutralisation([stops(20.0, [14.0], []) for _ in range(2)], [])

    assert model.sc_discount == pytest.approx(0.55)
    # With no VSC stops to measure, a VSC costs what a safety car does.
    assert model.vsc_discount == model.sc_discount
    assert len(model.warnings) == 2


def test_durations_and_the_vsc_share_come_from_the_history():
    history = [
        {"circuit": "Often", "sc_laps": [10, 11, 12, 13], "vsc_laps": [30, 31]},
        {"circuit": "Often", "sc_laps": [], "vsc_laps": [5, 6]},
        {"circuit": "Never", "sc_laps": [3, 4, 5, 6], "vsc_laps": []},
    ]
    model = fit_neutralisation([], history)

    assert 1 / model.sc_end_chance == pytest.approx(4.0)
    assert 1 / model.vsc_end_chance == pytest.approx(2.0)
    assert model.vsc_share == pytest.approx(2 / 4)
    # Shrunk toward the pooled share, never past it.
    assert 0.5 < model.vsc_share_for("Often") < 2 / 3
    assert 0.0 < model.vsc_share_for("Never") < 0.5
    assert model.vsc_share_for("Nowhere") == pytest.approx(0.5)


# -- provenance and wiring -----------------------------------------------------


def test_a_call_made_without_them_keeps_its_old_fingerprint():
    """Rows written before November must still compare equal to a rerun made
    the same way, so the new terms appear only when the models are used."""
    from pitwall.models.fingerprint import model_terms

    plain = model_terms(circuit="Monza")
    with_dynamics = model_terms(circuit="Monza", overtaking=fit_overtaking(field()))

    assert plain == ["circuit=Monza", "sc=none", "at=none", "pl=none", "dg=none"]
    assert with_dynamics[:-1] == plain
    assert with_dynamics[-1].startswith("ot=")


def test_the_hand_set_flag_reaches_the_engine(tmp_path, monkeypatch):
    import pitwall.cli as cli
    import pitwall.dashboard as dashboard

    built = []
    monkeypatch.setattr(
        dashboard,
        "serve",
        lambda engine, **_: built.append(
            (engine.overtaking is None, engine.neutralisation is None)
        ),
    )
    recording = tmp_path / "race.txt"
    recording.write_text("")
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    monkeypatch.chdir(root)

    cli.main(["dashboard", "--replay", str(recording)])
    cli.main(["dashboard", "--replay", str(recording), "--hand-set-dynamics"])

    assert built == [(False, False), (True, True)]
