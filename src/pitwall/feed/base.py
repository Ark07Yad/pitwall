"""The feed abstraction.

Every source of race data - a live websocket, a recorded session on disk, a REST
API - is a `RaceFeed` that yields `FeedEvent`s. Nothing downstream of this module
knows or cares which one it is talking to.
"""

from __future__ import annotations

import base64
import json
import zlib
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# Topics published by F1's live timing feed. Suffixed `.z` payloads are
# base64-encoded raw-deflate blobs rather than plain JSON.
TOPICS: tuple[str, ...] = (
    "Heartbeat",
    "CarData.z",
    "Position.z",
    "ExtrapolatedClock",
    "TopThree",
    "RcmSeries",
    "TimingStats",
    "TimingAppData",
    "WeatherData",
    "TrackStatus",
    "DriverList",
    "RaceControlMessages",
    "SessionInfo",
    "SessionData",
    "SessionStatus",
    "LapCount",
    "TimingData",
    "TeamRadio",
    "AudioStreams",
    "ContentStreams",
)


@dataclass(frozen=True, slots=True)
class FeedEvent:
    """One message from the feed.

    `topic` is always the logical name with any `.z` suffix stripped - consumers
    see `CarData`, never `CarData.z`, and `data` is already decompressed.
    """

    topic: str
    data: Any
    timestamp: datetime | None = None
    session_time: timedelta | None = None
    raw: str | None = field(default=None, repr=False)

    @property
    def is_snapshot(self) -> bool:
        """True for the initial full-state dump sent on subscribe.

        The feed opens with a complete picture, then sends deltas. Joining a race
        already in progress means the snapshot is the only place some state
        appears, so it must not be skipped.
        """
        return self.timestamp is None


def inflate(payload: str) -> Any:
    """Decode a `.z` topic payload: base64 then raw deflate (no zlib header)."""
    return json.loads(zlib.decompress(base64.b64decode(payload), -zlib.MAX_WBITS))


class RaceFeed(ABC):
    """A source of race events.

    Implementations must be async-iterable and should be usable as async context
    managers so that sockets and file handles get closed on the way out.
    """

    @abstractmethod
    def __aiter__(self) -> AsyncIterator[FeedEvent]: ...

    async def __aenter__(self) -> RaceFeed:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:  # noqa: B027 - optional hook, not every feed holds resources
        """Release any resources. Safe to call more than once."""
