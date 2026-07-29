"""Tests for the live SignalR parser.

The frame decoder is tested directly rather than over a socket. It is the part
that has to be right - protocol framing, snapshot expansion, compressed payloads
- and it is deterministic, so it can be exercised without a live race, which
happens roughly once a fortnight.

A network smoke test lives at the bottom, skipped by default.
"""

from __future__ import annotations

import json
import os

import pytest

from pitwall.feed.signalr import RECORD_SEPARATOR, LatencyStats, SignalRFeed
from pitwall.state.reducer import RaceStateReducer

from .conftest import compress


def frame(*messages: dict) -> str:
    """Encode messages the way the server does: JSON joined by 0x1E."""
    return "".join(json.dumps(m) + RECORD_SEPARATOR for m in messages)


def feed_message(topic: str, data: object, stamp: str = "2026-07-26T14:03:21.1234567Z") -> dict:
    return {"type": 1, "target": "feed", "arguments": [topic, data, stamp]}


# -- framing -----------------------------------------------------------


def test_snapshot_expands_to_one_event_per_topic():
    """Joining a race in progress makes the snapshot the only source of most
    state, so every topic in it has to become an event."""
    feed = SignalRFeed()
    raw = frame(
        {
            "type": 3,
            "invocationId": "0",
            "result": {
                "SessionInfo": {"Name": "Race"},
                "TrackStatus": {"Status": "1"},
                "LapCount": {"CurrentLap": 5, "TotalLaps": 70},
            },
        }
    )

    events = feed._decode(raw)

    assert {e.topic for e in events} == {"SessionInfo", "TrackStatus", "LapCount"}
    assert all(e.is_snapshot for e in events), "snapshot events carry no timestamp"


def test_feed_message_becomes_one_event():
    feed = SignalRFeed()
    events = feed._decode(frame(feed_message("TrackStatus", {"Status": "4"})))

    assert len(events) == 1
    assert events[0].topic == "TrackStatus"
    assert events[0].data == {"Status": "4"}
    assert events[0].timestamp is not None
    assert not events[0].is_snapshot


def test_several_messages_in_one_frame():
    """A single websocket read can carry several records; missing that drops
    every message after the first."""
    feed = SignalRFeed()
    raw = frame(
        feed_message("TrackStatus", {"Status": "2"}),
        feed_message("LapCount", {"CurrentLap": 12}),
        feed_message("WeatherData", {"AirTemp": "28.1"}),
    )

    events = feed._decode(raw)

    assert [e.topic for e in events] == ["TrackStatus", "LapCount", "WeatherData"]


def test_ping_produces_nothing():
    """Type 6 is a keepalive. It is the only traffic between sessions, so it must
    yield no events - and equally must not be treated as a dead connection."""
    feed = SignalRFeed()
    assert feed._decode(frame({"type": 6})) == []


def test_close_frame_produces_nothing():
    feed = SignalRFeed()
    assert feed._decode(frame({"type": 7, "error": None})) == []


def test_unknown_target_ignored():
    feed = SignalRFeed()
    raw = frame({"type": 1, "target": "somethingElse", "arguments": ["X", {}]})
    assert feed._decode(raw) == []


def test_malformed_json_is_skipped_not_fatal():
    """One bad frame must not end the stream mid-race."""
    feed = SignalRFeed()
    raw = (
        "{not json}"
        + RECORD_SEPARATOR
        + json.dumps(feed_message("LapCount", {"CurrentLap": 3}))
        + RECORD_SEPARATOR
    )

    events = feed._decode(raw)

    assert len(events) == 1
    assert events[0].topic == "LapCount"


def test_empty_frame_is_safe():
    feed = SignalRFeed()
    assert feed._decode("") == []
    assert feed._decode(RECORD_SEPARATOR) == []


def test_bytes_frames_are_decoded():
    feed = SignalRFeed()
    raw = frame(feed_message("LapCount", {"CurrentLap": 9})).encode()
    assert feed._decode(raw)[0].data == {"CurrentLap": 9}


def test_short_arguments_ignored():
    feed = SignalRFeed()
    assert feed._decode(frame({"type": 1, "target": "feed", "arguments": ["OnlyTopic"]})) == []


