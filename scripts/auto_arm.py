#!/usr/bin/env python3
"""Arm the race-day recorder without anybody having to remember to.

Two of the first five races this was meant to record were lost because nobody
ran the launcher: the Italian GP and the Singapore GP. Neither was a fault. The
launcher was tested, the dry run passed the night before, the command was in the
runbook - and the step before all of that was a person remembering on a Sunday.
A reminder was set after the first and expired with that race.

So the step is taken away. `--install` writes a launchd agent that fires before
each remaining race and runs this script, which then does what the runbook says
a person should do, in the same order:

    python scripts/auto_arm.py --install      # once; --status to see what is scheduled
    python scripts/auto_arm.py --uninstall

**What a firing does.** It finds the race it was fired for, posts a notification,
holds the Mac awake, waits until thirty minutes before the start, runs the
launcher's `--dry-run`, and only if that says OK starts the launcher itself and
stays with it until the recording ends. It posts again when the recorder is up
and when it has finished.

**It fires three hours before a race and again thirty minutes before.** The
second is a fallback: launchd will not start a job that is already running, so
it only does anything if the first never ran - the Mac was asleep at the time,
say - and launchd runs a missed firing on wake, so a late one still arms a race
already in progress rather than losing all of it. A race starting in the small
hours also fires at 21:00 the evening before, which is the only time anyone is
awake to be told to leave the lid open.

**One connection, always.** If a launcher, a dashboard or `record.py` is already
running it does nothing at all. Arming by hand is still allowed and wins.

**What it cannot do is open a closed lid.** A sleeping Mac runs nothing, and
waking one on a schedule needs `pmset`, which needs root and is not something
this script will touch. Plugged in, lid open. The evening notification says so.
What it does instead is say so when it matters: a closed lid is reported at each
firing, a nap during the recording as it is noticed, and the last notification
reads "recording has gaps" rather than "finished". The 2026 United States GP slept
through almost all of it, and that was only found by reading a file size.

**The start time is checked, not trusted.** Qualifying at the 2026 Singapore GP
moved by half an hour during the week. Each firing asks FastF1 for the current
start and uses that if it answers; the calendar file is the fallback, and the
launcher records for 330 minutes from half an hour before the start, which
covers a start ninety minutes late on its own.

`StartCalendarInterval` has no year, so these fire again on the same dates next
year. They find no race near and exit. Re-run `--install` each season.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import signal
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Overridable so the part that starts and stops a recorder can be tested against
# a stub. Nothing but the tests sets these; a real firing gets the real files.
CALENDAR = Path(os.environ.get("AUTO_ARM_CALENDAR") or REPO / "scripts" / "race_calendar.json")
LAUNCHER = Path(os.environ.get("AUTO_ARM_LAUNCHER") or REPO / "scripts" / "race_day.sh")
# Where macOS keeps the lid state. A module constant so a test can take it away.
IOREG = "/usr/sbin/ioreg"
# Seconds to give the launcher before calling it armed.
SETTLE_SECONDS = float(os.environ.get("AUTO_ARM_SETTLE") or 25)
LABEL = "com.pitwall.autoarm"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = REPO / "data" / "raw" / "auto-arm.log"

# Minutes before the start that the recorder goes up. Race control's rain-risk
# and delay messages arrive in this half hour, and they are worth having.
ARM_LEAD = 30
# Minutes before the start of the main firing, and of the notification with it.
REMIND_LEAD = 180
# The recording ends this long after the scheduled start: a two-hour race, a
# start ninety minutes late, and an hour to spare.
RECORD_AFTER_START = 300
# A firing this far ahead of a race waits for it; further out, it is not ours.
WAIT_UP_TO = 12 * 60
# A firing this long after the start still arms - half a race beats none.
ARM_UNTIL_AFTER = 150
# How often the job looks at the clock while recording, and the jump in seconds
# that means the Mac was asleep rather than busy.
WATCH_SECONDS = 10.0
SLEEP_GAP = 60.0
# Local hour before which a race counts as overnight and gets an evening firing.
OVERNIGHT_BEFORE_HOUR = 9
EVENING_HOUR = 21


@dataclass(frozen=True)
class Race:
    round: int
    name: str
    location: str
    slug: str
    session: str
    start: datetime  # timezone-aware, UTC

    @property
    def local(self) -> datetime:
        return self.start.astimezone()


def ascii_slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def race_from(round_number: int, name: str, location: str, start: datetime) -> Race:
    """Names the recording and the ledger the way the hand-armed races were."""
    season = start.astimezone().year
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return Race(
        round=round_number,
        name=name,
        location=location,
        slug=f"{season}-{ascii_slug(location)}-race",
        session=f"{season} {plain.replace('Grand Prix', 'GP').strip()}",
        start=start.astimezone(UTC),
    )


def load_calendar(path: Path = CALENDAR) -> list[Race]:
    races = []
    for item in json.loads(path.read_text()):
        start = datetime.fromisoformat(item["start_utc"].replace("Z", "+00:00"))
        races.append(
            Race(
                round=int(item["round"]),
                name=item["name"],
                location=item["location"],
                slug=item["slug"],
                session=item["session"],
                start=start,
            )
        )
    return sorted(races, key=lambda race: race.start)


def save_calendar(races: list[Race], path: Path = CALENDAR) -> None:
    payload = [
        {
            "round": race.round,
            "name": race.name,
            "location": race.location,
            "slug": race.slug,
            "session": race.session,
            "start_utc": race.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for race in sorted(races, key=lambda race: race.start)
    ]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def fetch_schedule(season: int) -> list[Race]:
    """Every race of the season from FastF1. Imported here so a firing that
    never needs the schedule never pays for, or trips over, the import."""
    import fastf1  # noqa: PLC0415

    races = []
    for _, event in fastf1.get_event_schedule(season).iterrows():
        for index in range(1, 6):
            if event.get(f"Session{index}") != "Race":
                continue
            start = event[f"Session{index}DateUtc"].to_pydatetime().replace(tzinfo=UTC)
            races.append(
                race_from(int(event["RoundNumber"]), event["EventName"], event["Location"], start)
            )
    return races


def minutes_until(race: Race, now: datetime) -> float:
    return (race.start - now).total_seconds() / 60.0


def decide(now: datetime, races: list[Race]) -> tuple[str, Race | None]:
    """What a firing at `now` should do, and for which race.

    `arm` - within half an hour of a start, or up to 150 minutes after one.
    `wait` - a race is coming within twelve hours: say so, stay awake, arm later.
    `missed` - a race started more than 150 minutes ago and under six hours ago.
    `nothing` - no race near. The usual answer for next year's firings.
    """
    best: tuple[str, Race | None] = ("nothing", None)
    for race in races:
        ahead = minutes_until(race, now)
        if -ARM_UNTIL_AFTER <= ahead <= ARM_LEAD:
            return "arm", race
        if ARM_LEAD < ahead <= WAIT_UP_TO:
            return "wait", race
        if -360 <= ahead < -ARM_UNTIL_AFTER:
            best = ("missed", race)
    return best


def firings(race: Race) -> list[datetime]:
    """Local times launchd should fire for this race."""
    local = race.local
    times = [local - timedelta(minutes=REMIND_LEAD), local - timedelta(minutes=ARM_LEAD)]
    if local.hour < OVERNIGHT_BEFORE_HOUR:
        evening = (local - timedelta(days=1)).replace(
            hour=EVENING_HOUR, minute=0, second=0, microsecond=0
        )
        times.insert(0, evening)
    return times


def calendar_intervals(races: list[Race], now: datetime) -> list[dict[str, int]]:
    intervals = []
    for race in races:
        if race.start <= now:
            continue
        for when in firings(race):
            intervals.append(
                {"Month": when.month, "Day": when.day, "Hour": when.hour, "Minute": when.minute}
            )
    return intervals


def launchd_plist(races: list[Race], now: datetime, python: Path) -> bytes:
    """Built with plistlib, never by hand. A hand-written one with a raw `&` in a
    shell command was accepted by launchctl on 5 September and would never have
    fired."""
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [str(python), str(Path(__file__).resolve()), "--fire"],
            "WorkingDirectory": str(REPO),
            "StartCalendarInterval": calendar_intervals(races, now),
            "StandardOutPath": str(LOG),
            "StandardErrorPath": str(LOG),
            "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
            "RunAtLoad": False,
        }
    )


def recording_minutes(race: Race, now: datetime) -> int:
    """So the recording ends at the same moment whenever it was armed."""
    begins = max(now, race.start - timedelta(minutes=ARM_LEAD))
    end = race.start + timedelta(minutes=RECORD_AFTER_START)
    return max(30, int((end - begins).total_seconds() // 60))


@dataclass
class SleepWatch:
    """Notices the clock jumping, which is how a process sees the Mac sleep.

    The 2026 United States GP was armed on time and then slept through: the Mac
    woke for a few seconds every quarter of an hour, the recorder saw 11 of 56
    lap counts, and the job reported "recording" and "finished" as if nothing had
    happened. A process cannot stop a closed lid, but it can tell afterwards.
    """

    last: float
    asleep: float = 0.0
    naps: int = 0

    def tick(self, now: float) -> float:
        """Seconds lost since the last tick, or zero if it was on time."""
        gap, self.last = now - self.last, now
        if gap <= SLEEP_GAP:
            return 0.0
        self.asleep += gap
        self.naps += 1
        return gap


def finish_message(race: Race, size_mb: float, code: int, watch: SleepWatch) -> tuple[str, str]:
    """The last notification. Says plainly when the recording cannot be whole."""
    if watch.naps:
        minutes = watch.asleep / 60
        return (
            "Pitwall - recording has gaps",
            f"{race.name}: the Mac slept for {minutes:.0f} min across {watch.naps} naps, so laps "
            f"are missing. {size_mb:.1f} MB recorded. It can be rebuilt from the archive.",
        )
    return "Pitwall - finished", f"{race.name}: {size_mb:.1f} MB recorded. Exit code {code}."


def launcher_args(race: Race, now: datetime) -> list[str]:
    start_at = (race.start - timedelta(minutes=ARM_LEAD)).astimezone().strftime("%Y-%m-%d %H:%M")
    return [start_at, race.slug, race.session, "", str(recording_minutes(race, now))]


# -- everything below touches the machine --------------------------------


def say(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


# Set by --dry-run: say what would be posted instead of posting it, so trying
# the logic at midnight does not tell anybody there is a race today.
QUIET = bool(os.environ.get("AUTO_ARM_QUIET"))


def notify(title: str, message: str) -> None:
    """A notification, passed as arguments so no text needs escaping."""
    if QUIET:
        say(f"would notify: {title} - {message}")
        return
    script = (
        "on run argv\n"
        '  display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"\n'
        "end run"
    )
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", script, title, message],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as error:
        say(f"could not post a notification: {error}")


def is_recorder(command: str) -> bool:
    """Whether a process's command line *is* a recorder, not merely mentions one.

    This used to be `pgrep -f` on the text, which matches anything with those words
    anywhere in its arguments: an editor open on the launcher, a `grep` for it, a
    shell running either. On 2 November a rehearsal of the São Paulo firing refused
    to arm because of the shell that was running the rehearsal. On race day that is
    a lost race with a reasonable-sounding notification. So the program and the
    script it was given are compared, and nothing else is read.
    """
    parts = command.split()
    if len(parts) < 2:
        return False
    program = Path(parts[0]).name.lower()
    arguments = parts[1:]
    if program.startswith("python"):
        if arguments[0] == "-m":
            return arguments[1:3] == ["pitwall", "dashboard"]
        script = Path(arguments[0]).name
        if script == "record.py":
            return True
        return script == "pitwall" and arguments[1:2] == ["dashboard"]
    if program in ("bash", "sh"):
        return Path(arguments[0]).name == "race_day.sh"
    return program == "pitwall" and arguments[0] == "dashboard"


def recorder_running() -> str:
    """The command line of anything already holding, or about to hold, the feed."""
    try:
        listing = subprocess.run(
            ["/bin/ps", "-axo", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        # Carry on: the launcher refuses a taken port before it connects, and a
        # second recorder holds that port. Stopping here would lose the race.
        say(f"could not list processes: {error}")
        return ""
    return next((line.strip() for line in listing.splitlines() if is_recorder(line.strip())), "")


def lid_closed() -> bool:
    """Whether the lid is shut, which no assertion from this process can overrule.

    A warning, so it may never cost what it warns about: if this cannot find out,
    the answer is "not as far as we know" and the race is still armed.
    """
    try:
        listing = subprocess.run(
            [IOREG, "-r", "-k", "AppleClamshellState", "-d", "4"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        say(f"could not read the lid state: {error}")
        return False
    return any(
        '"AppleClamshellState"' in line and line.rstrip().endswith("Yes")
        for line in listing.splitlines()
    )


def warn_if_lid_closed(race: Race) -> None:
    if lid_closed():
        say("THE LID IS CLOSED - the Mac will sleep through this race")
        notify(
            "Pitwall - lid closed",
            f"{race.name}: the lid is closed, so the Mac will sleep and laps will be lost. "
            "Open it.",
        )


def current_start(race: Race) -> Race:
    """The race with its start as FastF1 has it now, or unchanged if it will not say."""
    try:
        answer = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--print-start", str(race.round)],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
            cwd=REPO,
        ).stdout.strip()
        start = datetime.fromisoformat(answer)
    except (OSError, ValueError, subprocess.SubprocessError):
        say("could not confirm the start time; using the calendar file")
        return race
    if abs((start - race.start).total_seconds()) < 60:
        return race
    moved = Race(race.round, race.name, race.location, race.slug, race.session, start)
    say(f"the start has moved: calendar {race.local:%H:%M}, schedule now {moved.local:%H:%M}")
    notify(
        "Pitwall - start time moved",
        f"{race.name} now starts at {moved.local:%H:%M}, not {race.local:%H:%M}. "
        "The recorder will follow the new time.",
    )
    return moved


def wait_until(deadline: datetime) -> None:
    """Poll the clock rather than sleep once: one long sleep is suspended with
    the machine and wakes late by however long it was out."""
    while datetime.now(UTC) < deadline:
        time.sleep(min(30.0, max(1.0, (deadline - datetime.now(UTC)).total_seconds())))


def arm(race: Race, *, dry_run_only: bool = False) -> int:
    already = recorder_running()
    if already:
        say(f"a recorder is already running - leaving it alone: {already}")
        notify("Pitwall", f"{race.name}: a recorder is already running, so nothing was started.")
        return 0

    now = datetime.now(UTC)
    args = launcher_args(race, now)
    say(f"dry run: race_day.sh --dry-run {args}")
    rehearsal = subprocess.run(
        ["/bin/bash", str(LAUNCHER), "--dry-run", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=REPO,
    )
    if rehearsal.returncode != 0 or "dry run OK" not in rehearsal.stdout:
        tail = (rehearsal.stdout + rehearsal.stderr).strip().splitlines()[-3:]
        say("DRY RUN FAILED - the recorder was NOT started")
        for line in tail:
            say(f"    {line}")
        notify(
            "Pitwall - NOT RECORDING",
            f"{race.name}: the dry run failed, so the recorder was not started. See auto-arm.log.",
        )
        return 1
    say("dry run OK")
    if dry_run_only:
        say(f"would now run: race_day.sh {args}")
        return 0

    say(f"arming: race_day.sh {args}")
    launcher = subprocess.Popen(  # noqa: S603 - our own script, our own arguments
        ["/bin/bash", str(LAUNCHER), *args], cwd=REPO, stdin=subprocess.DEVNULL
    )

    # Stopping this job has to stop the recorder with it, cleanly, or the trap
    # that shuts the engine down never runs and a connection is left open.
    def pass_on(signum: int, _frame: object) -> None:
        say(f"signal {signum} - stopping the recorder")
        launcher.terminate()

    signal.signal(signal.SIGTERM, pass_on)
    signal.signal(signal.SIGINT, pass_on)

    time.sleep(SETTLE_SECONDS)
    if launcher.poll() is not None:
        say(f"the launcher exited at once with code {launcher.returncode}")
        notify("Pitwall - NOT RECORDING", f"{race.name}: the launcher exited immediately.")
        return launcher.returncode or 1
    ends = (race.start + timedelta(minutes=RECORD_AFTER_START)).astimezone()
    notify(
        "Pitwall - recording",
        f"{race.name} at {race.local:%H:%M}. Recording until {ends:%H:%M}. Lid open, plugged in.",
    )
    say(f"armed, pid {launcher.pid}; recording until {ends:%H:%M}")

    watch = SleepWatch(last=time.time())
    while launcher.poll() is None:
        time.sleep(WATCH_SECONDS)
        lost = watch.tick(time.time())
        if lost:
            say(f"THE MAC SLEPT for {lost / 60:.1f} min - the recording has a gap")
            notify(
                "Pitwall - Mac slept",
                f"{race.name}: {lost / 60:.0f} min lost. Keep the lid open, or laps will go on "
                "being missed.",
            )
    code = launcher.returncode
    recording = REPO / "data" / "raw" / f"{race.slug}.txt"
    size = recording.stat().st_size / 1e6 if recording.exists() else 0.0
    say(f"the launcher finished with code {code}; {recording.name} is {size:.1f} MB")
    if watch.naps:
        say(f"asleep for {watch.asleep / 60:.0f} min across {watch.naps} naps while recording")
    notify(*finish_message(race, size, code, watch))
    return code


def fire(now: datetime | None = None, *, dry_run_only: bool = False) -> int:
    moment = now or datetime.now(UTC)
    action, race = decide(moment, load_calendar())
    if race is None:
        say("no race near; nothing to do")
        return 0
    say(f"{action}: {race.name}, {race.location}, starts {race.local:%a %d %b %H:%M}")
    if action != "missed":
        warn_if_lid_closed(race)

    if action == "missed":
        notify(
            "Pitwall - race missed",
            f"{race.name} started at {race.local:%H:%M} and was not recorded. "
            "It can still be rebuilt from the archive.",
        )
        return 0

    if action == "wait":
        if not dry_run_only:
            race = current_start(race)
        arm_at = race.start - timedelta(minutes=ARM_LEAD)
        notify(
            "Pitwall - race today",
            f"{race.name} at {race.local:%H:%M}. The recorder starts itself at "
            f"{arm_at.astimezone():%H:%M}. Keep the Mac awake: lid open, plugged in.",
        )
        if dry_run_only:
            say(f"would hold the Mac awake and wait until {arm_at.astimezone():%H:%M}")
            return arm(race, dry_run_only=True)
        # Tied to this process, so it cannot outlive the job that wanted it.
        subprocess.Popen(  # noqa: S603
            ["/usr/bin/caffeinate", "-ims", "-w", str(os.getpid())], stdin=subprocess.DEVNULL
        )
        say(f"holding the Mac awake; waiting until {arm_at.astimezone():%H:%M}")
        wait_until(arm_at)
        race = current_start(race)
        warn_if_lid_closed(race)

    return arm(race, dry_run_only=dry_run_only)


def install() -> int:
    now = datetime.now(UTC)
    season = now.astimezone().year
    try:
        races = [race for race in fetch_schedule(season) if race.start > now]
    except Exception as error:  # noqa: BLE001 - any failure here means "no schedule"
        print(f"could not fetch the {season} schedule: {error}", file=sys.stderr)
        return 1
    if not races:
        print(f"no races left in {season}; nothing to schedule")
        return 0
    save_calendar(races)

    python = REPO / ".venv" / "bin" / "python"
    if not python.exists():
        print(f"no interpreter at {python}", file=sys.stderr)
        return 1
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(launchd_plist(races, now, python))
    plistlib.loads(PLIST.read_bytes())  # what was written must read back

    domain = f"gui/{os.getuid()}"
    subprocess.run(["/bin/launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)
    loaded = subprocess.run(
        ["/bin/launchctl", "bootstrap", domain, str(PLIST)], capture_output=True, text=True
    )
    if loaded.returncode != 0:
        print(f"launchctl would not load it: {loaded.stderr.strip()}", file=sys.stderr)
        return 1
    print(f"installed {PLIST}")
    return status()


def uninstall() -> int:
    subprocess.run(["/bin/launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    if PLIST.exists():
        PLIST.unlink()
    print(f"removed {LABEL}")
    return 0


def status() -> int:
    loaded = subprocess.run(
        ["/bin/launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, text=True
    )
    print(f"launchd job {LABEL}: {'loaded' if loaded.returncode == 0 else 'NOT LOADED'}")
    if not CALENDAR.exists():
        print("no calendar file; run --install")
        return 1
    now = datetime.now(UTC)
    print(f"\n{'race':<28}{'starts (local)':<20}fires at")
    for race in load_calendar():
        if race.start <= now:
            continue
        when = ", ".join(f"{t:%a %H:%M}" for t in firings(race))
        print(f"{race.name:<28}{race.local:%a %d %b %H:%M}    {when}")
    print(f"\nlog: {LOG}")
    return 0 if loaded.returncode == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--install", action="store_true", help="schedule every remaining race")
    group.add_argument("--uninstall", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--fire", action="store_true", help="what launchd runs")
    group.add_argument("--print-start", type=int, metavar="ROUND", help=argparse.SUPPRESS)
    parser.add_argument("--now", help="pretend it is this ISO time (with --fire --dry-run)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="with --fire: decide, notify and run the launcher's dry run, but start nothing",
    )
    args = parser.parse_args()

    if args.install:
        return install()
    if args.uninstall:
        return uninstall()
    if args.status:
        return status()
    if args.print_start is not None:
        season = datetime.now().year
        for race in fetch_schedule(season):
            if race.round == args.print_start:
                print(race.start.isoformat())
                return 0
        return 1
    if args.now and not args.dry_run:
        print("--now is only for --dry-run; a real firing uses the real clock", file=sys.stderr)
        return 2
    global QUIET  # noqa: PLW0603 - one process, one mode
    QUIET = QUIET or args.dry_run
    now = datetime.fromisoformat(args.now) if args.now else None
    if now is not None and now.tzinfo is None:
        now = now.astimezone()
    return fire(now.astimezone(UTC) if now else None, dry_run_only=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
