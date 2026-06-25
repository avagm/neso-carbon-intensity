"""
Per-bus carbon intensity for a solved PyPSA-GB network.

Companion to system_carbon_intensity.py. Same NESO emission factor table
(neso_factors.py), so the system total implied by the per-bus values here
agrees with the system-wide series. Adds the per-bus decomposition that the
system-wide post-processor omits, which is the quantity needed for a
geographical map.

Two views are produced per bus per snapshot, both in gCO2 per kWh.

Generation view
    Local emissions divided by local generation at the bus. The carbon
    intensity of what is being produced there. Coal and gas hubs are high;
    pure-renewable buses are zero.

Consumption view (Bialek average proportional sharing)
    Treat each bus as a perfectly mixed node. The intensity of the power
    leaving the bus equals the weighted average of the intensities of the
    power entering it, with weights given by the input flows. Per snapshot,
    let P_in be the gross input at each bus (local generation plus the sum
    of positive line and link inflows) and F[k, i] be the energy flowing
    from bus k into bus i. The bus intensities satisfy

        (diag(P_in) - F^T) ci = E_local

    Solving this gives a per-bus consumption intensity comparable in
    spirit to NESO's regional intensity, smoothed across the map by the
    flow pattern.

Interconnectors are part of the modelled topology. PyPSA-GB places each
EU_import generator on an external bus tagged with a country
(Netherlands, France, Belgium, Ireland, Norway, Denmark); the NESO
per-country factor sets the emission factor for that generator and therefore
the intensity of the bus it sits on. Imports propagate into GB via the DC link
from the external bus, and the GB end picks the imported intensity up through
the Bialek decomposition.

Storage discharge is local generation with a zero emission factor, in line with
NESO's published convention.

Scale note
----------
The Bialek step builds one dense (n_buses x n_buses) flow matrix per snapshot.
That is comfortable on the Zonal 17-bus and Reduced 32-bus networks (tens of
buses) but grows with the square of the bus count: at the full ETYS scale
(approximately 2000 buses x 8760 snapshots) the per-snapshot matrices reach
hundreds of GB and a sparse rewrite is needed. The system-wide
system_carbon_intensity.py has no such matrix and runs at any bus count.

CLI
---
    python nodal_carbon_intensity.py \
        --network path/to/Historical_2023_zonal_year_solved.nc \
        --out-dir out/zonal_17bus \
        --label "Zonal 17-bus"

Writes into the output directory:
    generation_intensity.csv      hourly per-bus generation-view intensity
    consumption_intensity.csv     hourly per-bus consumption-view intensity
    annual_mean_by_bus.csv        small per-bus table, both views, plus the
                                  totals used as the generation-weighted
                                  denominators
    nodal_manifest.json           inputs, factor tables, headline numbers
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

from neso_factors import (
    NESO_CARRIER_FACTORS,
    NESO_INTERCONNECTOR_FACTORS,
    T_PER_MWH_TO_G_PER_KWH,
    generator_emission_factors,
)


logger = logging.getLogger("nodal_carbon_intensity")


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _snapshot_weights(n: pypsa.Network) -> pd.Series:
    return n.snapshot_weightings["objective"].reindex(n.snapshots).fillna(1.0)


def local_generation_and_emissions(
    n: pypsa.Network,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Per-bus, per-snapshot local generation (MWh) and emissions (tCO2).

    Sources counted as local generation: positive generator dispatch, and
    positive storage discharge. Storage discharge carries a zero emission
    factor, matching the NESO convention.
    """
    snapshots = n.snapshots
    buses = n.buses.index
    weights = _snapshot_weights(n)

    gen_mwh = pd.DataFrame(0.0, index=snapshots, columns=buses)
    em_t = pd.DataFrame(0.0, index=snapshots, columns=buses)

    factors, diagnostics = generator_emission_factors(n)

    if not n.generators.empty and not n.generators_t.p.empty:
        p = n.generators_t.p.reindex(columns=n.generators.index).fillna(0.0)
        # Clip at zero so an interconnector exporting in a given hour
        # contributes neither generation nor emissions.
        p = p.clip(lower=0.0)
        p_mwh = p.multiply(weights, axis=0)
        gen_by_bus = p_mwh.T.groupby(n.generators.bus).sum().T
        gen_mwh = gen_mwh.add(gen_by_bus.reindex(columns=buses,
                                                  fill_value=0.0),
                              fill_value=0.0)
        em_per_gen = p_mwh.multiply(factors / T_PER_MWH_TO_G_PER_KWH, axis=1)
        em_by_bus = em_per_gen.T.groupby(n.generators.bus).sum().T
        em_t = em_t.add(em_by_bus.reindex(columns=buses, fill_value=0.0),
                        fill_value=0.0)

    if not n.storage_units.empty and not n.storage_units_t.p.empty:
        ps = n.storage_units_t.p.reindex(
            columns=n.storage_units.index).fillna(0.0)
        discharge = ps.clip(lower=0.0).multiply(weights, axis=0)
        d_by_bus = discharge.T.groupby(n.storage_units.bus).sum().T
        gen_mwh = gen_mwh.add(d_by_bus.reindex(columns=buses,
                                                fill_value=0.0),
                              fill_value=0.0)
        # Zero-emission discharge; no contribution to em_t.

    return gen_mwh, em_t, diagnostics


