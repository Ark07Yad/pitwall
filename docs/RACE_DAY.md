# Race day

> **Next up: Singapore GP, Marina Bay — Sunday 11 October, 13:00 Irish.** A sprint weekend. See
> "Marina Bay" below. The Kuala Lumpur, Baku and Monza sections are kept as worked examples; their
> numbers are theirs.
>
> **If the start is delayed, rearm.** The launcher's deadline is fixed when it starts. On 4 October
> the race began 93 minutes late and finished three minutes after the original arm would have
> stopped recording. See "When the start slips" under Kuala Lumpur.

## Marina Bay

**Race: Sunday 11 October, 13:00 Irish** (20:00 local). A sprint weekend: practice Friday 9 at
09:30, sprint qualifying Friday 13:30, **sprint Saturday 10:00**, qualifying Saturday 14:00. None
is needed live — the archive has every session afterwards.

### What good looks like

Every model has history here, so this is the Baku check and the opposite of Kuala Lumpur:
**`fitted: false` would be a fault.** The feed sends `Singapore`, which resolves to `Marina Bay`.

| field | expected |
|---|---|
| `circuit` | `Singapore` |
| `total_laps` | **62** |
| `model.pit_loss` | `{"seconds": 24.2, "expected": 24.49, "fitted": true, "races": 2}` |
| `model.prior` | `{"factor": 0.82, "fitted": true, "races": 3, "pooled_races": 81}` |
| ledger rows | `unfitted: ""` |

### What to expect from the models

| | Marina Bay (62 laps) |
|---|---|
| P(safety car) | **54%**, expected 0.76 |
| P(any neutralisation) | **79%**, expected 1.53 |
| lap-1 hazard (any) | **23.3%**, against 2.3% for any other lap |
| expected retirements | **2.58 of 22** — attrition factor 1.17x |
| pit loss (median / expected) | **24.20 s / 24.49 s**, on only 2 races |
| degradation factor | **0.82x** (3 races) |

Pit loss here is among the highest measured and degradation among the lowest, which is the Monza
shape: both push toward one stop, and toward a window that closes early.

### The window, and when the engine will actually speak

A second stop on a 26-lap-old hard needs **31 laps** of remaining running to pay, and on a
26-lap-old medium **26** — so the last lap another stop can be recommended is about **lap 31 of
62** on hards, lap 36 on mediums.

Measured on the last four races here, rebuilt from the archive (`scripts/window_sweep.py`):

| year | conditions | pace fit stable from | laps of window left (hard) |
|---|---|---|---|
| 2022 | wet to lap 35 | never, inside laps 8–45 | none |
| 2023 | dry | **lap 42** | none — the fit stood up eleven laps after the window shut |
| 2024 | dry | lap 25 (first usable 14) | about six |
| 2025 | dry | lap 26 (first usable 11) | about five |

**So expect silence until about lap 25, and a window of five or six laps if the race is a
2024 or a 2025.** If it is a 2023 — the field running one long stint — there will be no window at
all, and it should be written up that way.

**That silence is now a measured choice.** On 5 October the obvious fix was built and tested:
hold the race-lap trend with a prior so a field on one stint can be fitted. With it these fits
stand up at lap 19, 10 and 11 instead of 42, 25 and 26. It was not switched on, because the calls
it unlocks are bad: across eight races, a decisive "stop within three laps" was followed by the
team stopping **44%** of the time on laps the engine already speaks on, and **10%** on the laps
the prior would open. `window_sweep.py --hold-trend` shows the earlier laps; do not read them as
laps a call could be trusted on.

**Rain is a real possibility** — the 2022 race here started wet and never gave a usable fit. If
it does, the wet-phase filter added on 4 October applies: no call while the field is on wet tyres,
and none until six laps after it leaves them. Watch for `dry from lap N` in the model tag.

### Sunday, in this order

```bash
./scripts/race_day.sh --dry-run "2026-10-11 12:45" 2026-singapore-race "2026 Singapore GP" "" 210
```

