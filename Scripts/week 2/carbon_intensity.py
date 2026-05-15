"""
Nodal carbon intensity for a solved PyPSA-GB network.

Two per-bus, per-snapshot intensities are produced:

  generation_intensity[t, i]
      Local emissions divided by local generation at bus i. Production view.

  consumption_intensity[t, i]
      Bialek average proportional sharing applied to the LP flow solution.
      Consumption view, comparable in spirit to NESO's regional intensity.

Both are returned in gCO2 per kWh.

The module is a pure post-processor. It reads only what is in the solved
network and never modifies it.

CLI
---
    python carbon_intensity.py --network path/to/solved.nc --out-dir results/

Writes:
    results/generation_intensity.csv
    results/consumption_intensity.csv
    results/system_summary.csv
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

T_PER_MWH_TO_G_PER_KWH = 1000.0  # 1 tCO2 / 1 MWh == 1000 gCO2 / kWh


# Per-carrier electrical emission factors from NESO's /intensity/factors
# endpoint (gCO2/kWh of electricity sent out). These bypass the
# co2_emissions / efficiency computation when supplied.
#
# Snapshot taken from reference.md section 1.6. Re-fetch before quoting.
# Keys cover both lower-case and capitalised PyPSA-GB carrier names, and
# the additional biogenic carriers that PyPSA-GB splits out (NESO reports
# a single "Biomass" figure of 120 covering all biogenic combustion).
#
# Drax (wood pellet) appears to be ABSENT from the PyPSA-GB 2023
# historical fleet — no generators carry the `biomass`/`Bioenergy`
# carriers in either the Zonal or Reduced topology. The override
# therefore changes nothing for those carriers; flagged in the
# constraints document for follow-up.
NESO_FACTORS_G_PER_KWH = {
    # Biomass per se
    "biomass":          120.0,
    "Biomass":          120.0,
    "Bioenergy":        120.0,
    # Other biogenic carriers (NESO groups all under "Biomass" 120)
    "biogas":           120.0,
    "landfill_gas":     120.0,
    "sewage_gas":       120.0,
    "advanced_biofuel": 120.0,
}


def _t_per_mwh_e_from_g_per_kwh(g_per_kwh: float) -> float:
    """Convert gCO2/kWh (electrical) to tCO2/MWh (electrical)."""
    return g_per_kwh / T_PER_MWH_TO_G_PER_KWH


@dataclass
class CarbonIntensityResult:
    """Container for nodal carbon intensity outputs."""

    generation_intensity: pd.DataFrame   # snapshots x buses, gCO2/kWh
    consumption_intensity: pd.DataFrame  # snapshots x buses, gCO2/kWh
    bus_emissions_t: pd.DataFrame        # snapshots x buses, tCO2 (local)
    bus_generation_mwh: pd.DataFrame     # snapshots x buses, MWh (local gen)
    bus_gross_input_mwh: pd.DataFrame    # snapshots x buses, MWh (incl. inflows)

    def system_intensity(self) -> pd.Series:
        """System-wide intensity per snapshot, weighted by load."""
        # System total emissions divided by system total generation in each
        # snapshot, expressed in gCO2/kWh.
        em = self.bus_emissions_t.sum(axis=1)
        gen = self.bus_generation_mwh.sum(axis=1)
        out = (em / gen.replace(0, np.nan)) * T_PER_MWH_TO_G_PER_KWH
        out.name = "system_gCO2_per_kWh"
        return out


def _generator_emissions_t_per_mwh_e(
    n: pypsa.Network,
    electrical_overrides_g_per_kwh: dict[str, float] | None = None,
) -> pd.Series:
    """
    Per-generator electrical emission factor in tCO2 per MWh electrical.

    Default: carrier `co2_emissions` (tCO2 per MWh thermal) divided by
    generator efficiency.

    Override: if a carrier key appears in `electrical_overrides_g_per_kwh`
    (gCO2/kWh of electricity sent out), every generator on that carrier
    takes the override value, converted to tCO2/MWh_e. The override
    bypasses the thermal-to-electrical efficiency conversion because
    NESO factors are already at the system boundary.

    Generators with carriers missing from `n.carriers` get a zero factor
    and a logged warning.
    """
    carrier_co2 = n.carriers.co2_emissions if "co2_emissions" in n.carriers.columns \
        else pd.Series(0.0, index=n.carriers.index)

    co2_thermal = n.generators.carrier.map(carrier_co2).fillna(0.0)
    missing = n.generators.index[~n.generators.carrier.isin(n.carriers.index)]
    if len(missing):
        logger.warning(
            "%d generators have a carrier not in n.carriers; treated as zero "
            "emissions: %s",
            len(missing), sorted(set(n.generators.loc[missing, "carrier"]))
        )

    eff = n.generators.efficiency.replace(0.0, 1.0)
    ef_e = co2_thermal / eff

    if electrical_overrides_g_per_kwh:
        for carrier_name, g_per_kwh in electrical_overrides_g_per_kwh.items():
            mask = n.generators.carrier == carrier_name
            if mask.any():
                ef_e.loc[mask] = _t_per_mwh_e_from_g_per_kwh(g_per_kwh)
                logger.info(
                    "override applied: carrier=%s, %d generators, "
                    "EF=%.0f gCO2/kWh electrical (NESO)",
                    carrier_name, int(mask.sum()), g_per_kwh,
                )

    return ef_e


def _local_generation_and_emissions(
    n: pypsa.Network,
    electrical_overrides_g_per_kwh: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Per-bus, per-snapshot local generation (MWh) and emissions (tCO2).

    Includes generators and storage discharge. Storage charge and loads are
    handled separately when computing flows.
    """
    snapshots = n.snapshots
    buses = n.buses.index
    weights = n.snapshot_weightings.objective.reindex(snapshots).fillna(1.0)

    gen_mwh = pd.DataFrame(0.0, index=snapshots, columns=buses)
    em_t = pd.DataFrame(0.0, index=snapshots, columns=buses)

    if not n.generators.empty and not n.generators_t.p.empty:
        ef = _generator_emissions_t_per_mwh_e(
            n, electrical_overrides_g_per_kwh
        )  # tCO2 per MWh_e per gen
        p = n.generators_t.p.reindex(columns=n.generators.index).fillna(0.0)
        p_mwh = p.multiply(weights, axis=0)
        gen_by_bus = p_mwh.T.groupby(n.generators.bus).sum().T
        gen_mwh = gen_mwh.add(gen_by_bus.reindex(columns=buses, fill_value=0.0),
                              fill_value=0.0)

        em_per_gen = p_mwh.multiply(ef, axis=1)  # tCO2
        em_by_bus = em_per_gen.T.groupby(n.generators.bus).sum().T
        em_t = em_t.add(em_by_bus.reindex(columns=buses, fill_value=0.0),
                        fill_value=0.0)

    # Storage discharge (positive p) counts as generation. Carrier emission
    # factors for storage carriers are 0 in PyPSA-GB but we keep the path
    # general in case that changes.
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
        # storage carriers have no efficiency column at the unit level for
        # discharge here, treat as 1
        em_s = discharge.multiply(ef_s, axis=1)
        em_s_by_bus = em_s.T.groupby(n.storage_units.bus).sum().T
        em_t = em_t.add(em_s_by_bus.reindex(columns=buses, fill_value=0.0),
                        fill_value=0.0)

    return gen_mwh, em_t


