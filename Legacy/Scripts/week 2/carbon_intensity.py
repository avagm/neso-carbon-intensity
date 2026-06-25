"""Nodal carbon intensity from a solved PyPSA-GB network.

Writes generation_intensity.csv, consumption_intensity.csv (Bialek),
and system_summary.csv. `--neso-overrides` applies the NESO biomass
factor (120 gCO2/kWh electrical) to biogenic carriers.

    python carbon_intensity.py --network solved.nc --out-dir results/ --neso-overrides
"""
from __future__ import annotations

import argparse
import logging
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa


logger = logging.getLogger(__name__)

T_PER_MWH_TO_G_PER_KWH = 1000.0

# NESO /intensity/factors: single Biomass = 120 gCO2/kWh covers all
# biogenic combustion. PyPSA-GB's 2023 fleet has zero generators on the
# formal biomass/Bioenergy carriers; biogenic dispatch sits under the
# other keys below. Override bypasses the thermal-to-electrical conversion.
NESO_FACTORS_G_PER_KWH = {
    "biomass":          120.0,
    "Biomass":          120.0,
    "Bioenergy":        120.0,
    "biogas":           120.0,
    "landfill_gas":     120.0,
    "sewage_gas":       120.0,
    "advanced_biofuel": 120.0,
}


def _t_per_mwh_e_from_g_per_kwh(g_per_kwh: float) -> float:
    return g_per_kwh / T_PER_MWH_TO_G_PER_KWH


@dataclass
class CarbonIntensityResult:
    generation_intensity: pd.DataFrame   # snapshots x buses, gCO2/kWh
    consumption_intensity: pd.DataFrame  # snapshots x buses, gCO2/kWh
    bus_emissions_t: pd.DataFrame
    bus_generation_mwh: pd.DataFrame
    bus_gross_input_mwh: pd.DataFrame

    def system_intensity(self) -> pd.Series:
        em = self.bus_emissions_t.sum(axis=1)
        gen = self.bus_generation_mwh.sum(axis=1)
        out = (em / gen.replace(0, np.nan)) * T_PER_MWH_TO_G_PER_KWH
        out.name = "system_gCO2_per_kWh"
        return out


def _generator_emissions_t_per_mwh_e(
    n: pypsa.Network,
    overrides_g_per_kwh: dict[str, float] | None = None,
) -> pd.Series:
    """Per-generator EF in tCO2/MWh electrical. Overrides bypass efficiency."""
    carrier_co2 = (n.carriers.co2_emissions if "co2_emissions" in n.carriers.columns
                   else pd.Series(0.0, index=n.carriers.index))
    co2_thermal = n.generators.carrier.map(carrier_co2).fillna(0.0)

    missing = n.generators.index[~n.generators.carrier.isin(n.carriers.index)]
    if len(missing):
        logger.warning("%d generators with unknown carrier (treated as zero): %s",
                       len(missing), sorted(set(n.generators.loc[missing, "carrier"])))

    eff = n.generators.efficiency.replace(0.0, 1.0)
    ef_e = co2_thermal / eff

    if overrides_g_per_kwh:
        for carrier, g in overrides_g_per_kwh.items():
            mask = n.generators.carrier == carrier
            if mask.any():
                ef_e.loc[mask] = _t_per_mwh_e_from_g_per_kwh(g)
                logger.info("override: %s, %d gens, %.0f gCO2/kWh",
                            carrier, int(mask.sum()), g)
    return ef_e


