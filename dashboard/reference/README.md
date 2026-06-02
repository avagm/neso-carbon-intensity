# Reference figures

The three figures a team member produced for the topology comparison, which set
the visual direction for this dashboard. The dashboard reproduces all three from
the same underlying data and extends them with the ETYS 2000-bus series.

To keep the originals with the project, drop the PNGs the team member shared into
this folder as:

```
reference/team_01_validation_scatter.png
reference/team_02_duration_curve.png
reference/team_03_top_carriers.png
```

(Claude cannot write the shared image binaries from the chat, so this is a manual
copy. The descriptions below record what each one is so the mapping is clear even
before the files are added.)

## The three figures

1. **Validation, PyPSA vs NESO scatter.** Three density scatters (Copperplate,
   Zonal 17-bus, Reduced 32-bus) of hourly modelled intensity against NESO
   actual for 2023, each annotated with R, RMSE, and bias. Headline: Reduced
   32-bus R 0.936, RMSE 28.3, bias -8.9 gCO2 per kWh.
2. **Intensity duration curve, 2023.** Carbon intensity sorted from highest to
   lowest against percent of hours exceeded, NESO actual against the three
   modelled topologies.
3. **Top carriers by annual generation, GB 2023.** Horizontal bars of annual
   generation per carrier for each topology, coloured by carbon class (green
   zero, amber low, red high).

## Where the dashboard reproduces them

| Team figure | Dashboard view | Notes |
|---|---|---|
| 1. Validation scatter | Validation, "Scatter vs NESO" | Same R / RMSE / bias; small multiples across all four topologies including ETYS. |
| 2. Intensity duration curve | Validation, "Intensity duration curve" | Adds the ETYS curve, whose elevated high-percentile floor is the congestion signature. |
| 3. Top carriers | Validation, "Top carriers by generation" | Per-topology, same carbon-class colouring. |

## preview/

Static PNGs rendered by `analysis/render_dashboard_gallery.py` directly from the
dashboard's figure code and theme, so they are faithful to what the live app
draws. They are a quick way to see the dashboard without launching Streamlit, and
double as the visual QA artefacts for the build.

| File | View |
|---|---|
| `01_overview_timeseries.png` | Overview hourly series, one week, with NESO-style bands |
| `02_pie_technology.png` | Time-slice explorer, generation mix by technology |
| `03_pie_carbon_class.png` | Time-slice explorer, generation mix by carbon class |
| `04_calendar_heatmap.png` | Calendar heatmap (hour of day by date), Reduced 32-bus, full year |
| `05_map_etys_proxy.png` | Per-bus points map (static proxy without basemap tiles) |
| `06_validation_scatter.png` | Validation scatter, Reduced vs NESO |
| `07_duration_curve.png` | Intensity duration curve, all series |
| `08_top_carriers.png` | Top carriers by generation, ETYS |
| `09_neso_region_choropleth.png` | NESO region choropleth, ETYS (the live app draws this interactively on a basemap) |
| `10_catchment_fill.png` | Voronoi catchment fill, Reduced and ETYS (the point map filled in) |

Regenerate with:

```
python analysis/render_dashboard_gallery.py
```
