# Logbook

Running notes on what was built, what broke, and what the data taught me.

---

## 2026-07-28 (later) — Monte Carlo simulation and the first pit call

Phase 3. Pace, fuel, degradation and safety-car hazard now feed one engine that rolls the remaining
race forward thousands of times and ranks candidate stops. `pitwall strategy` replays a recording to
any lap and asks what the engine would have said there.

**Speed: 22.6M car-laps/second.** 2,000 full 70-lap races over 22 cars in 0.14 s; a twelve-option
decision with 3,000 simulations each in 1.8 s. Vectorising over simulations rather than looping was
the right call — a pure-Python version would be minutes, which is useless inside a live race.

**The bug that mattered.** The track-position rule re-derived the running order *after* adding each
lap's times. That let any car which gained more than the following distance in a single lap swap
position for free, no overtake required — quietly deleting the entire cost of being stuck in
traffic, which is the thing pit strategy exists to exploit. Symptom: later stops were *monotonically*
better, with no interior optimum, because being released into traffic cost nothing. Enforcing the
rule against the order from the *start* of the lap fixed it, and the recommendation immediately grew
a real pit window — lap +8 beating both +4 and +14.

Two related details fell out of the same fix. Cars that pit must be exempt from defending, or a car
that has just stopped still blocks the field it was nominally ahead of. And `undercut_threats` was
giving our own car no pit plan, so it compared "they stop" against "we never stop" — not an
undercut, just the inevitable result of staying out on dead tyres. It reported an 80% threat where
the honest number was 45%.

**A test that was wrong rather than a bug.** I asserted that pitting always costs time. It does not:
at 0.08 s/lap over 30 laps, fresh rubber is worth more than the twenty seconds it costs, so the
simulator was right and the assertion was wrong. Now tested from both sides — a stop loses when
degradation is flat and pays when it is steep — which is a better test than the one I meant to write.

**Sanity checks, not just unit tests.** The suite asserts textbook dynamics: the faster car usually
wins, starting ahead is worth something, a quicker car is held up behind a slower one, safety cars
compress a 25-second lead, stopping under one is cheaper, and the undercut works. If any of those
break the model is wrong regardless of what the unit tests say.

**Known limitation, and it is inherited.** The engine currently prefers the soft compound in almost
every scenario, because the fitted degradation says soft degrades slowest. That is the single-race
confounding already logged — compound usage was separated by race phase at Hungary, so those
estimates are not trustworthy, and the simulation propagates them faithfully. The *timing* of the
stop is on much firmer ground than the *compound*. More races break the confound; one cannot.

---

## 2026-07-28 — Per-circuit safety-car hazard

No public dataset gives per-circuit safety-car rates, so this builds one:
`scripts/fetch_history.py` collects which laps ran under SC/VSC/red for every race 2022–2026, and
`models/safety_car.py` fits a discrete-time hazard over it. 94 races, 26 circuits, 68 safety cars
and 56 VSCs.

**Lap 1 is a different sport.** The headline result, and it is not close:

| phase | SC | VSC | either |
|---|---|---|---|
| lap 1 | 0.181 | 0.043 | **0.223** |
| early | 0.011 | 0.012 | 0.021 |
| mid | 0.011 | 0.012 | 0.020 |
| late | 0.011 | 0.008 | 0.017 |
| final | 0.006 | 0.007 | 0.012 |

A better than one-in-five chance of a neutralisation on lap 1, against about one in fifty for any
other lap — a full order of magnitude. Bucketing lap 1 separately was a guess when I wrote it; it
is now the single most important feature in the model. Risk then decays gently, and the closing
quarter is the calmest part of a race.

**Circuit factors rank the way a fan would expect**, which is reassuring for a number that came out
of shrinkage rather than intuition. Melbourne 2.33x, then Montréal, Zandvoort, Jeddah, Baku, Las
Vegas, Marina Bay — walls and no run-off. At the other end Barcelona 0.48x, Yas Island 0.51x,
Budapest 0.59x, Monza 0.68x — wide, forgiving, acres of asphalt.

**Two things keep the estimate honest.** Laps already under a safety car are excluded from exposure
entirely: the question is "given none is out, does one get deployed", and counting neutralised laps
would make circuits with *long* safety car periods look *safer* by inflating their denominators.
And circuit factors are shrunk Gamma-Poisson toward the field average, because four races per
circuit with one or two events is not enough to justify a raw ratio.

