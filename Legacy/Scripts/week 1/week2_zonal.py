"""
week2_zonal.py
Week 2: 17-zone carbon intensity using Bialek upstream tracing.

Compares:
  - Copper-plate (single national average, from Week 1)
  - 17-zone Zonal network (per-zone CI using power flow tracing)
  - NESO regional carbon intensity from the API

ELEC60014 - NESO Project 3 | Imperial College London
"""

import pypsa
import pandas as pd
import numpy as np
import requests
import matplotlib.pyplot as plt

# Carbon factors (same as Week 1)
CARBON_FACTORS = {
    'CCGT':              394,
    'OCGT':              651,
    'coal':              937,
    'nuclear':           0,
    'wind_onshore':      0,
    'wind_offshore':     0,
    'solar_pv':          0,
    'large_hydro':       0,
    'small_hydro':       0,
    'biogas':            120,
    'advanced_biofuel':  120,
    'landfill_gas':      120,
    'sewage_gas':        120,
    'waste_to_energy':   300,
    'oil':               935,
    'tidal_stream':      0,
    'shoreline_wave':    0,
    'EU_import':         200,
    'load_shedding':     0,
}

# GB zone buses only (exclude external interconnector buses)
GB_ZONES = ['Z1_1','Z1_2','Z1_3','Z1_4','Z2','Z3','Z4','Z5','Z6',
            'Z7','Z8','Z9','Z10','Z11','Z12','Z13','Z14','Z15','Z16','Z17']

# 1: Load solved network
print("Loading solved network...")
n = pypsa.Network("resources/network/CopperPlate_2023_solved.nc")
print(f"Buses: {len(n.buses)}, Generators: {len(n.generators)}, Snapshots: {len(n.snapshots)}")

# 2: Copper-plate CI (Week 1 method, national average)
print("\nComputing copper-plate CI (national average)...")
dispatch   = n.generators_t.p
total_load = n.loads_t.p_set.sum(axis=1)

ci_copper = pd.Series(0.0, index=n.snapshots)
for gen in dispatch.columns:
    carrier = n.generators.loc[gen, 'carrier']
    factor  = CARBON_FACTORS.get(carrier, 0.0)
    ci_copper += dispatch[gen] * factor
ci_copper = ci_copper / total_load
ci_copper.name = 'copper_plate'

# 3: Per-bus generation and emission intensity
print("Computing per-bus generation and emission intensity...")

buses = n.buses.index.tolist()
bus_idx = {b: i for i, b in enumerate(buses)}
N = len(buses)

def get_bus_gen_and_ei(snapshot):
    """Return generation MW and emission intensity arrays for each bus."""
    gen_mw = np.zeros(N)
    ei_num = np.zeros(N)  # numerator for weighted average EI

    for gen_name in dispatch.columns:
        b = n.generators.loc[gen_name, 'bus']
        if b not in bus_idx:
            continue
        i       = bus_idx[b]
        mw      = max(float(dispatch.loc[snapshot, gen_name]), 0.0)
        carrier = n.generators.loc[gen_name, 'carrier']
        factor  = CARBON_FACTORS.get(carrier, 0.0)
        gen_mw[i] += mw
        ei_num[i] += factor * mw

    # Weighted average EI per bus
    ei = np.where(gen_mw > 1e-9, ei_num / gen_mw, 0.0)
    return gen_mw, ei

# 4: Bialek upstream tracing per snapshot
print("Running Bialek tracing for all snapshots...")

def build_flow_matrix(snapshot):
    """Build (N,N) flow matrix from link results. flows[i,j]>0 = inflow to i from j."""
    flows = np.zeros((N, N))
    if len(n.links) == 0:
        return flows
    p0 = n.links_t.p0.loc[snapshot]
    for link_name, row in n.links.iterrows():
        i0 = bus_idx.get(row.bus0)
        i1 = bus_idx.get(row.bus1)
        if i0 is None or i1 is None:
            continue
        flow = float(p0[link_name])
        if flow >= 0:
            flows[i1, i0] += flow   # inflow to bus1 from bus0
        else:
            flows[i0, i1] += -flow  # inflow to bus0 from bus1
    return flows

def bialek_aef(flows, gen_mw, ei):
    """
    Bialek upstream tracing — returns AEF per bus in gCO2/kWh.
    Uses source denominator convention (matching project slides).
    """
    # Throughflows: q_i = gen_i + sum of inflows
    inflows = np.maximum(flows, 0)
    q = gen_mw + inflows.sum(axis=1)
    q = np.where(q < 1e-9, 1e-9, q)

    # Build A matrix
    A = np.eye(N)
    for i in range(N):
        for j in range(N):
            if i != j and inflows[i, j] > 1e-9:
                A[i, j] = -inflows[i, j] / q[j]  # source denominator

    # Invert and compute AEF
    try:
        A_inv = np.linalg.inv(A)
    except np.linalg.LinAlgError:
        A_inv = np.linalg.pinv(A)

    ei_times_g = ei * gen_mw
    aef = (A_inv @ ei_times_g) / q
    return aef

# Run for all snapshots
aef_results = {}
for t in n.snapshots:
    flows       = build_flow_matrix(t)
    gen_mw, ei  = get_bus_gen_and_ei(t)
    aef         = bialek_aef(flows, gen_mw, ei)
    aef_results[t] = dict(zip(buses, aef))

aef_df = pd.DataFrame(aef_results).T  # rows=snapshots, cols=buses

