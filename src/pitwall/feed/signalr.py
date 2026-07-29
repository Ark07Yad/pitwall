"""Live connection to Formula 1's timing stream.

This is the piece FastF1 declines to build. Its client connects to the same
endpoint and writes raw frames to disk, with the documentation stating plainly
that it "is *not* possible to do real-time processing of the data". That is a
choice about scope, not a limitation of the feed - the frames are perfectly
parseable as they arrive. This module parses them, so the same reducer, models
and simulation that run against a recording also run against a live race.

The protocol, established against the live endpoint rather than from docs (there
are none), is **SignalR Core**, not the classic SignalR many older clients use.
The legacy `/signalr/negotiate` path now answers 401; `/signalrcore` still
accepts an unauthenticated connection:

1. `OPTIONS /signalrcore/negotiate` - yields an `AWSALBCORS` load-balancer
   cookie that every later request must carry.
2. `POST /signalrcore/negotiate?negotiateVersion=1` - returns a
   `connectionToken`. No credentials required.
3. Open `wss://livetiming.formula1.com/signalrcore?id=<token>`.
4. Send the handshake `{"protocol":"json","version":1}` and wait for `{}`.
5. Invoke `Subscribe` with the topic list.

Frames are newline-free JSON delimited by an ASCII record separator (0x1E), and
a single read may contain several. Message types that matter: **3** is the
completion carrying the full state snapshot, **1** is a feed update whose
`arguments` are `[topic, data, timestamp]` - the same triple the recorder writes
to disk, so recorded and live data parse through identical code - and **6** is a
keepalive ping, which arrives roughly every 15 seconds and is the only traffic
outside a session.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import statistics
import time
import urllib.parse
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

import requests
from websockets.asyncio.client import connect

from pitwall.feed.base import TOPICS, FeedEvent, RaceFeed, inflate
from pitwall.feed.replay import parse_timestamp

log = logging.getLogger(__name__)

NEGOTIATE_URL = "https://livetiming.formula1.com/signalrcore/negotiate"
CONNECTION_URL = "wss://livetiming.formula1.com/signalrcore"
RECORD_SEPARATOR = "\x1e"

# F1's endpoint rejects unfamiliar clients; these are what its own apps send.
BASE_HEADERS = {
    "User-agent": "BestHTTP",
    "Accept-Encoding": "gzip, identity",
}

# Pings arrive about every 15s. Three missed in a row means the connection is
# gone even though the socket has not noticed yet - a common failure on long
# sessions, and the reason a silent socket must be treated as a dead one.
SILENCE_TIMEOUT = 60.0


@dataclass
class LatencyStats:
    """Timing from frame arrival to event emitted.

    `lag` is the age of a message when it reaches us, measured against the
    timestamp F1 stamped on it. It therefore includes their pipeline, the
    network, and any skew between their clock and this machine's - so treat it
    as an upper bound on our own contribution, not a measurement of it.
    `decode` is time spent turning a frame into events, which is entirely ours.
    """

    lag_samples: deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    decode_samples: deque[float] = field(default_factory=lambda: deque(maxlen=2000))
    frames: int = 0
    events: int = 0

    def record(self, lag: float | None, decode: float) -> None:
        if lag is not None:
            self.lag_samples.append(lag)
        self.decode_samples.append(decode)

    @staticmethod
    def _percentile(samples: deque[float], fraction: float) -> float:
        if not samples:
            return 0.0
        ordered = sorted(samples)
        index = min(len(ordered) - 1, int(fraction * len(ordered)))
        return ordered[index]

    def summary(self) -> dict[str, float]:
        return {
            "frames": float(self.frames),
            "events": float(self.events),
            "lag_p50": self._percentile(self.lag_samples, 0.50),
            "lag_p99": self._percentile(self.lag_samples, 0.99),
            "decode_p50": self._percentile(self.decode_samples, 0.50),
            "decode_p99": self._percentile(self.decode_samples, 0.99),
        }

    def __str__(self) -> str:
        s = self.summary()
        mean_lag = statistics.mean(self.lag_samples) if self.lag_samples else 0.0
        return (
            f"{int(s['frames']):,} frames -> {int(s['events']):,} events | "
            f"decode p50 {s['decode_p50'] * 1000:.2f}ms p99 {s['decode_p99'] * 1000:.2f}ms | "
            f"feed lag mean {mean_lag:.2f}s p99 {s['lag_p99']:.2f}s"
        )


def _negotiate(session: requests.Session) -> tuple[str, dict[str, str]]:
    """Blocking negotiate. Returns the connection token and headers to reuse."""
    headers = dict(BASE_HEADERS)

    # The OPTIONS call answers 405, which is fine - it is made only to collect
    # the load balancer cookie, without which the websocket upgrade is refused.
    options = session.options(NEGOTIATE_URL, headers=headers, timeout=15)
    cookie = options.cookies.get("AWSALBCORS")
    if cookie:
        headers["Cookie"] = f"AWSALBCORS={cookie}"

    response = session.post(
        NEGOTIATE_URL,
        params={"negotiateVersion": "1"},
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    token = response.json()["connectionToken"]
    return token, headers


class SignalRFeed(RaceFeed):
    """Live timing as an async event stream.

    Interchangeable with `ReplayFeed`: both are a `RaceFeed`, so everything
    downstream is identical whether the race is happening now or happened in
    July. That is what makes it possible to develop this against a recording and
    trust it live.
    """

    def __init__(
        self,
        topics: tuple[str, ...] = TOPICS,
        *,
        reconnect: bool = True,
        max_backoff: float = 30.0,
        silence_timeout: float = SILENCE_TIMEOUT,
        record_to: str | None = None,
    ) -> None:
        self.topics = list(topics)
        self.reconnect = reconnect
        self.max_backoff = max_backoff
        self.silence_timeout = silence_timeout
        self.latency = LatencyStats()

        self._closed = False
        self._record_path = record_to
        self._record_file = None

    async def aclose(self) -> None:
        self._closed = True
        if self._record_file is not None:
            self._record_file.close()
            self._record_file = None

    async def __aiter__(self) -> AsyncIterator[FeedEvent]:
        backoff = 1.0
        if self._record_path and self._record_file is None:
            # Always keep the raw stream. Reconstructing a session is
            # impossible after the fact, and the file costs nothing. Closed in
            # aclose(); it must outlive this scope, so no context manager.
            self._record_file = open(  # noqa: SIM115
                self._record_path, "a", encoding="utf-8"
            )

        while not self._closed:
            try:
                async for event in self._stream_once():
                    backoff = 1.0
                    yield event
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("live feed dropped: %s: %s", type(exc).__name__, exc)

            if self._closed or not self.reconnect:
                break

            log.info("reconnecting in %.0fs", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, self.max_backoff)

    async def _stream_once(self) -> AsyncIterator[FeedEvent]:
        # `requests` is blocking and this runs inside the event loop, so the
        # handshake goes to a worker thread rather than stalling every other
        # task for the duration of two HTTP round trips.
        session = requests.Session()
        token, headers = await asyncio.to_thread(_negotiate, session)

        url = f"{CONNECTION_URL}?{urllib.parse.urlencode({'id': token})}"
        async with connect(url, additional_headers=headers, max_size=None) as ws:
            await ws.send('{"protocol":"json","version":1}' + RECORD_SEPARATOR)
            await asyncio.wait_for(ws.recv(), timeout=15)

            await ws.send(
                json.dumps(
                    {
                        "type": 1,
                        "invocationId": "0",
                        "target": "Subscribe",
                        "arguments": [self.topics],
                    }
                )
                + RECORD_SEPARATOR
            )
            log.info("subscribed to %d topics", len(self.topics))

            while not self._closed:
                raw = await asyncio.wait_for(ws.recv(), timeout=self.silence_timeout)
                received = time.monotonic()
                self.latency.frames += 1

                for event in self._decode(raw):
                    self.latency.events += 1
                    yield event

                self.latency.decode_samples.append(time.monotonic() - received)

    def _decode(self, raw: str | bytes) -> list[FeedEvent]:
        """Turn one websocket frame into events. A frame may hold several."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        if self._record_file is not None:
            self._record_file.write(raw.replace(RECORD_SEPARATOR, "\n"))
            self._record_file.flush()

        events: list[FeedEvent] = []
        for part in raw.split(RECORD_SEPARATOR):
            if not part.strip():
                continue
            try:
                message = json.loads(part)
            except json.JSONDecodeError:
                log.debug("undecodable frame: %.120s", part)
                continue

            kind = message.get("type")
            if kind == 3:
                events.extend(self._from_snapshot(message.get("result") or {}))
            elif kind == 1 and message.get("target") == "feed":
                event = self._from_feed(message.get("arguments") or [])
                if event is not None:
                    events.append(event)
            # type 6 is a keepalive ping and type 7 a close frame; neither
            # carries race data, and pings are the only traffic between
            # sessions, so they must not be mistaken for a dead connection.
        return events

    def _from_snapshot(self, result: dict) -> list[FeedEvent]:
        """The full state dump sent on subscribe.

        Joining a race in progress means this is the only place most state
        appears, so it is expanded into one event per topic rather than skipped.
        """
        events = []
        for topic, data in result.items():
            name, payload = self._normalise(topic, data)
            if payload is not None:
                events.append(FeedEvent(topic=name, data=payload))
        return events

    def _from_feed(self, arguments: list) -> FeedEvent | None:
        if len(arguments) < 2:
            return None
        topic, data = arguments[0], arguments[1]
        stamp = arguments[2] if len(arguments) > 2 else None

        name, payload = self._normalise(str(topic), data)
        if payload is None:
            return None

        timestamp = parse_timestamp(str(stamp)) if stamp else None
        if timestamp is not None:
            lag = (datetime.now(UTC) - timestamp.replace(tzinfo=UTC)).total_seconds()
            self.latency.lag_samples.append(lag)

        return FeedEvent(topic=name, data=payload, timestamp=timestamp)

    @staticmethod
    def _normalise(topic: str, data: object) -> tuple[str, object | None]:
        """Strip the `.z` suffix and inflate the payload behind it."""
        if topic.endswith(".z"):
            if not isinstance(data, str):
                return topic[:-2], None
            try:
                return topic[:-2], inflate(data)
            except Exception:
                log.debug("failed to inflate %s", topic)
                return topic[:-2], None
        return topic, data


async def stream_events(
    topics: tuple[str, ...] = TOPICS, **kwargs: object
) -> AsyncIterator[FeedEvent]:
    """Convenience wrapper that closes the feed on the way out."""
    feed = SignalRFeed(topics, **kwargs)  # type: ignore[arg-type]
    try:
        async for event in feed:
            yield event
    finally:
        with contextlib.suppress(Exception):
            await feed.aclose()
