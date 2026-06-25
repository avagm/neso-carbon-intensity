#  Visualisation — Quick Notes

## To run
```bash
conda activate xyz
cd xyz
python generation_mix.py
python validation_A.py
```
Figures go into `figures_mix/` and `figures_A/`

---

## Generation mix figures

**mix1** — stacked bar, zero/low/high carbon TWh per model. Copperplate uses less gas because it ignores grid limits. Network models need ~8 TWh more gas to cover what renewables can't reach.

**mix2** — top 10 carriers side by side. Wind offshore biggest in all (~62 TWh). Gas CCGT jumps ~8 TWh when you add a network. Coal tiny but highest emission factor by far.

**mix3** — emission factors per carrier. Coal 937, OCGT 651, CCGT 394. Explains why even a little coal causes big CI spikes.

**mix4** — total CO2 per model. Copperplate 37.3 Mt, both network models 40.2 Mt. Same resolution = same total, just distributed differently spatially.

---

## Validation figures

**A1** — scatter vs NESO actual. All models good (R ~0.93) but all underestimate. 32-bus best (RMSE 28.3 vs 38 for copperplate).

**A2** — Taylor diagram, all three models on one plot. 32-bus closest to NESO reference point. All slightly overestimate variability.

**A3** — duration curve. Models fine in the middle. Biggest gap at low-CI hours (high wind) — copperplate thinks grid is cleaner than it is.

**A4** — monthly means. Seasonal pattern right. All models 10–30 units below NESO most months. May closest.

**A5** — Bland-Altman. Bias is flat across CI range (not getting worse at extremes). 32-bus tightest limits.

**A6** — RMSE and bias by month. Worst in summer (variable renewables). 32-bus consistently best, most stable bias year-round.

---

## Key numbers

| | Copperplate | Zonal 17 | 32-bus |
|---|---|---|---|
| RMSE | 38.0 | 36.0 | **28.3** |
| R | 0.928 | 0.923 | **0.936** |
| Bias | −18.6 | −7.4 | −8.9 |
| CO₂ | 37.3 Mt | 40.2 Mt | 40.2 Mt |

NESO actual mean: **152.1 gCO₂/kWh**
