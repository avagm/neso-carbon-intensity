import pypsa
import pandas as pd
import numpy as np
import requests
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.lines import Line2D

# Carbon emission factors (gCO2/kWh) 
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
    'EU_import':        250,
}

# 17 GB zones in geographic order (N→S) with display labels
ZONE_ORDER = [
    'Z1_1', 'Z1_2', 'Z1_3', 'Z1_4',
    'Z2', 'Z3', 'Z4', 'Z5', 'Z6', 'Z7',
    'Z8', 'Z9', 'Z10', 'Z11', 'Z12',
    'Z13', 'Z14', 'Z15', 'Z16', 'Z17',
]

ZONE_LABELS = {
    'Z1_1': 'Z1_1 (Shetland)',
    'Z1_2': 'Z1_2 (W.Isles)',
    'Z1_3': 'Z1_3 (N.Scotland)',
    'Z1_4': 'Z1_4 (NW.Scot)',
    'Z2':   'Z2 (NE.Scot)',
    'Z3':   'Z3 (C.Scotland)',
    'Z4':   'Z4 (SW.Scot)',
    'Z5':   'Z5 (Borders)',
    'Z6':   'Z6 (N.England)',
    'Z7':   'Z7 (NE.England)',
    'Z8':   'Z8 (Yorks)',
    'Z9':   'Z9 (NW.England)',
    'Z10':  'Z10 (E.Midlands)',
    'Z11':  'Z11 (W.Midlands)',
    'Z12':  'Z12 (E.Anglia)',
    'Z13':  'Z13 (Wales/SW)',
    'Z14':  'Z14 (SE.England)',
    'Z15':  'Z15 (London)',
    'Z16':  'Z16 (S.England)',
    'Z17':  'Z17 (SW.England)',
}

FUEL_COLOURS = {
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
    'load_shedding':   '#ff0000',
}

# STEP 1: Load the network 

print("Loading network...")
n = pypsa.Network("resources/network/CopperPlate_2023.nc")

gb_buses = [b for b in n.buses.index if b.startswith('Z')]

print(f"\n=== Zonal network (17 zones) ===")
print(f"  Total buses:     {len(n.buses)}  ({len(gb_buses)} GB zones + {len(n.buses)-len(gb_buses)} external)")
print(f"  Links:           {len(n.links)}  (inter-zone + interconnectors)")
print(f"  Generators:      {len(n.generators)}")
print(f"  Storage units:   {len(n.storage_units)}")
print(f"  Loads:           {len(n.loads)}")
print(f"  Snapshots:       {len(n.snapshots)} half-hours")
print(f"  Period:          {n.snapshots[0]} → {n.snapshots[-1]}")

print(f"\n  Carrier types found:")
for carrier in sorted(n.generators.carrier.unique()):
    total_mw = n.generators[n.generators.carrier == carrier].p_nom.sum()
    factor = CARBON_FACTORS.get(carrier, '*** NOT IN DICT ***')
    print(f"    {carrier:<25} {total_mw:>8.0f} MW   EI={factor} gCO2/kWh")

print(f"\n  Inter-zone links:")
for _, row in n.links.iterrows():
    if row['bus0'].startswith('Z') and row['bus1'].startswith('Z'):
        print(f"    {row['bus0']:<8} ↔ {row['bus1']:<8}  {row['p_nom']:>6.0f} MW  ({row['carrier']})")

print(f"\n  Interconnectors to GB:")
for name, row in n.links.iterrows():
    if not (row['bus0'].startswith('Z') and row['bus1'].startswith('Z')):
        print(f"    {name:<35}  {row['p_nom']:>6.0f} MW")

# STEP 2: Subset snapshots (same January window as CopperPlate for comparison)

n.set_snapshots(n.snapshots[:1488])  # ~Jan 1–31 (half-hourly)
print(f"\n  Subset: {len(n.snapshots)} snapshots  "
      f"({n.snapshots[0]} → {n.snapshots[-1]})")

n.consistency_check()

# STEP 3: Solve (network-constrained economic dispatch)

