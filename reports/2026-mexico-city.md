# 2026 Mexico City GP — Mexico City

*Generated 2026-11-02 16:48 UTC from 40 logged predictions.*

## Verdict

Did not beat the baseline of assuming nothing changes (skill worse*). Track position is sticky and the model did not add information here.

## Scores

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (top 3) | 0.0776 | 0.0000 | worse* |
| Brier (points) | 0.0009 | 0.0000 | worse* |
| Mean position error | 0.86 | 0.65 | — |

The baseline forecasts that every car finishes where it currently runs. In Formula 1
that is a strong benchmark, not a straw man — track position is sticky. Negative skill
means the model added nothing over assuming the order holds.

## Calibration

| confidence band | n | said | happened |
|---|---|---|---|
| 40%–60% | 13 | 52.4% | 100.0% |
| 60%–80% | 1 | 74.3% | 100.0% |
| 80%–100% | 26 | 96.6% | 100.0% |

A well-calibrated model matches the last two columns. Consistently saying more
than happens is overconfidence, and it is a separate failure from being wrong.

## Every call

| lap | driver | call | expected | actual | horizon |
|---|---|---|---|---|---|
| 32 | ANT | pit lap 32 on HAR | P4.68 | P3 | lap 42 |
| 33 | ANT | pit lap 33 on MED | P4.55 | P3 | lap 43 |
| 34 | ANT | pit lap 34 on MED | P4.70 | P3 | lap 44 |
| 35 | ANT | pit lap 35 on MED | P4.02 | P3 | lap 45 |
| 36 | ANT | pit lap 36 on MED | P4.09 | P3 | lap 46 |
| 37 | ANT | pit lap 37 on HAR | P4.45 | P3 | lap 47 |
| 38 | ANT | pit lap 38 on MED | P4.47 | P3 | lap 48 |
| 39 | ANT | pit lap 39 on MED | P4.34 | P3 | lap 49 |
| 40 | ANT | pit lap 40 on MED | P4.40 | P3 | lap 50 |
| 41 | ANT | pit lap 41 on MED | P3.90 | P3 | lap 51 |
| 42 | ANT | pit lap 42 on MED | P3.79 | P3 | lap 52 |
| 43 | ANT | pit lap 43 on MED | P3.90 | P3 | lap 53 |
| 44 | ANT | pit lap 44 on MED | P3.66 | P3 | lap 54 |
| 45 | VER | stay out on SOF | P2.36 | P1 | lap 55 |
| 46 | VER | stay out on SOF | P3.12 | P1 | lap 56 |
| 47 | VER | stay out on SOF | P2.01 | P1 | lap 57 |
| 48 | VER | stay out on SOF | P2.19 | P1 | lap 58 |
| 49 | VER | stay out on SOF | P2.15 | P1 | lap 59 |
| 50 | VER | stay out on SOF | P1.95 | P1 | lap 60 |
| 51 | VER | stay out on SOF | P1.91 | P1 | lap 61 |
| 52 | VER | stay out on SOF | P1.82 | P1 | lap 62 |
| 53 | VER | stay out on SOF | P1.76 | P1 | lap 63 |
| 54 | VER | stay out on SOF | P1.67 | P1 | lap 64 |
| 55 | VER | stay out on SOF | P1.65 | P1 | lap 65 |
| 56 | VER | stay out on SOF | P1.61 | P1 | lap 66 |
| 57 | VER | stay out on SOF | P1.57 | P1 | lap 67 |
| 58 | VER | stay out on SOF | P1.52 | P1 | lap 68 |
| 59 | VER | stay out on SOF | P1.48 | P1 | lap 69 |
| 60 | VER | stay out on SOF | P1.27 | P1 | lap 70 |
| 61 | VER | stay out on SOF | P1.56 | P1 | lap 71 |
| 62 | VER | stay out on SOF | P1.55 | P1 | lap 71 |
| 63 | VER | stay out on SOF | P1.57 | P1 | lap 71 |
| 64 | VER | stay out on SOF | P1.47 | P1 | lap 71 |
| 65 | VER | stay out on SOF | P1.44 | P1 | lap 71 |
| 66 | VER | stay out on SOF | P1.40 | P1 | lap 71 |
| 67 | VER | stay out on SOF | P1.40 | P1 | lap 71 |
| 68 | VER | stay out on SOF | P1.33 | P1 | lap 71 |
| 69 | VER | stay out on SOF | P1.26 | P1 | lap 71 |
| 70 | VER | stay out on SOF | P1.21 | P1 | lap 71 |
| 71 | VER | stay out on SOF | P1.17 | P1 | lap 71 |

## Feed

```
Pipeline latency over 40 decisions

  fold     n=40    p50     0.04ms  p95     0.08ms  p99     0.08ms  max     0.08ms
  decide   n=40    p50   793.05ms  p95  1032.29ms  p99  1164.38ms  max  1164.38ms
  total    n=40    p50   793.13ms  p95  1032.34ms  p99  1164.42ms  max  1164.42ms
           budget p99 <= 2000ms: within (0 of 40 samples over)

  packet arrival -> recommendation, distribution:
        100-250 ms     3   7.5%  #####
        250-500 ms     8  20.0%  ##############
       500-1000 ms    23  57.5%  ########################################
      1000-2000 ms     6  15.0%  ##########

  feed lag (F1's pipeline + network, not ours): mean 2.95s  p99 3.40s
```

## Field forecast

Alongside each pit call the engine forecasts **every car**, which costs one simulation rather than one per car. That is what makes a calibration curve possible: 880 claims across 22 cars, against 40 recommendations concentrated on the car being advised.

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (win) | 0.0144 | 0.0295 | +51.2% |
| Brier (top 3) | 0.0267 | 0.0455 | +41.2% |
| Brier (points) | 0.0709 | 0.1068 | +33.7% |
| Mean position error | 1.69 | 1.50 | — |

### Reliability

When it says 70%, does it happen seven times in ten?

| confidence band | n | said | happened |
|---|---|---|---|
| 0%–20% | 720 | 0.9% | 0.0% |
| 20%–40% | 29 | 29.6% | 31.0% |
| 40%–60% | 13 | 54.2% | 100.0% |
| 60%–80% | 49 | 69.6% | 63.3% |
| 80%–100% | 69 | 92.4% | 97.1% |

Claimed and observed track each other across the range.

---

Every prediction above was committed to this repository before the lap it refers to.
Commit timestamps are the evidence; `git log predictions/` shows them.