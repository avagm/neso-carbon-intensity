"""
Standalone faithful solve for the finalized ETYS full-year network, for HPC.

Why this exists
---------------
The full-year ETYS LP (2,130 buses x 8,760 snapshots) cannot be built on a
32 GB workstation: PyPSA's cycle-based Kirchhoff voltage law materialises a
dense (snapshots x lines x cycles) coefficient tensor of about 110 GiB during
model construction, before the solver is ever invoked, and the construction
peaks near 1.1 TB. The solve must run on a large-memory node (for example an
Imperial RCS CX3 largemem node, request near 2000 GB).

Rather than transfer the whole PyPSA-GB clone plus the multi-GB ERA5 cutout to
HPC and drive Snakemake there, this script loads the already-finalised network
(99 MB) and reproduces, line for line, the preprocessing that
PyPSA-GB scripts/solve/solve_network.py (commit 074ea25e) applies before
n.optimize(). The result is therefore directly comparable to the Zonal 17-bus
and Reduced 32-bus default-settings solves.

Faithful reproduction of the solve_network rule
-----------------------------------------------
1. improve_numerical_conditioning: drop generators, storage units and links
   with p_nom < 0.1 MW (excluding load_shedding), and clamp transformer
   reactance values > 10.0 to 10.0. Copied verbatim from the rule.
2. LP mode: set all generators committable = False (config solve_mode: LP).
3. Must-run preserved: p_min_pu is left unchanged (remove_must_run defaults
   to False in the default config).
4. Transmission relaxation: a no-op under the default config
   (min_line_s_nom = 0, min_transformer_s_nom = 0, capacity_scale = 1.0), so it
   is intentionally omitted here. If a scenario ever sets those, this script
   would need the same step added.

Solver options match config/defaults.yaml solver block exactly (Gurobi
barrier, crossover off, relaxed tolerances). Gurobi and HiGHS solve the same
LP; with crossover off the barrier returns an interior optimal point.

Usage
-----
    python solve_etys_hpc.py INPUT.nc OUTPUT.nc [gurobi|highs] [threads] [crossover]

Defaults: gurobi, 12 threads, crossover 0 (off, matching defaults.yaml). Pass
crossover=-1 to let Gurobi clean a stalled or sub-optimal barrier point up to a
feasible optimal vertex (needed for the full ETYS LP, which stalls the barrier
under the relaxed default tolerances). Set GRB_LICENSE_FILE to the licence the
Gurobi build uses (on CX3 the Gurobi module points it at the campus token
server, TOKENSERVER=gurobi.cc.ic.ac.uk).
"""

import sys
import time

import pypsa


def improve_numerical_conditioning(network):
    """Verbatim from PyPSA-GB scripts/solve/solve_network.py (commit 074ea25e).

    Removes negligible (< 0.1 MW) generators, storage units and links, and
    clamps transformer reactance above 10.0 to 10.0, to keep the LP coefficient
    range bounded. Mutates the network in place.
    """
    min_pnom = 0.1  # MW

    # 1. Remove very small generators (excluding load_shedding)
    non_ls_gens = network.generators[network.generators.carrier != "load_shedding"]
    small_gens = non_ls_gens[non_ls_gens.p_nom < min_pnom]
    if len(small_gens) > 0:
        print(f"  Removing {len(small_gens)} generators with p_nom < {min_pnom} MW "
              f"(total {small_gens.p_nom.sum():.2f} MW)", flush=True)
        for attr in ["p_max_pu", "p_min_pu", "marginal_cost"]:
            df = getattr(network.generators_t, attr, None)
            if df is not None and len(df) > 0:
                cols = [c for c in small_gens.index if c in df.columns]
                if cols:
                    df.drop(columns=cols, inplace=True)
        network.generators.drop(small_gens.index, inplace=True)

    # 2. Remove very small storage units
    small_storage = network.storage_units[network.storage_units.p_nom < min_pnom]
    if len(small_storage) > 0:
        print(f"  Removing {len(small_storage)} storage units with p_nom < {min_pnom} MW "
              f"(total {small_storage.p_nom.sum():.2f} MW)", flush=True)
        for attr in ["p_max_pu", "p_min_pu", "state_of_charge_set", "inflow"]:
            df = getattr(network.storage_units_t, attr, None)
            if df is not None and len(df) > 0:
                cols = [c for c in small_storage.index if c in df.columns]
                if cols:
                    df.drop(columns=cols, inplace=True)
        network.storage_units.drop(small_storage.index, inplace=True)

    # 3. Remove very small links (but not HVDC interconnectors above the floor)
    if len(network.links) > 0:
        small_links = network.links[network.links.p_nom < min_pnom]
        if len(small_links) > 0:
            print(f"  Removing {len(small_links)} links with p_nom < {min_pnom} MW "
                  f"(total {small_links.p_nom.sum():.2f} MW)", flush=True)
            for attr in ["p_max_pu", "p_min_pu", "efficiency"]:
                df = getattr(network.links_t, attr, None)
                if df is not None and len(df) > 0:
                    cols = [c for c in small_links.index if c in df.columns]
                    if cols:
                        df.drop(columns=cols, inplace=True)
            network.links.drop(small_links.index, inplace=True)

    # 4. Clamp transformer reactance to a reasonable range
    if len(network.transformers) > 0:
        high_x = network.transformers.x > 10.0
        n_high_x = int(high_x.sum())
        if n_high_x > 0:
            print(f"  Clamping {n_high_x} transformer reactance values "
                  f"(max {network.transformers.loc[high_x, 'x'].max():.1f}) to 10.0",
                  flush=True)
            network.transformers.loc[high_x, "x"] = 10.0


