"""Extract completed laps from the event stream.

The reducer maintains *current* state; fitting a degradation curve needs the
opposite - a history of completed laps with the context each was run in. This
module turns the one into the other.

How the feed signals a completed lap, confirmed against the 2026 Hungarian GP
recording: `NumberOfLaps` and `LastLapTime` arrive together in a single
`TimingData` message. `NumberOfLaps` is the lap the car is now *starting*, so the
accompanying time belongs to lap `NumberOfLaps - 1`.

    {'NumberOfLaps': 2, 'LastLapTime': '1:26.103'}   # lap 1 took 86.103s
    {'NumberOfLaps': 3, 'LastLapTime': '1:25.307'}   # lap 2 took 85.307s
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

from pitwall.feed.base import FeedEvent
from pitwall.state.models import Compound, RaceState, TrackStatus
from pitwall.state.reducer import RaceStateReducer, parse_lap_time

_INTERVAL = re.compile(r"^\+?(\d+(?:\.\d+)?)$")


def parse_interval(value: object) -> float | None:
    """Parse a gap like `"+1.325"` into seconds.

    Returns None for values that are not a time gap - `"1L"` for a lapped car,
    `""` for the leader. None means "unknown", never "zero"; treating a lapped
    car's gap as 0.0 would mark it as stuck in traffic on every lap.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or "L" in text.upper():
        return None
    match = _INTERVAL.match(text)
    return float(match.group(1)) if match else None


@dataclass(frozen=True, slots=True)
class LapRecord:
    """One completed lap, with the context needed to judge whether it is usable."""

    driver: str
    tla: str
    team: str
    lap: int
    lap_time: float | None

    compound: Compound
    tyre_age: int
    stint: int

    position: int | None
    interval: float | None
    gap_to_leader: str | None

    track_statuses: frozenset[TrackStatus]
    entered_pit: bool
    exited_pit: bool
    retired: bool

    session_time: timedelta | None = None

    @property
    def was_neutralised(self) -> bool:
        return any(s.is_neutralised for s in self.track_statuses)


class LapCollector:
    """Folds events and accumulates `LapRecord`s as laps complete.

    Wraps a reducer rather than sitting beside one, so state is folded exactly
    once and the lap context is read from the same authoritative state.
    """

    def __init__(self) -> None:
        self.reducer = RaceStateReducer()
        self.laps: list[LapRecord] = []

        # Track status changes are rare (21 in a full race), so recording them
        # as a log and remembering each car's position in it is far cheaper than
        # accumulating a per-car set on every one of ~77k events.
        self._status_log: list[TrackStatus] = []
        self._status_mark: dict[str, int] = {}
        self._pit_flags: dict[str, tuple[bool, bool]] = {}
        self._last_lap_seen: dict[str, int] = {}

    @property
    def state(self) -> RaceState:
        return self.reducer.state

    def apply(self, event: FeedEvent) -> list[LapRecord]:
        """Fold one event. Returns any laps completed by it."""
        before = self.state.track_status
        self.reducer.apply(event)
        after = self.state.track_status

        if after != before or not self._status_log:
            self._status_log.append(after)

        # Pit flags are sampled continuously: a car can enter and leave the pits
        # between two lap-completion messages, so reading InPit only at the line
        # would miss the stop entirely.
        for number, car in self.state.cars.items():
            entered, exited = self._pit_flags.get(number, (False, False))
            self._pit_flags[number] = (entered or car.in_pit, exited or car.pit_out)

        if event.topic != "TimingData" or not isinstance(event.data, dict):
            return []
        lines = event.data.get("Lines")
        if not isinstance(lines, dict):
            return []

        completed: list[LapRecord] = []
        for number, line in lines.items():
            if not isinstance(line, dict) or "LastLapTime" not in line:
                continue
            record = self._complete_lap(number, line, event.session_time)
            if record is not None:
                completed.append(record)
                self.laps.append(record)
        return completed

    def _complete_lap(
        self, number: str, line: dict, session_time: timedelta | None
    ) -> LapRecord | None:
        raw = line["LastLapTime"]
        value = raw.get("Value") if isinstance(raw, dict) else raw
        lap_time = parse_lap_time(value)

        car = self.state.cars.get(number)
        if car is None:
            return None

        # `NumberOfLaps` is the lap now starting, so the time is for the one before.
        current = line.get("NumberOfLaps")
        lap_number = (int(current) - 1) if current is not None else car.laps_completed - 1
        if lap_number < 1:
            return None
        if self._last_lap_seen.get(number) == lap_number:
            return None
        self._last_lap_seen[number] = lap_number

        mark = self._status_mark.get(number, max(0, len(self._status_log) - 1))
        statuses = frozenset(self._status_log[mark:]) or frozenset({self.state.track_status})
        self._status_mark[number] = max(0, len(self._status_log) - 1)

        entered, exited = self._pit_flags.get(number, (False, False))
        self._pit_flags[number] = (car.in_pit, car.pit_out)

        return LapRecord(
            driver=number,
            tla=car.tla,
            team=car.team,
            lap=lap_number,
            lap_time=lap_time,
            compound=car.compound,
            tyre_age=car.tyre_age,
            stint=len(car.stints) - 1 if car.stints else 0,
            position=car.position,
            interval=parse_interval(car.interval),
            gap_to_leader=car.gap_to_leader,
            track_statuses=statuses,
            entered_pit=entered,
            exited_pit=exited,
            retired=car.retired or car.stopped,
            session_time=session_time,
        )
