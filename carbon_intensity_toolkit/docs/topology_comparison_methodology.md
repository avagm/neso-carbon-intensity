# Default-settings topology comparison: GB carbon intensity, 2023

## Purpose and scope

This document describes how hourly carbon intensity of the GB electricity
system for calendar year 2023 is produced from PyPSA-GB under default
settings, on two network topologies, so that a comparative heatmap can be
built of NESO actual carbon intensity against the two modelled series.

The objective is to isolate the effect of network topology. Both topologies
are solved from the same PyPSA-GB clone at the same commit, with identical
default settings, identical input data, and identical post-processing. The
only difference between the two runs is the `network_model` setting. Any
difference in the resulting carbon intensity is therefore attributable to
spatial resolution and the transmission constraints that come with it.

This is not a validation exercise. The NESO national series is included as an
external reference for the heatmap, not as a calibration target. The demand
uplift, emission-factor calibration, and REPD fleet corrections used in the
project's validation work are deliberately excluded. The validation-era nodal
methodology is documented separately in `methodology.md`; the present document
is self-contained for the topology comparison.

## PyPSA-GB configuration

The runs use a dedicated clone of PyPSA-GB kept separate from the calibration
clone, so that the default-settings work cannot be affected by uncommitted
scenario or solver edits. The clone is pinned to upstream master commit
`074ea25e` (2026-02-25) on a branch named `default-baseline`. This is the
PyPSA-GB version the project's prior work is based on, so the comparison
varies the topology and not the model version.

Default settings means the values shipped in `config/defaults.yaml` at commit
`074ea25e`, with three exceptions, none of which change the optimisation
result.

| Setting | Shipped | Used | Reason |
|---|---|---|---|
| `solver.threads` | 4 | 12 | Use more cores. Affects solve time only. |
| `solver.BarHomogeneous` | 1 | 0 | Relax barrier numerics. |
| `solver.NumericFocus` | 3 | 0 | Relax barrier numerics. |

The barrier numerics are relaxed from the shipped maximum-care values because
those values drive the barrier factorisation memory above the available RAM on
a full calendar-year solve. `BarHomogeneous` and `NumericFocus` are solver
performance settings; the linear-program optimum, and therefore the dispatch
and the carbon intensity, are unchanged. The solver itself, Gurobi, is the
value shipped at this commit.

Two scenarios are added to `config/scenarios.yaml`: `Historical_2023_zonal_year`
and `Historical_2023_reduced_year`. Each specifies only the modelled year
(2023), the renewables and demand years (2023), the network model, and a
full calendar-year solve period (2023-01-01 00:00 to 2023-12-31 23:00). Every
other value is inherited from `defaults.yaml`.

Under these settings the model is a linear-program economic dispatch
(`solve_mode: LP`, no unit commitment) at hourly resolution
(`timestep_minutes: 60`). Demand is the ESPENI historical metered series for
2023, used as recorded with no uplift for transmission and distribution
losses. Marginal costs come from the built-in historical lookup tables for
2023. Clustering, component and renewable aggregation, and demand flexibility
are all off. No demand is scaled, no emission factor is overridden inside the
model, and the REPD generator ingest is left at its upstream behaviour.

## Network topologies

PyPSA-GB provides the GB transmission network at three spatial resolutions.
This study uses the two coarser ones.

| Label | `network_model` | PyPSA-GB description | Solved buses |
|---|---|---|---|
| Zonal 17-bus | `Zonal` | 17 zones | 24 |
| Reduced 32-bus | `Reduced` | 32 buses | 34 |

The solved bus counts exceed the nominal zone or bus counts because each
network carries additional external buses for the interconnector endpoints
(four for Zonal, five for Reduced). Both networks draw the same generator
fleet (DUKES thermal plant and REPD renewables), the same ESPENI demand, and
the same ERA5-derived renewable profiles for 2023. They differ only in how
that fleet and demand are distributed across buses, and in the transmission
lines connecting them. The Reduced network carries more internal transmission
boundaries, so its linear optimal dispatch is subject to more binding line
constraints than the Zonal network.

## Emission factors

Dispatched energy is converted to emissions using the NESO published emission
factors, in gCO2 per kWh of electricity sent out, from the NESO Carbon
Intensity API `/intensity/factors` endpoint. The factor snapshot is stored at
`results/neso_2023/factors.json`; the values below are also tabulated in
`reference.md` section 1.6.

