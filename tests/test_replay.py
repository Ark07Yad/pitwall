from __future__ import annotations

import json
from pathlib import Path

from pitwall.feed.base import inflate
from pitwall.feed.replay import ReplayFeed, parse_line, parse_timestamp, read_events

from .conftest import compress


def test_parses_seven_digit_dotnet_timestamps():
    parsed = parse_timestamp("2026-07-26T14:03:21.1234567Z")
    assert parsed is not None
    assert (parsed.hour, parsed.minute, parsed.second) == (14, 3, 21)
    assert parsed.microsecond == 123456


def test_rejects_unparseable_timestamp():
    assert parse_timestamp("") is None
    assert parse_timestamp("not a time") is None


def test_apostrophes_survive_parsing():
    """The reason this uses `ast.literal_eval` rather than quote substitution.

    FastF1 turns Python reprs into JSON by replacing `'` with `"`. Any payload
    containing an apostrophe - race control messages routinely do - is corrupted
    by that, and the message is dropped.
    """
    message = "CAR 4 - DRIVER'S PIT ENTRY UNDER INVESTIGATION"
    line = repr(["RaceControlMessages", {"Messages": {"1": {"Message": message}}}, ""])

    parsed = parse_line(line)

    assert parsed is not None
    topic, data, _ = parsed
    assert topic == "RaceControlMessages"
    assert data["Messages"]["1"]["Message"] == message


def test_compressed_topic_is_inflated_and_renamed():
    payload = {"Entries": [{"Utc": "2026-07-26T14:05:00Z", "Cars": {"1": {"Speed": 312}}}]}
    line = repr(["CarData.z", compress(payload), "2026-07-26T14:05:00.0000000Z"])

    parsed = parse_line(line)

    assert parsed is not None
    topic, data, _ = parsed
    assert topic == "CarData", "consumers should never see the .z suffix"
    assert data == payload


def test_inflate_roundtrip():
    payload = {"a": [1, 2, 3], "b": {"c": True}}
    assert inflate(compress(payload)) == payload


def test_snapshot_payload_given_as_json_string_is_parsed():
    line = repr(["SessionInfo", json.dumps({"Name": "Race"}), ""])
    parsed = parse_line(line)
    assert parsed is not None
    assert parsed[1] == {"Name": "Race"}


def test_blank_and_malformed_lines_are_skipped():
    assert parse_line("") is None
    assert parse_line("   ") is None
    assert parse_line("this is not a record") is None
    assert parse_line(repr(["OnlyOneField"])) is None


def test_read_events_assigns_session_relative_times(recording: Path):
    events = list(read_events(recording))

    assert len(events) > 10
    timed = [e for e in events if e.session_time is not None]
    assert timed[0].session_time.total_seconds() == 0
    assert timed[-1].session_time.total_seconds() > 0
    assert all(e.session_time.total_seconds() >= 0 for e in timed)


def test_snapshot_events_are_flagged(recording: Path):
    events = list(read_events(recording))
    assert events[0].is_snapshot
    assert events[0].topic == "SessionInfo"


async def test_replay_feed_yields_every_event(recording: Path):
    expected = len(list(read_events(recording)))

    seen = []
    async with ReplayFeed(recording) as feed:
        async for event in feed:
            seen.append(event)

    assert len(seen) == expected


async def test_replay_is_deterministic(recording: Path):
    """Two runs must produce identical streams, or replay-based tests are worthless."""

    async def run() -> list[tuple[str, str]]:
        out = []
        async with ReplayFeed(recording) as feed:
            async for event in feed:
                out.append((event.topic, repr(event.data)))
        return out

    assert await run() == await run()


async def test_skip_to_drops_earlier_events(recording: Path):
    from datetime import timedelta

    async with ReplayFeed(recording, skip_to=timedelta(seconds=180)) as feed:
        events = [e async for e in feed]

    assert events, "expected some events after the skip point"
    assert all(e.session_time is None or e.session_time >= timedelta(seconds=180) for e in events)


# -- raw SignalR recordings ---------------------------------------------
#
# `SignalRFeed(record_to=...)` writes the wire format verbatim, which is not what
# FastF1 writes. Until this was handled, the Dutch GP recording - 14 MB and
# 80,535 lines of a complete race - folded to *zero* events. Nothing errored:
# `parse_line` required a list, every line was a dict, and each one was skipped
# as undecodable. The race was captured and unreplayable at the same time.

from pitwall.feed.replay import parse_frames  # noqa: E402


def signalr_update(topic: str, data: object, timestamp: str = "2026-08-23T14:18:22.878Z") -> str:
    return json.dumps({"type": 1, "target": "feed", "arguments": [topic, data, timestamp]})


def test_reads_a_raw_signalr_feed_frame():
    line = signalr_update("TimingData", {"Lines": {"55": {"Position": "3"}}})
    frames = parse_frames(line)
    assert len(frames) == 1
    topic, data, timestamp = frames[0]
    assert topic == "TimingData"
    assert data == {"Lines": {"55": {"Position": "3"}}}
    assert timestamp is not None


def test_a_snapshot_frame_carries_every_topic_at_once():
    """One line, seventeen events - so the reader cannot assume line == event."""
    line = json.dumps(
        {
            "type": 3,
            "invocationId": "0",
            "result": {
                "Heartbeat": {"Utc": "2026-08-23T12:45:00Z"},
                "LapCount": {"CurrentLap": 1, "TotalLaps": 72},
                "TrackStatus": {"Status": "1"},
            },
        }
    )
    frames = parse_frames(line)
    assert {topic for topic, _, _ in frames} == {"Heartbeat", "LapCount", "TrackStatus"}
    lap_count = next(data for topic, data, _ in frames if topic == "LapCount")
    assert lap_count["TotalLaps"] == 72


def test_keepalives_carry_nothing():
    assert parse_frames('{"type":6}') == []
    assert parse_frames("") == []


def test_compressed_topics_inflate_in_signalr_frames():
    from tests.conftest import compress

    payload = {"Entries": [{"Utc": "2026-08-23T14:00:00Z"}]}
    frames = parse_frames(signalr_update("CarData.z", compress(payload)))
    assert len(frames) == 1
    topic, data, _ = frames[0]
    assert topic == "CarData"
    assert data == payload


def test_both_formats_fold_to_the_same_state(tmp_path: Path):
    """The replay path must read what the live path writes.

    A recording the engine cannot replay is a recording that cannot be
    backtested, scored, or turned into a race report - which is most of what it
    is for.
    """
    events = [
        ("SessionInfo", {"Name": "Race", "Type": "Race"}),
        ("LapCount", {"CurrentLap": 5, "TotalLaps": 72}),
        ("TrackStatus", {"Status": "1"}),
    ]
    stamp = "2026-08-23T14:00:00.000Z"

    fastf1_file = tmp_path / "fastf1.txt"
    fastf1_file.write_text(
        "\n".join(repr([topic, data, stamp]) for topic, data in events), encoding="utf-8"
    )
    signalr_file = tmp_path / "signalr.txt"
    signalr_file.write_text(
        "\n".join(signalr_update(topic, data, stamp) for topic, data in events), encoding="utf-8"
    )

    from_fastf1 = [(e.topic, e.data) for e in read_events(fastf1_file)]
    from_signalr = [(e.topic, e.data) for e in read_events(signalr_file)]
    assert from_fastf1 == from_signalr
