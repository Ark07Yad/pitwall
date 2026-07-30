#!/usr/bin/env python3
"""Regenerate the dashboard screenshot for the README.

Scripted rather than done by hand so it can be refreshed after every race, and
so the image in the README is always of the current build rather than whatever
the UI happened to look like months ago.

It starts the dashboard against a recording, waits for the race to reach a lap
where the engine is actually making a call - a screenshot of "waiting for the
race to develop" sells nothing - and then drives headless Chrome to capture it.

    python scripts/screenshot.py --out docs/dashboard.png

Requires Google Chrome, which macOS usually has. No extra Python dependencies:
Playwright would pull a second browser engine for one PNG.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def chrome_binary() -> str:
    if Path(CHROME).exists():
        return CHROME
    for name in ("google-chrome", "chromium", "chromium-browser"):
        if found := shutil.which(name):
            return found
    raise SystemExit("no Chrome or Chromium found; install one or pass --chrome")


def state(port: int) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5) as r:
        return json.loads(r.read())


def wait_for_a_real_call(port: int, *, lap: int, timeout: float) -> dict:
    """Block until the engine is advising, not waiting.

    Both conditions matter. Before the pace fit is identified the panel
    (correctly) refuses to advise, and a screenshot of that is a screenshot of
    nothing.
    """
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        try:
            last = state(port)
        except Exception:
            time.sleep(1)
            continue
        advice = last.get("advice") or {}
        if last.get("lap", 0) >= lap and advice.get("call") and not advice.get("refused"):
            return last
        time.sleep(1)
    raise SystemExit(
        f"never reached lap {lap} with a live recommendation "
        f"(got lap {last.get('lap')}, advice {last.get('advice')})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, default=Path("data/raw/2026-hungary-race.txt"))
    parser.add_argument("--out", type=Path, default=Path("docs/dashboard.png"))
    parser.add_argument("--lap", type=int, default=34, help="wait until this lap")
    parser.add_argument("--skip", type=float, default=62.0, help="minutes to fast-forward")
    parser.add_argument("--speed", type=float, default=20.0)
    parser.add_argument("--driver", default="LEC")
    parser.add_argument("--port", type=int, default=8079)
    parser.add_argument("--width", type=int, default=1600)
    # Tall enough for the full 22-car field plus the footer, with no
    # dead space below it. A 2026 grid is 22; check this if that changes.
    parser.add_argument("--height", type=int, default=850)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--chrome", default="")
    args = parser.parse_args()

    if not args.recording.exists():
        raise SystemExit(f"no recording at {args.recording}")
    chrome = args.chrome or chrome_binary()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pitwall",
            "dashboard",
            "--replay",
            str(args.recording),
            "--speed",
            str(args.speed),
            "--skip",
            str(args.skip),
            "--driver",
            args.driver,
            "--port",
            str(args.port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        print(f"waiting for lap {args.lap} with a live call...", flush=True)
        snapshot = wait_for_a_real_call(args.port, lap=args.lap, timeout=args.timeout)
        print(
            f"  lap {snapshot['lap']}/{snapshot['total_laps']} - "
            f"{snapshot['advice']['tla']} {snapshot['advice']['call']}",
            flush=True,
        )

        subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--force-device-scale-factor=2",
                f"--screenshot={args.out.resolve()}",
                f"--window-size={args.width},{args.height}",
                # The page paints from a websocket push, so give it real time to
                # connect and receive one. A virtual-time budget alone races it.
                "--virtual-time-budget=8000",
                f"http://127.0.0.1:{args.port}",
            ],
            check=True,
            capture_output=True,
            timeout=90,
        )
    finally:
        server.terminate()
        server.wait(timeout=10)

    size = args.out.stat().st_size / 1024 if args.out.exists() else 0
    if size < 20:
        raise SystemExit(f"{args.out} looks empty ({size:.0f} KB); the page probably never painted")
    print(f"wrote {args.out} ({size:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
