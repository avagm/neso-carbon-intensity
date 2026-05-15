import pypsa
import pandas as pd
import numpy as np
import requests
import matplotlib.pyplot as plt

# Carbon factors matching PyPSA-GB 2023 carrier names 
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

# Load solved network 
print("Loading solved network...")
n = pypsa.Network("resources/network/CopperPlate_2023_solved.nc")
print(f"Generators: {len(n.generators)}, Snapshots: {len(n.snapshots)}")

# Calculate carbon intensity 
dispatch   = n.generators_t.p
total_load = n.loads_t.p_set.sum(axis=1)

ci = pd.Series(0.0, index=n.snapshots)
for gen in dispatch.columns:
    carrier = n.generators.loc[gen, 'carrier']
    factor  = CARBON_FACTORS.get(carrier, 0.0)
    ci += dispatch[gen] * factor
ci = ci / total_load
ci.name = "ci_copper_plate"

print(f"\nCarbon intensity (gCO2/kWh):")
print(ci.describe().round(1))

# Fetch NESO actual 
start = str(n.snapshots[0].date())
end   = str(n.snapshots[-1].date())
url   = f"https://api.carbonintensity.org.uk/intensity/{start}T00:00Z/{end}T23:59Z"
resp  = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
rows  = [{'time': pd.Timestamp(d['from']),
          'actual': d['intensity']['actual']} for d in resp.json()['data']]
neso  = pd.DataFrame(rows).set_index('time')['actual'].dropna()
neso.index = neso.index.tz_convert('UTC')

# Compare 
ci.index = ci.index.tz_localize('UTC')
common = ci.index.intersection(neso.index)
ci_a, neso_a = ci.loc[common], neso.loc[common]

mae  = (ci_a - neso_a).abs().mean()
rmse = ((ci_a - neso_a)**2).mean()**0.5
corr = ci_a.corr(neso_a)
bias = (ci_a - neso_a).mean()

print(f"\nVs NESO actual:")
print(f"  MAE  = {mae:.1f} gCO2/kWh")
print(f"  RMSE = {rmse:.1f} gCO2/kWh")
print(f"  r    = {corr:.3f}")
print(f"  bias = {bias:+.1f} gCO2/kWh")

# Plot 
fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)

ax = axes[0]
neso_a.plot(ax=ax, color='darkorange', lw=1.8, label='NESO actual')
ci_a.plot(ax=ax, color='steelblue', lw=1.5, ls='--', label='Copper-plate (ours)')
ax.set_ylabel('gCO₂/kWh')
ax.set_title(f'Copper-plate vs NESO  |  MAE={mae:.1f}  RMSE={rmse:.1f}  r={corr:.3f}')
ax.legend()
ax.grid(alpha=0.3)

ax = axes[1]
residual = ci_a - neso_a
residual.plot(ax=ax, color='crimson', lw=1.2)
ax.fill_between(residual.index, 0, residual, alpha=0.2, color='crimson')
ax.axhline(0, color='black', lw=0.8, ls='--')
ax.set_ylabel('Residual (gCO₂/kWh)')
ax.set_title(f'Our model minus NESO  |  bias={bias:+.1f}')
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig('copper_plate_result.png', dpi=150, bbox_inches='tight')
print("\nSaved: copper_plate_result.png")
plt.show()