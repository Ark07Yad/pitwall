from __future__ import annotations

from pathlib import Path

import pytest

from pitwall.feed.replay import read_events
from pitwall.laps import (
    CleanLapConfig,
    LapCollector,
    LapRecord,
    RejectReason,
    classify,
    filter_laps,
    parse_interval,
    session_best,
)
from pitwall.state.models import Compound, TrackStatus

GREEN = frozenset({TrackStatus.ALL_CLEAR})


def make_lap(**overrides: object) -> LapRecord:
    """A clean racing lap, unless an override makes it otherwise."""
    defaults = dict(
        driver="1",
        tla="NOR",
        team="McLaren",
        lap=10,
        lap_time=85.0,
        compound=Compound.MEDIUM,
        tyre_age=10,
        stint=0,
        position=1,
        interval=5.0,
        gap_to_leader="+5.000",
        track_statuses=GREEN,
        entered_pit=False,
        exited_pit=False,
        retired=False,
    )
    defaults.update(overrides)
    return LapRecord(**defaults)  # type: ignore[arg-type]


# -- interval parsing --------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("+1.325", 1.325), ("1.325", 1.325), ("+12.004", 12.004), ("0.244", 0.244)],
)
def test_parse_interval_reads_time_gaps(text, expected):
    assert parse_interval(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["1L", "2L", "15L", "", None, "LAP"])
def test_parse_interval_returns_none_for_non_gaps(text):
    """A lapped car has no time gap. None must not collapse to 0.0, or every
    lapped car would be marked as sitting in traffic."""
    assert parse_interval(text) is None


# -- classification ----------------------------------------------------


def test_clean_lap_has_no_reasons():
    assert classify(make_lap(), best=82.0) == frozenset()


def test_in_lap_rejected():
    assert RejectReason.IN_LAP in classify(make_lap(entered_pit=True), best=82.0)


def test_out_lap_rejected_via_pit_flag():
    assert RejectReason.OUT_LAP in classify(make_lap(exited_pit=True), best=82.0)


def test_out_lap_rejected_via_zero_tyre_age():
    """Catches a stop where the pit flag was never sampled during the lap."""
    lap = make_lap(stint=1, tyre_age=0, exited_pit=False)
    assert RejectReason.OUT_LAP in classify(lap, best=82.0)


def test_first_flying_lap_of_a_stint_is_kept():
    """Regression: age 1 is a real racing lap, not an out-lap.

    An earlier version rejected `tyre_age <= 1`, discarding one good lap per
    stint per car - and precisely the laps that pin down the intercept of the
    degradation curve. On one race that cost 38 usable laps.
    """
    lap = make_lap(stint=1, tyre_age=1, exited_pit=False)
    assert classify(lap, best=82.0) == frozenset()


def test_lap_one_rejected():
    assert RejectReason.FIRST_LAP in classify(make_lap(lap=1), best=82.0)


def test_lap_one_kept_when_configured():
    cfg = CleanLapConfig(exclude_first_lap=False)
    assert classify(make_lap(lap=1), best=82.0, config=cfg) == frozenset()


@pytest.mark.parametrize("status", [TrackStatus.SAFETY_CAR, TrackStatus.VSC, TrackStatus.RED])
def test_neutralised_laps_rejected(status):
    lap = make_lap(track_statuses=frozenset({TrackStatus.ALL_CLEAR, status}))
    assert RejectReason.NEUTRALISED in classify(lap, best=82.0)


def test_status_that_cleared_mid_lap_still_rejects():
    """The lap ended green but ran partly under VSC, so it is still unusable."""
    lap = make_lap(track_statuses=frozenset({TrackStatus.VSC, TrackStatus.ALL_CLEAR}))
    assert RejectReason.NEUTRALISED in classify(lap, best=82.0)


def test_traffic_rejected():
    assert RejectReason.TRAFFIC in classify(make_lap(interval=1.2), best=82.0)


def test_lap_just_outside_traffic_threshold_kept():
    assert classify(make_lap(interval=2.5), best=82.0) == frozenset()


def test_unknown_interval_is_not_traffic():
    assert classify(make_lap(interval=None), best=82.0) == frozenset()


