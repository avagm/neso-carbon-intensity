# Runbook: default-settings 17 vs 32 bus topology comparison

Step-by-step instructions to run the workflow and produce the heatmap dataset,
including the soft-copperplate variant on the Reduced 32-bus network. The
method behind it is described in `methodology.md`.

## Starting point

The setup is already in place. Before running anything, the following exists.

| Item | State |
|---|---|
| `..\PyPSA-GB-default` | Fresh PyPSA-GB clone, pinned to commit `074ea25e` on branch `default-baseline`. Separate from the calibration clone `..\PyPSA-GB`. |
| `config/scenarios.yaml` | Scenarios `Historical_2023_zonal_year` and `Historical_2023_reduced_year` added (full calendar 2023). |
| `config/config.yaml` | `run_scenarios` set to those two scenarios. |
| `config/defaults.yaml` | Solver block set to memory-safe Gurobi (threads 12, BarHomogeneous 0, NumericFocus 0). |
| `resources/atlite/cutouts/uk-2023.nc` | 2023 weather cutout, copied in. No download needed. |
| `personalPypsa/system_carbon_intensity.py` | Streamlined carbon-intensity post-processor. |
| `personalPypsa/copperplate.py` | Soft and hard copperplate utilities. |
| `personalPypsa/solve_softcopperplate.py` | Driver: soft copperplate then re-solve. |
| `personalPypsa/scripts/build_topology_heatmap_data.py` | Heatmap-dataset assembly. Supports the copperplate series via `--copperplate`. |
| `personalPypsa/scripts/pull_neso_2023.py` | NESO API puller for the reference series. |
| `personalPypsa/results/neso_2023/national_intensity.csv` | NESO 2023 national actuals, already on disk. |

The work that remains is to run the two solves, run the copperplate variant,
post-process all three, assemble the dataset, and promote the result.

## Step 1: open the shell

Open the Miniforge Prompt from the Start menu. Do not use PowerShell: its
execution policy blocks the conda profile hook on this machine.

## Step 2: activate the environment and check the clone

```
cd C:\Users\user\projects\PyPSA-GB-default
conda activate pypsa-gb
git branch --show-current
git status
```

`git branch --show-current` should print `default-baseline`. `git status` will
list `config/defaults.yaml`, `config/scenarios.yaml`, and `config/config.yaml`
as modified. That is expected: those are the three configuration edits for
this study, kept uncommitted by the same convention the calibration clone
uses. Leave them in place.

## Step 3: solve the two topologies

Solve one topology at a time. A full calendar-year solve uses a large amount of
memory, and two running together can exhaust the available RAM. Always pass
`--config scenario=` so that exactly one scenario, and therefore one solve,
runs at a time.

Solve the Zonal topology:

```
snakemake --cores 8 --config scenario=Historical_2023_zonal_year
```

Wait for it to finish, then solve the Reduced topology:

```
snakemake --cores 8 --config scenario=Historical_2023_reduced_year
```

The first run for each topology also builds the network from the bundled DUKES,
REPD, and ESPENI data and the 2023 cutout, so budget roughly 30 to 60 minutes
per topology. The linear-program solve itself is the shorter part. Snakemake
caches intermediates, so a re-run after an interruption skips completed steps.

Each solve writes its result to the clone:

```
resources/network/Historical_2023_zonal_year_solved.nc
resources/network/Historical_2023_reduced_year_solved.nc
```

To confirm a solve succeeded, check that the `_solved.nc` file exists and that
`resources/network/<scenario>_optimization_summary.txt` reports an optimal
solution.

## Step 4: compute system carbon intensity for the two topologies

Move to the workbench, keeping the same activated environment, and run the
post-processor once per topology. The `--pypsa-gb-commit` value is recorded in
the output manifest for reproducibility.

```
cd C:\Users\user\projects\personalPypsa

python system_carbon_intensity.py ^
  --network ..\PyPSA-GB-default\resources\network\Historical_2023_zonal_year_solved.nc ^
  --out-dir results\2023_topology_default\zonal_17bus ^
  --label "Zonal 17-bus" ^
  --pypsa-gb-commit 074ea25ec0ca83ecfd3703b2af3a820a25518c50

python system_carbon_intensity.py ^
  --network ..\PyPSA-GB-default\resources\network\Historical_2023_reduced_year_solved.nc ^
  --out-dir results\2023_topology_default\reduced_32bus ^
  --label "Reduced 32-bus" ^
  --pypsa-gb-commit 074ea25ec0ca83ecfd3703b2af3a820a25518c50
```

