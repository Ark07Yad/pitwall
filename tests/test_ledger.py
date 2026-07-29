from __future__ import annotations

import json
import subprocess

import pytest

from pitwall.ledger import (
    Prediction,
    PredictionLog,
    calibration_bins,
    race_report,
    score_predictions,
)
from pitwall.ledger.log import _slug


def make_prediction(**overrides: object) -> Prediction:
    defaults = dict(
        session="2026 Dutch GP",
        circuit="Zandvoort",
        lap=24,
        total_laps=72,
        driver="1",
        tla="NOR",
        position=3,
        pit_lap=28,
        compound="HAR",
        expected_position=2.4,
        margin=0.31,
        decisive=True,
        p_top3=0.72,
        p_points=0.99,
        p_gain=0.55,
        n_sims=3000,
        horizon_lap=34,
    )
    defaults.update(overrides)
    return Prediction(**defaults)  # type: ignore[arg-type]


# -- the log -----------------------------------------------------------


def test_writes_one_json_line_per_prediction(tmp_path):
    log = PredictionLog("Test GP", directory=tmp_path, commit=False)
    log.record(make_prediction())
    log.record(make_prediction(lap=30, tla="VER", driver="3"))

    lines = log.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["tla"] == "NOR"
    assert json.loads(lines[1])["tla"] == "VER"


def test_log_is_append_only(tmp_path):
    """A prediction that turns out badly must stay in the record."""
    log = PredictionLog("Test GP", directory=tmp_path, commit=False)
    log.record(make_prediction(lap=10))
    first = log.path.read_text(encoding="utf-8")

    log.record(make_prediction(lap=20))
    second = log.path.read_text(encoding="utf-8")

    assert second.startswith(first), "earlier entries must never be rewritten"


def test_every_prediction_is_timestamped_and_identified(tmp_path):
    log = PredictionLog("Test GP", directory=tmp_path, commit=False)
    a = log.record(make_prediction())
    b = log.record(make_prediction())

    assert a.id != b.id
    assert a.recorded_at.endswith("+00:00"), "timestamps are UTC and unambiguous"


def test_horizon_makes_the_claim_falsifiable():
    """Without a horizon a prediction can always be argued after the fact."""
    prediction = make_prediction(lap=24, total_laps=72)
    assert prediction.horizon_lap > prediction.lap


def test_entries_round_trip(tmp_path):
    log = PredictionLog("Test GP", directory=tmp_path, commit=False)
    log.record(make_prediction())
    assert log.entries()[0]["circuit"] == "Zandvoort"


def test_entries_survive_a_corrupt_line(tmp_path):
    log = PredictionLog("Test GP", directory=tmp_path, commit=False)
    log.record(make_prediction())
    with log.path.open("a", encoding="utf-8") as handle:
        handle.write("{ this is not json\n")
    log.record(make_prediction(lap=40))

    assert len(log.entries()) == 2


def test_missing_log_reads_as_empty(tmp_path):
    log = PredictionLog("Never Written", directory=tmp_path, commit=False)
    assert log.entries() == []


@pytest.mark.parametrize(
    ("name", "expected"),
    [("2026 Dutch GP", "2026-dutch-gp"), ("  Spa  ", "spa"), ("!!!", "session")],
)
def test_session_names_become_safe_filenames(name, expected):
    assert _slug(name) == expected


def test_commit_failure_does_not_raise(tmp_path):
    """A git problem must never take the engine down mid-race; the prediction
    is already on disk and only the timestamp witness is lost."""
    log = PredictionLog("Test GP", directory=tmp_path, commit=True, repo=tmp_path)
    log.record(make_prediction())

    assert log.written == 1
    assert log.commit_failures == 1, "tmp_path is not a git repo, so the commit fails"


