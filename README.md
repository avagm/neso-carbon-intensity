# NESO Carbon Intensity Project — ELEC60014
Imperial College London | Group Project

Forecasting nodal carbon intensity for the GB electricity system using
PyPSA-GB as the underlying dispatch model and the NESO Carbon Intensity API
as the validation target.

## Repository structure

```
neso-carbon-intensity/
├── README.md
├── Scripts/                Pipeline scripts
├── Results/
│   ├── week 1/             Copperplate and 17-zone outputs
│   └── week 2/             Pending
└── bialek_tracing_v2/      Shared Bialek tracing notebook
```

Per-member directories from earlier weeks have been folded in

## Week 1

Two runs on the same 1-7 January 2023 window (336 half-hour snapshots),
PyPSA-GB historical inputs (DUKES, ESPENI, ERA5).

Copperplate (single bus, no network constraints):
- MAE vs NESO actual: ~36 gCO2/kWh
- Pearson r: ~0.90
- Mean bias: -33.5 gCO2/kWh. Model underestimates, consistent with relaxed
  network and idealised generators.

Zonal (17 zones), same window. Outputs in `Results/week 1/`.

## Week 2

Three things to do.

### 1. Add the missing real-world variables

The Week 1 negative bias of around 33 gCO2/kWh lines up with two things the
model is not doing that NESO does.

Transmission line losses. PyPSA-GB has a flag for linear losses on AC
lines, currently off. UK transmission and distribution losses run at
around 8 percent. Switching the flag on raises required generation and
emissions in proportion. Lives in `PyPSA-GB/config/defaults.yaml`.

Biomass emission factor. PyPSA-GB carries biomass at 0 t/MWh on a
carbon-neutral assumption. NESO uses 120 gCO2/kWh. Edit
`PyPSA-GB/scripts/utilities/carrier_definitions.py` or apply the factor
in post-processing.

Report headline CI change against the Week 1 baseline for each switch in
isolation and the two combined.

### 2. 17-zone vs 32-bus, extended to the full year

Repeat the Week 1 run on both topologies first, then push to the full 2023
calendar year (8760 hours) on both. The short window does not show
seasonal irregularities and cannot be compared against
NESO's annual figures.

Tractability is the constraint.
Plan:

- Profile compute time 17 and 32 buses on the January
  window and on a one-month extension. This was asked by Neso to see about practical constaints
-Everyone should switch to gurobi

- Imperial HPC (CX1, CX2) for the full-year solve.

- Cloud maybe could be budgeted?


Important
Outputs: short table of wall time, peak memory and annual mean CI per
(topology, window, solver, machine) combination tried, plus the full-year
intensity series for both topologies against NESO.

So like an output with comparisons across our team results

### 3. Pipeline

Replace the four duplicate scripts in `Scripts/` with a single module that
takes a solved PyPSA-GB `.nc` and a scenario name, writes the standard CSV
outputs to `Results/<scenario>/`, and produces the standard plots
(intensity time series, generation mix, NESO comparison). System and
per-bus intensity, with the per-bus consumption view via Bialek average
proportional sharing.

The pipeline gives the same outputs

## Setup (do this once)

### 1. Clone PyPSA-GB

```
git clone https://github.com/andrewlyden/PyPSA-GB.git
cd PyPSA-GB
conda env create -f envs/pypsa-gb.yaml
conda activate pypsa-gb
pip install pyarrow --upgrade
pip install netCDF4 --force-reinstall
```

### 2. Fix the renewables.smk bug

Open `rules/renewables.smk`, find `_get_required_cutout_years()`, and
remove the line:

```
years.add(sc.get("demand_year", 2020))
```

### 3. Download 2023 weather data

In `config/cutouts_config.yaml` set:

```
years_to_generate:
  - 2023
```

Then run:

```
snakemake -s Snakefile_cutouts --cores 2
```

### 4. Add a 2023 scenario

`Historical_2023_reduced` (32-bus) and `Historical_2023_zonal` (17-zone)
already ship in upstream `config/scenarios.yaml`. For a copperplate
baseline, add:

```
CopperPlate_2023:
  description: "Week 1 copper-plate, historical 2023"
  modelled_year: 2023
  renewables_year: 2023
  demand_year: 2023
  network_model: "Zonal"
  timestep_minutes: 30
  solve_period:
    enabled: true
    start: "2023-01-01 00:00"
    end: "2023-01-07 23:30"
  solver:
    name: "highs"
```

Then in `config/config.yaml`:

```
run_scenarios:
  - CopperPlate_2023
```

### 5. Solve

```
snakemake resources/network/CopperPlate_2023_solved.nc -j 4
```

### 6. Clone this repo and run a Week 1 script

```
cd ..
git clone https://github.com/avagm/neso-carbon-intensity.git
cp neso-carbon-intensity/Scripts/copper_plate.py PyPSA-GB/
cd PyPSA-GB
python copper_plate.py
```

## Notes

HiGHS is the default solver (free, no licence). Set
`solver: name: "highs"` in scenario config.

On Apple Silicon Macs run after creating the conda environment:

```
pip install pyarrow --upgrade
pip install netCDF4 --force-reinstall
```

Do not push solved networks (`.nc`), the `resources/` folder, or other
large generated files. Snakemake regenerates them locally.
