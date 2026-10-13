# 2026 Singapore GP backtest — Singapore

*Generated 2026-10-13 22:24 UTC from 220 logged predictions.*

> **Not a live ledger.**
> Calls: backtest of 2026-singapore-archive.txt.
> Rows made against a recording that already contains the result are not evidence
> that the call preceded the outcome, whatever they score.

## Verdict

Better than the baseline on Brier skill (+49.4%) but not on position error (1.70 vs 1.20). A partial result.

## Scores

| metric | model | baseline | skill |
|---|---|---|---|
| Brier (top 3) | 0.0460 | 0.0909 | +49.4% |
| Brier (points) | 0.0939 | 0.1364 | +31.1% |
| Mean position error | 1.70 | 1.20 | — |

The baseline forecasts that every car finishes where it currently runs. In Formula 1
that is a strong benchmark, not a straw man — track position is sticky. Negative skill
means the model added nothing over assuming the order holds.

## Calibration

| confidence band | n | said | happened |
|---|---|---|---|
| 0%–20% | 167 | 0.9% | 0.0% |
| 20%–40% | 14 | 30.2% | 21.4% |
| 40%–60% | 11 | 48.4% | 54.5% |
| 60%–80% | 17 | 70.4% | 70.6% |
| 80%–100% | 11 | 95.3% | 81.8% |

A well-calibrated model matches the last two columns. Consistently saying more
than happens is overconfidence, and it is a separate failure from being wrong.

## Every call

