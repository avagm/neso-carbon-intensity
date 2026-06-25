"""Plot pack: time series, monthly bar, duration curve, diurnal, plus stats.

    python visualise.py \
        --series "Zonal 17-bus=Results/week 2/system_summary_zonal_17bus.csv" \
        --series "Reduced 32-bus=Results/week 2/system_summary_reduced_32bus.csv" \
        --neso   Data/neso_2023_national_intensity.csv \
        --out-dir "Results/week 2"
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


NESO_LABEL = "NESO actual"


def parse_series_arg(s: str) -> tuple[str, Path]:
    if "=" not in s:
        raise argparse.ArgumentTypeError(f"--series must be LABEL=PATH, got {s!r}")
    label, path = s.split("=", 1)
    return label.strip(), Path(path.strip())


def load_pypsa(csv_path: Path) -> pd.Series:
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    s = df["system_gCO2_per_kWh"].astype(float)
    s.index = pd.to_datetime(s.index, utc=True)
    return s.sort_index()


def load_neso(csv_path: Path) -> pd.Series:
    df = pd.read_csv(csv_path)
    df["from"] = pd.to_datetime(df["from"], utc=True)
    return (df.set_index("from")["actual"]
              .astype(float).sort_index().resample("h").mean()
              .rename(NESO_LABEL))


def summary_stats(series: dict[str, pd.Series],
                  neso: pd.Series | None) -> pd.DataFrame:
    rows = []
    for label, s in series.items():
        rows += [(label, k, float(v)) for k, v in
                 [("mean", s.mean()), ("min", s.min()),
                  ("max", s.max()), ("std", s.std())]]
        if neso is not None:
            j = pd.concat([s, neso], axis=1, join="inner").dropna()
            if not j.empty:
                d = j.iloc[:, 0] - j.iloc[:, 1]
                rows += [
                    (label, "vs_neso_bias", float(d.mean())),
                    (label, "vs_neso_rmse", float(np.sqrt((d ** 2).mean()))),
                    (label, "vs_neso_mae",  float(d.abs().mean())),
                    (label, "vs_neso_pearson_r", float(j.corr().iloc[0, 1])),
                    (label, "n_hours_aligned", int(len(j))),
                ]
    if neso is not None:
        rows += [(NESO_LABEL, k, float(v)) for k, v in
                 [("mean", neso.mean()), ("min", neso.min()),
                  ("max", neso.max()), ("std", neso.std())]]
    return pd.DataFrame(rows, columns=["series", "metric", "value"])


def plot_timeseries(series, neso, out, title):
    fig, ax = plt.subplots(figsize=(12, 4))
    for label, s in series.items():
        ax.plot(s.index, s.values, lw=0.5, alpha=0.8, label=label)
    if neso is not None:
        ax.plot(neso.index, neso.values, lw=0.5, alpha=0.8, color="k", label=NESO_LABEL)
    ax.set_ylabel("System CI (gCO2 / kWh)")
    ax.set_xlabel("Time (UTC)")
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize="small")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def plot_monthly_bar(series, neso, out):
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
        color = "k" if lab == NESO_LABEL else None
        ax.bar(x + (i - (n - 1) / 2) * width, s.values, width, label=lab, color=color)
    ax.set_xticks(x)
    ax.set_xticklabels(months.strftime("%b"))
    ax.set_ylabel("Mean CI (gCO2 / kWh)")
    ax.set_title("Monthly mean carbon intensity, 2023")
    ax.legend(fontsize="small")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def plot_duration_curve(series, neso, out):
    fig, ax = plt.subplots(figsize=(8, 5))
    for label, s in series.items():
        v = np.sort(s.dropna().values)[::-1]
        ax.plot(np.linspace(0, 100, len(v)), v, lw=1.5, label=label)
    if neso is not None:
        v = np.sort(neso.dropna().values)[::-1]
        ax.plot(np.linspace(0, 100, len(v)), v, lw=1.5, color="k", label=NESO_LABEL)
    ax.set_xlabel("Hours exceeded (%)")
    ax.set_ylabel("CI (gCO2 / kWh)")
    ax.set_title("Intensity duration curve, 2023")
    ax.legend(fontsize="small")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def plot_diurnal(series, neso, out):
    fig, ax = plt.subplots(figsize=(8, 4))
    for label, s in series.items():
        d = s.groupby(s.index.hour).mean()
        ax.plot(d.index, d.values, marker="o", label=label)
    if neso is not None:
        d = neso.groupby(neso.index.hour).mean()
        ax.plot(d.index, d.values, marker="o", color="k", label=NESO_LABEL)
    ax.set_xlabel("Hour of day (UTC)")
    ax.set_ylabel("Mean CI (gCO2 / kWh)")
    ax.set_title("Diurnal profile, 2023 average")
    ax.set_xticks(range(0, 24, 3))
    ax.legend(fontsize="small")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--series", action="append", type=parse_series_arg,
                   required=True, help="LABEL=PATH (repeat for multiple).")
    p.add_argument("--neso", type=Path, default=None)
    p.add_argument("--out-dir", required=True, type=Path)
    args = p.parse_args()

    series = {label: load_pypsa(path) for label, path in args.series}
    neso = load_neso(args.neso) if args.neso else None

    plots = args.out_dir / "plots"
    plots.mkdir(parents=True, exist_ok=True)

    plot_timeseries(series, neso, plots / "system_intensity_timeseries.png",
                    "Hourly system carbon intensity, 2023")
    plot_monthly_bar(series, neso, plots / "monthly_mean_bar.png")
    plot_duration_curve(series, neso, plots / "intensity_duration_curve.png")
    plot_diurnal(series, neso, plots / "diurnal_profile.png")

    stats = summary_stats(series, neso)
    stats.to_csv(args.out_dir / "summary_stats.csv", index=False)
    print(stats.to_string(index=False))
    print(f"\nplots and stats -> {args.out_dir}")


if __name__ == "__main__":
    main()
