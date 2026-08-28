# 2026 Dutch GP — Zandvoort

*Generated 2026-08-28 17:39 UTC from 49 logged predictions.*

> **Not a live ledger.**
> Field forecasts: replay of 2026-netherlands-race.txt.
> Rows made against a recording that already contains the result are not evidence
> that the call preceded the outcome, whatever they score.

## Verdict

Did not beat the baseline of assuming nothing changes (skill -167.4%). Track position is sticky and the model did not add information here.

## Scores

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (top 3) | 0.3820 | 0.1429 | -167.4% |
| Brier (points) | 0.0010 | 0.0000 | worse* |
| Mean position error | 2.50 | 0.76 | — |

The baseline forecasts that every car finishes where it currently runs. In Formula 1
that is a strong benchmark, not a straw man — track position is sticky. Negative skill
means the model added nothing over assuming the order holds.

## Calibration

| confidence band | n | said | happened |
|---|---|---|---|
| 0%–20% | 16 | 10.2% | 87.5% |
| 20%–40% | 7 | 22.3% | 42.9% |
| 40%–60% | 20 | 52.6% | 95.0% |
| 60%–80% | 6 | 69.1% | 100.0% |

A well-calibrated model matches the last two columns. Consistently saying more
than happens is overconfidence, and it is a separate failure from being wrong.

## Every call

| lap | driver | call | expected | actual | horizon |
|---|---|---|---|---|---|
| 21 | ANT | pit lap 21 on HAR | P3.96 | P2 | lap 31 |
| 25 | HAM | pit lap 25 on HAR | P4.68 | P4 | lap 35 |
| 26 | ANT | pit lap 36 on HAR | P3.23 | P2 | lap 36 |
| 27 | ANT | pit lap 27 on HAR | P4.16 | P2 | lap 37 |
| 28 | ANT | pit lap 28 on HAR | P4.23 | P2 | lap 38 |
| 29 | ANT | pit lap 39 on SOF | P4.05 | P2 | lap 39 |
| 30 | ANT | pit lap 30 on HAR | P4.18 | P2 | lap 40 |
| 31 | ANT | pit lap 41 on HAR | P4.19 | P2 | lap 41 |
| 32 | ANT | pit lap 35 on HAR | P4.17 | P2 | lap 42 |
| 33 | ANT | pit lap 39 on HAR | P4.24 | P2 | lap 43 |
| 34 | ANT | pit lap 34 on MED | P4.37 | P2 | lap 44 |
| 35 | ANT | pit lap 35 on MED | P4.02 | P2 | lap 45 |
| 36 | ANT | pit lap 36 on MED | P3.99 | P2 | lap 46 |
| 37 | ANT | pit lap 40 on MED | P3.92 | P2 | lap 47 |
| 38 | ANT | pit lap 38 on MED | P3.96 | P2 | lap 48 |
| 39 | ANT | pit lap 39 on HAR | P4.05 | P2 | lap 49 |
| 40 | ANT | pit lap 40 on HAR | P3.95 | P2 | lap 50 |
| 41 | NOR | pit lap 41 on HAR | P4.01 | P1 | lap 51 |
| 42 | NOR | pit lap 45 on HAR | P3.93 | P1 | lap 52 |
| 43 | NOR | pit lap 43 on HAR | P3.77 | P1 | lap 53 |
| 44 | NOR | pit lap 44 on HAR | P3.55 | P1 | lap 54 |
| 45 | NOR | pit lap 45 on HAR | P3.03 | P1 | lap 55 |
| 46 | NOR | pit lap 46 on HAR | P3.14 | P1 | lap 56 |
| 47 | NOR | pit lap 47 on HAR | P3.16 | P1 | lap 57 |
| 48 | NOR | pit lap 48 on HAR | P3.62 | P1 | lap 58 |
| 49 | HAM | pit lap 49 on HAR | P4.69 | P4 | lap 59 |
| 50 | HAM | pit lap 50 on HAR | P4.61 | P4 | lap 60 |
| 51 | HAM | pit lap 51 on MED | P4.58 | P4 | lap 61 |
| 52 | HAM | pit lap 52 on MED | P4.56 | P4 | lap 62 |
| 53 | HAM | pit lap 53 on MED | P4.61 | P4 | lap 63 |
| 54 | HAM | pit lap 54 on MED | P4.67 | P4 | lap 64 |
| 55 | NOR | pit lap 55 on MED | P4.57 | P1 | lap 65 |
| 56 | NOR | pit lap 56 on MED | P4.48 | P1 | lap 66 |
| 57 | NOR | pit lap 57 on MED | P3.71 | P1 | lap 67 |
| 58 | NOR | pit lap 58 on MED | P4.27 | P1 | lap 68 |
| 59 | NOR | pit lap 59 on MED | P4.56 | P1 | lap 69 |
| 60 | NOR | pit lap 60 on MED | P4.52 | P1 | lap 70 |
| 61 | NOR | pit lap 61 on MED | P4.51 | P1 | lap 71 |
| 62 | NOR | pit lap 62 on MED | P4.48 | P1 | lap 72 |
| 63 | NOR | pit lap 63 on MED | P4.56 | P1 | lap 72 |
| 64 | NOR | pit lap 64 on MED | P4.65 | P1 | lap 72 |
| 65 | NOR | pit lap 65 on MED | P4.69 | P1 | lap 72 |
| 66 | NOR | pit lap 66 on MED | P4.81 | P1 | lap 72 |
| 67 | NOR | pit lap 67 on MED | P4.88 | P1 | lap 72 |
| 68 | NOR | pit lap 68 on MED | P4.92 | P1 | lap 72 |
| 69 | NOR | pit lap 69 on MED | P4.97 | P1 | lap 72 |
| 70 | NOR | pit lap 70 on MED | P5.00 | P1 | lap 72 |
| 71 | NOR | pit lap 71 on MED | P4.90 | P1 | lap 72 |
| 72 | NOR | pit lap 72 on SOF | P4.95 | P1 | lap 72 |

