"""The race-day launcher, run for real under the shell that runs it on race day.

`race_day.sh` had no tests, and the 2026 Spanish GP was lost to it. Every
preflight check passed when it was armed at 08:08; at 13:45 the engine launch
died on `REHEARSE_FLAG[@]: unbound variable`, because macOS's /bin/bash 3.2
treats an empty array under `set -u` as unset and a real race always passes an
empty one. That is a runtime failure in one line, so nothing short of running
that line catches it - these tests run the whole script in `--dry-run`, which
swaps only the engine executable for a stub.

Each test builds a throwaway git repository holding a copy of the script, so the
real preflight (branch, identity, port) runs without touching this repository.

macOS only, and deliberately: the script needs BSD `date`, `caffeinate` and
`lsof`, and Linux's bash 5 accepts the construct that failed, so a Linux run
would pass whether or not the bug was there. CI runs this file on a macOS runner.
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "race_day.sh"
BASH = "/bin/bash"
FIXED = '${REHEARSE_FLAG[@]+"${REHEARSE_FLAG[@]}"}'
BROKEN = '"${REHEARSE_FLAG[@]}"'

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="race_day.sh needs BSD date, caffeinate and lsof; it only runs on macOS",
)


def _bash_major() -> int:
    out = subprocess.run(
        [BASH, "-c", "echo ${BASH_VERSINFO[0]}"], capture_output=True, text=True
    ).stdout
    return int(out.strip() or 0)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _sandbox(tmp_path: Path, script_text: str | None = None) -> Path:
    """A git repository on a branch with an identity, holding the script."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    script = repo / "scripts" / "race_day.sh"
    script.write_text(SCRIPT.read_text() if script_text is None else script_text)
    for args in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "test"],
        ["git", "add", "-A"],
        ["git", "commit", "-qm", "init"],
    ):
        subprocess.run(args, cwd=repo, check=True, capture_output=True)
    return script


def _dry_run(script: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            BASH,
            str(script),
            *flags,
            "--dry-run",
            "2000-01-01 00:00",
            "t",
            "Test GP",
            "",
            "1",
            str(_free_port()),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _log(script: Path) -> str:
    return (script.parent.parent / "data" / "raw" / "t-dryrun.log").read_text()


def test_the_script_still_carries_the_fix():
    """Guards the doctored-copy tests below: if the fixed expansion is ever
    rewritten, they would silently stop testing the real launch line."""
    text = SCRIPT.read_text()
    assert FIXED in text
    # The broken form is a substring of the fixed one, so it can only be looked
    # for outside every occurrence of the fix. The first version of this test
    # asserted `BROKEN not in text` and failed against the correct script.
    assert BROKEN not in text.replace(FIXED, "")


def test_a_race_dry_run_reaches_the_engine(tmp_path):
    """The Spanish GP case exactly: no --rehearse, so the flag array is empty."""
    script = _sandbox(tmp_path)
    result = _dry_run(script)
    log = _log(script)

    assert result.returncode == 0, result.stderr
    assert "unbound variable" not in result.stderr
    assert "dry run OK" in log
    argv = next(line for line in log.splitlines() if line.startswith("dry-run engine argv:"))
    assert "[--log-predictions]" in argv
    assert "[Test GP]" in argv
    assert "[--rehearse]" not in argv


def test_a_rehearsal_dry_run_passes_the_flag_through(tmp_path):
    script = _sandbox(tmp_path)
    result = _dry_run(script, "--rehearse")

    assert result.returncode == 0, result.stderr
    assert "[--rehearse]" in _log(script)


@pytest.mark.skipif(_bash_major() >= 4, reason="the failure is specific to bash 3.x")
def test_the_dry_run_fails_on_the_bug_that_lost_the_spanish_gp(tmp_path):
    """A check that cannot fail for the right reason is not a check. Put the old
    launch line back and the dry run must say FAILED, not OK."""
    script = _sandbox(tmp_path, SCRIPT.read_text().replace(FIXED, BROKEN))
    result = _dry_run(script)

    assert result.returncode != 0
    assert "unbound variable" in result.stderr
    assert "dry run FAILED" in _log(script)


@pytest.mark.skipif(_bash_major() >= 4, reason="the failure is specific to bash 3.x")
def test_a_stale_success_line_cannot_pass_a_failing_launch(tmp_path):
    """The verdict is read from the log, so an earlier run's success line left in
    it would turn a broken launch into a pass."""
    script = _sandbox(tmp_path, SCRIPT.read_text().replace(FIXED, BROKEN))
    stale = script.parent.parent / "data" / "raw"
    stale.mkdir(parents=True)
    (stale / "t-dryrun.log").write_text("dry-run engine argv: [left over]\n")

    result = _dry_run(script)

    assert result.returncode != 0
    assert "left over" not in _log(script)
