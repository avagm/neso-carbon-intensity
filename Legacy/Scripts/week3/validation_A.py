"""
validation_A.py  –  Section A: Model Validation Figures
NESO Carbon Intensity Project | Imperial College ELEC60014

Produces six IEEE-format PDF figures:
  A1_scatter.pdf          – PyPSA vs NESO hourly scatter (3-panel)
  A2_taylor.pdf           – Taylor diagram (all models on one axes)
  A3_duration.pdf         – Intensity duration curves
  A4_monthly_mean.pdf     – Monthly mean bar chart
  A5_bland_altman.pdf     – Bland–Altman agreement plots
  A6_error_timeseries.pdf – Monthly RMSE time series

FILES TO DOWNLOAD FROM GITHUB INTO THE SAME FOLDER AS THIS SCRIPT:
  results/copperplate/system_carbon_intensity.csv
  results/zonal_17bus/system_carbon_intensity.csv
  results/reduced_32bus/system_carbon_intensity.csv
  results/generation_by_carrier.csv
  results/heatmap_input.csv          (used first for NESO actual)

NESO actual is pulled from the Carbon Intensity API automatically
and cached to neso_actual_2023.csv so you only hit the API once.

Usage:
  pip install numpy pandas matplotlib scipy requests
  python validation_A.py
"""

# ── stdlib ──────────────────────────────────────────────────────────────────
import time
import warnings
from pathlib import Path

# ── third-party ─────────────────────────────────────────────────────────────
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy import stats
import requests

warnings.filterwarnings("ignore")

# ════════════════════════════════════════════════════════════════════════════
#  IEEE MATPLOTLIB STYLE
#  Single-column width = 3.5 in   Double-column = 7.16 in
# ════════════════════════════════════════════════════════════════════════════
mpl.rcParams.update({
    "text.usetex":        False,      # set True if LaTeX installed; Times then used
    "font.family":        "serif",
    "font.serif":         ["DejaVu Serif"],   # swap to "Times New Roman" with usetex
    "font.size":          8,
    "axes.labelsize":     8,
    "axes.titlesize":     8,
    "axes.titlepad":      4,
    "axes.linewidth":     0.5,
    "xtick.labelsize":    7,
    "ytick.labelsize":    7,
    "xtick.major.width":  0.5,
    "ytick.major.width":  0.5,
    "xtick.minor.width":  0.3,
    "ytick.minor.width":  0.3,
    "xtick.direction":    "in",
    "ytick.direction":    "in",
    "legend.fontsize":    7,
    "legend.framealpha":  0.85,
    "legend.edgecolor":   "0.7",
    "legend.handlelength": 1.5,
    "lines.linewidth":    0.9,
    "grid.linewidth":     0.35,
    "grid.alpha":         0.4,
    "figure.dpi":         300,
    "savefig.dpi":        300,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.02,
    "savefig.format":     "pdf",
})

W1 = 3.5    # single-column figure width (inches)
W2 = 7.16   # double-column figure width (inches)

# ════════════════════════════════════════════════════════════════════════════
#  PATHS
# ════════════════════════════════════════════════════════════════════════════
BASE    = Path(__file__).parent
RES     = BASE / "results"
OUT     = BASE / "figures_A"
CACHE   = BASE / "neso_actual_2023.csv"
OUT.mkdir(exist_ok=True)

MODEL_PATHS = {
    "Copperplate":    RES / "copperplate"   / "system_carbon_intensity.csv",
    "Zonal 17-bus":  RES / "zonal_17bus"   / "system_carbon_intensity.csv",
    "Reduced 32-bus": RES / "reduced_32bus" / "system_carbon_intensity.csv",
}

# Colours matched to existing project plots (blue, orange, black)
MODEL_COLORS = {
    "Copperplate":    "#85B7EB",
    "Zonal 17-bus":  "#378ADD",
    "Reduced 32-bus": "#D85A30",
}
NESO_COLOR  = "#2C2C2A"

YEAR = 2023

# ════════════════════════════════════════════════════════════════════════════
#  DATA LOADING
# ════════════════════════════════════════════════════════════════════════════

