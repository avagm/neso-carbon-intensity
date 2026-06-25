"""Apply an N-percent demand uplift to a solved PyPSA-GB network and re-solve.

Scales loads by 1 / (1 - loss) so the LP dispatches enough generation
to cover NESO's accounting of transmission + distribution losses.
Writes manifest.json alongside the output.

    python solve_with_uplift.py --in solved.nc --out uplift/network.nc --loss 0.08
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pypsa


def file_sha256(p: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def apply_demand_uplift(n: pypsa.Network, loss_fraction: float) -> float:
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
    p.add_argument("--in",  dest="input", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--loss", type=float, default=0.08)
    p.add_argument("--solver", default="highs")
    args = p.parse_args()

    in_sha = file_sha256(args.input)
    n = pypsa.Network(str(args.input))
    n_buses, n_snaps = len(n.buses), len(n.snapshots)
    print(f"{args.input} ({n_buses} buses, {n_snaps} snapshots)")

    uplift = apply_demand_uplift(n, args.loss)
    print(f"uplift x{uplift:.4f}; solving with {args.solver}")

    t0 = time.time()
    n.optimize(solver_name=args.solver)
    solve_seconds = time.time() - t0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    n.export_to_netcdf(str(args.out))

    (args.out.parent / "manifest.json").write_text(json.dumps({
        "input_path": str(args.input),
        "input_sha256": in_sha,
        "output_path": str(args.out),
        "loss_fraction": args.loss,
        "uplift_multiplier": uplift,
        "solver": args.solver,
        "solver_wall_seconds": round(solve_seconds, 1),
        "n_buses": n_buses,
        "n_snapshots": n_snaps,
        "snapshot_first": str(n.snapshots[0]),
        "snapshot_last":  str(n.snapshots[-1]),
    }, indent=2), encoding="utf-8")
    print(f"done in {solve_seconds:.1f}s -> {args.out}")


if __name__ == "__main__":
    main()
