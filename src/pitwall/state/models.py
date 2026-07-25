"""Typed view of the race.

These are projections, not the source of truth. The authoritative state is the
merged raw feed tree in `RaceState.raw`; everything here is derived from it by
`project()`. Keeping the raw tree means a field the projection does not yet
understand is still captured, and adding support for it later is a read-side
change that needs no re-recording.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum


class TrackStatus(Enum):
    UNKNOWN = "0"
    ALL_CLEAR = "1"
    YELLOW = "2"
    GREEN_RESUMED = "3"
    SAFETY_CAR = "4"
    RED = "5"
    VSC = "6"
    VSC_ENDING = "7"

    @property
    def is_neutralised(self) -> bool:
        """True when lap times are not representative of racing pace.

        Laps run under these conditions must be excluded from degradation
        fitting, and a pit stop taken under them costs far less time - both
        matter enormously to the strategy model.
        """
        return self in (TrackStatus.SAFETY_CAR, TrackStatus.VSC, TrackStatus.RED)


class Compound(Enum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, value: object) -> Compound:
        try:
            return cls(str(value).strip().upper())
        except ValueError:
            return cls.UNKNOWN

    @property
    def short(self) -> str:
        """Three-letter code, as used on the timing screens."""
        return {
            Compound.SOFT: "SOF",
            Compound.MEDIUM: "MED",
            Compound.HARD: "HAR",
            Compound.INTERMEDIATE: "INT",
            Compound.WET: "WET",
            Compound.UNKNOWN: "---",
        }[self]


@dataclass(slots=True)
class Stint:
    compound: Compound = Compound.UNKNOWN
    is_new: bool = True
    start_laps: int = 0
    total_laps: int = 0


@dataclass(slots=True)
class CarState:
    number: str
    tla: str = ""
    name: str = ""
    team: str = ""

    position: int | None = None
    gap_to_leader: str | None = None
    interval: str | None = None

    laps_completed: int = 0
    last_lap_time: float | None = None
    best_lap_time: float | None = None
    sectors: list[float | None] = field(default_factory=lambda: [None, None, None])

    stints: list[Stint] = field(default_factory=list)
    pit_count: int = 0
    in_pit: bool = False
    pit_out: bool = False

    retired: bool = False
    stopped: bool = False

    @property
    def current_stint(self) -> Stint | None:
        return self.stints[-1] if self.stints else None

    @property
    def compound(self) -> Compound:
        stint = self.current_stint
        return stint.compound if stint else Compound.UNKNOWN

    @property
    def tyre_age(self) -> int:
        """Laps on the current set, including any laps it carried from practice."""
        stint = self.current_stint
        return stint.total_laps if stint else 0


@dataclass(slots=True)
class Weather:
    air_temp: float | None = None
    track_temp: float | None = None
    humidity: float | None = None
    pressure: float | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    rainfall: bool = False


@dataclass(slots=True)
class RaceState:
    session_name: str = ""
    session_type: str = ""
    circuit: str = ""

    lap: int = 0
    total_laps: int = 0
    track_status: TrackStatus = TrackStatus.UNKNOWN

    cars: dict[str, CarState] = field(default_factory=dict)
    weather: Weather = field(default_factory=Weather)

    session_time: timedelta | None = None
    events_applied: int = 0

    raw: dict[str, object] = field(default_factory=dict)

    @property
    def laps_remaining(self) -> int:
        return max(0, self.total_laps - self.lap)

    def running_order(self) -> list[CarState]:
        """Cars in classified order. Unclassified cars sort to the back."""
        return sorted(
            self.cars.values(),
            key=lambda car: (car.position is None, car.position or 999),
        )

    def car_by_tla(self, tla: str) -> CarState | None:
        target = tla.strip().upper()
        return next((c for c in self.cars.values() if c.tla == target), None)
