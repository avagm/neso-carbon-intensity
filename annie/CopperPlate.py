import pypsa
import pandas as pd
import numpy as np
import requests
import matplotlib.pyplot as plt
 
# ── Carbon emission factors (gCO2/kWh) ────────────────────────────────────────
# Keys MUST match the carrier names PyPSA-GB actually uses (case-sensitive).
# Verified from the dashboard output: CCGT, OCGT, EU_import, advanced_biofuel,
# biogas, coal, landfill_gas, large_hydro, nuclear, oil, sewage_gas,
# shoreline_wave, small_hydro, solar_pv, tidal_stream, waste_to_energy,
# wind_offshore, wind_onshore.
CARBON_FACTORS = {
    'CCGT':             394,
    'OCGT':             651,
    'coal':             937,
    'oil':              935,
    'nuclear':            0,
    'wind_onshore':       0,
    'wind_offshore':      0,
    'solar_pv':           0,
    'large_hydro':        0,
    'small_hydro':        0,
    'tidal_stream':       0,
    'shoreline_wave':     0,
    'biomass':          120,
    'advanced_biofuel': 120,
    'biogas':           120,
    'landfill_gas':     490,
    'sewage_gas':       490,
    'waste_to_energy':  580,
    'EU_import':        250,   # ~EU grid average 2023
}
 
 
# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Load the network
# ─────────────────────────────────────────────────────────────────────────────
 
print("Loading network...")
n = pypsa.Network("resources/network/CopperPlate_2023.nc")
 
print(f"\n=== Network before copper-plate collapse ===")
print(f"  Buses:           {len(n.buses)}")
print(f"  Lines:           {len(n.lines)}")
print(f"  Generators:      {len(n.generators)}")
print(f"  Storage units:   {len(n.storage_units)}")
print(f"  Stores:          {len(n.stores)}")
print(f"  Links:           {len(n.links)}")
print(f"  Snapshots:       {len(n.snapshots)} half-hours")
print(f"  Period:          {n.snapshots[0]} → {n.snapshots[-1]}")
print(f"\n  Carrier types found:")
for carrier in sorted(n.generators.carrier.unique()):
    total_mw = n.generators[n.generators.carrier == carrier].p_nom.sum()
    factor = CARBON_FACTORS.get(carrier, '*** NOT IN DICT ***')
    print(f"    {carrier:<25} {total_mw:>8.0f} MW   EI={factor} gCO2/kWh")
 
 
# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Collapse to a single copper-plate bus
# ─────────────────────────────────────────────────────────────────────────────
 
print("\nCollapsing to single bus...")
 
n.add("Bus", "GB_copper", carrier="AC", x=-2.0, y=54.0)
 
# Move all components to the single bus
n.generators["bus"]    = "GB_copper"
n.loads["bus"]         = "GB_copper"
if len(n.storage_units) > 0:
    n.storage_units["bus"] = "GB_copper"
if len(n.stores) > 0:
    n.stores["bus"]    = "GB_copper"
 
# Remove transmission entirely — it's meaningless in copper-plate AND saves memory
if len(n.links) > 0:
    n.remove("Link", n.links.index)
if len(n.lines) > 0:
    n.remove("Line", n.lines.index)
if len(n.transformers) > 0:
    n.remove("Transformer", n.transformers.index)
 
# Drop the original buses
original_buses = n.buses.index[n.buses.index != "GB_copper"].tolist()
n.remove("Bus", original_buses)
 
print(f"\n=== Network after copper-plate collapse ===")
print(f"  Buses:      {len(n.buses)}  (should be 1)")
print(f"  Lines:      {len(n.lines)}  (should be 0)")
print(f"  Links:      {len(n.links)}  (should be 0)")
print(f"  Generators: {len(n.generators)}")
 
 
# ─────────────────────────────────────────────────────────────────────────────
# STEP 2.5: SUBSET SNAPSHOTS (memory fix for 16 GB machines)
# Halves resolution to hourly, keeps full year coverage. Removes the [::2]
# line if you have ≥32 GB RAM and want full half-hourly resolution.
# ─────────────────────────────────────────────────────────────────────────────
 
n.set_snapshots(n.snapshots[:1488])    # first 31 days × 48 half-hours
# July (summer, solar dominance, low demand)
#n.set_snapshots(n.snapshots[8688:10128])  # ~Jul 1 to Jul 31
# snapshot_weightings stays at default 0.5 (half-hourly)
print(f"\n  Subset to hourly resolution: {len(n.snapshots)} snapshots")
 
 
# Sanitize before solving — fixes the "undefined carriers" warnings
n.consistency_check()
 
 
# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: Solve (economic dispatch)
# ─────────────────────────────────────────────────────────────────────────────
 
print("\nSolving economic dispatch with Gurobi...")
n.optimize(solver_name="gurobi")
print("Solved.")
 
