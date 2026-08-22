from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from pitwall.dashboard.engine import Engine, _is_gap
from pitwall.feed.replay import ReplayFeed
from pitwall.laps.records import LapCollector

fastapi = pytest.importorskip("fastapi", reason="dashboard extra not installed")
from fastapi.testclient import TestClient  # noqa: E402

from pitwall.dashboard.server import build_app  # noqa: E402


# -- warp vs skip ------------------------------------------------------


async def collect(feed: ReplayFeed) -> LapCollector:
    collector = LapCollector()
    async for event in feed:
        collector.apply(event)
    return collector


async def test_warp_preserves_state_that_skip_discards(recording: Path):
    """Regression: jumping into a race must not lose what already happened.

    `skip_to` drops earlier events, so state they carried - the driver list,
    stints, tyre compounds - never arrives. On the real Hungary recording that
    left the whole field on an unknown compound and the strategy engine then
    reasoned from tyres it could not see. `warp_until` replays them at full
    speed instead, and only then starts pacing.
    """
    late = timedelta(seconds=200)

    skipped = await collect(ReplayFeed(recording, skip_to=late))
    warped = await collect(ReplayFeed(recording, warp_until=late))

    # Cars still appear under `skip_to` - TimingData creates them lazily - but
    # what the earlier events carried is gone: no driver names, no stints, so no
    # tyre compounds. That is the failure mode, and it looks like working
    # software. (The untimed snapshot survives either way, so the circuit does.)
    assert not any(car.tla for car in skipped.state.cars.values())
    assert not any(car.stints for car in skipped.state.cars.values())

    assert all(car.tla for car in warped.state.cars.values())
    assert warped.state.circuit == "Hungaroring"
    assert any(car.stints for car in warped.state.cars.values())


async def test_warp_still_yields_every_event(recording: Path):
    full = await collect(ReplayFeed(recording))
    warped = await collect(ReplayFeed(recording, warp_until=timedelta(seconds=200)))
    assert warped.state.events_applied == full.state.events_applied


# -- gap formatting ----------------------------------------------------


@pytest.mark.parametrize("value", ["+1.234", "2L", "+12.0"])
def test_real_gaps_are_shown(value):
    assert _is_gap(value)


@pytest.mark.parametrize("value", ["LAP 37", "lap 5", "", None])
def test_lap_markers_and_blanks_are_not_gaps(value):
    """The leader's GapToLeader carries the lap it is on, not a deficit.
    Rendering it raw puts "LAP 37" in the gap column."""
    assert not _is_gap(value)


# -- engine ------------------------------------------------------------


async def test_snapshot_has_everything_the_page_needs(recording: Path):
    engine = Engine(ReplayFeed(recording))
    await engine.run()
    snapshot = engine.snapshot()

    assert snapshot["circuit"] == "Hungaroring"
    assert snapshot["lap"] == 3
    assert snapshot["cars"]
    assert {"position", "tla", "compound", "age", "stops"} <= set(snapshot["cars"][0])
    assert snapshot["feed"]["live"] is False
    assert json.dumps(snapshot), "the snapshot must be JSON-serialisable"


async def test_engine_refuses_advice_it_cannot_stand_behind(recording: Path):
    """Three laps is nowhere near enough to fit a pace model. The engine must say
    so rather than publish a number."""
    engine = Engine(ReplayFeed(recording))
    await engine.run()
    advice = engine._compute(engine.state.lap)

    assert advice is not None
    assert advice.refused
    assert not advice.call


def test_driver_selection_falls_back_to_the_leader():
    from pitwall.sim import CarEntry

    entries = [
        CarEntry(driver="1", tla="NOR", base_pace=0.0),
        CarEntry(driver="3", tla="VER", base_pace=0.5),
    ]
    engine = Engine(ReplayFeed("unused"))

    assert engine._pick_driver(entries).tla == "NOR"
    engine.requested_driver = "VER"
    assert engine._pick_driver(entries).tla == "VER"
    engine.requested_driver = "NOBODY"
    assert engine._pick_driver(entries).tla == "NOR", "an unknown TLA falls back"


# -- server ------------------------------------------------------------


@pytest.fixture
def client(recording: Path):
    app = build_app(Engine(ReplayFeed(recording)), push_interval=0.05)
    with TestClient(app) as running:
        yield running


def test_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Pitwall" in response.text


def test_state_endpoint_returns_json(client):
    payload = client.get("/api/state").json()
    assert "cars" in payload
    assert "advice" in payload
    assert "feed" in payload


def test_websocket_pushes_snapshots(client):
    """Regression: `from __future__ import annotations` plus a function-local
    fastapi import left FastAPI unable to resolve `socket: WebSocket`. It
    silently treated it as a query parameter and rejected every upgrade with a
    403 that looked nothing like an import problem."""
    with client.websocket_connect("/ws") as socket:
        first = socket.receive_json()
        assert "cars" in first
        second = socket.receive_json()
        assert "lap" in second


def test_driver_change_from_the_browser_is_applied(recording: Path):
    engine = Engine(ReplayFeed(recording))
    app = build_app(engine, push_interval=0.05)
    with TestClient(app) as running, running.websocket_connect("/ws") as socket:
        socket.receive_json()
        socket.send_json({"driver": "ver"})
        for _ in range(5):
            socket.receive_json()
            if engine.requested_driver == "VER":
                break

    assert engine.requested_driver == "VER"


