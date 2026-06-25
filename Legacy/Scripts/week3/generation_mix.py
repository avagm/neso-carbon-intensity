"""
generation_mix.py  –  Generation mix figures
NESO Carbon Intensity Project | Imperial College ELEC60014

Produces four simple, readable figures:
  mix1_generation_by_group.pdf   – Clean / low-carbon / fossil TWh per model
  mix2_top_carriers.pdf          – Top 8 carriers side-by-side per model
  mix3_emission_factors.pdf      – Emission factor per carrier (reference)
  mix4_total_emissions.pdf       – Total annual CO2 per model

Place this script in neso_validation/ alongside results/
Run:  python generation_mix.py
"""

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt

# ── Paths ────────────────────────────────────────────────────────────────────
BASE = Path(__file__).parent
RES  = BASE / "results"
OUT  = BASE / "figures_mix"
OUT.mkdir(exist_ok=True)

MODEL_FOLDERS = {
    "Copperplate":     "copperplate",
    "Zonal 17-bus":   "zonal_17bus",
    "Reduced 32-bus": "reduced_32bus",
}

MODEL_COLORS = {
    "Copperplate":    "#85B7EB",
    "Zonal 17-bus":  "#378ADD",
    "Reduced 32-bus": "#D85A30",
}

# ── Carrier groupings ────────────────────────────────────────────────────────
GROUPS = {
    "Zero carbon": [
        "wind_offshore", "wind_onshore", "nuclear", "solar_pv",
        "large_hydro", "small_hydro", "storage_discharge",
        "shoreline_wave", "tidal_stream",
    ],
    "Low carbon": [
        "EU_import", "landfill_gas", "advanced_biofuel",
        "biogas", "sewage_gas",
    ],
    "High carbon": [
        "CCGT", "waste_to_energy", "OCGT", "coal", "oil",
    ],
}

GROUP_COLORS = {
    "Zero carbon": "#2ECC71",
    "Low carbon":  "#F39C12",
    "High carbon": "#E74C3C",
}

# Readable display names for carriers
CARRIER_LABELS = {
    "wind_offshore":    "Wind offshore",
    "wind_onshore":     "Wind onshore",
    "nuclear":          "Nuclear",
    "solar_pv":         "Solar PV",
    "large_hydro":      "Hydro",
    "small_hydro":      "Small hydro",
    "storage_discharge":"Storage",
    "EU_import":        "EU imports",
    "landfill_gas":     "Landfill gas",
    "advanced_biofuel": "Biofuel",
    "biogas":           "Biogas",
    "sewage_gas":       "Sewage gas",
    "CCGT":             "Gas (CCGT)",
    "waste_to_energy":  "Waste to energy",
    "OCGT":             "Gas (OCGT)",
    "coal":             "Coal",
    "shoreline_wave":   "Wave",
    "tidal_stream":     "Tidal",
    "storage_charge":   "Storage charge",
    "load_shedding":    "Load shedding",
    "oil":              "Oil",
}

# ── Presentation style ───────────────────────────────────────────────────────
mpl.rcParams.update({
    "font.family":        "sans-serif",
    "font.size":          12,
    "axes.labelsize":     12,
    "axes.titlesize":     13,
    "axes.titlepad":      10,
    "axes.linewidth":     0.8,
    "xtick.labelsize":    10,
    "ytick.labelsize":    10,
    "xtick.direction":    "in",
    "ytick.direction":    "in",
    "legend.fontsize":    10,
    "legend.framealpha":  0.9,
    "legend.edgecolor":   "0.75",
    "lines.linewidth":    1.8,
    "grid.linewidth":     0.5,
    "grid.alpha":         0.35,
    "savefig.dpi":        300,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.15,
})


# ── Load data ────────────────────────────────────────────────────────────────
def load_carriers(folder_name: str) -> pd.DataFrame:
    path = RES / folder_name / "generation_by_carrier.csv"
    if not path.exists():
        print(f"  WARNING: {path} not found — skipping")
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["label"] = df["carrier"].map(CARRIER_LABELS).fillna(df["carrier"])
    return df


def save(fig, name: str):
    for ext in ["png", "pdf"]:
        fig.savefig(OUT / f"{name}.{ext}")
    print(f"  Saved {name}.png / .pdf")
    plt.close(fig)