It must end with `dry run OK - the launch line ran under bash 3.2…`. Anything else, and do not arm.
Then arm it — it waits until 12:45 and records until 16:15:

```bash
nohup ./scripts/race_day.sh "2026-10-11 12:45" 2026-singapore-race "2026 Singapore GP" "" 210 &
```

Confirm rather than assume: `ps -o pid,ppid -p <pid>` shows a parent of `1`,
`pmset -g assertions` shows `caffeinate` holding `PreventSystemSleep`, and
`data/raw/2026-singapore-race-engine.log` shows the target line. Lid open, plugged in.

A 13:00 start can be armed that morning. Singapore runs close to the two-hour limit and is the
circuit most likely to be neutralised, so 210 minutes is deliberate; if the start slips, rearm.

## Kuala Lumpur

**Race: Sunday 4 October, 08:00 Irish** (15:00 local, GMT+8). Practice was Friday 2 October at
05:30 and 09:00 Irish, FP3 and qualifying Saturday 3 at 05:30 and 09:00 — all before the race and
none of them needed live: the archive has every session afterwards.

### Read this before arming: the models know Sakhir, and this is not Sakhir

The event is the **Bahrain Grand Prix**, country code **BRN**, official name *FORMULA 1 GULF AIR
BAHRAIN GRAND PRIX IN MALAYSIA 2026* — and it is run at **Kuala Lumpur**. Sakhir is in every
model, with a **1.90x degradation factor** (second-steepest of the pool) and a 23.57 s pit loss. If
the circuit name resolved to Sakhir, the engine would apply the harshest tyre physics it knows to a
circuit it has never seen and be confidently wrong, which is worse than being blind.

It does not. Checked against the FP1 archive rather than assumed, the feed publishes:

```
Meeting.Name       Bahrain Grand Prix
Meeting.Location   Kuala Lumpur
Circuit.ShortName  Kuala Lumpur      <- what the reducer reads
Country.Code       BRN
```

and the reducer records `circuit: 'Kuala Lumpur'`, which normalises to itself and matches no
history. **So every model is expected to report `fitted: false` here, and `fitted: true` would be
the fault** — the exact inverse of the Baku check below. Do not add an alias for this circuit.
There is nothing to alias it to: Malaysia last held a race in 2017, outside the 2022-2026 window.

### What happened

**Recorded whole, and the engine committed nothing.** Rain delayed the start by 93 minutes; the
race ran 09:33 to 11:20 Irish over 55 laps, one cut after an aborted start. The capture is 10.7 MB
with laps 1–55 present, no feed gap during the race and no engine relaunch. The name trap held:
`Kuala Lumpur` throughout.

Most of the field ran laps 1–8 on intermediates and those laps bent the race-lap trend for the
whole afternoon, so the fit was refused on every lap it could be attempted. That is fixed in
`laps/clean.py` — a wet phase is now treated as a different race and only the dry one is fitted —
and under it this race is usable from lap 31. The logbook entry for 4 October has the detail, and
`predictions/2026-bahrain-gp-in-malaysia-backtest.jsonl` is the post-hoc ledger. There is no live
one.

### When the start slips

The launcher's deadline is `start + MINUTES`, fixed at launch. A delayed start eats the end of the
race. On the day:

```bash
kill -TERM <launcher pid>          # the trap stops the engine and caffeinate with it
./scripts/race_day.sh --dry-run "<now>" 2026-r16-race "2026 Bahrain GP in Malaysia" "" 300
nohup ./scripts/race_day.sh "<now>" 2026-r16-race "2026 Bahrain GP in Malaysia" "" 300 &
```

Same basename and same session name, so the recording appends and the ledger carries on. Stop the
old one **first** and confirm it is gone before starting the new one — never two connections. Do
it while the session is still inactive: the reconnect then costs nothing, and mid-race it costs
laps. Race control's messages are in the recording (`DELAYED START`, `RACE WILL START AT`), so the
new start time can be read rather than guessed.

### What good looked like

