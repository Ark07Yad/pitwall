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
    stop: bool = True

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
    engine._record(FakeRecommendation(), race_state(), 72)

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
    engine._record(FakeRecommendation(), race_state(total_laps=0, session_type="Practice"), 42)
    engine._record(FakeRecommendation(), race_state(session_type="Qualifying"), 72)

    assert engine.logged == 0
    assert engine.log.entries() == []


def test_does_not_record_the_same_lap_twice(tmp_path):
    """A mid-race reconnection replays the snapshot and can revisit a lap.

    F1's feed drops after roughly two hours and a Grand Prix is two hours, so
    this is the expected path, not the exceptional one. Two entries for one lap
    would double-count that call in every score drawn from the file.
    """
    engine = engine_with_log(tmp_path)
    engine._record(FakeRecommendation(lap=24), race_state(lap=24), 72)
    engine._record(FakeRecommendation(lap=24), race_state(lap=24), 72)
    engine._record(FakeRecommendation(lap=25), race_state(lap=25), 72)

    assert engine.logged == 2
    assert [e["lap"] for e in engine.log.entries()] == [24, 25]


def test_a_ledger_failure_does_not_stop_the_engine(tmp_path, monkeypatch):
    """The race is not re-runnable, so a broken ledger must cost the calls only."""
    engine = engine_with_log(tmp_path)

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(engine.log, "record", boom)
    engine._record(FakeRecommendation(), race_state(), 72)  # must not raise

    assert engine.logged == 0
    assert engine.log_failures == 1
    # The lap is not marked done, so a later retry can still capture it.
    assert engine._logged_laps == set()


def test_snapshot_reports_the_ledger(tmp_path):
    """A silently disabled ledger during the one race it exists for is the
    expensive failure, so its state is on the screen."""
    engine = engine_with_log(tmp_path)
    assert engine.snapshot()["ledger"]["written"] == 0

    engine._record(FakeRecommendation(), race_state(), 72)
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

    engine._record(FakeRecommendation(lap=24), race_state(lap=24), 72)
    engine._record(FakeRecommendation(lap=25), race_state(lap=25), 72)

    assert log.commit_failures == 0
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert count == "2", "one commit per call, not one at the end"


def test_a_stay_out_call_is_logged_as_one(tmp_path):
    """ "Pit on the last lap" and "do not pit again" share a lap number and are
    opposite calls. The ledger has to tell them apart or it grades the wrong
    claim."""
    engine = engine_with_log(tmp_path)
    rec = FakeRecommendation(lap=60)
    rec.best = FakeOutcome(pit_lap=72, stop=False, compound=FakeCompound("MED"))
    engine._record(rec, race_state(lap=60), 72)

    entry = engine.log.entries()[0]
    assert entry["stop"] is False

    from pitwall.ledger import Prediction

    call = Prediction(**{k: v for k, v in entry.items() if k in Prediction.__dataclass_fields__})
    assert call.call == "stay out on MED"


def test_the_engine_forecasts_the_whole_field(tmp_path):
    """One simulation covers every car, which is why a calibration curve is
    affordable at all: ~0.16s for the field against ~37s to recommend per car."""
    from pitwall.ledger import ForecastLog

    flog = ForecastLog("2026 Dutch GP", directory=tmp_path, commit=False)
    engine = Engine(ReplayFeed(tmp_path / "x.txt"), forecasts=flog)

    state = race_state(lap=30)
    for number, tla in (("1", "NOR"), ("4", "VER"), ("16", "LEC")):
        car = state.cars.setdefault(
            number,
            __import__("pitwall.state.models", fromlist=["CarState"]).CarState(number=number),
        )
        car.tla = tla

    class FakeEntry:
        def __init__(self, driver, elapsed):
            self.driver, self.elapsed = driver, elapsed

    entries = [FakeEntry("1", 0.0), FakeEntry("4", 5.0), FakeEntry("16", 9.0)]

    import numpy as np

    class FakeResult:
        drivers = ["1", "4", "16"]
        tlas = ["NOR", "VER", "LEC"]
        positions = np.array([[1, 2, 3]] * 100)
        retired = np.zeros((100, 3), dtype=bool)

    import pitwall.dashboard.engine as module

    original = module.simulate
    module.simulate = lambda *a, **k: FakeResult()
    try:
        engine._forecast(entries, state, SimConfigStub(), state.total_laps or 72)
    finally:
        module.simulate = original

    rows = flog.entries()
    assert len(rows) == 3, "one row per car, from a single simulation"
    assert {r["tla"] for r in rows} == {"NOR", "VER", "LEC"}
    leader = next(r for r in rows if r["tla"] == "NOR")
    assert leader["p_win"] == 1.0
    assert leader["total_laps"] == 72


class SimConfigStub:
    n_sims = 100


def test_forecasts_only_during_a_race(tmp_path):
    from pitwall.ledger import ForecastLog

    flog = ForecastLog("GP", directory=tmp_path, commit=False)
    engine = Engine(ReplayFeed(tmp_path / "x.txt"), forecasts=flog)
    engine._forecast([], race_state(total_laps=0, session_type="Practice"), SimConfigStub(), 42)
    assert flog.entries() == []


