"""
Extract bus / line / link geometry from a solved PyPSA-GB network.

Produces three CSVs plus a manifest sufficient to plot the topology on a
map: bus positions with both EPSG:27700 (British National Grid easting,
northing in metres) and WGS84 (longitude, latitude in degrees) coordinates,
and the lines / links table with their bus0, bus1 endpoints.

PyPSA-GB stores `n.buses.x` and `n.buses.y` in EPSG:27700 (verified against
the upstream `data/network/reduced_network/buses_wgs84_backup.csv` which
carries the same names at the lon / lat equivalents of the on-network BNG
positions). For any standard web-mapping library a lon / lat column is
needed, so the script writes both.

Interconnector buses (carrier `AC` with `country` set to a non-GB value and
a name like `HVDC_External_<country>_<endpoint>`) are kept in the output;
they are part of the modelled topology. Their BNG positions sit off the GB
coast at the foreign endpoint location.

CLI
---
    python extract_topology_geometry.py \
        --network path/to/Historical_2023_zonal_year_solved.nc \
        --out-dir out/topology/zonal_17bus \
        --label "Zonal 17-bus"

Outputs:
    buses.csv     name, v_nom, carrier, country, x_bng, y_bng, lon, lat
    lines.csv     name, bus0, bus1, s_nom_mw, length_km (if any AC lines)
    links.csv     name, bus0, bus1, carrier, p_nom_mw, length_km
    manifest.json input SHA-256, PyPSA-GB commit, bus / line / link counts
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pypsa
from pyproj import Transformer


BNG_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    """Streamed hex SHA-256 of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def buses_table(n: pypsa.Network) -> pd.DataFrame:
    """Bus table with both BNG and WGS84 coordinates."""
    buses = n.buses[["v_nom", "carrier", "x", "y"]].copy()
    buses["country"] = n.buses.get("country", pd.Series("", index=n.buses.index))
    # Convert BNG (metres) to WGS84 (degrees). always_xy=True keeps the
    # transformer as (x, y) -> (lon, lat).
    lon, lat = BNG_TO_WGS84.transform(buses["x"].to_numpy(),
                                       buses["y"].to_numpy())
    out = pd.DataFrame({
        "name": buses.index,
        "v_nom_kv": buses["v_nom"].to_numpy(),
        "carrier": buses["carrier"].to_numpy(),
        "country": buses["country"].to_numpy(),
        "x_bng": buses["x"].to_numpy(),
        "y_bng": buses["y"].to_numpy(),
        "lon": lon,
        "lat": lat,
    })
    return out


def lines_table(n: pypsa.Network) -> pd.DataFrame:
    """Lines table (AC transmission). May be empty on the Zonal network."""
    if n.lines.empty:
        return pd.DataFrame(columns=["name", "bus0", "bus1", "s_nom_mw", "length_km"])
    out = pd.DataFrame({
        "name": n.lines.index,
        "bus0": n.lines["bus0"].to_numpy(),
        "bus1": n.lines["bus1"].to_numpy(),
        "s_nom_mw": n.lines["s_nom"].astype(float).to_numpy(),
        "length_km": n.lines.get("length",
                                 pd.Series(0.0, index=n.lines.index))
                              .astype(float).to_numpy(),
    })
    return out


def links_table(n: pypsa.Network) -> pd.DataFrame:
    """Links table (DC interconnectors and any inter-bus DC link)."""
    if n.links.empty:
        return pd.DataFrame(columns=["name", "bus0", "bus1", "carrier",
                                      "p_nom_mw", "length_km"])
    out = pd.DataFrame({
        "name": n.links.index,
        "bus0": n.links["bus0"].to_numpy(),
        "bus1": n.links["bus1"].to_numpy(),
        "carrier": n.links["carrier"].to_numpy(),
        "p_nom_mw": n.links["p_nom"].astype(float).to_numpy(),
        "length_km": n.links.get("length",
                                  pd.Series(0.0, index=n.links.index))
                              .astype(float).to_numpy(),
    })
    return out


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network", required=True, type=Path,
                   help="Path to a solved PyPSA-GB NetCDF network.")
    p.add_argument("--out-dir", required=True, type=Path,
                   help="Directory for the CSV and manifest outputs.")
    p.add_argument("--label", required=True,
                   help="Human-readable label, e.g. 'Zonal 17-bus'.")
    p.add_argument("--pypsa-gb-commit", default=None,
                   help="PyPSA-GB clone commit SHA, recorded in the manifest.")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if not args.network.exists():
        sys.exit(f"network not found: {args.network}")

    print(f"loading {args.network}")
    n = pypsa.Network(str(args.network))
    print(f"  {len(n.buses)} buses, {len(n.lines)} lines, "
          f"{len(n.links)} links")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    buses = buses_table(n)
    lines = lines_table(n)
    links = links_table(n)
    buses.to_csv(args.out_dir / "buses.csv", index=False)
    lines.to_csv(args.out_dir / "lines.csv", index=False)
    links.to_csv(args.out_dir / "links.csv", index=False)

    # Country breakdown for visibility in the manifest. PyPSA-GB tags GB
    # buses with country == "GB" and interconnector endpoint buses with the
    # foreign country name (Netherlands, France, Belgium, Norway, Ireland,
    # Denmark).
    country_counts = (buses["country"].fillna("").astype(str)
                                       .value_counts().to_dict())
    gb_buses = int((buses["country"].astype(str) == "GB").sum())
    foreign_buses = int(len(buses) - gb_buses)

    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "extract_topology_geometry.py",
        "label": args.label,
        "network_path": str(args.network),
        "network_basename": args.network.name,
        "network_sha256": file_sha256(args.network),
        "pypsa_gb_commit": args.pypsa_gb_commit,
        "counts": {
            "buses_total": int(len(buses)),
            "buses_gb": gb_buses,
            "buses_foreign_interconnector": foreign_buses,
            "lines": int(len(lines)),
            "links": int(len(links)),
        },
        "bus_country_counts": country_counts,
        "bbox_bng_metres": {
            "x_min": round(float(buses["x_bng"].min()), 1),
            "x_max": round(float(buses["x_bng"].max()), 1),
            "y_min": round(float(buses["y_bng"].min()), 1),
            "y_max": round(float(buses["y_bng"].max()), 1),
        },
        "bbox_wgs84_degrees": {
            "lon_min": round(float(buses["lon"].min()), 4),
            "lon_max": round(float(buses["lon"].max()), 4),
            "lat_min": round(float(buses["lat"].min()), 4),
            "lat_max": round(float(buses["lat"].max()), 4),
        },
        "coordinate_reference_systems": {
            "x_bng,y_bng": "EPSG:27700 (British National Grid, metres)",
            "lon,lat": "EPSG:4326 (WGS84 longitude, latitude in degrees)",
        },
        "software": {
            "pypsa": pypsa.__version__,
            "python": sys.version.split()[0],
        },
    }
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    c = manifest["counts"]
    bb = manifest["bbox_wgs84_degrees"]
    print(f"{args.label}: {c['buses_gb']} GB buses + {c['buses_foreign_interconnector']} interconnector buses, "
          f"{c['lines']} lines, {c['links']} links")
    print(f"  bounding box (WGS84): "
          f"lon [{bb['lon_min']:.2f}, {bb['lon_max']:.2f}], "
          f"lat [{bb['lat_min']:.2f}, {bb['lat_max']:.2f}]")
    print(f"outputs -> {args.out_dir}")


if __name__ == "__main__":
    main()
