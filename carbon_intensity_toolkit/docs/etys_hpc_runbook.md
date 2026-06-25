# Runbook: full ETYS 2000-bus solve on Imperial HPC

Step-by-step instructions to add a third topology to the default-settings
comparison: the full ETYS network (approximately 2000 buses) for full calendar
year 2023, solved on the Imperial College Research Computing Service (RCS) CX3
cluster. The solved network feeds the same `system_carbon_intensity.py`
post-processor as the Zonal 17-bus and Reduced 32-bus runs, so the ETYS carbon
intensity sits on the same footing as the other two topologies. The method and
the two coarser topologies are in `topology_comparison_methodology.md` and
`topology_comparison_runbook.md`.

## Purpose and scope

The Zonal and Reduced solves run on the 32 GB workstation. The full ETYS solve
does not, for a reason that is structural rather than a tuning problem (next
section). The solve is therefore moved to a large-memory HPC node. The
finalized network is built once on the workstation, transferred to HPC, and
solved there by a standalone script that reproduces the PyPSA-GB solve step
exactly. The solved network is brought back and post-processed on the
workstation.

## Why a large-memory node

The full-year ETYS linear program cannot be constructed in 32 GB. The wall is
in model construction, not in the solver. PyPSA builds the Kirchhoff voltage
law from a cycle basis, and at this network size linopy materialises a dense
coefficient tensor of shape (8760 snapshots, 1653 lines, 1, 1015 cycles) in
float64, which is approximately 110 GiB for that single array. The local
attempt failed there with a NumPy `Unable to allocate 110. GiB` error inside
`define_kirchhoff_voltage_constraints`, after approximately 2 minutes
43 seconds, before Gurobi was invoked.

The build allocates more than that one array. On a large-memory node the
construction proceeds past the 110 GiB float64 tensor and then needs a 207 GiB
int64 array of shape (8760, 1015, 3131) for the variable labels at the
constraint merge step. A 920 GB node reached approximately 553 GB resident
before failing on that allocation. On a node with room, the build completes with
an observed peak of approximately 1.1 TB (high-water mark 1,117,722,220 kB), so
the solve needs a large-memory node, though not the full 4 TB: about 2 TB is
ample.

The cycle count follows from the topology. Independent loops equal branches
minus buses plus connected components: (1653 lines plus 1478 transformers)
minus 2130 buses plus 14 components equals 1015. The Zonal and Reduced networks
have only a few cycles, so the same tensor is negligible there and they solve
in minutes. The array scales linearly with the number of snapshots, so the gate
is set by the full 8760-hour horizon at the full bus count.

Network dimensions, from the build validation report
`Historical_2023_etys_year_network_summary.txt` at PyPSA-GB commit `074ea25e`:

| Quantity | Value |
|---|---|
| Buses | 2,130 |
| Lines | 1,653 |
| Transformers | 1,478 |
| Links | 14 |
| Snapshots | 8,760 (hourly, 2023) |
| Load buses | 360 |
| Total demand | 274,703,150 MWh |
| Peak demand | 50,631 MW |
| Generation capacity | 161,009 MW |

CX3 node classes relevant here, from the RCS user guide cluster specification
(`icl-rcs-user-guide.readthedocs.io`):

| Node | Cores | Memory per node |
|---|---|---|
| AMD | 128 | 1 TB (1,024 GB) |
| Intel | 64 | 500 GB |
| AMD large memory | 128 | 4 TB (4,096 GB) |

A request above 920 GB routes to the `largemem72` queue and the 4 TB
large-memory nodes (which accept requests of 921 GB to 4000 GB). Size the request
near 2000 GB: the observed peak is approximately 1.1 TB, so 2000 GB gives margin
while still scheduling quickly. Do not over-request. A `mem=3500gb` ask sat in
the queue for over a day, because the scheduler only places it on a node with
3.5 TB free (effectively a near-empty 4 TB node); trimming the same job to
`mem=2500gb` with `qalter` let it backfill onto a partly-used 4 TB node and it
started within minutes. The `large72` queue (up to 920 GB) is not an option: a
920 GB node ran out of memory at the merge step.

