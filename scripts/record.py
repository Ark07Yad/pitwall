#!/usr/bin/env python3
"""Record a live session, and keep recording it.

FastF1's recorder is a good client but a fragile long-running process: the docs
note the connection tends to drop after roughly two hours, which is exactly the
length of a Grand Prix. This wraps it in a supervisor that restarts and appends,
so a dropped socket costs a few seconds of feed rather than the second half of
the race.

Usage:
    python scripts/record.py data/raw/hungary_2026_race.txt

Start it ~5 minutes before the session. Stop with Ctrl-C.
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RESTART_DELAY = 3.0
# Below this, assume the feed is refusing us rather than merely dropping - back
# off harder so we do not hammer F1's endpoint in a tight loop.
MIN_HEALTHY_RUN = 20.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="file to append the raw feed to")
    parser.add_argument("--max-restarts", type=int, default=200)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    stopping = False

    def handle_stop(*_: object) -> None:
        nonlocal stopping
        stopping = True
        print("\n[record] stopping after current attempt", flush=True)

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    print(f"[record] writing to {args.output}", flush=True)
    restarts = 0
    backoff = RESTART_DELAY

    while not stopping and restarts < args.max_restarts:
        started = time.monotonic()
        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"[record] {stamp} connecting (attempt {restarts + 1})", flush=True)

        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "fastf1.livetiming",
                    "save",
                    str(args.output),
                    "--append",
                ],
                check=False,
            )
        except KeyboardInterrupt:
            break

        if stopping:
            break

        ran_for = time.monotonic() - started
        restarts += 1

        if ran_for < MIN_HEALTHY_RUN:
            backoff = min(backoff * 2, 60.0)
            print(
                f"[record] exited after {ran_for:.1f}s - backing off {backoff:.0f}s",
                flush=True,
            )
        else:
            backoff = RESTART_DELAY
            print(f"[record] ran {ran_for / 60:.1f} min, reconnecting", flush=True)

        time.sleep(backoff)

    size_mb = args.output.stat().st_size / 1e6 if args.output.exists() else 0.0
    print(f"[record] done - {args.output} ({size_mb:.1f} MB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
