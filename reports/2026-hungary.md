# 2026 Hungarian GP — Hungaroring

*Generated 2026-07-29 08:01 UTC from 28 logged predictions.*

## Verdict

Better than the baseline on Brier skill (+3.7%) but not on position error (3.53 vs 3.50). A partial result.

## Scores

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (top 3) | 0.2063 | 0.2143 | +3.7% |
| Brier (points) | 0.1412 | 0.1429 | +1.1% |
| Mean position error | 3.53 | 3.50 | — |

The baseline forecasts that every car finishes where it currently runs. In Formula 1
that is a strong benchmark, not a straw man — track position is sticky. Negative skill
means the model added nothing over assuming the order holds.

## Calibration

| confidence band | n | said | happened |
|---|---|---|---|
| 0%–20% | 13 | 8.4% | 15.4% |
| 20%–40% | 7 | 30.6% | 57.1% |
| 40%–60% | 5 | 43.9% | 80.0% |
| 60%–80% | 2 | 68.0% | 50.0% |
| 80%–100% | 1 | 84.1% | 100.0% |

A well-calibrated model matches the last two columns. Consistently saying more
than happens is overconfidence, and it is a separate failure from being wrong.

## Every call

| lap | driver | call | expected | actual | horizon |
|---|---|---|---|---|---|
| 24 | ANT | pit lap 27 on HAR | P5.01 | P3 | lap 34 |
| 24 | HAM | pit lap 30 on HAR | P5.87 | P5 | lap 34 |
| 24 | LEC | pit lap 24 on HAR | P5.49 | P4 | lap 34 |
| 24 | NOR | pit lap 34 on MED | P3.30 | P1 | lap 34 |
| 24 | PIA | pit lap 34 on HAR | P3.07 | P20 | lap 34 |
| 24 | RUS | pit lap 24 on HAR | P6.54 | P7 | lap 34 |
| 24 | VER | pit lap 30 on HAR | P4.44 | P2 | lap 34 |
| 32 | ANT | pit lap 32 on HAR | P4.22 | P3 | lap 42 |
| 32 | HAM | pit lap 42 on SOF | P5.38 | P5 | lap 42 |
| 32 | LEC | pit lap 32 on HAR | P4.42 | P4 | lap 42 |
| 32 | NOR | pit lap 32 on HAR | P3.73 | P1 | lap 42 |
| 32 | PIA | pit lap 32 on HAR | P3.78 | P20 | lap 42 |
| 32 | RUS | pit lap 38 on SOF | P6.43 | P7 | lap 42 |
| 32 | VER | pit lap 32 on HAR | P3.89 | P2 | lap 42 |
| 40 | ANT | pit lap 40 on HAR | P4.45 | P3 | lap 50 |
| 40 | HAM | pit lap 40 on HAR | P5.10 | P5 | lap 50 |
| 40 | LEC | pit lap 40 on SOF | P5.87 | P4 | lap 50 |
| 40 | NOR | pit lap 40 on HAR | P5.19 | P1 | lap 50 |
| 40 | PIA | pit lap 40 on HAR | P4.71 | P20 | lap 50 |
| 40 | RUS | pit lap 40 on HAR | P6.58 | P7 | lap 50 |
| 40 | VER | pit lap 40 on HAR | P4.10 | P2 | lap 50 |
| 48 | ANT | pit lap 48 on MED | P4.34 | P3 | lap 58 |
| 48 | HAM | pit lap 48 on HAR | P5.09 | P5 | lap 58 |
| 48 | LEC | pit lap 48 on MED | P6.02 | P4 | lap 58 |
| 48 | NOR | pit lap 58 on MED | P1.95 | P1 | lap 58 |
| 48 | PIA | pit lap 48 on HAR | P5.09 | P20 | lap 58 |
| 48 | RUS | pit lap 48 on SOF | P7.37 | P7 | lap 58 |
| 48 | VER | pit lap 48 on MED | P5.69 | P2 | lap 58 |

---

Every prediction above was committed to this repository before the lap it refers to.
Commit timestamps are the evidence; `git log predictions/` shows them.