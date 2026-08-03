# 2026 Hungarian GP — Hungaroring

*Generated 2026-08-03 11:52 UTC from 28 logged predictions.*

## Verdict

Better than the baseline on Brier skill (+8.5%) but not on position error (3.69 vs 3.50). A partial result.

## Scores

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (top 3) | 0.1961 | 0.2143 | +8.5% |
| Brier (points) | 0.1327 | 0.1429 | +7.1% |
| Mean position error | 3.69 | 3.50 | — |

The baseline forecasts that every car finishes where it currently runs. In Formula 1
that is a strong benchmark, not a straw man — track position is sticky. Negative skill
means the model added nothing over assuming the order holds.

## Calibration

| confidence band | n | said | happened |
|---|---|---|---|
| 0%–20% | 10 | 11.2% | 10.0% |
| 20%–40% | 9 | 31.5% | 55.6% |
| 40%–60% | 6 | 49.2% | 66.7% |
| 60%–80% | 2 | 65.9% | 50.0% |
| 80%–100% | 1 | 82.9% | 100.0% |

A well-calibrated model matches the last two columns. Consistently saying more
than happens is overconfidence, and it is a separate failure from being wrong.

## Every call

| lap | driver | call | expected | actual | horizon |
|---|---|---|---|---|---|
| 24 | ANT | pit lap 27 on HAR | P5.63 | P3 | lap 34 |
| 24 | HAM | pit lap 24 on SOF | P6.49 | P5 | lap 34 |
| 24 | LEC | pit lap 34 on HAR | P6.19 | P4 | lap 34 |
| 24 | NOR | pit lap 30 on MED | P4.15 | P1 | lap 34 |
| 24 | PIA | pit lap 34 on MED | P4.12 | P20 | lap 34 |
| 24 | RUS | pit lap 24 on MED | P7.03 | P7 | lap 34 |
| 24 | VER | pit lap 27 on MED | P5.22 | P2 | lap 34 |
| 32 | ANT | pit lap 32 on HAR | P4.42 | P3 | lap 42 |
| 32 | HAM | pit lap 42 on SOF | P5.26 | P5 | lap 42 |
| 32 | LEC | pit lap 32 on HAR | P4.85 | P4 | lap 42 |
| 32 | NOR | pit lap 32 on HAR | P4.15 | P1 | lap 42 |
| 32 | PIA | pit lap 32 on HAR | P4.04 | P20 | lap 42 |
| 32 | RUS | pit lap 38 on SOF | P6.52 | P7 | lap 42 |
| 32 | VER | pit lap 32 on HAR | P4.09 | P2 | lap 42 |
| 40 | ANT | pit lap 40 on HAR | P4.68 | P3 | lap 50 |
| 40 | HAM | pit lap 40 on HAR | P5.23 | P5 | lap 50 |
| 40 | LEC | pit lap 40 on SOF | P6.08 | P4 | lap 50 |
| 40 | NOR | pit lap 40 on HAR | P5.29 | P1 | lap 50 |
| 40 | PIA | pit lap 40 on HAR | P4.93 | P20 | lap 50 |
| 40 | RUS | pit lap 40 on SOF | P6.68 | P7 | lap 50 |
| 40 | VER | pit lap 40 on SOF | P4.65 | P2 | lap 50 |
| 48 | ANT | pit lap 48 on MED | P4.70 | P3 | lap 58 |
| 48 | HAM | pit lap 48 on MED | P5.21 | P5 | lap 58 |
| 48 | LEC | pit lap 48 on MED | P6.13 | P4 | lap 58 |
| 48 | NOR | pit lap 58 on HAR | P2.30 | P1 | lap 58 |
| 48 | PIA | pit lap 48 on HAR | P5.22 | P20 | lap 58 |
| 48 | RUS | pit lap 48 on HAR | P7.52 | P7 | lap 58 |
| 48 | VER | pit lap 48 on MED | P5.69 | P2 | lap 58 |

---

Every prediction above was committed to this repository before the lap it refers to.
Commit timestamps are the evidence; `git log predictions/` shows them.