def flow_matrices(
    n: pypsa.Network,
) -> tuple[dict[pd.Timestamp, np.ndarray], list[str]]:
    """
    Per-snapshot directed flow matrix F where F[k, i] is the MWh flowing
    from bus k into bus i. Negative raw flows on a (bus0, bus1) edge are
    flipped to positive flows on the reverse edge. Diagonal is zero.

    Returns (flows_by_snapshot, bus_order). Bus order is `n.buses.index`.
    """
    buses = list(n.buses.index)
    bus_idx = {b: i for i, b in enumerate(buses)}
    snapshots = n.snapshots
    weights = _snapshot_weights(n)

    F_by_t: dict[pd.Timestamp, np.ndarray] = {
        t: np.zeros((len(buses), len(buses))) for t in snapshots
    }

    def _accumulate(df_components: pd.DataFrame,
                    flows_p0: pd.DataFrame) -> None:
        if df_components.empty or flows_p0.empty:
            return
        common = flows_p0.columns.intersection(df_components.index)
        if len(common) == 0:
            return
        bus0 = df_components.loc[common, "bus0"].map(bus_idx)
        bus1 = df_components.loc[common, "bus1"].map(bus_idx)
        valid = bus0.notna() & bus1.notna()
        if not valid.any():
            return
        common = common[valid.values]
        bus0 = bus0[valid].astype(int).to_numpy()
        bus1 = bus1[valid].astype(int).to_numpy()

        sub = flows_p0[common].multiply(weights, axis=0)
        for t in snapshots:
            row = sub.loc[t].to_numpy()
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


