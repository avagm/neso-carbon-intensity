"""
NESO published emission factors and their attribution to PyPSA-GB generators.

Single source of truth for the carbon-intensity post-processors in this folder.
Both system_carbon_intensity.py and nodal_carbon_intensity.py import the factor
tables and the attribution function from here, so the two views cannot drift
apart.

Why these factors and not the PyPSA-GB carrier definitions. PyPSA-GB stores
per-carrier co2_emissions in tonnes CO2 per MWh thermal and applies a uniform
placeholder efficiency of 0.5 to every thermal carrier, which makes the implied
electrical factors unreliable. The NESO published values are already stated at
the electrical system boundary (gCO2 per kWh sent out) and need no efficiency
conversion, so they are applied directly to dispatched generation.

Source: NESO Carbon Intensity API, /intensity/factors endpoint
(https://api.carbonintensity.org.uk). The values below are a fixed snapshot.
NESO revises them periodically; re-pull with pull_neso_2023.py and check the
snapshot date before quoting numbers. The same table is documented in the
methodology (topology_comparison_methodology.md, "Emission factors").
"""
from __future__ import annotations

import logging

import pandas as pd
import pypsa


logger = logging.getLogger("neso_factors")

# tCO2 per MWh electrical equals 1000 times gCO2 per kWh electrical.
T_PER_MWH_TO_G_PER_KWH = 1000.0

# NESO published emission factors, gCO2 per kWh of electricity sent out. NESO
# publishes a single "Biomass" factor (120), applied here to every biogenic
# PyPSA-GB carrier; waste-to-energy takes the NESO "Other" factor (300). Wind,
# solar, hydro, marine and nuclear are zero at the system boundary.
# load_shedding is the unmet-demand pseudo generator, not a fuel, so it is zero.
NESO_CARRIER_FACTORS: dict[str, float] = {
    "wind_onshore":     0.0,
    "wind_offshore":    0.0,
    "solar_pv":         0.0,
    "large_hydro":      0.0,
    "small_hydro":      0.0,
    "tidal_stream":     0.0,
    "shoreline_wave":   0.0,
    "nuclear":          0.0,
    "biomass":          120.0,
    "biogas":           120.0,
    "landfill_gas":     120.0,
    "sewage_gas":       120.0,
    "advanced_biofuel": 120.0,
    "CCGT":             394.0,
    "OCGT":             651.0,
    "coal":             937.0,
    "oil":              935.0,
    "waste_to_energy":  300.0,
    "load_shedding":    0.0,
}

# NESO attributes interconnector imports to the source country. PyPSA-GB places
# each EU_import generator on an external bus carrying a `country` tag, and that
# tag selects the factor. Netherlands, France and Ireland are NESO published
# factors; Belgium uses the NESO "Other" factor (no published Belgian row);
# Norway and Denmark use the respective national TSO published 2023 figures.
NESO_INTERCONNECTOR_FACTORS: dict[str, float] = {
    "Netherlands": 474.0,
    "France":       53.0,
    "Ireland":      458.0,
    "Belgium":      300.0,
    "Norway":       35.0,
    "Denmark":      130.0,
}

# Carriers whose generators represent interconnector imports. Their factor is
# looked up by the attached bus country, not by the carrier name.
INTERCONNECTOR_CARRIERS: set[str] = {"EU_import"}

# Stand-in factor for an interconnector whose bus country is not in the table
# above. NESO "Other" (300) is the documented value for an unclassified import.
UNKNOWN_INTERCONNECTOR_FACTOR = 300.0


def generator_emission_factors(
    n: pypsa.Network,
) -> tuple[pd.Series, dict[str, dict]]:
    """
    NESO electrical emission factor (gCO2 per kWh) for every generator.

    Domestic carriers are taken from NESO_CARRIER_FACTORS. Interconnector
    generators are taken from NESO_INTERCONNECTOR_FACTORS, keyed by the
    `country` tag of the bus they sit on. Anything that fails to match is
    reported in the returned diagnostics so it is visible in the manifest: an
    unmatched domestic carrier is set to zero, an unmatched interconnector
    country to the NESO "Other" factor.

    Returns (factors, diagnostics): factors is a Series indexed by generator
    name in gCO2 per kWh; diagnostics records any unmatched carriers and
    interconnector countries.
    """
    carriers = n.generators["carrier"].astype(str)
    is_ic = carriers.isin(INTERCONNECTOR_CARRIERS)

    # Domestic generators: factor by carrier name.
    factors = carriers.map(NESO_CARRIER_FACTORS)

    # Interconnector generators: factor by the country of the attached bus.
    countries = pd.Series("", index=n.generators.index, dtype=object)
    if is_ic.any():
        if "country" not in n.buses.columns:
            raise ValueError(
                "network has interconnector generators but n.buses has no "
                "'country' column; cannot attribute import emissions"
            )
        ic_country = n.generators.loc[is_ic, "bus"].map(n.buses["country"])
        countries.loc[is_ic] = ic_country
        factors.loc[is_ic] = ic_country.map(NESO_INTERCONNECTOR_FACTORS)

    # Diagnostics, then documented fallbacks for whatever did not match.
    unmatched_carrier = (~is_ic) & factors.isna()
    unmatched_ic = is_ic & factors.isna()
    diagnostics = {
        "unmatched_carriers":
            carriers[unmatched_carrier].value_counts().to_dict(),
        "unmatched_interconnector_countries":
            countries[unmatched_ic].astype(str).value_counts().to_dict(),
    }
    if diagnostics["unmatched_carriers"]:
        logger.warning("carriers with no NESO factor, set to 0 gCO2/kWh: %s",
                       diagnostics["unmatched_carriers"])
    if diagnostics["unmatched_interconnector_countries"]:
        logger.warning("interconnector buses with no country factor, set to "
                       "NESO Other (%g gCO2/kWh): %s",
                       UNKNOWN_INTERCONNECTOR_FACTOR,
                       diagnostics["unmatched_interconnector_countries"])
    factors.loc[unmatched_ic] = UNKNOWN_INTERCONNECTOR_FACTOR
    factors.loc[unmatched_carrier] = 0.0

    return factors.astype(float), diagnostics