def test_traffic_threshold_is_configurable():
    cfg = CleanLapConfig(traffic_threshold=1.0)
    assert classify(make_lap(interval=1.2), best=82.0, config=cfg) == frozenset()


def test_implausible_lap_rejected():
    """Piastri's real 5:48 cool-down lap at Hungary 2026."""
    assert RejectReason.IMPLAUSIBLE in classify(make_lap(lap_time=348.165), best=82.0)


def test_garage_lap_rejected():
    """Gasly's real 20:23 'lap' sitting in the garage after Q1 elimination."""
    assert RejectReason.IMPLAUSIBLE in classify(make_lap(lap_time=1223.94), best=82.0)


def test_slow_but_real_racing_lap_kept():
    """Heavy fuel plus worn tyres is slow, but it is still a racing lap."""
    assert classify(make_lap(lap_time=92.0), best=82.0) == frozenset()


def test_missing_time_rejected():
    assert RejectReason.NO_TIME in classify(make_lap(lap_time=None), best=82.0)


def test_retired_rejected():
    assert RejectReason.RETIRED in classify(make_lap(retired=True), best=82.0)


def test_a_lap_can_have_several_reasons():
    lap = make_lap(lap=1, entered_pit=True, interval=0.5, retired=True)
    reasons = classify(lap, best=82.0)
    assert {
        RejectReason.FIRST_LAP,
        RejectReason.IN_LAP,
        RejectReason.TRAFFIC,
        RejectReason.RETIRED,
    } <= reasons


def test_classification_survives_missing_best():
    assert classify(make_lap(), best=None) == frozenset()


# -- session best and reporting ----------------------------------------


def test_session_best_ignores_neutralised_and_pit_laps():
    laps = [
        make_lap(lap_time=95.0, track_statuses=frozenset({TrackStatus.SAFETY_CAR})),
        make_lap(lap_time=99.0, entered_pit=True),
        make_lap(lap_time=84.0),
        make_lap(lap_time=86.0),
    ]
    assert session_best(laps) == pytest.approx(84.0)


def test_session_best_none_when_nothing_usable():
    assert session_best([make_lap(lap_time=None)]) is None


def test_report_counts_and_fractions():
    laps = [make_lap(), make_lap(), make_lap(entered_pit=True), make_lap(lap=1)]
    clean, report = filter_laps(laps)

    assert len(clean) == 2
    assert report.total == 4
    assert report.clean == 2
    assert report.excluded == 2
    assert report.clean_fraction == pytest.approx(0.5)
    assert report.reasons[RejectReason.IN_LAP] == 1
    assert report.reasons[RejectReason.FIRST_LAP] == 1


def test_report_renders_without_error():
    _, report = filter_laps([make_lap(), make_lap(entered_pit=True)])
    text = str(report)
    assert "1 clean of 2 laps" in text
    assert "entered the pits" in text


def test_empty_input_is_safe():
    clean, report = filter_laps([])
    assert clean == []
    assert report.total == 0
    assert report.clean_fraction == 0.0


# -- extraction from a recording ---------------------------------------


def collect(path: Path) -> LapCollector:
    c = LapCollector()
    for event in read_events(path):
        c.apply(event)
    return c


def test_collector_extracts_laps(recording: Path):
    c = collect(recording)
    assert c.laps, "expected at least one completed lap"
    assert all(lap.lap >= 1 for lap in c.laps)
    assert all(lap.driver for lap in c.laps)


def test_lap_number_is_one_behind_the_counter(recording: Path):
    """`NumberOfLaps` is the lap being started, so its time is for the previous."""
    c = collect(recording)
    ver = [lap for lap in c.laps if lap.driver == "1"]
    assert ver
    assert ver[0].lap == 1
    assert ver[0].lap_time == pytest.approx(78.4)


def test_no_duplicate_laps(recording: Path):
    c = collect(recording)
    keys = [(lap.driver, lap.lap) for lap in c.laps]
    assert len(keys) == len(set(keys))


def test_collector_captures_compound_and_age(recording: Path):
    c = collect(recording)
    ver = [lap for lap in c.laps if lap.driver == "1"]
    assert ver[0].compound is Compound.MEDIUM


def test_collector_state_matches_a_plain_reducer(recording: Path):
    c = collect(recording)
    assert c.state.lap == 3
    assert c.state.circuit == "Hungaroring"
