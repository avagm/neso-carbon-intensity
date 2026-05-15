# Week 2 — 2023 full-year, 17-bus vs 32-bus, NESO-aligned

![Headline summary](headline_summary.png)

## Headline result

| Series | Annual mean (gCO2 / kWh) | Bias vs NESO | RMSE | MAE | Pearson r |
|---|---|---|---|---|---|
| NESO 2023 actual    | 152.1 | -                     | -     | -    | -    |
| Zonal 17-bus uplift | 155.3 | +3.6 (+2.4 percent)   | 100.6 | 82.3 | 0.13 |
| Reduced 32-bus uplift | 165.2 | +13.4 (+8.8 percent) |  91.1 | 73.7 | 0.14 |

Aligned on 8713 common hourly snapshots out of 8760 in 2023.

## What was done

### Task 1: real-world variables
- **Transmission losses (8 percent).** Applied as a uniform demand-side
  uplift: every load is multiplied by `1 / (1 - 0.08) = 1.087` before
  solve. This matches NESO's convention that the published intensity is
  per kWh **delivered**.
- **Biomass emission factor (120 gCO2 / kWh electrical).** Applied at
  post-processing in `Scripts/carbon_intensity.py` via
  `NESO_FACTORS_G_PER_KWH`. The override is electrical (sent-out) and
  bypasses the thermal-to-electrical efficiency conversion that the
  default code applies. Covers `biomass`, `Bioenergy`, `biogas`,
  `landfill_gas`, `sewage_gas`, `advanced_biofuel`, since NESO's
  single "Biomass" 120 covers all biogenic combustion.
- PyPSA-GB `carrier_definitions.py` is **not** modified — the LP
  dispatch uses upstream defaults, only the post-processing accounting
  deviates. Keeps the clone clean.

### Task 2: 17-zone vs 32-bus, full year
- Scenarios `Historical_2023_zonal_year` and
  `Historical_2023_reduced_year` added to PyPSA-GB's
  `config/scenarios.yaml` (both 2023-01-01 to 2023-12-31, 8760 hourly
  snapshots).
- HiGHS solver throughout. Wall times on 12700KF / 32 GB:

  | Step | Zonal | Reduced |
  |---|---|---|
  | Baseline solve | 39:32 | 44:40 |
  | Uplift re-solve | 34:30 | 44:33 |

- 8760 snapshots, ~80-190 MB output NetCDFs per scenario, ~9-16 GB peak
  RAM in solve.
- Annual total generation: 272.5 TWh (Zonal), 273.0 TWh (Reduced).
  Within 1 percent of GB's actual 2023 consumption.

### Task 3: pipeline
Single-module pipeline in `Scripts/`:
- `carbon_intensity.py` — post-processor. Reads a solved `.nc`, writes
  three standard CSVs (`system_summary`, `generation_intensity`,
  `consumption_intensity`). `--neso-overrides` flag toggles the
  biomass-class override.
- `solve_with_uplift.py` — driver: load a solved network, scale loads
  by the loss factor, re-solve. Writes `manifest.json` with input SHA,
  loss fraction, solver wall time.
- `visualise.py` — accepts any number of `LABEL=PATH` pairs and an
  optional NESO CSV. Writes a fixed plot pack (time series, monthly
  bar, duration curve, diurnal, scatter) and `summary_stats.csv`.
- `make_headline.py` — single composite figure for slide use.
- `pull_neso_2023.py` — NESO API puller (already used to populate
  `Data/`).

The four Week-1 duplicate scripts in `Scripts/` are not removed in this
commit. Their replacement is the new `carbon_intensity.py`; the team
should agree on the deletion before pushing it.

## Read

- **Annual mean is fit well.** Zonal lands within 2.4 percent of NESO.
  The Week 1 -33.5 gCO2 / kWh bias is essentially closed: the biomass
  override caught 457 generators that PyPSA-GB priced at zero, and the
  demand uplift forced the LP to dispatch ~8 percent more.
- **Hourly correlation is weak (r ~0.13).** The model matches the
  long-run average but not the hour-by-hour shape. Expected for an LP
  without unit commitment, ramp limits, or forced outages.