def _parse_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """
    Handles both datetime strings and integer snapshot indices.
    Returns df with a UTC-aware DatetimeIndex.
    """
    col = df["snapshot"]
    if pd.api.types.is_integer_dtype(col) or (
        col.dtype == object and col.iloc[0].replace(".", "").isdigit()
    ):
        # Integer index: map 0 → 2023-01-01 00:00 UTC
        df.index = pd.date_range(
            f"{YEAR}-01-01 00:00", periods=len(df), freq="h", tz="UTC"
        )
    else:
        df.index = pd.to_datetime(col, utc=True)
    return df.drop(columns=["snapshot"])


def load_model(path: Path, name: str) -> pd.Series:
    df = pd.read_csv(path)
    df = _parse_snapshot(df)
    return df["system_gCO2_per_kWh"].rename(name)


def pull_neso_api(year: int = YEAR) -> pd.Series:
    """
    Pulls half-hourly national CI actuals from the Carbon Intensity API
    and resamples to hourly. Slow (~5 min for full year) — cached to disk.
    """
    print("  Pulling NESO actual from API (this takes a few minutes)…")
    records = []
    dates = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    for d in dates:
        url = f"https://api.carbonintensity.org.uk/intensity/date/{d.date()}"
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            for pt in r.json()["data"]:
                actual = pt["intensity"]["actual"]
                if actual is not None:
                    records.append({
                        "timestamp": pd.Timestamp(pt["from"]),
                        "neso_actual": float(actual),
                    })
        except Exception as e:
            print(f"  Warning: API call failed for {d.date()}: {e}")
        time.sleep(0.08)   # polite rate limiting

    s = (
        pd.DataFrame(records)
        .set_index("timestamp")
        ["neso_actual"]
        .pipe(lambda x: x.tz_localize("UTC") if x.index.tz is None else x)
        .resample("h").mean()   # half-hourly → hourly
        .rename("NESO actual")
    )
    s.to_csv(CACHE, header=True)
    return s


def load_heatmap_input() -> pd.DataFrame:
    """
    Loads heatmap_input.csv which has columns:
      timestamp_utc, neso_actual, zonal_17bus, reduced_32bus, reduced_minus_zonal
    Returns a DataFrame with a UTC DatetimeIndex.
    """
    hi_path = RES / "heatmap_input.csv"
    if not hi_path.exists():
        return pd.DataFrame()

    hi = pd.read_csv(hi_path)

    # Detect timestamp column — could be timestamp_utc or snapshot
    ts_col = None
    for candidate in ["timestamp_utc", "snapshot", "datetime", "time"]:
        if candidate in hi.columns:
            ts_col = candidate
            break

    if ts_col is None:
        print(f"  WARNING: cannot find timestamp column in heatmap_input.csv. "
              f"Columns: {list(hi.columns)}")
        return pd.DataFrame()

    hi.index = pd.to_datetime(hi[ts_col], utc=True)
    return hi.drop(columns=[ts_col])


def load_neso() -> pd.Series:
    """
    Loads NESO actual CI (gCO2/kWh) for 2023, hourly.
    Priority: heatmap_input.csv → cached CSV → live API pull.
    """
    # 1. Try heatmap_input.csv (columns: timestamp_utc, neso_actual, ...)
    hi = load_heatmap_input()
    if not hi.empty:
        for candidate in ["neso_actual", "NESO actual", "neso", "actual"]:
            if candidate in hi.columns:
                print(f"  Found NESO actual in heatmap_input.csv (column: '{candidate}')")
                return hi[candidate].rename("NESO actual")
        print(f"  heatmap_input.csv loaded but no NESO column found. Columns: {list(hi.columns)}")

    # 2. Try cached API pull
    if CACHE.exists():
        print(f"  Loading cached NESO actual from {CACHE.name}")
        s = pd.read_csv(CACHE, index_col=0, parse_dates=True).iloc[:, 0]
        s.index = pd.to_datetime(s.index, utc=True)
        return s.rename("NESO actual")

    # 3. Live API pull
    return pull_neso_api()