def _flow_matrices(n: pypsa.Network) -> tuple[dict[pd.Timestamp, np.ndarray],
                                               list[str]]:
    """
    For every snapshot, build a directed flow matrix F where F[k, i] is the
    energy (MWh) flowing from bus k into bus i at that snapshot. Negative
    raw flows are flipped (a -10 MW flow from bus0 to bus1 becomes +10 MW
    from bus1 to bus0). Diagonal is zero.

    Returns (flows_by_snapshot, bus_order).
    """
    buses = list(n.buses.index)
    bus_idx = {b: i for i, b in enumerate(buses)}
    snapshots = n.snapshots
    weights = n.snapshot_weightings.objective.reindex(snapshots).fillna(1.0)

    F_by_t: dict[pd.Timestamp, np.ndarray] = {
        t: np.zeros((len(buses), len(buses))) for t in snapshots
    }

    def _accumulate(df_components: pd.DataFrame, flows_p0: pd.DataFrame) -> None:
        if df_components.empty or flows_p0.empty:
            return
        common = flows_p0.columns.intersection(df_components.index)
        if len(common) == 0:
            return
        bus0 = df_components.loc[common, "bus0"].map(bus_idx)
        bus1 = df_components.loc[common, "bus1"].map(bus_idx)
        # Drop any whose endpoints aren't both in the bus index (foreign).
        valid = bus0.notna() & bus1.notna()
        if not valid.any():
            return
        common = common[valid.values]
        bus0 = bus0[valid].astype(int).to_numpy()
        bus1 = bus1[valid].astype(int).to_numpy()

        sub = flows_p0[common].multiply(weights, axis=0)  # MWh per snapshot
        for t in snapshots:
            row = sub.loc[t].to_numpy()
            # Positive: bus0 -> bus1. Negative: bus1 -> bus0.
            pos = np.maximum(row, 0.0)
            neg = np.maximum(-row, 0.0)
            np.add.at(F_by_t[t], (bus0, bus1), pos)
            np.add.at(F_by_t[t], (bus1, bus0), neg)

    if not n.lines.empty:
        _accumulate(n.lines, n.lines_t.p0 if not n.lines_t.p0.empty
                    else pd.DataFrame())
    if not n.links.empty:
        _accumulate(n.links, n.links_t.p0 if not n.links_t.p0.empty
                    else pd.DataFrame())

    return F_by_t, buses


