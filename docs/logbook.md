# Logbook

Running notes on what was built, what broke, and what the data taught me.

---

## 2026-08-26 (later) — A latency budget, missed, then met

`PLAN.md` §6.4 wanted p50/p99 from packet arrival to published recommendation,
with a stated budget and a published histogram, on the argument that F1 teams
hire for real-time systems and a p99 is harder to fake than an accuracy number.
The feed had been tracking two things that sound like this and are not: `lag`,
the age of a message when it arrives, and `decode`, turning a frame into events.
Neither is the pipeline.

**The first measurement was flattering, twice over, and both had the same shape
as everything else found this week.**

Fourteen of seventy-two samples landed in the sub-millisecond bucket. Those were
cycles where the pace fit was refused - no usable model yet, so no simulation
ran. Counting a decision that never happened as a fast decision moved the median
from 1250ms to 677ms, nearly halving it. And the feed lag came out at a mean of
**278,345 seconds**, which is not a network problem: replaying a recording made
three days earlier, the "lag" is the age of the recording. Lag is now taken only
against a live feed, and never folded into the total, because it measures F1's
pipeline and the internet rather than this engine.

**Then the honest number, and it missed.** Over 49 real decisions at a fixed
1,500 simulations: p50 1250ms, p95 2814ms, **p99 3222ms against a 2s budget, over
on 13 of 49**. The budget was written down before the measurement and stayed
written down after it.

**§10 had already named the fix**, in June, under "simulation too slow for live
use": vectorise, reduce N adaptively, measure before optimising. Measured, so:
cost is near-linear in simulation count, which makes the correction a ratio.
Damped, because controlling on the last decision while being judged on the tail
oscillates - one slow lap halves the count and the next doubles it straight back,
and the test for that asserts the swing rather than the level.

First attempt: 13 misses down to 1. The one remaining was the *first* decision,
which the controller by definition cannot correct, and with 49 samples one
uncorrected outlier is the entire p99. So it now starts below the ceiling and
earns its way up rather than spending the budget on the single lap with no
evidence behind it.

| | fixed 1,500 | adaptive |
|---|---|---|
| p50 | 1250ms | 1158ms |
| p95 | 2814ms | 1306ms |
| p99 | 3222ms | **1505ms** |
| over budget | 13/49 | **0/49** |

A floor of 300 simulations, below which the margin between two options is
sampling error rather than a decision - and hitting it sets a flag that shows on
the dashboard, because at that point the budget is being missed by the model
being too expensive, not by the controller being slow. Degrading quietly would be
the worst of the available behaviours.

**What I actually like about this one** is that it is the first thing this week
where the loop closed inside a day: a number was written down, the system missed
it, the plan's own mitigation was implemented, and the number was met - with the
before and after both in the repository. The three findings before it were all
"the measurement was wrong". This one is "the measurement was right and the
system wasn't", which is a much more comfortable kind of problem to have.

---

## 2026-08-26 — The scorecard could not be read, and why

Sunday's report has a row that says `Brier (points) 0.0010 / 0.0000 / worse*`. A
baseline of exactly zero is not a hard benchmark, it is a broken question, and I
had been reading past it for three days while tuning the models it was supposed
to be grading.

**The evaluation was structurally uninformative and no amount of model work
would have fixed it.** The engine advises one car, because a pit wall has one car
to advise. So a race produces about fifty calls, and at Zandvoort nearly all of
them were on whoever led — a car that finished where it started. Every
`p_points` sat at 0.98, the naive baseline was flawless, and 41 of 49 calls
landed in a single calibration bucket. The reliability diagram, which `PLAN.md`
§6 calls the most persuasive artifact in the repository, had one populated band.

**The fix is a distinction I should have drawn at the start.** A *recommendation*
is expensive and singular — thirteen candidate strategies simulated for one car,
1.68s. A *forecast* is cheap and plural — where does everyone finish — and the
simulation already computes it, because the field is simulated jointly. One run
returns a (1500, 22) array of finishing positions.

Measured: **0.155s for the whole field, against 37s to run a recommendation for
each of 22 cars.** A factor of 240, and the reason a calibration curve is
affordable at all. Fifty concentrated claims become 1,078 spread across cars
whose outcomes genuinely differ.

**And the curve immediately says something the old one could not:**

| band | n | said | happened |
|---|---|---|---|
| 0–20% | 872 | 1.0% | 1.8% |
| 20–40% | 51 | 29.0% | 33.3% |
| 40–60% | 24 | 48.8% | 16.7% |
| 60–80% | 47 | 73.0% | 59.6% |
| 80–100% | 84 | 91.8% | 97.6% |

Overconfident through the middle — when it says 73% it happens 60% of the time —
and slightly *under*confident at the top. That is the first genuine, actionable
statement about this engine's calibration the project has been able to make, and
it was invisible while every claim was about a leader cruising to a win.

The headline numbers are mixed and that is fine: **+50.8% skill on P(win)**,
+21.5% on points, and **−5.6% on top-three** — beaten by the naive forecast on
the one question where track position is stickiest. Mean position error 1.53
against a baseline 1.13. A model that beats a strong baseline on two of three
questions and loses the third is a normal model; the previous −167% was a bug.

**Kept separate, deliberately.** Forecasts go in their own file and are committed
a lap at a time rather than a car at a time. They are a different claim from a
recommendation — settled at the flag with no judgement required — and folding
them together would let a thousand easy forecasts bury fifty hard calls, which is
exactly the kind of averaging this project exists not to do.

**The pattern, four days running.** Sunday: a decision layer with no "whether"
option. Monday: a pace model extrapolating past its own data. Today: a scorecard
whose baseline was degenerate. Each one produced a confident number, none of them
errored, and every test passed throughout. The recurring failure here is not
wrong code, it is a measurement that cannot say what it appears to say — and the
only defence I have found that works is to look at the distribution behind the
number rather than the number.

---

## 2026-08-24 — Pooling 95 races, and what survivorship does to a tyre curve

`PLAN.md` §5.2 asked for hierarchical degradation priors pooled across races, on
the argument that one race cannot identify a cliff. Built it: 95 races, 85,587
laps, tyre ages out to 78, entirely from the local FastF1 cache at no API cost.

