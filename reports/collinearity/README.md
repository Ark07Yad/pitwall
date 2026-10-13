# What the collinearity guard was calibrated on

Measured 13 October 2026, after the Singapore GP showed the guard reading a
quantity the fit does not see. See the logbook entry for that date and
`MAX_TREND_ERROR` in `src/pitwall/models/pace.py`.

- `fits/` — one file per recording: every lap from 8 on, with the fit's trend,
  its standard error, the pooled age/lap correlation the guard used to read, how
  much of the race-lap column the rest of the design explains, and which *other*
  guards refused it. Written by `measure_fits.py <recording>`.
- `plan.json` — the laps backtested in each of twelve races, chosen to span the
  collinearity bands among laps the guard accepted at the time.
- `collinearity-<race>.jsonl` — those backtests: 92 laps, every car, made with
  the guard as it stood on 13 October (pooled r ≤ 0.85). Stamped as backtests.
- `calibrate.py` — reads all of the above plus the Singapore and Kuala Lumpur
  backtests in `predictions/`, and prints the two tables the limit was set from:
  trend error against each race's end-of-race trend, and forecast skill of the
  calls, both by band of standard error.
- `skill_by_threshold.json` — what `calibrate.py` found for a line at each value.

The two scripts are a record of the measurement, kept so it can be re-run, not
maintained tools; they are run from the repository root.

These ledgers went into the repository because the ones behind the 5 October
trend-prior result were left in a scratch directory and were gone a week later.