# ════════════════════════════════════════════════════════════════════════════
#  MIX 1 — Generation by group (clean / low-carbon / fossil)
#  Grouped bar chart — one group of bars per model, stacked by category.
#  Shows the high-level generation portfolio at a glance.
# ════════════════════════════════════════════════════════════════════════════
print("Plot 1 — Generation by group")

# Build summary: for each model, total TWh per group
rows = []
for model_name, folder in MODEL_FOLDERS.items():
    df = load_carriers(folder)
    if df.empty:
        continue
    for group, carriers in GROUPS.items():
        twh = df.loc[df["carrier"].isin(carriers), "generation_twh"].sum()
        rows.append({"model": model_name, "group": group, "twh": twh})

summary = pd.DataFrame(rows)

fig, ax = plt.subplots(figsize=(9, 5.5))

models  = summary["model"].unique()
groups  = list(GROUPS.keys())
x       = np.arange(len(models))
bar_w   = 0.55
bottoms = np.zeros(len(models))

for group in groups:
    vals = []
    for m in models:
        row = summary[(summary["model"] == m) & (summary["group"] == group)]
        vals.append(row["twh"].values[0] if not row.empty else 0)
    vals = np.array(vals)
    bars = ax.bar(x, vals, bar_w, bottom=bottoms,
                  color=GROUP_COLORS[group], label=group,
                  linewidth=0.4, edgecolor="white")
    # Label each segment if large enough
    for i, (v, b) in enumerate(zip(vals, bottoms)):
        if v > 5:
            ax.text(x[i], b + v / 2, f"{v:.0f}",
                    ha="center", va="center",
                    fontsize=9, color="white", fontweight="bold")
    bottoms += vals

ax.set_xticks(x)
ax.set_xticklabels(models)
ax.set_ylabel("Annual generation (TWh)")
ax.set_title("Annual Generation by Energy Group — GB 2023")
ax.set_ylim(0, bottoms.max() * 1.12)
ax.grid(axis="y", zorder=0)
ax.set_axisbelow(True)
ax.legend(loc="upper right", framealpha=0.9)

fig.tight_layout()
save(fig, "mix1_generation_by_group")


# ════════════════════════════════════════════════════════════════════════════
#  MIX 2 — Top carriers by generation (TWh) — one panel per model
#  Horizontal bar chart per model. Easy to read, shows what's driving CI.
# ════════════════════════════════════════════════════════════════════════════
print("Plot 2 — Top carriers per model")

models_available = [m for m in MODEL_FOLDERS if
                    (RES / MODEL_FOLDERS[m] / "generation_by_carrier.csv").exists()]
n_models = len(models_available)

fig, axes = plt.subplots(1, n_models,
                         figsize=(5.5 * n_models, 6),
                         sharey=True)
axes = np.atleast_1d(axes)

# Build a consistent carrier order from the first available model
ref_df = load_carriers(MODEL_FOLDERS[models_available[0]])
top_carriers = (ref_df[ref_df["generation_twh"] > 0.5]
                .sort_values("generation_twh", ascending=True)
                .tail(10)["carrier"].tolist())

for ax, model_name in zip(axes, models_available):
    df = load_carriers(MODEL_FOLDERS[model_name])
    if df.empty:
        continue

    sub = df[df["carrier"].isin(top_carriers)].copy()
    sub = sub.set_index("carrier").reindex(top_carriers)

    # Colour bars by group
    bar_colors = []
    for c in top_carriers:
        for g, members in GROUPS.items():
            if c in members:
                bar_colors.append(GROUP_COLORS[g])
                break
        else:
            bar_colors.append("#95A5A6")

    labels = [CARRIER_LABELS.get(c, c) for c in top_carriers]
    vals   = sub["generation_twh"].fillna(0).values

    bars = ax.barh(labels, vals, color=bar_colors,
                   linewidth=0.4, edgecolor="white", height=0.65)

    # Value labels on bars
    for bar, v in zip(bars, vals):
        if v > 1:
            ax.text(v + 0.5, bar.get_y() + bar.get_height() / 2,
                    f"{v:.1f} TWh", va="center", fontsize=8.5, color="0.3")

    ax.set_xlabel("Annual generation (TWh)")
    ax.set_title(model_name, fontweight="bold",
                 color=MODEL_COLORS.get(model_name, "k"))
    ax.set_xlim(0, vals.max() * 1.28)
    ax.grid(axis="x", zorder=0)
    ax.set_axisbelow(True)

