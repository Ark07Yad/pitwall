# 2026 Spanish GP backtest — Madring

*Generated 2026-09-13 17:47 UTC from 176 logged predictions.*

> **Not a live ledger.**
> No circuit history: attrition,degradation,pit_loss,safety_car used the field average.
> Calls: backtest of 2026-r14-archive.txt.
> Rows made against a recording that already contains the result are not evidence
> that the call preceded the outcome, whatever they score.

## Verdict

Beat the hold-position baseline on both skill (+73.4%) and mean position error (1.02 vs 1.16).

## Scores

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (top 3) | 0.0182 | 0.0682 | +73.4% |
| Brier (points) | 0.0614 | 0.1591 | +61.4% |
| Mean position error | 1.02 | 1.16 | — |

The baseline forecasts that every car finishes where it currently runs. In Formula 1
that is a strong benchmark, not a straw man — track position is sticky. Negative skill
means the model added nothing over assuming the order holds.

## Calibration

| confidence band | n | said | happened |
|---|---|---|---|
| 0%–20% | 145 | 0.6% | 0.0% |
| 20%–40% | 6 | 25.9% | 0.0% |
| 40%–60% | 6 | 52.4% | 100.0% |
| 60%–80% | 7 | 64.1% | 85.7% |
| 80%–100% | 12 | 94.4% | 100.0% |

A well-calibrated model matches the last two columns. Consistently saying more
than happens is overconfidence, and it is a separate failure from being wrong.

## Every call

