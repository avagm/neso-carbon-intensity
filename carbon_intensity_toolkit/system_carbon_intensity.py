"""
System carbon intensity for a solved PyPSA-GB network.

Takes one solved PyPSA-GB network and produces a single hourly system carbon
intensity series in gCO2 per kWh, using the NESO published emission factors
(neso_factors.py).

Only the system-wide intensity is produced here. It is the one carbon-intensity
number directly comparable between networks with different bus counts (a 17-bus
and a 32-bus network do not share a bus set). Per-bus intensities are in
nodal_carbon_intensity.py.

Method
------
For each snapshot t,

    CI[t] = system_emissions[t] / system_generation[t] * 1000      gCO2 / kWh

system_emissions is in tonnes CO2 and system_generation in MWh; the factor 1000
converts tCO2 per MWh into gCO2 per kWh. system_generation is the sum of
positive generator dispatch and positive storage discharge. Storage carries a
zero emission factor, which keeps the denominator consistent with NESO, whose
published generation mix counts pumped storage as a zero-factor entry.
Generator dispatch is clipped at zero so that an interconnector exporting in a
given hour contributes neither generation nor emissions.

CLI
---
    python system_carbon_intensity.py \
        --network path/to/Historical_2023_zonal_year_solved.nc \
        --out-dir out/zonal_17bus \
        --label "Zonal 17-bus"

Writes into the output directory:
    system_carbon_intensity.csv   hourly system emissions, generation, intensity
    generation_by_carrier.csv     annual generation and emissions per carrier
    manifest.json                 inputs, factor tables, headline numbers
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
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


logger = logging.getLogger("system_carbon_intensity")


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    """Streamed hex SHA-256 of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _snapshot_weights(n: pypsa.Network) -> pd.Series:
    """Objective snapshot weighting, one value per snapshot (hours per step)."""
    return n.snapshot_weightings["objective"].reindex(n.snapshots).fillna(1.0)


def _positive_generation_mwh(n: pypsa.Network, weights: pd.Series) -> pd.DataFrame:
    """Per-generator positive dispatch in MWh, snapshots x generators."""
    p = n.generators_t.p.reindex(columns=n.generators.index).fillna(0.0)
    return p.clip(lower=0.0).multiply(weights, axis=0)


def _storage_discharge_mwh(n: pypsa.Network, weights: pd.Series) -> pd.Series:
    """System storage discharge in MWh per snapshot (zero-emission generation)."""
    if n.storage_units.empty or n.storage_units_t.p.empty:
        return pd.Series(0.0, index=n.snapshots)
    ps = n.storage_units_t.p.reindex(columns=n.storage_units.index).fillna(0.0)
    return ps.clip(lower=0.0).multiply(weights, axis=0).sum(axis=1)