**Pooling lap times is meaningless, so what pools is the part attributable to
tyre age.** A lap at Monaco and a lap at Monza share no scale. Each race is fitted
for its nuisance structure - driver pace, the fuel-and-evolution trend, each
compound's baseline - and subtracting it leaves degradation plus noise, in
seconds, which means the same thing everywhere.

**A bug I nearly shipped, and the synthetic test that caught it.** My first
version put only a *linear* age term in the nuisance fit, reasoning that the
residual keeps whatever the line missed so the delta still holds the whole age
effect. That reasoning is wrong, because a quadratic in tyre age is partly
collinear with the things being subtracted: its mean goes into the compound
offset, and the part trending with race lap goes into the fuel term. Measured
against synthetic data with a known cliff of 0.00250, the linear-only nuisance
fit recovered **0.00098 - 61% of the curvature eaten** - and inflated the linear
rate from 0.040 to 0.093 to compensate. Carrying `age²` through the nuisance and
zeroing both age columns recovers 0.00214. Without a known answer to check
against I would have shipped the first version and believed it.

**And then the pooled cliff still came out zero.** Which is where it got
interesting, because with 95 races the answer is not "not enough data". So I
looked at the curve instead of fitting it:

| compound | age 0-4 | 10-14 | 20-24 | 30-34 | 40-44 | 50-54 |
|---|---|---|---|---|---|---|
| HAR | +0.10 | +0.48 | +0.81 | +0.84 | +0.82 | +1.55 |
| MED | +0.11 | +0.44 | +0.62 | +0.66 | +1.76 | — |
| SOF | −0.29 | +0.21 | +0.21 | **−0.61** | — | — |

The soft is the tell. A tyre thirty laps old cannot be *faster* than one fifteen
laps old. What that measures is **survivorship**: a car whose tyres are going
away gets pitted, so the sample still circulating at age 30 is made of precisely
the stints that were not degrading. The selection strengthens with age, and
pooling more races sharpens the artifact rather than removing it.

So the observed curve is *concave* where physics says convex. An unconstrained
quadratic fitted to it comes back **negative** - a tyre improving with age - and
the non-negativity constraint I added yesterday floors it at zero. The zero was
never "no cliff exists"; it was the constraint refusing to encode a nonsense, and
I had been reading it as a finding.

**What the model does about it.** The shape is fitted only up to the age at which
the binned curve stops rising - found per compound, not assumed: soft turns at
19, hard at 29 - and **continued linearly beyond rather than flattening**.
Flattening is the artifact; a straight line is the smallest claim that is not
knowingly wrong, and it does not tell the engine a tyre lasts forever. Fitting
through the plateau is what had made the pooled soft look like it degraded at a
fifth the rate of the hard.

**A second sign error, laundered by shrinkage.** Melbourne came out at 0.06x the
field average - essentially "tyres do not wear here" - and the raw scale behind
it was **−0.64**. Lusail and Mexico City were negative too. Shrinking a negative
number toward 1.0 turns it into a small positive one that looks entirely
plausible, which is a good description of how a sign error survives review. Those
circuits are now rejected rather than shrunk, and fall back to the field average
with a warning naming them.

**Circuit factors that survive the fix rank the way a tyre engineer would
expect**: Sakhir 2.48x, Spa 2.27x, Barcelona 2.19x, Budapest 1.41x at the top;
Zandvoort 0.50x, Montréal 0.39x at the bottom. Zandvoort being genuinely
low-degradation is consistent with the near-flat hard-tyre wear measured directly
from Sunday's race.

**What it bought, and what it did not.** Re-running the 49 Dutch GP calls with
the prior, matched lap-for-lap:

| | Brier (top 3) | skill | on unobserved tyre ages |
|---|---|---|---|
| live | 0.3820 | −167.4% | 31 / 49 |
| stay-out option | 0.0585 | +59.1% | 31 / 49 |
| + pooled prior | 0.0837 | +41.4% | **0 / 49** |

The prior scores *worse* on this race and is still the better model. Its value is
the last column: two thirds of the calls used to rest on tyre ages nobody had
ever run, and now none do, because the evidence reaches to 78 laps instead of 36.
Forty-nine calls from one afternoon, all advising a leader who won comfortably,
cannot separate +59% from +41% and I am not going to pretend otherwise in either
direction.

**The honest summary of three days.** The engine's late-race preference for
staying out is not the modelling error I took it for on Sunday. Measured
degradation over the stint lengths teams actually run is genuinely small - one to
three seconds - against a 22.5-second stop. Once the mandatory change is done,
staying out often *is* right, and real teams stop for track position, the tyre
rule and safety cars rather than raw wear. What was wrong was never saying which
calls it could support.

---

## 2026-08-23 (later) — The cliff term, and a hypothesis the data refused

Yesterday's post-mortem blamed the 47-of-49 "stay out" calls on a degradation
model that was linear where `PLAN.md` §5.2 specified `α·age + β·age²`. The
quadratic term is now implemented. It did not help, and finding out *why* was
worth more than the fix.

**The term is there and it works.** Fitted with a non-negativity constraint,
because a negative quadratic is a tyre that gets faster the longer it runs and
extrapolating one actively rewards never stopping - the exact failure the term
exists to prevent. Where the unconstrained fit wants a negative γ the compound
is refit without it rather than clamped, so its α is not left carrying the bias.

**On synthetic data it recovers the truth to three decimals**: a true γ of
0.00300 comes back as 0.00297, and a genuinely linear compound picks up no
spurious curvature.

**On real races it fits ≈ zero.** Zandvoort: hard 0.00000, medium 0.00000, soft
0.00031. Hungary: hard 0.00008, the rest zero.

So I tested the obvious objection - that the estimator is simply too weak
against a 0.88 s residual. It is not. Regenerating the synthetic data at the
*real* noise level and real stint lengths, a true cliff of 0.0030 still comes
back as 0.0032. An effect of the size that would matter is comfortably
detectable; the data says it is not there.

