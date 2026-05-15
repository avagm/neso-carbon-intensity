"""
Apply an N-percent demand uplift to a PyPSA-GB network and re-solve.

The uplift represents NESO's accounting convention: published carbon
intensities are per kWh delivered, with transmission and distribution
losses included on the denominator. For a system that loses 8 percent
in T&D, the generators must produce `1 / (1 - 0.08) = 1.087` times
the metered demand. Scaling every load by that factor before solving
forces PyPSA-GB to dispatch the extra generation.

Usage
-----
    python scripts/solve_with_uplift.py \
        --in   ../PyPSA-GB/resources/network/Historical_2023_zonal_year_solved.nc \
        --out  results/Historical_2023_zonal_year_uplift/network.nc \
        --loss 0.08

A `manifest.json` is written next to the output network with the input
SHA, loss fraction, snapshot range, and solver wall time, so the result
is reproducible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pypsa


def file_sha256(p: Path, chunk_size: int = 1 << 20) -> str:
    """Hex SHA-256 of a file, streamed."""
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def apply_demand_uplift(n: pypsa.Network, loss_fraction: float) -> float:
    """
    Scale every load's `p_set` (static) and every column of `loads_t.p_set`
    (time-varying) by `1 / (1 - loss_fraction)`.

    Returns the uplift multiplier so it can be logged / manifested.
    """
    if not (0.0 <= loss_fraction < 1.0):
        raise ValueError(f"loss_fraction must be in [0, 1), got {loss_fraction}")
    uplift = 1.0 / (1.0 - loss_fraction)

    if not n.loads.empty:
        n.loads["p_set"] = n.loads["p_set"].astype(float) * uplift

    if not n.loads_t.p_set.empty:
        n.loads_t.p_set = n.loads_t.p_set.astype(float) * uplift

    return uplift


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in", dest="input", required=True, type=Path,
                   help="Solved PyPSA-GB network NetCDF.")
    p.add_argument("--out", required=True, type=Path,
                   help="Output path for the re-solved network NetCDF.")
    p.add_argument("--loss", type=float, default=0.08,
                   help="Loss fraction in [0, 1). Default 0.08 (NESO).")
    p.add_argument("--solver", default="highs",
                   help="LP solver name (highs, gurobi).")
    args = p.parse_args()

    print(f"loading {args.input}")
    in_sha = file_sha256(args.input)
    print(f"  sha256={in_sha[:12]}...")
    n = pypsa.Network(str(args.input))
    n_buses, n_snaps = len(n.buses), len(n.snapshots)
    print(f"  {n_buses} buses, {n_snaps} snapshots, "
          f"{len(n.generators)} generators, {len(n.loads)} loads")

    uplift = apply_demand_uplift(n, args.loss)
    print(f"applied demand uplift x{uplift:.4f} "
          f"(representing {args.loss * 100:.1f}% system losses)")

    print(f"solving with {args.solver}")
    t0 = time.time()
    n.optimize(solver_name=args.solver)
    solve_seconds = time.time() - t0
    print(f"  solver wall time: {solve_seconds:.1f}s")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"writing {args.out}")
    n.export_to_netcdf(str(args.out))

    manifest = {
        "input_path":   str(args.input),
        "input_sha256": in_sha,
        "output_path":  str(args.out),
        "loss_fraction": args.loss,
        "uplift_multiplier": uplift,
        "solver": args.solver,
        "solver_wall_seconds": round(solve_seconds, 1),
        "n_buses": n_buses,
        "n_snapshots": n_snaps,
        "snapshot_first": str(n.snapshots[0]),
        "snapshot_last": str(n.snapshots[-1]),
    }
    (args.out.parent / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print("done")


if __name__ == "__main__":
    main()
