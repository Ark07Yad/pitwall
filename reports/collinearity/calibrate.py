"""Where to put the line on the trend's standard error: by trend error, and by the calls made from it."""
import json, statistics
from collections import defaultdict
from pathlib import Path
from pitwall.feed.replay import read_events
from pitwall.ledger.score import finishing_positions, score_predictions
from pitwall.state.reducer import RaceStateReducer

R = Path("reports/collinearity"); F = R / "fits"
BANDS = [(0, .005), (.005, .010), (.010, .015), (.015, .020), (.020, .030), (.030, .050), (.050, 9)]
lab = lambda lo, hi: f"{lo:.3f}-{hi:.3f}" if hi < 9 else f"over {lo:.3f}"

pts = []
for f in sorted(F.glob("*.json")):
    rows = json.loads(f.read_text())["rows"]
    final = next((r for r in reversed(rows) if not r["other"] and r["per_kg"] is not None and r["pooled"] < 0.6), None)
    if not final: continue
    for r in rows:
        if r["other"] or r["per_kg"] is None or r["lap"] > final["lap"] - 5 or r["se_kg"] is None: continue
        pts.append({**r, "err": abs(r["per_kg"] - final["per_kg"])})
print(f"1. trend against the race's own end-of-race trend - {len(pts)} laps passing every other guard\n")
print(f"   {'trend se, s/kg':<16} {'laps':>5} {'median error':>13} {'error > 0.02 s/kg':>19}")
for lo, hi in BANDS:
    sel = [p["err"] for p in pts if lo <= p["se_kg"] < hi]
    if sel: print(f"   {lab(lo, hi):<16} {len(sel):>5} {statistics.median(sel):>12.4f}  {sum(e > .02 for e in sel):>6} ({100*sum(e > .02 for e in sel)/len(sel):>3.0f}%)")

plan = json.loads((R / "plan.json").read_text())
SETS = [(R / f"collinearity-{t}.jsonl", s["recording"]) for t, s in plan.items()]
SETS += [(Path("predictions/2026-singapore-gp-backtest.jsonl"), "2026-singapore-archive.txt"),
         (Path("predictions/2026-bahrain-gp-in-malaysia-backtest.jsonl"), "2026-r16-race.txt")]
cells = []
for path, rec in SETS:
    red = RaceStateReducer()
    for e in read_events(Path("data/raw") / rec): red.apply(e)
    fin = finishing_positions(red.state)
    stats = {r["lap"]: r for r in json.loads((F / (rec + ".json")).read_text())["rows"]}
    by = defaultdict(list)
    for r in map(json.loads, path.open()): by[r["lap"]].append(r)
    cells += [(rs, fin, stats[lap]) for lap, rs in by.items() if lap in stats and stats[lap]["se_kg"] is not None]
def skill(m, b): return 100 * (1 - m / b) if b > 0 else float("nan")
def agg(sel):
    n = t3 = b3 = pt = bp = pe = be = 0.0; dec = tot = 0
    for rs, fin, st in sel:
        c = score_predictions(rs, fin)
        n += c.n; t3 += c.brier_top3*c.n; b3 += c.baseline_top3*c.n; pt += c.brier_points*c.n; bp += c.baseline_points*c.n
        pe += c.position_error*c.n; be += c.baseline_position_error*c.n; dec += sum(r["decisive"] for r in rs); tot += len(rs)
    return dict(cells=len(sel), rows=int(n), top3=round(skill(t3, b3), 1), points=round(skill(pt, bp), 1), gap=round(pe/n - be/n, 2) if n else None, decisive=round(100*dec/tot) if tot else None)
print(f"\n2. the calls themselves - {len(cells)} (race, lap) cells, {sum(len(c[0]) for c in cells)} rows, {len(SETS)} races\n")
print(f"   {'trend se, s/kg':<16} {'cells':>5} {'rows':>5} {'top-3 skill':>12} {'points skill':>13} {'pos err vs baseline':>20} {'decisive':>9}")
for lo, hi in BANDS:
    sel = [c for c in cells if lo <= c[2]["se_kg"] < hi]
    if sel:
        a = agg(sel); print(f"   {lab(lo, hi):<16} {a['cells']:>5} {a['rows']:>5} {a['top3']:>+11.1f}% {a['points']:>+12.1f}% {a['gap']:>+20.2f} {a['decisive']:>8}%")
print("\n3. a line at each value: what is kept, what is refused")
out = {}
for thr in (0.010, 0.015, 0.020, 0.025, 0.030):
    k = agg([c for c in cells if c[2]["se_kg"] <= thr]); d = agg([c for c in cells if c[2]["se_kg"] > thr])
    out[str(thr)] = {"keep": k, "refuse": d}
    print(f"   se <= {thr:.3f}: keep {k['cells']:>3} cells top-3 {k['top3']:>+6.1f}% gap {k['gap']:>+5.2f}   |   refuse {d['cells']:>3} cells top-3 {d['top3']:>+7.1f}% gap {d['gap']:>+5.2f} decisive {d['decisive']}%")
m = agg([c for c in cells if c[2]["determination"] <= 0.95]); n_ = agg([c for c in cells if c[2]["determination"] > 0.95])
print(f"   (multiple R <= 0.95, for comparison: keep {m['cells']} cells {m['top3']:+.1f}%  |  refuse {n_['cells']} cells {n_['top3']:+.1f}%)")
(R / "skill_by_threshold.json").write_text(json.dumps(out, indent=1) + "\n")

print("\n4. across every lap of twenty recordings")
tot_old = tot = 0; rows_out = []
for f in sorted(F.glob("*.json")):
    race = json.loads(f.read_text()); rows = [r for r in race["rows"] if not r["other"]]
    old = {r["lap"] for r in rows if r["pooled"] <= 0.85}
    for thr in (0.020,):
        new = {r["lap"] for r in rows if r["se_kg"] is not None and r["se_kg"] <= thr}
    tot_old += len(old); tot += len(new)
    rows_out.append((f.name.replace(".txt.json", ""), race["circuit"], len(old), len(new), min(old) if old else None, min(new) if new else None, len(new - old)))
print(f"   accepted by the guard as it is: {tot_old}   by se <= 0.020 s/kg: {tot}")
print(f"   {'race':<26} {'circuit':<18} {'old':>4} {'new':>4}  first accepted lap    newly accepted")
for name, circ, a, b, fo, fn, gained in rows_out:
    print(f"   {name:<26} {circ:<18} {a:>4} {b:>4}  {str(fo):>4} -> {str(fn):<4}          {gained}")
