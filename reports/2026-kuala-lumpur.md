# 2026 Bahrain GP in Malaysia backtest — Kuala Lumpur

*Generated 2026-10-04 11:14 UTC from 154 logged predictions.*

> **Not a live ledger.**
> No circuit history: attrition,degradation,pit_loss,safety_car used the field average.
> Calls: backtest of 2026-r16-race.txt.
> Rows made against a recording that already contains the result are not evidence
> that the call preceded the outcome, whatever they score.

## Verdict

Better than the baseline on Brier skill (+11.0%) but not on position error (1.76 vs 1.57). A partial result.

## Scores

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (top 3) | 0.0693 | 0.0779 | +11.0% |
| Brier (points) | 0.0852 | 0.1039 | +18.0% |
| Mean position error | 1.76 | 1.57 | — |

The baseline forecasts that every car finishes where it currently runs. In Formula 1
that is a strong benchmark, not a straw man — track position is sticky. Negative skill
means the model added nothing over assuming the order holds.

## Calibration

| confidence band | n | said | happened |
|---|---|---|---|
| 0%–20% | 133 | 0.8% | 4.5% |
| 80%–100% | 21 | 94.6% | 71.4% |

A well-calibrated model matches the last two columns. Consistently saying more
than happens is overconfidence, and it is a separate failure from being wrong.

## Every call