**The honest conclusion is that within the stint lengths teams actually run,
degradation at these two circuits really is close to linear.** The cliff is a
real phenomenon, but it lives past the point where anyone runs a tyre, and my
hypothesis about why the engine wants to stay out was wrong.

**What was actually wrong is that the model cannot see past its own data**, and
was not saying so. Over 46 laps the fitted linear rate gives the hard tyre 2.0
seconds against a 22.57 s stop, so stopping can never win - but no hard stint at
Zandvoort ran past 36 laps, and nothing in the data says what lap 50 looks like.
That is truncation of the covariate, not noise, and no curve-fitting fixes it.
Teams pit before the cliff, so the steep part is absent *because* it is steep.

So the fit now records `observed_max_age` per compound, and an option is flagged
when it needs a tyre older than anything seen. Re-running the 49 Dutch GP calls:
**31 of them, 63%, rest on tyre ages never observed.** And the flag discriminates
exactly where it should:

| lap | call | tyre age needed | ever seen | |
|---|---|---|---|---|
| 26 | stay out | 49 | 21 | guessing |
| 71 | stay out | 23 | 33 | supported |

Which reframes yesterday's +59.1% skill properly. The late-race stay-out calls -
the ones that carry the score - are well inside the evidence. The mid-race ones,
where staying out means running 46 laps on one set, were never supported by
anything and are now marked as such rather than quietly averaged in with the
rest.

**The methodological point, which is the part I want to remember.** Both
yesterday and today the failure was a model answering a question outside the
range it had any evidence for, and answering it in a confident voice. The
decision layer did it by having no "whether" option; the pace model did it by
extrapolating a straight line into tyre ages nobody has run. A fit that reports
`observed_max_age` alongside its coefficients is making a smaller claim than one
that reports coefficients alone, and the smaller claim is the true one.

**Still open, and now clearly the next thing.** Identifying a cliff needs stints
long enough to contain one, which no single race provides. `PLAN.md` §5.2 already
called for hierarchical priors pooled across races, and the pit-loss model showed
the pattern works - 87 races out of the local FastF1 cache at no API cost. That
is how the extrapolation range gets extended honestly, rather than by assuming a
curve.

---

## 2026-08-23 — First live race: it worked, it lost to the baseline, and why

Zandvoort. The system ran unattended for three and a half hours and did what it
was built to do: 14 MB and 80,535 lines captured, one mid-race feed drop
reconnected without a gap, **49 pit calls committed to git before the laps they
referred to**. `git log predictions/` shows commits landing at 16:04, 16:05,
16:07 while the race was still running. That artifact now exists and cannot be
manufactured after the fact, which was the entire point.

Then it lost to the baseline by 167%.

**Brier (top 3) 0.3820 against a baseline 0.1429. Mean position error 2.50
against 0.76.** The baseline is "everyone finishes where they are now". Track
position is sticky in F1, so that is a strong benchmark — but negative skill of
that size is not a near miss, it is a systematic error.

**The cause, and it was in a docstring the whole time.** The decision layer
frames the question as *when* to stop, never *whether*: "staying out is just a
stop with a larger delay, evaluated on exactly the same footing." That is sound
while a mandatory tyre change is outstanding. It expires the moment the car has
stopped, and nothing in the code noticed. Every delay clamps at the flag, so by
lap 71 all twelve options had collapsed onto lap 72 — which is why those entries
carry `margin +0.00`, twelve identical answers dressed as a decision. It advised
pitting the race leader on lap 71 of 72 and put his expected finish at P4.90.
Norris won.

Fixed by offering a real `stay out` option, gated on the car having stopped at
least once — which is exactly when it becomes legal, and exactly when the old
framing's premise runs out. `planned_pit=None` already meant "not planning to
stop" in the simulation, so no new machinery underneath.

**Re-scored, matched lap-for-lap and car-for-car against the live ledger** — same
lap, same driver, same state, one variable changed. Post-hoc and labelled as
such, in `reports/rescore/`; the live 49 stand untouched, because a ledger you
rewrite when it embarrasses you is not evidence.

| | live | rescored |
|---|---|---|
| Brier (top 3) | 0.3820 | **0.0585** |
| skill vs baseline | −167.4% | **+59.1%** |
| mean position error | 2.50 | **0.48** |

It now beats the baseline it lost to, and mean expected position across the 49
calls moves from P4.26 to P2.08. The two calls that still say *pit* are laps 21
and 25 — the only two where the car had not yet made its mandatory stop, so the
guard held.

**But 47 of 49 now say "stay out", and that is not a victory.** At lap 26 that
means running 46 laps on one set of tyres, which no team would do. So I checked
the arithmetic the model is actually doing, and it is damning: fitted degradation
is **+0.044 s/lap on the hard**, so 46 laps of tyre age costs **2.0 seconds**,
against **22.57 s** for a pit stop. Once the mandatory stop is done, stopping can
never be worth it. The engine is not choosing to stay out; it has no arithmetic
under which stopping wins.

Two reasons, and both were foreseeable:

- **The degradation model is linear in tyre age.** `PLAN.md` §5.2 specified
  `α·age + β·age²`, the quadratic term explicitly there to capture the cliff.
  The implementation has only `α_c · tyre_age`. A model with no cliff term cannot
  represent a cliff.
- **The data is censored, and censored in exactly the wrong direction.** Teams
  pit *before* the tyre falls off. The steep part of the curve is therefore
  almost absent from the observations, and a linear fit through the flat part
  extrapolates a tyre that lasts forever.

So today's headline is honest but narrow: a real bug was found and fixed, and the
forecast stopped being dragged down by a phantom stop. The *strategy* logic
underneath is now biased the other way, for a different reason, and the improved
Brier score does not test it — the ledger grades finishing-position forecasts,
not whether the call was the right call. Worth stating plainly before anyone
quotes +59.1% at me, including me.

**What the scoreboard was for.** The plan said the first live race would break
somewhere and that a public post-mortem beats a suspiciously clean debut. It
broke in the decision layer, the ledger caught it within hours, and the fix is a
regression test that fails on the exact lap-71 case. That is the machinery
working, not the machinery being embarrassed.

Next: the cliff term, and censoring-aware degradation. Until then the engine's
late-race calls should be read as "the forecast is sound, the recommendation is
not yet".