print("\nSolving zonal network-constrained dispatch with Gurobi...")
n.optimize(solver_name="gurobi")
print("Solved.")
gen_zones  = n.generators_t.p.sum(axis=1)
load_zones = n.loads_t.p_set[
    [c for c in n.loads_t.p_set.columns if c.startswith('load_Z')]
].sum(axis=1)
balance = gen_zones - load_zones
print(f"\n  Generation vs demand balance:")
print(f"    Max imbalance:  {balance.abs().max():.2f} MW")
print(f"    Avg generation: {gen_zones.mean():.0f} MW")
print(f"    Avg demand:     {load_zones.mean():.0f} MW")

# STEP 4: Per-zone carbon intensity — Bialek upstream tracing
#
# For each snapshot t, solve the linear system:
#   (diag(q) - F_in) × CI = local_emission
# where:
#   q[i]           = local_gen[i] + Σ_j F_in[i,j]   (gross inflow to zone i)
#   F_in[i,j]      = MW flowing INTO zone i FROM zone j in snapshot t
#   local_gen[i]   = generator dispatch + storage discharge at zone i
#                    (load_shedding excluded; EU imports added via link flows)
#   local_emission[i] = Σ_k (p_ik × EI_k) for generators at zone i

print("\nCalculating per-zone carbon intensity (Bialek upstream tracing)...")

gb_zones = [b for b in n.buses.index if b.startswith('Z')]
zone_set  = set(gb_zones)
zone_idx  = {z: i for i, z in enumerate(gb_zones)}
n_zones   = len(gb_zones)

# ── Pre-compute per-zone generation & emissions 
# load_shedding has no entry in CARBON_FACTORS → map gives NaN → excluded
gen_ef_map   = n.generators['carrier'].map(CARBON_FACTORS)
gen_gb_mask  = n.generators['bus'].isin(zone_set) & gen_ef_map.notna()
gen_gb_names = n.generators.index[gen_gb_mask]
gen_gb_bus   = n.generators.loc[gen_gb_names, 'bus']
gen_gb_ef    = gen_ef_map[gen_gb_names]

disp  = n.generators_t.p[gen_gb_names].clip(lower=0)     # (T × n_gen)
emiss = disp.multiply(gen_gb_ef, axis=1)                  # (T × n_gen)

local_gen_df   = (disp.T.groupby(gen_gb_bus).sum().T
                  .reindex(columns=gb_zones, fill_value=0.0))
local_emiss_df = (emiss.T.groupby(gen_gb_bus).sum().T
                  .reindex(columns=gb_zones, fill_value=0.0))

# Storage discharge (EI = 0 — clean passthrough, avoids double-counting)
if hasattr(n.storage_units_t, 'p') and len(n.storage_units_t.p.columns) > 0:
    stor_gb_mask  = n.storage_units['bus'].isin(zone_set)
    stor_gb_names = n.storage_units.index[stor_gb_mask]
    if len(stor_gb_names) > 0:
        stor_gb_bus = n.storage_units.loc[stor_gb_names, 'bus']
        stor_disp   = n.storage_units_t.p[stor_gb_names].clip(lower=0)
        stor_zones  = (stor_disp.T.groupby(stor_gb_bus).sum().T
                       .reindex(columns=gb_zones, fill_value=0.0))
        local_gen_df = local_gen_df.add(stor_zones)

# Pre-cache link metadata ─
link_b0 = n.links['bus0']
link_b1 = n.links['bus1']
EU_EI   = CARBON_FACTORS['EU_import']
MIN_Q   = 1.0   # MW — zones below this threshold get CI = 0

