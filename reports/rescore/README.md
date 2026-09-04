# Post-hoc re-scores

**Nothing here is a prediction.** These files were produced *after* the 2026 Dutch GP, against a
recording that already contains the result, and are kept separate from `predictions/` for that
reason. The live ledger — 49 calls, each committed to git before the lap it referred to — stands
exactly as it was made, including the ones it got wrong. A ledger you rewrite when it embarrasses
you is not evidence of anything.

Each file re-runs the same 49 calls matched lap-for-lap and car-for-car against the live ledger, so
only one variable changes at a time.

| file | change | Brier (top 3) | skill | on unobserved tyre ages |
|---|---|---|---|---|
| *(live ledger)* | as raced | 0.3820 | −167.4% | 31 / 49 |
| `stayout-only.jsonl` | a real "stay out" option | 0.0585 | +59.1% | 31 / 49 |
| `stayout-plus-pooled-prior.jsonl` | + degradation pooled over 95 races | 0.0837 | +41.4% | **0 / 49** |
| `pooled-prior-v2.jsonl` | + degradation refit per race, disrupted races dropped | 0.0607 | +58.4% | 0 / 48 |

Produced by `scripts/rescore.py`, which is new. The first two rows were made by hand, which is why
they could not be regenerated when the degradation model changed on 28 August — the row above had
to be built from scratch rather than re-run. It is a command now.

**The most useful thing in the last row is not the skill number.** Matched lap-for-lap against the
row above it — same 48 laps, same cars, one model changed — the two priors produce **zero different
decisions**. Not "similar": identical, 48 of 48, still 47 stay-outs. The 28 August refit moved
Zandvoort's degradation factor from 0.505x to 1.05x and its break-even for a second stop from 47
laps to 22, and none of that reached a single call on this race.

The Brier gain is real but it is a *forecast* improvement, not a decision one: the same calls,
carrying better-calibrated probabilities about where the car ends up. Mean position error moves the
other way, 0.50 to 0.58.

So this race does not validate the refit. It corrected a demonstrable modelling error — a soft tyre
fitted as improving with age, and one race in five contributing a negative scale — and Zandvoort
happens to sit in a regime where staying out wins under both versions. **Monza is the first race
that can actually test it.**

The pooled prior scores *worse* on this race and is still the better model: its value is the last
column, not the third. Forty-nine calls from one afternoon, all advising a leader who won
comfortably, cannot separate +59% from +41% — but they can show that two thirds of the calls used
to rest on tyre ages nobody had ever run, and now none do.