| lap | driver | call | expected | actual | horizon |
|---|---|---|---|---|---|
| 31 | ALB | stay out on SOF | P19.20 | P21 | lap 41 |
| 31 | ALO | stay out on HAR | P8.96 | P8 | lap 41 |
| 31 | ANT | stay out on MED | P2.15 | P2 | lap 41 |
| 31 | BEA | stay out on HAR | P14.69 | P14 | lap 41 |
| 31 | BOR | pit lap 31 on SOF | P18.79 | P18 | lap 41 |
| 31 | BOT | pit lap 34 on MED | P17.07 | P22 | lap 41 |
| 31 | COL | stay out on MED | P11.15 | P13 | lap 41 |
| 31 | GAS | stay out on HAR | P15.83 | P16 | lap 41 |
| 31 | HAD | pit lap 31 on SOF | P6.21 | P5 | lap 41 |
| 31 | HAM | pit lap 31 on SOF | P6.66 | P3 | lap 41 |
| 31 | HUL | stay out on SOF | P13.66 | P11 | lap 41 |
| 31 | LAW | stay out on HAR | P12.96 | P7 | lap 41 |
| 31 | LEC | stay out on SOF | P10.30 | P4 | lap 41 |
| 31 | LIN | stay out on HAR | P12.37 | P10 | lap 41 |
| 31 | NOR | stay out on HAR | P6.60 | P9 | lap 41 |
| 31 | OCO | stay out on HAR | P15.55 | P15 | lap 41 |
| 31 | PER | pit lap 31 on SOF | P20.17 | P19 | lap 41 |
| 31 | PIA | stay out on HAR | P6.55 | P6 | lap 41 |
| 31 | RUS | stay out on MED | P3.09 | P20 | lap 41 |
| 31 | SAI | stay out on HAR | P14.99 | P17 | lap 41 |
| 31 | STR | stay out on HAR | P13.58 | P12 | lap 41 |
| 31 | VER | pit lap 31 on SOF | P2.84 | P1 | lap 41 |
| 35 | ALB | stay out on SOF | P19.12 | P21 | lap 45 |
| 35 | ALO | stay out on HAR | P12.45 | P8 | lap 45 |
| 35 | ANT | stay out on SOF | P1.74 | P2 | lap 45 |
| 35 | BEA | stay out on HAR | P14.40 | P14 | lap 45 |
| 35 | BOR | pit lap 35 on SOF | P20.41 | P18 | lap 45 |
| 35 | BOT | pit lap 38 on SOF | P17.55 | P22 | lap 45 |
| 35 | COL | stay out on HAR | P16.28 | P13 | lap 45 |
| 35 | GAS | stay out on HAR | P15.34 | P16 | lap 45 |
| 35 | HAD | stay out on SOF | P4.42 | P5 | lap 45 |
| 35 | HAM | stay out on MED | P5.32 | P3 | lap 45 |
| 35 | HUL | stay out on SOF | P13.38 | P11 | lap 45 |
| 35 | LAW | stay out on HAR | P8.13 | P7 | lap 45 |
| 35 | LEC | stay out on SOF | P6.64 | P4 | lap 45 |
| 35 | LIN | stay out on HAR | P10.35 | P10 | lap 45 |
| 35 | NOR | stay out on SOF | P8.35 | P9 | lap 45 |
| 35 | OCO | stay out on HAR | P13.78 | P15 | lap 45 |
| 35 | PER | pit lap 35 on SOF | P21.36 | P19 | lap 45 |
| 35 | PIA | stay out on HAR | P7.47 | P6 | lap 45 |
| 35 | RUS | stay out on MED | P2.83 | P20 | lap 45 |
| 35 | SAI | stay out on HAR | P17.54 | P17 | lap 45 |
| 35 | STR | stay out on HAR | P12.83 | P12 | lap 45 |
| 35 | VER | stay out on SOF | P3.16 | P1 | lap 45 |
| 40 | ALB | pit lap 40 on SOF | P19.19 | P21 | lap 50 |
| 40 | ALO | stay out on HAR | P11.03 | P8 | lap 50 |
| 40 | ANT | stay out on SOF | P1.91 | P2 | lap 50 |
| 40 | BEA | stay out on HAR | P16.65 | P14 | lap 50 |
| 40 | BOR | pit lap 40 on SOF | P20.36 | P18 | lap 50 |
| 40 | BOT | pit lap 46 on SOF | P18.91 | P22 | lap 50 |
| 40 | COL | stay out on HAR | P14.23 | P13 | lap 50 |
| 40 | GAS | stay out on HAR | P18.00 | P16 | lap 50 |
| 40 | HAD | stay out on SOF | P4.43 | P5 | lap 50 |
| 40 | HAM | stay out on MED | P5.49 | P3 | lap 50 |
| 40 | HUL | stay out on SOF | P11.36 | P11 | lap 50 |
| 40 | LAW | stay out on HAR | P9.05 | P7 | lap 50 |
| 40 | LEC | stay out on SOF | P7.35 | P4 | lap 50 |
| 40 | LIN | stay out on HAR | P10.96 | P10 | lap 50 |
| 40 | NOR | stay out on SOF | P7.35 | P9 | lap 50 |
| 40 | OCO | stay out on HAR | P14.29 | P15 | lap 50 |
| 40 | PER | pit lap 43 on SOF | P21.67 | P19 | lap 50 |
| 40 | PIA | stay out on HAR | P6.19 | P6 | lap 50 |
| 40 | RUS | stay out on MED | P3.13 | P20 | lap 50 |
| 40 | SAI | stay out on HAR | P16.27 | P17 | lap 50 |
| 40 | STR | stay out on HAR | P13.21 | P12 | lap 50 |
| 40 | VER | stay out on SOF | P1.82 | P1 | lap 50 |
| 44 | ALB | stay out on SOF | P20.67 | P21 | lap 54 |
| 44 | ALO | stay out on HAR | P10.41 | P8 | lap 54 |
| 44 | ANT | stay out on SOF | P1.69 | P2 | lap 54 |
| 44 | BEA | stay out on HAR | P14.62 | P14 | lap 54 |
| 44 | BOR | pit lap 44 on SOF | P19.03 | P18 | lap 54 |
| 44 | BOT | pit lap 47 on SOF | P20.43 | P22 | lap 54 |
| 44 | COL | stay out on MED | P14.42 | P13 | lap 54 |
| 44 | GAS | stay out on HAR | P16.18 | P16 | lap 54 |
| 44 | HAD | stay out on SOF | P4.21 | P5 | lap 54 |
| 44 | HAM | stay out on SOF | P6.29 | P3 | lap 54 |
| 44 | HUL | stay out on SOF | P10.74 | P11 | lap 54 |
| 44 | LAW | stay out on HAR | P8.91 | P7 | lap 54 |
| 44 | LEC | stay out on SOF | P8.24 | P4 | lap 54 |
| 44 | LIN | stay out on SOF | P12.33 | P10 | lap 54 |
| 44 | NOR | stay out on SOF | P6.86 | P9 | lap 54 |
| 44 | OCO | stay out on SOF | P16.53 | P15 | lap 54 |
| 44 | PER | stay out on MED | P20.97 | P19 | lap 54 |
| 44 | PIA | stay out on HAR | P5.02 | P6 | lap 54 |
| 44 | RUS | stay out on MED | P3.16 | P20 | lap 54 |
| 44 | SAI | stay out on SOF | P18.00 | P17 | lap 54 |
| 44 | STR | stay out on SOF | P12.58 | P12 | lap 54 |
| 44 | VER | stay out on SOF | P1.63 | P1 | lap 54 |
| 48 | ALB | stay out on SOF | P20.90 | P21 | lap 55 |
| 48 | ALO | stay out on SOF | P9.85 | P8 | lap 55 |
| 48 | ANT | stay out on SOF | P2.41 | P2 | lap 55 |
| 48 | BEA | stay out on HAR | P14.45 | P14 | lap 55 |
| 48 | BOR | stay out on SOF | P18.91 | P18 | lap 55 |
| 48 | BOT | pit lap 51 on SOF | P20.95 | P22 | lap 55 |
| 48 | COL | stay out on MED | P14.62 | P13 | lap 55 |
| 48 | GAS | stay out on SOF | P16.84 | P16 | lap 55 |
| 48 | HAD | stay out on SOF | P4.16 | P5 | lap 55 |
| 48 | HAM | stay out on SOF | P5.85 | P3 | lap 55 |
| 48 | HUL | stay out on SOF | P11.42 | P11 | lap 55 |
| 48 | LAW | stay out on SOF | P8.73 | P7 | lap 55 |
| 48 | LEC | stay out on SOF | P6.02 | P4 | lap 55 |
| 48 | LIN | stay out on SOF | P12.11 | P10 | lap 55 |
| 48 | NOR | stay out on SOF | P7.85 | P9 | lap 55 |
| 48 | OCO | stay out on SOF | P15.83 | P15 | lap 55 |
| 48 | PER | stay out on SOF | P20.56 | P19 | lap 55 |
| 48 | PIA | stay out on HAR | P6.94 | P6 | lap 55 |
| 48 | RUS | stay out on SOF | P2.68 | P20 | lap 55 |
| 48 | SAI | stay out on SOF | P18.04 | P17 | lap 55 |
| 48 | STR | stay out on SOF | P12.54 | P12 | lap 55 |
| 48 | VER | stay out on SOF | P1.27 | P1 | lap 55 |
| 52 | ALB | stay out on SOF | P20.18 | P21 | lap 55 |
| 52 | ALO | stay out on SOF | P8.07 | P8 | lap 55 |
| 52 | ANT | stay out on SOF | P1.95 | P2 | lap 55 |
| 52 | BEA | stay out on HAR | P13.85 | P14 | lap 55 |
| 52 | BOR | stay out on SOF | P17.93 | P18 | lap 55 |
| 52 | BOT | pit lap 55 on SOF | P21.59 | P22 | lap 55 |
| 52 | COL | stay out on MED | P12.61 | P13 | lap 55 |
| 52 | GAS | stay out on SOF | P16.43 | P16 | lap 55 |
| 52 | HAD | stay out on SOF | P3.24 | P5 | lap 55 |
| 52 | HAM | stay out on SOF | P4.40 | P3 | lap 55 |
| 52 | HUL | stay out on SOF | P8.92 | P11 | lap 55 |
| 52 | LAW | stay out on SOF | P6.59 | P7 | lap 55 |
| 52 | LEC | stay out on SOF | P5.05 | P4 | lap 55 |
| 52 | LIN | stay out on SOF | P10.69 | P10 | lap 55 |
| 52 | NOR | stay out on SOF | P10.93 | P9 | lap 55 |
| 52 | OCO | stay out on SOF | P14.93 | P15 | lap 55 |
| 52 | PER | stay out on SOF | P18.80 | P19 | lap 55 |
| 52 | PIA | stay out on HAR | P6.79 | P6 | lap 55 |
| 52 | RUS | stay out on SOF | P20.38 | P20 | lap 55 |
| 52 | SAI | stay out on SOF | P16.73 | P17 | lap 55 |
| 52 | STR | stay out on SOF | P11.72 | P12 | lap 55 |
| 52 | VER | stay out on SOF | P1.20 | P1 | lap 55 |
| 54 | ALB | stay out on SOF | P20.68 | P21 | lap 55 |
| 54 | ALO | stay out on SOF | P8.09 | P8 | lap 55 |
| 54 | ANT | stay out on SOF | P1.98 | P2 | lap 55 |
| 54 | BEA | stay out on HAR | P14.11 | P14 | lap 55 |
| 54 | BOR | stay out on SOF | P17.84 | P18 | lap 55 |
| 54 | BOT | pit lap 55 on SOF | P21.65 | P22 | lap 55 |
| 54 | COL | stay out on MED | P12.73 | P13 | lap 55 |
| 54 | GAS | stay out on SOF | P16.01 | P16 | lap 55 |
| 54 | HAD | stay out on SOF | P5.14 | P5 | lap 55 |
| 54 | HAM | stay out on SOF | P3.17 | P3 | lap 55 |
| 54 | HUL | stay out on SOF | P10.18 | P11 | lap 55 |
| 54 | LAW | stay out on SOF | P7.00 | P7 | lap 55 |
| 54 | LEC | stay out on SOF | P4.03 | P4 | lap 55 |
| 54 | LIN | stay out on SOF | P11.09 | P10 | lap 55 |
| 54 | NOR | stay out on SOF | P8.85 | P9 | lap 55 |
| 54 | OCO | stay out on SOF | P15.08 | P15 | lap 55 |
| 54 | PER | stay out on SOF | P19.21 | P19 | lap 55 |
| 54 | PIA | stay out on HAR | P5.90 | P6 | lap 55 |
| 54 | RUS | stay out on SOF | P20.17 | P20 | lap 55 |
| 54 | SAI | stay out on SOF | P16.95 | P17 | lap 55 |
| 54 | STR | stay out on SOF | P12.03 | P12 | lap 55 |
| 54 | VER | stay out on SOF | P1.08 | P1 | lap 55 |

---

Every prediction above was committed to this repository before the lap it refers to.
Commit timestamps are the evidence; `git log predictions/` shows them.