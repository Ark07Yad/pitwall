"""The season scorecard: generated, pooled honestly, and never out of date.

The README's scorecard was hand-typed from one race and went three months
stale while four more were recorded. `scripts/scorecard.py` builds it from the
committed ledgers and `reports/results.json`, and the first test here is the
reason that cannot happen again: it regenerates the block and compares.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from pitwall.laps import stop_laps
from pitwall.laps.records import LapRecord
from pitwall.ledger import stop_agreement
from pitwall.state.models import Compound, TrackStatus

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scorecard.py"
spec = importlib.util.spec_from_file_location("scorecard", SCRIPT)
scorecard = importlib.util.module_from_spec(spec)
sys.modules["scorecard"] = scorecard
spec.loader.exec_module(scorecard)


def test_the_readme_scorecard_matches_the_ledgers():
    """Add a ledger or a result without regenerating, and this fails."""
    races, unscored = scorecard.load(ROOT / scorecard.RESULTS, ROOT / scorecard.PREDICTIONS)
    block, _ = scorecard.render(races, unscored)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert scorecard.splice(readme, block) == readme, (
        "README scorecard is out of date: run python scripts/scorecard.py"
    )


def test_every_committed_ledger_is_scored_or_named():
    """A ledger with no result must show up as unscored, not quietly vanish."""
    races, unscored = scorecard.load(ROOT / scorecard.RESULTS, ROOT / scorecard.PREDICTIONS)
    ledgers = {
        p.stem
        for p in (ROOT / "predictions").glob("*.jsonl")
        if not p.stem.endswith(("-forecasts", "-latency"))
    }

    assert {r.ledger for r in races} | set(unscored) == ledgers


# -- the pieces, on data built to a known answer ----------------------------


def forecast(driver: str, position: int, p_top3: float, source: str = "live") -> dict:
    return {
        "driver": driver,
        "lap": 10,
        "position": position,
        "p_win": 0.0,
        "p_top3": p_top3,
        "p_points": 1.0,
        "expected_position": float(position),
        "source": source,
    }


def race(ledger: str, finish: dict, forecasts: list, calls=None, pits=None, round_=1):
    return scorecard.Race(
        round=round_,
        name=ledger,
        ledger=ledger,
        result={
            "finish": finish,
            "pits": pits or {},
            "total_laps": 50,
            "classification": "recording",
        },
        calls=calls or [{"source": "live", "lap": 10, "driver": "1"}],
        forecasts=forecasts,
    )


def test_pooling_does_not_cross_car_numbers_between_races():
    """Car 1 in one race is not car 1 in another. Pooled naively, a confident
    and correct forecast in race A would be graded against car 1's finish in
    race B, and a perfect forecaster would score badly."""
    a = race("a", {"1": 1}, [forecast("1", 1, 1.0)])
    b = race("b", {"1": 9}, [forecast("1", 9, 0.0)])

    pooled = scorecard.pooled_forecasts([a, b])

    assert pooled.n == 2
    assert pooled.brier_top3 == pytest.approx(0.0)


def test_replayed_forecasts_stay_out_of_the_live_pool():
    """The Dutch GP's calls were live but its field forecasts were made later
    from the recording. They are graded in the per-race table and never in the
    live total."""
    live = race("live", {"1": 1}, [forecast("1", 1, 1.0)])
    replayed = race("replayed", {"1": 1}, [forecast("1", 1, 0.0, source="replay of x.txt")])

    block, _ = scorecard.render([live, replayed], [])

    assert "1 forecasts across 1 races" in block
    assert "live calls, replay forecasts" in block


def test_provenance_takes_the_weakest_claim():
    assert scorecard.provenance([{"source": "live"}]) == "live"
    assert scorecard.provenance([{}]) == "live"  # rows from before the field existed
    mixed = [{"source": "live"}, {"source": "backtest of x.txt"}]
    assert scorecard.provenance(mixed) == "backtest"
    assert scorecard.provenance([{"source": "replay of x.txt"}]) == "replay"


def test_a_race_without_lap_data_is_not_graded_on_stops():
    """Austin's recording missed most of the race, so a call there cannot be
    said to have been followed or ignored."""
    gappy = race("gappy", {"1": 1}, [], calls=[{"source": "live", "lap": 10, "decisive": True}])
    gappy.result["pits"] = None

    assert scorecard.stop_tally(gappy) is None


def test_the_stop_tally_counts_decisive_calls_only():
    calls = [
        {"source": "live", "lap": 10, "driver": "1", "decisive": True, "stop": True, "pit_lap": 11},
        {"source": "live", "lap": 10, "driver": "2", "decisive": True, "stop": True, "pit_lap": 12},
        {
            "source": "live",
            "lap": 10,
            "driver": "3",
            "decisive": False,
            "stop": True,
            "pit_lap": 10,
        },
    ]
    r = race("r", {}, [], calls=calls, pits={"1": [12], "3": [10]})

    assert scorecard.stop_tally(r) == (2, 2, 1, 1)


def test_splice_refuses_a_readme_without_markers():
    with pytest.raises(ValueError):
        scorecard.splice("no markers here", "block")


def test_a_result_survives_json():
    """results.json is the committed half of the scorecard; it has to read back."""
    r = race("r", {"1": 1, "44": 2}, [])
    text = json.dumps({"r": {"round": 1, "name": "r", **r.result}})

    assert json.loads(text)["r"]["finish"] == {"1": 1, "44": 2}


# -- stops and agreement ------------------------------------------------------


def lap(n: int, stint: int, entered: bool = False, exited: bool = False) -> LapRecord:
    return LapRecord(
        driver="1",
        tla="AAA",
        team="T",
        lap=n,
        lap_time=90.0,
        compound=Compound.MEDIUM,
        tyre_age=n,
        stint=stint,
        position=1,
        interval=None,
        gap_to_leader="",
        track_statuses=frozenset({TrackStatus.ALL_CLEAR}),
        entered_pit=entered,
        exited_pit=exited,
        retired=False,
    )


def test_a_stop_is_counted_once_on_its_in_lap():
    """The pit flag is set on the in-lap and the out-lap. Counting it found two
    stops for every one, and scored a call made after the stop as followed."""
    laps = [lap(37, 0), lap(38, 0, entered=True), lap(39, 1, entered=True, exited=True), lap(40, 1)]

    assert stop_laps(laps) == {"1": [38]}


def test_a_stop_and_a_red_flag_change_a_lap_apart_stay_two():
    laps = [lap(42, 0, True), lap(43, 1, True, True), lap(44, 2, True, True), lap(45, 2)]

    assert stop_laps(laps) == {"1": [42, 43]}


@pytest.mark.parametrize(
    ("call", "stops", "expected"),
    [
        ({"lap": 10, "stop": True, "pit_lap": 12}, [12], (True, True)),
        ({"lap": 10, "stop": True, "pit_lap": 12}, [20], (True, False)),
        # "Pit on lap 20" at lap 10 is "not yet", not a stop call.
        ({"lap": 10, "stop": True, "pit_lap": 20}, [11], (False, True)),
        ({"lap": 10, "stop": False}, [], (False, False)),
        # A stop before the call is not a response to it.
        ({"lap": 10, "stop": True, "pit_lap": 10}, [9], (True, False)),
    ],
)
def test_stop_agreement(call, stops, expected):
    assert stop_agreement(call, stops, window=3) == expected