| lap | driver | call | expected | actual | horizon |
|---|---|---|---|---|---|
| 17 | ALB | pit lap 17 on HAR | P16.58 | P18 | lap 27 |
| 17 | ALO | pit lap 20 on SOF | P12.53 | P16 | lap 27 |
| 17 | ANT | pit lap 27 on HAR | P3.36 | P3 | lap 27 |
| 17 | BEA | pit lap 27 on HAR | P13.18 | P12 | lap 27 |
| 17 | BOR | pit lap 27 on SOF | P14.09 | P22 | lap 27 |
| 17 | BOT | pit lap 23 on MED | P18.51 | P19 | lap 27 |
| 17 | COL | pit lap 27 on MED | P14.61 | P21 | lap 27 |
| 17 | GAS | pit lap 20 on MED | P6.25 | P11 | lap 27 |
| 17 | HAD | pit lap 27 on MED | P15.24 | P10 | lap 27 |
| 17 | HAM | pit lap 23 on MED | P5.91 | P6 | lap 27 |
| 17 | HUL | pit lap 27 on HAR | P12.36 | P8 | lap 27 |
| 17 | LAW | pit lap 27 on HAR | P11.84 | P7 | lap 27 |
| 17 | LEC | pit lap 17 on HAR | P5.16 | P2 | lap 27 |
| 17 | LIN | pit lap 27 on MED | P15.43 | P15 | lap 27 |
| 17 | NOR | pit lap 17 on SOF | P3.87 | P4 | lap 27 |
| 17 | OCO | pit lap 17 on SOF | P14.01 | P13 | lap 27 |
| 17 | PER | pit lap 23 on MED | P17.36 | P17 | lap 27 |
| 17 | PIA | pit lap 17 on HAR | P8.22 | P5 | lap 27 |
| 17 | RUS | pit lap 27 on HAR | P13.45 | P9 | lap 27 |
| 17 | SAI | pit lap 23 on SOF | P15.21 | P14 | lap 27 |
| 17 | STR | pit lap 17 on HAR | P18.13 | P20 | lap 27 |
| 17 | VER | pit lap 17 on HAR | P5.21 | P1 | lap 27 |
| 20 | ALB | pit lap 20 on HAR | P16.66 | P18 | lap 30 |
| 20 | ALO | pit lap 23 on SOF | P12.86 | P16 | lap 30 |
| 20 | ANT | pit lap 20 on HAR | P4.82 | P3 | lap 30 |
| 20 | BEA | pit lap 20 on HAR | P12.19 | P12 | lap 30 |
| 20 | BOR | pit lap 23 on SOF | P14.98 | P22 | lap 30 |
| 20 | BOT | pit lap 30 on MED | P19.05 | P19 | lap 30 |
| 20 | COL | pit lap 30 on MED | P14.40 | P21 | lap 30 |
| 20 | GAS | pit lap 23 on HAR | P12.27 | P11 | lap 30 |
| 20 | HAD | pit lap 30 on MED | P14.04 | P10 | lap 30 |
| 20 | HAM | stay out on SOF | P4.99 | P6 | lap 30 |
| 20 | HUL | pit lap 23 on HAR | P12.09 | P8 | lap 30 |
| 20 | LAW | pit lap 30 on HAR | P11.49 | P7 | lap 30 |
| 20 | LEC | pit lap 20 on HAR | P3.83 | P2 | lap 30 |
| 20 | LIN | pit lap 20 on MED | P15.85 | P15 | lap 30 |
| 20 | NOR | pit lap 26 on SOF | P2.28 | P4 | lap 30 |
| 20 | OCO | pit lap 20 on HAR | P12.52 | P13 | lap 30 |
| 20 | PER | pit lap 26 on MED | P17.05 | P17 | lap 30 |
| 20 | PIA | pit lap 26 on MED | P7.00 | P5 | lap 30 |
| 20 | RUS | pit lap 23 on HAR | P12.42 | P9 | lap 30 |
| 20 | SAI | pit lap 30 on MED | P14.21 | P14 | lap 30 |
| 20 | STR | pit lap 30 on MED | P17.66 | P20 | lap 30 |
| 20 | VER | pit lap 20 on MED | P3.97 | P1 | lap 30 |
| 23 | ALB | pit lap 23 on MED | P17.45 | P18 | lap 33 |
| 23 | ALO | pit lap 23 on MED | P16.51 | P16 | lap 33 |
| 23 | ANT | pit lap 23 on MED | P4.13 | P3 | lap 33 |
| 23 | BEA | pit lap 23 on MED | P13.22 | P12 | lap 33 |
| 23 | BOR | pit lap 23 on HAR | P15.58 | P22 | lap 33 |
| 23 | BOT | pit lap 26 on MED | P19.37 | P19 | lap 33 |
| 23 | COL | pit lap 26 on MED | P14.63 | P21 | lap 33 |
| 23 | GAS | pit lap 23 on SOF | P13.35 | P11 | lap 33 |
| 23 | HAD | pit lap 26 on MED | P14.78 | P10 | lap 33 |
| 23 | HAM | stay out on SOF | P4.33 | P6 | lap 33 |
| 23 | HUL | pit lap 33 on MED | P13.03 | P8 | lap 33 |
| 23 | LAW | pit lap 29 on MED | P12.57 | P7 | lap 33 |
| 23 | LEC | pit lap 23 on MED | P3.85 | P2 | lap 33 |
| 23 | LIN | pit lap 23 on MED | P15.73 | P15 | lap 33 |
| 23 | NOR | pit lap 23 on HAR | P2.49 | P4 | lap 33 |
| 23 | OCO | pit lap 23 on MED | P13.61 | P13 | lap 33 |
| 23 | PER | stay out on MED | P17.57 | P17 | lap 33 |
| 23 | PIA | pit lap 23 on MED | P5.97 | P5 | lap 33 |
| 23 | RUS | pit lap 23 on MED | P13.58 | P9 | lap 33 |
| 23 | SAI | pit lap 23 on MED | P14.17 | P14 | lap 33 |
| 23 | STR | pit lap 23 on MED | P17.14 | P20 | lap 33 |
| 23 | VER | pit lap 23 on MED | P3.53 | P1 | lap 33 |
| 26 | ALB | stay out on SOF | P17.81 | P18 | lap 36 |
| 26 | ALO | pit lap 26 on SOF | P16.69 | P16 | lap 36 |
| 26 | ANT | stay out on MED | P4.00 | P3 | lap 36 |
| 26 | BEA | pit lap 26 on HAR | P13.34 | P12 | lap 36 |
| 26 | BOR | pit lap 36 on SOF | P16.04 | P22 | lap 36 |
| 26 | BOT | pit lap 29 on SOF | P19.77 | P19 | lap 36 |
| 26 | COL | pit lap 26 on SOF | P14.87 | P21 | lap 36 |
| 26 | GAS | pit lap 26 on SOF | P13.48 | P11 | lap 36 |
| 26 | HAD | pit lap 29 on MED | P15.25 | P10 | lap 36 |
| 26 | HAM | stay out on SOF | P3.91 | P6 | lap 36 |
| 26 | HUL | pit lap 36 on SOF | P12.64 | P8 | lap 36 |
| 26 | LAW | pit lap 32 on MED | P12.29 | P7 | lap 36 |
| 26 | LEC | stay out on MED | P3.60 | P2 | lap 36 |
| 26 | LIN | pit lap 26 on MED | P15.85 | P15 | lap 36 |
| 26 | NOR | pit lap 26 on HAR | P4.75 | P4 | lap 36 |
| 26 | OCO | pit lap 26 on MED | P14.06 | P13 | lap 36 |
| 26 | PER | stay out on MED | P18.87 | P17 | lap 36 |
| 26 | PIA | pit lap 26 on MED | P4.93 | P5 | lap 36 |
| 26 | RUS | pit lap 26 on HAR | P13.56 | P9 | lap 36 |
| 26 | SAI | pit lap 26 on MED | P14.71 | P14 | lap 36 |
| 26 | STR | pit lap 26 on SOF | P17.92 | P20 | lap 36 |
| 26 | VER | pit lap 26 on HAR | P2.81 | P1 | lap 36 |
| 29 | ALB | stay out on SOF | P17.43 | P18 | lap 39 |
| 29 | ALO | pit lap 29 on SOF | P15.23 | P16 | lap 39 |
| 29 | ANT | stay out on MED | P4.40 | P3 | lap 39 |
| 29 | BEA | pit lap 39 on MED | P13.89 | P12 | lap 39 |
| 29 | BOR | pit lap 39 on SOF | P16.04 | P22 | lap 39 |
| 29 | BOT | pit lap 35 on SOF | P20.00 | P19 | lap 39 |
| 29 | COL | pit lap 29 on MED | P14.48 | P21 | lap 39 |
| 29 | GAS | pit lap 39 on SOF | P13.08 | P11 | lap 39 |
| 29 | HAD | pit lap 29 on MED | P14.64 | P10 | lap 39 |
| 29 | HAM | stay out on SOF | P3.94 | P6 | lap 39 |
| 29 | HUL | pit lap 39 on HAR | P12.56 | P8 | lap 39 |
| 29 | LAW | pit lap 35 on MED | P12.00 | P7 | lap 39 |
| 29 | LEC | stay out on MED | P3.63 | P2 | lap 39 |
| 29 | LIN | stay out on SOF | P16.20 | P15 | lap 39 |
| 29 | NOR | pit lap 29 on SOF | P4.79 | P4 | lap 39 |
| 29 | OCO | stay out on MED | P13.93 | P13 | lap 39 |
| 29 | PER | stay out on MED | P17.81 | P17 | lap 39 |
| 29 | PIA | pit lap 29 on SOF | P5.02 | P5 | lap 39 |
| 29 | RUS | pit lap 39 on SOF | P13.57 | P9 | lap 39 |
| 29 | SAI | pit lap 29 on MED | P14.35 | P14 | lap 39 |
| 29 | STR | pit lap 29 on SOF | P18.94 | P20 | lap 39 |
| 29 | VER | pit lap 29 on MED | P3.08 | P1 | lap 39 |
| 31 | ALB | stay out on SOF | P16.29 | P18 | lap 41 |
| 31 | ALO | pit lap 31 on MED | P14.25 | P16 | lap 41 |
| 31 | ANT | stay out on MED | P4.55 | P3 | lap 41 |
| 31 | BEA | pit lap 31 on HAR | P11.30 | P12 | lap 41 |
| 31 | BOR | pit lap 31 on SOF | P16.97 | P22 | lap 41 |
| 31 | BOT | pit lap 31 on MED | P19.87 | P19 | lap 41 |
| 31 | COL | pit lap 31 on MED | P18.98 | P21 | lap 41 |
| 31 | GAS | stay out on SOF | P12.64 | P11 | lap 41 |
| 31 | HAD | pit lap 31 on HAR | P13.79 | P10 | lap 41 |
| 31 | HAM | stay out on SOF | P3.72 | P6 | lap 41 |
| 31 | HUL | stay out on SOF | P10.27 | P8 | lap 41 |
| 31 | LAW | pit lap 31 on HAR | P9.20 | P7 | lap 41 |
| 31 | LEC | stay out on MED | P3.51 | P2 | lap 41 |
| 31 | LIN | stay out on SOF | P15.42 | P15 | lap 41 |
| 31 | NOR | pit lap 31 on HAR | P4.99 | P4 | lap 41 |
| 31 | OCO | stay out on MED | P12.22 | P13 | lap 41 |
| 31 | PER | stay out on MED | P16.92 | P17 | lap 41 |
| 31 | PIA | pit lap 31 on HAR | P5.11 | P5 | lap 41 |
| 31 | RUS | pit lap 34 on HAR | P12.20 | P9 | lap 41 |
| 31 | SAI | pit lap 31 on MED | P13.33 | P14 | lap 41 |
| 31 | STR | stay out on MED | P18.51 | P20 | lap 41 |
| 31 | VER | pit lap 31 on HAR | P3.34 | P1 | lap 41 |
| 36 | ALB | pit lap 36 on MED | P16.21 | P18 | lap 46 |
| 36 | ALO | stay out on SOF | P16.62 | P16 | lap 46 |
| 36 | ANT | stay out on MED | P4.31 | P3 | lap 46 |
| 36 | BEA | stay out on MED | P10.44 | P12 | lap 46 |
| 36 | BOR | pit lap 46 on MED | P17.44 | P22 | lap 46 |
| 36 | BOT | pit lap 42 on MED | P21.15 | P19 | lap 46 |
| 36 | COL | pit lap 39 on MED | P19.79 | P21 | lap 46 |
| 36 | GAS | stay out on SOF | P9.72 | P11 | lap 46 |
| 36 | HAD | stay out on SOF | P12.88 | P10 | lap 46 |
| 36 | HAM | stay out on SOF | P5.10 | P6 | lap 46 |
| 36 | HUL | stay out on SOF | P8.70 | P8 | lap 46 |
| 36 | LAW | stay out on MED | P8.84 | P7 | lap 46 |
| 36 | LEC | stay out on MED | P2.65 | P2 | lap 46 |
| 36 | LIN | stay out on SOF | P14.56 | P15 | lap 46 |
| 36 | NOR | stay out on MED | P4.99 | P4 | lap 46 |
| 36 | OCO | stay out on MED | P12.15 | P13 | lap 46 |
| 36 | PER | pit lap 36 on MED | P17.96 | P17 | lap 46 |
| 36 | PIA | stay out on MED | P5.71 | P5 | lap 46 |
| 36 | RUS | pit lap 36 on MED | P9.49 | P9 | lap 46 |
| 36 | SAI | stay out on MED | P14.24 | P14 | lap 46 |
| 36 | STR | pit lap 36 on MED | P19.06 | P20 | lap 46 |
| 36 | VER | stay out on MED | P1.70 | P1 | lap 46 |
| 42 | ALB | stay out on SOF | P16.64 | P18 | lap 52 |
| 42 | ALO | pit lap 42 on SOF | P16.06 | P16 | lap 52 |
| 42 | ANT | stay out on SOF | P4.57 | P3 | lap 52 |
| 42 | BEA | stay out on MED | P10.32 | P12 | lap 52 |
| 42 | BOR | pit lap 52 on SOF | P19.70 | P22 | lap 52 |
| 42 | BOT | stay out on SOF | P20.71 | P19 | lap 52 |
| 42 | COL | pit lap 42 on SOF | P20.09 | P21 | lap 52 |
| 42 | GAS | stay out on SOF | P9.62 | P11 | lap 52 |
| 42 | HAD | stay out on SOF | P12.06 | P10 | lap 52 |
| 42 | HAM | stay out on SOF | P4.51 | P6 | lap 52 |
| 42 | HUL | stay out on SOF | P8.30 | P8 | lap 52 |
| 42 | LAW | stay out on MED | P8.17 | P7 | lap 52 |
| 42 | LEC | stay out on SOF | P2.94 | P2 | lap 52 |
| 42 | LIN | pit lap 42 on SOF | P14.72 | P15 | lap 52 |
| 42 | NOR | stay out on MED | P4.03 | P4 | lap 52 |
| 42 | OCO | stay out on MED | P12.79 | P13 | lap 52 |
| 42 | PER | pit lap 42 on SOF | P17.78 | P17 | lap 52 |
| 42 | PIA | stay out on SOF | P6.06 | P5 | lap 52 |
| 42 | RUS | stay out on SOF | P9.06 | P9 | lap 52 |
| 42 | SAI | pit lap 42 on SOF | P13.88 | P14 | lap 52 |
| 42 | STR | stay out on MED | P19.82 | P20 | lap 52 |
| 42 | VER | stay out on MED | P1.55 | P1 | lap 52 |
| 50 | ALB | stay out on SOF | P16.81 | P18 | lap 60 |
| 50 | ALO | pit lap 50 on SOF | P15.96 | P16 | lap 60 |
| 50 | ANT | stay out on SOF | P4.27 | P3 | lap 60 |
| 50 | BEA | stay out on MED | P10.71 | P12 | lap 60 |
| 50 | BOR | pit lap 53 on SOF | P20.71 | P22 | lap 60 |
| 50 | BOT | stay out on SOF | P20.66 | P19 | lap 60 |
| 50 | COL | pit lap 50 on SOF | P20.90 | P21 | lap 60 |
| 50 | GAS | stay out on SOF | P11.04 | P11 | lap 60 |
| 50 | HAD | stay out on SOF | P11.23 | P10 | lap 60 |
| 50 | HAM | stay out on SOF | P4.72 | P6 | lap 60 |
| 50 | HUL | stay out on SOF | P8.59 | P8 | lap 60 |
| 50 | LAW | stay out on MED | P7.55 | P7 | lap 60 |
| 50 | LEC | stay out on SOF | P2.22 | P2 | lap 60 |
| 50 | LIN | pit lap 50 on SOF | P14.88 | P15 | lap 60 |
| 50 | NOR | stay out on MED | P3.79 | P4 | lap 60 |
| 50 | OCO | stay out on MED | P12.89 | P13 | lap 60 |
| 50 | PER | pit lap 50 on SOF | P17.86 | P17 | lap 60 |
| 50 | PIA | stay out on SOF | P6.10 | P5 | lap 60 |
| 50 | RUS | stay out on SOF | P8.03 | P9 | lap 60 |
| 50 | SAI | pit lap 50 on HAR | P13.90 | P14 | lap 60 |
| 50 | STR | stay out on MED | P19.64 | P20 | lap 60 |
| 50 | VER | stay out on MED | P1.19 | P1 | lap 60 |
| 58 | ALB | stay out on SOF | P16.96 | P18 | lap 62 |
| 58 | ALO | stay out on MED | P15.99 | P16 | lap 62 |
| 58 | ANT | stay out on SOF | P3.06 | P3 | lap 62 |
| 58 | BEA | stay out on MED | P11.92 | P12 | lap 62 |
| 58 | BOR | pit lap 58 on SOF | P21.54 | P22 | lap 62 |
| 58 | BOT | stay out on SOF | P19.88 | P19 | lap 62 |
| 58 | COL | pit lap 58 on SOF | P21.88 | P21 | lap 62 |
| 58 | GAS | stay out on SOF | P10.51 | P11 | lap 62 |
| 58 | HAD | stay out on SOF | P10.59 | P10 | lap 62 |
| 58 | HAM | stay out on SOF | P5.50 | P6 | lap 62 |
| 58 | HUL | stay out on SOF | P8.47 | P8 | lap 62 |
| 58 | LAW | stay out on MED | P7.06 | P7 | lap 62 |
| 58 | LEC | stay out on SOF | P2.07 | P2 | lap 62 |
| 58 | LIN | stay out on SOF | P15.00 | P15 | lap 62 |
| 58 | NOR | stay out on MED | P4.02 | P4 | lap 62 |
| 58 | OCO | stay out on MED | P13.00 | P13 | lap 62 |
| 58 | PER | stay out on SOF | P17.97 | P17 | lap 62 |
| 58 | PIA | stay out on SOF | P5.59 | P5 | lap 62 |
| 58 | RUS | stay out on SOF | P8.51 | P9 | lap 62 |
| 58 | SAI | stay out on MED | P13.98 | P14 | lap 62 |
| 58 | STR | stay out on MED | P19.73 | P20 | lap 62 |
| 58 | VER | stay out on MED | P1.08 | P1 | lap 62 |

---

Every prediction above was committed to this repository before the lap it refers to.
Commit timestamps are the evidence; `git log predictions/` shows them.