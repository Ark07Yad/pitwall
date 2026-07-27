"""Clean-lap filtering.

Degradation is a small effect - tenths per lap - buried in a signal full of much
larger ones. A single in-lap is ~20 s slow; a lap behind the safety car is 30 s
slow. Leave either in and the fit describes pit stops and safety cars rather than
tyres. Expect to discard 30-50% of laps; that is the job working, not failing.

Rejections are reported as a set of *reasons* rather than a boolean, because the
breakdown is what tells you whether the filter is behaving. "312 laps excluded"
is not reviewable. "94 in-lap, 88 out-lap, 108 traffic, 22 neutralised" is.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from pitwall.laps.records import LapRecord


class RejectReason(Enum):
    NO_TIME = "no lap time recorded"
    FIRST_LAP = "lap 1 (standing start)"
    IN_LAP = "entered the pits"
    OUT_LAP = "left the pits"
    NEUTRALISED = "safety car, VSC or red flag"
    TRAFFIC = "following within the dirty-air threshold"
    IMPLAUSIBLE = "lap time implausible for a racing lap"
    RETIRED = "car retired or stopped"


@dataclass(frozen=True, slots=True)
class CleanLapConfig:
    # Inside roughly a second of the car ahead, a lap time says more about the
    # wake in front than about the tyres underneath.
    traffic_threshold: float = 2.0
    # Relative to the session's best lap, so it adapts to any circuit rather
    # than hardcoding a number that only makes sense at one of them. A racing
    # lap on worn tyres in traffic is maybe 10-15% off the best; 40% is not a
    # racing lap - it is a cool-down lap, a garage stop, or a formation lap.
    outlier_ratio: float = 1.4
    exclude_first_lap: bool = True
    exclude_traffic: bool = True


@dataclass
class FilterReport:
    total: int = 0
    clean: int = 0
    reasons: Counter[RejectReason] = field(default_factory=Counter)

    @property
    def excluded(self) -> int:
        return self.total - self.clean

    @property
    def clean_fraction(self) -> float:
        return self.clean / self.total if self.total else 0.0

    def __str__(self) -> str:
        lines = [
            f"{self.clean:,} clean of {self.total:,} laps "
            f"({self.clean_fraction:.1%} kept, {self.excluded:,} excluded)"
        ]
        if self.reasons:
            width = max(len(r.value) for r in self.reasons)
            lines.append("")
            for reason, count in self.reasons.most_common():
                lines.append(f"  {reason.value:<{width}}  {count:>5,}")
            lines.append("")
            lines.append("  (a lap may be excluded for more than one reason)")
        return "\n".join(lines)


def session_best(laps: list[LapRecord]) -> float | None:
    """Fastest lap in the set, used as the scale for the plausibility check.

    Taken from laps that were not neutralised or pit-affected, so a field-wide
    safety car period cannot drag the reference slow and let bad laps through.
    """
    candidates = [
        lap.lap_time
        for lap in laps
        if lap.lap_time and not lap.was_neutralised and not (lap.entered_pit or lap.exited_pit)
    ]
    return min(candidates) if candidates else None


def classify(
    lap: LapRecord,
    *,
    best: float | None,
    config: CleanLapConfig | None = None,
) -> frozenset[RejectReason]:
    """Return every reason this lap is unusable. Empty means clean."""
    cfg = config or CleanLapConfig()
    reasons: set[RejectReason] = set()

    if lap.lap_time is None:
        reasons.add(RejectReason.NO_TIME)
    if cfg.exclude_first_lap and lap.lap == 1:
        reasons.add(RejectReason.FIRST_LAP)
    if lap.entered_pit:
        reasons.add(RejectReason.IN_LAP)
    # A zero-age tyre means the set was fitted during this lap, so it is an
    # out-lap even if the pit flag was not sampled while it was set. Deliberately
    # `== 0` and not `<= 1`: age 1 is the first full flying lap of the stint,
    # which is a real racing lap and the most valuable point for pinning down
    # the intercept of the degradation curve. Discarding it would throw away one
    # good lap per stint per car.
    if lap.exited_pit or (lap.stint > 0 and lap.tyre_age == 0):
        reasons.add(RejectReason.OUT_LAP)
    if lap.was_neutralised:
        reasons.add(RejectReason.NEUTRALISED)
    if lap.retired:
        reasons.add(RejectReason.RETIRED)
    if cfg.exclude_traffic and lap.interval is not None and lap.interval < cfg.traffic_threshold:
        reasons.add(RejectReason.TRAFFIC)
    if lap.lap_time is not None and best is not None and lap.lap_time > best * cfg.outlier_ratio:
        reasons.add(RejectReason.IMPLAUSIBLE)

    return frozenset(reasons)


def filter_laps(
    laps: list[LapRecord],
    config: CleanLapConfig | None = None,
) -> tuple[list[LapRecord], FilterReport]:
    """Split laps into those usable for fitting and a report on the rest."""
    cfg = config or CleanLapConfig()
    best = session_best(laps)

    clean: list[LapRecord] = []
    report = FilterReport(total=len(laps))

    for lap in laps:
        reasons = classify(lap, best=best, config=cfg)
        if reasons:
            report.reasons.update(reasons)
        else:
            clean.append(lap)

    report.clean = len(clean)
    return clean, report