def compute_system_carbon_intensity(
    n: pypsa.Network,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, dict]:
    """
    Hourly system carbon intensity for a solved network.

    Returns
    -------
    ci_df : DataFrame indexed by snapshot, columns system_emissions_t,
        system_generation_mwh, system_gCO2_per_kWh.
    by_carrier : DataFrame indexed by carrier, annual generation and emissions,
        with a trailing storage_discharge row.
    factors : Series, the per-generator NESO factor used (gCO2 per kWh).
    diagnostics : dict of unmatched carriers and interconnector countries.
    """
    if n.generators_t.p.empty:
        raise ValueError("network has no generator dispatch; is it solved?")

    weights = _snapshot_weights(n)
    factors, diagnostics = generator_emission_factors(n)

    gen_mwh = _positive_generation_mwh(n, weights)
    # MWh * (gCO2/kWh) / 1000 = tCO2.
    emissions_t = gen_mwh.multiply(factors / T_PER_MWH_TO_G_PER_KWH, axis=1)

    system_em = emissions_t.sum(axis=1)
    discharge = _storage_discharge_mwh(n, weights)
    system_gen = gen_mwh.sum(axis=1).add(discharge, fill_value=0.0)

    with np.errstate(divide="ignore", invalid="ignore"):
        ci = np.where(system_gen > 0.0,
                      system_em / system_gen * T_PER_MWH_TO_G_PER_KWH,
                      np.nan)
    ci_df = pd.DataFrame(
        {
            "system_emissions_t": system_em,
            "system_generation_mwh": system_gen,
            "system_gCO2_per_kWh": ci,
        },
        index=n.snapshots,
    )
    ci_df.index.name = "snapshot"

    # Annual generation and emissions by carrier, with a storage row so the
    # generation column sums to the system total.
    per_gen_mwh = gen_mwh.sum(axis=0)
    per_gen_em = emissions_t.sum(axis=0)
    carrier = n.generators["carrier"].astype(str)
    by_carrier = pd.DataFrame({
        "generation_mwh": per_gen_mwh.groupby(carrier).sum(),
        "emissions_t": per_gen_em.groupby(carrier).sum(),
    })
    by_carrier.loc["storage_discharge"] = [float(discharge.sum()), 0.0]
    by_carrier["generation_twh"] = by_carrier["generation_mwh"] / 1e6
    with np.errstate(divide="ignore", invalid="ignore"):
        by_carrier["mean_factor_gCO2_per_kWh"] = np.where(
            by_carrier["generation_mwh"] > 0.0,
            by_carrier["emissions_t"] / by_carrier["generation_mwh"]
            * T_PER_MWH_TO_G_PER_KWH,
            0.0,
        )
    by_carrier = by_carrier.sort_values("generation_mwh", ascending=False)
    by_carrier.index.name = "carrier"

    return ci_df, by_carrier, factors, diagnostics


def write_outputs(
    out_dir: Path,
    label: str,
    network_path: Path,
    n: pypsa.Network,
    ci_df: pd.DataFrame,
    by_carrier: pd.DataFrame,
    diagnostics: dict,
    pypsa_gb_commit: str | None,
) -> dict:
    """Write the two CSVs and a manifest; return the manifest dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ci_df.to_csv(out_dir / "system_carbon_intensity.csv")
    by_carrier.to_csv(out_dir / "generation_by_carrier.csv")

    ci = ci_df["system_gCO2_per_kWh"]
    total_gen_mwh = float(ci_df["system_generation_mwh"].sum())
    total_em_t = float(ci_df["system_emissions_t"].sum())
    manifest = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "script": "system_carbon_intensity.py",
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
        "headline": {
            "annual_mean_hourly_gCO2_per_kWh": round(float(ci.mean()), 3),
            "annual_generation_weighted_gCO2_per_kWh": (
                round(total_em_t / total_gen_mwh * T_PER_MWH_TO_G_PER_KWH, 3)
                if total_gen_mwh > 0 else None),
            "min_gCO2_per_kWh": round(float(ci.min()), 3),
            "max_gCO2_per_kWh": round(float(ci.max()), 3),
            "total_generation_twh": round(total_gen_mwh / 1e6, 4),
            "total_emissions_Mt": round(total_em_t / 1e6, 4),
        },
        "software": {
            "pypsa": pypsa.__version__,
            "python": sys.version.split()[0],
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="System carbon intensity for a solved PyPSA-GB network "
                    "(see module docstring).",
    )
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
    logger.info("%d buses, %d generators, %d snapshots (%s .. %s)",
                len(n.buses), len(n.generators), len(n.snapshots),
                n.snapshots[0], n.snapshots[-1])

    ci_df, by_carrier, _factors, diagnostics = compute_system_carbon_intensity(n)
    manifest = write_outputs(args.out_dir, args.label, args.network, n,
                             ci_df, by_carrier, diagnostics,
                             args.pypsa_gb_commit)

    h = manifest["headline"]
    logger.info("%s: annual mean %.1f gCO2/kWh (generation-weighted %.1f), "
                "range %.0f to %.0f, generation %.1f TWh, emissions %.2f Mt",
                args.label,
                h["annual_mean_hourly_gCO2_per_kWh"],
                h["annual_generation_weighted_gCO2_per_kWh"],
                h["min_gCO2_per_kWh"], h["max_gCO2_per_kWh"],
                h["total_generation_twh"], h["total_emissions_Mt"])
    logger.info("outputs written to %s", args.out_dir)


if __name__ == "__main__":
    main()