def consumption_intensity(
    em_t: pd.DataFrame,
    gen_mwh: pd.DataFrame,
    flows: dict[pd.Timestamp, np.ndarray],
    buses: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Solve the Bialek system per snapshot.

    At bus i the carbon intensity of the energy leaving the bus equals
    that of the energy entering it (perfect mixing). Energy entering bus
    i in a given snapshot is local generation plus the sum of positive
    inflows from neighbours. Letting ci be the per-bus intensity in
    tCO2 / MWh, the balance at each bus reads

        ci[i] * P_in[i] = local_em[i] + sum_k F[k, i] * ci[k]

    with P_in[i] = local_gen[i] + sum_k F[k, i] and F[k, i] in MWh.
    Rearranging to all buses,

        (diag(P_in) - F^T) ci = local_em

    Solving this linear system per snapshot gives ci directly in
    tCO2 / MWh. Multiplying by 1000 converts to gCO2 / kWh, which is the
    unit the returned DataFrame carries.

    Dimensional check. diag(P_in) ci has units MWh * tCO2/MWh = tCO2.
    F^T ci has units MWh * tCO2/MWh = tCO2. local_em is in tCO2. So ci
    is tCO2 / MWh straight from the solver; no extra division by P_in
    is needed.

    Returns (consumption_intensity_g_per_kwh, gross_input_mwh)
    DataFrames indexed by snapshot, columns by bus. Buses with no
    energy entering them at a snapshot get NaN there.
    """
    snapshots = em_t.index
    n_buses = len(buses)

    ci_array = np.full((len(snapshots), n_buses), np.nan)
    pin_array = np.zeros((len(snapshots), n_buses))

    em_array = em_t.reindex(columns=buses).fillna(0.0).to_numpy()
    gen_array = gen_mwh.reindex(columns=buses).fillna(0.0).to_numpy()

    for ti, t in enumerate(snapshots):
        F = flows.get(t, np.zeros((n_buses, n_buses)))
        inflow_per_bus = F.sum(axis=0)
        P_in = gen_array[ti] + inflow_per_bus
        pin_array[ti] = P_in

        active = P_in > 1e-9
        if not active.any():
            continue

        A = np.diag(P_in) - F.T
        b = em_array[ti]

        try:
            ci_active = np.linalg.solve(A[np.ix_(active, active)],
                                        b[active])
        except np.linalg.LinAlgError:
            warnings.warn(
                f"Bialek system singular at snapshot {t}; falling back "
                "to generation-view intensity for this step.")
            with np.errstate(divide="ignore", invalid="ignore"):
                gen_int = np.where(gen_array[ti] > 0,
                                   em_array[ti] / gen_array[ti], 0.0)
            ci_active = gen_int[active]

        ci_array[ti, active] = ci_active * T_PER_MWH_TO_G_PER_KWH

    consumption = pd.DataFrame(ci_array, index=snapshots, columns=buses)
    pin = pd.DataFrame(pin_array, index=snapshots, columns=buses)
    consumption.index.name = "snapshot"
    pin.index.name = "snapshot"
    return consumption, pin


def annual_mean_by_bus(
    n: pypsa.Network,
    gen_mwh: pd.DataFrame,
    em_t: pd.DataFrame,
    cons_intensity: pd.DataFrame,
    gross_input_mwh: pd.DataFrame,
) -> pd.DataFrame:
    """
    Per-bus annual generation-weighted means for both views.

    Generation view weight is local generation MWh; consumption view weight
    is the Bialek gross input MWh. Both are reported with the totals used
    as the denominator so downstream tooling can reweight.
    """
    buses = list(n.buses.index)
    total_gen = gen_mwh.sum(axis=0).reindex(buses).fillna(0.0)
    total_em = em_t.sum(axis=0).reindex(buses).fillna(0.0)
    total_pin = gross_input_mwh.sum(axis=0).reindex(buses).fillna(0.0)

    with np.errstate(divide="ignore", invalid="ignore"):
        gen_view = np.where(total_gen > 0,
                            total_em / total_gen * T_PER_MWH_TO_G_PER_KWH,
                            np.nan)

    # For the consumption view, the throughput-weighted mean is
    # sum_t(ci_t * P_in_t) / sum_t(P_in_t). Mask out snapshots where
    # P_in == 0 or ci is NaN (those carry no throughput anyway).
    pin = gross_input_mwh.reindex(columns=buses).fillna(0.0)
    ci = cons_intensity.reindex(columns=buses)
    weighted = (ci * pin).sum(axis=0, min_count=1)
    total_pin_safe = pin.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        cons_view = np.where(total_pin_safe > 0,
                             weighted / total_pin_safe,
                             np.nan)

    out = pd.DataFrame({
        "bus": buses,
        "v_nom_kv": n.buses["v_nom"].reindex(buses).astype(float).to_numpy(),
        "carrier": n.buses["carrier"].reindex(buses).astype(str).to_numpy(),
        "country": (n.buses["country"].reindex(buses).astype(str).to_numpy()
                    if "country" in n.buses.columns
                    else np.array([""] * len(buses))),
        "total_generation_mwh": total_gen.to_numpy().round(3),
        "total_emissions_t": total_em.to_numpy().round(3),
        "gen_view_gCO2_per_kWh": np.round(gen_view, 3),
        "total_gross_input_mwh": total_pin.to_numpy().round(3),
        "cons_view_gCO2_per_kWh": np.round(cons_view, 3),
    })
    return out


def write_outputs(
    out_dir: Path,
    label: str,
    network_path: Path,
    n: pypsa.Network,
    gen_intensity: pd.DataFrame,
    cons_intensity: pd.DataFrame,
    annual: pd.DataFrame,
    diagnostics: dict,
    pypsa_gb_commit: str | None,
    gen_mwh: pd.DataFrame,
    em_t: pd.DataFrame,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    gen_intensity.to_csv(out_dir / "generation_intensity.csv")
    cons_intensity.to_csv(out_dir / "consumption_intensity.csv")
    annual.to_csv(out_dir / "annual_mean_by_bus.csv", index=False)

    # System-level totals so the manifest carries the consistency check
    # against system_carbon_intensity.py output.
    total_gen_mwh = float(gen_mwh.sum().sum())
    total_em_t = float(em_t.sum().sum())
    sys_mean = (total_em_t / total_gen_mwh * T_PER_MWH_TO_G_PER_KWH
                if total_gen_mwh > 0 else None)

    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "nodal_carbon_intensity.py",
        "label": label,
        "network_path": str(network_path),
        "network_basename": network_path.name,
        "network_sha256": file_sha256(network_path),
        "pypsa_gb_commit": pypsa_gb_commit,
        "n_buses": int(len(n.buses)),
        "n_generators": int(len(n.generators)),
        "n_storage_units": int(len(n.storage_units)),
        "n_snapshots": int(len(n.snapshots)),
        "snapshot_first": str(n.snapshots[0]),
        "snapshot_last": str(n.snapshots[-1]),
        "neso_carrier_factors_gCO2_per_kWh": NESO_CARRIER_FACTORS,
        "neso_interconnector_factors_gCO2_per_kWh": NESO_INTERCONNECTOR_FACTORS,
        "unmatched": diagnostics,
        "system_check": {
            "annual_generation_weighted_gCO2_per_kWh":
                round(sys_mean, 3) if sys_mean is not None else None,
            "total_generation_twh": round(total_gen_mwh / 1e6, 4),
            "total_emissions_Mt": round(total_em_t / 1e6, 4),
            "note": ("Reproduces the system-wide value system_carbon_intensity.py"
                     " writes; agreement to within rounding is the cross-check."),
        },
        "per_bus_extrema": {
            "gen_view_max_gCO2_per_kWh": (
                None if annual["gen_view_gCO2_per_kWh"].isna().all()
                else round(float(annual["gen_view_gCO2_per_kWh"].max()), 3)),
            "gen_view_argmax_bus": (
                None if annual["gen_view_gCO2_per_kWh"].isna().all()
                else str(annual.loc[
                    annual["gen_view_gCO2_per_kWh"].idxmax(), "bus"])),
            "cons_view_max_gCO2_per_kWh": (
                None if annual["cons_view_gCO2_per_kWh"].isna().all()
                else round(float(annual["cons_view_gCO2_per_kWh"].max()), 3)),
            "cons_view_argmax_bus": (
                None if annual["cons_view_gCO2_per_kWh"].isna().all()
                else str(annual.loc[
                    annual["cons_view_gCO2_per_kWh"].idxmax(), "bus"])),
            "cons_view_min_gCO2_per_kWh": (
                None if annual["cons_view_gCO2_per_kWh"].isna().all()
                else round(float(annual["cons_view_gCO2_per_kWh"].min()), 3)),
            "cons_view_argmin_bus": (
                None if annual["cons_view_gCO2_per_kWh"].isna().all()
                else str(annual.loc[
                    annual["cons_view_gCO2_per_kWh"].idxmin(), "bus"])),
        },
        "software": {
            "pypsa": pypsa.__version__,
            "python": sys.version.split()[0],
        },
    }
    # Write under a distinct filename so the per-bus run does not clobber
    # the system-wide manifest.json that system_carbon_intensity.py writes
    # in the same output directory.
    (out_dir / "nodal_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Per-bus carbon intensity (generation view and Bialek "
                    "consumption view) for a solved PyPSA-GB network. See "
                    "module docstring.")
    p.add_argument("--network", required=True, type=Path,
                   help="Path to a solved PyPSA-GB NetCDF network.")
    p.add_argument("--out-dir", required=True, type=Path,
                   help="Directory for the CSV and manifest outputs.")
    p.add_argument("--label", required=True,
                   help="Human-readable label, e.g. 'Zonal 17-bus'.")
    p.add_argument("--pypsa-gb-commit", default=None,
                   help="PyPSA-GB clone commit SHA, recorded in the manifest.")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not args.network.exists():
        sys.exit(f"network not found: {args.network}")

    logger.info("loading %s", args.network)
    n = pypsa.Network(str(args.network))
    logger.info("%d buses, %d generators, %d snapshots",
                len(n.buses), len(n.generators), len(n.snapshots))

    gen_mwh, em_t, diagnostics = local_generation_and_emissions(n)

    # Generation view: local emissions per local generation.
    with np.errstate(divide="ignore", invalid="ignore"):
        gen_intensity = (em_t.divide(gen_mwh.replace(0.0, np.nan))
                         * T_PER_MWH_TO_G_PER_KWH)
    gen_intensity.index.name = "snapshot"

    logger.info("building per-snapshot flow matrices")
    flows, buses = flow_matrices(n)
    logger.info("solving Bialek system across %d snapshots", len(n.snapshots))
    cons_intensity, gross_input = consumption_intensity(em_t, gen_mwh,
                                                         flows, buses)

    annual = annual_mean_by_bus(n, gen_mwh, em_t, cons_intensity, gross_input)

    manifest = write_outputs(args.out_dir, args.label, args.network, n,
                              gen_intensity, cons_intensity, annual,
                              diagnostics, args.pypsa_gb_commit,
                              gen_mwh, em_t)

    sc = manifest["system_check"]
    ext = manifest["per_bus_extrema"]
    logger.info("%s: system mean %.1f gCO2/kWh (%.1f TWh, %.2f Mt CO2)",
                args.label,
                sc["annual_generation_weighted_gCO2_per_kWh"],
                sc["total_generation_twh"], sc["total_emissions_Mt"])
    logger.info("consumption view range: %.1f (%s) to %.1f (%s) gCO2/kWh",
                ext["cons_view_min_gCO2_per_kWh"], ext["cons_view_argmin_bus"],
                ext["cons_view_max_gCO2_per_kWh"], ext["cons_view_argmax_bus"])
    logger.info("outputs written to %s", args.out_dir)


if __name__ == "__main__":
    main()