def load_genmix() -> pd.DataFrame:
    """Loads generation_by_carrier.csv and returns a DataFrame with wind/gas fractions."""
    path = RES / "generation_by_carrier.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df = _parse_snapshot(df)

    # Compute useful fractions regardless of exact column names
    wind_cols = [c for c in df.columns if "wind" in c.lower()]
    gas_cols  = [c for c in df.columns if "gas"  in c.lower()]
    gen_cols  = [c for c in df.columns if "mwh"  in c.lower() or "generation" in c.lower()]

    if wind_cols:
        df["wind_mwh"] = df[wind_cols].sum(axis=1)
    if gas_cols:
        df["gas_mwh"] = df[gas_cols].sum(axis=1)
    total_col = gen_cols[0] if gen_cols else None
    if total_col and "wind_mwh" in df:
        df["wind_frac"] = df["wind_mwh"] / df[total_col].replace(0, np.nan)
    if total_col and "gas_mwh" in df:
        df["gas_frac"]  = df["gas_mwh"]  / df[total_col].replace(0, np.nan)
    return df


# ════════════════════════════════════════════════════════════════════════════
#  BUILD MASTER DATAFRAME
# ════════════════════════════════════════════════════════════════════════════

# Map heatmap_input.csv column names → display names used in plots
HEATMAP_COL_MAP = {
    "zonal_17bus":   "Zonal 17-bus",
    "reduced_32bus":  "Reduced 32-bus",
    "copperplate":    "Copperplate",
}


def build_master() -> pd.DataFrame:
    print("Loading model results…")

    # Try individual subfolder CSVs first
    series = {}
    for name, path in MODEL_PATHS.items():
        if path.exists():
            series[name] = load_model(path, name)
        else:
            print(f"  {path.name} not found in subfolder — will try heatmap_input.csv")

    # Fill any missing models from heatmap_input.csv
    # (columns: timestamp_utc, neso_actual, zonal_17bus, reduced_32bus, ...)
    hi = load_heatmap_input()
    if not hi.empty:
        for col, display_name in HEATMAP_COL_MAP.items():
            if display_name not in series and col in hi.columns:
                print(f"  Loaded {display_name} from heatmap_input.csv")
                series[display_name] = hi[col].rename(display_name)

    print("Loading NESO actual…")
    series["NESO actual"] = load_neso()

    df = pd.concat(series.values(), axis=1)

    # Align to UTC hourly 2023
    idx = pd.date_range(f"{YEAR}-01-01", f"{YEAR}-12-31 23:00", freq="h", tz="UTC")
    df = df.reindex(idx)

    print(f"  Master frame: {len(df)} rows, {df.notna().sum().to_dict()}")

    # Quick sanity checks
    neso_mean = df["NESO actual"].mean()
    if not 100 < neso_mean < 250:
        print(f"  WARNING: NESO actual mean = {neso_mean:.1f} — check units (expected ~148 gCO2/kWh)")

    return df


# ════════════════════════════════════════════════════════════════════════════
#  HELPER: error metrics
# ════════════════════════════════════════════════════════════════════════════

def metrics(pred: pd.Series, obs: pd.Series):
    valid = pred.notna() & obs.notna()
    p, o = pred[valid].values, obs[valid].values
    bias = float(np.mean(p - o))
    rmse = float(np.sqrt(np.mean((p - o) ** 2)))
    mae  = float(np.mean(np.abs(p - o)))
    r, _ = stats.pearsonr(p, o)
    return dict(bias=bias, rmse=rmse, mae=mae, r=r, n=int(valid.sum()))


# ════════════════════════════════════════════════════════════════════════════
#  A1 – SCATTER PLOTS
# ════════════════════════════════════════════════════════════════════════════