def solver_options_for(solver_name, threads, crossover=0):
    """Exactly the options _get_solver_config builds from defaults.yaml.

    crossover defaults to 0 (off), matching defaults.yaml. Pass crossover=-1 to
    let Gurobi run crossover after the barrier; this recovers a feasible optimal
    vertex when the barrier stalls sub-optimally, as it does on the full ETYS LP.
    """
    if solver_name == "gurobi":
        return {
            "threads": threads,
            "method": 2,
            "crossover": crossover,
            "BarHomogeneous": 0,
            "BarConvTol": 1.0e-4,
            "FeasibilityTol": 1.0e-4,
            "OptimalityTol": 1.0e-4,
            "NumericFocus": 0,
            "ScaleFlag": 2,
            "DualReductions": 0,
            "BarIterLimit": 200,
        }
    if solver_name == "highs":
        return {"threads": threads, "log_to_console": False}
    return {"threads": threads}


def main():
    in_path = sys.argv[1] if len(sys.argv) > 1 else "Historical_2023_etys_year.nc"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "Historical_2023_etys_year_solved.nc"
    solver_name = sys.argv[3] if len(sys.argv) > 3 else "gurobi"
    threads = int(sys.argv[4]) if len(sys.argv) > 4 else 12
    crossover = int(sys.argv[5]) if len(sys.argv) > 5 else 0

    t_start = time.time()
    print(f"Loading network from {in_path}", flush=True)
    n = pypsa.Network(in_path)
    print(f"  {len(n.buses)} buses, {len(n.lines)} lines, "
          f"{len(n.transformers)} transformers, {len(n.links)} links, "
          f"{len(n.generators)} generators, {len(n.snapshots)} snapshots", flush=True)

    print("Improving numerical conditioning (verbatim from solve_network.py)", flush=True)
    improve_numerical_conditioning(n)

    if "committable" in n.generators.columns:
        n.generators["committable"] = False
        print("LP mode: set all generators committable = False", flush=True)

    n_must_run = int((n.generators["p_min_pu"] > 0).sum()) if "p_min_pu" in n.generators.columns else 0
    print(f"Preserving must-run: {n_must_run} generators with p_min_pu > 0", flush=True)

    opts = solver_options_for(solver_name, threads, crossover)
    print(f"Solving with {solver_name}, options: {opts}", flush=True)
    t_solve = time.time()
    status, termination = n.optimize(solver_name=solver_name, solver_options=opts)
    print(f"status={status} termination={termination} "
          f"solve_time={time.time() - t_solve:.1f}s", flush=True)

    if status != "ok":
        raise SystemExit(f"Optimisation failed: status={status} termination={termination}")
    if termination != "optimal":
        print(f"WARNING: termination is '{termination}', not 'optimal'. The barrier may "
              f"not have fully converged (sub-optimal, possibly slightly infeasible point). "
              f"Re-run with crossover on (5th arg = -1); if it still stalls, raise "
              f"NumericFocus / set BarHomogeneous 1.", flush=True)

    print(f"Objective (total system cost): {n.objective:,.2f}", flush=True)

    print(f"Saving solved network to {out_path}", flush=True)
    n.export_to_netcdf(out_path)
    print(f"Done in {time.time() - t_start:.1f}s total", flush=True)


if __name__ == "__main__":
    main()