| field | expected |
|---|---|
| `circuit` | `Kuala Lumpur` — **not** `Sakhir`, `Bahrain` or `Sepang` |
| `total_laps` | **56** (historic Sepang distance; the feed confirms it on the day) |
| `model.pit_loss` | `{"seconds": 22.17, "expected": 22.45, "fitted": false, "races": 0}` |
| `model.prior` | `{"factor": 1.0, "fitted": false, "races": 0, "pooled_races": 81}` |
| ledger rows | `unfitted` naming all four models |

### What to expect from the models

Everything here is the field average, because nothing else exists:

| | Kuala Lumpur (56 laps) | Baku, for contrast (51) |
|---|---|---|
| P(safety car) | **51%**, expected 0.69 | 45%, 0.58 |
| P(any neutralisation) | **72%**, expected 1.25 | 73%, 1.25 |
| lap-1 hazard (any) | **20.8%** | 22.5% |
| expected retirements | **2.07 of 22** | 2.10 of 22 |
| pit loss (median / expected) | **22.17 s / 22.45 s** (unfitted) | 21.73 s / 22.02 s (89 stops) |
| degradation factor | **1.00x** (unfitted) | 0.92x (3 races) |

### The window, and the risk worth writing down beforehand

A second stop on a 26-lap-old hard needs **23 laps** of remaining running to pay for itself, and on
a 26-lap-old medium **19**. So the last lap the engine can recommend another stop is about **lap 33
of 56** on hards, lap 37 on mediums — a wider window than Baku's lap 26 of 51, because the race is
longer.

**The risk is the other half of the window.** Since 30 September the pace fit refuses while tyre age
and race lap are more than 0.85 correlated, which is the case until the field's stints stagger. At
Baku that did not clear until **lap 41** — past the lap-26 break-even — so the engine would have had
nothing to say inside the window at all. Kuala Lumpur is hot and abrasive and a two-stop race should
stagger the field earlier than Baku's one-stopper did, but that is an expectation, not a measurement.

**Watch `model.age_lap_corr` on the dashboard.** It falls as the stops spread; the fit speaks below
0.85. If it is still above 0.85 at lap 33, the race had no decision window and should be written up
that way — not as the model being quiet for no reason.

### What Friday said, and why it is not in the model

`scripts/circuit_from_practice.py` now reads practice long runs properly (fuel removed at the
physics prior, an intercept per run, no race-lap term) and it does return a number here where the
old path returned nothing: **5.47x the pooled shape across 248 clean laps in 28 long runs.**

That number is not usable as a factor, and `--calibrate` is why. Against four circuits whose factor
*is* fitted from races, the same estimator overstated them by between 1.6x and 12x, and the median
of that ratio moves from 4.6x to 8.0x depending on where the long-run cutoff is set. Converted at
any of those, Kuala Lumpur lands at **0.6-0.9x**.

So the one thing Friday supports is a direction, and it is the opposite of what the event name
suggests: measured the same way as the others, this circuit reads **mid-to-low degradation, not a
Sakhir**. The model stays at 1.00x. If the race's own fit comes out materially above 1.0x, that is
worth a logbook entry.

### Saturday night, in this order

```bash
./scripts/race_day.sh --dry-run "2026-10-04 07:45" 2026-r16-race "2026 Bahrain GP in Malaysia" "" 210
```

It must end with `dry run OK - the launch line ran under bash 3.2…`. Anything else, and do not arm.
Then arm it — it waits on its own until 07:45 and records until 11:15:

```bash
nohup ./scripts/race_day.sh "2026-10-04 07:45" 2026-r16-race "2026 Bahrain GP in Malaysia" "" 210 &
```

Then confirm it rather than assuming: `ps -o pid,ppid -p <pid>` shows a parent of `1`,
`pmset -g assertions` shows `caffeinate` holding `PreventSystemSleep`, and
`data/raw/2026-r16-race-engine.log` shows the target line. Lid open, plugged in. Locking the screen
is fine; closing the lid, sleeping or logging out is not.

