"""Append-only log of predictions, committed as they are made.

Anyone can publish a model that looks good in hindsight. The only thing that
distinguishes this from a plausible story is evidence that the call was made
*before* the outcome was known, and git provides exactly that: a prediction
written and committed on lap 24 carries a commit timestamp no later edit can
forge without rewriting history in public.

Three rules keep that guarantee real:

**Append only.** The file is opened in append mode and never rewritten. A
prediction that turns out badly stays in the log; the accuracy report counts it.

**Commit immediately.** Not batched at the end of the race, when the results are
already known. Each prediction is committed as it is made, so the commit
timestamp is an independent witness to when it was written.

**Commit only this file.** Never `git add -A`. A prediction commit that also
sweeps up a source change would let a sceptic argue the model was edited to fit,
and they would be right to.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path("predictions")


@dataclass(frozen=True)
class Prediction:
    """One recorded call, and enough context to grade it later.

    `horizon_lap` states when the claim becomes checkable. Without it a
    prediction is unfalsifiable - "they will finish well" can always be argued
    after the fact - so every entry has to name the lap by which reality will
    have settled the question.
    """

    session: str
    circuit: str
    lap: int
    total_laps: int
    driver: str
    tla: str
    position: int

    pit_lap: int
    compound: str
    expected_position: float
    margin: float
    decisive: bool
    p_top3: float
    p_points: float
    p_gain: float
    n_sims: int

    horizon_lap: int
    # False when the call is to run to the flag on the current tyre. Without
    # this the log cannot tell "pit on the last lap" from "do not pit again",
    # which are opposite calls that happen to share a lap number.
    stop: bool = True
    # True when the call depends on running a tyre older than anything observed
    # on that compound in this race. Recorded so the scorecard can separate
    # calls the evidence supports from calls that rest on extrapolation - they
    # are different claims and grading them together hides which is which.
    extrapolated: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    recorded_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    note: str = ""

    @property
    def call(self) -> str:
        if not self.stop:
            return f"stay out on {self.compound}"
        when = "now" if self.pit_lap <= self.lap else f"lap {self.pit_lap}"
        return f"pit {when} on {self.compound}"

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


class PredictionLog:
    """Writes predictions to a JSONL file and commits each one."""

    def __init__(
        self,
        session: str,
        *,
        directory: Path | str = DEFAULT_DIR,
        commit: bool = True,
        repo: Path | str | None = None,
    ) -> None:
        self.session = session
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / f"{_slug(session)}.jsonl"
        self.commit_enabled = commit
        self.repo = Path(repo) if repo else Path.cwd()
        self.written = 0
        self.commit_failures = 0

    def record(self, prediction: Prediction) -> Prediction:
        """Append a prediction and commit it. Returns what was written."""
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(prediction.to_json() + "\n")
        self.written += 1

        if self.commit_enabled:
            self._commit(prediction)
        return prediction

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def _commit(self, prediction: Prediction) -> None:
        message = (
            f"predict: {prediction.tla} lap {prediction.lap} - {prediction.call}\n\n"
            f"P{prediction.position} now, expected P{prediction.expected_position:.2f} "
            f"({prediction.n_sims:,} sims, margin {prediction.margin:+.2f}).\n"
            f"Checkable by lap {prediction.horizon_lap}."
        )
        try:
            # Stage only the log. Sweeping up source changes in the same commit
            # would let a sceptic argue the model was tuned to fit, and the whole
            # point of this file is that they cannot.
            subprocess.run(
                ["git", "add", "--", str(self.path)],
                cwd=self.repo,
                check=True,
                capture_output=True,
                timeout=20,
            )
            subprocess.run(
                ["git", "commit", "-m", message, "--only", "--", str(self.path)],
                cwd=self.repo,
                check=True,
                capture_output=True,
                timeout=20,
            )
        except (subprocess.SubprocessError, OSError):
            # A failed commit must never take the race engine down with it. The
            # prediction is already on disk; only the timestamp witness is lost.
            self.commit_failures += 1


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text.strip()]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "session"


def prediction_from(
    recommendation: Any,
    *,
    session: str,
    circuit: str,
    total_laps: int,
    horizon: int = 10,
    note: str = "",
) -> Prediction:
    """Build a log entry from a `Recommendation`.

    `horizon` is how many laps ahead the call is claimed to hold for; the
    default of ten is roughly a pit window either side of the recommended stop.
    """
    best = recommendation.best
    return Prediction(
        session=session,
        circuit=circuit,
        lap=recommendation.lap,
        total_laps=total_laps,
        driver=recommendation.driver,
        tla=recommendation.tla,
        position=recommendation.current_position,
        pit_lap=best.pit_lap,
        compound=best.compound.short,
        expected_position=best.mean_position,
        margin=recommendation.margin,
        decisive=recommendation.decisive,
        p_top3=best.p_top3,
        p_points=best.p_points,
        p_gain=best.p_gain,
        n_sims=recommendation.n_sims,
        horizon_lap=min(recommendation.lap + horizon, total_laps),
        stop=best.stop,
        extrapolated=getattr(best, "extrapolated", False),
        note=note,
    )
