"""
Standardised plot pack comparing carbon-intensity time series from one
or more PyPSA-GB runs against the NESO national truth.

Inputs
------
- One or more `--series LABEL=PATH/system_summary.csv` pairs. Each CSV
  must have an `index` column parseable as UTC datetime and a column
  `system_gCO2_per_kWh`. Output of `carbon_intensity.py`.
- Optional `--neso PATH/national_intensity.csv` with columns `from`
  (ISO 8601 UTC) and `actual` (gCO2 per kWh). Output of
  `scripts/pull_neso_2023.py`.

Outputs
-------
PNGs and a `summary_stats.csv` under `--out-dir`:

    system_intensity_timeseries.png
    monthly_mean_bar.png
    intensity_duration_curve.png
    diurnal_profile.png
    pypsa_vs_neso_scatter.png    (one panel per PyPSA series, if NESO supplied)
    summary_stats.csv

CLI
---
    python deliverables/visualise.py \
        --series "Zonal 17-bus=results/Historical_2023_zonal_year_uplift/system_summary.csv" \
        --series "Reduced 32-bus=results/Historical_2023_reduced_year_uplift/system_summary.csv" \
        --neso results/neso_2023/national_intensity.csv \
        --out-dir results/comparison_2023
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


NESO_LABEL = "NESO actual"


def parse_series_arg(s: str) -> tuple[str, Path]:
    """`LABEL=PATH` -> (label, path)."""
    if "=" not in s:
        raise argparse.ArgumentTypeError(
            f"--series argument must be 'LABEL=PATH', got {s!r}"
        )
    label, path = s.split("=", 1)
    return label.strip(), Path(path.strip())


def load_pypsa(csv_path: Path) -> pd.Series:
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    if "system_gCO2_per_kWh" not in df.columns:
        raise ValueError(f"{csv_path} missing column system_gCO2_per_kWh")
    s = df["system_gCO2_per_kWh"].astype(float)
    s.index = pd.to_datetime(s.index, utc=True)
    return s.sort_index()


def load_neso(csv_path: Path) -> pd.Series:
    df = pd.read_csv(csv_path)
    if "from" not in df.columns or "actual" not in df.columns:
        raise ValueError(f"{csv_path} must have columns 'from' and 'actual'")
    df["from"] = pd.to_datetime(df["from"], utc=True)
    s = (df.set_index("from")["actual"]
           .astype(float)
           .sort_index()
           .resample("h").mean())
    s.name = NESO_LABEL
    return s


def summary_stats(series: dict[str, pd.Series],
                  neso: pd.Series | None) -> pd.DataFrame:
    rows = []
    for label, s in series.items():
        rows.append([label, "mean", float(s.mean())])
        rows.append([label, "min",  float(s.min())])
        rows.append([label, "max",  float(s.max())])
        rows.append([label, "std",  float(s.std())])
        if neso is not None:
            j = pd.concat([s, neso], axis=1, join="inner").dropna()
            if not j.empty:
                diff = j.iloc[:, 0] - j.iloc[:, 1]
                rows.append([label, "vs_neso_bias",
                             float(diff.mean())])
                rows.append([label, "vs_neso_rmse",
                             float(np.sqrt((diff ** 2).mean()))])
                rows.append([label, "vs_neso_mae",
                             float(diff.abs().mean())])
                rows.append([label, "vs_neso_pearson_r",
                             float(j.corr().iloc[0, 1])])
                rows.append([label, "n_hours_aligned", int(len(j))])
    if neso is not None:
        rows.append([NESO_LABEL, "mean", float(neso.mean())])
        rows.append([NESO_LABEL, "min",  float(neso.min())])
        rows.append([NESO_LABEL, "max",  float(neso.max())])
        rows.append([NESO_LABEL, "std",  float(neso.std())])
    return pd.DataFrame(rows, columns=["series", "metric", "value"])


def plot_timeseries(series: dict[str, pd.Series],
                    neso: pd.Series | None, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 4))
    for label, s in series.items():
        ax.plot(s.index, s.values, lw=0.5, alpha=0.8, label=label)
    if neso is not None:
        ax.plot(neso.index, neso.values, lw=0.5, alpha=0.8,
                color="k", label=NESO_LABEL)
    ax.set_ylabel("System CI (gCO2 / kWh)")
    ax.set_xlabel("Time (UTC)")
    ax.set_title("Hourly system carbon intensity, 2023")
    ax.legend(loc="upper right", fontsize="small")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def plot_monthly_bar(series: dict[str, pd.Series],
                     neso: pd.Series | None, out: Path) -> None:
    by_month = {label: s.resample("MS").mean() for label, s in series.items()}
    if neso is not None:
        by_month[NESO_LABEL] = neso.resample("MS").mean()

    months = next(iter(by_month.values())).index
    labels = list(by_month.keys())
    n = len(labels)
    width = 0.8 / n
    x = np.arange(len(months))

    fig, ax = plt.subplots(figsize=(10, 4))
    for i, lab in enumerate(labels):
        s = by_month[lab].reindex(months)
        offset = (i - (n - 1) / 2) * width
        color = "k" if lab == NESO_LABEL else None
        ax.bar(x + offset, s.values, width, label=lab, color=color)
    ax.set_xticks(x)
    ax.set_xticklabels(months.strftime("%b"))
    ax.set_ylabel("Mean CI (gCO2 / kWh)")
    ax.set_title("Monthly mean carbon intensity, 2023")
    ax.legend(fontsize="small")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def plot_duration_curve(series: dict[str, pd.Series],
                        neso: pd.Series | None, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))

    def _curve(s: pd.Series) -> tuple[np.ndarray, np.ndarray]:
        v = np.sort(s.dropna().values)[::-1]
        return np.linspace(0, 100, len(v)), v

    for label, s in series.items():
        x, y = _curve(s)
        ax.plot(x, y, lw=1.5, label=label)
    if neso is not None:
        x, y = _curve(neso)
        ax.plot(x, y, lw=1.5, color="k", label=NESO_LABEL)

    ax.set_xlabel("Hours exceeded (%)")
    ax.set_ylabel("CI (gCO2 / kWh)")
    ax.set_title("Intensity duration curve, 2023")
    ax.legend(fontsize="small")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def plot_diurnal(series: dict[str, pd.Series],
                 neso: pd.Series | None, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4))
    for label, s in series.items():
        d = s.groupby(s.index.hour).mean()
        ax.plot(d.index, d.values, marker="o", label=label)
    if neso is not None:
        d = neso.groupby(neso.index.hour).mean()
        ax.plot(d.index, d.values, marker="o", color="k", label=NESO_LABEL)
    ax.set_xlabel("Hour of day (UTC)")
    ax.set_ylabel("Mean CI (gCO2 / kWh)")
    ax.set_title("Diurnal carbon intensity profile, 2023 average")
    ax.set_xticks(range(0, 24, 3))
    ax.legend(fontsize="small")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def plot_scatter(series: dict[str, pd.Series], neso: pd.Series,
                 out: Path) -> None:
    n = len(series)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5), squeeze=False)
    for ax, (label, s) in zip(axes[0], series.items()):
        j = pd.concat([s, neso], axis=1, join="inner").dropna()
        if j.empty:
            continue
        ax.scatter(j.iloc[:, 1], j.iloc[:, 0], s=2, alpha=0.3)
        lo = float(min(j.min()))
        hi = float(max(j.max()))
        ax.plot([lo, hi], [lo, hi], "k--", lw=1, label="y = x")
        ax.set_xlabel(f"{NESO_LABEL} (gCO2 / kWh)")
        ax.set_ylabel(f"{label} (gCO2 / kWh)")
        ax.set_title(label)
        ax.legend(fontsize="small")
        ax.grid(True, alpha=0.3)
        ax.set_aspect("equal", adjustable="box")
    fig.suptitle("PyPSA vs NESO, hourly")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--series", action="append", type=parse_series_arg,
                   required=True,
                   help="LABEL=PATH/system_summary.csv. Repeat for multiple.")
    p.add_argument("--neso", type=Path, default=None,
                   help="Optional NESO national_intensity.csv.")
    p.add_argument("--out-dir", required=True, type=Path)
    args = p.parse_args()

    series = {label: load_pypsa(path) for label, path in args.series}
    neso = load_neso(args.neso) if args.neso else None

    args.out_dir.mkdir(parents=True, exist_ok=True)

    plot_timeseries(series, neso,
                    args.out_dir / "system_intensity_timeseries.png")
    plot_monthly_bar(series, neso,
                     args.out_dir / "monthly_mean_bar.png")
    plot_duration_curve(series, neso,
                        args.out_dir / "intensity_duration_curve.png")
    plot_diurnal(series, neso, args.out_dir / "diurnal_profile.png")
    if neso is not None:
        plot_scatter(series, neso,
                     args.out_dir / "pypsa_vs_neso_scatter.png")

    stats = summary_stats(series, neso)
    stats.to_csv(args.out_dir / "summary_stats.csv", index=False)
    print(stats.to_string(index=False))
    print(f"\nplots and stats -> {args.out_dir}")


if __name__ == "__main__":
    main()