# Keep only GB zones
gb_aef = aef_df[[z for z in GB_ZONES if z in aef_df.columns]]
print(f"Zonal AEF computed for {len(gb_aef)} snapshots across {len(gb_aef.columns)} GB zones")

# 5: Fetch NESO regional carbon intensity from API
print("\nFetching NESO regional carbon intensity from API...")
start = str(n.snapshots[0].date())
end   = str(n.snapshots[-1].date())
url   = (f"https://api.carbonintensity.org.uk/regional/intensity/"
         f"{start}T00:00Z/{end}T23:30Z")

try:
    resp = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
    resp.raise_for_status()
    records = []
    for entry in resp.json().get('data', []):
        ts  = pd.Timestamp(entry['from'])
        row = {'time': ts}
        for region in entry.get('regions', []):
            row[region['shortname']] = region['intensity']['forecast']
        records.append(row)
    neso_regional = pd.DataFrame(records).set_index('time')
    neso_regional.index = neso_regional.index.tz_convert('UTC')
    print(f"  NESO regions: {list(neso_regional.columns)}")
except Exception as e:
    print(f"  WARNING: Could not fetch regional data ({e})")
    neso_regional = pd.DataFrame()

# Also fetch national actual for copper-plate comparison
url_nat = f"https://api.carbonintensity.org.uk/intensity/{start}T00:00Z/{end}T23:59Z"
rows_nat = [{'time': pd.Timestamp(d['from']), 'actual': d['intensity']['actual']}
            for d in requests.get(url_nat, headers={"Accept": "application/json"}).json()['data']]
neso_national = pd.DataFrame(rows_nat).set_index('time')['actual'].dropna()
neso_national.index = neso_national.index.tz_convert('UTC')

# 6: Metrics
ci_copper.index = ci_copper.index.tz_localize('UTC')
gb_aef.index    = gb_aef.index.tz_localize('UTC')

common_nat = ci_copper.index.intersection(neso_national.index)
cp   = ci_copper.loc[common_nat]
neso = neso_national.loc[common_nat]

mae_cp  = (cp - neso).abs().mean()
rmse_cp = ((cp - neso)**2).mean()**0.5
corr_cp = cp.corr(neso)
bias_cp = (cp - neso).mean()

print(f"\n{'='*50}")
print(f"  WEEK 1 — Copper-plate vs NESO national actual")
print(f"{'='*50}")
print(f"  MAE  = {mae_cp:.1f} gCO2/kWh")
print(f"  RMSE = {rmse_cp:.1f} gCO2/kWh")
print(f"  r    = {corr_cp:.3f}")
print(f"  bias = {bias_cp:+.1f} gCO2/kWh")

# Spatial gradient in our zonal model
spatial_range = gb_aef.max(axis=1) - gb_aef.min(axis=1)
print(f"\n{'='*50}")
print(f"  WEEK 2 — Spatial gradient across 17 zones")
print(f"{'='*50}")
print(f"  Mean spread (max-min): {spatial_range.mean():.1f} gCO2/kWh")
print(f"  Max spread:            {spatial_range.max():.1f} gCO2/kWh")
print(f"\n  Per-zone mean CI (gCO2/kWh):")
print(gb_aef.mean().sort_values().round(1).to_string())

# 7: Plot
fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
fig.suptitle('Week 2: Copper-plate vs 17-Zone Zonal Network | Jan 2023',
             fontsize=13, fontweight='bold')

# Panel 1: copper-plate vs NESO national
ax = axes[0]
neso_national.plot(ax=ax, color='darkorange', lw=1.8, label='NESO national actual')
ci_copper.plot(ax=ax, color='steelblue', lw=1.5, ls='--', label='Copper-plate (Week 1)')
ax.set_ylabel('gCO₂/kWh')
ax.set_title(f'National average  |  MAE={mae_cp:.1f}  r={corr_cp:.3f}')
ax.legend()
ax.grid(alpha=0.3)

# Panel 2: zonal CI spread
ax = axes[1]
gb_aef_mean = gb_aef.mean(axis=1)
gb_aef_min  = gb_aef.min(axis=1)
gb_aef_max  = gb_aef.max(axis=1)
gb_aef_mean.plot(ax=ax, color='steelblue', lw=1.5, label='Zonal mean CI')
ax.fill_between(gb_aef.index, gb_aef_min, gb_aef_max,
                alpha=0.25, color='steelblue', label='Zone min-max range')
neso_national.plot(ax=ax, color='darkorange', lw=1.5, ls='--', label='NESO national actual')
ax.set_ylabel('gCO₂/kWh')
ax.set_title('17-Zone CI spread — band shows range across all zones')
ax.legend()
ax.grid(alpha=0.3)

# Panel 3: spatial gradient over time
ax = axes[2]
spatial_range.plot(ax=ax, color='crimson', lw=1.5)
ax.fill_between(spatial_range.index, 0, spatial_range, alpha=0.2, color='crimson')
ax.axhline(spatial_range.mean(), color='black', lw=0.8, ls='--',
           label=f'Mean = {spatial_range.mean():.1f} gCO₂/kWh')
ax.set_ylabel('Max − Min CI (gCO₂/kWh)')
ax.set_title('Spatial gradient — signal missed by copper-plate')
ax.legend()
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig('week2_zonal_result.png', dpi=150, bbox_inches='tight')
print("\nSaved: week2_zonal_result.png")
plt.show()