# -- the latency controller ---------------------------------------------
#
# Measured on the Dutch GP recording: at a fixed 1,500 simulations the engine ran
# p50 1.25s and p99 3.22s against a 2s budget, missing it on 13 of 49 decisions.
# PLAN.md §10 names reducing N adaptively as the mitigation.


def engine_with_latency(tmp_path, sims=1500):
    from pitwall.latency import LatencyLog

    return Engine(ReplayFeed(tmp_path / "x.txt"), sims=sims, latency=LatencyLog(budget=2.0))


def test_it_starts_below_the_ceiling(tmp_path):
    """The first decision is the one the controller cannot correct, and with
    fifty decisions in a race one uncorrected outlier *is* the p99."""
    engine = engine_with_latency(tmp_path, sims=1500)
    assert engine.max_sims == 1500
    assert engine.sims < 1500


def test_a_slow_decision_reduces_the_simulation_count(tmp_path):
    engine = engine_with_latency(tmp_path)
    before = engine.sims
    engine._adapt_sims(4.0)  # double the budget
    assert engine.sims < before


def test_headroom_ramps_back_up_but_never_past_the_ceiling(tmp_path):
    engine = engine_with_latency(tmp_path, sims=1500)
    for _ in range(20):
        engine._adapt_sims(0.05)
    assert engine.sims == 1500, "should climb to the configured count"
    for _ in range(5):
        engine._adapt_sims(0.05)
    assert engine.sims == 1500, "and never past it"


def test_it_will_not_degrade_below_a_usable_sample(tmp_path):
    """Below the floor the margin between two options is sampling error, so the
    honest response is to flag the miss rather than keep cutting."""
    from pitwall.dashboard.engine import MIN_SIMS

    engine = engine_with_latency(tmp_path)
    for _ in range(50):
        engine._adapt_sims(30.0)
    assert engine.sims == MIN_SIMS
    assert engine.sims_floor_hit
    assert engine.snapshot()["feed"]["sims_floor"] is True


def test_damping_stops_it_oscillating(tmp_path):
    """Undamped, one slow lap halves the count and the next doubles it back."""
    engine = engine_with_latency(tmp_path)
    seen = []
    for took in (4.0, 0.05, 4.0, 0.05, 4.0, 0.05):
        engine._adapt_sims(took)
        seen.append(engine.sims)
    swings = [abs(b - a) / a for a, b in zip(seen, seen[1:], strict=False)]
    assert max(swings) < 1.5, f"simulation count is oscillating: {seen}"


def test_no_latency_log_means_no_adaptation(tmp_path):
    engine = Engine(ReplayFeed(tmp_path / "x.txt"), sims=1500)
    before = engine.sims
    engine._adapt_sims(10.0)
    assert engine.sims == before


# -- rehearsing against a live practice session -------------------------


def test_rehearsal_records_from_a_session_that_is_not_a_race(tmp_path):
    """Practice never sends `LapCount`, so the race-only guard means a dashboard
    run through FP2 proves the feed and the reducer and nothing whatever about
    the ledger - which is the part that has never run live. `--rehearse` is the
    only way to drive that path before a race does it for real."""
    engine = engine_with_log(tmp_path, rehearsal=True)
    engine._record(FakeRecommendation(), race_state(total_laps=0, session_type="Practice"), 42)

    assert engine.logged == 1
    assert engine.log.entries()


def test_a_rehearsal_records_the_horizon_it_actually_ran_against(tmp_path):
    """`total_laps` is 0 in practice. Writing that to the file would give every
    row a horizon_lap of 0 - a claim already settled before it was made."""
    engine = engine_with_log(tmp_path, rehearsal=True)
    engine._record(FakeRecommendation(lap=22), race_state(lap=22, total_laps=0), 42)

    row = engine.log.entries()[0]
    assert row["total_laps"] == 42
    assert row["horizon_lap"] > row["lap"]


def test_rehearsal_is_off_by_default(tmp_path):
    """The guard has to stay the default. A flag that has to be remembered to
    stay safe is not a guard."""
    engine = engine_with_log(tmp_path)
    engine._record(FakeRecommendation(), race_state(total_laps=0, session_type="Practice"), 42)
    assert engine.logged == 0


def test_the_rehearse_flag_reaches_the_engine(tmp_path, monkeypatch):
    """The wiring, not the guard: `--rehearse` is worth nothing if the CLI parses
    it and then builds an Engine that still refuses to write."""
    import pitwall.cli as cli
    import pitwall.dashboard as dashboard

    built = {}

    def fake_serve(engine, **kwargs):
        built["rehearsal"] = engine.rehearsal
        built["commit"] = engine.log.commit_enabled
        built["source"] = engine.log.source

    monkeypatch.setattr(dashboard, "serve", fake_serve)
    monkeypatch.chdir(tmp_path)
    recording = tmp_path / "quali.txt"
    recording.write_text("")

    cli.main(
        [
            "dashboard",
            "--replay",
            str(recording),
            "--rehearse",
            "--log-predictions",
            "--session",
            "Italy FP2",
            "--out",
            str(tmp_path / "predictions"),
        ]
    )

    assert built == {
        "rehearsal": True,
        "commit": False,
        "source": "rehearsal of Italy FP2",
    }