**Rate limit: the F1 API allows 500 calls an hour**, and a race costs several. A five-season fetch
cannot finish in one run. The fetcher is now resumable — it reloads what it has, skips those races,
saves after every success, and exits cleanly with a message when limited. First run got 39 races;
re-running took it to 94 without re-spending a single cached call.

**Bug: `Location` is not a stable circuit identity.** FastF1 recorded Miami as "Miami" through 2024
and "Miami Gardens" from 2025, silently splitting four seasons into two under-sampled entries that
shrinkage then flattened toward the mean. Nothing errored; the circuit just quietly lost its
history. Normalised via an alias map in the model rather than the fetcher, so existing data files
are fixed without re-spending API calls.

**Known gap:** red flags are collected but excluded from the `any` hazard. They are a genuinely
different strategic situation — the race stops and everyone gets a free tyre change — so folding
them in with safety cars would model the wrong thing. Monaco's modest 0.80x factor is partly this:
its 2024 incident was a red flag, not a safety car.

---

## 2026-07-26 (later still) — Fuel correction, and an identification problem

Fuel and degradation cannot be estimated one after the other: within a stint the car gets a lap
lighter at exactly the rate the tyre gets a lap older, so they are perfectly collinear. What breaks
the tie is the stint structure — fuel tracks the *race lap* and falls all afternoon, tyre age
*resets* at every stop. So both go in one model:

    lap_time = pace(driver) + β·race_lap + Σ_c δ_c + Σ_c α_c·tyre_age + ε

Two artefacts, deliberately: `models/fuel.py` is physics from published constants and works from
lap 1 with no data, which is the situation the live engine is in when a call actually matters.
`models/pace.py` estimates the same thing from a finished race, more accurately, and can calibrate
the first. That is the offline/online split the plan asked for.

**The fuel result holds up.** Fitted trend −0.0503 s/lap against a physics prior of −0.0350
(70 kg / 70 laps at 0.035 s/kg). Implied 0.050 s/kg vs a published 0.030–0.040 — above the range,
and it should be: the coefficient absorbs everything trending with race lap, which is fuel burn
*plus* track evolution as rubber goes down. R² 0.826, residual σ 0.70 s.

**Bug: no per-compound intercept.** The first version had driver intercepts and per-compound
*slopes* but no per-compound *offset*, so the model predicted identical times for every compound at
age zero. A hard tyre is genuinely slower than a soft at equal age, and the only way the fit could
express that was to inflate `α_hard`. It duly reported the hard degrading fastest — a completely
plausible number that was pure misspecification. Fixed with offsets against a reference compound.

**But the compound ordering is still not trustworthy, and this one is not a bug.** After the fix:
MED +0.090, HAR +0.086, SOF +0.071 s/lap. Soft degrading slowest is not believable. The cause is in
the usage pattern:

| Compound | median race lap | n |
|---|---|---|
| MED | 15 | 222 |
| HAR | 42 | 479 |
| SOF | 55 | 180 |

Teams ran medium early, hard through the middle, soft to the end. Compound is therefore almost a
proxy for race phase, and "degradation on the soft" and "whatever happens late in a race" are
effectively the same column of the design matrix. No estimator separates them from one race.

The estimator itself is fine — on synthetic data with staggered compound usage it recovers β and
every `α_c` to 1e-6 and reproduces the correct SOFT > MEDIUM > HARD ordering. So this is a data
identification problem, not a code problem, and `fit_pace` now detects the phase separation and
says so in its output rather than reporting confident nonsense.

This is exactly the argument for hierarchical priors across races that the plan already made.
Different circuits force different stint patterns, so pooling breaks the confound that a single
race cannot. Zandvoort will be the second data point.

---

## 2026-07-26 (later) — Clean-lap filter

Phase 2 begins. Built lap extraction (`laps/records.py`) and the clean-lap filter
(`laps/clean.py`), then ran both against the Hungary recording.

**How the feed signals a completed lap.** Worth writing down, because I guessed wrong first and
the probe returned nothing. `NumberOfLaps` and `LastLapTime` arrive *together* in one `TimingData`
message, and `NumberOfLaps` is the lap now being **started** — so the time belongs to
`NumberOfLaps - 1`:

    {'NumberOfLaps': 2, 'LastLapTime': '1:26.103'}   # lap 1 took 86.103s
    {'NumberOfLaps': 3, 'LastLapTime': '1:25.307'}   # lap 2 took 85.307s

The 2026 grid also does not use the numbers I assumed — Norris is #1, not #4. Always read the
`DriverList` rather than hardcoding.