total_gen    = n.generators_t.p.sum(axis=1)
total_demand = n.loads_t.p_set.sum(axis=1)
balance      = total_gen - total_demand
print(f"\n  Generation vs demand balance:")
print(f"    Max imbalance:  {balance.abs().max():.2f} MW (should be near zero)")
print(f"    Avg generation: {total_gen.mean():.0f} MW")
print(f"    Avg demand:     {total_demand.mean():.0f} MW")
 
 
# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: Carbon intensity (aggregate dispatch by carrier first — much faster)
# ─────────────────────────────────────────────────────────────────────────────
 
print("\nCalculating carbon intensity...")
 
# Aggregate per-generator dispatch into per-carrier dispatch
dispatch_by_carrier = (
    n.generators_t.p.T
     .groupby(n.generators.carrier)
     .sum()
     .T
)
 
total_load = n.loads_t.p_set.sum(axis=1)
 
# Build per-carrier emission factor series (zero for unknown carriers)
unknown_carriers = [c for c in dispatch_by_carrier.columns if c not in CARBON_FACTORS]
if unknown_carriers:
    print(f"\n  WARNING: Carriers not in CARBON_FACTORS (treated as 0):")
    for c in unknown_carriers:
        print(f"    {c}")
 
ef = pd.Series({c: CARBON_FACTORS.get(c, 0.0) for c in dispatch_by_carrier.columns})
 
# CI = Σ (dispatch_carrier × EI_carrier) / total_load
emissions_by_carrier = dispatch_by_carrier.multiply(ef, axis=1)   # gCO2-MW (per timestep)
ci = emissions_by_carrier.sum(axis=1) / total_load
ci.name = "ci_copper_plate_gCO2_per_kWh"
 
print(f"\n  Carbon intensity summary (gCO2/kWh):")
print(ci.describe().round(1).to_string())
 
print(f"\n  Average contribution by fuel (gCO2/kWh):")
contrib = emissions_by_carrier.div(total_load, axis=0).mean()
for carrier, val in contrib[contrib > 0.1].sort_values(ascending=False).items():
    print(f"    {carrier:<25} {val:>6.1f}")
 
 
# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: Fetch NESO actual carbon intensity (chunked: API max ~30 days)
# ─────────────────────────────────────────────────────────────────────────────
 
print("\nFetching NESO actual carbon intensity from API...")
 
def fetch_neso_chunked(start_ts: pd.Timestamp, end_ts: pd.Timestamp,
                       chunk_days: int = 14) -> pd.DataFrame:
    rows = []
    cur = start_ts
    while cur < end_ts:
        chunk_end = min(cur + pd.Timedelta(days=chunk_days), end_ts)
        url = (f"https://api.carbonintensity.org.uk/intensity/"
               f"{cur.strftime('%Y-%m-%dT%H:%MZ')}/"
               f"{chunk_end.strftime('%Y-%m-%dT%H:%MZ')}")
        resp = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
        resp.raise_for_status()
        for item in resp.json()['data']:
            rows.append({
                'time':     pd.Timestamp(item['from']),
                'actual':   item['intensity']['actual'],
                'forecast': item['intensity']['forecast'],
            })
        cur = chunk_end + pd.Timedelta(minutes=30)
    return pd.DataFrame(rows).drop_duplicates('time').set_index('time')
 
start_ts = pd.Timestamp(n.snapshots[0]).tz_localize('UTC')
end_ts   = pd.Timestamp(n.snapshots[-1]).tz_localize('UTC') + pd.Timedelta(hours=1)
 
neso_df = fetch_neso_chunked(start_ts, end_ts)
neso_df.index = neso_df.index.tz_convert('UTC').tz_localize(None)  # match PyPSA naive index
# Use actual where available, fall back to forecast (API often returns null actual for older months)
neso_actual = neso_df['actual'].fillna(neso_df['forecast']).dropna()
print(f"  Fetched {len(neso_actual)} NESO values  "
      f"(actual: {neso_df['actual'].notna().sum()}, "
      f"forecast fallback: {neso_df['actual'].isna().sum()})")
 
 
# ─────────────────────────────────────────────────────────────────────────────
# STEP 6: Compare (resample NESO to hourly to align with our snapshots)
# ─────────────────────────────────────────────────────────────────────────────
 
# NESO is half-hourly
 
common = ci.index.intersection(neso_actual.index)
ci_a   = ci.loc[common]
neso_a = neso_actual.loc[common]

print(f"  Overlapping timestamps: {len(common)} "
      f"(model: {len(ci)}, NESO: {len(neso_actual)})")
if len(common) > 0:
    print(f"  Overlap range: {common[0]} → {common[-1]}")

