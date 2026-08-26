"""Timing the path from a packet arriving to a recommendation existing.

`PLAN.md` §6.4 asks for this specifically, and the reasoning is worth repeating:
F1 teams hire for real-time systems, and a latency budget with evidence behind it
is a stronger signal than any accuracy number. An accuracy number can be got by
running a notebook overnight. A p99 cannot.

**What is measured, and whose fault each part is.** The feed already tracked two
things: `lag`, the age of a message when it reaches us, and `decode`, turning a
frame into events. Neither is the number the plan asks for. `lag` includes F1's
own pipeline, the internet, and any skew between their clock and this machine's,
so it is an upper bound on our contribution rather than a measurement of it -
useful context, not a score. What this module times is the part that is entirely
ours:

    fold    applying the event to race state
    decide  fitting the pace model and simulating every candidate strategy
    total   the triggering packet landing -> a recommendation existing

`decide` dominates by two orders of magnitude and is the only one worth
optimising, which is exactly the kind of thing a histogram tells you and a mean
does not.

**A budget is a claim that can fail.** Publishing p50 alone would be close to
meaningless - the interesting question is the tail, because a strategy call that
arrives after the pit window has closed is not a late call, it is no call. The
budget is stated up front, checked against the samples, and reported as passed or
missed. A missed budget stays in the report.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# A lap at a modern circuit is 70-100 seconds and a pit window is a handful of
# laps, so a decision has plenty of room. This is not set by the sport, it is set
# by what the engine should be able to hold while still leaving the screen
# responsive - the simulation runs off the event loop precisely so that ingest
# keeps flowing through it.
DEFAULT_BUDGET_P99 = 2.0

# Bucket edges in milliseconds. Latency here spans microseconds (folding an
# event) to seconds (simulating twelve strategies), so the buckets widen rather
# than dividing the range evenly - a linear histogram would put everything in the
# first bar and tell you nothing.
BUCKETS_MS: tuple[float, ...] = (0, 1, 10, 50, 100, 250, 500, 1000, 2000, 4000)


@dataclass(frozen=True)
class LatencySample:
    """One trip through the pipeline, in seconds."""

    lap: int
    fold: float
    decide: float
    total: float
    lag: float | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


def _percentile(ordered: list[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, int(fraction * len(ordered)))
    return ordered[index]


@dataclass
class LatencyReport:
    """Percentiles and a histogram for one stage, against the budget."""

    name: str
    samples: list[float]
    budget: float | None = None

    @property
    def n(self) -> int:
        return len(self.samples)

    @property
    def p50(self) -> float:
        return _percentile(sorted(self.samples), 0.50)

    @property
    def p95(self) -> float:
        return _percentile(sorted(self.samples), 0.95)

    @property
    def p99(self) -> float:
        return _percentile(sorted(self.samples), 0.99)

    @property
    def worst(self) -> float:
        return max(self.samples) if self.samples else 0.0

    @property
    def over_budget(self) -> int:
        if self.budget is None:
            return 0
        return sum(1 for s in self.samples if s > self.budget)

    @property
    def within_budget(self) -> bool:
        """Judged on p99, not the worst sample.

        One pathological run - a garbage collection, the machine swapping - is
        not a design failure, and a budget that any single outlier can bust is a
        budget nobody will keep honestly.
        """
        return self.budget is None or self.p99 <= self.budget

    def histogram(self, width: int = 40) -> list[str]:
        if not self.samples:
            return []
        counts: list[int] = []
        labels: list[str] = []
        edges = list(BUCKETS_MS) + [float("inf")]
        for low, high in zip(edges, edges[1:], strict=False):
            counts.append(sum(1 for s in self.samples if low <= s * 1000.0 < high))
            labels.append(f"{low:g}+" if high == float("inf") else f"{low:g}-{high:g}")

        peak = max(counts) or 1
        rows = []
        for label, count in zip(labels, counts, strict=False):
            if count == 0:
                continue
            bar = "#" * max(1, round(width * count / peak))
            share = count / len(self.samples)
            rows.append(f"    {label:>11} ms {count:>5} {share:>6.1%}  {bar}")
        return rows

    def __str__(self) -> str:
        lines = [
            f"  {self.name:<8} n={self.n:<5} "
            f"p50 {self.p50 * 1000:>8.2f}ms  p95 {self.p95 * 1000:>8.2f}ms  "
            f"p99 {self.p99 * 1000:>8.2f}ms  max {self.worst * 1000:>8.2f}ms"
        ]
        if self.budget is not None:
            verdict = "within" if self.within_budget else "MISSED"
            lines.append(
                f"           budget p99 <= {self.budget * 1000:.0f}ms: {verdict}"
                f" ({self.over_budget} of {self.n} samples over)"
            )
        return "\n".join(lines)


@dataclass
class LatencyLog:
    """Collects samples during a race and writes them for the report.

    Not committed to git the way predictions are. A latency measurement is not a
    falsifiable claim about the future - nobody needs a timestamp proving when it
    was taken - so the evidentiary machinery around the ledger would be theatre
    here.
    """

    path: Path | None = None
    budget: float = DEFAULT_BUDGET_P99
    samples: list[LatencySample] = field(default_factory=list)
    write_failures: int = 0

    def record(self, sample: LatencySample) -> None:
        self.samples.append(sample)
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(sample.to_json() + "\n")
        except OSError:
            # Never take the race engine down over a timing measurement.
            self.write_failures += 1

    def stage(self, name: str) -> LatencyReport:
        values = [getattr(s, name) for s in self.samples]
        values = [v for v in values if v is not None]
        budget = self.budget if name == "total" else None
        return LatencyReport(name=name, samples=values, budget=budget)

    def summary(self) -> str:
        if not self.samples:
            return "no latency samples recorded"
        total = self.stage("total")
        lines = [
            f"Pipeline latency over {len(self.samples)} decisions",
            "",
            str(self.stage("fold")),
            str(self.stage("decide")),
            str(total),
            "",
            "  packet arrival -> recommendation, distribution:",
            *total.histogram(),
        ]
        lag = [s.lag for s in self.samples if s.lag is not None]
        if lag:
            lines += [
                "",
                f"  feed lag (F1's pipeline + network, not ours): "
                f"mean {statistics.mean(lag):.2f}s  p99 {_percentile(sorted(lag), 0.99):.2f}s",
            ]
        return "\n".join(lines)


def load_samples(path: Path | str) -> list[dict[str, Any]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def report_from(rows: list[dict[str, Any]], budget: float = DEFAULT_BUDGET_P99) -> LatencyLog:
    log = LatencyLog(path=None, budget=budget)
    for row in rows:
        log.samples.append(
            LatencySample(
                lap=int(row.get("lap", 0)),
                fold=float(row.get("fold", 0.0)),
                decide=float(row.get("decide", 0.0)),
                total=float(row.get("total", 0.0)),
                lag=row.get("lag"),
            )
        )
    return log
