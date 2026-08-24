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

The pooled prior scores *worse* on this race and is still the better model: its value is the last
column, not the third. Forty-nine calls from one afternoon, all advising a leader who won
comfortably, cannot separate +59% from +41% — but they can show that two thirds of the calls used
to rest on tyre ages nobody had ever run, and now none do.
