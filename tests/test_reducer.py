from __future__ import annotations

from pathlib import Path

import pytest

from pitwall.feed.replay import ReplayFeed, read_events
from pitwall.state.models import Compound, TrackStatus
from pitwall.state.reducer import RaceStateReducer, parse_lap_time


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1:18.400", 78.4),
        ("0:59.999", 59.999),
        ("23.456", 23.456),
        ("1:00.000", 60.0),
        ("", None),
        (None, None),
        ("garbage", None),
    ],
)
def test_parse_lap_time(text, expected):
    result = parse_lap_time(text)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def fold(path: Path) -> RaceStateReducer:
    reducer = RaceStateReducer()
    for event in read_events(path):
        reducer.apply(event)
    return reducer


def test_session_metadata_from_snapshot(recording: Path):
    state = fold(recording).state
    assert state.session_name == "Race"
    assert state.circuit == "Hungaroring"
    assert state.total_laps == 70


def test_lap_count_follows_latest_update(recording: Path):
    state = fold(recording).state
    assert state.lap == 3
    assert state.laps_remaining == 67


def test_driver_identity_is_populated(recording: Path):
    state = fold(recording).state
    ver = state.car_by_tla("VER")
    assert ver is not None
    assert ver.number == "1"
    assert ver.name == "Max Verstappen"
    assert ver.team == "Red Bull"


def test_partial_timing_update_keeps_earlier_fields(recording: Path):
    """Lap 2 sent only `NumberOfLaps` for car 1; its lap time must survive."""
    state = fold(recording).state
    ver = state.cars["1"]
    assert ver.laps_completed == 2
    assert ver.last_lap_time == pytest.approx(78.4)
    assert ver.position == 1
    assert ver.sectors[0] == pytest.approx(24.1)


def test_pit_stop_updates_count_and_flags(recording: Path):
    state = fold(recording).state
    nor = state.cars["4"]
    assert nor.pit_count == 1
    assert nor.in_pit is False
    assert nor.pit_out is True


def test_new_stint_becomes_current_tyre(recording: Path):
    state = fold(recording).state
    nor = state.cars["4"]
    assert len(nor.stints) == 2
    assert nor.stints[0].compound is Compound.SOFT
    assert nor.compound is Compound.HARD
    assert nor.tyre_age == 0


def test_tyre_age_accumulates(recording: Path):
    state = fold(recording).state
    assert state.cars["1"].compound is Compound.MEDIUM
    assert state.cars["1"].tyre_age == 2


def test_safety_car_is_recognised_as_neutralised(recording: Path):
    state = fold(recording).state
    assert state.track_status is TrackStatus.SAFETY_CAR
    assert state.track_status.is_neutralised


def test_green_flag_is_not_neutralised():
    assert not TrackStatus.ALL_CLEAR.is_neutralised


def test_weather_is_parsed_to_numbers(recording: Path):
    state = fold(recording).state
    assert state.weather.air_temp == pytest.approx(28.4)
    assert state.weather.track_temp == pytest.approx(44.1)
    assert state.weather.rainfall is False


def test_running_order_is_by_position(recording: Path):
    state = fold(recording).state
    order = [car.tla for car in state.running_order() if car.position]
    assert order == ["VER", "NOR"]


def test_unknown_compound_does_not_raise():
    assert Compound.parse("SUPERSOFT") is Compound.UNKNOWN
    assert Compound.parse(None) is Compound.UNKNOWN
    assert Compound.parse("soft") is Compound.SOFT


def test_reducer_survives_junk_payloads():
    from datetime import datetime

    from pitwall.feed.base import FeedEvent

    reducer = RaceStateReducer()
    for data in ("a string", 42, None, [], {"Lines": "not a mapping"}):
        reducer.apply(FeedEvent(topic="TimingData", data=data, timestamp=datetime.now()))

    assert reducer.state.cars == {}


async def test_fold_over_feed_matches_direct_read(recording: Path):
    direct = fold(recording).state

    streamed = RaceStateReducer()
    async with ReplayFeed(recording) as feed:
        async for event in feed:
            streamed.apply(event)

    assert streamed.state.lap == direct.lap
    assert streamed.state.events_applied == direct.events_applied
    assert set(streamed.state.cars) == set(direct.cars)