def _local_generation_and_emissions(
    n: pypsa.Network,
    overrides_g_per_kwh: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    snapshots = n.snapshots
    buses = n.buses.index
    weights = n.snapshot_weightings.objective.reindex(snapshots).fillna(1.0)

    gen_mwh = pd.DataFrame(0.0, index=snapshots, columns=buses)
    em_t = pd.DataFrame(0.0, index=snapshots, columns=buses)

    if not n.generators.empty and not n.generators_t.p.empty:
        ef = _generator_emissions_t_per_mwh_e(n, overrides_g_per_kwh)
        p_mwh = n.generators_t.p.reindex(columns=n.generators.index).fillna(0.0) \
                                 .multiply(weights, axis=0)
        gen_by_bus = p_mwh.T.groupby(n.generators.bus).sum().T
        gen_mwh = gen_mwh.add(gen_by_bus.reindex(columns=buses, fill_value=0.0),
                              fill_value=0.0)
        em_by_bus = p_mwh.multiply(ef, axis=1).T.groupby(n.generators.bus).sum().T
        em_t = em_t.add(em_by_bus.reindex(columns=buses, fill_value=0.0),
                        fill_value=0.0)

    if not n.storage_units.empty and not n.storage_units_t.p.empty:
        ps = n.storage_units_t.p.reindex(columns=n.storage_units.index).fillna(0.0)
        discharge = ps.clip(lower=0.0).multiply(weights, axis=0)
        d_by_bus = discharge.T.groupby(n.storage_units.bus).sum().T
        gen_mwh = gen_mwh.add(d_by_bus.reindex(columns=buses, fill_value=0.0),
                              fill_value=0.0)
        ef_s = n.storage_units.carrier.map(
            n.carriers.co2_emissions if "co2_emissions" in n.carriers.columns
            else pd.Series(0.0, index=n.carriers.index)
        ).fillna(0.0)
        em_s_by_bus = discharge.multiply(ef_s, axis=1).T.groupby(n.storage_units.bus).sum().T
        em_t = em_t.add(em_s_by_bus.reindex(columns=buses, fill_value=0.0),
                        fill_value=0.0)

    return gen_mwh, em_t


def _flow_matrices(n: pypsa.Network):
    """F[k, i] = MWh from bus k into bus i per snapshot (negatives flipped)."""
    buses = list(n.buses.index)
    bus_idx = {b: i for i, b in enumerate(buses)}
    snapshots = n.snapshots
    weights = n.snapshot_weightings.objective.reindex(snapshots).fillna(1.0)

    F_by_t = {t: np.zeros((len(buses), len(buses))) for t in snapshots}

    def _accumulate(components: pd.DataFrame, flows_p0: pd.DataFrame) -> None:
        if components.empty or flows_p0.empty:
            return
        common = flows_p0.columns.intersection(components.index)
        if len(common) == 0:
            return
        bus0 = components.loc[common, "bus0"].map(bus_idx)
        bus1 = components.loc[common, "bus1"].map(bus_idx)
        valid = bus0.notna() & bus1.notna()
        if not valid.any():
            return
        common = common[valid.values]
        bus0 = bus0[valid].astype(int).to_numpy()
        bus1 = bus1[valid].astype(int).to_numpy()
        sub = flows_p0[common].multiply(weights, axis=0)
        for t in snapshots:
            row = sub.loc[t].to_numpy()
            np.add.at(F_by_t[t], (bus0, bus1), np.maximum(row, 0.0))
            np.add.at(F_by_t[t], (bus1, bus0), np.maximum(-row, 0.0))

    if not n.lines.empty:
        _accumulate(n.lines, n.lines_t.p0 if not n.lines_t.p0.empty else pd.DataFrame())
    if not n.links.empty:
        _accumulate(n.links, n.links_t.p0 if not n.links_t.p0.empty else pd.DataFrame())

    return F_by_t, buses


def _consumption_intensity(em_t: pd.DataFrame, gen_mwh: pd.DataFrame,
                           flows, buses: list[str]):
    """Bialek average proportional sharing: (diag(P_in) - F^T) x = em."""
    snapshots = em_t.index
    n_buses = len(buses)
    ci_array = np.zeros((len(snapshots), n_buses))
    pin_array = np.zeros((len(snapshots), n_buses))
    em_array  = em_t.reindex(columns=buses).fillna(0.0).to_numpy()
    gen_array = gen_mwh.reindex(columns=buses).fillna(0.0).to_numpy()

    for ti, t in enumerate(snapshots):
        F = flows.get(t, np.zeros((n_buses, n_buses)))
        P_in = gen_array[ti] + F.sum(axis=0)
        pin_array[ti] = P_in
        A = np.diag(P_in) - F.T
        b = em_array[ti]
        active = P_in > 1e-9
        if not active.any():
            ci_array[ti, :] = np.nan
            continue
        x = np.zeros(n_buses)
        try:
            x[active] = np.linalg.solve(A[np.ix_(active, active)], b[active])
        except np.linalg.LinAlgError:
            warnings.warn(f"Bialek singular at {t}; using generation intensity.")
            with np.errstate(divide="ignore", invalid="ignore"):
                gen_int = np.where(gen_array[ti] > 0, em_array[ti] / gen_array[ti], 0.0)
            x[active] = gen_int[active] * P_in[active]
        with np.errstate(divide="ignore", invalid="ignore"):
            ci_array[ti] = np.where(P_in > 1e-9, x / P_in, np.nan) * T_PER_MWH_TO_G_PER_KWH

    return (pd.DataFrame(ci_array, index=snapshots, columns=buses),
            pd.DataFrame(pin_array, index=snapshots, columns=buses))


def compute_carbon_intensity(
    n: pypsa.Network,
    electrical_overrides_g_per_kwh: dict[str, float] | None = None,
) -> CarbonIntensityResult:
    gen_mwh, em_t = _local_generation_and_emissions(n, electrical_overrides_g_per_kwh)
    with np.errstate(divide="ignore", invalid="ignore"):
        gen_intensity = (em_t.divide(gen_mwh.replace(0.0, np.nan))
                         * T_PER_MWH_TO_G_PER_KWH)
    flows, buses = _flow_matrices(n)
    cons_intensity, gross_input = _consumption_intensity(em_t, gen_mwh, flows, buses)
    return CarbonIntensityResult(
        generation_intensity=gen_intensity.reindex(columns=buses),
        consumption_intensity=cons_intensity,
        bus_emissions_t=em_t.reindex(columns=buses).fillna(0.0),
        bus_generation_mwh=gen_mwh.reindex(columns=buses).fillna(0.0),
        bus_gross_input_mwh=gross_input,
    )


def write_outputs(result: CarbonIntensityResult, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    result.generation_intensity.to_csv(out_dir / "generation_intensity.csv")
    result.consumption_intensity.to_csv(out_dir / "consumption_intensity.csv")
    summary = pd.DataFrame({
        "system_emissions_t":   result.bus_emissions_t.sum(axis=1),
        "system_generation_mwh": result.bus_generation_mwh.sum(axis=1),
        "system_gCO2_per_kWh":   result.system_intensity(),
    })
    summary.to_csv(out_dir / "system_summary.csv")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--neso-overrides", action="store_true",
                   help="Apply NESO biomass=120 gCO2/kWh to biogenic carriers.")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper()),
                        format="%(asctime)s %(levelname)s %(message)s")

    n = pypsa.Network(str(args.network))
    logger.info("loaded %s: %d buses, %d snapshots, %d gens",
                args.network, len(n.buses), len(n.snapshots), len(n.generators))

    overrides = NESO_FACTORS_G_PER_KWH if args.neso_overrides else None
    result = compute_carbon_intensity(n, electrical_overrides_g_per_kwh=overrides)
    write_outputs(result, args.out_dir)

    s = result.system_intensity()
    logger.info("system intensity: mean=%.1f, min=%.1f, max=%.1f gCO2/kWh",
                s.mean(), s.min(), s.max())
    logger.info("outputs -> %s", args.out_dir)


if __name__ == "__main__":
    main()