**An 08:00 race on a machine on Irish time** means the arm happens the night before and the engine
starts while nobody is awake. That is the Madrid and Baku procedure exactly, and the launcher now
relaunches an engine that dies early (30 s backoff, up to 10 times) rather than ending the
afternoon.

## Baku

**Race: Saturday 26 September, 12:00 Irish** (13:00 local). Practice is Thursday 24 at 09:30 and
13:00, and FP3 and qualifying are Friday 25 at 09:30 and 13:00 — all in working hours, and none of
them needed: the archive has every session afterwards, and practice does not feed the model.

**The Spanish GP was lost to the launcher, not the engine.** It was armed at 08:08, passed every
preflight check, and died at 13:45 on `REHEARSE_FLAG[@]: unbound variable` — macOS's
`/bin/bash` 3.2 treats an empty array under `set -u` as unset, and a real race always passes an
empty one. Fixed, and now covered: `--dry-run` runs this whole script with a stub in place of the
engine, and `tests/test_race_day.py` runs it under `/bin/bash` on a macOS CI runner, including a
version with the old line put back, which must fail.

**Friday night, in this order:**

```bash
./scripts/race_day.sh --dry-run "2026-09-26 11:45" 2026-baku-race "2026 Azerbaijan GP" "" 210
```

It must end with `dry run OK - the launch line ran under bash 3.2…`. Anything else, and do not arm.
Then arm it — it waits on its own until 11:45 and records until 15:15:

```bash
nohup ./scripts/race_day.sh "2026-09-26 11:45" 2026-baku-race "2026 Azerbaijan GP" "" 210 &
```

And confirm it is really armed rather than assuming: `ps -o pid,ppid -p <pid>` shows a parent of
`1` (detached, survives the terminal closing), `pmset -g assertions` shows `caffeinate` holding
`PreventSystemSleep`, and `data/raw/2026-baku-race-engine.log` shows the target line. Lid open,
plugged in. Locking the screen is fine; closing the lid, sleeping or logging out is not.

**What good looks like at Baku.** Unlike Madring, every model has history here:

| field | expected |
|---|---|
| `circuit` | `Baku` |
| `total_laps` | **51** |
| `model.pit_loss` | `{"seconds": 21.73, "expected": 22.02, "fitted": true, "races": 4}` |
| `model.prior` | `{"factor": 0.92, "fitted": true, "races": 3, "pooled_races": 81}` |
| ledger rows | `unfitted: ""` |

Here `fitted: false` *would* be a fault — the name did not resolve.

**What to expect from the models.** Safety car expectation 1.25 over 51 laps, a 73% chance of at
least one, 10th of 26 circuits — and a **22.5% hazard on lap 1** alone. Expected retirements 2.10.

**The window, and when it actually binds.** A second stop on a 26-lap-old hard needs **25 laps** of
remaining running to pay (a 26-lap-old medium, 21), so for a car that has **already made its stop**
the last lap another can be recommended is about **lap 26 of 51**. For a car still on its first
stint that line does not apply: the stop is mandatory, and the engine is choosing when, not whether.

Measured on the last four Baku races rebuilt from the archive (`scripts/window_sweep.py` for when
the pace fit stays usable; backtests for what the calls then were):

| year | early neutralisation | pace fit stable from | what the calls were |
|---|---|---|---|
| 2022 | VSC laps 9–10 | lap 17 | not checked |
| 2023 | **SC laps 10–13** | lap 26 | field stopped laps 4–10; at lap 26, **3 stop calls of 20 — exactly the three cars yet to stop** (OCO, HUL, DEV); everyone else "stay out" |
| 2024 | none | lap 24 (first usable 18) | not checked |
| 2025 | **SC laps 1–4** | lap 25 (first usable 20) | laps 20–26: **13–17 stop calls of 20** — first stops, most still to come (VER 39, RUS 38); SAI called for lap 26, pitted lap 26 |
| 2026 | SC laps 31–35, 36–38 | **lap 41** | 15 calls committed live; nothing before 41 — the field ran one stint to lap 39 |

