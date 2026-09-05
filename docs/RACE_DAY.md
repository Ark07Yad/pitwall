# Race day

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
nohup ./scripts/race_day.sh "2026-09-06 13:45" 2026-italy-race "2026 Italian GP" "" 210 &
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
`... "2026 Italian GP" "" 210 8010`.

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

**Engine dies.** Restart the same command; it appends to the recording and the ledger.
The `--session` name must be identical or you get a second ledger file.

```bash
.venv/bin/pitwall dashboard --record data/raw/2026-italy-race.txt \
    --log-predictions --session "2026 Italian GP"
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
uv run pitwall report data/raw/2026-italy-race.txt \
    --log predictions/2026-italian-gp.jsonl --out reports/2026-italy.md
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