---

## 2026-08-22 (later still) — The fat tail, and two ways to get it wrong

Pit loss was measured this afternoon but still drawn from a symmetric normal. That gets the shape
wrong in the one direction that matters: a stop cannot go meaningfully *better* than a clean one —
the pit lane has a speed limit and the stationary time has a floor — but it can go very much worse.
And a marginal pit call is decided by the expensive futures, not the typical one.

**The distribution, once you look at it.** Excess over each race's own median, pooled across 2023–25
so the circuit constant drops out: p75 +1.0 s, p90 +2.6 s, p95 +8.9 s, max +30 s. Firmly
right-skewed, as expected.

But also p1 **−5.4 s**, min −11.0 s. A stop cannot cost eleven seconds *less* than the median, so
that left tail is measurement, not physics: the out-lap runs on fresh tyres against a baseline of
worn ones, so genuine tyre-age gain is being subtracted from the measured pit loss. The median
absorbs it, and the core spread is therefore an upper bound on true pit-lane variability rather
than an estimate of it. Worth knowing before anyone reads 1.4 s as the real scatter of a pit stop.

**First way to get it wrong: penalties.** 3.3% of stops came out more than 12 s slower than the
race median, which is an order of magnitude above the real rate of catastrophic pit stops. The
empirical p99 was +20.5 s, which is *suspiciously exactly* a drive-through. A served time penalty
is added to the stationary time, so in lap data it is a pit stop that went badly — indistinguishable
from a botched one. Race control announces them, but `RacingNumber` is null on those messages and
the car number lives only in the text, so it has to be parsed out of "FOR CAR 55 (SAI)". Excluding
the 134 stops that served one halves p95, from +8.95 s to +4.88 s.

This mattered more than a tidier number. An over-fat tail is not a conservative error: it tells the
simulation that stopping carries a risk it does not carry, and biases every call against pitting.
Getting the contamination out was the difference between modelling botched stops and modelling the
stewards.

**Second way: double-counting the core.** The obvious estimator — botch rate = fraction of stops
more than 2 s over the median — is wrong, and quietly. With a spread of 1.4 s, about 7% of
*perfectly clean* stops clear +2 s on ordinary scatter alone. Counting them as botched inflated the
rate from a real 5.0% to 12.1%, and the simulated P(stop >2 s slow) came out at 17.6% against an
empirical 12.1%. Subtracting what the core already explains, and taking the scale from the mean
rather than from the same threshold count, fixes it: fitted rate 5.0%, scale 3.81 s, and the
mixture now reproduces the empirical mean excess *exactly* and P(>2 s) to within 0.2 points.

**Where it deliberately stops.** Above +15 s the model does not reach, and the empirical p99 sits
above that cap. Beyond there it is a front wing change, a repair, or a penalty the parser missed —
a different event. Discovering that the >15 s outliers carried **half the total mean excess**
(+0.62 s pooled, +0.29 s in-scope) was the moment this stopped being a rounding argument. The
honest cost is that a genuinely catastrophic stop — the stuck wheel nut that costs half a minute —
is not modelled either, because in lap data I cannot tell it apart from damage.

**What it moves.** Leclerc, Hungary lap 34, 6,000 sims: expected P4.781 symmetric against P4.879
with the tail, top-3 31.9% against 30.1%. Modest, and it should be — a tail that swung calls around
would mean I had fitted the contamination rather than the phenomenon.

**A test of mine that was passing by luck.** `test_the_model_overrides_the_flat_config_constant`,
written this afternoon, put two cars 30 s apart and asserted the pit-loss model changed the expected
finishing position. It cannot: the leader wins every simulation whatever a stop costs, and the
expected position saturates at exactly 1.0. It had been passing on floating-point noise between two
identical answers, and the tail made both land on 1.0 at once. Any assertion about pit loss has to
be made where track position is actually contested, so it now runs on a three-car field within five
seconds. A test that cannot fail for the right reason is worse than no test, because it is counted.

---

## 2026-08-22 (later) — Pit loss, and a lookup that had been failing in silence

The last hard-coded constant in the engine was pit loss: a flat 20.0 s ± 1.2 for every circuit,
carried since Phase 3 because the plan called for a per-circuit measurement and Phase 3 had a
Monte Carlo engine to build. It is the number the *timing* of every call rests on.

**The measurement.** For each stop, the quantity the simulation actually adds — total time lost
against staying out, `(in_lap - baseline) + (out_lap - baseline)` — against a *local* per-driver
baseline of green, accurate, non-pit laps within five laps either side. The local baseline is what
makes this work without modelling anything else: fuel load, track evolution and the driver's own
pace are all near-constant across a fifteen-lap window, so they cancel rather than needing
correction. 89 usable races, 2,066 stops, from the FastF1 cache at no API cost.

**It validates against a number I did not fit.** Spa comes out at 18.40 s raw. `PLAN.md` wrote in
June, from a published source, that Spa is the cheapest stop of the era at ~18.4 s. Two independent
routes to the same figure is the only real evidence an estimator of this kind is measuring what it
claims.

**And the constant really is constant.** Monza across four seasons: 25.23, 25.29, 25.82, 25.29. The
plan's claim that this is the most stable number in the sport is not rhetoric. Which is precisely
why one flat value was the wrong model — it is reliable, it is just *different everywhere*, and the
calendar spans about nine seconds from Spa at 19.5 to Lusail at 25.6.

**Three filters, each removing a way the number would be wrong rather than merely noisy.** Stops
under a safety car are excluded, because they are genuinely cheaper and the simulation already
discounts that separately — folding them in would discount it twice. Stops whose reference window
disagrees with itself by more than 1.5 s are excluded, which is what keeps wet and drying races
out of a dry constant without needing to know which races were wet. And a race contributes its
*median*, not its stops: the 2023 Dutch GP alone yields 34 measurable stops at a median of 31 s,
and pooling stops would have let one chaotic afternoon define Zandvoort's constant.

