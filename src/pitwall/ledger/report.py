"""Post-race report: what the engine called, and what actually happened.

Generated rather than written, so it costs one command instead of an evening,
and so it cannot quietly skip the races that went badly. A system grading itself
in public every other weekend is the most persuasive thing in this repository,
and it only stays persuasive if the bad weekends appear too.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pitwall.ledger.score import Scorecard, score_predictions


def _verdict(card: Scorecard) -> str:
    if not card.n:
        return "No predictions were scored, so nothing is claimed."
    if card.n < 10:
        return (
            f"Only {card.n} predictions scored — far too few to draw a conclusion "
            "from. Reported for the record, not as evidence."
        )
    if card.beats_baseline:
        return (
            f"Beat the hold-position baseline on both skill "
            f"({Scorecard.format_skill(card.skill_top3)}) "
            f"and mean position error ({card.position_error:.2f} vs "
            f"{card.baseline_position_error:.2f})."
        )
    if card.skill_top3 > 0:
        return (
            f"Better than the baseline on Brier skill "
            f"({Scorecard.format_skill(card.skill_top3)}) but not "
            f"on position error ({card.position_error:.2f} vs "
            f"{card.baseline_position_error:.2f}). A partial result."
        )
    return (
        f"Did not beat the baseline of assuming nothing changes "
        f"(skill {Scorecard.format_skill(card.skill_top3)}). Track position is sticky "
        "and the model "
        "did not add information here."
    )


def race_report(
    predictions: list[dict[str, Any]],
    finishing: dict[str, int],
    *,
    session: str,
    circuit: str,
    tla_by_driver: dict[str, str] | None = None,
    latency: str | None = None,
) -> str:
    """Render a markdown report grading a race's predictions."""
    names = tla_by_driver or {}
    card = score_predictions(predictions, finishing)
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# {session} — {circuit}",
        "",
        f"*Generated {generated} from {len(predictions)} logged predictions.*",
        "",
        "## Verdict",
        "",
        _verdict(card),
        "",
        "## Scores",
        "",
        "| metric | model | baseline | skill |",
        "|---|---|---|---|",
        f"| Brier (top 3) | {card.brier_top3:.4f} | {card.baseline_top3:.4f} "
        f"| {Scorecard.format_skill(card.skill_top3)} |",
        f"| Brier (points) | {card.brier_points:.4f} | {card.baseline_points:.4f} "
        f"| {Scorecard.format_skill(card.skill_points)} |",
        f"| Mean position error | {card.position_error:.2f} "
        f"| {card.baseline_position_error:.2f} | — |",
        "",
        "The baseline forecasts that every car finishes where it currently runs. In Formula 1",
        "that is a strong benchmark, not a straw man — track position is sticky. Negative skill",
        "means the model added nothing over assuming the order holds.",
        "",
    ]

    if card.calibration:
        lines += [
            "## Calibration",
            "",
            "| confidence band | n | said | happened |",
            "|---|---|---|---|",
        ]
        for b in card.calibration:
            lines.append(
                f"| {b.low:.0%}–{b.high:.0%} | {b.n} | {b.predicted:.1%} | {b.observed:.1%} |"
            )
        lines += [
            "",
            "A well-calibrated model matches the last two columns. Consistently saying more",
            "than happens is overconfidence, and it is a separate failure from being wrong.",
            "",
        ]

    if predictions:
        lines += [
            "## Every call",
            "",
            "| lap | driver | call | expected | actual | horizon |",
            "|---|---|---|---|---|---|",
        ]
        for entry in sorted(predictions, key=lambda e: (e.get("lap", 0), e.get("tla", ""))):
            driver = str(entry.get("driver", ""))
            tla = entry.get("tla") or names.get(driver, driver)
            actual = finishing.get(driver)
            if entry.get("stop", True):
                when = entry.get("pit_lap", entry.get("lap", 0))
                call = f"pit lap {when} on {entry.get('compound', '?')}"
            else:
                call = f"stay out on {entry.get('compound', '?')}"
            lines.append(
                f"| {entry.get('lap', '?')} | {tla} | {call} "
                f"| P{float(entry.get('expected_position', 0)):.2f} "
                f"| {'P' + str(actual) if actual else 'DNF'} "
                f"| lap {entry.get('horizon_lap', '?')} |"
            )
        lines.append("")

    if card.warnings:
        lines += ["## Caveats", ""]
        lines += [f"- {w}" for w in card.warnings]
        lines.append("")

    if latency:
        lines += ["## Feed", "", f"```\n{latency}\n```", ""]

    lines += [
        "---",
        "",
        "Every prediction above was committed to this repository before the lap it refers to.",
        "Commit timestamps are the evidence; `git log predictions/` shows them.",
    ]
    return "\n".join(lines)
