from __future__ import annotations

from pathlib import Path

import pytest

from pitwall.latency import (
    DEFAULT_BUDGET_P99,
    LatencyLog,
    LatencyReport,
    LatencySample,
    load_samples,
    report_from,
)


def sample(total: float, *, lap: int = 30, decide: float | None = None) -> LatencySample:
    return LatencySample(
        lap=lap, fold=0.00001, decide=total if decide is None else decide, total=total
    )


# -- percentiles and the budget -----------------------------------------


def test_percentiles_describe_the_tail_not_the_middle():
    report = LatencyReport("total", [0.1] * 95 + [3.0] * 5, budget=2.0)
    assert report.p50 == pytest.approx(0.1)
    assert report.p99 == pytest.approx(3.0)


def test_the_budget_is_judged_on_p99_not_the_worst_sample():
    """One pathological run - a garbage collection, the machine swapping - is not
    a design failure, and a budget any single outlier can bust is one nobody
    keeps honestly."""
    report = LatencyReport("total", [0.5] * 999 + [9.0], budget=2.0)
    assert report.worst == 9.0
    assert report.within_budget
    assert report.over_budget == 1


def test_a_missed_budget_says_so():
    report = LatencyReport("total", [3.0] * 50, budget=2.0)
    assert not report.within_budget
    assert report.over_budget == 50
    assert "MISSED" in str(report)


def test_no_budget_no_verdict():
    report = LatencyReport("decide", [0.5, 0.6])
    assert report.within_budget
    assert "budget" not in str(report)


# -- the histogram ------------------------------------------------------


def test_the_histogram_spans_microseconds_to_seconds():
    """Latency here runs from folding an event to simulating twelve strategies.
    Even buckets would put everything in the first bar."""
    report = LatencyReport("total", [0.0005, 0.005, 0.3, 1.4, 3.0])
    rows = report.histogram()
    assert rows
    joined = "\n".join(rows)
    assert "0-1 ms" in joined
    assert "2000-4000 ms" in joined


def test_empty_buckets_are_omitted():
    report = LatencyReport("total", [1.5] * 10)
    rows = report.histogram()
    assert len(rows) == 1
    assert "1000-2000" in rows[0]


def test_no_samples_no_histogram():
    assert LatencyReport("total", []).histogram() == []
    assert LatencyLog().summary() == "no latency samples recorded"


# -- the log ------------------------------------------------------------


def test_samples_round_trip_through_disk(tmp_path):
    path = tmp_path / "latency.jsonl"
    log = LatencyLog(path=path)
    log.record(sample(1.2, lap=30))
    log.record(sample(0.8, lap=31))

    rows = load_samples(path)
    assert len(rows) == 2
    restored = report_from(rows)
    assert restored.stage("total").p50 == pytest.approx(0.8, abs=0.5)


def test_a_write_failure_never_stops_the_race(tmp_path):
    """A timing measurement must not be able to take the engine down."""
    log = LatencyLog(path=tmp_path / "nope" / "x.jsonl")
    log.path = Path("/proc/definitely/not/writable/x.jsonl")
    log.record(sample(1.0))
    assert log.write_failures == 1
    # Still collected in memory.
    assert len(log.samples) == 1


def test_lag_is_reported_separately_from_the_total():
    """Lag measures F1's pipeline and the internet. Folding it into the total
    would produce a number this machine cannot be held to."""
    log = LatencyLog()
    log.record(LatencySample(lap=1, fold=0.001, decide=1.0, total=1.001, lag=0.4))
    text = log.summary()
    assert "not ours" in text
    assert log.stage("total").p50 == pytest.approx(1.001)


def test_the_default_budget_is_stated():
    assert DEFAULT_BUDGET_P99 == 2.0
