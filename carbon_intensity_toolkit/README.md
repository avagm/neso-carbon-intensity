# Carbon intensity toolkit

A small set of Python scripts that compute the hourly carbon intensity of the
GB electricity system from [PyPSA-GB](https://github.com/andrewlyden/PyPSA-GB)
and compare it against the NESO published actual series. The work was done for
calendar year 2023 on two PyPSA-GB network topologies (Zonal 17-bus and Reduced
32-bus), with a transmission-unconstrained copperplate variant and a full ETYS
(approximately 2000-bus) extension solved on HPC.

The scripts post-process solved networks. They do not build the base network or
run the main dispatch optimisation; that is done by PyPSA-GB itself
(`snakemake`). The one exception is `solve_etys_hpc.py`, which re-solves an
already-built ETYS network on a large-memory node. Everything here reads the
NetCDF files PyPSA-GB writes and turns them into carbon intensity series,
comparison datasets, and map geometry.

## What it computes

For each hourly snapshot the system carbon intensity is

    CI = system_emissions / system_generation * 1000     gCO2 per kWh

with emissions in tonnes CO2 and generation in MWh. Emissions are dispatched
generation multiplied by the NESO published emission factor for each carrier,
in gCO2 per kWh sent out. The factors are applied directly rather than derived
from the PyPSA-GB carrier definitions, because PyPSA-GB assigns a uniform
placeholder efficiency of 0.5 to every thermal carrier, which makes its implied
electrical factors unreliable. The factor table and its sources are in
`neso_factors.py` and in the methodology document.

A system-wide intensity is the only carbon intensity quantity that is directly
comparable between networks with different bus counts, because a 17-bus and a
32-bus network do not share a bus set. It is therefore the headline output. A
per-bus decomposition (`nodal_carbon_intensity.py`) is available for mapping
within a single topology.

## Pipeline

The stages run in order. Stage 2 (the base Zonal and Reduced solve) is PyPSA-GB
itself; every other stage is a script in this folder.

| Stage | Script | Purpose |
|---|---|---|
| 1. NESO reference | `pull_neso_2023.py` | Fetch the NESO national actual series and the live emission-factor snapshot. |
| 2. Solve (base) | (`snakemake` in the PyPSA-GB clone) | Solve the Zonal and Reduced topologies. Not a script here. |
| 3. Copperplate | `solve_softcopperplate.py` (uses `copperplate.py`) | Relax all transmission and re-solve, giving the unconstrained-transmission reference. |
| 4. Carbon intensity | `system_carbon_intensity.py` | Convert one solved network to an hourly system intensity series. Run once per topology. |
| 4b. Per-bus (optional) | `nodal_carbon_intensity.py` | Per-bus generation-view and consumption-view intensity for mapping. |
| 5. Assemble | `build_topology_heatmap_data.py` | Align the topology series and NESO on a common hourly index and write the heatmap dataset. |
| Extension (optional) | `solve_etys_hpc.py` | Re-solve the full ETYS (~2000-bus) network on a large-memory HPC node, as a third comparison point. Needs HPC; see `docs/etys_hpc_runbook.md`. |
| Side utility | `extract_topology_geometry.py` | Dump bus and line coordinates (BNG and WGS84) for plotting the topology on a map. |

## Scripts

| Script | Reads | Writes |
|---|---|---|
| `pull_neso_2023.py` | NESO Carbon Intensity API | `national_intensity.csv`, `factors.json` |
| `copperplate.py` | a PyPSA network `.nc` | soft and/or hard copperplate `.nc` |
| `solve_softcopperplate.py` | solved Reduced network `.nc` | re-solved copperplate network `.nc` |
| `neso_factors.py` | imported by the two intensity scripts | no command-line use |
| `system_carbon_intensity.py` | solved network `.nc` | `system_carbon_intensity.csv`, `generation_by_carrier.csv`, `manifest.json` |
| `nodal_carbon_intensity.py` | solved network `.nc` | `generation_intensity.csv`, `consumption_intensity.csv`, `annual_mean_by_bus.csv`, `nodal_manifest.json` |
| `build_topology_heatmap_data.py` | the intensity CSVs and the NESO CSV | `heatmap_input.csv`, `heatmap_pivot_*.csv`, `assembly_manifest.json` |
| `extract_topology_geometry.py` | solved network `.nc` | `buses.csv`, `lines.csv`, `links.csv`, `manifest.json` |
| `solve_etys_hpc.py` (optional, HPC) | finalized ETYS network `.nc` | solved network `.nc` |

`neso_factors.py` holds the NESO emission factor tables and the function that
attributes a factor to every generator. Both intensity scripts import it, so
the system view and the per-bus view always use the same factors. It is the one
file to edit if a factor changes.

## Setup

The scripts need Python 3.11 or later and the packages in `requirements.txt`. A
conda environment is recommended on Windows, because `pyproj` and `pypsa` pull
geospatial libraries that do not install cleanly from pip wheels there.

```
conda create -n carbon-intensity -c conda-forge python=3.11 pypsa=1.2.0 \
    linopy=0.6.7 pandas numpy requests pyproj netcdf4 highspy
conda activate carbon-intensity
```

The post-processors (`system_carbon_intensity.py`, `nodal_carbon_intensity.py`,
`extract_topology_geometry.py`, `build_topology_heatmap_data.py`,
`pull_neso_2023.py`) read already-solved networks and need no solver. The
re-solve scripts (`solve_softcopperplate.py`, `solve_etys_hpc.py`) need a linear
program solver, either Gurobi (used for the original comparison, academic
licence) or HiGHS (open-source, no licence, solves the same LP).

## Running the pipeline

The commands below assume the solved Zonal and Reduced networks already exist
(produced by `snakemake` in the PyPSA-GB clone) and that all toolkit scripts
are run from inside this folder, so the intra-folder imports resolve. Paths are
illustrative; substitute your own.

Pull the NESO reference series:

```
python pull_neso_2023.py --out-dir out/neso_2023
```

Compute system carbon intensity for each topology:

```
python system_carbon_intensity.py --network path/to/zonal_solved.nc \
    --out-dir out/zonal_17bus --label "Zonal 17-bus"
python system_carbon_intensity.py --network path/to/reduced_solved.nc \
    --out-dir out/reduced_32bus --label "Reduced 32-bus"
```

Build and post-process the copperplate variant:

```
python solve_softcopperplate.py --in path/to/reduced_solved.nc \
    --out out/reduced_32bus_copperplate/network.nc --solver gurobi
python system_carbon_intensity.py \
    --network out/reduced_32bus_copperplate/network.nc \
    --out-dir out/reduced_32bus_copperplate --label "Reduced 32-bus copperplate"
```

Assemble the heatmap dataset:

```
python build_topology_heatmap_data.py \
    --zonal       out/zonal_17bus/system_carbon_intensity.csv \
    --reduced     out/reduced_32bus/system_carbon_intensity.csv \
    --copperplate out/reduced_32bus_copperplate/system_carbon_intensity.csv \
    --neso        out/neso_2023/national_intensity.csv \
    --out-dir     out
```

The full ETYS solve is an optional extension. It runs on an HPC large-memory
node and has its own procedure; see `docs/etys_hpc_runbook.md`.

## Emission factors

The NESO published factors, in gCO2 per kWh of electricity sent out, from the
NESO Carbon Intensity API `/intensity/factors` endpoint. Wind, solar, hydro,
marine, and nuclear are zero at the system boundary.

| Carrier group | Factor (gCO2 per kWh) |
|---|---|
| Wind, solar, hydro, marine, nuclear | 0 |
| Biogenic (biomass, biogas, landfill gas, sewage gas, advanced biofuel) | 120 |
| Gas combined cycle (CCGT) | 394 |
| Gas open cycle (OCGT) | 651 |
| Coal | 937 |
| Oil | 935 |
| Waste to energy | 300 |

Interconnector imports are attributed to the source country: France 53,
Netherlands 474, Ireland 458, Belgium 300 (the NESO "Other" factor, no published
Belgian row), Norway 35, and Denmark 130, all in gCO2 per kWh. The values and
their per-country sources are documented in `neso_factors.py` and in the
methodology. NESO revises the factors periodically, so re-pull with
`pull_neso_2023.py` and check the snapshot date before quoting numbers.

## Outputs and reproducibility

Every post-processing script writes a `manifest.json` (the per-bus script writes
`nodal_manifest.json` so it does not overwrite the system one). Each manifest
records the input network SHA-256, the PyPSA-GB commit, the factor tables, the
headline numbers, and any carriers that did not match the factor table. A result
is therefore reproducible from the solved network plus the pinned PyPSA-GB
commit, and the manifest states exactly what produced it.

The comparison was run against PyPSA-GB commit `074ea25e` (2026-02-25). Carbon
intensity values in every output are in gCO2 per kWh. The heatmap pivots are
oriented with calendar date on the rows and hour of day (0 to 23) on the
columns.

## Results, full year 2023

The Zonal, Reduced, and copperplate comparison, aligned hourly across 2023.
Source: `assembly_manifest.json`, generated 2026-05-24, 8713 aligned hours. The
CSVs behind this table are bundled in `results/`; `results/README.md` lists them.

| Series | Mean | Std | Min | Max | Mean offset vs NESO |
|---|---|---|---|---|---|
| NESO actual | 152.1 | 62.6 | 0.0 | 307.5 | reference |
| Zonal 17-bus | 144.8 | 83.5 | 0.0 | 330.9 | -7.4 |
| Reduced 32-bus | 143.2 | 73.9 | 3.0 | 317.9 | -8.9 |
| Reduced 32-bus copperplate | 133.5 | 81.5 | 0.0 | 319.9 | -18.6 |

All values are in gCO2 per kWh. The 17-bus and 32-bus means agree to within
2 gCO2 per kWh, while the hourly difference (32-bus minus 17-bus) averages
16.0 gCO2 per kWh in absolute terms: the two topologies dispatch the same total
emissions across the year but disagree on when intensity is high or low. The
32-bus line constraints raise the annual mean by approximately 10 gCO2 per kWh
relative to the unconstrained copperplate dispatch (mean 32-bus minus
copperplate +9.7 gCO2 per kWh), by forcing higher-carbon local generation when
constrained boundaries would otherwise carry zero-carbon power.

## Interpretation and limitations

Both modelled series sit 7 to 9 gCO2 per kWh below NESO under default settings.
This is expected and is documented in the methodology. No demand uplift for
transmission and distribution losses is applied, the dispatch is a linear
program with no unit commitment (so it loads low-carbon plant more fully than a
real system bound by minimum run times and start-up costs), and the upstream
REPD ingest at this commit under-represents dedicated biomass capacity. None of
these are corrected here, because the purpose is the topology comparison, not a
match to NESO. The dispatch is a DC linear flow with no reactive power. The NESO
series is published half-hourly and is averaged to hourly to match the model.

## ETYS extension

A third topology, the full ETYS network (2,130 solved buses), can be added on
the same default settings as an optional extension. The full-year ETYS linear
program cannot be built on a 32 GB workstation: PyPSA's cycle-based Kirchhoff voltage law materialises a
dense coefficient array of approximately 110 GiB during model construction,
before the solver runs, and the build peaks near 1.1 TB. It is therefore solved
on an Imperial RCS CX3 large-memory node by `solve_etys_hpc.py`, which
reproduces the PyPSA-GB solve step exactly so the result is comparable to the
two coarser topologies. The end-to-end HPC procedure is in
`docs/etys_hpc_runbook.md`.

The per-bus `nodal_carbon_intensity.py` builds one dense bus-by-bus flow matrix
per snapshot. That is fine at tens of buses but grows with the square of the bus
count, so it needs a sparse rewrite before it runs at the full ETYS scale. The
system-wide `system_carbon_intensity.py` has no such matrix and runs at any bus
count.

## Documents in this bundle

The method and the exact commands ship with the code, in `docs/`:

- `docs/topology_comparison_methodology.md`, the method in academic form,
  including the factor table and the emission attribution choices.
- `docs/topology_comparison_runbook.md`, the step-by-step commands for the
  Zonal, Reduced, and copperplate pipeline.
- `docs/etys_hpc_runbook.md`, the full ETYS solve on Imperial RCS HPC, including
  the memory analysis and the batch job script (only needed for the optional
  ETYS extension).
