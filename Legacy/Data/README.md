# Data

- `neso_2023_national_intensity.csv` — half-hourly NESO Carbon Intensity API national series for 2023 (17 430 rows, columns `from`, `to`, `forecast`, `actual`, `index`). Used as the validation truth.
- `neso_2023_factors.json` — snapshot of NESO's per-fuel emission factor table (`/intensity/factors`, gCO2/kWh). Used to set the biomass override (120) and to document the gas / coal / interconnector gaps.
- `pypsa_2023_zonal_input.nc` — PyPSA-GB built (unsolved) network for the Zonal (17-zone) 2023 scenario. The full dataset PyPSA was fed: hourly demand, generator capacities + carriers, lines, links, storage. Used as the 17-bus input to the topology comparison.
- `pypsa_2023_reduced_input.nc` — same as above for the Reduced (32-bus) 2023 scenario. Used as the 32-bus input.