def test_commit_stages_only_the_log(tmp_path):
    """Sweeping a source change into a prediction commit would let a sceptic
    argue the model was tuned to fit - so only the log may be staged."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / "unrelated.py").write_text("x = 1\n")

    log = PredictionLog("Test GP", directory=tmp_path / "predictions", commit=True, repo=tmp_path)
    log.record(make_prediction())

    assert log.commit_failures == 0
    committed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "predictions" in committed
    assert "unrelated.py" not in committed


# -- scoring -----------------------------------------------------------


def entry(**overrides: object) -> dict:
    base = {
        "driver": "1",
        "position": 3,
        "expected_position": 3.0,
        "p_top3": 0.7,
        "p_points": 0.95,
    }
    base.update(overrides)
    return base


def test_perfect_forecast_scores_zero():
    """Brier is an error, so lower is better and a certain correct call is 0."""
    card = score_predictions([entry(p_top3=1.0, p_points=1.0)], {"1": 2})
    assert card.brier_top3 == pytest.approx(0.0)


def test_confidently_wrong_scores_one():
    card = score_predictions([entry(p_top3=1.0)], {"1": 15})
    assert card.brier_top3 == pytest.approx(1.0)


def test_hedging_scores_in_between():
    confident_wrong = score_predictions([entry(p_top3=0.9)], {"1": 15}).brier_top3
    hedged_wrong = score_predictions([entry(p_top3=0.5)], {"1": 15}).brier_top3
    assert hedged_wrong < confident_wrong


def test_skill_is_positive_when_the_model_beats_holding_position():
    """Baseline says P8 finishes outside the top 3; the model says it gets there,
    and it does."""
    card = score_predictions([entry(position=8, p_top3=0.9)], {"1": 2})
    assert card.skill_top3 > 0


def test_skill_is_negative_when_the_model_is_worse():
    card = score_predictions([entry(position=2, p_top3=0.1)], {"1": 2})
    assert card.skill_top3 < 0


def test_retirements_are_skipped_not_counted_as_errors():
    """A car that crashes out is not a forecasting failure."""
    card = score_predictions([entry(driver="1"), entry(driver="99")], {"1": 4})
    assert card.n == 1
    assert any("no recorded finish" in w for w in card.warnings)


def test_small_samples_are_flagged():
    card = score_predictions([entry()], {"1": 3})
    assert any("too few" in w for w in card.warnings)


def test_empty_input_is_safe():
    card = score_predictions([], {})
    assert card.n == 0
    assert str(card) == "no scored predictions"


def test_scorecard_renders():
    card = score_predictions([entry() for _ in range(12)], {"1": 3})
    text = str(card)
    assert "Brier (top 3)" in text
    assert "calibration" in text


# -- calibration -------------------------------------------------------


def test_calibration_compares_claimed_against_observed():
    # Ten forecasts of 70%, seven of which happen: perfectly calibrated.
    pairs = [(0.7, 1.0)] * 7 + [(0.7, 0.0)] * 3
    bins = calibration_bins(pairs)

    assert len(bins) == 1
    assert bins[0].predicted == pytest.approx(0.7)
    assert bins[0].observed == pytest.approx(0.7)
    assert bins[0].gap == pytest.approx(0.0)


def test_overconfidence_shows_as_a_positive_gap():
    pairs = [(0.9, 1.0)] * 3 + [(0.9, 0.0)] * 7
    assert calibration_bins(pairs)[0].gap > 0


def test_certain_predictions_are_not_dropped():
    """A probability of exactly 1.0 must land in the top band, not vanish."""
    bins = calibration_bins([(1.0, 1.0), (1.0, 0.0)])
    assert sum(b.n for b in bins) == 2


def test_empty_bands_are_omitted():
    assert len(calibration_bins([(0.1, 1.0)])) == 1


# -- report ------------------------------------------------------------


def test_report_states_a_verdict_and_shows_the_calls():
    entries = [entry(position=5, p_top3=0.6) for _ in range(12)]
    text = race_report(entries, {"1": 3}, session="2026 Dutch GP", circuit="Zandvoort")

    assert "# 2026 Dutch GP" in text
    assert "## Verdict" in text
    assert "## Scores" in text
    assert "Every call" in text


def test_report_admits_when_it_loses_to_the_baseline():
    """The report has to be able to say the model failed, or it is marketing."""
    entries = [entry(position=1, p_top3=0.05) for _ in range(12)]
    text = race_report(entries, {"1": 1}, session="GP", circuit="X")
    assert "did not beat the baseline" in text.lower()


def test_report_refuses_to_conclude_from_too_little():
    text = race_report([entry()], {"1": 3}, session="GP", circuit="X")
    assert "too few" in text.lower()


def test_report_handles_an_empty_log():
    text = race_report([], {}, session="GP", circuit="X")
    assert "nothing is claimed" in text.lower()
