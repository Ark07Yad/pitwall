# 2026 Hungarian GP — Hungaroring

*Generated 2026-07-29 07:52 UTC from 35 logged predictions.*

## Verdict

Better than the baseline on Brier skill (+33.2%) but not on position error (3.46 vs 3.17). A partial result.

## Scores

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (top 3) | 0.2481 | 0.3714 | +33.2% |
| Brier (points) | 0.1366 | 0.1429 | +4.4% |
| Mean position error | 3.46 | 3.17 | — |

The baseline forecasts that every car finishes where it currently runs. In Formula 1
that is a strong benchmark, not a straw man — track position is sticky. Negative skill
means the model added nothing over assuming the order holds.

## Calibration

| confidence band | n | said | happened |
|---|---|---|---|
| 0%–20% | 13 | 3.3% | 30.8% |
| 20%–40% | 8 | 30.1% | 25.0% |
| 40%–60% | 6 | 48.3% | 33.3% |
| 60%–80% | 6 | 67.6% | 100.0% |
| 80%–100% | 2 | 100.0% | 50.0% |

A well-calibrated model matches the last two columns. Consistently saying more
than happens is overconfidence, and it is a separate failure from being wrong.

## Every call

| lap | driver | call | expected | actual | horizon |
|---|---|---|---|---|---|
| 16 | ANT | pit lap 19 on MED | P1.00 | P3 | lap 26 |
| 16 | HAM | pit lap 26 on MED | P5.95 | P5 | lap 26 |
| 16 | LEC | pit lap 16 on MED | P2.00 | P4 | lap 26 |
| 16 | NOR | pit lap 16 on HAR | P8.04 | P1 | lap 26 |
| 16 | PIA | pit lap 16 on SOF | P6.48 | P20 | lap 26 |
| 16 | RUS | pit lap 16 on SOF | P9.74 | P7 | lap 26 |
| 16 | VER | pit lap 16 on SOF | P9.25 | P2 | lap 26 |
| 24 | ANT | pit lap 24 on HAR | P4.08 | P3 | lap 34 |
| 24 | HAM | pit lap 27 on MED | P4.93 | P5 | lap 34 |
| 24 | LEC | pit lap 27 on HAR | P4.47 | P4 | lap 34 |
| 24 | NOR | pit lap 34 on MED | P2.60 | P1 | lap 34 |
| 24 | PIA | pit lap 24 on HAR | P17.62 | P20 | lap 34 |
| 24 | RUS | pit lap 24 on HAR | P5.51 | P7 | lap 34 |
| 24 | VER | pit lap 27 on HAR | P3.57 | P2 | lap 34 |
| 32 | ANT | pit lap 32 on HAR | P3.25 | P3 | lap 42 |
| 32 | HAM | pit lap 38 on SOF | P4.20 | P5 | lap 42 |
| 32 | LEC | pit lap 32 on HAR | P3.33 | P4 | lap 42 |
| 32 | NOR | pit lap 32 on HAR | P2.93 | P1 | lap 42 |
| 32 | PIA | pit lap 38 on SOF | P15.56 | P20 | lap 42 |
| 32 | RUS | pit lap 38 on SOF | P5.25 | P7 | lap 42 |
| 32 | VER | pit lap 32 on HAR | P2.68 | P2 | lap 42 |
| 40 | ANT | pit lap 40 on SOF | P2.87 | P3 | lap 50 |
| 40 | HAM | pit lap 43 on SOF | P4.20 | P5 | lap 50 |
| 40 | LEC | pit lap 50 on SOF | P4.81 | P4 | lap 50 |
| 40 | NOR | pit lap 40 on SOF | P3.66 | P1 | lap 50 |
| 40 | PIA | pit lap 43 on SOF | P3.94 | P20 | lap 50 |
| 40 | RUS | pit lap 40 on SOF | P5.87 | P7 | lap 50 |
| 40 | VER | pit lap 46 on SOF | P14.35 | P2 | lap 50 |
| 48 | ANT | pit lap 48 on SOF | P3.44 | P3 | lap 58 |
| 48 | HAM | pit lap 48 on HAR | P4.12 | P5 | lap 58 |
| 48 | LEC | pit lap 48 on MED | P4.91 | P4 | lap 58 |
| 48 | NOR | pit lap 54 on MED | P12.07 | P1 | lap 58 |
| 48 | PIA | pit lap 48 on HAR | P4.05 | P20 | lap 58 |
| 48 | RUS | pit lap 48 on SOF | P6.29 | P7 | lap 58 |
| 48 | VER | pit lap 48 on MED | P4.52 | P2 | lap 58 |

---

Every prediction above was committed to this repository before the lap it refers to.
Commit timestamps are the evidence; `git log predictions/` shows them.