These moved on 30 September when two new refusals went in (age/race-lap
collinearity, and a trend outside the physics). 2022 went from 12 to 17 and 2025
from 20 to 25; the laps taken away were fits claiming the car gained 0.17–0.23 s
a lap from fuel burn, and 2024's lap 15 claimed **0.91 s a lap**. Read the change
as the old numbers having been optimistic rather than the model having got worse.

**The bad case is an early mass stop, not an early safety car as such.** In 2023 the field made its
one stop by lap 10, so by the time the fit was usable (lap 26) almost every car was past the only
decision the race had, and the calls were "stay out" by arithmetic — correctly, but not as a
judgement. Pooled stops also put every car on one stint and one compound, which is why the fit
refused until 26. In 2025 the safety car came on lap 1, too early to stop under, and the window for
first-stop timing stayed open past lap 26.

So, on Saturday: **note when most of the field makes its stop, and the lap of the first published
call.** If the field has already stopped and the first call comes after about lap 26, write the race
up as having had no decision window — not as the model being right.

**If the engine dies, the script relaunches it.** An engine that exits before the deadline is
restarted after 30 seconds, up to 10 times, and the log says `engine exited early with code N -
relaunching`. That is safe: the recording opens in append mode, and a new engine loads the laps
already in the ledger, so none is logged twice. Still one connection at a time — the next engine
starts only once the last has gone. Ten failures in a row ends in `giving up`; that is the case to
read `data/raw/2026-baku-race-engine.log` for. A script-level error — the kind that lost the Spanish
GP — lands in `data/raw/2026-baku-race-nohup.log` instead. One recorder at a time, always: confirm
nothing is running before starting another.

---

The procedure for a live race. Written 22 August 2026 for Zandvoort; retargeted 28 August for
Monza, with the Zandvoort numbers replaced rather than kept alongside — a runbook with two sets of
expected values is a runbook nobody checks against.

The whole point of a race day is that it is not repeatable. Everything here exists because a
mistake costs a fortnight.

---

## The schedule

**2026 Italian Grand Prix, Monza — Sunday 6 September, 14:00–16:00 Irish time.**

From the 2026 schedule: round 13, race at **15:00 CEST / 13:00 UTC**. This machine is on
Europe/Dublin, so **14:00 local** — the same clock as Zandvoort, which is a coincidence worth not
relying on. `date` printing "IST" here means *Irish* Summer Time, not India.

Confirm against F1's own `SessionInfo` on the day rather than trusting this line: the meeting key
and the `GmtOffset` of +02:00 are what settle it.

## The rehearsal that did not happen, and what it does and does not cost

**All four practice and qualifying windows passed unused** — FP1 and FP2 on Friday, FP3 and
Qualifying on Saturday. There is no rehearsal before this race.

**This is a smaller problem than the previous version of this document claimed, and the correction
matters more than the miss.** That version said the rehearsal was needed because "the live path has
still never run against a real green-flag session." That was written on 28 August and it was
already false: **the Dutch GP ran live on 23 August** — 49 calls committed to git lap by lap
between 15:00 and 16:07 while the race was running, a 13.7 MB recording, every row stamped
`source: "live"`. The claim was carried over from the note written *before* Zandvoort and never
re-checked against the repository that disproves it.

So the engine is not going into Monza cold. It has completed a live race, including a red flag on
lap 2 and a mid-race feed drop it reconnected through.

**What is genuinely unproven is narrower: the five commits since.** Nothing that changed after
23 August has run against a live feed —

| change | landed | live-tested |
|---|---|---|
| `source` stamping on every ledger row | 28 Aug | no |
| degradation refit (per-race median, disrupted races dropped) | 28 Aug | no |
| `--rehearse` mode and the `ledger_mode` split | 29 Aug | no |
| `model.prior` block on the dashboard | 28 Aug | no |

