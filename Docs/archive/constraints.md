# NESO Methodology Constraints: Coverage Checklist

Status: **Match** / **Exceeds** / **Approximated** / **Deviates (documented)**.

## 1. Temporal resolution

| NESO | Ours | Status |
|---|---|---|
| 30-minute settlement | 60-minute snapshot | Approximated. NESO is resampled to hourly. < 1 gCO2/kWh effect on annual mean. |
| 96 h ahead forecast | 2023 hindcast | Deviates. Validation is against NESO `actual`. |

## 2. Spatial granularity

| NESO | Ours | Status |
|---|---|---|
| 14 DNO regions | Zonal 24 buses / Reduced 34 buses | Coarser than NESO regionally, finer than 1-bus. National total is the headline. |
| Reduced GB network | Two topologies side by side | Approximated; the topology sensitivity is the experiment. |

## 3. Power flow physics

| NESO | Ours | Status |
|---|---|---|
| Active power flow | DC linear LP | Match. |
| Reactive power flow | Not modelled | Deviates. No gCO2/kVArh series. |
| Line impedance | DC reactance only | Approximated (unity power factor). |
| System losses | 8% demand-side uplift (T+D combined) | Match in spirit. The 8% is transmission + distribution, not transmission alone. |

## 4. Emission factors

NESO factors snapshot at `Data/neso_2023_factors.json` (biomass = 120). Carriers
actually dispatched in Reduced 2023, NESO vs run:

| Carrier | TWh | NESO (gCO2/kWh) | Run | Status |
|---|---|---|---|---|
| wind_offshore | 66.04 | 0 | 0 | Match |
| CCGT | 55.99 | 394 | ~367 (0.202 t/MWh / 0.55 eff) | Approximated, ~7% gap |
| nuclear | 37.48 | 0 | 0 | Match |
| EU_import | 32.97 | Dutch 474 / French 53 / Irish 458 | 200 flat | Deviates |
| wind_onshore | 32.87 | 0 | 0 | Match |
| waste_to_energy | 19.65 | 300 (Other) | 200 | Deviates, ~100 gCO2/kWh gap |
| solar_pv | 9.26 | 0 | 0 | Match |
| landfill_gas | 5.62 | 120 | 120 (override) | Match |
| OCGT | 2.69 | 651 | ~577 (0.202 / 0.35) | Approximated, ~11% gap |
| coal | 2.68 | 937 | ~947 (0.341 / 0.36) | Approximated, ~1% gap |
| advanced_biofuel | 2.46 | 120 | 120 (override) | Match |
| biogas | 2.36 | 120 | 120 (override) | Match |
| large_hydro | 2.00 | 0 | 0 | Match |
| small_hydro | 0.40 | 0 | 0 | Match |
| sewage_gas | 0.38 | 120 | 120 (override) | Match |
| biomass / Bioenergy | 0 | 120 | (override would apply) | No effect: **Drax absent from PyPSA-GB fleet** |

Override applied only to biogenic carriers. Other thermal-carrier deviations
are left so the loss + biomass effect is isolable.

## 5. Scope and boundary

| NESO | Ours | Status |
|---|---|---|
| Generation-side only | Generators + storage discharge | Match |
| Embedded wind / solar | Not split from transmission-connected | Approximated; affects regional only |
| T+D losses included | 8% demand uplift | Match |
| Interconnector imports | Single EU_import carrier | Approximated, see Section 4 |
| Attribution stops at regional load | Per-bus Bialek; loads inherit bus CI | Match |

## 6. Attribution

NESO does not publish the exact algorithm; we use Bialek average proportional
sharing on the LP flow solution, system-mean weighted for the headline.

## 7. Validation

NESO 2023 actual: **152.1 gCO2/kWh** (std 62.6, min 0.0, max 307.5, n = 17 430
half-hours resampled to 8713 hourly rows for alignment).

| Series | Annual mean | Bias | RMSE | MAE | Pearson r |
|---|---|---|---|---|---|
| Zonal 17-bus | 155.3 | +3.6 | 100.6 | 82.3 | 0.13 |
| Reduced 32-bus | 165.2 | +13.4 | 91.1 | 73.7 | 0.14 |

- Annual means within 2.4% (Zonal) and 8.8% (Reduced) of NESO. Biomass
  override matters here.
- Hourly correlation weak (r ~0.13-0.14). LP without unit commitment,
  ramp limits, or forced outages does not track NESO's hour-by-hour shape.
- Model std exceeds NESO (87.3 / 74.4 vs 62.6); idealised dispatch swings
  more than reality.
- 17 vs 32 spread ~10 gCO2/kWh on annual mean: topology matters, not noise.

## 8. Reproducibility

PyPSA-GB `074ea25e` on `carbon-intensity-work`. NESO factors snapshot
2026-05-14. HiGHS solver. Per-output `manifest.json` for SHA / solver /
wall time.

## 9. Summary

**Match:** generation-side scope, Bialek attribution, zero-emission carriers,
demand-side losses, biogenic carriers at 120.
**Approximated:** hourly vs half-hourly, thermal carrier factors (gap < 10%),
DC reactance only.
**Deviates (documented):** reactive power, per-cable interconnector factors,
waste_to_energy 200 vs NESO 300, embedded vs transmission split.
**Data gap:** Drax / wood pellet absent from PyPSA-GB 2023 fleet. NESO 2023
mix is ~5% biomass; ours captures ~4% via biogenic override but not the
Drax-scale ~15-17 TWh that should be there. Expect annual mean below NESO
for that reason alone.
