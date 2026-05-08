# NESO Carbon Intensity Project — ELEC60014
Imperial College London | Group Project

## Repository Structure
Each team member has their own folder. Week outputs go in the relevant week subfolder.

neso-carbon-intensity/
├── ava/
│   └── week1/
│       ├── copper_plate.py
│       └── copper_plate_result.png
├── annie/
│   └── week1/
├── momo/
│   └── week1/
├── matthew/
│   └── week1/
├── adnan/
│   └── week1/
├── mert/
│   └── week1/
└── README.md

## Setup (do this once)

### 1. Clone PyPSA-GB
    git clone https://github.com/andrewlyden/PyPSA-GB.git
    cd PyPSA-GB
    conda env create -f envs/pypsa-gb.yaml
    conda activate pypsa-gb
    pip install pyarrow --upgrade
    pip install netCDF4 --force-reinstall

### 2. Fix the renewables.smk bug
Open rules/renewables.smk and find _get_required_cutout_years(). Remove this line:
    years.add(sc.get("demand_year", 2020))

### 3. Download 2023 weather data
In config/cutouts_config.yaml set:
    years_to_generate:
      - 2023

Then run:
    snakemake -s Snakefile_cutouts --cores 2

### 4. Add the CopperPlate_2023 scenario
In config/scenarios.yaml add at the top:

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

In config/config.yaml set:
    run_scenarios:
      - CopperPlate_2023

### 5. Build and solve the network
    snakemake resources/network/CopperPlate_2023_solved.nc -j 4

### 6. Clone this repo and run Week 1
    cd ..
    git clone https://github.com/avagm/neso-carbon-intensity.git
    cp neso-carbon-intensity/ava/week1/copper_plate.py PyPSA-GB/
    cd PyPSA-GB
    python copper_plate.py

## Week 1 Results
- Model: Copper-plate (single bus, no network constraints)
- Data: PyPSA-GB historical 2023 (DUKES generators, ESPENI demand, ERA5 weather)
- Period: 1-7 January 2023 (336 half-hour snapshots)
- MAE vs NESO actual: ~36 gCO2/kWh
- Pearson r: ~0.90
- Mean bias: -33.5 gCO2/kWh (model underestimates — expected without network constraints)

## Notes
- Use HiGHS solver (free, no licence needed) — set solver: name: "highs" in scenario config
- On Apple Silicon Macs (M1/M2/M3) run these after creating the conda environment:
    pip install pyarrow --upgrade
    pip install netCDF4 --force-reinstall
- Each team member should work in their own named folder and push their week's work there
- Do not push large data files or the resources/ folder — these are generated locally by Snakemake