# Per-snapshot Bialek solve 
ci_rows = []
for t in n.snapshots:
    local_g = local_gen_df.loc[t].values.copy()
    local_e = local_emiss_df.loc[t].values.copy()
    F_in    = np.zeros((n_zones, n_zones))

    if hasattr(n.links_t, 'p0') and t in n.links_t.p0.index:
        p0_t = n.links_t.p0.loc[t]
        for lname in n.links.index:
            if lname not in p0_t.index:
                continue
            p0 = p0_t[lname]
            if abs(p0) < 1e-6:
                continue
            b0, b1   = link_b0[lname], link_b1[lname]
            b0_gb    = b0 in zone_set
            b1_gb    = b1 in zone_set

            if b0_gb and b1_gb:
                # Zone-to-zone: positive p0 → flow b0→b1
                if p0 > 0:
                    F_in[zone_idx[b1], zone_idx[b0]] += p0
                else:
                    F_in[zone_idx[b0], zone_idx[b1]] -= p0

            elif b0_gb and not b1_gb:
                # GB (b0) ↔ external (b1): import when p0 < 0
                if p0 < 0:
                    imp = -p0
                    local_g[zone_idx[b0]] += imp
                    local_e[zone_idx[b0]] += imp * EU_EI

            elif not b0_gb and b1_gb:
                # external (b0) ↔ GB (b1): import when p0 > 0
                if p0 > 0:
                    local_g[zone_idx[b1]] += p0
                    local_e[zone_idx[b1]] += p0 * EU_EI

    # Gross inflow
    q = local_g + F_in.sum(axis=1)

    # Bialek system
    M     = np.diag(q) - F_in
    b_vec = local_e.copy()

    # Guard: near-zero inflow → CI = 0
    low_q              = q < MIN_Q
    M[low_q, :]        = 0.0
    M[low_q, low_q]    = 1.0
    b_vec[low_q]       = 0.0

    try:
        CI = np.linalg.solve(M, b_vec)
    except np.linalg.LinAlgError:
        CI = np.where(q >= MIN_Q, local_e / np.maximum(q, MIN_Q), 0.0)

    CI = np.clip(CI, 0.0, 1000.0)   # physical bounds: max real CI ≈ 937 gCO2/kWh
    ci_rows.append(CI)

ci_zonal = pd.DataFrame(ci_rows, index=n.snapshots, columns=gb_zones)

# ── Load per zone (needed for national CI and plots) 
load_by_zone = {}
for col in n.loads_t.p_set.columns:
    if col.startswith('load_Z'):
        zone = col.replace('load_', '')
        load_by_zone[zone] = n.loads_t.p_set[col]
load_by_zone  = pd.DataFrame(load_by_zone)
zones_present = [z for z in ZONE_ORDER if z in ci_zonal.columns]

# National CI = demand-weighted average (conservation: equals total_emissions / total_load)
total_load_all = load_by_zone[zones_present].sum(axis=1)
ci_national    = (
    ci_zonal[zones_present].multiply(load_by_zone[zones_present]).sum(axis=1)
    / total_load_all
)
ci_national.name = "ci_zonal_national_gCO2_per_kWh"

# gen_df with MultiIndex (kept for generation-mix plot in Step 9) 
gen_df = n.generators_t.p.copy()
gen_df.columns = pd.MultiIndex.from_arrays(
    [n.generators.loc[gen_df.columns, 'bus'],
     n.generators.loc[gen_df.columns, 'carrier']],
    names=['bus', 'carrier'],
)

print(f"\n  National CI (demand-weighted Bialek) (gCO2/kWh):")
print(ci_national.describe().round(1).to_string())

print(f"\n  Per-zone mean CI (gCO2/kWh):")
for zone in zones_present:
    print(f"    {ZONE_LABELS.get(zone, zone):<30} {ci_zonal[zone].mean():>6.1f}")

# STEP 5: Locational marginal prices (LMPs) per zone

print("\nExtracting locational marginal prices...")

# n.buses_t.marginal_price is populated after optimization
if hasattr(n.buses_t, 'marginal_price') and len(n.buses_t.marginal_price.columns) > 0:
    lmp = n.buses_t.marginal_price[[b for b in gb_zones
                                    if b in n.buses_t.marginal_price.columns]]
    print(f"\n  LMP summary per zone (£/MWh):")
    for zone in [z for z in zones_present if z in lmp.columns]:
        print(f"    {ZONE_LABELS.get(zone, zone):<30}  "
              f"mean={lmp[zone].mean():>7.2f}  "
              f"min={lmp[zone].min():>7.2f}  "
              f"max={lmp[zone].max():>7.2f}")
else:
    lmp = pd.DataFrame(index=n.snapshots)
    print("  LMPs not available (check solver / shadow prices).")