**Result: 881 clean laps of 1,405 (62.7%).** The exclusion counts are what convinced me the filter
is right, more than the headline number:

| Reason | Count | Cross-check |
|---|---|---|
| Traffic (<2.0 s behind) | 429 | Hungaroring, 22 cars, DRS trains — expected to dominate |
| Entered pits | 92 | 47 stops recorded, so ~2 laps affected per stop ✓ |
| Left pits | 45 | ≈ one per stop ✓ |
| Neutralised | 34 | the lap-56 VSC ✓ |
| Lap 1 | 22 | exactly the grid size ✓ |
| Implausible | 2 | the cool-down and garage laps ✓ |

**Bug caught by a sanity check, not a test.** The out-lap rule was `tyre_age <= 1`, which also
discarded the first *flying* lap of every stint — a real racing lap, and the most useful one for
pinning the intercept of a degradation curve. Cost: 38 usable laps in one race. Now `== 0`, with a
regression test.

**The signal is there.** Median lap time by tyre age on the hard, clean laps only:

    age  0-4   5-9  10-14  15-19  20-24  25-29  30-34  40-44
        84.85 85.32  85.60  85.78  86.04  86.03  86.32  87.90

Monotonic, which is what degradation should look like.

**But do not read the raw slopes as tyre degradation yet.** Crude fits give SOF +0.060, MED +0.026,
HAR +0.051 s/lap — and medium's *absolute* times (86.9–88.2 s) sit above both other compounds,
which is nonsense for a mid-range tyre. The explanation is fuel: mediums ran early on a heavy car,
hards ran late on a light one. Fuel burn is worth roughly −0.05 s/lap, the same order as the effect
being measured, and it is currently pushing in the opposite direction. So these numbers are
confounded and every one of them understates true degradation.

That is the next job: fuel correction, then per-compound fits with circuit priors. The filter was
the prerequisite; the decomposition is what makes the output mean anything.

Also: `slots=True` on a dataclass replaces class attributes with descriptors, so
`CleanLapConfig.traffic_threshold` is a `member_descriptor`, not `2.0`. Read defaults off an
instance. The tests passed while the CLI crashed.

---

## 2026-07-26 — First full race captured and parsed

Recorded the Hungarian Grand Prix unattended and folded it through the Phase 1 pipeline. This is
the first time the engine has seen a real race rather than a synthetic fixture.

**The capture:** 11.9 MB, 76,979 events across 17 topics, from a single unbroken 157-minute
connection (13:30–16:07). The race ran 14:00–16:00, so the whole thing is inside one session with
buffer either side. `TimingData` dominates at 69,710 events — 91% of the feed.

**What the reducer got right, unprompted:**

- Final classification at lap 70/70: Norris from Verstappen (+15.080) and Antonelli
- Lapped cars correctly marked (`1L`, `2L`), Piastri correctly flagged retired
- 47 pit stops across the field, three compounds, stint transitions tracked per car
- Track status timeline including the VSC deployed on lap 56 and ending on lap 57
- Weather: 31.3 °C air, 47.0 °C track, no rain

Folding all 76,979 events takes 5.5 s — roughly 14k events/sec, single-threaded and unoptimised.
That is comfortably inside any sane live budget, so the simulation, not the ingest, will be the
thing to optimise later.

**Bug this surfaced: 2026 has 22 cars, not 20.** The CLI hardcoded a 20-row limit, silently
truncating Pérez and Bottas in the Cadillacs. Nothing errored — the screen just looked complete
and wasn't. A good reminder that the dangerous failures in this project are the plausible-looking
ones, which is the same reason the delta-merge code is the most heavily tested module here.

**The supervisor's backoff earned its keep.** When the session ended at 16:07 the feed kept
accepting connections but returned only a ~92 KB snapshot. The idle detection caught it and
stepped 30s → 60s → 120s → 240s → 300s, so the hour after the race cost 12 reconnects instead of
roughly 40. Worth having built the day before.

**Preview of Phase 2.** Yesterday's qualifying snapshot already showed why clean-lap filtering is
the first real job: Piastri's "last lap" was 5:48 (a cool-down lap) and Gasly's was 20:23 (sitting
in the garage after Q1 elimination). Both are faithfully parsed and both would wreck a degradation
fit. The race adds more of the same — in-laps, out-laps, VSC laps, and traffic-bound laps all need
excluding before anything can be fitted.

Next: the clean-lap filter, then per-compound degradation with circuit priors.
