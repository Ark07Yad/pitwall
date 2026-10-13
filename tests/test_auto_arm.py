"""The job that arms the recorder so nobody has to remember to.

Two of the first five races were lost to nobody running the launcher. What is
tested here is the part that decides - which race a firing is for, whether to
wait, arm or do nothing, and what launchd is asked to do - because that part
runs with nobody watching and its mistakes look like a quiet Sunday.

The part that starts processes is not run here. `--fire --dry-run` exercises it
by hand, and the launcher it calls has its own tests in `test_race_day.py`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import plistlib
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "auto_arm.py"
spec = importlib.util.spec_from_file_location("auto_arm", SCRIPT)
auto_arm = importlib.util.module_from_spec(spec)
sys.modules["auto_arm"] = auto_arm
spec.loader.exec_module(auto_arm)

DUBLIN = ZoneInfo("Europe/Dublin")


def race(start: datetime, name: str = "United States Grand Prix", location: str = "Austin"):
    return auto_arm.race_from(18, name, location, start)


AUSTIN = race(datetime(2026, 10, 25, 20, 0, tzinfo=UTC))


def at(minutes_before_start: float, of=AUSTIN) -> datetime:
    return of.start - timedelta(minutes=minutes_before_start)


# -- which race, and what to do about it --------------------------------


def test_three_hours_out_it_waits():
    action, found = auto_arm.decide(at(180), [AUSTIN])

    assert (action, found) == ("wait", AUSTIN)


def test_half_an_hour_out_it_arms():
    assert auto_arm.decide(at(30), [AUSTIN])[0] == "arm"


def test_a_firing_after_the_start_still_arms():
    """launchd runs a missed firing when the Mac wakes. Half a race is worth
    having, so a late one arms rather than giving up."""
    assert auto_arm.decide(at(-45), [AUSTIN])[0] == "arm"
    assert auto_arm.decide(at(-150), [AUSTIN])[0] == "arm"


def test_long_after_the_start_it_says_the_race_was_missed():
    action, found = auto_arm.decide(at(-200), [AUSTIN])

    assert (action, found) == ("missed", AUSTIN)


def test_with_no_race_near_it_does_nothing():
    """StartCalendarInterval has no year, so every firing happens again next
    October. It has to find nothing and leave."""
    a_year_on = AUSTIN.start + timedelta(days=365) - timedelta(minutes=30)

    assert auto_arm.decide(a_year_on, [AUSTIN]) == ("nothing", None)
    assert auto_arm.decide(at(60 * 24 * 3), [AUSTIN]) == ("nothing", None)


def test_it_picks_the_race_it_was_fired_for():
    mexico = race(datetime(2026, 11, 1, 20, 0, tzinfo=UTC), "Mexico City Grand Prix", "Mexico City")

    assert auto_arm.decide(at(30, mexico), [AUSTIN, mexico])[1] == mexico
    assert auto_arm.decide(at(30, AUSTIN), [AUSTIN, mexico])[1] == AUSTIN


# -- names: the same ones the hand-armed races used ---------------------


def test_names_are_plain_ascii_and_match_the_house_style():
    sao_paulo = race(datetime(2026, 11, 8, 17, 0, tzinfo=UTC), "São Paulo Grand Prix", "São Paulo")

    assert AUSTIN.slug == "2026-austin-race"
    assert AUSTIN.session == "2026 United States GP"
    # The ledger's file name is made from the session, and the recording's from
    # the slug. Neither should depend on how a filesystem feels about a tilde.
    assert sao_paulo.slug == "2026-sao-paulo-race"
    assert sao_paulo.session == "2026 Sao Paulo GP"


# -- what the launcher is asked for --------------------------------------


def test_the_recording_ends_at_the_same_moment_however_late_it_was_armed():
    on_time = auto_arm.recording_minutes(AUSTIN, at(30))
    late = auto_arm.recording_minutes(AUSTIN, at(-40))

    assert on_time == 330
    assert late == 260
    assert at(30) + timedelta(minutes=on_time) == at(-40) + timedelta(minutes=late)


def test_an_early_firing_does_not_lengthen_the_recording():
    """Armed three hours out, the launcher waits for its start time. The length
    is counted from there, not from when it was asked."""
    assert auto_arm.recording_minutes(AUSTIN, at(180)) == 330


def test_launcher_arguments_are_the_ones_the_runbook_types():
    args = auto_arm.launcher_args(AUSTIN, at(30))
    start_at = (AUSTIN.start - timedelta(minutes=30)).astimezone().strftime("%Y-%m-%d %H:%M")

    assert args == [start_at, "2026-austin-race", "2026 United States GP", "", "330"]


# -- what launchd is asked to do -----------------------------------------


def test_each_race_fires_three_hours_and_half_an_hour_before():
    times = [t.astimezone(UTC) for t in auto_arm.firings(AUSTIN)]

    assert times == [at(180), at(30)]


def test_a_race_in_the_small_hours_also_fires_the_evening_before():
    """Las Vegas starts at 04:00 Irish. Three hours before is 01:00, when nobody
    is awake to be told to leave the lid open."""
    vegas = race(
        datetime(2026, 11, 22, 4, 0, tzinfo=DUBLIN).astimezone(UTC),
        "Las Vegas Grand Prix",
        "Las Vegas",
    )
    times = auto_arm.firings(vegas)
    local_start = vegas.local

    assert len(times) == 3
    assert (times[0].hour, times[0].minute) == (21, 0)
    assert times[0].date() == (local_start - timedelta(days=1)).date()


def test_an_afternoon_race_gets_no_evening_firing():
    afternoon = race(
        datetime(2026, 12, 6, 13, 0, tzinfo=DUBLIN).astimezone(UTC), "Abu Dhabi Grand Prix"
    )
    # Judged on this machine's clock, which is the one launchd fires on.
    expected = 3 if afternoon.local.hour < auto_arm.OVERNIGHT_BEFORE_HOUR else 2

    assert len(auto_arm.firings(afternoon)) == expected


def test_races_already_run_are_not_scheduled():
    mexico = race(datetime(2026, 11, 1, 20, 0, tzinfo=UTC), "Mexico City Grand Prix", "Mexico City")
    after_austin = AUSTIN.start + timedelta(days=1)

    intervals = auto_arm.calendar_intervals([AUSTIN, mexico], after_austin)

    assert len(intervals) == len(auto_arm.firings(mexico))
    assert all(set(i) == {"Month", "Day", "Hour", "Minute"} for i in intervals)


def test_the_plist_is_one_launchd_can_read():
    """Built with plistlib. A hand-written one with a raw ampersand in it was
    accepted by launchctl on 5 September and would never have fired."""
    raw = auto_arm.launchd_plist([AUSTIN], at(60 * 24), Path("/tmp/venv/bin/python"))
    loaded = plistlib.loads(raw)

    assert loaded["Label"] == "com.pitwall.autoarm"
    assert loaded["ProgramArguments"][-1] == "--fire"
    assert loaded["ProgramArguments"][0] == "/tmp/venv/bin/python"
    assert len(loaded["StartCalendarInterval"]) == len(auto_arm.firings(AUSTIN))
    assert loaded["RunAtLoad"] is False


# -- the calendar file ---------------------------------------------------


def test_the_calendar_survives_a_round_trip(tmp_path):
    path = tmp_path / "calendar.json"
    sao_paulo = race(datetime(2026, 11, 8, 17, 0, tzinfo=UTC), "São Paulo Grand Prix", "São Paulo")
    auto_arm.save_calendar([sao_paulo, AUSTIN], path)

    assert auto_arm.load_calendar(path) == [AUSTIN, sao_paulo]


@pytest.mark.parametrize("minutes", [30, 0, -150])
def test_the_arm_window_includes_its_edges(minutes):
    assert auto_arm.decide(at(minutes), [AUSTIN])[0] == "arm"


# -- starting a recorder, and stopping one --------------------------------

STUB = """#!/bin/bash
# Stands in for race_day.sh: passes its dry run, then runs until told to stop.
if [[ "$1" == "--dry-run" ]]; then echo "dry run OK - stub"; exit 0; fi
trap 'echo stopped > "$MARK"; exit 0' TERM
printf '%s\n' "$@" > "$MARK.args"
while :; do sleep 0.2; done
"""


def _fire_against_a_stub(tmp_path, *, starts_in_minutes: float, stub: str = STUB):
    launcher = tmp_path / "launcher.sh"
    launcher.write_text(stub)
    start = datetime.now(UTC) + timedelta(minutes=starts_in_minutes)
    calendar = tmp_path / "calendar.json"
    auto_arm.save_calendar([race(start)], calendar)
    env = {
        **os.environ,
        "AUTO_ARM_LAUNCHER": str(launcher),
        "AUTO_ARM_CALENDAR": str(calendar),
        "AUTO_ARM_SETTLE": "1",
        "AUTO_ARM_QUIET": "1",
        "MARK": str(tmp_path / "mark"),
    }
    return subprocess.Popen(
        [sys.executable, str(SCRIPT), "--fire"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for(path: Path, seconds: float = 20.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.1)
    return False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals and bash")
def test_a_firing_starts_the_recorder_and_stopping_the_job_stops_it(tmp_path):
    """The whole point of staying with the launcher instead of leaving it
    behind: when launchd stops this job, the recorder must get the signal too,
    or its trap never runs and a connection to the feed is left open."""
    if auto_arm.recorder_running():
        pytest.skip("a real recorder is running on this machine")
    job = _fire_against_a_stub(tmp_path, starts_in_minutes=10)
    try:
        assert _wait_for(tmp_path / "mark.args"), (
            job.stdout.read() if job.poll() else "never started"
        )
        args = (tmp_path / "mark.args").read_text().splitlines()
        assert args[1:4] == ["2026-austin-race", "2026 United States GP", ""]

        time.sleep(1.5)  # past the settle, so the handler is installed
        job.send_signal(signal.SIGTERM)
        job.wait(timeout=20)
    finally:
        if job.poll() is None:
            job.kill()

    assert (tmp_path / "mark").read_text().strip() == "stopped"


@pytest.mark.skipif(sys.platform == "win32", reason="bash")
def test_a_failed_dry_run_starts_nothing(tmp_path):
    """The runbook's rule, kept by the machine: anything but OK, and do not arm."""
    if auto_arm.recorder_running():
        pytest.skip("a real recorder is running on this machine")
    broken = STUB.replace('echo "dry run OK - stub"; exit 0', 'echo "dry run FAILED"; exit 1')
    job = _fire_against_a_stub(tmp_path, starts_in_minutes=10, stub=broken)
    output, _ = job.communicate(timeout=30)

    assert job.returncode == 1
    assert "NOT started" in output
    assert not (tmp_path / "mark.args").exists()


def test_the_real_calendar_is_well_formed():
    """The file launchd's firings are decided from. If it is missing the job
    was never installed, which is not this test's business."""
    path = SCRIPT.parent / "race_calendar.json"
    if not path.exists():
        pytest.skip("not installed")
    races = auto_arm.load_calendar(path)

    assert races == sorted(races, key=lambda r: r.start)
    for item in json.loads(path.read_text()):
        assert item["slug"].isascii() and item["session"].isascii()
        assert item["slug"].endswith("-race")