# STEP 6: Fetch NESO actual carbon intensity (national, for validation)

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
neso_df.index = neso_df.index.tz_convert('UTC').tz_localize(None)
neso_actual = neso_df['actual'].dropna()
print(f"  Fetched {len(neso_actual)} NESO actual values")

# STEP 7: Compare national CI against NESO

common = ci_national.index.intersection(neso_actual.index)
ci_n   = ci_national.loc[common]
neso_n = neso_actual.loc[common]

if len(common) == 0:
    print("\n  WARNING: No overlapping timestamps between model and NESO.")
else:
    mae  = (ci_n - neso_n).abs().mean()
    rmse = ((ci_n - neso_n) ** 2).mean() ** 0.5
    corr = ci_n.corr(neso_n)
    bias = (ci_n - neso_n).mean()

    print(f"\n{'='*55}")
    print(f"  ZONAL MODEL vs NESO National Actual")
    print(f"{'='*55}")
    print(f"  Overlapping points: {len(common)}")
    print(f"  MAE            = {mae:.1f} gCO2/kWh")
    print(f"  RMSE           = {rmse:.1f} gCO2/kWh")
    print(f"  Pearson r      = {corr:.3f}")
    print(f"  Mean bias      = {bias:+.1f} gCO2/kWh")
    print(f"  Our mean CI    = {ci_n.mean():.1f} gCO2/kWh")
    print(f"  NESO mean CI   = {neso_n.mean():.1f} gCO2/kWh")
    print(f"{'='*55}")

# STEP 8: Inter-zone flow utilisation

print("\nInter-zone link utilisation:")
if hasattr(n.links_t, 'p0') and len(n.links_t.p0.columns) > 0:
    for link in n.links.index:
        if link not in n.links_t.p0.columns:
            continue
        b0, b1 = n.links.loc[link, 'bus0'], n.links.loc[link, 'bus1']
        if not (b0.startswith('Z') and b1.startswith('Z')):
            continue
        cap   = n.links.loc[link, 'p_nom']
        flows = n.links_t.p0[link].abs()
        util  = flows.mean() / cap * 100
        print(f"  {b0:<8} ↔ {b1:<8}  cap={cap:>6.0f} MW  "
              f"mean_flow={flows.mean():>6.0f} MW  utilisation={util:>5.1f}%")

# STEP 9: Plots

fig = plt.figure(figsize=(18, 22))
fig.suptitle(
    f"17-Zone Zonal Model  |  {n.snapshots[0].strftime('%b %Y')}  |  MAE={mae:.1f}  RMSE={rmse:.1f}  r={corr:.3f}",
    fontsize=14, fontweight='bold'
)

gs = fig.add_gridspec(4, 2, hspace=0.45, wspace=0.35)

# Panel A: National CI comparison 
ax_nat = fig.add_subplot(gs[0, :])
if len(common) > 0:
    neso_n.plot(ax=ax_nat, color='darkorange', lw=1.2, label='NESO actual')
    ci_n.plot(ax=ax_nat, color='steelblue', lw=1.0, ls='--', label='Zonal model (national)')
ax_nat.set_ylabel('gCO₂/kWh')
ax_nat.set_title('National carbon intensity: Zonal model vs NESO actual')
ax_nat.legend(loc='upper right')
ax_nat.grid(alpha=0.3)

# Panel B: Per-zone mean CI bar chart 
ax_ci = fig.add_subplot(gs[1, 0])
ci_means  = ci_zonal[zones_present].mean()
ci_stds   = ci_zonal[zones_present].std()
labels    = [ZONE_LABELS.get(z, z) for z in zones_present]
colours   = plt.cm.RdYlGn_r(
    mcolors.Normalize(vmin=ci_means.min(), vmax=ci_means.max())(ci_means)
)
bars = ax_ci.barh(labels, ci_means, xerr=ci_stds, color=colours,
                  capsize=3, error_kw={'lw': 0.8})
ax_ci.set_xlabel('Mean CI (gCO₂/kWh)')
ax_ci.set_title('Per-zone mean carbon intensity')
ax_ci.invert_yaxis()
ax_ci.grid(axis='x', alpha=0.3)

