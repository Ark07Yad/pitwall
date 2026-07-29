"""Grading recorded predictions against what actually happened.

A log of calls is only worth keeping if it is scored honestly, and honest
scoring needs three things that are easy to skip.

**A proper scoring rule.** Accuracy on "was the call right" is close to
meaningless for probabilistic claims - a model that says 90% and one that says
51% look identical when the event happens. The Brier score is the mean squared
error of a probability against a 0/1 outcome, so it rewards being confident *and*
right and punishes being confident and wrong.

**A baseline.** A Brier score alone is unreadable. Is 0.12 good? It depends
entirely on how hard the question was. The comparison here is against the naive
forecast that everyone finishes where they currently are, which is a genuinely
strong baseline in Formula 1 - track position is sticky - and therefore an
uncomfortable one. Skill below zero means the model is worse than assuming
nothing changes, and that is worth knowing and publishing.

**Calibration, separately from accuracy.** A model can rank drivers perfectly
and still be badly overconfident. Bucketing predictions by stated probability
and comparing against observed frequency answers a different question: when it
says 70%, does it happen seven times in ten?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_BINS: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
# Below this, per-race numbers bounce around too much to read anything into.
MIN_FOR_CONFIDENCE = 10


@dataclass(frozen=True)
class CalibrationBin:
    low: float
    high: float
    n: int
    predicted: float
    observed: float

    @property
    def gap(self) -> float:
        """Positive means overconfident: claimed more often than it happened."""
        return self.predicted - self.observed


@dataclass
class Scorecard:
    n: int = 0
    brier_top3: float = 0.0
    brier_points: float = 0.0
    baseline_top3: float = 0.0
    baseline_points: float = 0.0
    position_error: float = 0.0
    baseline_position_error: float = 0.0
    calibration: list[CalibrationBin] = field(default_factory=list)
    warnings: tuple[str, ...] = field(default=())

    @staticmethod
    def _skill(model: float, baseline: float) -> float:
        """1.0 is perfect, 0.0 matches the baseline, negative is worse than it.

        A perfect baseline makes the ratio undefined, and returning 0.0 there
        would report "matched the baseline" while the model was in fact wrong on
        every call - an error that flatters the model, which is the direction a
        scoring function must never fail in. Any error against a flawless
        baseline is infinitely worse, so that is what gets reported.
        """
        if baseline <= 0:
            return 0.0 if model <= 0 else float("-inf")
        return 1.0 - (model / baseline)

    @property
    def skill_top3(self) -> float:
        return self._skill(self.brier_top3, self.baseline_top3)

    @property
    def skill_points(self) -> float:
        return self._skill(self.brier_points, self.baseline_points)

    @property
    def beats_baseline(self) -> bool:
        return self.skill_top3 > 0 and self.position_error < self.baseline_position_error

    @staticmethod
    def format_skill(value: float) -> str:
        if value == float("-inf"):
            return "worse*"
        return f"{value:+.1%}"

    def __str__(self) -> str:
        if not self.n:
            return "no scored predictions"
        lines = [
            f"{self.n} predictions scored",
            "",
            f"  {'metric':<22} {'model':>8} {'baseline':>10} {'skill':>8}",
            f"  {'Brier (top 3)':<22} {self.brier_top3:>8.4f} "
            f"{self.baseline_top3:>10.4f} {self.format_skill(self.skill_top3):>8}",
            f"  {'Brier (points)':<22} {self.brier_points:>8.4f} "
            f"{self.baseline_points:>10.4f} {self.format_skill(self.skill_points):>8}",
            f"  {'mean position error':<22} {self.position_error:>8.2f} "
            f"{self.baseline_position_error:>10.2f}",
        ]
        if self.calibration:
            lines += ["", "  calibration:", f"  {'band':<12} {'n':>4} {'said':>8} {'happened':>10}"]
            for b in self.calibration:
                lines.append(
                    f"  {f'{b.low:.0%}-{b.high:.0%}':<12} {b.n:>4} "
                    f"{b.predicted:>8.1%} {b.observed:>10.1%}"
                )
        if float("-inf") in (self.skill_top3, self.skill_points):
            lines.append("  * the baseline was flawless here; any model error is worse")
        for warning in self.warnings:
            lines.append(f"  ! {warning}")
        return "\n".join(lines)


def _brier(pairs: list[tuple[float, float]]) -> float:
    if not pairs:
        return 0.0
    return sum((p - o) ** 2 for p, o in pairs) / len(pairs)


def calibration_bins(
    pairs: list[tuple[float, float]], bins: tuple[float, ...] = DEFAULT_BINS
) -> list[CalibrationBin]:
    """Bucket (predicted, outcome) pairs and compare claimed against observed."""
    out: list[CalibrationBin] = []
    for low, high in zip(bins, bins[1:], strict=False):
        # The top band has to include 1.0, or a confident correct call falls
        # out of the reliability diagram entirely.
        inside = [(p, o) for p, o in pairs if low <= p < high or (high == bins[-1] and p == high)]
        if not inside:
            continue
        out.append(
            CalibrationBin(
                low=low,
                high=high,
                n=len(inside),
                predicted=sum(p for p, _ in inside) / len(inside),
                observed=sum(o for _, o in inside) / len(inside),
            )
        )
    return out


def score_predictions(
    predictions: list[dict[str, Any]],
    finishing_positions: dict[str, int],
) -> Scorecard:
    """Grade a prediction log against final classification.

    `finishing_positions` maps driver number to finishing position. Predictions
    for drivers with no recorded finish are skipped rather than guessed at -
    a retirement is not a forecasting error.
    """
    top3: list[tuple[float, float]] = []
    points: list[tuple[float, float]] = []
    base_top3: list[tuple[float, float]] = []
    base_points: list[tuple[float, float]] = []
    errors: list[float] = []
    base_errors: list[float] = []

    for entry in predictions:
        driver = str(entry.get("driver", ""))
        actual = finishing_positions.get(driver)
        if actual is None:
            continue

        # Baseline: nothing changes from here. Sticky track position makes this
        # a genuinely hard benchmark, which is the point of choosing it.
        held = int(entry.get("position") or 0)

        top3.append((float(entry.get("p_top3", 0.0)), 1.0 if actual <= 3 else 0.0))
        points.append((float(entry.get("p_points", 0.0)), 1.0 if actual <= 10 else 0.0))
        base_top3.append((1.0 if held and held <= 3 else 0.0, 1.0 if actual <= 3 else 0.0))
        base_points.append((1.0 if held and held <= 10 else 0.0, 1.0 if actual <= 10 else 0.0))

        errors.append(abs(float(entry.get("expected_position", actual)) - actual))
        if held:
            base_errors.append(abs(held - actual))

    warnings: list[str] = []
    if 0 < len(top3) < MIN_FOR_CONFIDENCE:
        warnings.append(f"only {len(top3)} scored predictions - too few to read anything into")
    skipped = len(predictions) - len(top3)
    if skipped:
        warnings.append(f"{skipped} predictions skipped (driver has no recorded finish)")

    return Scorecard(
        n=len(top3),
        brier_top3=_brier(top3),
        brier_points=_brier(points),
        baseline_top3=_brier(base_top3),
        baseline_points=_brier(base_points),
        position_error=sum(errors) / len(errors) if errors else 0.0,
        baseline_position_error=sum(base_errors) / len(base_errors) if base_errors else 0.0,
        calibration=calibration_bins(top3),
        warnings=tuple(warnings),
    )


def finishing_positions(state: Any) -> dict[str, int]:
    """Final classification from folded race state."""
    return {car.number: car.position for car in state.running_order() if car.position is not None}
