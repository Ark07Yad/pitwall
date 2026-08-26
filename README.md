# Pitwall

[![CI](https://github.com/Ark07Yad/pitwall/actions/workflows/ci.yml/badge.svg)](https://github.com/Ark07Yad/pitwall/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**A live Formula 1 race strategy engine.**

Pitwall consumes Formula 1's live timing stream, fits tyre degradation and safety-car models
in-session, and simulates the remainder of the race to answer one question: **should we pit now?**

Every recommendation is committed to this repository with a timestamp *before* the lap it refers
to. The accuracy log is public and includes the calls it got wrong.

![The Pitwall dashboard mid-race: a 22-car timing tower with team colours, tyre badges, lap-time
sparklines and stint bars on the left; on the right the current pit call for Leclerc, the Monte
Carlo distribution of his finishing positions, ranked alternatives, an undercut threat from
Antonelli, safety-car risk and the fitted pace model.](docs/dashboard.png)

*Lap 34 of the 2026 Hungarian GP, replayed through the engine. Leclerc is P3; stopping now on hards
comes out at an expected P4.58, 0.33 clear of the next option, with Antonelli one second back at a
41% chance of jumping him. The histogram is the simulation's actual output — the spread from P1 to
P7 is the part a single expected value hides. Bottom right, the model reports the confounding in
its own degradation estimates rather than presenting them as fact. Regenerate with
`python scripts/screenshot.py`.*

> **Status: all five phases built.** Live ingest, race state, clean-lap filtering, fuel
> correction, degradation and a per-circuit safety-car hazard feed a Monte Carlo simulation that
> produces pit calls, and every call is logged, committed before the lap it refers to, and scored
> against what happened. What remains is races — see [the plan](docs/PLAN.md).

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

### The dashboard

```bash
uv run pitwall dashboard                                    # live
uv run pitwall dashboard --replay data/raw/2026-hungary-race.txt --speed 20 --skip 62 --driver LEC
```

Pushed over a websocket to `http://127.0.0.1:8000`, and it paints from a REST snapshot on load so
it is correct from the first frame rather than after a round trip.

**The timing tower** carries team colours, tyre-compound badges with age, lap-time sparklines
(green improving, red falling away), stint bars showing each car's strategy so far, session-fastest
in purple, and positions gained or lost since the grid. Click any car to advise it instead.

**The right column** is the engine showing its working:

- **The call**, with its margin over the next option — and where that margin is thin, it says
  "marginal" rather than dressing a coin-flip as a decision.
- **The finishing distribution** from the Monte Carlo, clipped to the positions holding 95% of the
  probability. A tight spread around P4 and a coin-flip between P2 and P8 have the same mean and
  mean very different things; the histogram is where that shows.
- **Undercut threats** — who can jump us by stopping now, and how likely, against our own planned
  stop rather than against never stopping.
- **Race risk** — safety-car probability over the next 5, 10 and 20 laps, plus the chance a given
  car retires and how many DNFs to expect, both from per-circuit hazards fitted on 103 races.
- **The pace model** — race-lap trend, per-compound degradation, residual σ and r², plus any
  warning the fit carries. When the design is not identified it says so and no call is offered.

Because it runs off a `RaceFeed` it is identical live or on a recording — the replay form
reproduces the Hungarian GP from lap 30 in about a minute, so it can be demonstrated on any
Tuesday rather than once a fortnight. The simulation runs in a worker thread, so ingest and the
screen keep going through the second or two a decision takes.

### Run it live

On a race day this is the whole system in one process — one connection to F1's endpoint, which
records the raw frames, folds them, fits the models, publishes a call every lap, and commits each
call to the ledger as it is made:

```bash
uv run pitwall dashboard --record data/raw/2026-netherlands-race.txt \
    --log-predictions --session "2026 Dutch GP"
```

`scripts/race_day.sh` wraps that for an unattended run: it waits for the session, checks the git
identity *before* the two-hour wait rather than failing silently for the whole race, holds off
system sleep, and stops on its own.

Predictions are written only when `LapCount` says a race is running, so a dashboard left going
through practice records nothing; only once per lap, so the reconnection that a two-hour feed
guarantees cannot double-count a call; and never fatally, because the race is not re-runnable. The
CLI refuses to *commit* calls made from a `--replay`, since the recording already contains the
outcome and the commit timestamp is the only thing the ledger is worth anything for.

For just the timing screen, without the engine:

```bash
uv run pitwall live --record data/raw/2026-netherlands-race.txt
```

Connects to F1's live timing stream, folds it in real time, and redraws a timing screen. It works
between sessions too — the endpoint replies with the last session's snapshot, then keepalive pings.

This is the part FastF1 does not do. Its client connects to the same endpoint and writes frames to
disk; its documentation states that it "is *not* possible to do real-time processing of the data".
`SignalRFeed` parses them as they arrive, and is a drop-in `RaceFeed` alongside `ReplayFeed`, so
everything downstream is identical whether the race is happening now or happened in July.

Measured against the live endpoint: **17 events in 0.32 s, decode p50 0.05 ms, p99 4.6 ms.**

Two protocol notes, established by probing since none of this is documented. The classic
`/signalr/negotiate` path that most public clients use now answers **401**. And `/signalrcore`
accepts an **unauthenticated** connection despite FastF1 wiring in an F1 TV token — no login is
required.

**Reconnection is tested, not hoped for.** F1's feed drops after roughly two hours and a Grand Prix
is two hours, so a mid-race drop is the expected case. The suite drives the retry loop through
injected drops, escalating backoff, the cap, the reset after a good connection, and cancellation.
Against the live endpoint, with the silence timeout cut to force real drops, it completed **11
reconnections in 75 seconds** — each a full negotiate, handshake and re-subscribe — with race state
intact after every one.

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
uv run pitwall pitloss                                   # per-circuit pit loss
uv run pitwall degradation                               # pooled tyre-degradation prior
uv run pitwall strategy data/raw/2026-hungary-race.txt --lap 34 --driver LEC
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
Race @ Hungaroring  lap 34/70

LEC P3, lap 34 (3,000 sims)
  → PIT now on HAR
     expected P4.85, margin +0.25 to next option

  option              exp. pos    top3  points    gain
  now on HAR              4.85  37.5%   95.6%   24.5%
  now on MED              5.09  33.8%   95.6%   24.6%
  now on SOF              5.16  32.1%   95.6%   23.9%
  ...

  undercut threats:
    ANT  +0.9s behind   P(jumps us) 46.3%
```

Three things carry the realism. **Track position is enforced** — cars cannot pass through each
other, so a quick car stuck in a train stays stuck, which is what makes an undercut work.
**Safety cars compress the field**, collapsing a twenty-second lead and discounting a stop taken
under one. **Rivals are not static** — their stops are sampled from a policy distribution, so the
answer accounts for them covering or attacking.

The suite asserts textbook dynamics rather than just unit behaviour: starting ahead is worth
something, a faster car is held up behind a slower one, safety cars erase a large lead, and the
undercut works. If those break the model is wrong whatever the unit tests say.

The *timing* of a stop rests on how much one costs, and that is now measured per circuit rather
than assumed — see below.

### Tyre degradation, and where the evidence stops

Degradation is fitted as `α_c·age + γ_c·age²` — the quadratic being the cliff, the point where a
tyre stops wearing and starts falling away. `γ` is constrained non-negative, because a negative
quadratic describes a tyre that gets *faster* the longer it runs, and extrapolating one would
actively reward never stopping.

On synthetic data the estimator recovers a true cliff of 0.00300 as 0.00297. **On real races it
fits essentially zero** — Zandvoort's hard tyre 0.00000, Hungary's 0.00008 — and that is not the
estimator being too weak: regenerated at the real 0.88 s residual, a cliff of that size still comes
back. Within the stint lengths teams actually run, degradation at these circuits really is close to
linear.

The cliff is real; it just lives past the point anyone runs a tyre. Which is the more important
limitation:

> **The model cannot see past its own data, and now says so.** The longest hard stint at Zandvoort
> was 36 laps. Asked what lap 50 looks like, a straight line promises a tyre that lasts forever —
> and staying out is precisely the option that benefits from that optimism. Teams pit *before* the
> cliff, so the steep part of the curve is missing *because* it is steep.

### Pooling across races, and survivorship

A cliff needs stints long enough to contain one, which no single race provides. `scripts/
fetch_degradation.py` pools **95 races and 85,587 laps** out of the local FastF1 cache — no API
calls — by stripping each race down to the part of a lap attributable to tyre age and pooling
those deltas, which mean the same thing at Monaco and Monza.

Pooling did not reveal a cliff, and why is the more useful result:

| compound | age 0–4 | 10–14 | 20–24 | 30–34 | 50–54 |
|---|---|---|---|---|---|
| HAR | +0.10 | +0.48 | +0.81 | +0.84 | +1.55 |
| SOF | −0.29 | +0.21 | +0.21 | **−0.61** | — |

A thirty-lap-old soft cannot be faster than a fifteen-lap-old one. That is **survivorship**: a car
whose tyres are going away gets pitted, so the sample still circulating at high age is made of
exactly the stints that were *not* degrading. The selection strengthens with age, and more races
sharpen the artifact rather than removing it — which is why the observed curve is concave where
physics says convex, and why an unconstrained quadratic through it comes back negative.

So the shape is fitted only up to where the binned curve stops rising — found per compound, soft at
19, hard at 29 — and **continued linearly beyond rather than flattening**. Flattening is the
artifact; a straight line is the smallest claim that is not knowingly wrong.

```
uv run pitwall degradation

  compound       linear       cliff  trusted  seen     @20     @40     @55
  HAR          +0.0369   +0.00000       29    78  +0.74s  +1.48s  +2.03s
  MED          +0.0307   +0.00000       29    77  +0.61s  +1.23s  +1.69s
  SOF          -0.0148   +0.00228       19    54  +0.61s  +2.05s  +3.12s

  circuit factor (shrunk toward 1.0):
    Sakhir 2.48x   Spa 2.27x   Barcelona 2.19x   ...   Zandvoort 0.50x   Montréal 0.39x
```

Circuits whose fitted scale comes out *negative* are rejected rather than shrunk — Melbourne's raw
scale was −0.64, and shrinking that toward 1.0 produced a plausible-looking 0.06x, which is how a
sign error survives review. They fall back to the field average with a warning.

The in-session fit is blended toward this prior in proportion to how many laps back it, so a
well-observed compound keeps its own rate and a thin one borrows the pooled shape.

Every fit records `observed_max_age` per compound, and any option needing a tyre older
than that is flagged. Of the 49 calls made live at the 2026 Dutch GP, **31 rest on tyre ages never
observed** — and the flag separates them properly: staying out on lap 71 needs a 23-lap tyre where
33 were seen, while staying out on lap 26 needs 49. Same call, entirely different standing. With
the pooled prior supplying evidence out to 78 laps, **none of the 49 still rest on unobserved tyre
ages**; see [the re-scores](reports/rescore/README.md), which are post-hoc and kept well away from
the live ledger.

⚠️ The *timing* of a stop is on much firmer ground than the *compound*. Compound choice inherits the
single-race degradation confounding documented in [the logbook](docs/logbook.md) — at Hungary the
compounds were used in separate phases of the race, so their degradation rates are not separately
identified. More races break that; one cannot.

### The track record

Every call is written to an append-only log and **committed before the lap it refers to**. The
commit timestamp is the evidence: `git log predictions/` shows when each was made. Predictions
stage only the log file, never source, so no commit can be argued to have tuned the model to fit.

```bash
uv run pitwall backtest data/raw/2026-hungary-race.txt --laps 16,24,32,40,48 --drivers NOR,VER,LEC
uv run pitwall report   data/raw/2026-hungary-race.txt --log predictions/2026-hungarian-gp.jsonl
```

`backtest` re-folds the recording from scratch for every lap, so a decision at lap 24 sees only
laps 1–24 — no leak from the finish into a forecast of it. The report grades the log against the
actual classification, and is generated rather than written so the bad weekends cannot be quietly
skipped.

### Forecasting the whole field

A recommendation log cannot be calibrated. The engine advises **one** car — a pit wall only has one
to advise — so a race yields ~50 calls, nearly all on a leader who was never going to move. Every
`p_points` sits at 0.98, the baseline scores a perfect 0.0000, and the reliability diagram has one
populated bucket. Nothing there is measurable.

So alongside each call the engine forecasts **every car**, which costs **one** simulation rather
than one per car — 0.16 s against the ~37 s it would take to evaluate a full recommendation for all
22 — because the field is simulated jointly anyway. That turns 49 concentrated claims into 1,078
spread across cars whose outcomes genuinely differ:

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (win) | 0.0210 | 0.0427 | **+50.8%** |
| Brier (top 3) | 0.0412 | 0.0390 | −5.6% |
| Brier (points) | 0.0554 | 0.0705 | +21.5% |

And a reliability diagram that says something:

| confidence band | n | said | happened |
|---|---|---|---|
| 0%–20% | 872 | 1.0% | 1.8% |
| 20%–40% | 51 | 29.0% | 33.3% |
| 40%–60% | 24 | 48.8% | 16.7% |
| 60%–80% | 47 | 73.0% | 59.6% |
| 80%–100% | 84 | 91.8% | 97.6% |

The engine is **overconfident in the middle** — when it says 73% it happens 60% of the time — and
slightly *under*confident at the top. That is a real, actionable flaw, and it is the first one this
project has been able to state at all, because leader-only calls could not reveal it.

Forecasts are kept in their own file and committed a lap at a time rather than a car at a time:
they are a different claim from a recommendation, settled at the flag with no judgement required.

### The current scorecard

28 leak-free predictions from the 2026 Hungarian GP:

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (top 3) | 0.1961 | 0.2143 | +8.5% |
| Brier (points) | 0.1327 | 0.1429 | +7.1% |
| Mean position error | 3.69 | 3.50 | — |

The baseline assumes every car finishes where it currently runs. In F1 that is a strong benchmark,
not a straw man — and on one race this engine barely beats it. That is the honest position.

An earlier version of this table reported +33.2% skill. It was wrong, and the correction is
instructive: a bug placed the race leader at the back of the grid, so the *baseline* was also being
scored against corrupted positions and looked far worse than it was. Fixing the bug cut the
apparent skill by an order of magnitude. Both the bug and the inflated number are written up in
[the logbook](docs/logbook.md).

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
    ├── degradation.py  pooled tyre wear, selection-aware
    ├── pit_loss.py   per-circuit green-flag pit loss, shrunk
    └── safety_car.py per-circuit hazard with empirical-Bayes shrinkage
scripts/record.py     supervised live recorder
scripts/fetch_history.py  resumable safety-car history fetch
scripts/fetch_pit_loss.py resumable pit-loss measurement
scripts/fetch_degradation.py  pooled degradation history
scripts/circuit_aliases.py  derive circuit-name aliases from F1's session info
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

The strongest signal is that lap 1 is a different regime entirely — a 21% chance of a safety car or
VSC (`pitwall hazard --kind any`; the default reports safety cars alone), against about 2% for any
other lap:

```
  baseline per-lap hazard by race phase:
    lap1   0.2136
    early  0.0195
    mid    0.0214
    late   0.0203
    final  0.0137

  circuit factor (shrunk, prior weight 3):
    Melbourne                 2.24x  (5 races)
    Zandvoort                 1.28x  (4 races)
    ...
    Yas Island                0.49x  (4 races)
```

Laps already running under a safety car are excluded from exposure — the question is "given none is
out, does one get deployed" — and circuit factors are shrunk toward the field average, since four
races per circuit cannot justify a raw ratio.

Note the F1 API allows 500 calls an hour, so a full fetch takes a couple of runs. The script is
resumable: re-run the same command and it picks up where it stopped.

---

### Pit loss

The time a stop costs is the most stable constant in the sport — it is fixed by pit lane geometry
and a speed limit, not by car performance. Monza measures 25.2, 25.3, 25.8 and 25.3 seconds across
four consecutive seasons. That stability is exactly why modelling it as one flat number everywhere
was expensive: the constant is reliable, it is just *different everywhere*, and the calendar spans
about nine seconds.

`scripts/fetch_pit_loss.py` measures it from 2022–2026 lap data and `pitwall pitloss` fits it:

```
Green-flag pit loss from 87 races, 1981 stops

  field median 22.17s  (spread 1.39s)
  botched stops: 5.0% of stops, +2.0s then mean +3.81s more
  so a stop costs 22.17s at the median, 22.45s on average

  per circuit (shrunk, prior weight 2 races):
    circuit                   shrunk     raw     sd  races  stops
    Spa-Francorchamps         19.47s  18.40s  1.60s      5    101
    Miami                     20.46s  19.78s  1.55s      5     73
    ...
    Monza                     24.24s  25.29s  1.15s      4     92
    Lusail                    25.55s  27.81s  1.32s      3     69
```

What is measured is the quantity the simulation actually adds — total time lost against staying
out, in-lap delta plus out-lap delta — against a *local* per-driver baseline, so fuel load, track
evolution and driver pace cancel rather than needing correction. Spa comes out at 18.40 s raw,
which is independently the number this sport quotes as the cheapest stop of the era.

Green-flag stops only: a stop under a safety car is cheaper because the field is crawling, and the
simulation discounts that separately. Races contribute their median rather than their stops, so one
wet afternoon with forty measurable stops cannot outvote three clean ones, and circuits are shrunk
toward the field median because five races is not enough to justify a raw constant.

**Stops are not symmetric, so they are not drawn symmetrically.** A stop cannot go meaningfully
*better* than a clean one — the pit lane has a speed limit and the stationary time has a floor —
but it can go very much worse. The simulation draws ordinary scatter around the circuit median plus,
5% of the time, an exponential excess for a stop that went wrong. That is the difference between a
median stop and an *expected* one: 22.17 s against 22.45 s across the calendar, and the expensive
futures are exactly the ones a marginal call turns on.

Two things keep that tail from being too fat, which would bias the engine against pitting for a
reason that is not real. Served time penalties are excluded — they are added to the stationary time
and read as botched stops in lap data, and leaving them in roughly doubles the apparent rate of
disasters. And the rate subtracts what ordinary scatter already explains: with a spread of 1.4 s
about 7% of perfectly clean stops clear +2 s on their own, so counting those as botched would
double-count them. Fitted on 1,981 stops, the mixture reproduces the empirical mean excess exactly
and P(stop >2 s slow) to within 0.2 points.

Above +15 s the model deliberately stops: that is a front wing change, a repair, or an uncaught
penalty — a different event, not a routine stop, and not one this model claims to describe.

### A note on circuit names

These models are fitted on FastF1's `Location` but queried at runtime with the name the live feed
sends, `Meeting.Circuit.ShortName`. **Nine of twenty-seven circuits spell those differently** —
Hungaroring/Budapest, Catalunya/Barcelona, Singapore/Marina Bay, Interlagos/São Paulo — and the
mismatch was silent: the lookup returned the neutral default and nothing reported it. The 2026
Hungarian GP ran on a 1.0x safety-car factor when the fitted value was 0.58x.

The alias table is *derived*, never recalled — `scripts/circuit_aliases.py` reads both spellings
out of F1's own session info for every cached race and prints the pairs that disagree. A wrong
entry here maps one circuit's history onto another and nothing errors.

---

## Disclaimer

Unofficial and unaffiliated with Formula 1. It uses F1's public live timing endpoint the same way
open-source clients like FastF1 and f1-dash do: one connection, no redistribution of the raw feed,
non-commercial use only. Jolpica is volunteer-funded — its responses are cached rather than polled.

MIT licensed.
