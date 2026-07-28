# Pitwall

[![CI](https://github.com/Ark07Yad/pitwall/actions/workflows/ci.yml/badge.svg)](https://github.com/Ark07Yad/pitwall/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**A live Formula 1 race strategy engine.**

Pitwall consumes Formula 1's live timing stream, fits tyre degradation and safety-car models
in-session, and simulates the remainder of the race to answer one question: **should we pit now?**

Every recommendation is committed to this repository with a timestamp *before* the lap it refers
to. The accuracy log is public and includes the calls it got wrong.

> **Status: Phase 3 of 5.** Ingest, replay, race state, clean-lap filtering, fuel correction,
> degradation and the safety-car hazard all feed a Monte Carlo simulation that produces pit calls.
> The live SignalR parser and the dashboard are next — see [the plan](docs/PLAN.md).

---

## Why this exists

Most public F1 projects predict *outcomes* from historical data after the fact. A pit wall does
something harder: it makes *decisions* in real time, under uncertainty, against rivals who react.
Pitwall is built around that difference.

| | Typical F1 repo | Pitwall |
|---|---|---|
| Timing | Offline, post-race | Real-time, under a latency budget |
| Output | "Who will win?" | "Pit now, or lap +3?" |
| Rivals | Assumed static | Modelled as reactive agents |
| Validation | Often none | Pre-registered calls, scored on calibration |

---

## Quickstart

Requires Python 3.11+. [`uv`](https://docs.astral.sh/uv/) handles the interpreter for you.

```bash
uv sync --extra dev
uv run pytest
```

### Record a live session

Run this ~5 minutes before a session starts. It supervises the connection and reconnects, because
F1's feed reliably drops after about two hours — roughly the length of a Grand Prix.

```bash
uv run python scripts/record.py data/raw/2026-hungary-race.txt
```

It is safe to start early: a connection made outside a session returns one state snapshot and then
nothing, and the supervisor detects that and backs off to five-minute retries rather than
reconnecting in a loop.

### Record unattended

Races happen at awkward times. This waits for the session, holds off system sleep, records, and
stops on its own:

```bash
nohup ./scripts/scheduled_record.sh "2026-07-26 13:30" data/raw/2026-hungary-race.txt 210 &
```

Arguments are start time (local), output file, and minutes to record. Progress goes to
`data/raw/<name>-runner.log`.

**Leave the machine plugged in, on wi-fi, and with the lid open.** macOS sleeps on lid close
regardless of `caffeinate`, and a sleeping Mac records nothing.

### Replay one

```bash
uv run pitwall topics data/raw/2026-hungary-race.txt      # what's in the recording
uv run pitwall replay data/raw/2026-hungary-race.txt      # fold it into race state
uv run pitwall replay data/raw/2026-hungary-race.txt --speed 60 --follow
uv run pitwall laps   data/raw/2026-hungary-race.txt      # extract and filter laps
uv run pitwall hazard                                    # per-circuit safety-car risk
uv run pitwall strategy data/raw/2026-hungary-race.txt --lap 30 --driver LEC
```

`--speed 60` replays a two-hour race in about two minutes with a live timing screen.

### Clean-lap filtering

Degradation is a tenths-per-lap effect buried under much larger ones — an in-lap is ~20 s slow, a
safety-car lap ~30 s. `pitwall laps` extracts completed laps and reports what it excluded and why:

```
881 clean of 1,405 laps (62.7% kept, 524 excluded)

  following within the dirty-air threshold    429
  entered the pits                             92
  left the pits                                45
  safety car, VSC or red flag                  34
  lap 1 (standing start)                       22
  lap time implausible for a racing lap         2
```

Rejections are reported as counted *reasons* rather than a boolean, because the breakdown is what
shows the filter is behaving — on the 2026 Hungarian GP the 22 first-lap exclusions match the grid
exactly, and the in/out-lap counts match the 47 recorded pit stops.

### Pit calls

`pitwall strategy` replays a recording to any lap and asks what the engine would have said there.
2,000 full race simulations take 0.14 s, so a twelve-option decision lands in under two seconds:

```
Race @ Hungaroring  lap 30/70

LEC P3, lap 30 (3,000 sims)
  → PIT now on SOF
     expected P2.41, margin +0.19 to next option

  option              exp. pos    top3  points    gain
  now on SOF              2.41  81.9%   98.7%   64.4%
  now on MED              2.60  79.2%   98.8%   61.0%
  lap +3 on SOF           2.64  78.1%   98.9%   59.3%
  ...

  undercut threats:
    HAM  +0.7s behind   P(jumps us) 45.9%
```

Three things carry the realism. **Track position is enforced** — cars cannot pass through each
other, so a quick car stuck in a train stays stuck, which is what makes an undercut work.
**Safety cars compress the field**, collapsing a twenty-second lead and discounting a stop taken
under one. **Rivals are not static** — their stops are sampled from a policy distribution, so the
answer accounts for them covering or attacking.

The suite asserts textbook dynamics rather than just unit behaviour: starting ahead is worth
something, a faster car is held up behind a slower one, safety cars erase a large lead, and the
undercut works. If those break the model is wrong whatever the unit tests say.

⚠️ The *timing* of a stop is on much firmer ground than the *compound*. Compound choice inherits the
single-race degradation confounding documented in [the logbook](docs/logbook.md) — at Hungary the
compounds were used in separate phases of the race, so their degradation rates are not separately
identified. More races break that; one cannot.

---

## Architecture

```
RaceFeed  ──►  RaceStateReducer  ──►  Models  ──►  Simulation  ──►  Decision
(ingest)       (fold events)         (fit)        (Monte Carlo)    (pit or stay)
```

**Two design rules carry the whole system:**

1. **Everything is a `RaceFeed`.** Live websocket, recorded file, REST API — nothing downstream
   knows which. This is what lets the same code be developed offline and run live.
2. **State is only ever produced by folding events.** No model, heuristic, or UI callback writes
   to it. Given the same recording the reducer produces byte-identical state every time, which is
   what makes replay-based regression tests — and the backtest — trustworthy.

### Layout

```
src/pitwall/
├── feed/
│   ├── base.py       RaceFeed ABC, FeedEvent, .z inflation
│   └── replay.py     ReplayFeed — the development workhorse
├── state/
│   ├── merge.py      delta merging (the most safety-critical code here)
│   ├── models.py     typed projections: RaceState, CarState, Stint
│   └── reducer.py    folds events into state
├── laps/
│   ├── records.py    completed laps with the context to judge them
│   └── clean.py      clean-lap filtering, with counted reject reasons
└── models/
    ├── fuel.py       physics fuel correction, usable from lap 1
    ├── pace.py       joint fit: pace, fuel trend, per-compound degradation
    └── safety_car.py per-circuit hazard with empirical-Bayes shrinkage
scripts/record.py     supervised live recorder
scripts/fetch_history.py  resumable safety-car history fetch
docs/PLAN.md          the full five-phase plan
docs/logbook.md       what broke and what the data taught me
```

### Two details worth knowing

**The feed sends deltas, not snapshots.** After the initial dump, `{"Lines": {"4": {"Position":
"3"}}}` means "car 4 moved to P3" — not "the timing table now contains only car 4". Overwriting
instead of merging doesn't crash; it silently drops state and still renders a plausible-looking
screen. `state/merge.py` handles this, including the feed's habit of patching arrays with
index-keyed objects, and it's the most heavily tested module in the repo.

**Recorded lines are Python reprs, not JSON.** The common approach is to convert them by replacing
`'` with `"`, which corrupts any payload containing an apostrophe — race control messages routinely
contain them. Pitwall uses `ast.literal_eval`, which parses Python literals natively and safely.
There's a regression test for exactly this.

---

## Data sources

Everything used here is free.

| Purpose | Source |
|---|---|
| Live timing | F1 SignalR feed — no key, no account |
| Backtest telemetry, 2023+ | [OpenF1](https://openf1.org/) free tier |
| Laps and telemetry, 2018+ | [FastF1](https://docs.fastf1.dev/) |
| Results and standings, 1950+ | [Jolpica-F1](https://github.com/jolpica/jolpica-f1) |

### Safety-car hazard

No public dataset publishes per-circuit safety-car rates, so `scripts/fetch_history.py` builds one
from 2022–2026 race control data and `pitwall hazard` fits a discrete-time hazard over it.

The strongest signal is that lap 1 is a different regime entirely — a 22% chance of a safety car or
VSC, against about 2% for any other lap:

```
  baseline per-lap hazard by race phase:
    lap1   0.2234
    early  0.0207
    mid    0.0195
    late   0.0168
    final  0.0119

  circuit factor (shrunk, prior weight 3):
    Melbourne                 2.33x  (5 races)
    Zandvoort                 1.33x  (4 races)
    ...
    Barcelona                 0.48x  (4 races)
```

Laps already running under a safety car are excluded from exposure — the question is "given none is
out, does one get deployed" — and circuit factors are shrunk toward the field average, since four
races per circuit cannot justify a raw ratio.

Note the F1 API allows 500 calls an hour, so a full fetch takes a couple of runs. The script is
resumable: re-run the same command and it picks up where it stopped.

---

## Disclaimer

Unofficial and unaffiliated with Formula 1. It uses F1's public live timing endpoint the same way
open-source clients like FastF1 and f1-dash do: one connection, no redistribution of the raw feed,
non-commercial use only. Jolpica is volunteer-funded — its responses are cached rather than polled.

MIT licensed.
