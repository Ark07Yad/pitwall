"""Fold a feed event stream into race state.

Design rule, and the reason the backtest can be trusted: state is *only* ever
produced by folding events. Nothing else writes to it - no model, no heuristic,
no dashboard callback. Given the same recording the reducer produces the same
state every time, which is what makes replay-based regression tests meaningful.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pitwall.feed.base import FeedEvent
from pitwall.state.merge import as_mapping, deep_merge
from pitwall.state.models import (
    CarState,
    Compound,
    RaceState,
    Stint,
    TrackStatus,
)

log = logging.getLogger(__name__)

_LAP_TIME = re.compile(r"^(?:(\d+):)?(\d+)(?:\.(\d+))?$")

# Topics folded into raw state but not yet projected. Listed explicitly so an
# genuinely unknown topic still shows up in the logs.
_UNPROJECTED = frozenset(
    {
        "Heartbeat",
        "CarData",
        "Position",
        "ExtrapolatedClock",
        "TopThree",
        "RcmSeries",
        "TimingStats",
        "SessionData",
        "SessionStatus",
        "RaceControlMessages",
        "TeamRadio",
        "AudioStreams",
        "ContentStreams",
        "DriverRaceInfo",
        "LapSeries",
        "PitLaneTimeCollection",
        "ChampionshipPrediction",
        "TyreStintSeries",
        "SessionAssets",
        "WeatherDataSeries",
    }
)


def parse_lap_time(value: Any) -> float | None:
    """Parse `"1:23.456"` or `"23.456"` into seconds. Empty means "not set"."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) or None
    match = _LAP_TIME.match(str(value).strip())
    if not match:
        return None
    minutes, seconds, fraction = match.groups()
    total = int(minutes or 0) * 60 + int(seconds)
    if fraction:
        total += int(fraction) / (10 ** len(fraction))
    return total or None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1")


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


