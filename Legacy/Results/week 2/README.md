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
- **Transmission + distribution losses (8 percent total).** Applied as
  a uniform demand-side uplift: every load is multiplied by
  `1 / (1 - 0.08) = 1.087` before solve. NESO publishes intensity
  per kWh **delivered**, so this matches its denominator.
- **Biomass-class emission factor (120 gCO2 / kWh electrical).**
  Applied at post-processing via `NESO_FACTORS_G_PER_KWH` in
  `Scripts/week 2/carbon_intensity.py`. Covers `biomass`, `Bioenergy`,
  `biogas`, `landfill_gas`, `sewage_gas`, `advanced_biofuel` (NESO's
  single "Biomass" 120 spans all biogenic combustion).
- PyPSA-GB `carrier_definitions.py` is **not** modified.

### Task 2: 17-zone vs 32-bus, full year
- Scenarios `Historical_2023_zonal_year` and
  `Historical_2023_reduced_year` (both 2023-01-01 to 2023-12-31, 8760
  hourly snapshots).
- HiGHS on 12700KF / 32 GB:

  | Step | Zonal | Reduced |
  |---|---|---|
  | Baseline solve | 39:32 | 44:40 |
  | Uplift re-solve | 34:30 | 44:33 |

- Annual generation: 272.5 TWh (Zonal), 273.0 TWh (Reduced). Within
  1% of GB's actual 2023 consumption.

### Task 3: pipeline
Single-module pipeline in `Scripts/week 2/`:
- `carbon_intensity.py` — post-processor. Writes
  `system_summary.csv`, `generation_intensity.csv`,
  `consumption_intensity.csv`. `--neso-overrides` flag toggles the
  biomass-class override.
- `solve_with_uplift.py` — loss-uplift driver. Writes `manifest.json`.
- `visualise.py` — plot pack: time series, monthly bar, duration
  curve, diurnal. Writes `summary_stats.csv`.
- `make_headline.py` — 1x2 composite for slides.
- `pull_neso_2023.py` — NESO API puller (populates `Data/`).

Inputs in `Data/`; methodology in `Docs/`.
