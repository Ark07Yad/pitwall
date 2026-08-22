# Race day

The procedure for a live race. Written 22 August 2026, the night before Zandvoort.

The whole point of a race day is that it is not repeatable. Everything here exists because a
mistake costs a fortnight.

---

## The schedule

**2026 Dutch Grand Prix, Zandvoort — Sunday 23 August, 14:00–16:00 Irish time.**

Confirmed against F1's own feed rather than a calendar page: `SessionInfo` reports meeting key 1292,
round 12, path `2026/2026-08-23_Dutch_Grand_Prix/`, with a `GmtOffset` of +02:00. Local time at the
circuit is 15:00 CEST; this machine is on Europe/Dublin, so **14:00 local, 13:00 UTC**.

Qualifying finished 16:00–17:00 CEST on Saturday and the feed already reports it `Finalised`.

---

## One command

```bash
nohup ./scripts/race_day.sh "2026-08-23 13:45" 2026-netherlands-race "2026 Dutch GP" "" 195 &
```

Arguments: start time (local), recording basename, ledger session name, TLA to advise (empty = the
race leader), minutes to run.

That is **one process holding one connection**, which records the raw frames, folds them into race
state, fits the models, publishes a call every lap, and commits each call to the ledger as it is
made. The dashboard is at <http://127.0.0.1:8000>.

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
| `total_laps` | **72** — this is the switch that turns logging on |
| `circuit` | `Zandvoort` |
| cars | 22 |
| `ledger.written` | rising by one per lap, once calls begin |
| `ledger.commits_failed` | **0** |

`curl -s http://127.0.0.1:8000/api/state | python -m json.tool` if the browser is inconvenient.

### Things that look broken and are not

**No call for the first ~20 laps.** The pace model refuses to publish until the design is
identified. It says so in the refusal line. On the Hungary recording the first usable call was lap
24. Refusing is the feature; a confident number from a degenerate fit is the failure.

**The screen is quiet between laps.** A recomputation is throttled to one per 8 seconds, and laps
at Zandvoort are ~72 s. One call per lap is the intended rate.

**A reconnection mid-race.** Expected, not exceptional — F1's feed drops after roughly two hours
and a Grand Prix is two hours. The recording appends across it, state rebuilds from the snapshot,
and the ledger will not re-log a lap it already wrote.

---

## What to expect from the models here

Zandvoort is a **high safety-car circuit**: shrunk factor **1.45x**, third of 26 behind Melbourne
and São Paulo, on four races. Over 72 laps that is a **72% chance of a safety car**, 87% of some
neutralisation. Expect the simulation's safety-car handling — field compression, and discounting a
stop taken under one — to be doing real work in every call, and expect lap 1 to dominate the early
risk numbers (a 17% hazard against ~1% for any other lap).

Attrition factor is 0.82, slightly below average.

**Pit loss is now measured, not assumed.** Zandvoort costs **22.58 s ± 1.55** under green, fitted
on 4 races and 97 stops — against the flat 20.0 s the engine used until the night before. A stop
here is ~2.6 s more expensive than the model believed, which makes every call slightly more
conservative about stopping and narrows the margins. Confirm it on the dashboard: `model.pit_loss`
should read `{"seconds": 22.58, "fitted": true, "races": 4}`. If `fitted` is false, the circuit
name did not resolve and it has fallen back to the 22.18 s field median.

**Known weakness, going in deliberately.** Compound choice still carries the single-race
degradation confounding documented in the logbook — Zandvoort is the second data point that starts
to break it. And the pit-loss spread is symmetric, where the real distribution has a long right
tail from botched stops; the plan asked for that tail and it is not modelled yet.

---

## If it goes wrong

**Engine dies.** Restart the same command; it appends to the recording and the ledger.
The `--session` name must be identical or you get a second ledger file.

```bash
.venv/bin/pitwall dashboard --record data/raw/2026-netherlands-race.txt \
    --log-predictions --session "2026 Dutch GP"
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
uv run pitwall report data/raw/2026-netherlands-race.txt \
    --log predictions/2026-dutch-gp.jsonl > reports/2026-netherlands.md
```

Then the honest part: `git log predictions/` is the evidence. Read the calls it got wrong first,
and write the logbook entry the same evening while it is still uncomfortable.