Each run takes under a minute and prints the annual mean intensity. It writes
`system_carbon_intensity.csv`, `generation_by_carrier.csv`, and `manifest.json`
into the output directory.

## Step 5: soft copperplate the Reduced network and re-solve

The soft copperplate keeps the 32-bus topology and the same generators and
loads, but raises every line and link `s_nom` to 10^7 MW so no transmission
constraint can bind. Re-solving gives the dispatch the system would produce
without transmission constraints, the "no transmission" reference for the
study.

```
python solve_softcopperplate.py ^
  --in  ..\PyPSA-GB-default\resources\network\Historical_2023_reduced_year_solved.nc ^
  --out results\2023_topology_default\reduced_32bus_copperplate\network.nc ^
  --solver gurobi
```

The re-solve uses dual simplex by default for a no-constraint LP and finishes
in roughly five to ten minutes.

Post-process the copperplate the same way as the constrained runs:

```
python system_carbon_intensity.py ^
  --network results\2023_topology_default\reduced_32bus_copperplate\network.nc ^
  --out-dir results\2023_topology_default\reduced_32bus_copperplate ^
  --label "Reduced 32-bus copperplate" ^
  --pypsa-gb-commit 074ea25ec0ca83ecfd3703b2af3a820a25518c50
```

## Step 6: assemble the heatmap dataset

```
python scripts\build_topology_heatmap_data.py ^
  --zonal       results\2023_topology_default\zonal_17bus\system_carbon_intensity.csv ^
  --reduced     results\2023_topology_default\reduced_32bus\system_carbon_intensity.csv ^
  --copperplate results\2023_topology_default\reduced_32bus_copperplate\system_carbon_intensity.csv ^
  --neso        results\neso_2023\national_intensity.csv ^
  --out-dir     results\2023_topology_default
```

If the copperplate variant has not been run, omit `--copperplate`. With it, the
script also writes `heatmap_pivot_reduced_32bus_copperplate.csv` and
`heatmap_pivot_reduced_minus_copperplate.csv` (the transmission-constraint
impact on hourly CI), and adds the copperplate series to `heatmap_input.csv`
and the manifest.

## Step 7: outputs and promotion

The dataset for the team heatmap is in `results\2023_topology_default\`.

| File | Role |
|---|---|
| `heatmap_input.csv` | Hourly UTC table: `neso_actual`, `zonal_17bus`, `reduced_32bus`, `reduced_32bus_copperplate`, `reduced_minus_zonal`, `reduced_minus_copperplate`. |
| `heatmap_pivot_neso_actual.csv` | NESO actual as a date by hour-of-day grid. |
| `heatmap_pivot_zonal_17bus.csv` | 17-bus model as a date by hour-of-day grid. |
| `heatmap_pivot_reduced_32bus.csv` | 32-bus model as a date by hour-of-day grid. |
| `heatmap_pivot_reduced_32bus_copperplate.csv` | 32-bus copperplate as a date by hour-of-day grid. |
| `heatmap_pivot_reduced_minus_zonal.csv` | 32-bus minus 17-bus as a grid (topology difference). |
| `heatmap_pivot_reduced_minus_copperplate.csv` | 32-bus minus its copperplate as a grid (transmission-constraint impact). |
| `zonal_17bus/`, `reduced_32bus/`, `reduced_32bus_copperplate/` | Per-variant hourly intensity, per-carrier breakdown, and manifest. |
| `assembly_manifest.json` | Alignment record and per-series statistics. |

To deliver the result, copy into the team delivery directory
`..\neso-carbon-intensity\` and commit to the team repository:

- `methodology.md`
- `deliverables\topology_comparison_runbook.md` (this file)
- the contents of `results\2023_topology_default\` (the dataset)
- the scripts the team needs to reproduce: `system_carbon_intensity.py`,
  `copperplate.py`, `solve_softcopperplate.py`,
  `scripts\build_topology_heatmap_data.py`, `scripts\pull_neso_2023.py`

## Notes

The NESO actuals on disk were pulled earlier in the project. To refresh them,
run `python scripts\pull_neso_2023.py --out-dir results\neso_2023`, which also
re-fetches the emission-factor snapshot.

For a quick sanity plot, the per-variant `system_carbon_intensity.csv` files
are compatible with the existing `deliverables\visualise.py` script, which can
plot them against the NESO series.

If a solve reports a memory error, confirm that only one `snakemake` process is
running and that `config/defaults.yaml` still has `BarHomogeneous: 0` and
`NumericFocus: 0` in the solver block.
