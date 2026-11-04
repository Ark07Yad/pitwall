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

### Without anybody remembering

Two of the first five races this was meant to record were lost the same way: the launcher was
tested, the dry run had passed the night before, and nobody ran it on Sunday. The step that failed
was a person remembering, so it is no longer a person's:

```bash
.venv/bin/python scripts/auto_arm.py --install
```

That schedules a launchd agent for every remaining race. Three hours before each one it posts a
notification, holds the Mac awake, waits, runs the launcher's `--dry-run`, and starts the launcher
only if that says OK — the runbook's own order. It refuses to start anything while another recorder
is running, passes a stop signal on to the launcher so the feed connection is always closed, and
exits quietly when it fires on the same date next year. It cannot open a closed lid.

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

**A wet phase is treated as a different race.** Every reason above judges a lap on its own; this
one judges it against the track. Laps on intermediate or wet tyres are dropped — the model has no
rates for them — and so are slick laps run before the track dried, starting six laps after the
field leaves wet tyres. The boundary is read off what the field is running rather than the rain
sensor: a lap is wet when more than one car in ten ran it on wet-weather tyres.

It exists because of the 2026 Bahrain GP in Malaysia, which was recorded whole and produced no
call at all. Eight laps on intermediates at the start bent the single race-lap trend for the whole
afternoon — −4.3 s/lap at lap 7, still −0.24 at the flag — and the fit was refused on every lap it
could be attempted. Fitted on the dry phase alone it is usable from lap 31, at 0.025–0.033 s/kg.
Across eleven recordings the usable count goes *down* slightly, 107 to 101: the change removes
fits made in the rain (24 of the 41 laps lost) and adds the dry ones that were being thrown away.

### Pit calls

`pitwall strategy` replays a recording to any lap and asks what the engine would have said there.
2,000 full race simulations take 0.14 s, so a twelve-option decision lands in under two seconds:

```
Race @ Hungaroring  lap 34/70

LEC P3, lap 34 (3,000 sims)
  → now on SOF marginally ahead; no clear call
     expected P5.11, margin +0.01 to next option

  option              exp. pos    top3  points    gain
  now on SOF              5.11  24.8%   97.3%   17.4%
  now on MED              5.13  24.5%   97.3%   14.2%
  now on HAR              5.29  20.1%   97.3%   10.2%
  ...

  undercut threats:
    ANT  +0.9s behind   P(jumps us) 47.4%
```