def plot_A1_scatter(df: pd.DataFrame):
    """
    A1: PyPSA vs NESO hourly scatter — one panel per model.
    What it shows: point-by-point agreement. A perfect model sits on the
    y = x line. Scatter above y=x = model overestimates CI; below = underestimates.
    Colour encodes point density (log scale) to avoid overplotting 8760 points.
    """
    print("  Plotting A1: Scatter…")
    models = [m for m in MODEL_PATHS if m in df.columns]
    neso   = df["NESO actual"].dropna()

    fig, axes = plt.subplots(1, len(models), figsize=(W2, W2 / len(models) * 1.05),
                             sharey=True)

    lim = (0, 360)
    ref = np.array(lim)

    for ax, name in zip(np.atleast_1d(axes), models):
        valid = df[name].notna() & neso.notna()
        x = neso[valid].values
        y = df[name][valid].values

        # 2-D histogram for density colouring
        h, xe, ye = np.histogram2d(x, y, bins=80, range=[lim, lim])
        # map each point to its bin density
        xi = np.clip(np.digitize(x, xe) - 1, 0, h.shape[0]-1)
        yi = np.clip(np.digitize(y, ye) - 1, 0, h.shape[1]-1)
        density = np.log1p(h[xi, yi])

        sc = ax.scatter(x, y, c=density, cmap="YlOrRd", s=1.5,
                        linewidths=0, alpha=0.6, rasterized=True)

        ax.plot(ref, ref, "k--", lw=0.6, zorder=5)  # y = x reference

        m = metrics(df[name], neso)
        ax.text(0.05, 0.95,
                f"$R$={m['r']:.3f}\nRMSE={m['rmse']:.1f}\nBias={m['bias']:+.1f}",
                transform=ax.transAxes, va="top", fontsize=6.5,
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="0.7", lw=0.5))

        ax.set_xlim(*lim); ax.set_ylim(*lim)
        ax.set_aspect("equal")
        ax.set_xlabel(r"NESO actual (gCO$_2$ kWh$^{-1}$)")
        ax.set_title(name)
        ax.xaxis.set_major_locator(ticker.MultipleLocator(100))
        ax.yaxis.set_major_locator(ticker.MultipleLocator(100))
        ax.grid(True)

    axes[0].set_ylabel(r"PyPSA model (gCO$_2$ kWh$^{-1}$)")

    cb = fig.colorbar(sc, ax=axes[-1], shrink=0.7, pad=0.02)
    cb.set_label("log(count + 1)", fontsize=6)
    cb.ax.tick_params(labelsize=6)

    fig.tight_layout(pad=0.5)
    fig.savefig(OUT / "A1_scatter.pdf")
    plt.close(fig)
    print("    Saved A1_scatter.pdf")


# ════════════════════════════════════════════════════════════════════════════
#  A2 – TAYLOR DIAGRAM
# ════════════════════════════════════════════════════════════════════════════

def plot_A2_taylor(df: pd.DataFrame):
    """
    A2: Taylor diagram — correlation, std dev, and RMSE in one polar plot.
    What it shows: compares all 3 models simultaneously against NESO actual.
    Angle = arccos(correlation); radius = normalised std dev;
    distance from REF point = normalised RMSE.
    A model sitting at the REF point would be perfect.
    """
    print("  Plotting A2: Taylor diagram…")
    neso   = df["NESO actual"].dropna()
    models = [m for m in MODEL_PATHS if m in df.columns]

    ref_std = float(neso.std())

    fig = plt.figure(figsize=(W1 * 1.1, W1 * 1.1))
    ax  = fig.add_subplot(111, polar=True)

    # Only show top quarter of polar plot (0 to π/2 = r=0 to r=1 corr)
    ax.set_thetamin(0)
    ax.set_thetamax(90)
    ax.set_theta_direction(-1)
    ax.set_theta_offset(np.pi / 2)

    # Radial axis = normalised std dev
    max_r = 1.6
    ax.set_rlim(0, max_r)
    ax.set_rlabel_position(135)
    ax.set_rticks([0.5, 1.0, 1.5])
    ax.set_yticklabels(["0.5", "1.0", "1.5"], fontsize=6)
    ax.set_rlabel_position(-20)

    # Angular axis = correlation
    corr_ticks = [0.0, 0.2, 0.4, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0]
    theta_ticks = np.arccos(corr_ticks)
    ax.set_thetagrids(np.degrees(theta_ticks),
                      labels=[str(c) for c in corr_ticks], fontsize=6)

    # RMSE arcs centred on REF (1, 0) in normalised coordinates
    ref_theta, ref_r = 0.0, 1.0
    for rmse_norm in [0.5, 1.0, 1.5]:
        theta_arc = np.linspace(0, np.pi / 2, 200)
        # arc: distance from REF = rmse_norm
        # x = r*cos(θ), y = r*sin(θ);  REF = (ref_r, 0) in Cartesian
        # solve: (r*cos(θ) - ref_r)^2 + (r*sin(θ))^2 = rmse_norm^2
        # → r^2 - 2*r*ref_r*cos(θ) + ref_r^2 - rmse_norm^2 = 0
        a = 1
        b = -2 * ref_r * np.cos(theta_arc)
        c = ref_r**2 - rmse_norm**2
        disc = b**2 - 4*a*c
        r_arc = np.where(disc >= 0, (-b + np.sqrt(np.maximum(disc, 0))) / (2*a), np.nan)
        valid  = (r_arc >= 0) & (r_arc <= max_r)
        ax.plot(theta_arc[valid], r_arc[valid], ":", color="0.6", lw=0.5, zorder=1)
        # label at 45 degrees
        idx45 = np.argmin(np.abs(theta_arc - np.pi/4))
        if valid[idx45]:
            ax.text(theta_arc[idx45], r_arc[idx45],
                    f"{rmse_norm:.1f}", fontsize=5.5, color="0.5",
                    ha="center", va="center")

    # Standard deviation circles
    for r_circ in [0.5, 1.0, 1.5]:
        t = np.linspace(0, np.pi/2, 200)
        ax.plot(t, np.full_like(t, r_circ), color="0.75", lw=0.3, zorder=0)

    # REF point (NESO actual)
    ax.plot(0, 1.0, "*", ms=9, color=NESO_COLOR, zorder=5, label="NESO actual (REF)")

    # Model points
    markers = ["o", "s", "^"]
    for name, mk in zip(models, markers):
        valid = df[name].notna() & neso.notna()
        p = df[name][valid].values
        o = neso[valid].values
        r, _ = stats.pearsonr(p, o)
        s_norm = float(np.std(p)) / ref_std
        theta = np.arccos(np.clip(r, -1, 1))
        ax.plot(theta, s_norm, mk, ms=6, color=MODEL_COLORS[name],
                label=name, zorder=4, markeredgewidth=0.4,
                markeredgecolor="white")

    ax.set_title("Taylor diagram — 2023 hourly CI", pad=10)
    ax.legend(loc="lower left", bbox_to_anchor=(0.9, 0.0),
              framealpha=0.9, fontsize=6)

    # Axis labels
    fig.text(0.5, 0.01, "Normalised standard deviation", ha="center", fontsize=7)
    fig.text(0.01, 0.5, "Correlation coefficient",
             ha="center", va="center", rotation=90, fontsize=7)

    fig.tight_layout(pad=0.8)
    fig.savefig(OUT / "A2_taylor.pdf")
    plt.close(fig)
    print("    Saved A2_taylor.pdf")


