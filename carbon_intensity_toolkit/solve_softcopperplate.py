"""
Apply soft copperplate to a solved PyPSA-GB network and re-solve.

The soft copperplate (see copperplate.py) keeps the bus topology, generators
and loads exactly as in the input network, but raises every line, link and
transformer s_nom to 10^7 MW. Re-solving the LP then yields the dispatch the
system would produce under unconstrained transmission. The result is the
"no transmission constraint" reference for any topology-sensitivity study.

The output network is exported as a NetCDF (.nc) and can be fed straight into
system_carbon_intensity.py for post-processing.

Usage
-----
    python solve_softcopperplate.py \\
        --in  path/to/Historical_2023_reduced_year_solved.nc \\
        --out out/reduced_32bus_copperplate/network.nc \\
        --solver gurobi
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pypsa

from copperplate import soft_copperplate


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in", dest="input", required=True, type=Path,
                   help="Solved PyPSA-GB network (NetCDF) to copperplate.")
    p.add_argument("--out", required=True, type=Path,
                   help="Output path for the re-solved network.")
    p.add_argument("--solver", default="gurobi",
                   help="LP solver name (gurobi, highs). Defaults to gurobi.")
    args = p.parse_args()

    print(f"loading {args.input}")
    n = pypsa.Network(str(args.input))
    print(f"  {len(n.buses)} buses, {len(n.snapshots)} snapshots, "
          f"{len(n.generators)} generators")

    print("applying soft copperplate (s_nom -> 1e7 MW on lines/links/transformers)")
    n_soft = soft_copperplate(n)

    print(f"solving with {args.solver}")
    n_soft.optimize(solver_name=args.solver)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"writing {args.out}")
    n_soft.export_to_netcdf(str(args.out))
    print("done")


if __name__ == "__main__":
    main()
