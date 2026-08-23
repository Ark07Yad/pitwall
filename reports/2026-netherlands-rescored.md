# 2026 Dutch GP rescored — Zandvoort

*Generated 2026-08-23 19:01 UTC from 49 logged predictions.*

## Verdict

Beat the hold-position baseline on both skill (+59.1%) and mean position error (0.48 vs 0.76).

## Scores

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (top 3) | 0.0585 | 0.1429 | +59.1% |
| Brier (points) | 0.0008 | 0.0000 | worse* |
| Mean position error | 0.48 | 0.76 | — |

The baseline forecasts that every car finishes where it currently runs. In Formula 1
that is a strong benchmark, not a straw man — track position is sticky. Negative skill
means the model added nothing over assuming the order holds.

## Calibration

| confidence band | n | said | happened |
|---|---|---|---|
| 40%–60% | 1 | 48.9% | 0.0% |
| 60%–80% | 7 | 63.8% | 14.3% |
| 80%–100% | 41 | 95.6% | 100.0% |

A well-calibrated model matches the last two columns. Consistently saying more
than happens is overconfidence, and it is a separate failure from being wrong.

## Every call

| lap | driver | call | expected | actual | horizon |
|---|---|---|---|---|---|
| 21 | ANT | pit lap 21 on HAR | P3.96 | P2 | lap 31 |
| 25 | HAM | pit lap 25 on HAR | P4.68 | P4 | lap 35 |
| 26 | ANT | stay out on HAR | P2.36 | P2 | lap 36 |
| 27 | ANT | stay out on HAR | P2.60 | P2 | lap 37 |
| 28 | ANT | stay out on HAR | P2.27 | P2 | lap 38 |
| 29 | ANT | stay out on HAR | P2.07 | P2 | lap 39 |
| 30 | ANT | stay out on HAR | P2.33 | P2 | lap 40 |
| 31 | ANT | stay out on HAR | P2.36 | P2 | lap 41 |
| 32 | ANT | stay out on HAR | P2.28 | P2 | lap 42 |
| 33 | ANT | stay out on HAR | P2.39 | P2 | lap 43 |
| 34 | ANT | stay out on HAR | P2.51 | P2 | lap 44 |
| 35 | ANT | stay out on HAR | P2.41 | P2 | lap 45 |
| 36 | ANT | stay out on HAR | P2.63 | P2 | lap 46 |
| 37 | ANT | stay out on HAR | P2.18 | P2 | lap 47 |
| 38 | ANT | stay out on HAR | P1.95 | P2 | lap 48 |
| 39 | ANT | stay out on HAR | P2.05 | P2 | lap 49 |
| 40 | ANT | stay out on HAR | P1.99 | P2 | lap 50 |
| 41 | NOR | stay out on HAR | P2.10 | P1 | lap 51 |
| 42 | NOR | stay out on HAR | P2.50 | P1 | lap 52 |
| 43 | NOR | stay out on HAR | P2.16 | P1 | lap 53 |
| 44 | NOR | stay out on HAR | P2.09 | P1 | lap 54 |
| 45 | NOR | stay out on HAR | P2.26 | P1 | lap 55 |
| 46 | NOR | stay out on HAR | P2.34 | P1 | lap 56 |
| 47 | NOR | stay out on HAR | P2.26 | P1 | lap 57 |
| 48 | NOR | stay out on HAR | P2.30 | P1 | lap 58 |
| 49 | HAM | stay out on HAR | P3.43 | P4 | lap 59 |
| 50 | HAM | stay out on HAR | P3.50 | P4 | lap 60 |
| 51 | HAM | stay out on HAR | P3.44 | P4 | lap 61 |
| 52 | HAM | stay out on HAR | P3.36 | P4 | lap 62 |
| 53 | HAM | stay out on HAR | P3.29 | P4 | lap 63 |
| 54 | HAM | stay out on HAR | P3.22 | P4 | lap 64 |
| 55 | NOR | stay out on HAR | P1.24 | P1 | lap 65 |
| 56 | NOR | stay out on HAR | P1.28 | P1 | lap 66 |
| 57 | NOR | stay out on HAR | P1.29 | P1 | lap 67 |
| 58 | NOR | stay out on HAR | P1.23 | P1 | lap 68 |
| 59 | NOR | stay out on HAR | P1.21 | P1 | lap 69 |
| 60 | NOR | stay out on HAR | P1.17 | P1 | lap 70 |
| 61 | NOR | stay out on HAR | P1.16 | P1 | lap 71 |
| 62 | NOR | stay out on HAR | P1.15 | P1 | lap 72 |
| 63 | NOR | stay out on HAR | P1.10 | P1 | lap 72 |
| 64 | NOR | stay out on HAR | P1.10 | P1 | lap 72 |
| 65 | NOR | stay out on HAR | P1.12 | P1 | lap 72 |
| 66 | NOR | stay out on HAR | P1.12 | P1 | lap 72 |
| 67 | NOR | stay out on HAR | P1.10 | P1 | lap 72 |
| 68 | NOR | stay out on HAR | P1.08 | P1 | lap 72 |
| 69 | NOR | stay out on HAR | P1.07 | P1 | lap 72 |
| 70 | NOR | stay out on HAR | P1.05 | P1 | lap 72 |
| 71 | NOR | stay out on HAR | P1.07 | P1 | lap 72 |
| 72 | NOR | stay out on HAR | P1.03 | P1 | lap 72 |

---

Every prediction above was committed to this repository before the lap it refers to.
Commit timestamps are the evidence; `git log predictions/` shows them.