**Zandvoort: 22.58 s, not 20.0 s.** Tomorrow's race was being simulated with a stop 2.6 s cheaper
than it is. On the Hungary recording, correcting to Budapest's 21.62 s moves Leclerc's lap-34 call
from an expected P4.60 to P4.86 and — the part that matters — narrows the margin over the next
option from +0.30 to +0.18. Same call, honestly less certain. That margin is what the engine uses
to decide whether to say "marginal" instead of dressing a coin-flip as a decision.

**The bug this uncovered is worse than the gap it fixed.** Building a per-circuit lookup meant
checking that per-circuit lookups work, and they did not. These models are fitted on FastF1's
`Location` and queried at runtime with the name the live feed sends, `Meeting.Circuit.ShortName`.
**Nine of twenty-seven circuits spell those differently.** `circuit_factor.get(name, 1.0)` returned
the neutral default and nothing reported it — no error, no warning, just the model quietly
declining to use what it knew.

So the 2026 Hungarian GP — the one race this system has actually run against, the race every number
in this repo is fitted on — used a safety-car factor of 1.0x when the fitted value was 0.58x. A
73% overestimate of safety-car risk, in the analysis I have been treating as the baseline. Barcelona,
Monaco, Montréal, Singapore, São Paulo and Yas Marina were all equally inert, which is to say the
per-circuit hazard model had been switched off at a third of the calendar since the day it was
written.

I did not write the alias table from memory, and the reason is that a wrong entry there maps one
circuit's history onto another and *still* nothing errors — a worse failure than the one being
fixed, and equally silent. `scripts/circuit_aliases.py` reads both spellings out of F1's own session
info for every cached race and prints the pairs that disagree, with `Circuit.Key` alongside as the
one genuinely stable identity. Re-run it when a season is added.

**The lesson worth keeping** is that both of today's findings — the ledger that was never wired up,
and this — are absences rather than errors. Nothing failed. Nothing logged a warning. Every test
passed. A `.get(key, default)` with a sensible default is a decision to fail silently, and I had
written two of them into the parts of the system whose whole purpose is to be checkable.

**Still not done:** the spread is symmetric, and the real stop distribution has a long right tail —
a botched stop is ten seconds slow, a good one is never ten seconds early. The plan asked for that
tail explicitly. It is the next thing.

---

## 2026-08-22 — The night before Zandvoort, and the gap that would have wasted it

Race-day preflight, the day before the first live race. The suite is green, the endpoint still
answers unauthenticated, and the models know the circuit. One thing was missing, and it was the
only one that mattered.

**The dashboard never logged anything.** `Engine._compute` built a full `Recommendation` every lap
and then flattened it into an `Advice` for the screen. `PredictionLog` was wired into `backtest`
and `report` — both of which run against a *finished* recording — and nowhere else. Every one of
the 28 predictions in this repo was made after the fact, against a race whose result was already on
disk.

So tomorrow, as built this morning, would have produced a nice screen, a ~200 MB recording, and
zero live track record. The README already claimed otherwise. The plan said, in June, "build the
commit step into the live loop so it happens automatically, not by hand" — and then five phases
happened and nobody checked that sentence against the code.

That is the failure worth writing down: not a bug, an *absence*, in the one feature the whole
project is a delivery mechanism for. Nothing failed a test, because no test asserted it. The engine
worked. The dashboard was pretty. The thesis was unimplemented.

**Fixed, with the guards that keep a ledger meaningful rather than merely full.** Predictions are
written only when `LapCount` reports a race — practice and qualifying never send it, so a dashboard
left running through FP1 records nothing and could not be scored against a classification anyway.
Only once per lap, because F1's feed drops after about two hours and a Grand Prix *is* two hours,
so the reconnection that replays the state snapshot and revisits a lap is the expected path, not
the exception; logging it twice would double-count that call in every score drawn from the file.
And never fatally — a ledger failure costs the calls, not the engine.

**The CLI refuses to commit predictions made from a `--replay`.** This one is not defensive
programming, it is the whole argument. A replayed race contains its own outcome; a commit timestamp
on a call made from it proves nothing, and mixing those into the same file as live calls would
quietly destroy the evidentiary value of every honest entry beside them. `--no-commit` still allows
a rehearsal.

**A rehearsal that lied, and why.** First end-to-end run against the Hungary recording logged
*nothing* while replaying all 76,979 events. Not the guards — `MIN_SECONDS_BETWEEN_ADVICE` is 8
seconds of wall clock, and at unbounded replay speed the whole race folds in 6.8 s, so exactly one
advice attempt fired, at lap 1, where the pace fit is correctly not yet identified. Live, laps are
~80 s apart and the throttle never binds. Worth knowing before reading a quiet dashboard tomorrow
as a failure: at max speed this system is *supposed* to look idle. With the throttle neutralised
the real path ran — 47 calls, one per lap from 24 to 70, no duplicates, and laps 1–23 refused while
the design was unidentified.

**Zandvoort is a good first race for this engine.** Shrunk safety-car factor 1.45x, third of 26
circuits behind only Melbourne and São Paulo, on four races. Over 72 laps that is a 72% chance of a
safety car and 87% of some neutralisation. The part of the simulation that compresses the field and
discounts a stop taken under a neutralisation is the part most likely to be *exercised* tomorrow —
and most likely to be caught being wrong, which is better.

**Still open, and going in as known.** Pit loss is a flat 20.0 s ± 1.2 for every circuit; the plan
called for a per-circuit constant measured from history and never got one. Zandvoort's real number
is close enough to 20 s that tomorrow is not the day to change it, but every call is sitting on an
assumption rather than a measurement, and the next quiet week should fix it. The compound
confounding from Hungary is unchanged — Zandvoort is the second data point that starts to break it.

---

## 2026-08-10 — Making the anti-rot rule executable

Two days ago the audit found the README quoting numbers the code no longer produced — the hazard
table stuck on the 94-race fit, the strategy example predating the running-order fix. I fixed the
text and wrote down the real lesson: the numbers that stayed honest were the ones a command
regenerates, and the two that rotted were hand-pasted with nothing behind them. Writing that down is
not the same as fixing it, so today it becomes a tool.