| lap | driver | call | expected | actual | horizon |
|---|---|---|---|---|---|
| 20 | ALB | stay out on HAR | P15.59 | P15 | lap 30 |
| 20 | ALO | stay out on SOF | P17.68 | P17 | lap 30 |
| 20 | ANT | stay out on HAR | P2.51 | P1 | lap 30 |
| 20 | BEA | pit lap 20 on MED | P11.05 | P16 | lap 30 |
| 20 | BOR | pit lap 23 on SOF | P11.87 | P13 | lap 30 |
| 20 | BOT | pit lap 30 on SOF | P20.32 | P18 | lap 30 |
| 20 | COL | stay out on HAR | P10.54 | P7 | lap 30 |
| 20 | GAS | pit lap 20 on SOF | P11.09 | P12 | lap 30 |
| 20 | HAM | stay out on SOF | P18.94 | P22 | lap 30 |
| 20 | HUL | stay out on HAR | P11.20 | P10 | lap 30 |
| 20 | LAW | pit lap 30 on SOF | P8.27 | P6 | lap 30 |
| 20 | LEC | pit lap 23 on SOF | P4.71 | P4 | lap 30 |
| 20 | LIN | pit lap 26 on MED | P7.50 | P9 | lap 30 |
| 20 | NOR | stay out on HAR | P3.80 | P3 | lap 30 |
| 20 | OCO | stay out on HAR | P13.29 | P11 | lap 30 |
| 20 | PER | stay out on HAR | P16.33 | P20 | lap 30 |
| 20 | PIA | pit lap 30 on SOF | P9.97 | P8 | lap 30 |
| 20 | RUS | pit lap 26 on SOF | P5.22 | P5 | lap 30 |
| 20 | SAI | pit lap 30 on SOF | P18.67 | P19 | lap 30 |
| 20 | STR | pit lap 23 on SOF | P19.95 | P21 | lap 30 |
| 20 | TSU | pit lap 30 on SOF | P16.06 | P14 | lap 30 |
| 20 | VER | stay out on HAR | P4.22 | P2 | lap 30 |
| 25 | ALB | stay out on HAR | P15.92 | P15 | lap 35 |
| 25 | ALO | pit lap 25 on HAR | P16.99 | P17 | lap 35 |
| 25 | ANT | stay out on HAR | P2.44 | P1 | lap 35 |
| 25 | BEA | pit lap 25 on SOF | P15.99 | P16 | lap 35 |
| 25 | BOR | pit lap 25 on SOF | P11.44 | P13 | lap 35 |
| 25 | BOT | pit lap 31 on SOF | P19.18 | P18 | lap 35 |
| 25 | COL | stay out on HAR | P11.55 | P7 | lap 35 |
| 25 | GAS | pit lap 25 on SOF | P10.54 | P12 | lap 35 |
| 25 | HAM | stay out on SOF | P19.75 | P22 | lap 35 |
| 25 | HUL | stay out on HAR | P10.90 | P10 | lap 35 |
| 25 | LAW | pit lap 25 on HAR | P8.09 | P6 | lap 35 |
| 25 | LEC | pit lap 25 on SOF | P4.81 | P4 | lap 35 |
| 25 | LIN | pit lap 25 on SOF | P6.74 | P9 | lap 35 |
| 25 | NOR | stay out on HAR | P3.66 | P3 | lap 35 |
| 25 | OCO | stay out on HAR | P12.85 | P11 | lap 35 |
| 25 | PER | stay out on HAR | P16.23 | P20 | lap 35 |
| 25 | PIA | pit lap 31 on SOF | P8.74 | P8 | lap 35 |
| 25 | RUS | stay out on MED | P5.61 | P5 | lap 35 |
| 25 | SAI | stay out on MED | P19.36 | P19 | lap 35 |
| 25 | STR | pit lap 25 on HAR | P20.69 | P21 | lap 35 |
| 25 | TSU | pit lap 25 on SOF | P14.91 | P14 | lap 35 |
| 25 | VER | stay out on HAR | P4.25 | P2 | lap 35 |
| 30 | ALB | pit lap 30 on SOF | P15.61 | P15 | lap 40 |
| 30 | ALO | pit lap 30 on SOF | P17.20 | P17 | lap 40 |
| 30 | ANT | stay out on HAR | P2.42 | P1 | lap 40 |
| 30 | BEA | pit lap 30 on SOF | P13.75 | P16 | lap 40 |
| 30 | BOR | pit lap 30 on SOF | P10.58 | P13 | lap 40 |
| 30 | BOT | pit lap 30 on SOF | P18.65 | P18 | lap 40 |
| 30 | COL | stay out on HAR | P11.33 | P7 | lap 40 |
| 30 | GAS | pit lap 30 on SOF | P9.82 | P12 | lap 40 |
| 30 | HAM | stay out on SOF | P19.81 | P22 | lap 40 |
| 30 | HUL | stay out on HAR | P11.60 | P10 | lap 40 |
| 30 | LAW | pit lap 30 on SOF | P7.55 | P6 | lap 40 |
| 30 | LEC | pit lap 30 on SOF | P3.45 | P4 | lap 40 |
| 30 | LIN | pit lap 40 on SOF | P6.94 | P9 | lap 40 |
| 30 | NOR | stay out on HAR | P3.52 | P3 | lap 40 |
| 30 | OCO | stay out on HAR | P12.95 | P11 | lap 40 |
| 30 | PER | pit lap 30 on SOF | P16.52 | P20 | lap 40 |
| 30 | PIA | pit lap 30 on SOF | P7.99 | P8 | lap 40 |
| 30 | RUS | stay out on HAR | P5.65 | P5 | lap 40 |
| 30 | SAI | stay out on MED | P19.80 | P19 | lap 40 |
| 30 | STR | pit lap 36 on SOF | P20.83 | P21 | lap 40 |
| 30 | TSU | pit lap 30 on SOF | P13.78 | P14 | lap 40 |
| 30 | VER | pit lap 30 on SOF | P3.97 | P2 | lap 40 |
| 35 | ALB | stay out on HAR | P15.24 | P15 | lap 45 |
| 35 | ALO | pit lap 35 on HAR | P16.50 | P17 | lap 45 |
| 35 | ANT | stay out on HAR | P2.29 | P1 | lap 45 |
| 35 | BEA | stay out on MED | P15.35 | P16 | lap 45 |
| 35 | BOR | pit lap 35 on HAR | P11.79 | P13 | lap 45 |
| 35 | BOT | stay out on HAR | P17.97 | P18 | lap 45 |
| 35 | COL | stay out on HAR | P11.04 | P7 | lap 45 |
| 35 | GAS | pit lap 35 on HAR | P10.74 | P12 | lap 45 |
| 35 | HAM | stay out on SOF | P20.24 | P22 | lap 45 |
| 35 | HUL | stay out on HAR | P11.35 | P10 | lap 45 |
| 35 | LAW | pit lap 35 on HAR | P7.94 | P6 | lap 45 |
| 35 | LEC | pit lap 35 on HAR | P4.11 | P4 | lap 45 |
| 35 | LIN | stay out on HAR | P10.35 | P9 | lap 45 |
| 35 | NOR | stay out on HAR | P3.53 | P3 | lap 45 |
| 35 | OCO | stay out on HAR | P12.87 | P11 | lap 45 |
| 35 | PER | stay out on HAR | P20.20 | P20 | lap 45 |
| 35 | PIA | pit lap 35 on HAR | P7.98 | P8 | lap 45 |
| 35 | RUS | stay out on HAR | P5.01 | P5 | lap 45 |
| 35 | SAI | stay out on HAR | P18.61 | P19 | lap 45 |
| 35 | STR | pit lap 35 on HAR | P21.28 | P21 | lap 45 |
| 35 | TSU | pit lap 35 on HAR | P13.76 | P14 | lap 45 |
| 35 | VER | stay out on HAR | P3.75 | P2 | lap 45 |
| 40 | ALB | stay out on HAR | P15.12 | P15 | lap 50 |
| 40 | ALO | stay out on HAR | P16.68 | P17 | lap 50 |
| 40 | ANT | stay out on HAR | P2.17 | P1 | lap 50 |
| 40 | BEA | stay out on MED | P15.79 | P16 | lap 50 |
| 40 | BOR | pit lap 40 on SOF | P12.66 | P13 | lap 50 |
| 40 | BOT | stay out on HAR | P18.03 | P18 | lap 50 |
| 40 | COL | stay out on HAR | P10.51 | P7 | lap 50 |
| 40 | GAS | pit lap 40 on SOF | P11.35 | P12 | lap 50 |
| 40 | HAM | stay out on SOF | P20.64 | P22 | lap 50 |
| 40 | HUL | stay out on HAR | P11.46 | P10 | lap 50 |
| 40 | LAW | pit lap 40 on SOF | P8.51 | P6 | lap 50 |
| 40 | LEC | pit lap 40 on SOF | P4.30 | P4 | lap 50 |
| 40 | LIN | stay out on HAR | P10.48 | P9 | lap 50 |
| 40 | NOR | stay out on HAR | P3.41 | P3 | lap 50 |
| 40 | OCO | stay out on HAR | P12.88 | P11 | lap 50 |
| 40 | PER | stay out on HAR | P19.97 | P20 | lap 50 |
| 40 | PIA | pit lap 40 on SOF | P8.26 | P8 | lap 50 |
| 40 | RUS | stay out on HAR | P5.04 | P5 | lap 50 |
| 40 | SAI | stay out on HAR | P18.93 | P19 | lap 50 |
| 40 | STR | pit lap 40 on HAR | P21.53 | P21 | lap 50 |
| 40 | TSU | stay out on MED | P13.93 | P14 | lap 50 |
| 40 | VER | stay out on HAR | P3.48 | P2 | lap 50 |
| 45 | ALB | stay out on HAR | P15.05 | P15 | lap 55 |
| 45 | ALO | stay out on HAR | P16.78 | P17 | lap 55 |
| 45 | ANT | stay out on HAR | P2.25 | P1 | lap 55 |
| 45 | BEA | stay out on HAR | P15.88 | P16 | lap 55 |
| 45 | BOR | pit lap 45 on SOF | P12.86 | P13 | lap 55 |
| 45 | BOT | pit lap 45 on SOF | P17.99 | P18 | lap 55 |
| 45 | COL | stay out on HAR | P9.56 | P7 | lap 55 |
| 45 | GAS | pit lap 45 on SOF | P11.46 | P12 | lap 55 |
| 45 | HAM | stay out on SOF | P20.91 | P22 | lap 55 |
| 45 | HUL | stay out on HAR | P10.64 | P10 | lap 55 |
| 45 | LAW | stay out on --- | P7.06 | P6 | lap 55 |
| 45 | LEC | pit lap 45 on SOF | P4.18 | P4 | lap 55 |
| 45 | LIN | stay out on HAR | P10.36 | P9 | lap 55 |
| 45 | NOR | stay out on HAR | P3.32 | P3 | lap 55 |
| 45 | OCO | stay out on HAR | P12.86 | P11 | lap 55 |
| 45 | PER | stay out on HAR | P20.00 | P20 | lap 55 |
| 45 | PIA | stay out on MED | P10.56 | P8 | lap 55 |
| 45 | RUS | pit lap 45 on SOF | P5.10 | P5 | lap 55 |
| 45 | SAI | stay out on HAR | P19.01 | P19 | lap 55 |
| 45 | STR | pit lap 45 on SOF | P21.72 | P21 | lap 55 |
| 45 | TSU | stay out on MED | P13.96 | P14 | lap 55 |
| 45 | VER | stay out on HAR | P3.18 | P2 | lap 55 |
| 50 | ALB | stay out on HAR | P15.00 | P15 | lap 57 |
| 50 | ALO | stay out on HAR | P16.89 | P17 | lap 57 |
| 50 | ANT | stay out on HAR | P1.42 | P1 | lap 57 |
| 50 | BEA | stay out on HAR | P15.95 | P16 | lap 57 |
| 50 | BOR | stay out on SOF | P12.94 | P13 | lap 57 |
| 50 | BOT | stay out on SOF | P18.87 | P18 | lap 57 |
| 50 | COL | stay out on HAR | P8.77 | P7 | lap 57 |
| 50 | GAS | pit lap 50 on SOF | P11.08 | P12 | lap 57 |
| 50 | HAM | stay out on SOF | P21.30 | P22 | lap 57 |
| 50 | HUL | stay out on HAR | P10.78 | P10 | lap 57 |
| 50 | LAW | stay out on MED | P6.73 | P6 | lap 57 |
| 50 | LEC | stay out on SOF | P4.19 | P4 | lap 57 |
| 50 | LIN | stay out on HAR | P9.96 | P9 | lap 57 |
| 50 | NOR | stay out on HAR | P2.49 | P3 | lap 57 |
| 50 | OCO | stay out on HAR | P11.95 | P11 | lap 57 |
| 50 | PER | stay out on HAR | P19.71 | P20 | lap 57 |
| 50 | PIA | stay out on MED | P8.67 | P8 | lap 57 |
| 50 | RUS | stay out on HAR | P4.99 | P5 | lap 57 |
| 50 | SAI | stay out on HAR | P18.98 | P19 | lap 57 |
| 50 | STR | pit lap 50 on SOF | P21.84 | P21 | lap 57 |
| 50 | TSU | stay out on MED | P13.96 | P14 | lap 57 |
| 50 | VER | stay out on HAR | P2.46 | P2 | lap 57 |
| 55 | ALB | stay out on HAR | P14.98 | P15 | lap 57 |
| 55 | ALO | stay out on HAR | P16.97 | P17 | lap 57 |
| 55 | ANT | stay out on HAR | P1.14 | P1 | lap 57 |
| 55 | BEA | stay out on HAR | P15.98 | P16 | lap 57 |
| 55 | BOR | stay out on SOF | P13.00 | P13 | lap 57 |
| 55 | BOT | stay out on SOF | P18.54 | P18 | lap 57 |
| 55 | COL | stay out on HAR | P8.04 | P7 | lap 57 |
| 55 | GAS | pit lap 55 on SOF | P9.07 | P12 | lap 57 |
| 55 | HAM | stay out on SOF | P21.62 | P22 | lap 57 |
| 55 | HUL | stay out on HAR | P10.99 | P10 | lap 57 |
| 55 | LAW | stay out on MED | P6.05 | P6 | lap 57 |
| 55 | LEC | stay out on SOF | P4.27 | P4 | lap 57 |
| 55 | LIN | stay out on HAR | P10.00 | P9 | lap 57 |
| 55 | NOR | stay out on HAR | P2.78 | P3 | lap 57 |
| 55 | OCO | stay out on HAR | P11.99 | P11 | lap 57 |
| 55 | PER | stay out on HAR | P19.78 | P20 | lap 57 |
| 55 | PIA | stay out on MED | P8.73 | P8 | lap 57 |
| 55 | RUS | stay out on HAR | P4.78 | P5 | lap 57 |
| 55 | SAI | stay out on HAR | P19.08 | P19 | lap 57 |
| 55 | STR | pit lap 55 on SOF | P21.95 | P21 | lap 57 |
| 55 | TSU | stay out on MED | P13.99 | P14 | lap 57 |
| 55 | VER | stay out on HAR | P2.22 | P2 | lap 57 |

---

Every prediction above was committed to this repository before the lap it refers to.
Commit timestamps are the evidence; `git log predictions/` shows them.