def _consumption_intensity(
    bus_local_em_t: pd.DataFrame,
    bus_local_gen_mwh: pd.DataFrame,
    flows: dict[pd.Timestamp, np.ndarray],
    buses: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Solve the Bialek system for each snapshot.

    For snapshot t:
        P_in[i] = local_gen[i] + sum_k F[k, i]
        (diag(P_in) - F^T) ci = local_em
        consumption_intensity[i] = ci[i] / P_in[i]   (gCO2/kWh)

    Returns (consumption_intensity, gross_input_mwh) as DataFrames with
    snapshots as the index and buses as columns.
    """
    snapshots = bus_local_em_t.index
    n_buses = len(buses)
    bus_idx = {b: i for i, b in enumerate(buses)}

    ci_array = np.zeros((len(snapshots), n_buses))
    pin_array = np.zeros((len(snapshots), n_buses))

    em_array = bus_local_em_t.reindex(columns=buses).fillna(0.0).to_numpy()
    gen_array = bus_local_gen_mwh.reindex(columns=buses).fillna(0.0).to_numpy()

    for ti, t in enumerate(snapshots):
        F = flows.get(t, np.zeros((n_buses, n_buses)))
        inflow_per_bus = F.sum(axis=0)  # F[k, i] summed over k
        P_in = gen_array[ti] + inflow_per_bus
        pin_array[ti] = P_in

        # Solve (diag(P_in) - F^T) x = em
        # x has units of tCO2 (it is CI in tCO2/MWh times P_in MWh).
        A = np.diag(P_in) - F.T
        b = em_array[ti]

        # Buses with no power in: leave intensity as NaN.
        active = P_in > 1e-9
        if not active.any():
            ci_array[ti, :] = np.nan
            continue

        x = np.zeros(n_buses)
        try:
            x_active = np.linalg.solve(A[np.ix_(active, active)],
                                       b[active])
            x[active] = x_active
        except np.linalg.LinAlgError:
            # Singular case: fall back to generation-based intensity.
            warnings.warn(
                f"Bialek system singular at snapshot {t}; using "
                "generation-based intensity for this step.")
            with np.errstate(divide="ignore", invalid="ignore"):
                gen_int = np.where(gen_array[ti] > 0,
                                   em_array[ti] / gen_array[ti], 0.0)
            x[active] = gen_int[active] * P_in[active]

        with np.errstate(divide="ignore", invalid="ignore"):
            ci = np.where(P_in > 1e-9, x / P_in, np.nan)
        ci_array[ti] = ci * T_PER_MWH_TO_G_PER_KWH

    consumption = pd.DataFrame(ci_array, index=snapshots, columns=buses)
    pin = pd.DataFrame(pin_array, index=snapshots, columns=buses)
    return consumption, pin


def compute_carbon_intensity(
    n: pypsa.Network,
    electrical_overrides_g_per_kwh: dict[str, float] | None = None,
) -> CarbonIntensityResult:
    """
    Compute generation-based and consumption-based per-bus carbon intensity
    for every snapshot in the solved network `n`.

    Parameters
    ----------
    n : pypsa.Network
        A solved PyPSA network.
    electrical_overrides_g_per_kwh : dict[str, float], optional
        Per-carrier electrical emission factors in gCO2/kWh. Bypass the
        default thermal-to-electrical conversion for the listed carriers.
        Pass `NESO_FACTORS_G_PER_KWH` for the standard biomass = 120
        override.
    """
    gen_mwh, em_t = _local_generation_and_emissions(
        n, electrical_overrides_g_per_kwh
    )

    # Generation view.
    with np.errstate(divide="ignore", invalid="ignore"):
        gen_intensity = (em_t.divide(gen_mwh.replace(0.0, np.nan))
                         * T_PER_MWH_TO_G_PER_KWH)

    # Consumption view.
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
        "system_emissions_t": result.bus_emissions_t.sum(axis=1),
        "system_generation_mwh": result.bus_generation_mwh.sum(axis=1),
        "system_gCO2_per_kWh": result.system_intensity(),
    })
    summary.to_csv(out_dir / "system_summary.csv")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network", required=True, type=Path,
                   help="Path to a solved PyPSA NetCDF network.")
    p.add_argument("--out-dir", required=True, type=Path,
                   help="Directory for CSV outputs.")
    p.add_argument("--neso-overrides", action="store_true",
                   help="Apply NESO electrical emission factors "
                        "(biomass = 120 gCO2/kWh) on top of PyPSA-GB defaults.")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()),
                        format="%(asctime)s %(levelname)s %(message)s")

    n = pypsa.Network(str(args.network))
    logger.info("loaded %s: %d buses, %d snapshots, %d generators",
                args.network, len(n.buses), len(n.snapshots),
                len(n.generators))

    overrides = NESO_FACTORS_G_PER_KWH if args.neso_overrides else None
    result = compute_carbon_intensity(n, electrical_overrides_g_per_kwh=overrides)
    write_outputs(result, args.out_dir)

    sys = result.system_intensity()
    logger.info("system intensity: mean=%.1f gCO2/kWh, min=%.1f, max=%.1f",
                sys.mean(), sys.min(), sys.max())
    logger.info("wrote outputs to %s", args.out_dir)


if __name__ == "__main__":
    main()
