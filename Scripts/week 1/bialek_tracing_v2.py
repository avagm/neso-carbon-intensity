"""
Bialek Tracing - Average Carbon Intensity Calculation
======================================================
Based on: Bialek, J., 1996. Tracing the flow of electricity.
IEE Proceedings-Generation, Transmission and Distribution, 143(4), pp.313-320.


"""

import numpy as np
import pandas as pd
import pypsa
import os

# ─────────────────────────────────────────────────────────────
# NESO Official Emission Factors (gCO2/kWh)
# Source: neso-ci-national-methodology_v2.pdf
# ─────────────────────────────────────────────────────────────
EMISSION_FACTORS = {
    "biomass":            120,
    "Biomass":            120,
    "coal":               937,
    "Coal":               937,
    "CCGT":               394,
    "Gas (Combined Cycle)": 394,
    "OCGT":               651,
    "Gas (Open Cycle)":   651,
    "large_hydro":        0,
    "small_hydro":        0,
    "Hydro":              0,
    "hydro":              0,
    "nuclear":            0,
    "Nuclear":            0,
    "oil":                935,
    "Oil":                935,
    "solar_pv":           0,
    "Solar":              0,
    "wind_onshore":       0,
    "wind_offshore":      0,
    "Wind":               0,
    "EU_import":          200,
    "waste_to_energy":    300,
    "landfill_gas":       200,
    "biogas":             120,
    "sewage_gas":         120,
    "advanced_biofuel":   120,
    "tidal_stream":       0,
    "shoreline_wave":     0,
    "tidal_lagoon":       0,
    "load_shedding":      0,
    "Other":              300,
}


def get_emission_factor(carrier):
    return EMISSION_FACTORS.get(carrier, 300)


def bialek_tracing(n, snapshot):
    
    buses = n.buses.index.tolist()
    n_buses = len(buses)
    bus_idx = {b: i for i, b in enumerate(buses)}

    # Step 1: Generation per bus
    gen_p = n.generators_t.p.loc[snapshot]
    gen_emission = n.generators["carrier"].map(get_emission_factor)

    gen_df = pd.DataFrame({
        "p":        gen_p,
        "emission": gen_emission,
        "bus":      n.generators["bus"]
    })

    bus_gen_mw = gen_df.groupby("bus")["p"].sum().reindex(buses, fill_value=0)
    bus_gen_em = gen_df.groupby("bus").apply(
        lambda g: (g["p"] * g["emission"]).sum()
    ).reindex(buses, fill_value=0)


    line_p = n.lines_t.p0.loc[snapshot] if snapshot in n.lines_t.p0.index else pd.Series(dtype=float)

    inflow = bus_gen_mw.copy()
    for line, p in line_p.items():
        b0 = n.lines.at[line, "bus0"]
        b1 = n.lines.at[line, "bus1"]
        if p > 0:
            inflow[b1] += p
        else:
            inflow[b0] += abs(p)


    A = np.eye(n_buses)

    for line, p in line_p.items():
        b0 = n.lines.at[line, "bus0"]
        b1 = n.lines.at[line, "bus1"]
        i0 = bus_idx[b0]
        i1 = bus_idx[b1]

        if p > 0 and inflow[b1] > 1e-6:
            A[i1, i0] -= p / inflow[b1]
        elif p < 0 and inflow[b0] > 1e-6:
            A[i0, i1] -= abs(p) / inflow[b0]


    source = np.zeros(n_buses)
    for i, bus in enumerate(buses):
        if inflow[bus] > 1e-6:
            source[i] = bus_gen_em[bus] / inflow[bus]


    try:
        ci = np.linalg.solve(A, source)
    except np.linalg.LinAlgError:
        ci, _, _, _ = np.linalg.lstsq(A, source, rcond=None)

    ci = np.clip(ci, 0, 1000)
    return pd.Series(ci, index=buses)


def run_all_snapshots(n, max_snapshots=None, verbose=True):
    snapshots = n.snapshots[:max_snapshots] if max_snapshots else n.snapshots
    total = len(snapshots)
    results = {}

    for i, snap in enumerate(snapshots):
        if verbose and i % 10 == 0:
            print(f"  {i}/{total} snapshots ({100*i//total}%)")
        try:
            results[snap] = bialek_tracing(n, snap)
        except Exception as e:
            if verbose:
                print(f"  Warning at {snap}: {e}")
            results[snap] = pd.Series(np.nan, index=n.buses.index)

    return pd.DataFrame(results).T


def main():
    print("=" * 60)
    print("Bialek Tracing - Carbon Intensity")
    print("=" * 60)

    path = "resources/network/Historical_2023_etys_solved.nc"
    print(f"\nLoading: {path}")
    n = pypsa.Network(path)

    print(f"Buses:      {len(n.buses)}")
    print(f"Lines:      {len(n.lines)}")
    print(f"Generators: {len(n.generators)}")
    print(f"Snapshots:  {len(n.snapshots)}")

    print(f"\nRunning Bialek tracing on {len(n.snapshots)} snapshots...")
    ci = run_all_snapshots(n)

    print(f"\nResults:")
    print(f"  Mean CI: {ci.mean().mean():.1f} gCO2/kWh")
    print(f"  Min CI:  {ci.min().min():.1f} gCO2/kWh")
    print(f"  Max CI:  {ci.max().max():.1f} gCO2/kWh")


    os.makedirs("resources/results", exist_ok=True)
    out = "resources/results/Historical_2023_etys_carbon_intensity.csv"
    ci.to_csv(out)
    print(f"\nSaved: {out}")


    summary = pd.DataFrame({
        "mean_gCO2_kWh": ci.mean(),
        "min_gCO2_kWh":  ci.min(),
        "max_gCO2_kWh":  ci.max(),
        "std_gCO2_kWh":  ci.std(),
    })
    summary = summary.join(n.buses[["x", "y"]], how="left")
    summary_out = "resources/results/Historical_2023_etys_carbon_intensity_summary.csv"
    summary.to_csv(summary_out)
    print(f"Saved: {summary_out}")

    print("\nTop 5 highest carbon intensity buses (mean):")
    print(summary["mean_gCO2_kWh"].sort_values(ascending=False).head())

    print("\nTop 5 lowest carbon intensity buses (mean):")
    print(summary["mean_gCO2_kWh"].sort_values().head())


if __name__ == "__main__":
    main()

