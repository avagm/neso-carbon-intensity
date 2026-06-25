"""
Copperplate variants for a PyPSA-GB network.

PyPSA-GB ships with three network models (ETYS ~2000 buses, Reduced 32 buses,
Zonal 17 buses) but no 1-bus copperplate. Two ways to approximate one:

  1. soft_copperplate(n)
       Keep the existing bus structure but raise every line/link s_nom (and
       p_nom for links) to a huge value. The network is still solved over the
       full topology; only the transmission constraint is effectively removed.
       Useful for carbon-intensity work because it preserves where each
       generator and load sits while eliminating congestion.

  2. hard_copperplate(n)
       Collapse every bus to a single cluster using PyPSA's clustering API
       (`network.cluster.cluster_by_busmap`). Result is a 1-bus network with
       aggregated generators, loads, and storage. Lines are removed. Useful as
       a sanity-check baseline (system-wide intensity = total emissions / total
       generation). Loses all spatial info.

Both functions return a *new* network and leave the input untouched.

CLI
---
    python copperplate.py --in path/to/solved_network.nc --out-soft soft.nc --out-hard hard.nc

Imports a saved PyPSA network in NetCDF format and writes both variants.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pypsa


LARGE_CAP = 1e7  # MW. Big enough to never bind in GB-scale problems.


def soft_copperplate(n: pypsa.Network, large_cap: float = LARGE_CAP) -> pypsa.Network:
    """
    Return a copy of `n` with every transmission element relaxed.

    Lines: `s_nom` set to `large_cap`, `s_nom_extendable` left as is.
    Links: `p_nom` set to `large_cap`, `p_nom_extendable` left as is.
    Transformers: `s_nom` set to `large_cap` (rare in PyPSA-GB but handled).

    Existing flows, generator capacities, load profiles, and bus topology are
    untouched. Re-solve `out` to get the relaxed dispatch.
    """
    out = n.copy()

    if not out.lines.empty:
        out.lines["s_nom"] = large_cap
        out.lines["s_nom_min"] = 0.0
        out.lines["s_nom_max"] = large_cap

    if not out.links.empty:
        out.links["p_nom"] = large_cap
        out.links["p_nom_min"] = 0.0
        out.links["p_nom_max"] = large_cap

    if not out.transformers.empty:
        out.transformers["s_nom"] = large_cap
        out.transformers["s_nom_min"] = 0.0
        out.transformers["s_nom_max"] = large_cap

    return out


def hard_copperplate(n: pypsa.Network, cluster_label: str = "GB") -> pypsa.Network:
    """
    Return a 1-bus aggregation of `n`.

    Every bus is mapped to a single cluster. Generators, loads, storage units,
    and stores are summed. Lines are dropped because they would all be
    self-loops on the single bus.

    Notes
    -----
    - PyPSA's clustering API returns a `Clustering` object for the modern API
      (`n.cluster.cluster_by_busmap`) and a `Network` directly for older
      versions. We handle both.
    - Carriers, snapshots, and time-series shapes are preserved.
    """
    busmap = n.buses.index.to_series().map(lambda _: cluster_label).rename("cluster")

    cluster_method = getattr(getattr(n, "cluster", None), "cluster_by_busmap", None)
    if cluster_method is not None:
        clustered = cluster_method(busmap)
        out = clustered.network if hasattr(clustered, "network") else clustered
    else:
        # Fallback for older PyPSA versions that exposed clustering at module level.
        from pypsa.clustering.spatial import get_clustering_from_busmap

        out = get_clustering_from_busmap(n, busmap).network

    return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="input", required=True, type=Path,
                        help="Path to a PyPSA NetCDF file.")
    parser.add_argument("--out-soft", type=Path, default=None,
                        help="If given, write the soft-copperplate variant here.")
    parser.add_argument("--out-hard", type=Path, default=None,
                        help="If given, write the hard-copperplate (1-bus) variant here.")
    parser.add_argument("--large-cap", type=float, default=LARGE_CAP,
                        help=f"Capacity used by the soft variant (default {LARGE_CAP:g} MW).")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    n = pypsa.Network(str(args.input))

    if args.out_soft is not None:
        n_soft = soft_copperplate(n, large_cap=args.large_cap)
        n_soft.export_to_netcdf(str(args.out_soft))
        print(f"soft copperplate -> {args.out_soft}  ({len(n_soft.buses)} buses)")

    if args.out_hard is not None:
        n_hard = hard_copperplate(n)
        n_hard.export_to_netcdf(str(args.out_hard))
        print(f"hard copperplate -> {args.out_hard}  ({len(n_hard.buses)} buses)")

    if args.out_soft is None and args.out_hard is None:
        print("Nothing to do. Pass --out-soft and/or --out-hard.")


if __name__ == "__main__":
    main()
