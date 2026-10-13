"""Every lap of every recording: three measures of fuel/wear collinearity beside the fit they describe."""
import json, sys
from pathlib import Path
from pitwall.feed.replay import read_events
from pitwall.laps import LapCollector, filter_laps
from pitwall.models import fit_degradation, fit_pace, load_degradation, load_history, neutralisation_index

TAG = "tyre age and race lap"
history = load_history(Path("data/history/safety_car.json"))
prior = fit_degradation(load_degradation(Path("data/history/degradation.json")), history=neutralisation_index(history))
name = sys.argv[1]
collector = LapCollector(); seen = set(); rows = []
for event in read_events(Path("data/raw") / name):
    collector.apply(event)
    state = collector.state
    lap = state.lap - 1
    if lap < 8 or lap in seen:
        continue
    seen.add(lap)
    clean, _ = filter_laps(collector.laps)
    fit = fit_pace(clean, prior=prior, circuit=state.circuit, total_laps=state.total_laps)
    if fit is None:
        continue
    stints = {}
    for l in clean:
        stints.setdefault(l.driver, set()).add(l.stint)
    rows.append({
        "lap": lap, "total": state.total_laps, "n": fit.n_laps,
        "trend": fit.race_lap_coef, "per_kg": fit.seconds_per_lap_from_fuel / fit.burn_per_lap_kg if fit.burn_per_lap_kg else None,
        "pooled": fit.age_lap_correlation, "determination": fit.lap_determination,
        "se": fit.trend_se, "se_kg": (fit.trend_se / fit.burn_per_lap_kg) if fit.burn_per_lap_kg else None,
        "resid": fit.residual_std,
        "other": [r[:50] for r in fit.unusable_reasons if TAG not in r],
        "multi": sum(1 for s in stints.values() if len(s) > 1), "drivers": len(stints),
    })
out = Path("reports/collinearity/fits")
(out / (name + ".json")).write_text(json.dumps({"circuit": collector.state.circuit, "rows": rows}))
print(name, collector.state.circuit, len(rows), "laps")
