# Results (2023)

Outputs this toolkit produced for 2023: Zonal 17-bus, Reduced 32-bus, and the
Reduced soft-copperplate variant. All values are gCO2 per kWh.

## Heatmap dataset

- `heatmap_input.csv`: hourly UTC table with NESO actual, the three modelled
  series, and their differences, over the 8713 hours all four cover.
- `heatmap_pivot_*.csv`: each series as a date-by-hour grid.
- `assembly_manifest.json`: alignment and per-series stats.

## Per topology

`zonal_17bus/`, `reduced_32bus/`, `reduced_32bus_copperplate/`:

- `system_carbon_intensity.csv`: hourly emissions, generation, intensity.
- `generation_by_carrier.csv`: annual totals per carrier.
- `manifest.json`: run provenance.
- `annual_mean_by_bus.csv`, `nodal_manifest.json`: per-bus means (Zonal and
  Reduced only).

## NESO reference

`neso_2023/`: the national actual series and the factor snapshot, from
`pull_neso_2023.py`. Re-pull and check the date before quoting factors.