## Parity with the Zonal and Reduced solves

The HPC solve uses `scripts/solve_etys_hpc.py`. It loads the finalized network
and applies, in order, the same operations as PyPSA-GB
`scripts/solve/solve_network.py` at commit `074ea25e`, so the resulting
dispatch is comparable to the two coarser topologies.

1. Numerical conditioning, copied verbatim from the rule: remove generators,
   storage units, and links with `p_nom` below 0.1 MW (load shedding excepted),
   and clamp transformer reactance above 10.0 to 10.0.
2. LP mode: set every generator `committable` to False (`solve_mode: LP`).
3. Must-run preserved: `p_min_pu` is left unchanged (`remove_must_run` defaults
   to False).
4. Transmission relaxation is a no-op under the default config
   (`min_line_s_nom: 0`, `min_transformer_s_nom: 0`, `capacity_scale: 1.0`), so
   it is omitted.

The solver options default to the `defaults.yaml` solver block exactly: Gurobi
barrier (`method: 2`), crossover off (`crossover: 0`), 12 threads,
`BarHomogeneous: 0`, `BarConvTol: 1e-4`, `FeasibilityTol: 1e-4`,
`OptimalityTol: 1e-4`, `NumericFocus: 0`, `ScaleFlag: 2`, `DualReductions: 0`,
`BarIterLimit: 200`. PyPSA and linopy are pinned to the workstation versions
(PyPSA 1.2.0, linopy 0.6.7), so the optimisation formulation is identical. These
defaults do not converge the full ETYS LP (see "Numerical convergence" below);
the recommended invocation overrides two of them, crossover and the barrier
numerics, which changes only the path to the optimum, not the optimum itself.

The solver on HPC is Gurobi 11.0.0, the version the CX3 token server licenses,
against Gurobi 12.0.3 on the workstation. The solver version does not change
the linear-program optimum, only the path to it, so the dispatch and the carbon
intensity are unaffected. This is the same argument the methodology uses for
the relaxed barrier numerics.

The standalone script omits the rule's CSV exports (generation, storage, flows,
costs, emissions) and the optimization summary text. Those are conveniences;
the carbon-intensity post-processor reads the solved network directly. The
standalone path also bypasses Snakemake and its config validation, which is why
only the finalized network (99 MB) and the script need to reach HPC, not the
full clone or the ERA5 cutout.

## Prerequisites

| Item | State |
|---|---|
| RCS account | Registered for the Imperial RCS HPC service. Post-docs and PhD students are added by a supervisor or group leader. |
| Off-campus access | Connected to Unified Access (Zscaler) when not on the College network. The CX3 login nodes are not reachable otherwise. |
| Gurobi on CX3 | Module `Gurobi/11.0.0-GCCcore-12.3.0`, licensed by the campus token server `gurobi.cc.ic.ac.uk`. The licence file is `/sw-eb/software/Gurobi/11.0.0-GCCcore-12.3.0/gurobi.lic`. |
| Finalized network | `Historical_2023_etys_year.nc`, built locally (step 1). |
| Solve script | `scripts/solve_etys_hpc.py` in this repository. |

## Step 1: build the finalized network (workstation)

The ETYS scenario is in `config/scenarios.yaml` as `Historical_2023_etys_year`
(full calendar year 2023). It is documented in `config/config.yaml` but kept
out of the active `run_scenarios` list, because the full-year solve is the
HPC-gated case. The build is memory-light and runs on the workstation. From the
Miniforge Prompt:

```
cd C:\Users\user\projects\PyPSA-GB-default
conda activate pypsa-gb
snakemake --cores 8 resources/network/Historical_2023_etys_year.nc ^
  --config scenario=Historical_2023_etys_year
```