All four were exercised end to end on a 60x replay of Zandvoort on 4 September: the ledger wrote,
forecasts wrote, and `model.prior` read `1.046x / 3 races / 80 pooled`. A replay cannot test the
feed handshake or a live pace fit, but it does test every one of those four changes, because none
of them is in the feed layer.

**The residual risk, stated plainly:** the parts a replay cannot reach — F1's endpoint accepting the
connection, and the reducer folding live frames — are the parts that did *not* change since they
last worked in anger. The endpoint was re-checked on 4 September and still accepts unauthenticated
connections.

`--rehearse` stays in the tool for the next weekend that offers a practice session: it lifts the
race-only `total_laps` guard and pays for it by forcing never-commit and a `source: "rehearsal of
..."` stamp on every row. Its strategy numbers are meaningless — practice has no running order to
simulate against — so it tests the write path, not the calls.

Whenever it is next used, delete the ledger it writes afterwards — the rows are stamped and
uncommitted so they cannot contaminate the evidence, but there is no reason to keep them. Keep the
recording: a practice session of raw frames is a useful thing to replay against later.

---

## One command

```bash
nohup ./scripts/race_day.sh "2026-09-26 11:45" 2026-baku-race "2026 Azerbaijan GP" "" 210 &
```

Arguments: start time (local), recording basename, ledger session name, TLA to advise (empty = the
race leader), minutes to run, dashboard port.

210 minutes from 13:45 runs to 17:15. F1's regulations cap a race at three hours of total elapsed
time including suspensions, so a red-flagged race cannot finish later than 17:00 — the window
covers the worst case rather than the scheduled one, and over-running costs nothing but a few MB of
snapshots. Zandvoort used the whole margin: it was red-flagged on lap 2.

That is **one process holding one connection**, which records the raw frames, folds them into race
state, fits the models, publishes a call every lap, and commits each call to the ledger as it is
made. The dashboard is at <http://127.0.0.1:8000>.

The port is the optional 6th argument. The script **refuses to start if it is already in use**,
checked before the wait rather than at launch — uvicorn cannot bind a taken port, so a clash would
kill the engine the instant it finally started, hours later with the race under way. This is not
hypothetical: the `smishing-web` backend held 8000 for seventeen days until it was stopped on the
eve of the Dutch GP. If something is on 8000 again, pass a free port instead:
`... "2026 Azerbaijan GP" "" 210 8010`.

**Do not also run `scripts/record.py`.** It would open a second connection to an undocumented
endpoint from one address, which is exactly what this project's disclaimer promises not to do. The
race-day script already records.

### Why 13:45 and not earlier

`SignalRFeed`'s reconnect backoff caps at 30 s, so between sessions it reconnects every 30 s for
the same idle snapshot. That is fine for fifteen minutes and rude for three hours. `record.py` has
the gentler idle backoff, but it is not the engine. Start at 13:45: the feed goes live well before
lights out, and 15 minutes of grid procedure is ample lead-in.

### Physical checklist

- Plugged in, on wi-fi, **lid open**. macOS sleeps on lid close whatever `caffeinate` says, and a
  sleeping Mac records nothing.
- Nothing else saturating the connection.

---

## What good looks like

Check the dashboard in the first few laps:

| Field | Expected |
|---|---|
| `feed.live` | `true` |
| `total_laps` | **53** — this is the switch that turns logging on |
| `circuit` | `Monza` — the feed's `ShortName`, which needs no alias here |
| cars | 22 |
| `ledger.written` | rising by one per lap, once calls begin |
| `ledger.commits_failed` | **0** |
| `ledger.forecasts` | rising by ~22 per lap — the whole field |
| `feed.sims` | ramping from 600 toward 1500; drops if decisions run long |
| `feed.sims_floor` | **false** — true means the budget is being missed at 300 sims |

`curl -s http://127.0.0.1:8000/api/state | python -m json.tool` if the browser is inconvenient.

### Things that look broken and are not

**No call for the first ~20 laps.** The pace model refuses to publish until the design is
identified. It says so in the refusal line. On the Hungary recording the first usable call was lap
24. Refusing is the feature; a confident number from a degenerate fit is the failure.

