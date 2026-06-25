"""
Assemble the topology-comparison heatmap dataset.

Takes the two system carbon intensity series (Zonal 17-bus and Reduced 32-bus,
produced by system_carbon_intensity.py) and the NESO national carbon intensity
series (produced by pull_neso_2023.py), aligns them on a common hourly UTC
index, and writes the dataset used to build the comparative heatmap of NESO
actual versus 17-bus versus 32-bus.

Optionally also accepts a fourth series, the Reduced 32-bus soft-copperplate
re-solve, via --copperplate. When supplied, the series is added to the dataset
alongside the others, and a `reduced_minus_copperplate` difference column and
pivot are added. That difference is the transmission-constraint impact on
hourly CI: positive values mean the 32-bus line constraints push intensity up
versus the unconstrained dispatch.

This step does no validation scoring. It aligns and reshapes the series so the
comparison can be visualised; it does not judge the model against NESO.

CLI
---
    python build_topology_heatmap_data.py \
        --zonal       out/zonal_17bus/system_carbon_intensity.csv \
        --reduced     out/reduced_32bus/system_carbon_intensity.csv \
        --copperplate out/reduced_32bus_copperplate/system_carbon_intensity.csv \
        --neso        out/neso_2023/national_intensity.csv \
        --out-dir     out

Writes into the output directory:
    heatmap_input.csv                          wide hourly UTC table
    heatmap_pivot_neso_actual.csv              date by hour-of-day grid
    heatmap_pivot_zonal_17bus.csv              date by hour-of-day grid
    heatmap_pivot_reduced_32bus.csv            date by hour-of-day grid
    heatmap_pivot_reduced_minus_zonal.csv      32-bus minus 17-bus grid
    (with --copperplate, also:)
    heatmap_pivot_reduced_32bus_copperplate.csv    date by hour-of-day grid
    heatmap_pivot_reduced_minus_copperplate.csv    32-bus minus its
                                                   soft-copperplate grid
    assembly_manifest.json                     inputs, alignment, headline numbers

All carbon intensity values are in gCO2 per kWh.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


def load_pypsa_ci(path: Path) -> pd.Series:
    """Hourly system carbon intensity from a system_carbon_intensity.csv."""
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    if "system_gCO2_per_kWh" not in df.columns:
        raise ValueError(f"{path} has no 'system_gCO2_per_kWh' column")
    s = df["system_gCO2_per_kWh"].astype(float)
    # PyPSA-GB snapshots are tz-naive. Treat them as UTC, the convention the
    # project already uses when aligning model output against NESO.
    s.index = pd.to_datetime(s.index, utc=True)
    return s.sort_index()


def load_neso(path: Path) -> pd.Series:
    """Hourly NESO national actual carbon intensity from national_intensity.csv."""
    df = pd.read_csv(path)
    if "from" not in df.columns or "actual" not in df.columns:
        raise ValueError(f"{path} must have 'from' and 'actual' columns")
    df["from"] = pd.to_datetime(df["from"], utc=True)
    # NESO publishes half-hourly; average to hourly to match the model.
    return (df.set_index("from")["actual"].astype(float)
              .sort_index().resample("h").mean())


def day_hour_pivot(s: pd.Series) -> pd.DataFrame:
    """Reshape an hourly UTC series into a date (rows) by hour-of-day (cols) grid."""
    grid = pd.DataFrame({
        "date": s.index.date,
        "hour": s.index.hour,
        "value": s.to_numpy(),
    })
    pivot = grid.pivot(index="date", columns="hour", values="value")
    pivot.index.name = "date"
    pivot.columns.name = "hour"
    return pivot


def _stats(s: pd.Series) -> dict:
    """Descriptive statistics for one aligned series."""
    return {
        "mean": round(float(s.mean()), 3),
        "min": round(float(s.min()), 3),
        "max": round(float(s.max()), 3),
        "std": round(float(s.std()), 3),
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Assemble the 17 vs 32 bus heatmap dataset, optionally "
                    "including the Reduced 32-bus soft-copperplate re-solve. "
                    "See module docstring.")
    p.add_argument("--zonal", required=True, type=Path,
                   help="Zonal 17-bus system_carbon_intensity.csv")
    p.add_argument("--reduced", required=True, type=Path,
                   help="Reduced 32-bus system_carbon_intensity.csv")
    p.add_argument("--copperplate", type=Path, default=None,
                   help="Optional Reduced 32-bus soft-copperplate "
                        "system_carbon_intensity.csv. When supplied, the "
                        "series is included in the dataset.")
    p.add_argument("--neso", required=True, type=Path,
                   help="NESO national_intensity.csv (from pull_neso_2023.py)")
    p.add_argument("--out-dir", required=True, type=Path)
    args = p.parse_args()

    inputs_to_check = [("zonal", args.zonal), ("reduced", args.reduced),
                       ("neso", args.neso)]
    if args.copperplate is not None:
        inputs_to_check.append(("copperplate", args.copperplate))
    for label, path in inputs_to_check:
        if not path.exists():
            raise SystemExit(f"{label} input not found: {path}")

    zonal = load_pypsa_ci(args.zonal)
    reduced = load_pypsa_ci(args.reduced)
    neso = load_neso(args.neso)
    copperplate = (load_pypsa_ci(args.copperplate)
                    if args.copperplate is not None else None)

    # Align all series on the hours they all cover.
    join_series = {
        "neso_actual": neso,
        "zonal_17bus": zonal,
        "reduced_32bus": reduced,
    }
    if copperplate is not None:
        join_series["reduced_32bus_copperplate"] = copperplate
    wide = pd.concat(join_series, axis=1, join="inner").dropna()
    if wide.empty:
        raise SystemExit("no overlapping hours across the inputs; "
                         "check their date ranges")
    wide["reduced_minus_zonal"] = wide["reduced_32bus"] - wide["zonal_17bus"]
    if copperplate is not None:
        wide["reduced_minus_copperplate"] = (
            wide["reduced_32bus"] - wide["reduced_32bus_copperplate"])
    wide.index.name = "timestamp_utc"

    args.out_dir.mkdir(parents=True, exist_ok=True)
    wide.to_csv(args.out_dir / "heatmap_input.csv")

    pivot_specs = [
        ("neso_actual", "heatmap_pivot_neso_actual.csv"),
        ("zonal_17bus", "heatmap_pivot_zonal_17bus.csv"),
        ("reduced_32bus", "heatmap_pivot_reduced_32bus.csv"),
        ("reduced_minus_zonal", "heatmap_pivot_reduced_minus_zonal.csv"),
    ]
    if copperplate is not None:
        pivot_specs.extend([
            ("reduced_32bus_copperplate",
             "heatmap_pivot_reduced_32bus_copperplate.csv"),
            ("reduced_minus_copperplate",
             "heatmap_pivot_reduced_minus_copperplate.csv"),
        ])
    for column, filename in pivot_specs:
        day_hour_pivot(wide[column]).to_csv(args.out_dir / filename)

    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "build_topology_heatmap_data.py",
        "inputs": {
            "zonal": str(args.zonal),
            "reduced": str(args.reduced),
            "neso": str(args.neso),
        },
        "hours_per_input": {
            "zonal": int(len(zonal)),
            "reduced": int(len(reduced)),
            "neso": int(len(neso)),
        },
        "hours_aligned": int(len(wide)),
        "timestamp_first": str(wide.index[0]),
        "timestamp_last": str(wide.index[-1]),
        "series_stats_gCO2_per_kWh": {
            "neso_actual": _stats(wide["neso_actual"]),
            "zonal_17bus": _stats(wide["zonal_17bus"]),
            "reduced_32bus": _stats(wide["reduced_32bus"]),
        },
        "topology_difference_gCO2_per_kWh": {
            "mean_reduced_minus_zonal":
                round(float(wide["reduced_minus_zonal"].mean()), 3),
            "mean_abs_reduced_minus_zonal":
                round(float(wide["reduced_minus_zonal"].abs().mean()), 3),
        },
        "mean_offset_from_neso_gCO2_per_kWh": {
            "zonal_17bus":
                round(float((wide["zonal_17bus"] - wide["neso_actual"]).mean()), 3),
            "reduced_32bus":
                round(float((wide["reduced_32bus"] - wide["neso_actual"]).mean()), 3),
        },
    }
    if copperplate is not None:
        manifest["inputs"]["copperplate"] = str(args.copperplate)
        manifest["hours_per_input"]["copperplate"] = int(len(copperplate))
        manifest["series_stats_gCO2_per_kWh"]["reduced_32bus_copperplate"] = (
            _stats(wide["reduced_32bus_copperplate"]))
        manifest["transmission_constraint_impact_gCO2_per_kWh"] = {
            "mean_reduced_minus_copperplate":
                round(float(wide["reduced_minus_copperplate"].mean()), 3),
            "mean_abs_reduced_minus_copperplate":
                round(float(wide["reduced_minus_copperplate"].abs().mean()), 3),
        }
        manifest["mean_offset_from_neso_gCO2_per_kWh"]["reduced_32bus_copperplate"] = (
            round(float((wide["reduced_32bus_copperplate"]
                         - wide["neso_actual"]).mean()), 3))

    (args.out_dir / "assembly_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    stats = manifest["series_stats_gCO2_per_kWh"]
    print(f"aligned {len(wide)} hours ({wide.index[0]} .. {wide.index[-1]})")
    print(f"  NESO actual                 mean {stats['neso_actual']['mean']:8.2f} gCO2/kWh")
    print(f"  Zonal 17-bus                mean {stats['zonal_17bus']['mean']:8.2f} gCO2/kWh")
    print(f"  Reduced 32-bus              mean {stats['reduced_32bus']['mean']:8.2f} gCO2/kWh")
    if copperplate is not None:
        print(f"  Reduced 32-bus copperplate  mean "
              f"{stats['reduced_32bus_copperplate']['mean']:8.2f} gCO2/kWh")
    print(f"  mean (32-bus minus 17-bus)              "
          f"{manifest['topology_difference_gCO2_per_kWh']['mean_reduced_minus_zonal']:+.2f} gCO2/kWh")
    if copperplate is not None:
        print(f"  mean (32-bus minus 32-bus copperplate)  "
              f"{manifest['transmission_constraint_impact_gCO2_per_kWh']['mean_reduced_minus_copperplate']:+.2f} gCO2/kWh")
    print(f"outputs -> {args.out_dir}")


if __name__ == "__main__":
    main()