# Panel C: Per-zone mean LMP bar chart 
ax_lmp = fig.add_subplot(gs[1, 1])
if not lmp.empty:
    lmp_zones   = [z for z in zones_present if z in lmp.columns]
    lmp_means   = lmp[lmp_zones].mean()
    lmp_stds    = lmp[lmp_zones].std()
    lmp_labels  = [ZONE_LABELS.get(z, z) for z in lmp_zones]
    lmp_colours = plt.cm.RdYlGn(
        mcolors.Normalize(vmin=lmp_means.min(), vmax=lmp_means.max())(lmp_means)
    )
    ax_lmp.barh(lmp_labels, lmp_means, xerr=lmp_stds,
                color=lmp_colours, capsize=3, error_kw={'lw': 0.8})
    ax_lmp.set_xlabel('Mean LMP (£/MWh)')
    ax_lmp.set_title('Per-zone locational marginal price')
    ax_lmp.invert_yaxis()
    ax_lmp.grid(axis='x', alpha=0.3)
else:
    ax_lmp.text(0.5, 0.5, 'LMPs not available', ha='center', va='center',
                transform=ax_lmp.transAxes)
    ax_lmp.set_title('Locational marginal prices')

# Panel D: Zonal CI time series heat-map
ax_hm = fig.add_subplot(gs[2, :])
hm_data = ci_zonal[zones_present].T.values
im = ax_hm.imshow(
    hm_data,
    aspect='auto',
    cmap='RdYlGn_r',
    vmin=0,
    vmax=max(200, float(ci_zonal[zones_present].values.max())),
    interpolation='nearest',
)
ax_hm.set_yticks(range(len(zones_present)))
ax_hm.set_yticklabels(labels, fontsize=7)
# Show ~10 x-tick labels
step = max(1, len(n.snapshots) // 10)
xtick_pos = range(0, len(n.snapshots), step)
xtick_lbl = [str(n.snapshots[i])[:13] for i in xtick_pos]
ax_hm.set_xticks(list(xtick_pos))
ax_hm.set_xticklabels(xtick_lbl, rotation=30, ha='right', fontsize=7)
ax_hm.set_title('Zonal carbon intensity heat-map (gCO₂/kWh)')
plt.colorbar(im, ax=ax_hm, fraction=0.02, pad=0.01, label='gCO₂/kWh')

# Panel E: National generation mix 
ax_mix = fig.add_subplot(gs[3, :])
# Aggregate national dispatch by carrier
national_gen = gen_df.T.groupby(level='carrier').sum().T
plot_fuels = [f for f in FUEL_COLOURS if f in national_gen.columns]
if plot_fuels:
    gen_pct = national_gen[plot_fuels].div(total_load_all, axis=0) * 100
    gen_pct.plot.area(
        ax=ax_mix,
        color=[FUEL_COLOURS[f] for f in plot_fuels],
        linewidth=0,
        legend=True,
    )
ax_mix.set_ylabel('% of demand met')
ax_mix.set_title('National generation mix (zonal model)')
ax_mix.legend(loc='upper right', ncol=5, fontsize=7)
ax_mix.set_ylim(0, 120)
ax_mix.grid(alpha=0.3)

plt.savefig('zonal_result.png', dpi=150, bbox_inches='tight')
print("\nPlot saved: zonal_result.png")
plt.show()

# STEP 10: Zonal summary table

print(f"\n{'='*75}")
print(f"  ZONAL SUMMARY TABLE")
print(f"{'='*75}")
header = f"{'Zone':<30} {'Mean CI':>9} {'Std CI':>8}"
if not lmp.empty:
    header += f"  {'Mean LMP':>9} {'Std LMP':>8}"
print(header)
print('-' * (len(header)))
for zone in zones_present:
    row = f"{ZONE_LABELS.get(zone, zone):<30} {ci_zonal[zone].mean():>9.1f} {ci_zonal[zone].std():>8.1f}"
    if not lmp.empty and zone in lmp.columns:
        row += f"  {lmp[zone].mean():>9.2f} {lmp[zone].std():>8.2f}"
    print(row)
print('=' * (len(header)))
