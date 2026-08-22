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
from pitwall.ledger import PredictionLog, prediction_from
from pitwall.models import AttritionModel, HazardModel, PaceFit, PitLossModel, fit_pace
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
    distribution: dict[int, float] = field(default_factory=dict)
    computed_at: float = 0.0
    refused: str = ""


class Engine:
    """Folds a feed and keeps a current recommendation."""

    def __init__(
        self,
        feed: RaceFeed,
        *,
        hazard: HazardModel | None = None,
        attrition: AttritionModel | None = None,
        pit_loss: PitLossModel | None = None,
        driver: str = "",
        sims: int = 1500,
        log: PredictionLog | None = None,
        horizon: int = 10,
    ) -> None:
        self.feed = feed
        self.hazard = hazard
        self.attrition = attrition
        self.pit_loss = pit_loss
        self.requested_driver = driver.upper()
        self.sims = sims
        self.log = log
        self.horizon = horizon

        self.collector = LapCollector()
        self.advice: Advice | None = None
        self.events = 0
        self.started = time.monotonic()

        self._last_advice_at = 0.0
        self._last_advised_lap = -1
        self._busy = False

        self.logged = 0
        self.log_failures = 0
        # Laps already written. `_compute` is gated to one run per lap, but a
        # reconnection mid-race replays the snapshot and can revisit a lap, and
        # a ledger that records the same lap twice is not a track record.
        self._logged_laps: set[int] = set()

        # Where each car started, so the screen can show positions gained
        # rather than only where everyone is now. Captured the first time a car
        # is seen classified, which for a race is the grid.
        self._grid: dict[str, int] = {}
        self._pace: PaceFit | None = None
        self._clean_laps = 0

    @property
    def state(self) -> RaceState:
        return self.collector.state

    async def run(self) -> None:
        """Consume the feed until it ends. Intended as a background task."""
        async for event in self.feed:
            self.collector.apply(event)
            self.events += 1
            for number, car in self.collector.state.cars.items():
                if car.position is not None and number not in self._grid:
                    self._grid[number] = car.position
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
        self._clean_laps = len(clean)
        pace: PaceFit | None = fit_pace(clean)
        self._pace = pace if (pace and pace.usable) else None

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
            attrition=self.attrition,
            pit_loss=self.pit_loss,
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
            attrition=self.attrition,
            pit_loss=self.pit_loss,
            our_pit_lap=recommendation.best.pit_lap,
            config=config,
        )

        self._record(recommendation, state)

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
                    "retire": round(o.p_retire, 3),
                }
                for o in recommendation.outcomes[:6]
            ],
            distribution=recommendation.best.distribution,
            threats=[
                {"tla": t.tla, "gap": round(t.gap, 1), "probability": round(t.probability, 3)}
                for t in threats
            ],
            computed_at=time.time(),
        )

    def _record(self, recommendation: Any, state: RaceState) -> None:
        """Write the call to the ledger and commit it, before the lap it covers.

        This runs inside `_compute`, which is already on a worker thread, so the
        git subprocess cannot stall ingest.

        Three guards keep the ledger honest rather than merely full:

        **A race only.** `total_laps` is set by the `LapCount` topic, which
        practice and qualifying never send, so a dashboard left running through
        FP1 records nothing. `session_type` is checked too where the feed gives
        it.

        **Once per lap.** A mid-race reconnection replays the state snapshot and
        can walk back over a lap already advised. Logging it twice would double-
        count that call in every score computed from the file afterwards.

        **Never fatal.** A prediction that cannot be written must not take the
        race engine down with it; the screen keeps working and the failure is
        surfaced in the snapshot instead.
        """
        if self.log is None:
            return
        if state.total_laps <= 0:
            return
        if state.session_type and state.session_type.lower() != "race":
            return
        if recommendation.lap in self._logged_laps:
            return

        try:
            self.log.record(
                prediction_from(
                    recommendation,
                    session=self.log.session,
                    circuit=state.circuit,
                    total_laps=state.total_laps,
                    horizon=self.horizon,
                )
            )
        except Exception:
            self.log_failures += 1
            log.exception("could not log prediction at lap %s", recommendation.lap)
            return

        self._logged_laps.add(recommendation.lap)
        self.logged += 1

    def _recent_laps(self, limit: int = 12) -> dict[str, list[float]]:
        """Last few clean-ish lap times per car, for the trend sparklines.

        Pit and neutralised laps are dropped: a 105-second in-lap in a series of
        85s laps flattens the sparkline into a single spike and hides the tyre
        trend the chart exists to show.
        """
        recent: dict[str, list[float]] = {}
        for lap in self.collector.laps:
            if lap.lap_time is None or lap.entered_pit or lap.exited_pit:
                continue
            if lap.was_neutralised:
                continue
            recent.setdefault(lap.driver, []).append(round(lap.lap_time, 3))
        return {k: v[-limit:] for k, v in recent.items()}

    def _model_summary(self) -> dict[str, Any] | None:
        """What the pace model currently believes, so the screen can show its
        working rather than only its conclusion."""
        pace = self._pace
        if pace is None:
            return None
        stop = None
        if self.pit_loss is not None:
            circuit = self.state.circuit
            stop = {
                "seconds": round(self.pit_loss.loss(circuit), 2),
                "spread": round(self.pit_loss.spread_for(circuit), 2),
                "fitted": self.pit_loss.known_circuit(circuit),
                "races": self.pit_loss.races_at(circuit),
            }

        return {
            "clean_laps": self._clean_laps,
            "stints": pace.n_stints,
            "pit_loss": stop,
            "trend": round(pace.race_lap_coef, 4),
            "residual": round(pace.residual_std, 3),
            "r2": round(pace.r_squared, 3),
            "degradation": {
                compound.short: round(rate, 4)
                for compound, rate in sorted(pace.degradation.items(), key=lambda kv: -kv[1])
            },
            "warnings": list(pace.warnings),
        }

    def _risk(self) -> dict[str, Any] | None:
        """Safety-car risk over the rest of the race, from the fitted hazard."""
        state = self.state
        if self.hazard is None or not state.total_laps or state.lap <= 0:
            return None
        circuit, lap, total = state.circuit, state.lap, state.total_laps
        windows = {}
        for span in (5, 10, 20):
            end = min(total, lap + span)
            if end > lap:
                windows[str(span)] = round(
                    self.hazard.probability_within(circuit, lap + 1, end, total), 3
                )
        return {
            "circuit_factor": round(self.hazard.circuit_factor.get(circuit, 1.0), 2),
            "known_circuit": self.hazard.known_circuit(circuit),
            "windows": windows,
            "remaining": round(self.hazard.probability_within(circuit, lap + 1, total, total), 3),
        }

    def _ledger_summary(self) -> dict[str, Any] | None:
        """Whether calls are being committed, so the screen can show it.

        A silently disabled ledger during the one race it exists for is the
        expensive failure here - the race is not re-runnable - so this is on the
        dashboard rather than only in a log file.
        """
        if self.log is None:
            return None
        return {
            "path": str(self.log.path),
            "written": self.logged,
            "commits_failed": self.log.commit_failures,
            "write_failures": self.log_failures,
            "committing": self.log.commit_enabled,
        }

    def snapshot(self) -> dict[str, Any]:
        """Everything the browser needs, as plain JSON."""
        state = self.state
        recent = self._recent_laps()

        timed = [c.best_lap_time for c in state.cars.values() if c.best_lap_time]
        session_best = min(timed) if timed else None

        cars = []
        for car in state.running_order():
            if car.position is None and not car.tla:
                continue
            grid = self._grid.get(car.number)
            history = recent.get(car.number, [])
            cars.append(
                {
                    "position": car.position,
                    "tla": car.tla or car.number,
                    "number": car.number,
                    "team": car.team,
                    "compound": car.compound.short,
                    "age": car.tyre_age,
                    "last": round(car.last_lap_time, 3) if car.last_lap_time else None,
                    "best": round(car.best_lap_time, 3) if car.best_lap_time else None,
                    "fastest": bool(
                        car.best_lap_time and session_best and car.best_lap_time <= session_best
                    ),
                    "gap": car.gap_to_leader if _is_gap(car.gap_to_leader) else None,
                    "interval": car.interval if _is_gap(car.interval) else None,
                    "stops": car.pit_count,
                    "in_pit": car.in_pit,
                    "out": car.retired or car.stopped,
                    "gained": (grid - car.position) if (grid and car.position) else 0,
                    "stints": [
                        {"compound": st.compound.short, "laps": st.total_laps}
                        for st in car.stints
                        if st.total_laps > 0 or st is car.stints[-1]
                    ],
                    "trend": history,
                    "delta": (round(history[-1] - min(history), 3) if len(history) >= 3 else None),
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
                "driver": self.advice.driver,
                "call": self.advice.call,
                "decisive": self.advice.decisive,
                "expected": round(self.advice.expected_position, 2),
                "margin": round(self.advice.margin, 2),
                "options": self.advice.options,
                "threats": self.advice.threats,
                "distribution": {str(k): round(v, 4) for k, v in self.advice.distribution.items()},
                "age": round(time.time() - self.advice.computed_at, 1)
                if self.advice.computed_at
                else None,
                "refused": self.advice.refused,
            }

        return {
            "session": state.session_name,
            "circuit": state.circuit,
            "lap": state.lap,
            "total_laps": state.total_laps,
            "progress": round(state.lap / state.total_laps, 4) if state.total_laps else 0.0,
            "track_status": state.track_status.name,
            "neutralised": state.track_status.is_neutralised,
            "weather": {
                "air": state.weather.air_temp,
                "track": state.weather.track_temp,
                "rain": state.weather.rainfall,
            },
            "session_best": round(session_best, 3) if session_best else None,
            "cars": cars,
            "advice": advice,
            "model": self._model_summary(),
            "risk": self._risk(),
            "feed": feed_stats,
            "ledger": self._ledger_summary(),
            "computing": self._busy,
        }
