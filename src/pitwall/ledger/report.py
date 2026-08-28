"""Post-race report: what the engine called, and what actually happened.

Generated rather than written, so it costs one command instead of an evening,
and so it cannot quietly skip the races that went badly. A system grading itself
in public every other weekend is the most persuasive thing in this repository,
and it only stays persuasive if the bad weekends appear too.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pitwall.ledger.score import Scorecard, score_forecasts, score_predictions


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


def _pct(value: float) -> str:
    if value == float("-inf"):
        return "worse"
    return f"{value:+.1%}"


def _reliability_verdict(field: Any) -> str:
    """Say which way the miscalibration runs, rather than only tabulating it."""
    over = [b for b in field.reliability if b.n >= 15 and b.gap > 0.10]
    under = [b for b in field.reliability if b.n >= 15 and b.gap < -0.10]
    if not over and not under:
        return "Claimed and observed track each other across the range."
    parts = []
    if over:
        bands = ", ".join(f"{b.low:.0%}–{b.high:.0%}" for b in over)
        parts.append(f"**overconfident** in the {bands} band(s)")
    if under:
        bands = ", ".join(f"{b.low:.0%}–{b.high:.0%}" for b in under)
        parts.append(f"**underconfident** in the {bands} band(s)")
    return (
        "The model is " + " and ".join(parts) + ". Bands with fewer than fifteen "
        "forecasts are not judged here; they move too much to read."
    )


def _provenance(
    predictions: list[dict[str, Any]],
    forecasts: list[dict[str, Any]] | None,
) -> list[str]:
    """State up front where the graded rows came from.

    A report that grades replayed calls looks exactly like one that grades live
    ones, and the numbers mean different things. Anything not made live is said
    so in the second line of the document rather than a footnote, because the
    headline skill figure is what gets quoted.
    """

    def sources(rows: list[dict[str, Any]] | None) -> list[str]:
        # Rows written before the field existed are live: nothing else could
        # write to the ledger then, and the replay guard has always been there.
        return sorted({str(row.get("source", "live")) for row in rows or []})

    calls, field = sources(predictions), sources(forecasts)
    if calls == ["live"] and field in ([], ["live"]):
        return []

    lines = ["> **Not a live ledger.**"]
    if calls != ["live"]:
        lines.append(f"> Calls: {', '.join(calls)}.")
    if field and field != ["live"]:
        lines.append(f"> Field forecasts: {', '.join(field)}.")
    lines += [
        "> Rows made against a recording that already contains the result are not evidence",
        "> that the call preceded the outcome, whatever they score.",
        "",
    ]
    return lines


def race_report(
    predictions: list[dict[str, Any]],
    finishing: dict[str, int],
    *,
    session: str,
    circuit: str,
    tla_by_driver: dict[str, str] | None = None,
    latency: str | None = None,
    forecasts: list[dict[str, Any]] | None = None,
) -> str:
    """Render a markdown report grading a race's predictions."""
    names = tla_by_driver or {}
    card = score_predictions(predictions, finishing)
    field = score_forecasts(forecasts, finishing) if forecasts else None
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# {session} — {circuit}",
        "",
        f"*Generated {generated} from {len(predictions)} logged predictions.*",
        "",
        *_provenance(predictions, forecasts),
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

    if field is not None and field.n:
        lines += [
            "## Field forecast",
            "",
            f"Alongside each pit call the engine forecasts **every car**, which costs one "
            f"simulation rather than one per car. That is what makes a calibration curve "
            f"possible: {field.n:,} claims across {field.n_cars} cars, against "
            f"{len(predictions)} recommendations concentrated on the car being advised.",
            "",
            "| metric | model | baseline | skill |",
            "|---|---|---|---|",
            f"| Brier (win) | {field.brier_win:.4f} | {field.baseline_win:.4f} "
            f"| {_pct(field.skill_win)} |",
            f"| Brier (top 3) | {field.brier_top3:.4f} | {field.baseline_top3:.4f} "
            f"| {_pct(field.skill_top3)} |",
            f"| Brier (points) | {field.brier_points:.4f} | {field.baseline_points:.4f} "
            f"| {_pct(field.skill_points)} |",
            f"| Mean position error | {field.position_error:.2f} "
            f"| {field.baseline_position_error:.2f} | — |",
            "",
            "### Reliability",
            "",
            "When it says 70%, does it happen seven times in ten?",
            "",
            "| confidence band | n | said | happened |",
            "|---|---|---|---|",
        ]
        for b in field.reliability:
            lines.append(
                f"| {b.low:.0%}–{b.high:.0%} | {b.n} | {b.predicted:.1%} | {b.observed:.1%} |"
            )
        lines += [
            "",
            _reliability_verdict(field),
            "",
        ]

    lines += [
        "---",
        "",
        "Every prediction above was committed to this repository before the lap it refers to.",
        "Commit timestamps are the evidence; `git log predictions/` shows them.",
    ]
    return "\n".join(lines)
