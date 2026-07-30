"""The live engine behind the dashboard.

Folds a feed into race state and, as the race moves on, recomputes a pit
recommendation for the car being advised.

The one structural constraint: **the simulation must not run on the event
loop.** A twelve-option decision is a second or two of solid numpy, and doing
that inline would stall ingest and stop the screen updating exactly when a
strategy call is being made. It runs in a worker thread, and the last completed
answer stays on screen while the next one is computed.

Which feed is underneath is irrelevant here - `SignalRFeed` during a race,
`ReplayFeed` at 60x for a demo. That is the point of the `RaceFeed` abstraction,
and it is why this can be shown working without waiting a fortnight for a race.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pitwall.feed.base import RaceFeed
from pitwall.feed.signalr import SignalRFeed
from pitwall.laps import LapCollector, filter_laps
from pitwall.models import HazardModel, PaceFit, fit_pace
from pitwall.sim import SimConfig, entries_from_state, evaluate_actions, undercut_threats
from pitwall.state.models import RaceState

log = logging.getLogger(__name__)


def _is_gap(value: object) -> bool:
    """Whether a timing field actually holds a gap rather than a lap marker."""
    text = str(value or "").strip()
    return bool(text) and not text.upper().startswith("LAP")


# Recompute at most this often. A decision costs a second or two of CPU, and the
# answer does not move meaningfully between consecutive laps.
MIN_SECONDS_BETWEEN_ADVICE = 8.0


@dataclass
class Advice:
    lap: int
    driver: str
    tla: str
    call: str
    decisive: bool
    expected_position: float
    margin: float
    options: list[dict[str, Any]] = field(default_factory=list)
    threats: list[dict[str, Any]] = field(default_factory=list)
    computed_at: float = 0.0
    refused: str = ""


class Engine:
    """Folds a feed and keeps a current recommendation."""

    def __init__(
        self,
        feed: RaceFeed,
        *,
        hazard: HazardModel | None = None,
        driver: str = "",
        sims: int = 1500,
    ) -> None:
        self.feed = feed
        self.hazard = hazard
        self.requested_driver = driver.upper()
        self.sims = sims

        self.collector = LapCollector()
        self.advice: Advice | None = None
        self.events = 0
        self.started = time.monotonic()

        self._last_advice_at = 0.0
        self._last_advised_lap = -1
        self._busy = False

    @property
    def state(self) -> RaceState:
        return self.collector.state

    async def run(self) -> None:
        """Consume the feed until it ends. Intended as a background task."""
        async for event in self.feed:
            self.collector.apply(event)
            self.events += 1
            await self._maybe_advise()

    async def _maybe_advise(self) -> None:
        state = self.state
        now = time.monotonic()
        if self._busy or state.lap <= 0 or not state.cars:
            return
        if state.lap == self._last_advised_lap:
            return
        if now - self._last_advice_at < MIN_SECONDS_BETWEEN_ADVICE:
            return

        self._busy = True
        self._last_advice_at = now
        self._last_advised_lap = state.lap
        try:
            # Off the event loop: ingest keeps flowing while this runs, so the
            # screen stays live through the seconds a decision takes.
            self.advice = await asyncio.to_thread(self._compute, state.lap)
        except Exception:
            log.exception("advice failed on lap %s", state.lap)
        finally:
            self._busy = False

    def _pick_driver(self, entries: list) -> Any:
        wanted = self.requested_driver
        if wanted:
            for entry in entries:
                if entry.tla.upper() == wanted or entry.driver == wanted:
                    return entry
        return entries[0] if entries else None

    def _compute(self, lap: int) -> Advice | None:
        state = self.state
        clean, _ = filter_laps(self.collector.laps)
        pace: PaceFit | None = fit_pace(clean)

        if pace is None:
            return Advice(
                lap=lap,
                driver="",
                tla=self.requested_driver or "—",
                call="",
                decisive=False,
                expected_position=0.0,
                margin=0.0,
                computed_at=time.time(),
                refused="not enough clean laps to fit a pace model yet",
            )
        if not pace.usable:
            # Early in a race the design is not identified. Publishing a
            # confident number from it is worse than publishing nothing.
            return Advice(
                lap=lap,
                driver="",
                tla=self.requested_driver or "—",
                call="",
                decisive=False,
                expected_position=0.0,
                margin=0.0,
                computed_at=time.time(),
                refused="; ".join(pace.unusable_reasons),
            )

        entries = entries_from_state(state, pace)
        target = self._pick_driver(entries)
        if target is None:
            return None

        total = state.total_laps or lap + 20
        config = SimConfig(n_sims=self.sims)
        recommendation = evaluate_actions(
            entries,
            our_driver=target.driver,
            from_lap=lap,
            total_laps=total,
            circuit=state.circuit,
            pace=pace,
            hazard=self.hazard,
            config=config,
        )
        threats = undercut_threats(
            entries,
            our_driver=target.driver,
            from_lap=lap,
            total_laps=total,
            circuit=state.circuit,
            pace=pace,
            hazard=self.hazard,
            our_pit_lap=recommendation.best.pit_lap,
            config=config,
        )

        return Advice(
            lap=lap,
            driver=target.driver,
            tla=target.tla,
            call=recommendation.best.label,
            decisive=recommendation.decisive,
            expected_position=recommendation.best.mean_position,
            margin=recommendation.margin,
            options=[
                {
                    "label": o.label,
                    "expected": round(o.mean_position, 2),
                    "top3": round(o.p_top3, 3),
                    "points": round(o.p_points, 3),
                }
                for o in recommendation.outcomes[:6]
            ],
            threats=[
                {"tla": t.tla, "gap": round(t.gap, 1), "probability": round(t.probability, 3)}
                for t in threats
            ],
            computed_at=time.time(),
        )

    def snapshot(self) -> dict[str, Any]:
        """Everything the browser needs, as plain JSON."""
        state = self.state
        cars = []
        for car in state.running_order():
            if car.position is None and not car.tla:
                continue
            cars.append(
                {
                    "position": car.position,
                    "tla": car.tla or car.number,
                    "number": car.number,
                    "team": car.team,
                    "compound": car.compound.short,
                    "age": car.tyre_age,
                    "last": round(car.last_lap_time, 3) if car.last_lap_time else None,
                    # `GapToLeader` carries "LAP 37" for the leader - the lap it
                    # is on, not a gap. Showing it raw puts nonsense in the
                    # column; the leader is the reference and has no gap.
                    "gap": car.gap_to_leader if _is_gap(car.gap_to_leader) else None,
                    "interval": car.interval if _is_gap(car.interval) else None,
                    "stops": car.pit_count,
                    "in_pit": car.in_pit,
                    "out": car.retired or car.stopped,
                }
            )

        feed_stats: dict[str, Any] = {"events": self.events}
        if isinstance(self.feed, SignalRFeed):
            summary = self.feed.latency.summary()
            feed_stats.update(
                {
                    "frames": int(summary["frames"]),
                    "decode_p50_ms": round(summary["decode_p50"] * 1000, 2),
                    "decode_p99_ms": round(summary["decode_p99"] * 1000, 2),
                    "lag_p50": round(summary["lag_p50"], 2),
                    "live": True,
                }
            )
        else:
            feed_stats["live"] = False

        advice = None
        if self.advice is not None:
            advice = {
                "lap": self.advice.lap,
                "tla": self.advice.tla,
                "call": self.advice.call,
                "decisive": self.advice.decisive,
                "expected": round(self.advice.expected_position, 2),
                "margin": round(self.advice.margin, 2),
                "options": self.advice.options,
                "threats": self.advice.threats,
                "refused": self.advice.refused,
            }

        return {
            "session": state.session_name,
            "circuit": state.circuit,
            "lap": state.lap,
            "total_laps": state.total_laps,
            "track_status": state.track_status.name,
            "neutralised": state.track_status.is_neutralised,
            "weather": {
                "air": state.weather.air_temp,
                "track": state.weather.track_temp,
                "rain": state.weather.rainfall,
            },
            "cars": cars,
            "advice": advice,
            "feed": feed_stats,
            "computing": self._busy,
        }