# ════════════════════════════════════════════════════════════════════════════
#  A3 – INTENSITY DURATION CURVES
# ════════════════════════════════════════════════════════════════════════════

def plot_A3_duration(df: pd.DataFrame):
    """
    A3: Intensity duration curve — each model's 8760 hourly CI values sorted
    descending and plotted against the percentage of hours exceeded.
    What it shows: a model that perfectly matches NESO will sit exactly on
    the black NESO curve. Divergence at the extremes (left = high-CI peaks,
    right = low-CI troughs) reveals whether the model captures stress events.
    """
    print("  Plotting A3: Duration curves…")
    models = [m for m in MODEL_PATHS if m in df.columns]
    neso   = df["NESO actual"].dropna().values

    fig, ax = plt.subplots(figsize=(W1, W1 * 0.78))

    def duration_xy(series):
        s = np.sort(series[~np.isnan(series)])[::-1]
        x = np.linspace(0, 100, len(s))
        return x, s

    x_neso, y_neso = duration_xy(neso)
    ax.plot(x_neso, y_neso, color=NESO_COLOR, lw=1.0, zorder=5,
            label="NESO actual")

    for name in models:
        s = df[name].dropna().values
        x, y = duration_xy(s)
        ax.plot(x, y, color=MODEL_COLORS[name], lw=0.8,
                alpha=0.85, label=name)

    ax.set_xlabel(r"Hours exceeded (\%)")
    ax.set_ylabel(r"Carbon intensity (gCO$_2$ kWh$^{-1}$)")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, None)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(20))
    ax.yaxis.set_major_locator(ticker.MultipleLocator(50))
    ax.grid(True)
    ax.legend(framealpha=0.9)
    ax.set_title("Intensity duration curve — 2023")

    fig.tight_layout(pad=0.5)
    fig.savefig(OUT / "A3_duration.pdf")
    plt.close(fig)
    print("    Saved A3_duration.pdf")


