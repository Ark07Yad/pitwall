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
from datetime import UTC, datetime
from typing import Any

from pitwall.feed.base import RaceFeed
from pitwall.feed.signalr import SignalRFeed
from pitwall.laps import LapCollector, filter_laps
from pitwall.latency import LatencyLog, LatencySample
from pitwall.ledger import Forecast, ForecastLog, PredictionLog, prediction_from
from pitwall.models import (
    AttritionModel,
    DegradationPrior,
    HazardModel,
    PaceFit,
    PitLossModel,
    fit_pace,
    normalise_circuit,
)
from pitwall.sim import (
    SimConfig,
    entries_from_state,
    evaluate_actions,
    simulate,
    undercut_threats,
)
from pitwall.state.models import RaceState

log = logging.getLogger(__name__)


def _is_gap(value: object) -> bool:
    """Whether a timing field actually holds a gap rather than a lap marker."""
    text = str(value or "").strip()
    return bool(text) and not text.upper().startswith("LAP")


# Recompute at most this often. A decision costs a second or two of CPU, and the
# answer does not move meaningfully between consecutive laps.
MIN_SECONDS_BETWEEN_ADVICE = 8.0

# Below this the finishing distribution is too noisy to publish a margin from -
# the difference between two options would be sampling error. If the budget
# cannot be met at this many simulations, the honest response is to say so rather
# than to keep degrading quietly.
MIN_SIMS = 300
# Aim here rather than at the budget itself. Controlling on the last decision
# while being judged on p99 means leaving headroom for the slow ones.
BUDGET_TARGET = 0.65
# Move this fraction of the way to the new estimate each time. Undamped, one slow
# decision halves the simulation count and the next doubles it back.
ADAPT_DAMPING = 0.5
# The first decision is the one the controller cannot correct, because it has no
# measurement yet - and with fifty decisions in a race, one uncorrected outlier
# *is* the p99. So start below the ceiling and let the loop earn its way up,
# rather than spending the budget on the one lap that has no evidence behind it.
WARMUP_SIMS = 600


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
    extrapolated: bool = False


