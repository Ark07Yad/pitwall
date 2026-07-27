from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path

import pytest


def compress(payload: object) -> str:
    """Encode a payload the way F1 encodes `.z` topics: raw deflate, then base64."""
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    blob = compressor.compress(json.dumps(payload).encode()) + compressor.flush()
    return base64.b64encode(blob).decode()


@pytest.fixture
def recording(tmp_path: Path) -> Path:
    """A small synthetic recording in the exact on-disk format FastF1 writes.

    Two cars, three laps, one pit stop, a safety car, and a race control message
    containing an apostrophe - the last of these is what breaks naive
    quote-substitution parsers.
    """
    ts = "2026-07-26T14:0{}:00.1234567Z"
    lines: list[object] = [
        # Initial snapshot: payload arrives as a JSON *string*, no timestamp.
        [
            "SessionInfo",
            json.dumps(
                {
                    "Name": "Race",
                    "Type": "Race",
                    "Meeting": {"Circuit": {"ShortName": "Hungaroring"}},
                }
            ),
            "",
        ],
        [
            "DriverList",
            {
                "1": {"Tla": "VER", "FullName": "Max Verstappen", "TeamName": "Red Bull"},
                "4": {"Tla": "NOR", "FullName": "Lando Norris", "TeamName": "McLaren"},
            },
            ts.format(0),
        ],
        ["LapCount", {"CurrentLap": 1, "TotalLaps": 70}, ts.format(0)],
        ["TrackStatus", {"Status": "1", "Message": "AllClear"}, ts.format(0)],
        [
            "TimingAppData",
            {
                "Lines": {
                    "1": {"Stints": {"0": {"Compound": "MEDIUM", "New": "true", "TotalLaps": 0}}},
                    "4": {"Stints": {"0": {"Compound": "SOFT", "New": "true", "TotalLaps": 0}}},
                }
            },
            ts.format(0),
        ],
        # Cars take the start. No lap time exists yet.
        [
            "TimingData",
            {
                "Lines": {
                    "1": {"Position": "1", "NumberOfLaps": 1, "GapToLeader": ""},
                    "4": {"Position": "2", "NumberOfLaps": 1, "GapToLeader": "+1.200"},
                }
            },
            ts.format(1),
        ],
        # Lap 1 completed. `NumberOfLaps` is the lap now being *started*, so the
        # accompanying time belongs to the lap before it - matching how the real
        # feed behaved in the 2026 Hungarian GP recording.
        [
            "TimingData",
            {
                "Lines": {
                    "1": {
                        "NumberOfLaps": 2,
                        "LastLapTime": {"Value": "1:18.400"},
                        "Sectors": {"0": {"Value": "24.100"}},
                    },
                    "4": {
                        "NumberOfLaps": 2,
                        "LastLapTime": {"Value": "1:19.600"},
                        "IntervalToPositionAhead": {"Value": "+1.200"},
                    },
                }
            },
            ts.format(1),
        ],
        # Delta: only the changed field is sent.
        ["TimingData", {"Lines": {"1": {"NumberOfLaps": 3}}}, ts.format(2)],
        ["LapCount", {"CurrentLap": 2}, ts.format(2)],
        ["TimingAppData", {"Lines": {"1": {"Stints": {"0": {"TotalLaps": 2}}}}}, ts.format(2)],
        # Pit stop: new stint appended, pit flags toggled.
        ["TimingData", {"Lines": {"4": {"InPit": True, "NumberOfPitStops": 1}}}, ts.format(3)],
        [
            "TimingAppData",
            {
                "Lines": {
                    "4": {"Stints": {"1": {"Compound": "HARD", "New": "true", "TotalLaps": 0}}}
                }
            },
            ts.format(3),
        ],
        ["TimingData", {"Lines": {"4": {"InPit": False, "PitOut": True}}}, ts.format(4)],
        ["TrackStatus", {"Status": "4", "Message": "SCDeployed"}, ts.format(4)],
        # Apostrophe in the payload - fatal to `"'" -> '"'` string substitution.
        [
            "RaceControlMessages",
            {"Messages": {"1": {"Message": "CAR 4 - DRIVER'S PIT ENTRY UNDER INVESTIGATION"}}},
            ts.format(5),
        ],
        ["WeatherData", {"AirTemp": "28.4", "TrackTemp": "44.1", "Rainfall": "0"}, ts.format(5)],
        # Compressed topic.
        ["CarData.z", compress({"Entries": [{"Utc": "2026-07-26T14:05:00Z"}]}), ts.format(5)],
        ["LapCount", {"CurrentLap": 3}, ts.format(6)],
    ]

    path = tmp_path / "session.txt"
    # `repr` reproduces FastF1's writer, which stringifies Python objects.
    path.write_text("\n".join(repr(line) for line in lines), encoding="utf-8")
    return path