Targeting the finalized network `{scenario}.nc` runs the build and finalize
steps only (jobs 1 to 13), not the solve. The build completes in approximately
4 minutes when the 2023 renewable profiles are already cached from the Zonal and
Reduced runs, and 30 to 60 minutes on a first build that has to compute them.
Confirm `resources/network/Historical_2023_etys_year.nc` exists (approximately
99 MB) and that `Historical_2023_etys_year_network_summary.txt` reports
validation passed.

## Step 2: log in to CX3 (workstation)

```
ssh your_username@login.cx3.hpc.imperial.ac.uk
```

Use the College username, not the email address. Authentication is username and
password (SSH keys are disabled). Accept the host key on first connection. From
off-campus, Zscaler must be connected first.

## Step 3: conda environment on CX3 (one time)

Install a personal conda once per account:

```
module load miniforge/3
miniforge-setup
```

Then activate conda and set conda-forge as the channel:

```
eval "$(~/miniforge3/bin/conda shell.bash hook)"
conda config --set auto_activate_base false
conda config --add channels conda-forge
```

Create a dedicated solve environment. Gurobi is pinned to 11.0.0 to match the
token server; PyPSA and linopy are pinned to the workstation versions:

```
conda create -n etys-solve -c gurobi -c conda-forge ^
  python=3.11 pypsa=1.2.0 linopy=0.6.7 gurobi=11.0.0 highspy netcdf4 -y
```

Test the Gurobi licence before submitting any job:

```
source ~/miniforge3/etc/profile.d/conda.sh
conda activate etys-solve
export GRB_LICENSE_FILE=/sw-eb/software/Gurobi/11.0.0-GCCcore-12.3.0/gurobi.lic
python -c "import gurobipy as g; g.Model(); print('GUROBI OK')"
```

`GUROBI OK` confirms the token server is reachable and the version matches. If
this errors, use HiGHS (troubleshooting section); the result is identical.

## Step 4: stage the network and solve script

On CX3, make a working directory:

```
mkdir -p ~/etys
```

From the workstation, in a second shell, copy the two files across. Each `scp`
prompts for the College password and needs Zscaler connected:

```
scp "C:\Users\user\projects\PyPSA-GB-default\resources\network\Historical_2023_etys_year.nc" your_username@login.cx3.hpc.imperial.ac.uk:~/etys/
scp "C:\Users\user\projects\personalPypsa\scripts\solve_etys_hpc.py" your_username@login.cx3.hpc.imperial.ac.uk:~/etys/
```

## Step 5: the batch job script

On CX3, write `~/etys/etys_solve.pbs` with the following content. A PBS batch
shell does not read `~/.bashrc`, so conda is initialised explicitly with
`source ~/miniforge3/etc/profile.d/conda.sh` and `conda activate`, not the
older `source activate`.

```
#!/bin/bash
#PBS -N etys_solve
#PBS -l select=1:ncpus=12:mem=2000gb
#PBS -l walltime=24:00:00
#PBS -j oe

cd $PBS_O_WORKDIR

source ~/miniforge3/etc/profile.d/conda.sh
conda activate etys-solve

export GRB_LICENSE_FILE=/sw-eb/software/Gurobi/11.0.0-GCCcore-12.3.0/gurobi.lic

python -u solve_etys_hpc.py Historical_2023_etys_year.nc Historical_2023_etys_year_solved_tight.nc gurobi 12 0 0 0 200 1e-6
```

The trailing `0 0 0 200 1e-6` are crossover off, `BarHomogeneous 0`,
`NumericFocus 0`, `BarIterLimit 200`, and the convergence tolerances tightened to
1e-6. ETYS is solved barrier-only, because crossover is intractable at this
problem size; the tightened tolerances give a near-exact interior point. The
"Numerical convergence" section below explains how the procedure arrived at this
and the fallback if the tighter barrier hits numerical trouble.