class Engine:
    """Folds a feed and keeps a current recommendation."""

    def __init__(
        self,
        feed: RaceFeed,
        *,
        hazard: HazardModel | None = None,
        attrition: AttritionModel | None = None,
        pit_loss: PitLossModel | None = None,
        degradation: DegradationPrior | None = None,
        driver: str = "",
        sims: int = 1500,
        log: PredictionLog | None = None,
        forecasts: ForecastLog | None = None,
        latency: LatencyLog | None = None,
        horizon: int = 10,
        rehearsal: bool = False,
    ) -> None:
        self.feed = feed
        self.hazard = hazard
        self.attrition = attrition
        self.pit_loss = pit_loss
        self.degradation = degradation
        self.requested_driver = driver.upper()
        # The ceiling. The controller ramps toward it and never past it.
        self.max_sims = sims
        self.sims = min(sims, WARMUP_SIMS)
        self.sims_floor_hit = False
        self.log = log
        self.forecasts = forecasts
        self.latency = latency
        self.horizon = horizon
        # A rehearsal writes to the ledger from a session that is not a race, so
        # the two race-only guards below are relaxed. It is the only way to
        # exercise the write path against a live feed: practice never sends
        # `LapCount`, so a dashboard left running through FP2 otherwise proves
        # the feed and the reducer and nothing at all about the ledger - which is
        # the part that has never run live. The CLI forces `commit=False` and a
        # `source` of "rehearsal of ..." alongside it, so relaxing the guard
        # cannot put a practice call anywhere the real ledger is read from.
        self.rehearsal = rehearsal

        self.collector = LapCollector()
        self.advice: Advice | None = None
        self.events = 0
        self.started = time.monotonic()

        self._last_advice_at = 0.0
        self._last_advised_lap = -1
        self._busy = False

        self.logged = 0
        self.forecast_rows = 0
        self.log_failures = 0
        # Laps already written. `_compute` is gated to one run per lap, but a
        # reconnection mid-race replays the snapshot and can revisit a lap, and
        # a ledger that records the same lap twice is not a track record.
        self._logged_laps: set[int] = set()
        self._forecast_laps: set[int] = set()

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
            # The clock starts when the packet lands, not when the decision
            # begins - the question the budget answers is how stale a published
            # recommendation is, and folding is part of that even though it is
            # microseconds against the simulation's seconds.
            arrived = time.perf_counter()
            self.collector.apply(event)
            fold = time.perf_counter() - arrived
            self.events += 1
            for number, car in self.collector.state.cars.items():
                if car.position is not None and number not in self._grid:
                    self._grid[number] = car.position
            await self._maybe_advise(arrived=arrived, fold=fold, event=event)

    async def _maybe_advise(
        self,
        *,
        arrived: float | None = None,
        fold: float = 0.0,
        event: Any = None,
    ) -> None:
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
        started = time.perf_counter()
        try:
            # Off the event loop: ingest keeps flowing while this runs, so the
            # screen stays live through the seconds a decision takes.
            self.advice = await asyncio.to_thread(self._compute, state.lap)
        except Exception:
            log.exception("advice failed on lap %s", state.lap)
        else:
            self._record_latency(
                state.lap, arrived=arrived, fold=fold, started=started, event=event
            )
        finally:
            self._busy = False

    def _record_latency(
        self,
        lap: int,
        *,
        arrived: float | None,
        fold: float,
        started: float,
        event: Any,
    ) -> None:
        """One trip through the pipeline, timed end to end.

        `lag` is kept separate and never folded into the total: it measures F1's
        pipeline and the internet, not this engine, and adding it would produce a
        flattering-sounding number that this machine cannot be held to.
        """
        if self.latency is None:
            return

        # A refused cycle - no usable pace fit yet - runs no simulation and costs
        # microseconds. Counting those as decisions would put a fifth of the
        # samples in the sub-millisecond bucket and halve the reported median
        # with work that never happened. The budget is about published calls.
        advice = self.advice
        if advice is None or advice.refused or not advice.call:
            return

        finished = time.perf_counter()

        # Lag only means something against a live feed. On a replay the
        # timestamps are days old, so the "lag" is the age of the recording - a
        # spectacular-looking number measuring nothing.
        lag: float | None = None
        stamp = getattr(event, "timestamp", None)
        if stamp is not None and isinstance(self.feed, SignalRFeed):
            try:
                lag = max(0.0, (datetime.now(UTC) - stamp.replace(tzinfo=UTC)).total_seconds())
            except (TypeError, ValueError, AttributeError):
                lag = None
        self._adapt_sims(finished - started)
        self.latency.record(
            LatencySample(
                lap=lap,
                fold=fold,
                decide=finished - started,
                total=(finished - arrived) if arrived is not None else (finished - started),
                lag=lag,
            )
        )

    def _adapt_sims(self, took: float) -> None:
        """Scale the simulation count to hold the latency budget.

        `PLAN.md` §10 names this as the mitigation for the simulation being too
        slow to run live, with the instruction to measure before optimising.
        Measured: at a fixed 1,500 simulations the Dutch GP ran p50 1.25s and p99
        3.22s against a 2s budget, missing it on 13 of 49 decisions.

        Cost is close to linear in the number of simulations, so the correction
        is just a ratio - damped, because controlling on the last decision while
        being judged on the tail otherwise oscillates: one slow lap halves the
        count and the next doubles it straight back.

        It never exceeds the configured count: a budget is not a licence to spend
        more than was asked for.
        """
        if self.latency is None or took <= 0:
            return
        budget = self.latency.budget
        if budget <= 0:
            return

        wanted = self.sims * (budget * BUDGET_TARGET) / took
        wanted = min(wanted, float(self.max_sims))
        adjusted = self.sims + ADAPT_DAMPING * (wanted - self.sims)
        target = int(max(MIN_SIMS, min(self.max_sims, round(adjusted))))

        if target < self.sims:
            log.info("latency %.2fs over budget - simulations %d -> %d", took, self.sims, target)
        self.sims = target
        # Flag rather than hide it: at the floor the budget is being missed by
        # the model being too expensive, not by the controller being slow.
        self.sims_floor_hit = self.sims_floor_hit or (target == MIN_SIMS and took > budget)

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
        pace: PaceFit | None = fit_pace(clean, prior=self.degradation, circuit=state.circuit)
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

        self._record(recommendation, state, total)
        self._forecast(entries, state, config, total)

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
            extrapolated=recommendation.best.extrapolated,
            threats=[
                {"tla": t.tla, "gap": round(t.gap, 1), "probability": round(t.probability, 3)}
                for t in threats
            ],
            computed_at=time.time(),
        )

    def _record(self, recommendation: Any, state: RaceState, total_laps: int) -> None:
        """Write the call to the ledger and commit it, before the lap it covers.

        This runs inside `_compute`, which is already on a worker thread, so the
        git subprocess cannot stall ingest.

        Three guards keep the ledger honest rather than merely full:

        **A race only.** `total_laps` is set by the `LapCount` topic, which
        practice and qualifying never send, so a dashboard left running through
        FP1 records nothing. `session_type` is checked too where the feed gives
        it. Both are lifted by `rehearsal`, which exists precisely to drive this
        path from a practice session - and which the CLI pairs with a forced
        `commit=False` and a "rehearsal of ..." source, so nothing written under
        it can be mistaken for a call made on a race.

        **Once per lap.** A mid-race reconnection replays the state snapshot and
        can walk back over a lap already advised. Logging it twice would double-
        count that call in every score computed from the file afterwards.

        **Never fatal.** A prediction that cannot be written must not take the
        race engine down with it; the screen keeps working and the failure is
        surfaced in the snapshot instead.
        """
        if self.log is None:
            return
        if not self.rehearsal:
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
                    # In a rehearsal this is the synthetic horizon the
                    # simulation actually ran against, not a real race length.
                    # Writing state.total_laps here would put a 0 in the file and
                    # a horizon_lap of 0 with it.
                    total_laps=total_laps,
                    horizon=self.horizon,
                )
            )
        except Exception:
            self.log_failures += 1
            log.exception("could not log prediction at lap %s", recommendation.lap)
            return

        self._logged_laps.add(recommendation.lap)
        self.logged += 1

    def _forecast(
        self, entries: list, state: RaceState, config: SimConfig, total_laps: int
    ) -> None:
        """Log where every car is heading, not just the one being advised.

        One simulation covers the whole field - they are simulated jointly
        anyway - so this costs about a sixth of a second against the ~37 it would
        take to run a full recommendation for each car. That difference is the
        entire reason the calibration curve can exist: fifty leader-only calls
        cannot be calibrated, and a thousand spread across the grid can.

        Cars already out are skipped. "Where will a retired car finish" is not a
        forecast, and scoring it would pad the log with free correct answers.
        """
        if self.forecasts is None:
            return
        if not self.rehearsal:
            if state.total_laps <= 0:
                return
            if state.session_type and state.session_type.lower() != "race":
                return
        if state.lap in self._forecast_laps:
            return

        try:
            result = simulate(
                entries,
                from_lap=state.lap,
                total_laps=total_laps,
                circuit=state.circuit,
                pace=self._pace,
                hazard=self.hazard,
                attrition=self.attrition,
                pit_loss=self.pit_loss,
                config=config,
            )
            order = {
                entry.driver: i + 1
                for i, entry in enumerate(sorted(entries, key=lambda e: e.elapsed))
            }
            rows: list[Forecast] = []
            for index, entry in enumerate(result.drivers):
                column = result.positions[:, index]
                retired = (
                    float(result.retired[:, index].mean()) if result.retired is not None else 0.0
                )
                rows.append(
                    Forecast(
                        session=self.forecasts.session,
                        circuit=state.circuit,
                        lap=state.lap,
                        total_laps=total_laps,
                        driver=entry,
                        tla=result.tlas[index],
                        position=order.get(entry, 0),
                        expected_position=float(column.mean()),
                        p_win=float((column == 1).mean()),
                        p_top3=float((column <= 3).mean()),
                        p_points=float((column <= 10).mean()),
                        p_retire=retired,
                        n_sims=config.n_sims,
                    )
                )
            self.forecast_rows += self.forecasts.record_lap(rows)
        except Exception:
            self.log_failures += 1
            log.exception("could not forecast the field at lap %s", state.lap)
            return

        self._forecast_laps.add(state.lap)

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
                "expected": round(self.pit_loss.expected_loss(circuit), 2),
                "spread": round(self.pit_loss.spread_for(circuit), 2),
                "botch_rate": round(self.pit_loss.botch_rate, 3),
                "fitted": self.pit_loss.known_circuit(circuit),
                "races": self.pit_loss.races_at(circuit),
            }

        prior = None
        if self.degradation is not None:
            circuit = self.state.circuit
            # The factor alone cannot be read: 1.05x from three races and 1.05x
            # from one are the same number and not the same claim, and after the
            # disrupted-race filter several circuits rest on one.
            prior = {
                "factor": round(
                    self.degradation.circuit_factor.get(normalise_circuit(circuit), 1.0), 3
                ),
                "fitted": self.degradation.known_circuit(circuit),
                "races": self.degradation.circuit_races.get(normalise_circuit(circuit), 0),
                "pooled_races": self.degradation.n_races,
            }

        return {
            "clean_laps": self._clean_laps,
            "stints": pace.n_stints,
            "pit_loss": stop,
            "prior": prior,
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
        if self.log is None and self.forecasts is None:
            return None
        if self.log is None:
            return {"forecasts": self.forecast_rows, "committing": self.forecasts.commit_enabled}
        return {
            "path": str(self.log.path),
            "written": self.logged,
            "forecasts": self.forecast_rows,
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

        feed_stats: dict[str, Any] = {
            "events": self.events,
            "sims": self.sims,
            "sims_floor": self.sims_floor_hit,
        }
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
                "extrapolated": self.advice.extrapolated,
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