Three of those refusal lines name a cause worth knowing on the day:

- **"tyre age and race lap are 0.9x correlated"** — the field is still on its first set, so fuel
  burn and tyre wear are the same column and cannot be separated. It clears itself as the stops
  stagger; watch `age/lap corr` on the model panel fall below 0.85. At Baku 2026 it did not clear
  until lap 41, and the engine was right to say nothing until then.
- **"s/kg of fuel, far outside the 0.030–0.040 s/kg cars actually gain"** — the trend has picked up
  something other than fuel, usually because it is being fitted on eight laps. Expect it early and
  not after about lap 30.
- **"effects are not separately identified"** — rank deficiency, normally a compound only one or two
  cars have run. Also clears itself.
- **"the track is wet — N of M cars ran lap L on intermediate or wet tyres"** — the model has no
  rates for those tyres and says nothing while they are on. Not a fault.
- **"the track is still drying"** / **"the track dried on lap N and only K clean laps have been run
  since"** — after a wet phase only the dry laps are fitted, starting six laps after the field leaves
  wet tyres. The model tag on the dashboard shows `dry from lap N` once it is speaking again. Expect
  a long wait: at Kuala Lumpur the field was on slicks from lap 9 and the fit was not stable until
  lap 31, because everyone had taken the same tyre at the same moment.

**The tyre data lags the rain.** The wet phase is read off what the field is running, and the feed
is a lap or two behind on that. If rain arrives mid-race, treat the first couple of calls after it
as coming from a dry fit.

**The simulation count moving around.** It adapts to hold a p99 ≤ 2 s budget, starting at 600 and
ramping toward 1500 when there is headroom. Falling is the controller working, not a fault. Only
`sims_floor: true` is a problem, and it means the model is too expensive rather than the machine
too slow.

**The screen is quiet between laps.** A recomputation is throttled to one per 8 seconds, and laps
at Monza are ~84 s. One call per lap is the intended rate.

**A reconnection mid-race.** Expected, not exceptional — F1's feed drops after roughly two hours
and a Grand Prix is two hours. The recording appends across it, state rebuilds from the snapshot,
and the ledger will not re-log a lap it already wrote.

---

## What to expect from the models here

All four models were refitted on 28 August through round 12, so the Dutch GP is in them. Zandvoort
moved on every one — safety-car expectation down (it ran a red flag and two VSCs, no full SC),
attrition up (five of twenty-two retired). Monza barely moved, which is the check that the refit
did not perturb circuits it had no new data for.

Monza is a **low safety-car circuit**, and the opposite of Zandvoort in almost every respect:

| | Monza | Zandvoort, for contrast |
|---|---|---|
| SC factor | **0.72x**, 21st of 25 | 1.28x, 5th |
| P(safety car over the race) | **38%** over 53 laps | 67% over 72 |
| expected SC events | 0.47 | 1.08 |
| attrition factor | 0.98x, 16th | 1.01x |
| expected retirements | 1.94 of 22 | 2.54 of 22 |
| pit loss (median / expected) | **24.24 s / 24.53 s** (89 stops) | 22.38 s / 22.67 s (126) |
| degradation factor | **0.78x** (3 usable races) | 1.05x (3) |

Lap 1 still dominates the early risk numbers: a **12.4% hazard against 0.7%** for any other lap.

**The consequence to watch, written down before the race.** Monza's pit loss is among the highest
measured — 24.24 s, 4th of 25 behind Imola, Lusail and Le Castellet — while its degradation factor
is one of the lowest at 0.78x. Both push the same way, and the break-even for a second stop on a
26-lap-old hard lands at **31 laps of remaining running: the last lap on which the engine can
recommend another stop is lap 22 of 53.** Past that it will say stay out every time, and that is
arithmetic rather than judgement.

At Monza that is roughly right — one-stop races are the norm here. It is still the same shape of
answer that made Zandvoort's late calls degenerate on 23 August, so read anything after lap 22 as
the model having no option to compare against, not as a considered call.

