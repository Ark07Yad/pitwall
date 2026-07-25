# Pitwall — Live F1 Race Strategy Engine

**Status:** Planning (written 25 July 2026)
**Goal:** A system that runs live during F1 race weekends, ingests the official timing feed, maintains a Monte Carlo simulation of the remaining race, and publishes strategy calls — pit windows, undercut threats, expected finishing position — *before* they happen.

---

## 1. The pitch (what goes at the top of the README)

> Pitwall consumes Formula 1's live timing stream, fits tyre degradation and safety-car
> models in-session, and simulates the remainder of the race thousands of times per lap to
> answer one question: **should we pit now?**
>
> Every recommendation is committed to this repository with a timestamp *before* the lap it
> refers to. The accuracy log is public and includes the calls it got wrong.

That last sentence is the whole project. Anyone can publish a model. Almost nobody publishes a
timestamped, falsifiable track record against a live event they could not have known the outcome
of. Git history is the proof.

---

## 2. Why this beats the existing GitHub crowd

The F1 GitHub space is saturated with "predict the race winner with XGBoost" notebooks trained on
historical results. They all share the same three weaknesses, and Pitwall is designed around
attacking each one:

| Their weakness | What Pitwall does instead |
|---|---|
| Batch/offline — runs on a CSV after the race | Real-time — reacts to a live feed under a latency budget |
| Predicts *outcomes* (who wins) | Recommends *decisions* (pit now vs. lap +3), which is what a pit wall actually does |
| Single-agent — assumes rivals do nothing | Multi-agent — models how rivals respond to our stop |
| No validation, or validation on the training set | Pre-registered predictions + calibration scoring (Brier, log-loss) |
| Point estimates | Calibrated probability distributions |

The multi-agent gap is real and worth naming in the README. The 2026 *Machine Learning* paper on
race-strategy RL notes that even team methods are "usually limited to linear optimization" and
that Monte Carlo approaches in the literature "fail to take into account complex interactions
between teams' strategies in this unpredictable multi-agent environment." That is a published
opening, and it is the technical heart of this project.

---

## 3. Data access — the constraint that shapes the architecture

This was the most important finding of the research phase, and it needs to be settled before any
code is written.

### The three sources

**OpenF1 (openf1.org)** — clean REST/JSON, 18 endpoints, 3.7 Hz telemetry.
- Historical (2023+): **free**, no API key, 3 req/s and 30 req/min.
- **Live data is paid**: €9.90/month sponsor tier. "Live" = from 30 min before a session to 30 min
  after. Outside that window everything is free.

**FastF1 (Python)** — the standard library, historical data back to 2018, excellent lap/telemetry
handling and a caching layer. Also ships `fastf1.livetiming.SignalRClient`, which connects to F1's
own feed — **but the docs state explicitly it "is *not* possible to do real-time processing"**. It
records raw messages to a file for post-session parsing. It is a recorder, not a live parser.

**F1's SignalR feed directly** — `wss://livetiming.formula1.com/signalrcore`, the undocumented
endpoint powering F1 TV's timing screens. Free. Negotiate over HTTP for a `ConnectionToken`, open
the websocket, invoke `Subscribe` with the topic list, then decompress the `.z`-suffixed topics
(zlib, base64). Several reference implementations exist to learn the protocol from
(`matteocelani/f1-telemetry` in Node, `Troftu/F1-SignalR`, `claudiopizzillo/F1client`).

### The decision — zero cost, no subscription

**Build the real-time parser on the raw SignalR feed. Total project cost: $0.**

F1's SignalR endpoint requires **no API key, no account, and no payment**. It is the same feed that
FastF1, `f1-dash` (~2k stars), `OpenF1.Data`, `undercutf1` and `matteocelani/f1-telemetry` all
connect to. OpenF1 charges €9.90 not because the data is gated but because *they* pay to run an
always-on ingestor and a public API. Running on a laptop for one session at a time, those costs
don't exist.

The free fallback chain replaces the paid tier entirely:

| Need | Free source |
|---|---|
| Live, during session | Own SignalR client → `wss://livetiming.formula1.com/signalrcore` |
| Live fallback if own parser breaks mid-race | Self-hosted `f1-dash` (`docker compose up`) — already decodes the feed and serves it over WebSocket |
| Dev/replay, any time | Recorded raw sessions via `ReplayFeed` |
| Backtest telemetry, 2023+ | OpenF1 **free** tier (all 18 endpoints; only the live window is paid) |
| Backtest laps/telemetry, 2018+ | FastF1 |
| Results/standings, 1950+ | [Jolpica-F1](https://github.com/jolpica/jolpica-f1) — free, no auth, Ergast successor |

⚠️ **Do not vendor OpenF1's source code.** It is CC BY-NC-SA 4.0 — the ShareAlike clause could
force this repository under the same licence. Using their *API* is fine; copying their *code* is a
licensing entanglement. Writing our own SignalR client avoids it — and is the better portfolio move
anyway. Jolpica is volunteer-run on ~$45/month of donations, so cache aggressively and don't hammer it.

**Possible IP blocking (unconfirmed):** one source suggests F1 has begun blocking some hosted
clients, which would explain why public instances go down while self-hosting keeps working. I could
not verify this from a primary source, so treat it as a rumour with a useful implication: a laptop
on home broadband is the *least* likely configuration to be blocked. Another reason to run locally
and not reach for a cloud VM.

The reasoning matters more than the choice: FastF1 — the most-used library in this space —
explicitly declines to parse this stream in real time. Building the layer that does is a genuine,
demonstrable piece of systems engineering, and it is exactly the "real-time data processing" skill
every F1 software job listing asks for. It is also the part of this project that a competing
portfolio cannot trivially copy from a tutorial.

Design the ingest layer behind an interface with three implementations so the models never know
which source they are on:

```
RaceFeed (abstract)
├── SignalRFeed      # live, raw websocket, the real thing
├── ReplayFeed       # a recorded session played back at 1x or 50x — the dev workhorse
└── OpenF1Feed       # REST polling; fallback if SignalR breaks mid-season
```

`ReplayFeed` is what makes this project buildable at all. It turns a stochastic once-a-fortnight
live event into a deterministic test fixture you can run a hundred times a day.

### ⚠️ Time-critical: record the Hungarian GP

**Today is Saturday 25 July 2026. The Hungarian Grand Prix is this weekend (24–26 July) — the race
is tomorrow.** After it, F1 enters the summer break and the next race is the Dutch GP at Zandvoort
in late August (~21–23 Aug; verify).

Recording it costs one command and ~200 MB.

**Why it still matters even though historical data is free:** OpenF1 and FastF1 give you *parsed,
normalised* data for any past race — plenty for building the models in Phase 2. What they do not
give you is the **raw SignalR wire format**: the compressed, incremental, out-of-order message
stream the live parser in Phase 4 has to handle. Only a live recording captures that. So the honest
framing is: miss it and Phases 1–3 proceed fine on free historical data, but the real-time parser —
the hardest and most differentiating part — has nothing to be tested against until Zandvoort.

```bash
python -m fastf1.livetiming save hungary_2026_race.txt
```

Start it 5 minutes before lights out. Note the docs' warning that the connection may drop after
~2 hours — run it under a wrapper that restarts and appends (`--append`), or just run two
overlapping recorders. Also record quali today if the session is still ahead.

This single recording becomes the fixture that Phases 1–4 are built and tested against. **Do this
first, before writing any other code.**

### Legal / ethical note (put a short version in the README)

The SignalR endpoint is undocumented and not an officially supported public API. Be a good
citizen: one connection, no hammering, no redistribution of the raw feed, and no commercial use.
Publish derived analysis, not bulk re-hosted F1 data. The paid OpenF1 tier exists precisely as the
sanctioned route — subscribing to it (€9.90) is cheap insurance and worth doing if this becomes
anything more than a personal portfolio project. Being able to discuss this trade-off thoughtfully
is itself a mark of engineering maturity in an interview.

---

## 4. Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  INGEST                                                        │
│  SignalRFeed / ReplayFeed / OpenF1Feed  →  normalised events    │
│  (negotiate, subscribe, zlib-decompress, dedupe, timestamp)     │
└───────────────────────────┬────────────────────────────────────┘
                            │  Event stream (async queue)
┌───────────────────────────▼────────────────────────────────────┐
│  RACE STATE                                                    │
│  Authoritative in-memory state, rebuilt from event log          │
│  per car: position, gap, interval, compound, tyre age, stint    │
│           pit count, fuel estimate, sector times, status        │
│  global : lap, track status (green/SC/VSC/red), weather         │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│  MODELS  (fit offline, updated online)                         │
│  ├─ Degradation   hierarchical Bayes, prior→posterior per stint │
│  ├─ Pace          fuel- and traffic-corrected true pace         │
│  ├─ Safety car    per-circuit, per-lap hazard rate              │
│  ├─ Pit loss      circuit constant + stationary-time dist.      │
│  └─ Overtaking    P(pass | pace delta, circuit difficulty)      │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│  SIMULATION                                                    │
│  Monte Carlo, N≈5–20k futures, lap-stepped to chequered flag    │
│  Rivals sampled from a policy distribution (multi-agent)        │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────────────┐
│  DECISION                                                      │
│  EV(finish pos) for each action ∈ {stay, pit→S/M/H}             │
│  Undercut/overcut windows, threat detection, confidence          │
└───────────────────────────┬────────────────────────────────────┘
                            │
┌──────────────┬────────────▼──────────────┬─────────────────────┐
│  DASHBOARD   │  PREDICTION LOG (git)     │  EVALUATION         │
│  live push   │  append-only, timestamped │  post-race scoring  │
└──────────────┴───────────────────────────┴─────────────────────┘
```

**Design rule:** race state is rebuilt by folding the event log. Never mutate state from a model.
This makes the whole system replayable and deterministic given a recording — which is what makes
the backtest trustworthy.

---

## 5. The models, in detail

This is where the engineering credibility lives. Each model should get its own notebook in
`notebooks/` showing the fit, the residuals, and the failure cases.

### 5.1 Lap time decomposition

Everything rests on decomposing an observed lap time:

```
lap_time = base_pace(driver, car)
         + fuel_effect(lap)          # ~ -0.03 s per kg burned, ~1.5–1.8 kg/lap
         + degradation(compound, tyre_age)
         + traffic_penalty(gap_ahead)
         + track_evolution(lap)
         + noise
```

**Clean-lap filtering is the unglamorous part that decides whether any of this works.** Exclude:
in-laps and out-laps, any lap under SC/VSC/red, laps with gap-to-car-ahead < ~2.0 s (dirty air),
laps with track-limit deletions, and the first flying lap of a stint. Expect to throw away 30–50%
of laps. Document the filter — reviewers will look for it, and its absence is the tell of a naive
project.

### 5.2 Degradation model — hierarchical Bayesian

Per compound `c`, per driver `d`:

```
deg(age) = α_{c,d} · age + β_c · age²
```

The linear term is normal wear; the quadratic term captures the "cliff."

The problem this must solve: **on lap 6 you have almost no data, but you still need a
recommendation.** So use a hierarchical prior — `α_{c,d} ~ Normal(α_c^circuit, σ)` where the
circuit-level prior comes from historical races at that track (and, shrunk, from similar tracks),
then update in-session as clean laps arrive.

Fit the priors offline with PyMC or numpyro. For the live path, express the update as a **Kalman
filter** so each new lap is an O(1) update instead of a re-run of MCMC. That online/offline split
is a strong thing to be able to explain in an interview.

Circuit context worth encoding: degradation varies enormously by track — Barcelona was the highest-
degradation circuit of 2026, and undercut strength varies far more by circuit than by compound
offset.

### 5.3 Safety car hazard model

Per-lap hazard rate `λ(circuit, lap)`. It is *not* constant — lap 1 is far riskier than lap 30, and
risk rises after incidents and in wet conditions.

No comprehensive per-circuit SC probability table is publicly published — deriving one from
2018–2026 race control messages (available via FastF1) is a genuine small contribution, and worth
publishing as a standalone table/blog post in `docs/`. Expect few observations per circuit, so
shrink each circuit's estimate toward the global mean (empirical Bayes) rather than trusting a raw
rate from six races.

Model as a discrete-time hazard: `P(SC on lap L) = logit⁻¹(circuit effect + lap effect + weather)`.

### 5.4 Pit loss

Total time lost = in-lap delta + stationary time + out-lap delta, measured empirically per circuit.
This is the most stable constant in the whole system — it is set by pit lane geometry and speed
limits, not car performance (Spa is the cheapest stop of the era at ~18.4 s median). Measure it per
circuit from history; sample stationary time from a distribution (with a fat tail for botched
stops) rather than using a fixed 2.4 s, since the tail is exactly what changes marginal calls.

### 5.5 Overtaking model

`P(pass per lap | pace delta, circuit difficulty)`, fitted from historical position changes. Without
this, the simulation will happily assume a faster car sails past at Monaco. Circuit overtaking
difficulty should be a fitted per-track parameter, not a hand-written constant.

### 5.6 Multi-agent rival policies — the differentiator

Do **not** assume rivals hold station. For each rival, sample their strategy from a policy
distribution:

- **Static** — runs to their pre-race planned window.
- **Reactive/covering** — pits the lap after we do, if we are a threat (what teams mostly do).
- **Aggressive** — takes the undercut on *us* when in range.
- **Optimal** — plays their own best response from the same engine.

Running each future against a *sampled* opponent policy rather than one fixed assumption is what
turns this from a single-agent toy into something defensible. The output is then a distribution
over finishing positions that already integrates over rival behaviour.

---

## 6. Evaluation — the part that makes it credible

Most portfolio projects stop at "it works." This one should ship a scoreboard that can embarrass
it, because that is what makes the good numbers believable.

**Backtest set:** 2023–2026 races (OpenF1 free covers 2023+; FastF1 back to 2018 for a larger set).
Hold out the 2026 season entirely as a test set while developing on 2023–2025 — then the live races
from Zandvoort onward are a genuine out-of-sample stream.

**Metrics:**

1. **Calibration** — Brier score and log-loss on probabilistic claims ("P(Norris finishes top 3)").
   Ship a reliability diagram: when the system says 70%, does it happen ~70% of the time? A
   well-calibrated model that is honestly evaluated beats a sharper one that is not.
2. **Decision quality** — for each real pit decision, compare the simulated EV of the actual team's
   choice against the system's recommendation. Frame this honestly: it is a counterfactual under
   *our own model*, so it demonstrates internal consistency, not superiority over a real pit wall.
   Say so explicitly in the README. Overclaiming here is the fastest way to lose a reviewer's trust.
3. **Undercut call precision/recall** — of flagged undercut opportunities, how many actually gained
   position?
4. **Latency** — p50/p99 from packet arrival to published recommendation. Set a budget (e.g. p99
   < 2 s) and publish the histogram. F1 teams hire for real-time systems; a latency budget with
   evidence is a stronger signal than any accuracy number.

**Pre-registration:** predictions are written to an append-only log and committed *during* the
race. Git timestamps make them falsifiable. This is the single most persuasive artifact in the
repo — build the commit step into the live loop so it happens automatically, not by hand.

---

## 7. Timeline

Anchored to the real calendar. Ten rounds are done; twelve remain, ending Abu Dhabi 4–6 December.

| Phase | Dates | Milestone |
|---|---|---|
| **0. Capture** | **26 Jul (tomorrow)** | Record the Hungarian GP raw stream. Non-negotiable. |
| **1. Foundation** | 27 Jul – 2 Aug | Repo, env, `RaceFeed` interface, `ReplayFeed` working off the Hungary recording, race-state folding, first tests |
| **2. Models** | 3 – 9 Aug | Clean-lap filter, degradation model + priors, pace model, SC hazard table, pit-loss constants. One notebook each. |
| **3. Simulation** | 10 – 16 Aug | Monte Carlo engine, overtaking model, rival policies, decision layer. Backtest on 2023–2025. |
| **4. Real-time** | 17 – 23 Aug | SignalR live parser, dashboard, auto-commit prediction log, latency instrumentation. |
| **🏁 GO LIVE** | **Dutch GP, ~21–23 Aug** | First live race. Expect it to break — that is the point. |
| **5. Iterate** | Sep – Dec | Italy (4–6 Sep) → Abu Dhabi (4–6 Dec). ~11 live races. One improvement per race, driven by what broke. |

Four weeks of build during the summer break, then eleven races of public track record before
December. For a graduate job hunt the arc is close to ideal: by October you can write "live since
August, N races, calibration curve here" on an application.

**Deliberately deferred to Phase 5+:** weather/rain modelling, 2026 energy-management (Boost/
X-mode) integration, and the RL agent. Each is a good idea and each will sink Phase 1–4 if pulled
in early. The energy-management piece is the natural bridge into Project #1 — the simulation core
is shared, which is why these two projects were sequenced this way.

---

## 8. Daily commit strategy

The aim is a green graph made of real work, not `README typo` commits — a reviewer can tell the
difference in about five seconds, and padding actively hurts.

**Weekdays:** one meaningful unit per day. The phase breakdown above is deliberately sized so most
days have a natural stopping point: one model, one filter, one test suite, one endpoint.

**Race weekends:** these generate content for free.
- Friday — record FP1/FP2; commit the session recording metadata and a practice-pace note
- Saturday — quali analysis, degradation priors updated from long runs
- Sunday — live run; the prediction log commits itself during the race
- Monday — auto-generated race report: what it called, what happened, what it got wrong

**Build the race report as a generated artifact** (`reports/2026-13-netherlands.md`) so it is one
command, not an evening of writing. That report — a system grading itself in public every two
weeks — becomes the most compelling thing in the repository.

A weekly `docs/logbook.md` entry ("this week I learned the SC hazard needs shrinkage because Baku
had 4 observations") costs ten minutes and shows reasoning over time, which is what people actually
read when deciding whether you can think.

---

## 9. Tech stack

Chosen for "boring and defensible" over novel.

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | ⚠️ Machine has 3.9.6 — install 3.12 via pyenv/homebrew first. FastF1 and modern typing need it. |
| Async ingest | `asyncio` + `websockets` | Native fit for a streaming feed |
| Data | `polars` or `pandas`, **Parquet + DuckDB** | DuckDB makes the backtest queryable in one file; no server |
| Modelling | `numpy`, `scipy`, `PyMC`/`numpyro` (offline), hand-rolled Kalman (online) | Split offline fitting from online updating |
| Simulation | `numpy` vectorised, `numba` only if profiling demands it | Optimise after measuring, not before |
| Serving | `FastAPI` + WebSocket | Same async model as ingest |
| Frontend | Plain HTML + Plotly, or Svelte if it grows | The dashboard is evidence, not the product — don't spend a week on it |
| Testing | `pytest`, replay-based golden tests | Deterministic replays make real regression tests possible |
| CI | GitHub Actions — tests + lint on push | Signals professional habits |

Keep Docker for later. It solves a deployment problem you do not have in week one.

---

## 10. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| **Hungary recording missed** | — | Do it tomorrow. Everything downstream slips 4 weeks otherwise. |
| SignalR protocol breaks / F1 changes it | Medium | `RaceFeed` abstraction; self-hosted `f1-dash` as a free drop-in fallback (it decodes the same feed); four open-source reference clients to diff against |
| Connection drops mid-race (~2 h limit) | High | Auto-reconnect with backoff + append mode; state rebuilds from event log |
| Scope creep (RL, weather, 2026 energy) | **High** | Explicitly deferred to Phase 5. Written down here so it is a decision, not a temptation. |
| Simulation too slow for live use | Medium | Vectorise; reduce N adaptively; measure before optimising |
| Models overfit to few races | Medium | Hierarchical shrinkage; hold out 2026; publish calibration honestly |
| Live race day chaos | Certain | The first live race *will* fail somewhere. Log everything, fix it Monday, write it up. A public failure post-mortem is a better artifact than a suspiciously clean first run. |

---

## 11. What "done" looks like

By early December the repository should contain:

- A live system with **~11 races of timestamped, out-of-sample predictions**
- A calibration curve and Brier score on real out-of-sample data, including the misses
- A latency histogram with a stated budget and evidence it is met
- A per-circuit safety-car hazard table — a small original contribution, publishable on its own
- Eleven auto-generated race reports, each grading the system against reality
- A README leading with a 15-second GIF of the dashboard calling an undercut that then happened

And the sentence that opens a cover letter: *"I've been running a live race-strategy engine against
the F1 timing feed since August. Here's what it called at Zandvoort, and here's where it was
wrong."*

That is a conversation with an engineer, not a résumé bullet.

---

## Appendix: immediate next actions

1. **Record the Hungarian GP tomorrow** — install `fastf1`, run the recorder 5 min before lights out
2. Install Python 3.12 (system 3.9.6 is too old for comfort)
3. `git init`, push `pitwall` to GitHub with this plan as the first commit
4. Build `ReplayFeed` against the Hungary recording — first real code, Monday
