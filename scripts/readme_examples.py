#!/usr/bin/env python
"""Regenerate the example blocks in README.md from live CLI output.

The README quotes real command output — the clean-lap breakdown, the
safety-car hazard, a strategy call, the scorecard. Those numbers move
whenever the models or the data change, and a hand-pasted block rots in
silence: on 8 August the hazard table was still the 94-race fit and the
strategy example predated the running-order fix, both quietly wrong in a
repository whose whole pitch is that its numbers are trustworthy.

This re-runs the exact commands the README documents and prints each block
under the heading it belongs to, so refreshing the README is a command and
a diff rather than a copy-paste taken on trust. It does not edit README.md —
it prints the current truth next to a note of where each block lives, and
leaves the judgement of what to paste to a human.

    python scripts/readme_examples.py

Needs the Hungary recording (data/raw/2026-hungary-race.txt) and the
committed prediction log, both local, so this is a developer tool and not
part of CI. The Monte Carlo is seeded, so the strategy block reproduces
byte-for-byte between runs.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

RACE = Path("data/raw/2026-hungary-race.txt")
LOG = Path("predictions/2026-hungarian-gp.jsonl")


def cli(*args: str) -> str:
    """Run `python -m pitwall ...` and return its stdout, trailing blanks trimmed."""
    result = subprocess.run(
        [sys.executable, "-m", "pitwall", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.rstrip("\n")


def block(heading: str, readme_location: str, body: str) -> str:
    rule = "─" * 76
    return f"{rule}\n{heading}\n  README: {readme_location}\n{rule}\n\n{body}\n"


def strategy_block() -> str:
    """The 'Pit calls' example, trimmed to three options and '...' as the README shows it."""
    full = cli("strategy", str(RACE), "--lap", "34", "--driver", "LEC").splitlines()
    opt = next(i for i, line in enumerate(full) if line.lstrip().startswith("option"))
    undercut = next(i for i, line in enumerate(full) if "undercut threats" in line)
    kept = full[: opt + 4] + ["  ..."] + full[undercut - 1 :]
    return "\n".join(kept)


def main() -> int:
    missing = [p for p in (RACE, LOG) if not p.exists()]
    if missing:
        print("missing local inputs: " + ", ".join(str(p) for p in missing), file=sys.stderr)
        print("this tool runs against the Hungary recording; nothing to do.", file=sys.stderr)
        return 1

    with tempfile.NamedTemporaryFile(suffix=".md") as tmp:
        report = cli("report", str(RACE), "--log", str(LOG), "--out", tmp.name)

    hazard = cli("hazard", "--kind", "any")
    print(block("Clean-lap filtering", "### Clean-lap filtering", cli("laps", str(RACE))))
    print(block("Safety-car hazard", "### Safety-car hazard (--kind any)", hazard))
    print(block("Pit calls", "### Pit calls", strategy_block()))
    print(block("The track record", "### The track record", report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