# ════════════════════════════════════════════════════════════════════════════
#  A4 – MONTHLY MEAN BAR CHART
# ════════════════════════════════════════════════════════════════════════════

def plot_A4_monthly_mean(df: pd.DataFrame):
    """
    A4: Monthly mean CI — grouped bar chart with NESO actual as a step line.
    What it shows: seasonal accuracy. Models that consistently sit above NESO
    have a positive bias; below = negative bias. Look for which months show
    the largest divergence (typically high-wind spring/summer months).
    """
    print("  Plotting A4: Monthly mean bars…")
    models = [m for m in MODEL_PATHS if m in df.columns]

    df_m = df.copy()
    df_m["month"] = df_m.index.month

    monthly = df_m.groupby("month").mean()

    fig, ax = plt.subplots(figsize=(W2, W2 * 0.38))

    n_models = len(models)
    bar_w    = 0.65 / n_models
    x        = np.arange(12)
    offsets  = np.linspace(-(n_models-1)/2, (n_models-1)/2, n_models) * bar_w

    for name, offset in zip(models, offsets):
        if name in monthly:
            ax.bar(x + offset, monthly[name], width=bar_w,
                   color=MODEL_COLORS[name], label=name,
                   linewidth=0, zorder=2)

    # NESO actual as step line
    if "NESO actual" in monthly:
        neso_vals = monthly["NESO actual"].reindex(range(1, 13)).values
        ax.step(np.arange(-0.5, 12, 1), np.append(neso_vals, neso_vals[-1]),
                where="post", color=NESO_COLOR, lw=1.1,
                zorder=5, label="NESO actual")
        # also plot dots at month centres
        ax.plot(x, neso_vals, ".", color=NESO_COLOR, ms=3, zorder=6)

    months_abbr = ["Jan","Feb","Mar","Apr","May","Jun",
                   "Jul","Aug","Sep","Oct","Nov","Dec"]
    ax.set_xticks(x)
    ax.set_xticklabels(months_abbr)
    ax.set_xlim(-0.55, 11.55)
    ax.set_ylim(0, None)
    ax.set_ylabel(r"Mean CI (gCO$_2$ kWh$^{-1}$)")
    ax.set_title("Monthly mean carbon intensity — 2023")
    ax.grid(axis="y", zorder=0)
    ax.set_axisbelow(True)
    ax.legend(ncol=n_models + 1, loc="upper center",
              bbox_to_anchor=(0.5, -0.18), framealpha=0.9)

    fig.tight_layout(pad=0.5)
    fig.savefig(OUT / "A4_monthly_mean.pdf")
    plt.close(fig)
    print("    Saved A4_monthly_mean.pdf")


# ════════════════════════════════════════════════════════════════════════════
#  A5 – BLAND–ALTMAN AGREEMENT PLOTS
# ════════════════════════════════════════════════════════════════════════════

def plot_A5_bland_altman(df: pd.DataFrame):
    """
    A5: Bland–Altman agreement — x = mean of (model, NESO), y = model − NESO.
    What it shows: whether model error is systematic (constant bias) or
    proportional (growing with CI magnitude). The bias line (mean diff)
    and ±1.96σ limits of agreement are annotated. A bias line close to zero
    and narrow limits = good agreement. Funnel shape = proportional error.
    """
    print("  Plotting A5: Bland–Altman…")
    models = [m for m in MODEL_PATHS if m in df.columns]
    neso   = df["NESO actual"]

    fig, axes = plt.subplots(1, len(models), figsize=(W2, W2 / len(models) * 0.85),
                             sharey=True)

    for ax, name in zip(np.atleast_1d(axes), models):
        valid = df[name].notna() & neso.notna()
        mean_  = ((df[name] + neso) / 2)[valid].values
        diff_  = (df[name] - neso)[valid].values

        bias   = float(np.mean(diff_))
        sd     = float(np.std(diff_))
        loa_up = bias + 1.96 * sd
        loa_lo = bias - 1.96 * sd

        # density colouring
        from scipy.stats import gaussian_kde
        try:
            xy     = np.vstack([mean_, diff_])
            kernel = gaussian_kde(xy)
            c      = kernel(xy)
        except Exception:
            c = "C0"

        ax.scatter(mean_, diff_, c=c, cmap="YlOrRd", s=1.5,
                   linewidths=0, alpha=0.5, rasterized=True)

        for val, ls, lbl in [
            (bias,   "--", f"Bias={bias:+.1f}"),
            (loa_up, ":" , f"+1.96σ={loa_up:+.1f}"),
            (loa_lo, ":" , f"−1.96σ={loa_lo:+.1f}"),
        ]:
            ax.axhline(val, color="k", lw=0.7, ls=ls)
            ax.text(350, val, lbl, fontsize=5.5, va="bottom", ha="right",
                    color="k")

        ax.axhline(0, color="0.5", lw=0.4)
        ax.set_xlabel(r"Mean CI (gCO$_2$ kWh$^{-1}$)")
        ax.set_title(name)
        ax.grid(True)

    axes[0].set_ylabel(r"Model $-$ NESO actual (gCO$_2$ kWh$^{-1}$)")
    fig.suptitle("Bland–Altman agreement — 2023", y=1.01)
    fig.tight_layout(pad=0.5)
    fig.savefig(OUT / "A5_bland_altman.pdf")
    plt.close(fig)
    print("    Saved A5_bland_altman.pdf")


