# GB Carbon Intensity dashboard

An interactive Streamlit dashboard over the PyPSA-GB topology-comparison
dataset: modelled hourly carbon intensity of the GB electricity system for 2023
on the Zonal 17-bus, Reduced 32-bus, copperplate, and ETYS 2000-bus topologies,
shown against the NESO national actual in the NESO visual language.

This is a draft/mockup intended for the NESO academic deliverable. The data it
reads is produced by the toolkit scripts in the repository root; the dashboard
itself does not touch a PyPSA network or a solver, only the pre-computed CSVs.

## Views

Views appear in the sidebar in this order:

| View | What it shows |
|---|---|
| **Overview** | Headline annual-mean intensities per topology vs NESO, and the hourly series for any window with NESO-style intensity bands. |
| **Time-slice explorer** | Generation or emissions mix as a pie plus a stacked area, sliceable to any day, week, month, or custom range, grouped by technology, carbon class (zero / low / high), or renewable status. Headline renewable share, zero-carbon share, and mean intensity for the window. |
| **Geographical map** | Three styles. **NESO regions** (default): the 14 GSP-group regions coloured by generation-weighted regional intensity, every region filled (a region with no modelled bus takes the nearest bus's value). **Points**: one marker per bus, area by generation, colour by intensity. **Catchment areas**: the point map filled in, a Voronoi tessellation where every location is coloured by its nearest bus, a few dozen areas on the coarse networks (with plain-English names from `catchment_names.csv`) and a 666-cell mosaic on ETYS. Regions and the coarse catchments are interactive: hover for intensity and top carriers, click (or use the Focus area box) for a generation-mix pie and headline numbers, with a ranking table (most to least carbon intensive) under the map. ETYS catchments stay a static fill (too many cells to rank or drill). |
| **Calendar heatmap** | Hour-of-day (rows) by calendar date (columns) intensity heatmap on the NESO green-to-red scale, per series, with a model-minus-NESO difference mode. |
| **Validation** | One scrolling page: model-vs-NESO density scatter (with R, RMSE, bias) per topology, the intensity duration curve, and top carriers by annual generation coloured by carbon class. Reproduces the team's three reference figures (see `reference/`). |

## Roadmap

- A time slider on the geographical map, so the regional and catchment maps
  animate or step through the year rather than showing the annual mean. The
  hourly per-bus data this needs is not yet extracted (`buses_with_ci.csv` is an
  annual mean); a per-bus hourly extract would feed it.

## Running it

The dashboard needs only a plotting stack (no PyPSA, no solver). Two options.

Reuse the project conda env (streamlit is already installed there):

```
conda activate pypsa-gb
cd C:\Users\user\projects\personalPypsa
streamlit run dashboard/app.py
```

Or a clean standalone environment:

```
python -m venv dashboard/.venv
dashboard\.venv\Scripts\activate
pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```

It opens at http://localhost:8501. On this machine the PowerShell conda hook is
blocked by execution policy, so either open the Miniforge Prompt first or invoke
streamlit through the env interpreter directly:

```
C:\Users\user\miniforge3\envs\pypsa-gb\python.exe -m streamlit run dashboard/app.py
```

## Data it reads

The dashboard ships a committed data bundle under `dashboard/data/` (about
25 MB), so a fresh clone runs without regenerating anything. `lib/data.py`
prefers that bundle and falls back to the git-ignored working `results/` tree
when developing locally. Rebuild the bundle with
`python dashboard/build_data_bundle.py` after regenerating any data.

The files below live under `results/2023_topology_default/` and
`results/neso_2023/` in the working tree, and are mirrored into the bundle. Per
topology directory:

| File | Produced by | Used for |
|---|---|---|
| `system_carbon_intensity.csv` | `system_carbon_intensity.py` | overview, heatmap, validation |
| `hourly_generation_by_carrier.csv` | `scripts/extract_dashboard_data.py` | time-slice explorer (generation mix) |
| `hourly_emissions_by_carrier.csv` | `scripts/extract_dashboard_data.py` | time-slice explorer (emissions mix) |
| `generation_by_carrier.csv` | `system_carbon_intensity.py` | validation top-carriers bar |
| `buses_with_ci.csv` | `scripts/extract_dashboard_data.py --per-bus` | geographical map (points) |
| `bus_carrier_generation.csv`, `bus_carrier_emissions.csv` | `scripts/extract_dashboard_data.py --per-bus` | per-catchment generation-mix pie + hover |
| `neso_region_intensity.csv` | `scripts/aggregate_neso_regions.py` | NESO region choropleth |
| `region_carrier_generation.csv`, `region_carrier_emissions.csv` | `scripts/aggregate_neso_regions.py` | per-region generation-mix pie + hover |
| `bus_catchments.geojson` | `scripts/build_bus_catchments.py` | geographical map (catchment areas) |
| `data/topology/<topo>/catchment_names.csv` | hand-curated (committed) | plain-English catchment names (17- and 32-bus) |

`results/neso_2023/national_intensity.csv` is the NESO truth series, and
`data/topology/neso_regions.geojson` (written once by the region aggregation
script) holds the 14 region polygons.

The region aggregation and the catchment polygons are both derived from the
cheap per-bus generation-view data; neither needs HPC, and the maps render in
the browser. To regenerate the region tables and catchments (run the region
script first; it writes the shared region geometry the catchment script reuses):

```
python scripts/aggregate_neso_regions.py ^
  --buses results/2023_topology_default/etys_2000bus/buses_with_ci.csv ^
  --out-dir results/2023_topology_default/etys_2000bus --label "ETYS 2000-bus"
python scripts/build_bus_catchments.py ^
  --buses results/2023_topology_default/etys_2000bus/buses_with_ci.csv ^
  --out-dir results/2023_topology_default/etys_2000bus --label "ETYS 2000-bus"
```

If the per-carrier or per-bus files are missing for a topology, regenerate them:

```
python scripts/extract_dashboard_data.py ^
  --network ../PyPSA-GB-default/resources/network/Historical_2023_zonal_year_solved.nc ^
  --out-dir results/2023_topology_default/zonal_17bus ^
  --label "Zonal 17-bus" --per-bus ^
  --pypsa-gb-commit 074ea25ec0ca83ecfd3703b2af3a820a25518c50
```

Repeat for `reduced_32bus`, `reduced_32bus_copperplate` (no `--per-bus`), and
`etys_2000bus`.

## Layout

```
dashboard/
├── app.py                 # Streamlit entrypoint: sidebar router + the five views
├── build_data_bundle.py   # copy the files the dashboard reads into dashboard/data/
├── lib/
│   ├── data.py            # cached CSV loaders, topology registry, NESO alignment
│   ├── carriers.py        # carrier -> technology / carbon-class / renewable maps + colours
│   └── theme.py           # NESO-style colour scale, index bands, Plotly layout defaults
├── tests/
│   └── test_map_interactions.py  # AppTest checks for the map + heatmap views
├── reference/
│   ├── README.md          # the team's three reference figures and where the dashboard reproduces them
│   └── preview/           # static PNG previews rendered by analysis/render_dashboard_gallery.py
├── requirements.txt
└── README.md              # this file
```

## A note on ETYS

The ETYS 2000-bus series is taken at the interior point of its barrier solve (HPC
job 2899855). Its annual mean (189 gCO2/kWh) is validated as the genuine
congestion signature of full transmission detail (see
`deliverables/etys_data_validation.md`); it carries a +0.36% generation-demand
smear and two Northern Ireland imports on the NESO Other fallback, and should be
replaced by the tightened re-solve when that lands.
