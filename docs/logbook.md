# Logbook

Running notes on what was built, what broke, and what the data taught me.

---

## 2026-07-26 (later) — Clean-lap filter

Phase 2 begins. Built lap extraction (`laps/records.py`) and the clean-lap filter
(`laps/clean.py`), then ran both against the Hungary recording.

**How the feed signals a completed lap.** Worth writing down, because I guessed wrong first and
the probe returned nothing. `NumberOfLaps` and `LastLapTime` arrive *together* in one `TimingData`
message, and `NumberOfLaps` is the lap now being **started** — so the time belongs to
`NumberOfLaps - 1`:

    {'NumberOfLaps': 2, 'LastLapTime': '1:26.103'}   # lap 1 took 86.103s
    {'NumberOfLaps': 3, 'LastLapTime': '1:25.307'}   # lap 2 took 85.307s

The 2026 grid also does not use the numbers I assumed — Norris is #1, not #4. Always read the
`DriverList` rather than hardcoding.

**Result: 881 clean laps of 1,405 (62.7%).** The exclusion counts are what convinced me the filter
is right, more than the headline number:

| Reason | Count | Cross-check |
|---|---|---|
| Traffic (<2.0 s behind) | 429 | Hungaroring, 22 cars, DRS trains — expected to dominate |
| Entered pits | 92 | 47 stops recorded, so ~2 laps affected per stop ✓ |
| Left pits | 45 | ≈ one per stop ✓ |
| Neutralised | 34 | the lap-56 VSC ✓ |
| Lap 1 | 22 | exactly the grid size ✓ |
| Implausible | 2 | the cool-down and garage laps ✓ |

**Bug caught by a sanity check, not a test.** The out-lap rule was `tyre_age <= 1`, which also
discarded the first *flying* lap of every stint — a real racing lap, and the most useful one for
pinning the intercept of a degradation curve. Cost: 38 usable laps in one race. Now `== 0`, with a
regression test.

**The signal is there.** Median lap time by tyre age on the hard, clean laps only:

    age  0-4   5-9  10-14  15-19  20-24  25-29  30-34  40-44
        84.85 85.32  85.60  85.78  86.04  86.03  86.32  87.90

Monotonic, which is what degradation should look like.

**But do not read the raw slopes as tyre degradation yet.** Crude fits give SOF +0.060, MED +0.026,
HAR +0.051 s/lap — and medium's *absolute* times (86.9–88.2 s) sit above both other compounds,
which is nonsense for a mid-range tyre. The explanation is fuel: mediums ran early on a heavy car,
hards ran late on a light one. Fuel burn is worth roughly −0.05 s/lap, the same order as the effect
being measured, and it is currently pushing in the opposite direction. So these numbers are
confounded and every one of them understates true degradation.

That is the next job: fuel correction, then per-compound fits with circuit priors. The filter was
the prerequisite; the decomposition is what makes the output mean anything.

Also: `slots=True` on a dataclass replaces class attributes with descriptors, so
`CleanLapConfig.traffic_threshold` is a `member_descriptor`, not `2.0`. Read defaults off an
instance. The tests passed while the CLI crashed.

---

## 2026-07-26 — First full race captured and parsed

Recorded the Hungarian Grand Prix unattended and folded it through the Phase 1 pipeline. This is
the first time the engine has seen a real race rather than a synthetic fixture.

**The capture:** 11.9 MB, 76,979 events across 17 topics, from a single unbroken 157-minute
connection (13:30–16:07). The race ran 14:00–16:00, so the whole thing is inside one session with
buffer either side. `TimingData` dominates at 69,710 events — 91% of the feed.

**What the reducer got right, unprompted:**

- Final classification at lap 70/70: Norris from Verstappen (+15.080) and Antonelli
- Lapped cars correctly marked (`1L`, `2L`), Piastri correctly flagged retired
- 47 pit stops across the field, three compounds, stint transitions tracked per car
- Track status timeline including the VSC deployed on lap 56 and ending on lap 57
- Weather: 31.3 °C air, 47.0 °C track, no rain

Folding all 76,979 events takes 5.5 s — roughly 14k events/sec, single-threaded and unoptimised.
That is comfortably inside any sane live budget, so the simulation, not the ingest, will be the
thing to optimise later.

**Bug this surfaced: 2026 has 22 cars, not 20.** The CLI hardcoded a 20-row limit, silently
truncating Pérez and Bottas in the Cadillacs. Nothing errored — the screen just looked complete
and wasn't. A good reminder that the dangerous failures in this project are the plausible-looking
ones, which is the same reason the delta-merge code is the most heavily tested module here.

**The supervisor's backoff earned its keep.** When the session ended at 16:07 the feed kept
accepting connections but returned only a ~92 KB snapshot. The idle detection caught it and
stepped 30s → 60s → 120s → 240s → 300s, so the hour after the race cost 12 reconnects instead of
roughly 40. Worth having built the day before.

**Preview of Phase 2.** Yesterday's qualifying snapshot already showed why clean-lap filtering is
the first real job: Piastri's "last lap" was 5:48 (a cool-down lap) and Gasly's was 20:23 (sitting
in the garage after Q1 elimination). Both are faithfully parsed and both would wreck a degradation
fit. The race adds more of the same — in-laps, out-laps, VSC laps, and traffic-bound laps all need
excluding before anything can be fitted.

Next: the clean-lap filter, then per-compound degradation with circuit priors.