## Feed

```
Pipeline latency over 49 decisions

  fold     n=49    p50     0.01ms  p95     0.01ms  p99     0.02ms  max     0.02ms
  decide   n=49    p50  1157.98ms  p95  1305.57ms  p99  1504.66ms  max  1504.66ms
  total    n=49    p50  1157.99ms  p95  1305.57ms  p99  1504.67ms  max  1504.67ms
           budget p99 <= 2000ms: within (0 of 49 samples over)

  packet arrival -> recommendation, distribution:
         50-100 ms     1   2.0%  #
        100-250 ms     3   6.1%  ####
        250-500 ms     6  12.2%  ########
       500-1000 ms     7  14.3%  #########
      1000-2000 ms    32  65.3%  ########################################
```

## Field forecast

Alongside each pit call the engine forecasts **every car**, which costs one simulation rather than one per car. That is what makes a calibration curve possible: 1,078 claims across 22 cars, against 49 recommendations concentrated on the car being advised.

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (win) | 0.0210 | 0.0427 | +50.8% |
| Brier (top 3) | 0.0412 | 0.0390 | -5.6% |
| Brier (points) | 0.0554 | 0.0705 | +21.5% |
| Mean position error | 1.53 | 1.13 | — |

### Reliability

When it says 70%, does it happen seven times in ten?

| confidence band | n | said | happened |
|---|---|---|---|
| 0%–20% | 872 | 1.0% | 1.8% |
| 20%–40% | 51 | 29.0% | 33.3% |
| 40%–60% | 24 | 48.8% | 16.7% |
| 60%–80% | 47 | 73.0% | 59.6% |
| 80%–100% | 84 | 91.8% | 97.6% |

The model is **overconfident** in the 40%–60%, 60%–80% band(s). Bands with fewer than fifteen forecasts are not judged here; they move too much to read.

---

Every prediction above was committed to this repository before the lap it refers to.
Commit timestamps are the evidence; `git log predictions/` shows them.