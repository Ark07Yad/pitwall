#!/usr/bin/env python3
"""The season so far, generated from what is committed.

The README's scorecard was a table typed in by hand from one race, the Hungarian
GP, and it stayed there for three months while four more races were recorded
live. The front page undersold the project by most of its evidence - and, being
hand-typed, it could as easily have left out the weekends that went badly. This
builds it from the ledgers instead, every race in them, good and bad.

    python scripts/scorecard.py --results   # after each race: read the recordings
    python scripts/scorecard.py             # rewrite reports/scorecard.md and the README

**Two steps, because the recordings stay on this machine.** They are F1's data,
not ours. `--results` folds each race's recording and keeps only what grading
needs - the final classification and the lap each car entered the pits - in
`reports/results.json`, which is committed. The second step reads nothing else,
so CI can regenerate the README block from committed files and fail when the two
disagree. A scorecard that cannot go stale is the point; tests/test_scorecard.py
is what holds it to that.

**Three kinds of row, never pooled into one number.** A *live* row was written
during the race and committed before the lap it names. A *backtest* was written
afterwards against a recording that already holds the result: leak-free by
construction, but not evidence that the call came first, and stamped as such on
every row. A *replay* is a backtest by another route. Headline figures pool live
rows only; backtests are reported beside them and never added in.

**Rows were made by different versions of the model.** Every ledger row is
stamped with the commit that made it, and the engine changed between races, so a
season total is an average across systems. That is still the honest summary of
"what this project has said in public and how it went", which is the question the
README answers - but it is not a measurement of today's model, and the per-race
rows are there so nobody has to take the total on trust.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pitwall.feed.replay import read_events
from pitwall.laps import LapCollector, stop_laps
from pitwall.latency import DEFAULT_BUDGET_P99, report_from
from pitwall.ledger import finishing_positions, score_forecasts, stop_agreement
from pitwall.ledger.log import _slug

PREDICTIONS = Path("predictions")
RAW = Path("data/raw")
RESULTS = Path("reports/results.json")
REPORT = Path("reports/scorecard.md")
README = Path("README.md")
CALENDAR = Path("scripts/race_calendar.json")
START, END = "<!-- scorecard:start -->", "<!-- scorecard:end -->"
SEASON = 2026
WINDOW = 3

# Ledger -> recording, for every scored race. Live ledgers are named after the
# session and say nothing about which file holds the race, so this has to be
# written down; from round 20 the race calendar names both and fills it in.
RACES: list[tuple[int, str, str, str]] = [
    (11, "Hungarian GP", "2026-hungarian-gp", "2026-hungary-race.txt"),
    (12, "Dutch GP", "2026-dutch-gp", "2026-netherlands-race.txt"),
    (13, "Italian GP", "2026-italian-gp-backtest", "2026-italy-race.txt"),
    (14, "Spanish GP", "2026-spanish-gp-backtest", "2026-r14-archive.txt"),
    (15, "Azerbaijan GP", "2026-azerbaijan-gp", "2026-baku-race.txt"),
    (16, "Bahrain GP (Kuala Lumpur)", "2026-bahrain-gp-in-malaysia-backtest", "2026-r16-race.txt"),
    (17, "Singapore GP", "2026-singapore-gp-backtest", "2026-singapore-archive.txt"),
    (18, "United States GP", "2026-united-states-gp", "2026-austin-race.txt"),
    (19, "Mexico City GP", "2026-mexico-city-gp", "2026-mexico-city-race.txt"),
]


def manifest(calendar: Path = CALENDAR) -> list[tuple[int, str, str, str]]:
    """Every race to score: the list above, then the calendar's later rounds.

    A calendar race is assumed recorded live, which is what the armer does. One
    rebuilt from the archive instead needs a line above naming its backtest.
    """
    races = list(RACES)
    last = max(r[0] for r in races)
    if calendar.exists():
        for entry in json.loads(calendar.read_text()):
            if entry["round"] > last:
                name = entry["name"].replace("Grand Prix", "GP")
                ledger, recording = _slug(entry["session"]), entry["slug"] + ".txt"
                races.append((entry["round"], name, ledger, recording))
    return races


# -- step one: results from recordings ---------------------------------------


def read_result(recording: Path) -> dict[str, Any]:
    """Classification and pit laps, folded out of one recording."""
    collector = LapCollector()
    for event in read_events(recording):
        collector.apply(event)
    state = collector.state
    seen = {lap.lap for lap in collector.laps}
    return {
        "recording": recording.name,
        "laps": state.lap,
        "total_laps": state.total_laps,
        # Every lap, not the last one: Austin's recording woke for the final laps
        # and ended on 56 of 56 with most of the race missing in between. The
        # final lap never closes into a record, so a full race shows N - 1.
        "complete": state.total_laps > 0 and seen >= set(range(2, state.total_laps)),
        "laps_seen": len(seen),
        "finish": finishing_positions(state),
        "pits": dict(sorted(stop_laps(collector.laps).items())),
    }


def classification_from_f1(round_: int) -> dict[str, int] | None:
    """F1's published result, for a race whose recording stopped early.

    Austin is the case: the Mac slept through most of it and the recording has
    lap times for 11 of 56 laps. It woke for the flag, so folding it does give
    the right order - checked, it matches F1's result car for car - but that was
    luck, and a recording that ends early would give the order on its last lap.
    The published result does not depend on when the Mac woke. Neither carries
    the stops that fell in the gaps, so pit calls from such a race go unscored.
    """
    try:
        import fastf1
    except ImportError:
        return None
    fastf1.Cache.enable_cache("cache")
    fastf1.set_log_level("ERROR")
    session = fastf1.get_session(SEASON, round_, "R")
    session.load(laps=False, telemetry=False, weather=False, messages=False)
    results = session.results
    if results is None or results.empty:
        return None
    return {
        str(number): int(position)
        for number, position in zip(results["DriverNumber"], results["Position"], strict=True)
        if position == position  # NaN for a car with no classification
    }


def build_results(races: list[tuple[int, str, str, str]], path: Path = RESULTS) -> int:
    existing = json.loads(path.read_text()) if path.exists() else {}
    for round_, name, ledger, recording in races:
        source = RAW / recording
        if not (PREDICTIONS / f"{ledger}.jsonl").exists():
            continue
        if not source.exists():
            if ledger in existing:
                print(f"  R{round_:<3} {name:<28} kept: {recording} is not on this machine")
            else:
                print(f"  R{round_:<3} {name:<28} no recording ({recording}); not scored")
            continue
        result = read_result(source)
        result["classification"] = "recording"
        if not result["complete"]:
            result["pits"] = None
            published = classification_from_f1(round_)
            if published:
                result["finish"] = published
                result["classification"] = "F1's published result"
        existing[ledger] = {"round": round_, "name": name, **result}
        laps = f"{result['laps']}/{result['total_laps']} laps"
        print(f"  R{round_:<3} {name:<28} {laps:<12} {result['classification']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = dict(sorted(existing.items(), key=lambda item: item[1]["round"]))
    path.write_text(json.dumps(ordered, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    return 0


# -- step two: the scorecard -------------------------------------------------


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def provenance(rows: list[dict[str, Any]]) -> str:
    """live, backtest or replay - the weakest claim among the rows."""
    sources = {str(row.get("source", "live")) for row in rows}
    if not sources:
        return ""
    if sources == {"live"}:
        return "live"
    return "backtest" if any(s.startswith("backtest") for s in sources) else "replay"


@dataclass
class Race:
    round: int
    name: str
    ledger: str
    result: dict[str, Any]
    calls: list[dict[str, Any]] = field(default_factory=list)
    forecasts: list[dict[str, Any]] = field(default_factory=list)
    latency: list[dict[str, Any]] = field(default_factory=list)

    @property
    def made(self) -> str:
        return provenance(self.calls)

    @property
    def forecasts_made(self) -> str:
        return provenance(self.forecasts)

    @property
    def finish(self) -> dict[str, int]:
        return {str(k): int(v) for k, v in self.result["finish"].items()}

    @property
    def models(self) -> list[str]:
        # A stamp is "<commit>[+dirty]/<data hash>"; the commit is the part to read.
        return sorted({str(row.get("models") or "")[:7] or "unrecorded" for row in self.calls})


def load(results: Path = RESULTS, directory: Path = PREDICTIONS) -> tuple[list[Race], list[str]]:
    """Scored races in round order, and ledgers that have no result yet."""
    known = json.loads(results.read_text()) if results.exists() else {}
    races = [
        Race(
            round=int(entry["round"]),
            name=str(entry["name"]),
            ledger=ledger,
            result=entry,
            calls=read_rows(directory / f"{ledger}.jsonl"),
            forecasts=read_rows(directory / f"{ledger}-forecasts.jsonl"),
            latency=read_rows(directory / f"{ledger}-latency.jsonl"),
        )
        for ledger, entry in known.items()
    ]
    ledgers = {
        p.stem for p in directory.glob("*.jsonl") if not p.stem.endswith(("-forecasts", "-latency"))
    }
    return sorted(races, key=lambda r: r.round), sorted(ledgers - set(known))


def para(text: str) -> str:
    return textwrap.fill(text, width=100, break_on_hyphens=False)


def pct(value: float) -> str:
    return "worse" if value == float("-inf") else f"{value:+.1%}"


def pooled_forecasts(races: list[Race]) -> Any:
    """One forecast score across races, each car keyed by its race.

    Car numbers repeat from race to race, so they are prefixed before pooling;
    otherwise a forecast for car 1 in one race would be graded against car 1's
    finish in another.
    """
    entries, finish = [], {}
    for race in races:
        for row in race.forecasts:
            entries.append({**row, "driver": f"{race.ledger}/{row.get('driver')}"})
        finish.update({f"{race.ledger}/{d}": p for d, p in race.finish.items()})
    return score_forecasts(entries, finish)


def stop_tally(race: Race, window: int = WINDOW) -> tuple[int, int, int, int] | None:
    """Decisive calls: (rows, said stop soon, team then did, team stopped soon at all)."""
    pits = race.result.get("pits")
    if pits is None:
        return None
    rows = said = followed = stopped = 0
    for row in race.calls:
        if not row.get("decisive"):
            continue
        rows += 1
        s, d = stop_agreement(row, pits.get(str(row["driver"]), []), window)
        said += s
        followed += s and d
        stopped += d
    return rows, said, followed, stopped


def share(part: int, whole: int) -> str:
    return f"{part}/{whole} ({part / whole:.0%})" if whole else "-"


def laps_called(race: Race) -> str:
    laps = sorted({int(row["lap"]) for row in race.calls})
    total = int(race.result.get("total_laps") or 0)
    if not laps:
        return "-"
    return f"{laps[0]}–{laps[-1]} of {total}" if total else f"{laps[0]}–{laps[-1]}"


def render(races: list[Race], unscored: list[str]) -> tuple[str, str]:
    """The README block, and the fuller report it summarises."""
    live = [r for r in races if r.made == "live" and r.forecasts_made == "live"]
    with_forecasts = [r for r in races if r.forecasts]
    pooled = pooled_forecasts(live)

    block = [
        "*Generated by `python scripts/scorecard.py` from every ledger in `predictions/` and the",
        "results in `reports/results.json`. CI regenerates it and fails if the two disagree, so",
        "it cannot be edited by hand and cannot go stale.*",
        "",
        para(
            f"**Field forecasts, live races only** — {pooled.n:,} forecasts across {len(live)} "
            "races, every car on every lap the engine spoke, each committed before the lap it "
            "names:"
        ),
        "",
        "| metric | model | baseline | skill |",
        "|---|---|---|---|",
        f"| Brier (win) | {pooled.brier_win:.4f} | {pooled.baseline_win:.4f} "
        f"| {pct(pooled.skill_win)} |",
        f"| Brier (top 3) | {pooled.brier_top3:.4f} | {pooled.baseline_top3:.4f} "
        f"| {pct(pooled.skill_top3)} |",
        f"| Brier (points) | {pooled.brier_points:.4f} | {pooled.baseline_points:.4f} "
        f"| {pct(pooled.skill_points)} |",
        f"| Mean position error | {pooled.position_error:.2f} "
        f"| {pooled.baseline_position_error:.2f} | — |",
        "",
        para(
            "The baseline says every car finishes where it is running. Positive skill beats it. "
            "A position error above the baseline's means the expected positions landed further "
            "from the result than assuming nothing changes would have - true of every race so "
            "far. The top-3 and points probabilities are where it beats the baseline; its "
            "expected positions and its pick of the winner do not."
        ),
        "",
        "| round | race | made | forecasts | win | top 3 | points | position error |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for race in with_forecasts:
        card = score_forecasts(race.forecasts, race.finish)
        made = (
            race.made
            if race.forecasts_made == race.made
            else (f"{race.made} calls, {race.forecasts_made} forecasts")
        )
        block.append(
            f"| {race.round} | {race.name} | {made} | {card.n:,} | {pct(card.skill_win)} "
            f"| {pct(card.skill_top3)} | {pct(card.skill_points)} "
            f"| {card.position_error:.2f} vs {card.baseline_position_error:.2f} |"
        )
    block += [
        "",
        "**Reliability, live races pooled.** When it says 70%, does it happen seven times in ten?",
        "",
        "| P(top 3) band | n | said | happened |",
        "|---|---|---|---|",
    ]
    for b in pooled.reliability:
        block.append(
            f"| {b.low:.0%}–{b.high:.0%} | {b.n:,} | {b.predicted:.1%} | {b.observed:.1%} |"
        )

    block += [
        "",
        para(
            f'**Pit calls against what the teams did.** A decisive "stop within {WINDOW} laps" '
            "- one with a clear margin over the alternatives - set against whether that car then "
            f"stopped within {WINDOW} laps. A team's stop is not ground truth; it is the best "
            "evidence there is of when stopping was reasonable. *Base rate* is how often the car "
            "stopped that soon whatever the engine said, which is the number to beat."
        ),
        "",
        "| round | race | made | calls on laps | calls | decisive | said stop soon "
        "| team then did | base rate |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    totals: dict[str, list[int]] = {"live": [0, 0, 0, 0], "backtest": [0, 0, 0, 0]}
    for race in races:
        tally = stop_tally(race)
        if tally is None:
            cells = "no lap data | no lap data | —"
            decisive = "—"
        else:
            rows, said, followed, stopped = tally
            group = totals["live" if race.made == "live" else "backtest"]
            for i, value in enumerate(tally):
                group[i] += value
            decisive = str(rows)
            cells = f"{said} | {share(followed, said)} | {share(stopped, rows)}"
        block.append(
            f"| {race.round} | {race.name} | {race.made} | {laps_called(race)} "
            f"| {len(race.calls)} | {decisive} | {cells} |"
        )
    for group, (rows, said, followed, stopped) in totals.items():
        block.append(
            f"| | **all {group}** | | | | {rows} | {said} | {share(followed, said)} "
            f"| {share(stopped, rows)} |"
        )

    live_rows, live_said = totals["live"][0], totals["live"][1]
    if live_rows and not live_said:
        block += [
            "",
            para(
                f'**No live race has produced a decisive "stop soon" call yet** - all '
                f"{live_rows} decisive live calls were to stay out. The engine advises one car, "
                "and every live call so far has been for the car in P1, the one least likely "
                "to be told to stop. That is a gap in the evidence, not a result: the pit-call "
                "side of this engine has so far been graded only on backtests."
            ),
        ]

    timed = [r for r in races if r.latency and r.made == "live"]
    if timed:
        block += [
            "",
            para(
                "**Latency, live races.** Packet landing to recommendation existing, against a "
                f"p99 budget of {DEFAULT_BUDGET_P99:.0f} s:"
            ),
            "",
            "| round | race | decisions | p50 | p99 | over budget |",
            "|---|---|---|---|---|---|",
        ]
        everything: list[dict[str, Any]] = []
        for race in timed:
            everything += race.latency
            stage = report_from(race.latency).stage("total")
            block.append(
                f"| {race.round} | {race.name} | {stage.n} | {stage.p50 * 1000:.0f} ms "
                f"| {stage.p99 * 1000:.0f} ms | {stage.over_budget} |"
            )
        stage = report_from(everything).stage("total")
        block.append(
            f"| | **all live** | {stage.n} | {stage.p50 * 1000:.0f} ms "
            f"| {stage.p99 * 1000:.0f} ms | {stage.over_budget} |"
        )

    notes = []
    for race in races:
        if race.result.get("classification") != "recording":
            notes.append(
                para(
                    f"- **{race.name}**: the recording holds {race.result.get('laps_seen')} of "
                    f"{race.result.get('total_laps')} laps, so its forecasts are graded against "
                    f"{race.result.get('classification')} and its pit calls, with no stops to "
                    "set them against, are not graded."
                )
            )
    if notes:
        block += ["", *notes]

    report = [
        "# Scorecard",
        "",
        "Every race this engine has a ledger for, graded. Regenerate with "
        "`python scripts/scorecard.py`; the README carries the same tables.",
        "",
        *block,
        "",
        "## Which model made each race",
        "",
        "Rows are stamped with the commit that made them. More than one stamp in a race means",
        "the ledger mixes model versions and its per-race scores average across them.",
        "",
        "| round | race | made | recording | model commits |",
        "|---|---|---|---|---|",
    ]
    for race in races:
        report.append(
            f"| {race.round} | {race.name} | {race.made} | `{race.result.get('recording')}` "
            f"| {', '.join(race.models)} |"
        )
    if unscored:
        report += [
            "",
            "## Not scored yet",
            "",
            "Ledgers with no result in `reports/results.json`. Run `--results` after the race.",
            "",
            *[f"- `predictions/{name}.jsonl`" for name in unscored],
        ]
    return "\n".join(block), "\n".join(report) + "\n"


def splice(readme: str, block: str) -> str:
    before, start, rest = readme.partition(START)
    _, end, after = rest.partition(END)
    if not start or not end:
        raise ValueError(f"README has no {START} ... {END} markers")
    return f"{before}{START}\n{block}\n{END}{after}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        action="store_true",
        help="read final classifications and pit laps from the local recordings first",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if the README block is out of date",
    )
    args = parser.parse_args()

    if args.results:
        build_results(manifest())
    if not RESULTS.exists():
        print(f"no {RESULTS}; run with --results first", file=sys.stderr)
        return 1

    races, unscored = load()
    block, report = render(races, unscored)
    current = README.read_text(encoding="utf-8")
    updated = splice(current, block)
    if args.check:
        if updated != current:
            print("README scorecard is out of date: run python scripts/scorecard.py")
            return 1
        print("README scorecard is current")
        return 0
    README.write_text(updated, encoding="utf-8")
    REPORT.write_text(report, encoding="utf-8")
    print(f"wrote {REPORT} and the README block: {len(races)} races")
    for name in unscored:
        print(f"  not scored yet: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