`scripts/readme_examples.py` re-runs the four commands the README quotes — `laps`, `hazard --kind
any`, the lap-34 `strategy` call, `report` — and prints each block under the heading it belongs to.
Refreshing the README is now a run and a diff instead of a paste taken on trust. It deliberately does
not edit the file: it prints the current truth beside where each block lives and leaves the paste to
a human, because a script that rewrites its own documentation is a new way to be silently wrong.

Two small things fell out of building it. The strategy block needed the same trim the README uses —
three options then `...` then the undercut line — so the tool reproduces that rather than dumping all
twelve, which means its output is paste-ready rather than merely correct. And `report` writes a file
as a side effect; pointing `--out` at a tempfile keeps the generator from littering `reports/` every
time it runs, the same discipline the prediction commits already follow.

Ran against today's code it prints exactly what the README now carries, which is the point: the check
that would have caught the 8 August drift is green because the drift is already fixed. The value is
the next time — a model change that moves a number will now show up as a diff the moment anyone runs
this, instead of surviving to the next person who reads the file closely.

---

## 2026-08-08 — An audit, and which numbers rot

No new feature today — a pass back through every phase to check nothing had quietly drifted since
the attrition work. The code held up: 263 tests pass, lint and format clean, and the CLI still
reproduces the documented output for `laps`, `hazard`, `strategy` and `report`.

The README did not, in two places, and the pattern in *which* two is the useful part.

**The safety-car block was the 94-race fit.** It still read lap1 0.2234, Melbourne 2.33x, Barcelona
0.48x over four races — the numbers from before the attrition history grew the sample to 103. The
prose two lines above already said "103 races", so the table was contradicting its own caption. The
current safety-car-or-VSC fit reads lap1 0.2136, Melbourne 2.24x, Yas Island now the calmest track.
While fixing it I noticed the block is the `--kind any` view but the default `pitwall hazard`
reports safety cars alone (17% on lap 1, not 21%), so the command now says which is which.

**The strategy example was pre-fix output.** It showed LEC P3 at lap 30 stopping to an expected
P2.41 — a decisive, tidy call. Folding the recording to lap 30 today puts LEC P5, and every compound
option there sits within a tenth of the others, so the honest call is "marginal, no clear
recommendation". That example dates to the Phase 3 commit on 28 July and was never regenerated after
the 29 July running-order fix — the same bug write-up already in this logbook, quietly still on
display in the README. Moved it to lap 34, where LEC really is P3 and the engine makes a clean
"PIT now on hards", which is also the scenario in the dashboard screenshot.

**The lesson is about provenance, not arithmetic.** The numbers that stayed correct — the scorecard,
the clean-lap counts — are the ones produced by machinery: `report` and `laps` regenerate them, so
they cannot drift without the code drifting too. The two that rotted were both hand-pasted snippets
of example output with nothing regenerating them. So the fix that actually prevents a recurrence is
to generate the README's example blocks the same way the race report is generated, rather than
trusting a paste to stay true across a model change. Filed as the next chore; for now they are at
least correct again, and the Monte Carlo is seeded so they reproduce exactly.

A small reassurance in a boring pass: the things designed to stay honest did, and the things that
slipped are exactly the things the project's own philosophy says to distrust — a number without a
process behind it.

---

## 2026-08-02 — Attrition, and a hypothesis that was right after all

Every car finished, every time. Roughly one in ten does not, and a simulation without that is wrong
in a specific, one-sided way: it can never promote anyone. A car running P8 gains places when two
ahead retire, and the model treated that as impossible rather than as a one-in-ten event repeated
across seven cars.

**Fitted, not guessed.** Extending the history fetcher cost almost nothing because FastF1's cache
already held 103 races. `ClassifiedPosition == "R"` marks a retirement and the car's last completed
lap dates it. **204 retirements from 2,080 starters — 9.8% per car-race**, and 43 of those are on
lap 1.

**Lap 1 again.** The same spike as safety cars, and larger in relative terms:

| phase | hazard per car-lap |
|---|---|
| **lap 1** | **0.0207** |
| early | 0.0014 |
| mid | 0.0018 |
| late | 0.0017 |
| final | 0.0007 |

A **14× spike** on the opening lap. Two independent hazards, fitted from different columns of
different data, both saying the same thing about lap 1.

Circuit factors rank plausibly: Melbourne 1.68×, Jeddah 1.41×, Silverstone 1.33× at the top;
Budapest 0.51×, Barcelona 0.53×, Yas Island 0.68× at the bottom.

**Exposure is per car-lap, not per race.** A car that retires on lap 20 was at risk for twenty laps
and then stopped being at risk. Counting it as a full race would understate the hazard, most for
the circuits where cars fail earliest, and counting the race rather than the car would ignore that
twenty-two cars each roll the dice.

**And it measurably helped**, which is the part I did not expect. Back on 29 July I guessed the
calibration miss came from under-modelled chaos, ran a diagnostic, and concluded the guess was
wrong — position volatility already matched reality. That conclusion was right about *dispersion*
and wrong about *promotion*: the field moved the correct amount overall, but nobody was ever
promoted by a retirement ahead of them.

| | before | after |
|---|---|---|
| Brier skill (top 3) | +3.7% | **+8.5%** |
| Brier skill (points) | +1.1% | **+7.1%** |
| 0–20% calibration gap | 7.0 pts | **1.2 pts** |
| Mean position error | 3.53 | 3.69 |

Skill roughly doubled and the low-confidence band is now nearly perfectly calibrated — it says
11.2% and it happens 10.0%. Point-estimate error got slightly *worse*, which is the honest
trade: retirement variance widens the distribution, so the mean drifts from the mode. For a model
whose output is a probability, that is the right direction to trade in.

**A third circuit rename.** Monaco became "Monte Carlo" in the 2026 data — after Miami became
"Miami Gardens" in 2025. Same silent split, same fix. The alias table now carries a note to check
it whenever a season is added, because this is clearly a pattern and not an accident.

**A test that was wrong again.** I asserted a retired car always classifies behind the other car.
It does not when *both* retire — then they are ordered by distance covered, which is how F1
actually classifies them, and the quick car can legitimately be ahead. Now isolated to runs where
the other car finished.

---

## 2026-07-31 — Reconnection proved, and there is no FP2 to rehearse on

