"""Replay a recorded session from disk.

This is the workhorse of development. A live race happens once a fortnight and
never the same way twice; a recording can be replayed a hundred times an hour and
always behaves identically, which is what makes real regression tests possible.

Two on-disk formats are read, because this project writes one and FastF1 writes
the other, and a recording is useless if the replay path cannot read what the
live path produced:

- **FastF1's**, one Python-repr list per line: `[topic, data, timestamp]`.
- **Raw SignalR frames**, which is what `SignalRFeed(record_to=...)` writes -
  the wire format verbatim, one JSON object per line. `{"type": 1, "arguments":
  [topic, data, timestamp]}` carries the same triple; `{"type": 3, ...}` is the
  initial snapshot holding every topic at once; `{"type": 6}` is a keepalive.

Recording the raw frames is deliberate - it is the only faithful capture of what
F1 actually sent, and re-deriving it from a normalised file is impossible - so
the reader meets it rather than the recorder compromising.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pitwall.feed.base import FeedEvent, RaceFeed, inflate

log = logging.getLogger(__name__)


def parse_timestamp(value: str) -> datetime | None:
    """Parse F1's .NET-style timestamps.

    They carry 7 fractional-second digits, which `fromisoformat` rejects - it
    accepts 3 or 6. Truncate rather than round; sub-microsecond precision is
    meaningless here anyway.
    """
    if not value:
        return None
    text = value.strip().rstrip("Z")
    if "." in text:
        head, _, frac = text.partition(".")
        text = f"{head}.{frac[:6]}"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        log.debug("unparseable timestamp: %r", value)
        return None


def parse_line(line: str) -> tuple[str, Any, datetime | None] | None:
    """Parse one recorded line into `(topic, data, timestamp)`.

    FastF1 fixes up Python reprs into JSON by string-replacing quotes and
    booleans, which corrupts any payload containing an apostrophe - driver names
    and race control messages both do. `ast.literal_eval` understands Python
    literals natively and is safe (literals only, no evaluation), so it handles
    those correctly. JSON parsing stays as a fallback for lines that were already
    written as JSON.
    """
    line = line.strip()
    if not line:
        return None

    parsed: Any = None
    try:
        parsed = ast.literal_eval(line)
    except (ValueError, SyntaxError):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            log.debug("undecodable line: %.120s", line)
            return None

    if isinstance(parsed, dict):
        frames = _from_signalr(parsed)
        return frames[0] if len(frames) == 1 else None

    if not isinstance(parsed, (list, tuple)) or len(parsed) < 2:
        return None

    return _normalise(parsed[0], parsed[1], parsed[2] if len(parsed) > 2 else None)


def _normalise(topic: Any, data: Any, timestamp: Any) -> tuple[str, Any, datetime | None] | None:
    """Turn one raw triple into the form the reducer expects."""
    topic = str(topic)
    stamp = parse_timestamp(str(timestamp)) if timestamp else None

    # The initial snapshot arrives with its payload as a JSON *string*.
    if isinstance(data, str) and topic and not topic.endswith(".z"):
        with contextlib.suppress(json.JSONDecodeError):
            data = json.loads(data)

    if topic.endswith(".z"):
        topic = topic[:-2]
        if isinstance(data, str):
            try:
                data = inflate(data)
            except Exception:
                log.debug("failed to inflate %s payload", topic)
                return None

    return topic, data, stamp


def _from_signalr(frame: dict) -> list[tuple[str, Any, datetime | None]]:
    """Unwrap a raw SignalR frame into zero or more triples.

    Type 1 is a feed update whose `arguments` are already `[topic, data,
    timestamp]` - the same triple FastF1 writes to disk, which is why both
    formats converge here. Type 3 is the completion carrying the full state
    snapshot, one entry per topic and no timestamps. Type 6 is a keepalive and
    carries nothing.
    """
    kind = frame.get("type")

    if kind == 1:
        arguments = frame.get("arguments") or []
        if len(arguments) < 2:
            return []
        found = _normalise(arguments[0], arguments[1], arguments[2] if len(arguments) > 2 else None)
        return [found] if found else []

    if kind == 3:
        result = frame.get("result") or {}
        if not isinstance(result, dict):
            return []
        out = []
        for topic, data in result.items():
            found = _normalise(topic, data, None)
            if found:
                out.append(found)
        return out

    return []


def parse_frames(line: str) -> list[tuple[str, Any, datetime | None]]:
    """Every triple carried by one recorded line.

    A FastF1 line is always one event, but a raw SignalR snapshot frame holds the
    whole session state at once - seventeen topics on a single line - so the
    reader cannot assume one line means one event.
    """
    line = line.strip()
    if not line:
        return []

    parsed: Any = None
    try:
        parsed = ast.literal_eval(line)
    except (ValueError, SyntaxError):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            log.debug("undecodable line: %.120s", line)
            return []

    if isinstance(parsed, dict):
        return _from_signalr(parsed)

    if not isinstance(parsed, (list, tuple)) or len(parsed) < 2:
        return []

    found = _normalise(parsed[0], parsed[1], parsed[2] if len(parsed) > 2 else None)
    return [found] if found else []


def read_events(path: Path | str) -> Iterator[FeedEvent]:
    """Yield events from a recording, lazily. Recordings run to hundreds of MB."""
    path = Path(path)
    session_start: datetime | None = None

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            for topic, data, timestamp in parse_frames(line):
                session_time: timedelta | None = None
                if timestamp is not None:
                    if session_start is None:
                        session_start = timestamp
                    session_time = timestamp - session_start

                yield FeedEvent(
                    topic=topic,
                    data=data,
                    timestamp=timestamp,
                    session_time=session_time,
                )


class ReplayFeed(RaceFeed):
    """Replay a recording as an async event stream.

    `speed` controls pacing: `None` or `0` replays as fast as the CPU allows
    (the default, for tests and backtests), `1.0` reproduces real time, and
    larger values compress it - `speed=60` runs a two-hour race in two minutes,
    which is the useful setting for watching the dashboard behave.

    `skip_to` and `warp_until` both start you later in a session and are not
    interchangeable. `skip_to` **discards** everything before it; `warp_until`
    **replays it at full speed** and only then starts pacing. Discarding loses
    the state those events carried - jumping into the 2026 Hungarian GP an hour
    in with `skip_to` left most of the field on an unknown tyre compound,
    because the stints had been announced before the skip point. Prefer
    `warp_until` for anything that consumes state; `skip_to` is for tests that
    only care about ordering.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        speed: float | None = None,
        skip_to: timedelta | None = None,
        warp_until: timedelta | None = None,
    ) -> None:
        self.path = Path(path)
        self.speed = speed
        self.skip_to = skip_to
        self.warp_until = warp_until

    async def __aiter__(self) -> AsyncIterator[FeedEvent]:
        loop = asyncio.get_running_loop()
        wall_start = loop.time()
        first_event_time: timedelta | None = None

        for event in read_events(self.path):
            if (
                self.skip_to is not None
                and event.session_time is not None
                and event.session_time < self.skip_to
            ):
                continue

            warping = (
                self.warp_until is not None
                and event.session_time is not None
                and event.session_time < self.warp_until
            )
            if warping:
                # Fast-forward: emit without pacing so all state is applied, then
                # reset the clock so pacing resumes from the warp point.
                first_event_time = None
                wall_start = loop.time()
                await asyncio.sleep(0)
                yield event
                continue

            if self.speed and event.session_time is not None:
                if first_event_time is None:
                    first_event_time = event.session_time
                offset = (event.session_time - first_event_time).total_seconds()
                target = wall_start + offset / self.speed
                delay = target - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
            else:
                # Yield control periodically so an unpaced replay cannot starve
                # the event loop and block the dashboard or the recorder.
                await asyncio.sleep(0)

            yield event