| Carrier group | PyPSA-GB carriers | Factor (gCO2 per kWh) |
|---|---|---|
| Wind, solar, hydro, marine, nuclear | wind_onshore, wind_offshore, solar_pv, large_hydro, small_hydro, tidal_stream, shoreline_wave, nuclear | 0 |
| Biogenic | biomass, biogas, landfill_gas, sewage_gas, advanced_biofuel | 120 |
| Gas, combined cycle | CCGT | 394 |
| Gas, open cycle | OCGT | 651 |
| Coal | coal | 937 |
| Oil | oil | 935 |
| Waste | waste_to_energy | 300 |

NESO publishes a single Biomass factor (120 gCO2 per kWh), applied here to
every biogenic carrier. Waste-to-energy takes the NESO "Other" factor
(300 gCO2 per kWh).

The factors are applied directly to dispatched generation. They are not
derived from the PyPSA-GB carrier definitions, because PyPSA-GB assigns a
uniform efficiency of 0.5 to every thermal carrier rather than a
per-technology value, which makes a thermal-to-electrical conversion through
that efficiency unreliable. The NESO factors are already stated at the
electrical system boundary and need no efficiency conversion.

NESO attributes interconnector imports to the source country. PyPSA-GB places
each import generator on an external bus tagged with a country, and that tag
selects the factor.

| Country | Factor (gCO2 per kWh) | Source |
|---|---|---|
| France | 53 | NESO French Imports |
| Netherlands | 474 | NESO Dutch Imports |
| Ireland | 458 | NESO Irish Imports |
| Belgium | 300 | NESO "Other" (no published Belgian factor) |
| Norway | 35 | Statnett published 2023 figure |
| Denmark | 130 | Energinet published 2023 figure |

## System carbon intensity

For each hourly snapshot t, the system carbon intensity is

    CI[t] = system_emissions[t] / system_generation[t] * 1000

with `system_emissions` in tonnes CO2, `system_generation` in MWh, and the
factor 1000 converting tCO2 per MWh into gCO2 per kWh.

`system_emissions` is the sum over generators of dispatched energy multiplied
by the NESO factor for that generator. `system_generation` is the sum of
positive generator dispatch and positive storage discharge. Storage discharge
carries a zero emission factor, which keeps the denominator consistent with
NESO, whose published generation mix counts pumped storage as a zero-factor
entry. Generator dispatch is clipped at zero, so an interconnector exporting
in a given hour contributes neither generation nor emissions.

A system-wide intensity is the only carbon intensity quantity that is directly
comparable between a 17-bus and a 32-bus network, because the two networks do
not share a common bus set. Per-bus intensities are therefore not produced for
this comparison.

PyPSA-GB snapshots are time-zone naive. They are treated as UTC, consistent
with the convention the project already uses when aligning model output
against NESO.

## Data pipeline

The pipeline runs in five stages. Stages 2 to 4 are scripted; stage 5 is the
team's visualisation work.

1. **Inputs.** The pinned PyPSA-GB clone provides the model code and the
   bundled input data (DUKES, REPD, ESPENI). The 2023 ERA5 weather cutout
   `uk-2023.nc` provides renewable profiles. The NESO national carbon
   intensity for 2023 is pulled by `scripts/pull_neso_2023.py` into
   `results/neso_2023/national_intensity.csv`, with the factor snapshot in
   `results/neso_2023/factors.json`.

2. **Solve.** For each topology, `snakemake` builds the network and solves the
   linear-program economic dispatch, writing a solved network to the clone's
   `resources/network/` directory. The two scenarios are solved one at a time.

3. **System carbon intensity.** `system_carbon_intensity.py` reads one solved
   network, applies the NESO factors, and writes the hourly intensity series,
   a per-carrier generation breakdown, and a manifest. It is run once per
   topology.

4. **Assembly.** `build_topology_heatmap_data.py` reads the two intensity
   series and the NESO series, aligns them on a common hourly UTC index, and
   writes the heatmap dataset.

5. **Visualisation.** The team builds the comparative heatmap of NESO actual
   against the 17-bus and 32-bus series from the assembled dataset.

The artifacts produced are as follows. Paths under `results/` are relative to
the `personalPypsa` workbench.