The plan was to dress-rehearse the live path on FP2 at Zandvoort. **Zandvoort 2026 is a Sprint
weekend, so there is no FP2.** The format is one hour of practice and then straight into
competitive sessions:

| | session | Irish time |
|---|---|---|
| Fri 21 Aug | FP1 | 11:30–12:30 |
| Fri 21 Aug | Sprint Qualifying | 15:30–16:14 |
| Sat 22 Aug | Sprint | 11:00–11:30 |
| Sat 22 Aug | Qualifying | 15:00–16:00 |
| Sun 23 Aug | **Race** | 14:00–16:00 |

Friday is a better rehearsal than FP2 would have been anyway: two live sessions separated by three
idle hours exercises capture, the idle backoff, and reconnection in one unattended run.

    nohup ./scripts/scheduled_record.sh "2026-08-21 11:15" data/raw/2026-netherlands-friday.txt 320 &

**Reconnection is no longer the untested gap.** It was the one thing I had flagged as only
exercised against forced local failures, and F1's feed drops after roughly two hours while a Grand
Prix *is* two hours — so the failure mode is the expected case, not the exceptional one.

Two levels of evidence now. Fault injection in the test suite drives the retry loop through drops,
escalating backoff, the cap, the reset after a good connection, and cancellation. And against the
real endpoint, with the silence timeout cut to six seconds to force genuine drops: **11 successful
reconnections in 75 seconds**, each a full negotiate → connect → handshake → subscribe → snapshot,
with all 22 cars still in state afterwards. The backoff held at 1s throughout, which is the
reset-after-success path working in the wild rather than only in a test.

**A bug in the test helper, which is still worth writing down.** My fake feed raised scheduled
failures with `isinstance(step, Exception)`. `asyncio.CancelledError` derives from
`BaseException`, not `Exception`, so the cancellation case never raised — the helper tried to
*iterate* the exception instead, the loop caught the resulting `TypeError` as a connection drop,
retried forever, and the suite hung for seven minutes instead of failing. The same confusion in
production code would make a process refuse to shut down. `BaseException` in the helper, and the
real code already had it right: it re-raises `CancelledError` before the generic handler.

---

## 2026-07-30 — Dashboard

A live timing tower, the current pit call with its ranked alternatives, undercut threats and feed
health, pushed over a websocket. Deliberately small: the dashboard is evidence the engine works,
not the product.

The design decision that matters is that it runs off a `RaceFeed`, so it is identical live or on a
recording. `pitwall dashboard --replay ... --speed 20 --skip 62` reproduces the Hungarian GP from
lap 30 in about a minute, which means it can be demonstrated on any Tuesday rather than once a
fortnight.

**The simulation runs in a worker thread.** A twelve-option decision is a second or two of numpy,
and running it on the event loop would freeze ingest and the screen exactly when a strategy call is
being made. The last completed answer stays up while the next is computed.

**A subtle bug worth writing down.** Every websocket upgrade was rejected with `403`. The route was
registered, the REST endpoints worked, and the server logged nothing. Turning on trace logging gave
it away:

    Send {'type': 'websocket.close', 'code': 1008,
          'reason': [{'loc': ['query', 'socket'], 'msg': 'Field required'}]}

FastAPI was treating `socket: WebSocket` as a *query parameter*. `from __future__ import
annotations` turns every annotation into a string, and FastAPI resolves those against the module
namespace — but `WebSocket` was imported *inside* `build_app`, to keep fastapi an optional
dependency. Unresolvable annotation, so it fell back to "unknown parameter, must be a query param",
and reported a missing field rather than an import problem. Dropping the future import from that
one module fixes it, because the annotation is then evaluated where the import is in scope.

**And one the screenshot caught.** Running the dashboard mid-race showed most of the field on an
unknown tyre, and the leader's gap column reading `LAP 37`. Two causes. `--skip` used
`ReplayFeed.skip_to`, which *discards* earlier events — including the stints that had already
announced everyone's compound. It now uses a new `warp_until`, which replays them at full speed and
only then starts pacing. And `GapToLeader` carries `"LAP 37"` for the leader, which the simulation
already knew to ignore but the display did not.

---

## 2026-07-29 (later) — Chasing the calibration miss, and finding two bugs instead

The last report said the model was underconfident about cars reaching the podium and guessed the
cause was under-modelled safety-car chaos. That guess was wrong, and worth recording as wrong.

**The diagnostic rejected the hypothesis.** Simulated mean |Δposition| from a given lap to the flag
tracks reality closely — 2.57 against a real 2.45 at lap 24, 1.95 against 1.82 at lap 32. The
simulation is not too rigid. Only lap 16 was out, and wildly *over*-dispersed at 7.42, which
pointed somewhere else entirely.

**Bug 1: the race leader was being simulated from last place.** Looking at the individual misses
rather than theorising: `lap 16 NOR P21 said 0.0% finished P1`. Norris was never P21 — he won.
`entries_from_state` built each car's position from `GapToLeader`, and that field is not reliably a
gap. The leader's carries `"LAP 17"` — the lap it is *on*. P2's was `None`. Both failed to parse,
and the fallback dropped unparseable cars to the back, putting the two fastest cars **112 seconds
behind the field** in every simulation. The engine then correctly concluded that a car running last
would not finish on the podium. The running order is now authoritative and gaps only refine spacing
within it, with elapsed times forced non-decreasing down the order.

**Bug 2: fits nobody should have simulated from.** At lap 16 the pace fit was rank deficient and
reported a **67-second** spread in driver pace and **+28 s/lap** of hard-tyre degradation. Early in
a race the design genuinely is not identified — few laps, one stint per car, fuel and degradation
perfectly collinear — and least squares answers anyway. `PaceFit.usable` now rejects a fit that is
rank deficient, has a positive race-lap trend, or reports physically impossible coefficients, and
the backtest publishes nothing rather than a confident number drawn from noise. Laps 12, 16 and 20
are now refused at Hungary; 24 onward pass.

**The calibration miss is largely fixed.** The 0–20% band went from *said 3.3%, happened 30.8%* to
*said 8.4%, happened 15.4%* — a 27.5-point gap down to 7.0.