if len(common) == 0:
    print("\n  WARNING: No overlapping timestamps between model and NESO.")
    print(f"    Model index sample: {list(ci.index[:3])}")
    print(f"    NESO  index sample: {list(neso_actual.index[:3])}")
else:
    mae  = (ci_a - neso_a).abs().mean()
    rmse = ((ci_a - neso_a) ** 2).mean() ** 0.5
    corr = ci_a.corr(neso_a)
    bias = (ci_a - neso_a).mean()
 
    print(f"\n{'='*50}")
    print(f"  RESULTS vs NESO National Actual")
    print(f"{'='*50}")
    print(f"  Overlapping points: {len(common)}")
    print(f"  MAE            = {mae:.1f} gCO2/kWh")
    print(f"  RMSE           = {rmse:.1f} gCO2/kWh")
    print(f"  Pearson r      = {corr:.3f}")
    print(f"  Mean bias      = {bias:+.1f} gCO2/kWh")
    print(f"  Our mean CI    = {ci_a.mean():.1f} gCO2/kWh")
    print(f"  NESO mean CI   = {neso_a.mean():.1f} gCO2/kWh")
    print(f"{'='*50}")
 
 
# ─────────────────────────────────────────────────────────────────────────────
# STEP 7: Plot
# ─────────────────────────────────────────────────────────────────────────────
 
if len(common) > 0:
    import matplotlib.dates as mdates

    # Convert to plain Python datetimes — matplotlib handles these reliably
    # on all platforms/versions, unlike pandas DatetimeIndex directly
    x_cmp  = [t.to_pydatetime() for t in common]
    x_full = [t.to_pydatetime() for t in n.snapshots]

    fig, axes = plt.subplots(3, 1, figsize=(14, 11))
    fig.suptitle(
        f"Copper-Plate vs NESO  |  MAE={mae:.1f}  RMSE={rmse:.1f}  r={corr:.3f}",
        fontsize=13, fontweight='bold'
    )

    # Panel 1 — CI comparison
    ax = axes[0]
    ax.plot(x_cmp, neso_a.values, color='darkorange', lw=1.2, label='NESO actual')
    ax.plot(x_cmp, ci_a.values,   color='steelblue',  lw=1.0, ls='--', label='Copper-plate (ours)')
    ax.set_xlim(x_cmp[0], x_cmp[-1])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.set_ylabel('gCO₂/kWh')
    ax.set_title('National average carbon intensity')
    ax.legend(loc='upper right')
    ax.grid(alpha=0.3)

    # Panel 2 — residual
    ax = axes[1]
    residual = (ci_a - neso_a).values
    ax.plot(x_cmp, residual, color='crimson', lw=0.8)
    ax.fill_between(x_cmp, 0, residual, alpha=0.2, color='crimson')
    ax.axhline(0, color='black', lw=0.8, ls='--')
    ax.set_xlim(x_cmp[0], x_cmp[-1])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.set_ylabel('Residual (gCO₂/kWh)')
    ax.set_title(f'Our model minus NESO actual  |  bias = {bias:+.1f} gCO₂/kWh')
    ax.grid(alpha=0.3)

    # Panel 3 — generation mix
    ax = axes[2]
    fuel_colours = {
        'CCGT':            '#f4a460',
        'OCGT':            '#cd853f',
        'coal':            '#696969',
        'oil':             '#8b4513',
        'nuclear':         '#9370db',
        'wind_onshore':    '#87ceeb',
        'wind_offshore':   '#4682b4',
        'solar_pv':        '#ffd700',
        'large_hydro':     '#4169e1',
        'small_hydro':     '#6495ed',
        'biomass':         '#228b22',
        'advanced_biofuel':'#3cb371',
        'biogas':          '#32cd32',
        'landfill_gas':    '#9acd32',
        'waste_to_energy': '#bdb76b',
        'EU_import':       '#ff6347',
        'tidal_stream':    '#00ced1',
        'shoreline_wave':  '#20b2aa',
        'sewage_gas':      '#daa520',
    }
    plot_fuels = [f for f in fuel_colours if f in dispatch_by_carrier.columns]
    if plot_fuels:
        gen_pct = dispatch_by_carrier[plot_fuels].div(total_load, axis=0) * 100
        ax.stackplot(
            x_full,
            [gen_pct[f].values for f in plot_fuels],
            colors=[fuel_colours[f] for f in plot_fuels],
            labels=plot_fuels,
        )
        ax.set_xlim(x_full[0], x_full[-1])
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.set_ylabel('% of demand met')
    ax.set_title('Generation mix')
    ax.legend(loc='upper right', ncol=4, fontsize=7)
    ax.set_ylim(0, 110)
    ax.grid(alpha=0.3)
 
    plt.tight_layout()
    plt.savefig('copper_plate_result.png', dpi=150, bbox_inches='tight')
    print("\nPlot saved: copper_plate_result.png")
    plt.show()
 