The `select` line requests one node, 12 cores, and 2000 GB, which routes to the
`largemem72` queue and the 4 TB nodes (the observed build peak is approximately
1.1 TB). Walltime is 24 hours, well inside the 72-hour queue limit. Keep the
request near 2000 GB rather than higher: a larger request waits much longer for a
sufficiently empty node (raise to 2500 to 3000 GB only if the careful
factorisation runs out of memory). To use HiGHS instead, change `gurobi` to
`highs`.

## Numerical convergence (why barrier-only with tightened tolerances)

The full-year ETYS LP has tens of millions of variables. The procedure reached
the recommended invocation through three solves and one log read on 2026-06-01.

1. Crossover off, default tolerances (`gurobi 12`). Job 2899855 finished in
   approximately 2h09m and Gurobi reported `termination=suboptimal` (code 13).
   This was first read as a failed solve. It is not (see point 3).

2. Crossover on (`gurobi 12 -1`, job 2902640), then crossover on plus careful
   numerics (`gurobi 12 -1 1 2`, job 2906105), were tried on the theory that the
   barrier was stalling. Both ran for many hours single-threaded with no result
   and were cancelled. The single-threaded phase is identifiable from the resource
   counters: the increase in `resources_used.cput` divided by the increase in
   `resources_used.walltime` sits near 1.0 (one core), whereas a parallel barrier
   drives that ratio toward the thread count. The `resources_used.cpupercent`
   field is a stale sample and is not reliable.

3. Reading the job 2899855 Gurobi log settled the diagnosis. The barrier is not
   the problem. The log shows "Barrier solved model in 39 iterations ... Optimal
   objective 1.65034312e+10": the barrier converges cleanly in 39 iterations (of a
   200 cap, so the cap never binds) to the optimal objective. The 16.50 billion
   pounds is therefore the LP optimum, not a stalled artifact, and the excess over
   the 12.82 billion pounds of the Zonal and Reduced topologies is the real
   congestion cost of full transmission detail. The `suboptimal` status is a
   technicality: with crossover off, Gurobi returns the barrier interior point
   rather than a vertex.

The actual blocker is crossover. The presolved ETYS LP is 47,437,526 rows by
147,984,806 columns. Crossing the barrier interior point over to an exact vertex
grinds single-threaded for hours and is intractable at this size, which is what
jobs 2902640 and 2906105 hit.

The solution is to stay barrier-only (crossover off) and tighten the convergence
tolerances so the interior point is near-exact. At the default 1e-4 tolerances the
interior point carries an approximately 0.3 percent generation-demand smear;
tightening BarConvTol, FeasibilityTol and OptimalityTol to 1e-6 (the `tol` 9th
argument) shrinks that to negligible, at the cost of a handful more barrier
iterations. The recommended ETYS invocation is therefore `gurobi 12 0 0 0 200 1e-6`.
If the tighter barrier hits "numerical trouble" on the ill-conditioned matrix
(coefficient range approximately 5e-6 to 5e3), add `NumericFocus 2`
(`gurobi 12 0 0 2 200 1e-6`) or relax `tol` to 1e-5.

The script exposes crossover, BarHomogeneous, NumericFocus, BarIterLimit and tol
as the 5th to 9th positional arguments, with defaults `0 0 0 200 1e-4` that
reproduce the workstation `defaults.yaml` behaviour. A healthy barrier-only run
shows, after the approximately 1.1 TB build, `cput` rising faster than `walltime`
(the parallel barrier) and then the job completing in a few hours, with no
single-threaded crossover phase. On retrieval, confirm the network before
post-processing: total generation approximately 274.70 TWh (the demand) and
objective approximately 16.50 billion pounds.

## Step 6: submit and monitor

```
cd ~/etys
qsub etys_solve.pbs
qstat -u your_username
```

`qsub` prints a job ID. In `qstat`, `Q` is queued, `R` is running, and an empty
listing means the job has finished. The merged `#PBS -j oe` log
`~/etys/etys_solve.o<jobid>` only appears when the job finishes, not during the
run, so while it is `R` track progress through the resource counters instead:

```
qstat -f <jobid> | grep -iE 'resources_used.(mem|walltime)|job_state'
```

`resources_used.mem` is the high-water mark. It climbs through the build, peaks
near 1.1 TB, then plateaus once the build is done and the Gurobi barrier takes
over. When the job finishes, read the log:

```
cat ~/etys/etys_solve.o<jobid>
```

Healthy progress in the log, in order: the load line with the bus, line, and
snapshot counts; the numerical-conditioning removals; `LP mode: set all
generators committable = False`; `Solving with gurobi`; Gurobi barrier
iterations; then `Objective (total system cost)` and `Done`.

## Step 7: retrieve and post-process

When `~/etys/Historical_2023_etys_year_solved.nc` exists, copy it back to the
workstation. From the workstation:

```
scp your_username@login.cx3.hpc.imperial.ac.uk:~/etys/Historical_2023_etys_year_solved.nc ^
  C:\Users\user\projects\personalPypsa\results\2023_topology_default\etys_2000bus\
```

Post-process it with the same script and commit reference used for the other
two topologies:

```
cd C:\Users\user\projects\personalPypsa
python system_carbon_intensity.py ^
  --network results\2023_topology_default\etys_2000bus\Historical_2023_etys_year_solved.nc ^
  --out-dir results\2023_topology_default\etys_2000bus ^
  --label "ETYS 2000-bus" ^
  --pypsa-gb-commit 074ea25ec0ca83ecfd3703b2af3a820a25518c50
```

This writes `system_carbon_intensity.csv`, `generation_by_carrier.csv`, and
`manifest.json` into the output directory, in the same format as the Zonal and
Reduced outputs. Check the manifest for unmatched carriers. Adding the ETYS
series to the heatmap dataset is a follow-up: `build_topology_heatmap_data.py`
currently takes the Zonal, Reduced, copperplate, and NESO series, and would
need an ETYS argument added.

## Troubleshooting

Local build OOM at `define_kirchhoff_voltage_constraints` (the 110 GiB array).
Expected on 32 GB; it is the reason the solve runs on HPC. Confirm the NumPy
`Unable to allocate` message names that function, then continue on HPC.

Batch job exits in seconds with `activate: No such file or directory` and
`python: command not found`. The PBS shell did not initialise conda. Use
`source ~/miniforge3/etc/profile.d/conda.sh` followed by `conda activate
etys-solve`, not `module load miniforge/3` plus `source activate`.

Gurobi licence error when the solve starts. The CX3 token server licenses
Gurobi 11, so the environment must carry `gurobi=11.0.0` and
`GRB_LICENSE_FILE` must point to the token-server file. If it stays unresolved,
change the script argument from `gurobi` to `highs`; HiGHS needs no licence and
solves the same linear program.

Out-of-memory failure during the model build. The full-year ETYS Kirchhoff
voltage law peaks at approximately 1.1 TB, so a 920 GB `large72` node is
insufficient (observed: about 553 GB resident, then a failed 207 GiB allocation
at the merge step). Use `mem=2000gb` on the `largemem72` queue. If a run does OOM
at 2000 GB, raise to `mem=3000gb`, still above the 1.1 TB peak with margin. If
the `largemem72` queue wait is too long, first trim an over-large request (a
3500 GB ask can sit for over a day, while approximately 2000 GB backfills onto a
partly-used node in minutes); only if that fails, solve in monthly chunks to cut
the snapshot dimension by approximately 12 times (a myopic rolling horizon; for
GB short-duration storage the effect on carbon intensity is minor).

## Sources

Network dimensions from `Historical_2023_etys_year_network_summary.txt`,
PyPSA-GB commit `074ea25e`. Preprocessing and solver options from
`scripts/solve/solve_network.py` and `config/defaults.yaml` at the same commit.
CX3 node classes, queues, login host, and the conda and Gurobi module details
from the Imperial RCS user guide (`icl-rcs-user-guide.readthedocs.io`),
consulted 2026-05-31.