# -- the live prediction ledger ----------------------------------------
#
# The dashboard used to compute a recommendation and then discard it into a
# display object, so a live race produced a screen and no track record - the one
# artifact the project exists to produce. These cover the wiring and, more
# importantly, the guards that keep the ledger meaningful.

import subprocess  # noqa: E402
from dataclasses import dataclass  # noqa: E402

from pitwall.ledger import PredictionLog  # noqa: E402
from pitwall.state.models import RaceState  # noqa: E402


@dataclass
class FakeCompound:
    short: str = "HAR"


@dataclass
class FakeOutcome:
    pit_lap: int = 28
    compound: FakeCompound = None  # type: ignore[assignment]
    mean_position: float = 3.4
    p_top3: float = 0.61
    p_points: float = 0.98
    p_gain: float = 0.4

    def __post_init__(self):
        if self.compound is None:
            self.compound = FakeCompound()


@dataclass
class FakeRecommendation:
    lap: int = 24
    driver: str = "1"
    tla: str = "NOR"
    current_position: int = 3
    margin: float = 0.31
    decisive: bool = True
    n_sims: int = 1500
    best: FakeOutcome = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.best is None:
            self.best = FakeOutcome()


def race_state(**overrides) -> RaceState:
    state = RaceState()
    state.session_name = "Race"
    state.session_type = "Race"
    state.circuit = "Zandvoort"
    state.lap = 24
    state.total_laps = 72
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def engine_with_log(tmp_path, **kwargs) -> Engine:
    log = PredictionLog("2026 Dutch GP", directory=tmp_path, commit=False, repo=tmp_path)
    return Engine(ReplayFeed(tmp_path / "nonexistent.txt"), log=log, **kwargs)


def test_records_a_call_during_a_race(tmp_path):
    engine = engine_with_log(tmp_path)
    engine._record(FakeRecommendation(), race_state())

    assert engine.logged == 1
    entry = engine.log.entries()[0]
    assert entry["tla"] == "NOR"
    assert entry["lap"] == 24
    assert entry["total_laps"] == 72
    assert entry["circuit"] == "Zandvoort"
    # The horizon is what makes the claim falsifiable, so it must be set.
    assert entry["horizon_lap"] == 34


def test_does_not_record_outside_a_race(tmp_path):
    """A dashboard left running through practice must not fill the ledger.

    `total_laps` is the tell: `LapCount` is a race-only topic, so a session that
    never sends one cannot be scored against a classification either.
    """
    engine = engine_with_log(tmp_path)
    engine._record(FakeRecommendation(), race_state(total_laps=0, session_type="Practice"))
    engine._record(FakeRecommendation(), race_state(session_type="Qualifying"))

    assert engine.logged == 0
    assert engine.log.entries() == []


def test_does_not_record_the_same_lap_twice(tmp_path):
    """A mid-race reconnection replays the snapshot and can revisit a lap.

    F1's feed drops after roughly two hours and a Grand Prix is two hours, so
    this is the expected path, not the exceptional one. Two entries for one lap
    would double-count that call in every score drawn from the file.
    """
    engine = engine_with_log(tmp_path)
    engine._record(FakeRecommendation(lap=24), race_state(lap=24))
    engine._record(FakeRecommendation(lap=24), race_state(lap=24))
    engine._record(FakeRecommendation(lap=25), race_state(lap=25))

    assert engine.logged == 2
    assert [e["lap"] for e in engine.log.entries()] == [24, 25]


def test_a_ledger_failure_does_not_stop_the_engine(tmp_path, monkeypatch):
    """The race is not re-runnable, so a broken ledger must cost the calls only."""
    engine = engine_with_log(tmp_path)

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine.log, "record", boom)
    engine._record(FakeRecommendation(), race_state())  # must not raise

    assert engine.logged == 0
    assert engine.log_failures == 1
    # The lap is not marked done, so a later retry can still capture it.
    assert engine._logged_laps == set()


def test_snapshot_reports_the_ledger(tmp_path):
    """A silently disabled ledger during the one race it exists for is the
    expensive failure, so its state is on the screen."""
    engine = engine_with_log(tmp_path)
    assert engine.snapshot()["ledger"]["written"] == 0

    engine._record(FakeRecommendation(), race_state())
    ledger = engine.snapshot()["ledger"]
    assert ledger["written"] == 1
    assert ledger["committing"] is False

    assert Engine(ReplayFeed(tmp_path / "x.txt")).snapshot()["ledger"] is None


def test_live_calls_are_committed_as_they_are_made(tmp_path):
    """The commit timestamp is the whole evidence, so it has to happen per call
    rather than in a batch after the flag."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)

    log = PredictionLog(
        "2026 Dutch GP", directory=tmp_path / "predictions", commit=True, repo=tmp_path
    )
    engine = Engine(ReplayFeed(tmp_path / "x.txt"), log=log)

    engine._record(FakeRecommendation(lap=24), race_state(lap=24))
    engine._record(FakeRecommendation(lap=25), race_state(lap=25))

    assert log.commit_failures == 0
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert count == "2", "one commit per call, not one at the end"