**And the headline number I reported last time was inflated by the same bug.** Skill has gone from
+33.2% to **+3.7%**, and that is a correction, not a regression. The baseline scores each
prediction against its recorded position, and those positions were the corrupted ones — so the
baseline was being asked to explain how a car "running P21" won the race, failed, and made the
model look far better by comparison. The honest figure is that this barely beats assuming the order
holds. Worth stating plainly: the impressive version was an artifact, and I published it.

**Where it stands.** A milder underconfidence remains in the middle bands (said 30.6%, happened
57.1%), but on seven predictions from one race. Chasing that now would be tuning to a single
afternoon, which is exactly the failure this machinery exists to prevent. It needs Zandvoort and
the races after it.

---

## 2026-07-29 — Prediction ledger, scoring, and a leak I had shipped

Phase 5. The engine now writes every call to an append-only log, commits it as it is made, and
grades itself against what happened. This is the credibility machinery the whole project was
pointed at: anyone can publish a model that looks good in hindsight, and the only defence against
that suspicion is a commit timestamp from before the outcome was known.

Three rules keep the guarantee real. The log is **append only** — a call that ages badly stays in
it. Commits happen **immediately**, not batched after the flag when results are known. And a
prediction commit stages **only the log file**, never `git add -A`, because a commit that also
carried a source change would let a sceptic argue the model was tuned to fit.

**The bug this exposed was mine, and it was already shipped.** `pitwall strategy --lap 30` claimed
to answer "what would the engine have said at lap 30". It did not. It folded the *entire*
recording, captured a snapshot it then threw away, and simulated from the **final classification**
using a pace model fitted on **all 70 laps**. Two separate leaks of the future into a decision that
was supposed to predict it, and the output looked completely reasonable throughout — LEC showed as
P3 at lap 30 when he was actually P4. `fold_to_lap` now stops folding at the target lap, which
fixes both at once.

Worth noting how it surfaced: not from a test, but from building the scoring harness and finding
the numbers were nonsense. The leak made results *worse* (−1.2% skill), because feeding
end-of-race positions into a lap-16 simulation is garbage rather than cheating. A leak that
flattered the model would have been far harder to notice.

**The honest first scorecard**, 35 leak-free predictions across laps 16–48:

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (top 3) | 0.2481 | 0.3714 | **+33.2%** |
| Brier (points) | 0.1366 | 0.1429 | +4.4% |
| Mean position error | 3.46 | 3.17 | — |

Better than "assume the order holds" at *probabilistic* top-three calls, and worse than it at point
estimates of finishing position. A genuinely mixed verdict, and the report says so rather than
quoting the flattering half.

**Calibration is the more useful finding.** In the 0–20% band the model said 3.3% and it happened
30.8% of the time. It is badly underconfident about cars reaching the podium from further back —
almost certainly because the simulation under-models safety-car chaos and overtaking, so it treats
the current order as more fixed than it is. That is a specific, actionable defect, and it came out
of the scoring machinery rather than from staring at the model.

**A scoring bug caught by its own test.** Skill is `1 - model/baseline`, undefined when the
baseline is perfect. I returned 0.0 there — "matched the baseline" — while the model was wrong on
every call. That is an error in the one direction a scoring function must never fail in, since it
flatters the model. Now reported as infinitely worse and rendered as `worse*`.

---

## 2026-07-28 (evening) — Live SignalR parser

Phase 4, and the piece the whole project was pointed at. FastF1's client connects to this same
endpoint and writes frames to disk, its docs stating plainly that it "is *not* possible to do
real-time processing of the data". That is a scope decision, not a property of the feed. This
parses the frames as they arrive, so the reducer, models and simulation built over the last two
days now run against a live race rather than a recording.

**The protocol had to be established by probing, because there is no documentation.** Two findings
matter:

*The classic SignalR endpoint is dead.* Nearly every public client and gist uses
`GET /signalr/negotiate?clientProtocol=1.5`. It now answers **401**. Anything written against that
path has stopped working, which is presumably why FastF1 moved.

*`/signalrcore` still accepts unauthenticated connections.* FastF1 wires in an F1 TV
`access_token_factory`, so it looked like login was mandatory. It is not — the negotiate returns
200 with no credentials at all. The working sequence:

1. `OPTIONS /signalrcore/negotiate` → answers 405, but sets the `AWSALBCORS` load-balancer cookie
   that every later request must carry. Without it the websocket upgrade is refused.
2. `POST /signalrcore/negotiate?negotiateVersion=1` → `connectionToken`.
3. `wss://livetiming.formula1.com/signalrcore?id=<token>`.
4. Handshake `{"protocol":"json","version":1}`, server replies `{}`.
5. Invoke `Subscribe` with the topic list.

Frames are JSON delimited by an ASCII record separator (0x1E), several per read. Type **3** is the
completion carrying the state snapshot, type **1** a feed update, type **6** a keepalive ping.

**A pleasing symmetry:** a type-1 message's `arguments` are `[topic, data, timestamp]` — exactly the
triple the recorder writes to disk. Live and recorded data therefore parse through the same code
path, which is why `SignalRFeed` and `ReplayFeed` are genuinely interchangeable rather than
approximately so.

**Verified live, with no race running.** The endpoint replies with the previous session's snapshot
and then pings, which is enough for a real end-to-end test today: 17 events in 0.32 s, folded into
the correct final Hungarian GP classification, all 22 cars. **Decode p50 0.05 ms, p99 4.6 ms.**
Feed lag is not yet measurable — snapshot events carry no timestamp, so that number only becomes
real at Zandvoort.

**The same trap twice.** Between sessions the feed sends *only* pings, which correctly produce no
events — so any deadline check written inside the `async for` body never executes and the consumer
hangs forever. It caught my first probe and then, embarrassingly, the `--duration` flag on the CLI.
The fix is to wrap the iteration in `asyncio.timeout`, not to check inside it. Worth remembering:
"no events" and "no connection" look identical from inside a for loop, and only one of them is a
problem.

**What is not done.** Reconnection logic exists and backs off exponentially, but has only been
exercised against forced local failures, not a real two-hour session drop. Zandvoort is the test.

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