Three things carry the realism. **Track position is enforced** — cars cannot pass through each
other, so a quick car stuck in a train stays stuck, which is what makes an undercut work, and how
hard it is to get past is measured per circuit. **Safety cars compress the field**, collapsing a
twenty-second lead and turning a stop under one into lost places rather than lost time; a VSC
does neither. **Rivals are not static** — their stops are sampled from a policy distribution, so
the answer accounts for them covering or attacking. The passing and safety-car numbers are
described under [Passing, and what a safety car does to a stop](#passing-and-what-a-safety-car-does-to-a-stop).

The suite asserts textbook dynamics rather than just unit behaviour: starting ahead is worth
something, a faster car is held up behind a slower one, safety cars erase a large lead, and the
undercut works. If those break the model is wrong whatever the unit tests say.

The *timing* of a stop rests on how much one costs, and that is now measured per circuit rather
than assumed — see below.

**Clear about the lap, torn about the tyre.** The example above reads "no clear call", and that is
the usual shape of a stop call: the next-best option is the same stop on another compound, so the
gap to it is a few hundredths of a place. That margin answers "which option", and is right to be
unsure. It does not answer the question a team's stop can grade — stop now or not yet — so every
call also records `soon_margin`, the best stop within three laps against the best option that is
not. Run across the field at Mexico City, laps 32–42, 52 calls said stop within three laps and not
one cleared the bar on the old margin.

**Every car, not just the leader.** From Zandvoort to Mexico City the live engine advised one car,
and with no `--driver` that was the leader — the car least likely to be told to stop. Four races
produced 106 live calls and not one clear "stop soon" to set against what a team did. Since
November, once that call is out, every other running car is advised from the same fit and the
same simulation settings, marked `focus: false`, and committed once per lap. It runs on a worker
beside the feed: the first version awaited it in line and, replayed, left the event count standing
still for the fifteen to twenty seconds a pass takes. It gives way the moment the next lap starts,
and `--focus-only` turns it off. Replayed through Mexico City, it made 35 clear "stop within three
laps" calls and the team stopped in 22 of them, against a base rate of 16% — a replay, so a check
that the calls are gradable, not evidence they are good.

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
fetch_degradation.py` collects **95 races** out of the local FastF1 cache — no API calls — by
stripping each race down to the part of a lap attributable to tyre age and pooling those deltas,
which mean the same thing at Monaco and Monza. **81 of the 95 are used**; the rest are excluded,
and which and why is the subject of the next section.

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
  HAR          +0.0378   +0.00000       54    71  +0.76s  +1.51s  +2.08s
  MED          +0.0456   +0.00000       29    59  +0.91s  +1.82s  +2.51s
  SOF          +0.0647   +0.00000       24    38  +1.29s  +2.59s  +3.56s

  circuit factor (shrunk toward 1.0):
    Spa 2.03x   Sakhir 1.90x   Barcelona 1.38x   ...   Monza 0.78x   Budapest 0.51x
```

Circuits whose fitted scale comes out *negative* are rejected rather than shrunk — Melbourne's raw
scale was −0.64, and shrinking that toward 1.0 produced a plausible-looking 0.06x, which is how a
sign error survives review. They fall back to the field average with a warning.

### The race that gets a vote it has not earned

The table above used to read `SOF −0.0148` against `HAR +0.0369`: a soft tyre that improves with
age and wears more slowly than a hard, which is backwards twice over. It was in the model every pit
call runs on for four days and no test failed.

**Seventeen of the 95 races fit a negative degradation scale** — a tyre that gets faster the longer
it runs. They are not random. Against the 78 that fit a positive one they were six times as likely
to be **red-flagged** (29% against 5%), had three times the safety-car starts, and ran twice the
share of the race neutralised. The decomposition subtracts one straight line in race lap — fuel burn
and track evolution together — before attributing anything to tyre age, and a red flag resets fuel
load and track state mid-race while a drying track falls several seconds a lap. Whatever that line
fails to fit is attributed to the tyre.

Two things follow, and the second matters more than it looks:

- The circuit scale is fitted **per race and combined by median**, not pooled into a single
  least-squares over every bucket row. Pooling gave one failed race a vote proportional to its lap
  count: Zandvoort's factor was **0.505x** — second-lowest of twenty-two, on a banked high-load
  circuit — because the wet 2023 race outvoted four sound ones. Per compound that race read hard
  0.92x, medium 1.30x, soft **−1.48x**. The guard that exists for exactly this tests the aggregate,
  which came to +0.207, so nothing looked wrong. It is now **1.05x**.
- Disrupted races are excluded on a criterion **measured independently of the answer** — red-flagged,
  or over 5% of laps on wet tyres — never on the sign of the estimate. Excluding on the sign
  systematically overstates every circuit whose true degradation is near zero, since noise there
  lands either side and only one side survives, and those are the circuits the scale matters most
  for.

What that does to the only number a strategist would check — how many laps of running a second stop
needs before it pays for itself, on a 26-lap-old hard:

| | Zandvoort | Montréal | Monaco | Silverstone | Spa | Monza |
|---|---|---|---|---|---|---|
| before | 47 | 57 | 36 | 22 | 10 | 30 |
| after | **22** | 30 | 21 | 22 | 10 | 31 |

The circuits that were already clean do not move, which is the shape a contamination fix should
have. At Zandvoort the old number meant that past lap 25 of 72 no second stop could ever win, which
is what made the 23 August "stay out on everything" result impossible to fix by tuning.

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

### When it says nothing, and the number behind that

For roughly the first third of a race the engine offers no call. A car that has not stopped has a
tyre age equal to its race lap, so fuel burn and tyre wear are one column of the design matrix and
no estimator separates them; the fit is refused until the field's stints stagger. That cost three
races their decision window — Baku silent to lap 41, Kuala Lumpur to 31.

The fix is to hold the race-lap trend with a prior and take tyre wear as what is left. It was
built, measured from 13 races (0.040 s/kg, sd 0.013), and works as a fit: first usable lap moves
from 41 to 10 at Baku, and the degradation it leaves is closer to the race's own end-of-race value
than the pooled prior on 72% of laps.

**It is not switched on**, because of what the calls did. `scripts/stop_calls.py` scores the one
thing about a call a recording can check — when the engine said "stop within three laps", did the
team? — counting only calls it marked decisive:

| | decisive "stop soon" calls | team then did |
|---|---|---|
| laps the engine already speaks on | 63 | **44%** |
| laps that speak only if the trend is held | 69 | **10%** |

Both rows overstate, by the same mechanism. They were counted on 5 October with a pit flag that is
set on the in-lap *and* the out-lap, so every stop counted twice and a call made the lap after a car
had already stopped scored as followed. Counted by stint change instead, a comparable corpus of
1,243 decisive calls drops from 36% followed to 28%. The ledgers behind this table were not kept, so
it cannot be recounted exactly. The two rows were counted the same way, so the gap between them is
what decides the question, not the level of either.

A control on identical laps, where the trend was measurable either way, shows the prior itself is
harmless (same call in 84% of rows) and that an early call is not bad merely for being early. What
fails is a call made on a one-stint field: early track evolution is steeper than any end-of-race
trend, so the wear left over comes out negative, the fit falls back on the pooled rate, and the
call rests on nothing the race measured.

So the silence is a measured choice rather than a missing feature, and `--hold-trend` reproduces
the comparison. `reports/trend-prior.json` has the tables.

**What decides when the silence ends** is the standard error of the race-lap trend, in seconds per
kilogram of fuel: the fit is refused while it exceeds 0.015. It is the third thing to stand guard
there. A count of stints was dead code; a 0.85 limit on the correlation of tyre age and race lap,
pooled across cars, was walked past at the 2026 Singapore GP when three cars started on used tyres
and diluted it to 0.847 with nobody on a second stint. The fit has an intercept per driver and does
not see an offset between cars, so the guard was measuring something the fit does not. The limit
was then set on the calls themselves — 2,336 of them across fourteen races:

| trend known to (s/kg) | top-3 skill | position error over baseline |
|---|---|---|
| under 0.010 | +32% to +45% | +0.13 |
| 0.010–0.015 | +39% | +0.24 |
| 0.015–0.030 | −1% to −14% | +0.29 to +0.65 |

`reports/collinearity/` holds the fits and ledgers behind it.

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

### Latency, with a budget it can miss

`PLAN.md` §6.4 asks for this specifically: F1 teams hire for real-time systems, and a latency
budget with evidence behind it is a stronger signal than any accuracy number. An accuracy number
can be got by running a notebook overnight; a p99 cannot.

The budget is **p99 ≤ 2 s from a packet landing to a recommendation existing**, and it is checked
against the samples rather than asserted. Measured over the 2026 Dutch GP, at a fixed 1,500
simulations, it was **missed** — so the simulation count now adapts, which `PLAN.md` §10 named as
the mitigation before any of this was built:

| | fixed 1,500 sims | adaptive |
|---|---|---|
| p50 | 1250 ms | 1158 ms |
| p95 | 2814 ms | **1306 ms** |
| p99 | 3222 ms | **1505 ms** |
| over budget | 13 / 49 | **0 / 49** |

```
  packet arrival -> recommendation, distribution:
         50-100 ms     1   2.0%  #
        100-250 ms     3   6.1%  ####
        250-500 ms     6  12.2%  ########
       500-1000 ms     7  14.3%  #########
      1000-2000 ms    32  65.3%  ########################################
```

Cost is near-linear in the number of simulations, so the controller is a damped ratio — undamped,
one slow lap halves the count and the next doubles it back. It starts *below* the configured
ceiling and earns its way up, because the first decision is the one it cannot correct and with
fifty decisions in a race a single uncorrected outlier **is** the p99. It never goes below 300
simulations: past that the margin between two options is sampling error, and the honest response
is to report the miss rather than keep degrading quietly.

Two measurement notes, both of which flattered the number before they were fixed. Cycles where the
pace fit is refused run no simulation and cost microseconds; counting them as decisions put a fifth
of the samples in the sub-millisecond bucket and nearly halved the reported median. And `lag` —
the age of a message on arrival — is reported separately and never folded into the total, because
it measures F1's pipeline and the internet rather than this engine.

### Forecasting the whole field

A recommendation log cannot be calibrated. Until November the engine advised **one** car — a pit
wall only has one to advise — so a race yielded ~50 calls, nearly all on a leader who was never
going to move. Every
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

<!-- scorecard:start -->
*Generated by `python scripts/scorecard.py` from every ledger in `predictions/` and the
results in `reports/results.json`. CI regenerates it and fails if the two disagree, so
it cannot be edited by hand and cannot go stale.*

**Field forecasts, live races only** — 1,254 forecasts across 3 races, every car on every lap the
engine spoke, each committed before the lap it names:

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (win) | 0.0216 | 0.0207 | -4.2% |
| Brier (top 3) | 0.0232 | 0.0399 | +41.7% |
| Brier (points) | 0.0808 | 0.1148 | +29.7% |
| Mean position error | 1.69 | 1.46 | — |

The baseline says every car finishes where it is running. Positive skill beats it. A position error
above the baseline's means the expected positions landed further from the result than assuming
nothing changes would have - true of every race so far. The top-3 and points probabilities are where
it beats the baseline; its expected positions and its pick of the winner do not.

| round | race | made | forecasts | win | top 3 | points | position error |
|---|---|---|---|---|---|---|---|
| 12 | Dutch GP | live calls, replay forecasts | 1,078 | +50.8% | -5.6% | +21.5% | 1.53 vs 1.13 |
| 15 | Azerbaijan GP | live | 330 | worse | +36.8% | +22.5% | 1.83 vs 1.50 |
| 18 | United States GP | live | 44 | worse | +72.6% | worse | 0.57 vs 0.32 |
| 19 | Mexico City GP | live | 880 | +51.2% | +41.2% | +33.7% | 1.69 vs 1.50 |

**Reliability, live races pooled.** When it says 70%, does it happen seven times in ten?

| P(top 3) band | n | said | happened |
|---|---|---|---|
| 0%–20% | 1,037 | 1.0% | 0.2% |
| 20%–40% | 35 | 30.0% | 31.4% |
| 40%–60% | 18 | 53.6% | 77.8% |
| 60%–80% | 54 | 69.7% | 66.7% |
| 80%–100% | 110 | 93.2% | 98.2% |

**Pit calls against what the teams did.** A clear "stop within 3 laps" - the best stop that soon
beating every later option and staying out by at least 0.15 places - set against whether that car
then stopped within 3 laps. Rows from before 3 November are judged on their gap to the next option
instead, which is what they recorded. A team's stop is not ground truth; it is the best evidence
there is of when stopping was reasonable. *Base rate* is how often the car stopped that soon
whatever the engine said, which is the number to beat.

| round | race | made | calls on laps | calls | clear on timing | said stop soon | team then did | base rate |
|---|---|---|---|---|---|---|---|---|
| 11 | Hungarian GP | backtest | 24–48 of 70 | 28 | 4 | 0 | - | 1/4 (25%) |
| 12 | Dutch GP | live | 21–72 of 72 | 49 | 1 | 0 | - | 0/1 (0%) |
| 13 | Italian GP | backtest | 32–48 of 53 | 110 | 96 | 0 | - | 1/96 (1%) |
| 14 | Spanish GP | backtest | 20–55 of 57 | 176 | 103 | 12 | 1/12 (8%) | 2/103 (2%) |
| 15 | Azerbaijan GP | live | 11–51 of 51 | 15 | 11 | 0 | - | 0/11 (0%) |
| 16 | Bahrain GP (Kuala Lumpur) | backtest | 31–54 of 55 | 154 | 130 | 0 | - | 10/130 (8%) |
| 17 | Singapore GP | backtest | 17–58 of 62 | 220 | 86 | 5 | 1/5 (20%) | 3/86 (3%) |
| 18 | United States GP | live | 46–56 of 56 | 2 | — | no lap data | no lap data | — |
| 19 | Mexico City GP | live | 32–71 of 71 | 40 | 27 | 0 | - | 0/27 (0%) |
| | **all live** | | | | 39 | 0 | - | 0/39 (0%) |
| | **all backtest** | | | | 419 | 17 | 2/17 (12%) | 17/419 (4%) |

**No live race has produced a clear "stop soon" call yet** - all 39 clear live calls were to stay
out. Every live call so far has been for the car in P1, the one least likely to be told to stop.
Since November the engine also advises every other running car once that call is out, so the next
live race is the first that can fill this. Until then the pit-call side of this engine has been
graded only on backtests.

**Latency, live races.** Packet landing to recommendation existing, against a p99 budget of 2 s:

| round | race | decisions | p50 | p99 | over budget |
|---|---|---|---|---|---|
| 12 | Dutch GP | 49 | 1158 ms | 1505 ms | 0 |
| 15 | Azerbaijan GP | 15 | 355 ms | 933 ms | 0 |
| 18 | United States GP | 2 | 436 ms | 436 ms | 0 |
| 19 | Mexico City GP | 40 | 793 ms | 1164 ms | 0 |
| | **all live** | 106 | 822 ms | 1425 ms | 0 |

- **United States GP**: the recording holds 19 of 56 laps, so its forecasts are graded against F1's
published result and its pit calls, with no stops to set them against, are not graded.
<!-- scorecard:end -->

Until November this section was a table typed in by hand from the Hungarian GP alone, and it sat
here for three months while four more races were recorded live. An earlier version of *that* table
reported +33.2% skill, and was wrong: a bug placed the race leader at the back of the grid, so the
baseline was being scored against corrupted positions and looked far worse than it was. Both are
written up in [the logbook](docs/logbook.md), and both are why this block is now generated and
checked rather than written. The fuller version, including which model commit made each race, is
[reports/scorecard.md](reports/scorecard.md).

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
    lap1   0.2075
    early  0.0204
    mid    0.0207
    late   0.0210
    final  0.0140

  circuit factor (shrunk, prior weight 3):
    Melbourne                 2.23x  (5 races)
    Zandvoort                 1.29x  (5 races)
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

### Passing, and what a safety car does to a stop

Two numbers decided more pit calls than the degradation model and were set by hand until November
2026: how hard it is to pass, and how cheap a stop is under a neutralisation. Both sit where pit
decisions are closest — whether a car that stops can get back past the cars it drops behind, and
whether "pit now, it's cheap" is true. `scripts/fetch_race_dynamics.py` measures both from every
cached race since 2022.

**Passing** was one rule for every circuit: a car held behind another passes with probability
0.18 a lap, plus 0.35 per second of pace edge. Measured on 17,123 green laps where a car started
within a second of the one ahead, with its edge taken from a clear-air pace fit of the race:

```
  earlier (<2026)  base 0.084/lap, +0.231 per s/lap  (80 races)
  current (2026+)  base 0.169/lap, +0.122 per s/lap  (15 races)

  circuit         vs era   used        circuit        vs era   used
  Monaco            0.03   0.019       Monza            0.76   0.139
  Marina Bay        0.21   0.056       Spielberg        1.25   0.200
  Baku              0.35   0.081       São Paulo        1.93   0.258
  Zandvoort         0.37   0.085       Austin           2.33   0.307
  Budapest          0.55   0.109       Barcelona        2.43   0.329
```

Three things in how that is fitted matter. **The simulation's own rule is fitted, not a summary
of it**: a car the simulation fails to pass with is pinned behind and rolls again only on laps it
closes back in — about half of them for an even pair — so fitting the raw pass rate would have it
pass half as often as the races it was fitted on. **The level belongs to the cars and the ratio to
the track**: 2026's rules made passing easier and less a matter of pace, so the level and slope
come from 2026 and five seasons say how hard each track is against its own era. **Shrinkage is
estimated, not borrowed**: one race says little — Baku reads 0.02 of average in two seasons and 1.5
in the other two — and the ratio of race-to-race to circuit-to-circuit variance puts the weight at
1.7 races, on a log scale because ratios multiply.

**A safety car and a VSC are now different events.** Every neutralisation used to be a full
safety car that bunched the field once, on the lap it came out, with a stop under it costing 55%
of a green one. Measured against what the field did on the same two laps — a method that reads
green stops at 22.1 s against the pit-loss constant's 22.17, which is the check that it works:

| | hand-set | measured |
|---|---|---|
| stop under a safety car | 55% | **72%** (121 stops, 23 races) |
| stop under a VSC | 55% | **77%** (162 stops, 30 races) |
| safety car lasts | 3.6 laps | **5.3** |
| VSC lasts | 3.6 laps | **3.5** |
| neutralisations that are VSC only | 0% | **44%** |

A safety car is dearer than assumed only over the two laps of the stop. The queue keeps closing up
behind it, so a car that stops rejoins at the back having lost places rather than time — and the
simulation now bunches the field on every lap a safety car is out, not just the first. A VSC
holds every car to a delta and never bunches, so the 77% stays lost.

**Does it change the calls?** `scripts/dynamics_corpus.py` folds each race once per decision lap
and makes every call twice from the same state, hand-set and measured, for every third car down
the order. It needs two reference points to be read at all, and has both:

| on the same 160 calls, six 2026 races | calls changed |
|---|---|
| a different random seed, nothing else (`--noise`) | 27 — 17% |
| **measured numbers instead of hand-set** | **53 — 33%** |
| passing switched off entirely (`--control`) | 56 — 35% |

Across all fourteen races the measured numbers changed 80 of 333 calls: 38 between stopping and
staying out, in both directions (20 to stop, 18 to stay), 34 in when to stop, 8 in tyre only.
Barcelona moved most (22 of 32), where passing went from 0.18 a lap to 0.33. Half the raw count is
the simulation's own noise; the rest, about sixteen points over it, is nearly as much as removing
passing altogether. That is a large effect for the degradation refit's comparison point — 2% of
calls — and it is the reason these two numbers were worth measuring first.

The noise floor is a finding of its own: at 1,000 simulations about one call in six turns on the
random draw. Those are the calls the engine already marks "no clear call", and it is why the
decisive flag and `soon_margin`, not the bare label, are what gets graded.

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