**Zandvoort's own factor moved from 0.50x to 1.05x on 28 August**, which is why the contrast column
above no longer matches the Dutch GP runbook. The old figure was one failed decomposition — the wet
2023 race — outvoting four sound ones. A second stop at Zandvoort used to need 47 laps of running
to pay for itself and now needs 22. The logbook entry has the detail.

Confirm both on the dashboard:

- `model.pit_loss` ≈ `{"seconds": 24.24, "expected": 24.53, "botch_rate": 0.05, "fitted": true,
  "races": 4}`
- `model.prior` ≈ `{"factor": 0.78, "fitted": true, "races": 3, "pooled_races": 80}`

If either `fitted` is false the circuit name did not resolve and that model has fallen back to a
neutral default — still sane, but it means the call is not Monza-specific and the write-up has to
say so. `races` is on the screen precisely so 0.78x from three races cannot be read as 0.78x from
ten.

**Known weaknesses, going in deliberately.**

- **No cliff term is identified on any compound.** On the filtered pool the quadratic came back
  negative for all three and was refit without it, so every long stint is modelled as a straight
  line — the optimistic direction. The fit says so in its own warnings now rather than printing
  `+0.00000` as though it were a measurement.
- The **botched-stop tail is capped at +15 s**: the stuck wheel nut that costs half a minute is not
  modelled, because in lap data it is indistinguishable from a front wing change.
- Measured pit-loss spread is an **upper bound**, not an estimate — the out-lap runs on fresh tyres
  against a worn-tyre baseline, which leaks tyre-age gain into the measurement.

---

## If it goes wrong

**Stopping it early.** `kill` the `race_day.sh` PID — it shuts the engine and caffeinate down
within a second or two. (Ctrl-C works if it is in the foreground.)

**Engine dies.** `race_day.sh` relaunches it by itself. Only if `race_day.sh` itself has gone —
nothing listed by `pgrep -fl race_day.sh` — run the engine directly; it appends to the recording
and the ledger, and skips laps already logged. The `--session` name must be identical or you get a
second ledger file.

```bash
.venv/bin/pitwall dashboard --record data/raw/2026-baku-race.txt \
    --log-predictions --session "2026 Azerbaijan GP"
```

**Commits failing** (`ledger.commits_failed` climbing). The predictions are still on disk; only the
timestamp witness is lost. Do not stop the race to debug it — note it and carry on. The script
checks branch and git identity before the wait precisely so this should not happen.

**Feed will not connect at all.** The recording is the irreplaceable artifact, the calls are not.
Fall back to `scripts/record.py`, which is the more conservative client, and reconstruct
predictions afterwards with `backtest` — clearly marked as such, never committed as live calls.

**Nothing is logging but the race is running.** Check `total_laps` is non-zero. If `LapCount` never
arrived, that is the guard doing its job on bad state, not a bug to override mid-race.

---

## Afterwards

```bash
uv run pitwall report data/raw/2026-baku-race.txt \
    --log predictions/2026-azerbaijan-gp.jsonl --out reports/2026-baku.md
```

The field forecasts written alongside the calls are picked up automatically from
`<log>-forecasts.jsonl`; they are what the reliability diagram is built from, since fifty
leader-only calls cannot be calibrated.

**Every row now carries a `source`.** A live run stamps `"live"`; a `--replay` stamps
`"replay of <file>"` and a `backtest` stamps `"backtest of <file>"`, set by the log rather than the
caller. The report prints a "Not a live ledger" banner above the scores if anything it graded was
not live. Monza should produce a report with no banner at all — if one appears, something was run
from a recording and the numbers are not what they look like.

Use `--out`, not a shell redirect: stdout carries only the summary, and the report itself is written
to the file (defaulting to `reports/race.md`). Redirecting gets you the summary under the report's
name and the real report somewhere you did not look.

Then the honest part: `git log predictions/` is the evidence. Read the calls it got wrong first,
and write the logbook entry the same evening while it is still uncomfortable.
