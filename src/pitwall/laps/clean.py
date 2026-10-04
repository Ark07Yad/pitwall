"""Clean-lap filtering.

Degradation is a small effect - tenths per lap - buried in a signal full of much
larger ones. A single in-lap is ~20 s slow; a lap behind the safety car is 30 s
slow. Leave either in and the fit describes pit stops and safety cars rather than
tyres. Expect to discard 30-50% of laps; that is the job working, not failing.

Rejections are reported as a set of *reasons* rather than a boolean, because the
breakdown is what tells you whether the filter is behaving. "312 laps excluded"
is not reviewable. "94 in-lap, 88 out-lap, 108 traffic, 22 neutralised" is.

**A wet phase is a different race, not a slow lap.** Every other reason here
judges a lap on its own. This one judges it against the state of the track: a
lap run before the circuit dried is clean by every individual test and still
cannot share a fit with the laps after it. The pace model subtracts one straight
line in race lap - fuel burn and track evolution - and a drying track falls
several seconds a lap, so eight wet laps at the start bend that line for the
whole afternoon.

That is what happened at the 2026 Bahrain GP in Malaysia. Most of the field ran
laps 1-8 on intermediates, everyone was on slicks by lap 10, and the fit read
-4.3 s/lap at lap 7 and was still at -0.24 at the flag. It was refused on all 48
laps it could be attempted and the engine committed nothing. Fitted on the dry
phase alone it was usable from lap 31. The pooled degradation history has
excluded wet races since 28 August for exactly this reason; the live fit never
got the same treatment.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from pitwall.laps.records import LapRecord
from pitwall.state.models import Compound

# Tyres the pace model has no rates for. A lap on either is never comparable
# with a slick lap, whatever the track is doing.
WET_TYRES = frozenset({Compound.INTERMEDIATE, Compound.WET})


class RejectReason(Enum):
    NO_TIME = "no lap time recorded"
    FIRST_LAP = "lap 1 (standing start)"
    IN_LAP = "entered the pits"
    OUT_LAP = "left the pits"
    NEUTRALISED = "safety car, VSC or red flag"
    TRAFFIC = "following within the dirty-air threshold"
    IMPLAUSIBLE = "lap time implausible for a racing lap"
    RETIRED = "car retired or stopped"
    WET_TYRE = "on intermediate or wet tyres"
    BEFORE_DRY = "run before the track dried"


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
    # Treat a wet phase as a separate race: drop wet-tyre laps, and drop slick
    # laps run before the track last dried. Off, the filter judges every lap on
    # its own, which is what it did before 4 October 2026.
    separate_wet_phase: bool = True
    # Share of the field on wet-weather tyres above which a race lap counts as
    # wet. One car in ten, so a lone gambler on intermediates on a dry track -
    # one of twenty-two - does not move the boundary, and three do. Deliberately
    # low: keeping a damp lap in the fit bends the trend for the rest of the
    # race, while losing a dry one costs a lap of data.
    wet_field_share: float = 0.10
    # Laps to leave out after the field has come off wet-weather tyres. A track
    # does not dry on the lap the last car pits: it goes on drying under slicks
    # for a while, and those laps are still on a different surface.
    #
    # Measured on the four mixed-condition recordings with a dry phase long
    # enough to fit, by how far the race-lap trend moves between the first lap
    # the fit is usable and the last - a contaminated trend relaxes as dry laps
    # dilute the damp ones, a sound one sits still:
    #
    #     margin    Kuala Lumpur 26   Spa 25   Zandvoort 23   Montreal 26
    #        0           0.053        0.022       0.043          0.074
    #        2           0.053        0.009       0.053          0.076
    #        4           0.026        0.006       0.033          0.047
    #        6           0.002        0.006       0.033          0.027
    #        8           0.023        0.005       0.033          0.039
    #
    # Every race is better at 4-8 than at 0-2, and at 6 the Kuala Lumpur trend
    # lands at 0.025-0.033 s/kg against 0.060-0.116 with no margin. Four races
    # support "four to eight"; six is the middle of that and not a measured
    # optimum. It has one independent anchor: race control declared NORMAL GRIP
    # CONDITIONS at Kuala Lumpur on lap 15, six laps after the field left
    # intermediates. Where that message exists it is the better instrument, and
    # reading it is the obvious next step.
    drying_laps: int = 6


@dataclass(frozen=True)
class TrackRegime:
    """Where the current dry phase of a race begins, if the race has been wet."""

    # Race laps on which more than `wet_field_share` of the field ran wet tyres.
    wet_laps: tuple[int, ...] = ()
    # Newest race lap any car has completed.
    latest_lap: int = 0
    # Cars on wet-weather tyres, and cars with a known compound, on that lap.
    wet_now: int = 0
    known_now: int = 0
    # Laps left out after the last wet one, while the surface finishes drying.
    drying_laps: int = 0

    @property
    def was_wet(self) -> bool:
        return bool(self.wet_laps)

    @property
    def slicks_from(self) -> int:
        """First race lap after the field came off wet-weather tyres."""
        return self.wet_laps[-1] + 1 if self.wet_laps else 1

    @property
    def dry_from(self) -> int:
        """First race lap that belongs to the present. One, if it never rained."""
        return self.slicks_from + self.drying_laps if self.wet_laps else 1

    @property
    def currently_wet(self) -> bool:
        return self.was_wet and self.wet_laps[-1] >= self.latest_lap

    @property
    def still_drying(self) -> bool:
        return self.was_wet and not self.currently_wet and self.latest_lap < self.dry_from

    def describe(self) -> str:
        """The state of the track, in the words a refusal should use."""
        if not self.was_wet:
            return "dry throughout"
        if self.currently_wet:
            return (
                f"the track is wet - {self.wet_now} of {self.known_now} cars ran lap "
                f"{self.latest_lap} on intermediate or wet tyres, which the model has no "
                "rates for"
            )
        if self.still_drying:
            return (
                f"the track is still drying - the field came off wet tyres on lap "
                f"{self.slicks_from}, and laps before {self.dry_from} are left out of the fit"
            )
        return (
            f"the track dried on lap {self.dry_from}; laps before it are a different "
            "race and are left out of the fit"
        )


def track_regime(laps: list[LapRecord], config: CleanLapConfig | None = None) -> TrackRegime:
    """Find the wet laps of a race from what the field was running.

    Read off the tyres rather than the weather feed: `Rainfall` says whether it
    is raining at one sensor, and what matters is whether the track is wet
    enough that teams have put wet-weather tyres on. They are the better
    instrument, and the only one that also says when it stopped mattering.
    """
    cfg = config or CleanLapConfig()
    known: Counter[int] = Counter()
    wet: Counter[int] = Counter()
    for lap in laps:
        if lap.compound is Compound.UNKNOWN:
            continue
        known[lap.lap] += 1
        if lap.compound in WET_TYRES:
            wet[lap.lap] += 1

    if not known:
        return TrackRegime()
    latest = max(known)
    return TrackRegime(
        wet_laps=tuple(sorted(n for n in known if wet[n] / known[n] > cfg.wet_field_share)),
        latest_lap=latest,
        wet_now=wet[latest],
        known_now=known[latest],
        drying_laps=cfg.drying_laps,
    )


@dataclass
class FilterReport:
    total: int = 0
    clean: int = 0
    reasons: Counter[RejectReason] = field(default_factory=Counter)
    # What the track was doing, so a caller with no clean laps can say why
    # rather than reporting that it is still waiting for data.
    regime: TrackRegime = field(default_factory=TrackRegime)

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
        if self.regime.was_wet:
            lines.append("")
            lines.append(f"  {self.regime.describe()}")
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
    regime: TrackRegime | None = None,
) -> frozenset[RejectReason]:
    """Return every reason this lap is unusable. Empty means clean.

    `regime` is the one input that is not about this lap: where the race's
    current dry phase began. Without it the wet-phase reasons are not applied.
    """
    cfg = config or CleanLapConfig()
    reasons: set[RejectReason] = set()

    if regime is not None and cfg.separate_wet_phase:
        if lap.compound in WET_TYRES:
            reasons.add(RejectReason.WET_TYRE)
        elif regime.was_wet and lap.lap < regime.dry_from:
            # A slick lap, and a perfectly good one by every other test - run on
            # a track that was still wet enough for the rest of the field to be
            # on intermediates.
            reasons.add(RejectReason.BEFORE_DRY)

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
    regime = track_regime(laps, cfg) if cfg.separate_wet_phase else None

    clean: list[LapRecord] = []
    report = FilterReport(total=len(laps), regime=regime or TrackRegime())

    for lap in laps:
        reasons = classify(lap, best=best, config=cfg, regime=regime)
        if reasons:
            report.reasons.update(reasons)
        else:
            clean.append(lap)

    report.clean = len(clean)
    return clean, report