class RaceStateReducer:
    """Maintains `RaceState` by folding events."""

    def __init__(self) -> None:
        self.state = RaceState()
        self._unknown_topics: set[str] = set()

    def apply(self, event: FeedEvent) -> RaceState:
        state = self.state
        state.events_applied += 1
        if event.session_time is not None:
            state.session_time = event.session_time

        if not isinstance(event.data, (dict, list)):
            return state

        # Fold into the raw tree first; projections read from the merged result,
        # never from the delta, so a partial update cannot clobber known state.
        merged = deep_merge(state.raw.get(event.topic), event.data)
        state.raw[event.topic] = merged

        handler = getattr(self, f"_on_{_snake(event.topic)}", None)
        if handler is not None:
            try:
                handler(merged)
            except Exception:
                log.exception("reducer failed on topic %s", event.topic)
        elif event.topic not in _UNPROJECTED and event.topic not in self._unknown_topics:
            self._unknown_topics.add(event.topic)
            log.info("unhandled topic: %s", event.topic)

        return state

    # -- projections -----------------------------------------------------

    def _car(self, number: str) -> CarState:
        car = self.state.cars.get(number)
        if car is None:
            car = CarState(number=number)
            self.state.cars[number] = car
        return car

    def _on_session_info(self, data: dict[str, Any]) -> None:
        meeting = data.get("Meeting") or {}
        self.state.session_name = str(data.get("Name") or "")
        self.state.session_type = str(data.get("Type") or "")
        circuit = (meeting.get("Circuit") or {}).get("ShortName")
        self.state.circuit = str(circuit or meeting.get("Location") or "")

    def _on_lap_count(self, data: dict[str, Any]) -> None:
        if (current := _as_int(data.get("CurrentLap"))) is not None:
            self.state.lap = current
        if (total := _as_int(data.get("TotalLaps"))) is not None:
            self.state.total_laps = total

    def _on_track_status(self, data: dict[str, Any]) -> None:
        try:
            self.state.track_status = TrackStatus(str(data.get("Status", "0")))
        except ValueError:
            self.state.track_status = TrackStatus.UNKNOWN

    def _on_driver_list(self, data: dict[str, Any]) -> None:
        for number, entry in data.items():
            if not number.isdigit() or not isinstance(entry, dict):
                continue
            car = self._car(number)
            car.tla = str(entry.get("Tla") or car.tla)
            car.name = str(entry.get("FullName") or entry.get("BroadcastName") or car.name)
            car.team = str(entry.get("TeamName") or car.team)

    def _on_weather_data(self, data: dict[str, Any]) -> None:
        weather = self.state.weather
        weather.air_temp = _as_float(data.get("AirTemp")) or weather.air_temp
        weather.track_temp = _as_float(data.get("TrackTemp")) or weather.track_temp
        weather.humidity = _as_float(data.get("Humidity")) or weather.humidity
        weather.pressure = _as_float(data.get("Pressure")) or weather.pressure
        weather.wind_speed = _as_float(data.get("WindSpeed")) or weather.wind_speed
        weather.wind_direction = _as_float(data.get("WindDirection")) or weather.wind_direction
        if "Rainfall" in data:
            weather.rainfall = _as_bool(data.get("Rainfall"))

    def _on_timing_data(self, data: dict[str, Any]) -> None:
        for number, line in as_mapping(data.get("Lines")).items():
            if not isinstance(line, dict):
                continue
            car = self._car(number)

            if (position := _as_int(line.get("Position"))) is not None:
                car.position = position
            if (laps := _as_int(line.get("NumberOfLaps"))) is not None:
                car.laps_completed = laps
            if (stops := _as_int(line.get("NumberOfPitStops"))) is not None:
                car.pit_count = stops

            if "GapToLeader" in line:
                car.gap_to_leader = str(line["GapToLeader"]) or None
            if isinstance(interval := line.get("IntervalToPositionAhead"), dict):
                car.interval = str(interval.get("Value") or "") or None
            elif "IntervalToPositionAhead" in line:
                car.interval = str(line["IntervalToPositionAhead"]) or None

            if isinstance(last := line.get("LastLapTime"), dict):
                car.last_lap_time = parse_lap_time(last.get("Value")) or car.last_lap_time
            if isinstance(best := line.get("BestLapTime"), dict):
                car.best_lap_time = parse_lap_time(best.get("Value")) or car.best_lap_time

            for index, sector in as_mapping(line.get("Sectors")).items():
                slot = int(index)
                if not isinstance(sector, dict) or not 0 <= slot < 3:
                    continue
                if (value := parse_lap_time(sector.get("Value"))) is not None:
                    car.sectors[slot] = value

            if "InPit" in line:
                car.in_pit = _as_bool(line["InPit"])
            if "PitOut" in line:
                car.pit_out = _as_bool(line["PitOut"])
            if "Retired" in line:
                car.retired = _as_bool(line["Retired"])
            if "Stopped" in line:
                car.stopped = _as_bool(line["Stopped"])

    def _on_timing_app_data(self, data: dict[str, Any]) -> None:
        for number, line in as_mapping(data.get("Lines")).items():
            if not isinstance(line, dict):
                continue
            car = self._car(number)
            stints = as_mapping(line.get("Stints"))
            if not stints:
                continue

            for index_text, entry in sorted(stints.items(), key=lambda kv: int(kv[0])):
                if not isinstance(entry, dict):
                    continue
                index = int(index_text)
                while len(car.stints) <= index:
                    car.stints.append(Stint())
                stint = car.stints[index]

                if "Compound" in entry:
                    compound = Compound.parse(entry["Compound"])
                    if compound is not Compound.UNKNOWN:
                        stint.compound = compound
                if "New" in entry:
                    stint.is_new = _as_bool(entry["New"])
                if (start := _as_int(entry.get("StartLaps"))) is not None:
                    stint.start_laps = start
                if (total := _as_int(entry.get("TotalLaps"))) is not None:
                    stint.total_laps = total


def _snake(topic: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", topic).lower()