- **Topology effect is ~10 gCO2 / kWh on annual mean.** Reduced's line
  constraints push dispatch toward a slightly higher-emission mix more
  often, raising the mean but dampening some zero-CI excursions that
  drive Zonal's RMSE. The 17 vs 32 difference is a real signal, not
  noise.
- **Diurnal panel is the most interesting diagnostic.** Both PyPSA
  topologies show pronounced morning and evening peaks that NESO does
  not — classic LP-without-UC signature.

## Known gaps

- **Drax / wood pellet appears absent** from PyPSA-GB's 2023 fleet on
  both topologies: zero generators carry the formal `biomass` or
  `Bioenergy` carriers. The override caught ~11 TWh of dispatched
  biogenic generation but cannot replace ~15-17 TWh of missing
  Drax-scale wood-pellet generation. Worth investigating before
  quoting absolute numbers in a writeup.
- `waste_to_energy` 19.65 TWh dispatched at PyPSA's 200 gCO2 / kWh vs
  NESO's "Other" 300 gCO2 / kWh.
- `EU_import` flat 200 gCO2 / kWh vs NESO's per-cable factors (Dutch
  474, French 53, Irish 458).
- Hourly resolution against NESO's half-hourly; NESO is resampled to
  hourly for the comparison.
- DC linear flow, no reactive power, no gCO2 / kVArh.

Full coverage table in `Docs/constraints_ticked.md`.

## Files in this folder

```
Results/week 2/
├── README.md                          (this file)
├── headline_summary.png               (2x2 composite, slide-ready)
├── system_summary_zonal_17bus.csv     (8760 hourly: emissions, gen, CI)
├── system_summary_reduced_32bus.csv   (same shape)
├── summary_stats.csv                  (mean, bias, RMSE, MAE, r per series)
└── plots/
    ├── system_intensity_timeseries.png
    ├── monthly_mean_bar.png
    ├── intensity_duration_curve.png
    ├── diurnal_profile.png
    └── pypsa_vs_neso_scatter.png
```

Inputs are in `Data/`; pipeline scripts in `Scripts/`; methodology
documents in `Docs/`.

## Reproduce

```
# 1. PyPSA-GB scenarios (config/scenarios.yaml on carbon-intensity-work):
#      Historical_2023_zonal_year
#      Historical_2023_reduced_year

# 2. Snakemake build + baseline solve, ~40-45 min each
snakemake -j 4

# 3. Apply demand uplift and re-solve
python Scripts/solve_with_uplift.py \
    --in  ../PyPSA-GB/resources/network/Historical_2023_zonal_year_solved.nc \
    --out results/Historical_2023_zonal_year_uplift/network.nc --loss 0.08
python Scripts/solve_with_uplift.py \
    --in  ../PyPSA-GB/resources/network/Historical_2023_reduced_year_solved.nc \
    --out results/Historical_2023_reduced_year_uplift/network.nc --loss 0.08

# 4. Post-process with NESO biomass override
python Scripts/carbon_intensity.py \
    --network results/Historical_2023_zonal_year_uplift/network.nc \
    --out-dir results/Historical_2023_zonal_year_uplift --neso-overrides
python Scripts/carbon_intensity.py \
    --network results/Historical_2023_reduced_year_uplift/network.nc \
    --out-dir results/Historical_2023_reduced_year_uplift --neso-overrides

# 5. Visualise the comparison
python Scripts/visualise.py \
    --series "Zonal 17-bus=results/Historical_2023_zonal_year_uplift/system_summary.csv" \
    --series "Reduced 32-bus=results/Historical_2023_reduced_year_uplift/system_summary.csv" \
    --neso   Data/neso_2023_national_intensity.csv \
    --out-dir "Results/week 2"

# 6. Headline composite
python Scripts/make_headline.py \
    --zonal   "Results/week 2/system_summary_zonal_17bus.csv" \
    --reduced "Results/week 2/system_summary_reduced_32bus.csv" \
    --neso    Data/neso_2023_national_intensity.csv \
    --out     "Results/week 2/headline_summary.png"
```

PyPSA-GB commit `074ea25e` on `carbon-intensity-work`. NESO factor
snapshot fetched 2026-05-14.