# Legend for groups
from matplotlib.patches import Patch
legend_handles = [Patch(color=c, label=g) for g, c in GROUP_COLORS.items()]
fig.legend(handles=legend_handles, loc="lower center",
           ncol=3, bbox_to_anchor=(0.5, -0.04), framealpha=0.9)
fig.suptitle("Top Carriers by Annual Generation — GB 2023",
             fontsize=14, fontweight="bold")
fig.tight_layout(pad=1.2)
save(fig, "mix2_top_carriers")


# ════════════════════════════════════════════════════════════════════════════
#  MIX 3 — Emission factors by carrier (single chart, same for all models)
#  Horizontal bar — shows which carriers drive CI up. Reference chart.
# ════════════════════════════════════════════════════════════════════════════
print("Plot 3 — Emission factors")

# Use first available model (factors are same across models)
ref_df = load_carriers(MODEL_FOLDERS[models_available[0]])
ef = (ref_df[ref_df["mean_factor_gCO2_per_kWh"] > 0]
      .sort_values("mean_factor_gCO2_per_kWh", ascending=True)
      .copy())
ef["label"] = ef["carrier"].map(CARRIER_LABELS).fillna(ef["carrier"])

bar_colors = []
for c in ef["carrier"]:
    for g, members in GROUPS.items():
        if c in members:
            bar_colors.append(GROUP_COLORS[g])
            break
    else:
        bar_colors.append("#95A5A6")

fig, ax = plt.subplots(figsize=(8, max(4, len(ef) * 0.45)))

bars = ax.barh(ef["label"], ef["mean_factor_gCO2_per_kWh"],
               color=bar_colors, linewidth=0.4,
               edgecolor="white", height=0.65)

for bar, v in zip(bars, ef["mean_factor_gCO2_per_kWh"]):
    ax.text(v + 8, bar.get_y() + bar.get_height() / 2,
            f"{v:.0f}", va="center", fontsize=9, color="0.3")

ax.set_xlabel(r"Emission factor (gCO$_2$ kWh$^{-1}$)")
ax.set_title("Emission Factor by Carrier")
ax.set_xlim(0, ef["mean_factor_gCO2_per_kWh"].max() * 1.18)
ax.grid(axis="x", zorder=0)
ax.set_axisbelow(True)

from matplotlib.patches import Patch
legend_handles = [Patch(color=c, label=g) for g, c in GROUP_COLORS.items()]
ax.legend(handles=legend_handles, loc="lower right", framealpha=0.9)

fig.tight_layout()
save(fig, "mix3_emission_factors")


# ════════════════════════════════════════════════════════════════════════════
#  MIX 4 — Total annual CO2 emissions per model
#  Simple bar chart — one bar per model. Shows whether adding network
#  constraints changes the total system emissions picture.
# ════════════════════════════════════════════════════════════════════════════
print("Plot 4 — Total annual emissions")

em_rows = []
for model_name, folder in MODEL_FOLDERS.items():
    df = load_carriers(folder)
    if df.empty:
        continue
    total_mt = df["emissions_t"].sum() / 1e6  # convert to Mt CO2
    em_rows.append({"model": model_name, "MtCO2": total_mt})

em_df = pd.DataFrame(em_rows)

fig, ax = plt.subplots(figsize=(7, 4.5))

colors = [MODEL_COLORS.get(m, "#95A5A6") for m in em_df["model"]]
bars   = ax.bar(em_df["model"], em_df["MtCO2"],
                color=colors, width=0.45,
                linewidth=0.4, edgecolor="white")

for bar, v in zip(bars, em_df["MtCO2"]):
    ax.text(bar.get_x() + bar.get_width() / 2,
            v + 0.3,
            f"{v:.1f} Mt",
            ha="center", va="bottom",
            fontsize=11, fontweight="bold", color="0.25")

ax.set_ylabel(r"Total CO$_2$ emissions (Mt)")
ax.set_title("Total Annual System Emissions by Model — GB 2023")
ax.set_ylim(0, em_df["MtCO2"].max() * 1.18)
ax.grid(axis="y", zorder=0)
ax.set_axisbelow(True)

fig.tight_layout()
save(fig, "mix4_total_emissions")

print(f"\nAll done. Figures saved to: {OUT.resolve()}")