| Artifact | Produced by | Location | Content |
|---|---|---|---|
| `<scenario>_solved.nc` | snakemake | clone `resources/network/` | Solved network, 8760 hourly snapshots |
| `system_carbon_intensity.csv` | `system_carbon_intensity.py` | `results/2023_topology_default/<topology>/` | Hourly system emissions (tCO2), generation (MWh), intensity (gCO2 per kWh) |
| `generation_by_carrier.csv` | `system_carbon_intensity.py` | same | Annual generation and emissions per carrier |
| `manifest.json` | `system_carbon_intensity.py` | same | Network SHA-256, factor tables, headline numbers |
| `heatmap_input.csv` | `build_topology_heatmap_data.py` | `results/2023_topology_default/` | Hourly UTC table: `neso_actual`, `zonal_17bus`, `reduced_32bus`, `reduced_minus_zonal` |
| `heatmap_pivot_*.csv` | `build_topology_heatmap_data.py` | same | Date (rows) by hour-of-day 0 to 23 (columns) grids, one per series plus the 32-bus minus 17-bus difference |
| `assembly_manifest.json` | `build_topology_heatmap_data.py` | same | Inputs, hours aligned, per-series statistics |

All carbon intensity values in these files are in gCO2 per kWh. The heatmap
pivots are oriented with calendar date on the rows and hour of day on the
columns.

## Interpretation and limitations

Under default settings the modelled series are expected to sit below the NESO
reference. Two reasons account for most of the gap. First, no demand uplift is
applied, so the model dispatches generation to meet metered demand only, while
NESO reports intensity per kWh delivered with transmission and distribution
losses included. Second, a linear program with perfect foresight and no unit
commitment dispatches low-cost low-carbon plant more fully than a real system
constrained by minimum run times and start-up costs. Neither effect is
corrected here, because the purpose is the topology comparison and not a match
to NESO.

At commit `074ea25e` the PyPSA-GB REPD ingest under-represents dedicated
biomass capacity relative to the operational GB fleet. This is a known
property of the upstream model at this version and is left uncorrected, since
correcting it is part of the validation work this study sets aside. Both
topologies share the same fleet, so the topological difference is unaffected.

Further limitations. The dispatch is a DC linear flow with no reactive power.
The NESO series is published half-hourly and is averaged to hourly to match
the model. Across 2023 a small number of hours (of order 0.5 percent) have no
NESO actual value; those hours are absent from the aligned dataset and will
appear as blank cells in the heatmap pivots.

## ETYS 2000-bus extension

A third, finer topology is added on the same default settings: the full ETYS
network (2,130 solved buses) for 2023. It uses the same pinned clone, the same
finalized-build provenance, and the same `system_carbon_intensity.py`
post-processing, so its carbon intensity is comparable to the Zonal and Reduced
series.

The full-year ETYS solve does not fit the 32 GB workstation, and the limit is
in model construction rather than in the solver. PyPSA builds the Kirchhoff
voltage law from a cycle basis, and at 1015 independent loops over 8760
snapshots linopy materialises a dense coefficient array of approximately
110 GiB before the solver runs. The 1015 loops are branches minus buses plus
connected components: (1653 lines plus 1478 transformers) minus 2130 buses plus
14 components. The Zonal and Reduced networks have only a few loops, so the same
array is negligible there.

The solve is therefore run on an Imperial RCS CX3 large-memory node. To hold
parity, a standalone script (`scripts/solve_etys_hpc.py`) reproduces the
PyPSA-GB solve step verbatim: the same numerical-conditioning and LP-mode
preprocessing, the same Gurobi barrier options from `defaults.yaml`, and the
same PyPSA 1.2.0 and linopy 0.6.7 versions. The HPC solver is Gurobi 11.0.0
against 12.0.3 on the workstation; the linear-program optimum, and therefore the
dispatch and carbon intensity, are unaffected by the solver version. The full
procedure is in `etys_hpc_runbook.md`.

## Reproducibility

Every result is regeneratable from this repository's code and the pinned
PyPSA-GB commit. The clone is fixed at `074ea25e`. Each `system_carbon_intensity.py`
run records the solved-network SHA-256 and the PyPSA-GB commit in its
`manifest.json`; the assembly step records its inputs and the number of hours
aligned in `assembly_manifest.json`. The exact commands are in
`topology_comparison_runbook.md`. The NESO factor table changes over time and
should be re-pulled, and the snapshot date checked, before the numbers are
quoted in any final write-up.