# ════════════════════════════════════════════════════════════════════════════
#  A6 – ERROR METRIC TIME SERIES
# ════════════════════════════════════════════════════════════════════════════

def plot_A6_error_timeseries(df: pd.DataFrame):
    """
    A6: Monthly RMSE and bias time series for each model.
    What it shows: whether model accuracy is consistent across the year or
    degrades in specific seasons (e.g. high-wind summer, cold winter peaks).
    A model that is accurate in winter but poor in summer has a solar/wind
    representation problem, not a global calibration problem.
    """
    print("  Plotting A6: Error time series…")
    models = [m for m in MODEL_PATHS if m in df.columns]
    neso   = df["NESO actual"]

    fig, (ax_rmse, ax_bias) = plt.subplots(2, 1, figsize=(W2, W2 * 0.55),
                                            sharex=True)

    for name in models:
        diff   = df[name] - neso
        sq_err = diff ** 2

        monthly_rmse = sq_err.resample("MS").mean().pow(0.5)
        monthly_bias = diff.resample("MS").mean()

        lw = 0.9
        ax_rmse.plot(monthly_rmse.index, monthly_rmse.values,
                     color=MODEL_COLORS[name], lw=lw,
                     marker="o", ms=2.5, label=name)
        ax_bias.plot(monthly_bias.index, monthly_bias.values,
                     color=MODEL_COLORS[name], lw=lw,
                     marker="o", ms=2.5, label=name)

    ax_bias.axhline(0, color="0.4", lw=0.5)
    ax_rmse.set_ylabel(r"RMSE (gCO$_2$ kWh$^{-1}$)")
    ax_bias.set_ylabel(r"Bias (gCO$_2$ kWh$^{-1}$)")
    ax_bias.set_xlabel("Month")
    ax_rmse.set_title("Monthly error metrics vs NESO actual — 2023")
    ax_rmse.grid(True); ax_bias.grid(True)
    ax_rmse.legend(fontsize=6)

    # Format x-axis as month abbreviations
    import matplotlib.dates as mdates
    ax_bias.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    ax_bias.xaxis.set_major_locator(mdates.MonthLocator())

    fig.tight_layout(pad=0.5)
    fig.savefig(OUT / "A6_error_timeseries.pdf")
    plt.close(fig)
    print("    Saved A6_error_timeseries.pdf")


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  Validation Section A  |  NESO Carbon Intensity Project")
    print("=" * 60)

    df = build_master()

    print("\nRunning plots…")
    plot_A1_scatter(df)
    plot_A2_taylor(df)
    plot_A3_duration(df)
    plot_A4_monthly_mean(df)
    plot_A5_bland_altman(df)
    plot_A6_error_timeseries(df)

    print(f"\nAll figures saved to: {OUT.resolve()}")
    print("\nMetrics summary:")
    print("-" * 50)
    neso = df["NESO actual"]
    for name in MODEL_PATHS:
        if name in df.columns:
            m = metrics(df[name], neso)
            print(f"  {name:<20} RMSE={m['rmse']:5.1f}  "
                  f"Bias={m['bias']:+5.1f}  "
                  f"MAE={m['mae']:5.1f}  "
                  f"R={m['r']:.4f}")
    print("-" * 50)