# -- compressed topics -------------------------------------------------


def test_compressed_topic_is_inflated_and_renamed():
    feed = SignalRFeed()
    payload = {"Entries": [{"Utc": "2026-07-26T14:05:00Z", "Cars": {"1": {"Speed": 315}}}]}
    events = feed._decode(frame(feed_message("CarData.z", compress(payload))))

    assert len(events) == 1
    assert events[0].topic == "CarData", "consumers must never see the .z suffix"
    assert events[0].data == payload


def test_compressed_topic_in_a_snapshot():
    feed = SignalRFeed()
    payload = {"Position": [{"Entries": {}}]}
    raw = frame({"type": 3, "result": {"Position.z": compress(payload)}})

    events = feed._decode(raw)

    assert [e.topic for e in events] == ["Position"]
    assert events[0].data == payload


def test_corrupt_compressed_payload_is_dropped_not_raised():
    feed = SignalRFeed()
    assert feed._decode(frame(feed_message("CarData.z", "not-valid-base64!!"))) == []


# -- integration with the rest of the pipeline -------------------------


def test_decoded_events_fold_into_race_state():
    """The point of the whole module: live frames must drive the same reducer
    that recordings do."""
    feed = SignalRFeed()
    reducer = RaceStateReducer()

    raw = frame(
        {
            "type": 3,
            "result": {
                "SessionInfo": {
                    "Name": "Race",
                    "Meeting": {"Circuit": {"ShortName": "Zandvoort"}},
                },
                "DriverList": {"1": {"Tla": "NOR", "TeamName": "McLaren"}},
                "LapCount": {"CurrentLap": 1, "TotalLaps": 72},
            },
        },
        feed_message("LapCount", {"CurrentLap": 14}),
        feed_message("TrackStatus", {"Status": "4", "Message": "SCDeployed"}),
    )

    for event in feed._decode(raw):
        reducer.apply(event)

    state = reducer.state
    assert state.circuit == "Zandvoort"
    assert state.lap == 14
    assert state.total_laps == 72
    assert state.track_status.is_neutralised
    assert state.cars["1"].tla == "NOR"


def test_frames_are_recorded_when_asked(tmp_path):
    """Live data cannot be recovered afterwards, so the raw stream is kept."""
    path = tmp_path / "live.txt"
    feed = SignalRFeed(record_to=str(path))
    feed._record_file = path.open("a", encoding="utf-8")

    feed._decode(frame(feed_message("LapCount", {"CurrentLap": 4})))
    feed._record_file.close()

    written = path.read_text(encoding="utf-8")
    assert "LapCount" in written
    assert RECORD_SEPARATOR not in written, "separators are rewritten as newlines"


# -- latency -----------------------------------------------------------


def test_latency_percentiles():
    stats = LatencyStats()
    for value in range(100):
        stats.record(lag=float(value), decode=float(value) / 1000)

    summary = stats.summary()
    assert 45 <= summary["lag_p50"] <= 55
    assert summary["lag_p99"] >= 95
    assert summary["decode_p99"] > summary["decode_p50"]


def test_latency_is_safe_when_empty():
    stats = LatencyStats()
    assert stats.summary()["lag_p50"] == 0.0
    assert str(stats)


def test_latency_counts_are_reported():
    feed = SignalRFeed()
    feed._decode(frame(feed_message("LapCount", {"CurrentLap": 2})))
    assert feed.latency.lag_samples, "a timestamped message should record lag"


# -- live smoke test ---------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("PITWALL_LIVE_TEST") != "1",
    reason="hits F1's live endpoint; set PITWALL_LIVE_TEST=1 to run",
)
async def test_connects_to_the_real_endpoint():
    """End-to-end against F1. Works between sessions too - the server replies
    with the last session's snapshot, then only keepalive pings."""
    import asyncio

    feed = SignalRFeed(reconnect=False, silence_timeout=20.0)
    events = []
    try:
        async with asyncio.timeout(30):
            async for event in feed:
                events.append(event)
    except TimeoutError:
        pass
    finally:
        await feed.aclose()

    assert events, "expected at least the state snapshot"
    assert any(e.topic == "SessionInfo" for e in events)
