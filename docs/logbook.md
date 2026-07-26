# Logbook

Running notes on what was built, what broke, and what the data taught me.

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
