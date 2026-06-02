"""
Carrier groupings and colours for the carbon-intensity dashboard.

The PyPSA-GB per-carrier series use machine names (CCGT, wind_offshore,
EU_import, ...). The dashboard groups them three ways so the pie / area / bar
charts can be sliced by whichever lens the user wants:

  - "Technology": wind, solar, nuclear, hydro, ... (the generation-mix view).
  - "Carbon class": Zero / Low / High carbon, matching the team's
    top-carriers bar chart legend.
  - "Renewable": Renewable / Nuclear / Fossil / Imports / Storage, for the
    "share of renewable generation" question.

Each grouping has a stable colour map so a carrier keeps its colour across
charts and topologies. Colours are chosen for categorical legibility; the
carbon-class palette is green / amber / red to match NESO's visual language.
"""
from __future__ import annotations

# Pretty labels for the raw carrier names.
CARRIER_LABEL: dict[str, str] = {
    "wind_onshore": "Wind onshore",
    "wind_offshore": "Wind offshore",
    "solar_pv": "Solar PV",
    "nuclear": "Nuclear",
    "large_hydro": "Hydro (large)",
    "small_hydro": "Hydro (small)",
    "tidal_stream": "Tidal stream",
    "shoreline_wave": "Wave",
    "biomass": "Biomass",
    "biogas": "Biogas",
    "landfill_gas": "Landfill gas",
    "sewage_gas": "Sewage gas",
    "advanced_biofuel": "Advanced biofuel",
    "CCGT": "Gas (CCGT)",
    "OCGT": "Gas (OCGT)",
    "coal": "Coal",
    "oil": "Oil",
    "waste_to_energy": "Waste to energy",
    "EU_import": "EU imports",
    "storage_discharge": "Storage discharge",
    "load_shedding": "Unserved (load shed)",
}

# Carrier -> technology group.
CARRIER_TECH: dict[str, str] = {
    "wind_onshore": "Wind",
    "wind_offshore": "Wind",
    "solar_pv": "Solar",
    "nuclear": "Nuclear",
    "large_hydro": "Hydro",
    "small_hydro": "Hydro",
    "tidal_stream": "Marine",
    "shoreline_wave": "Marine",
    "biomass": "Biomass",
    "biogas": "Biomass",
    "landfill_gas": "Biomass",
    "sewage_gas": "Biomass",
    "advanced_biofuel": "Biomass",
    "CCGT": "Gas",
    "OCGT": "Gas",
    "coal": "Coal",
    "oil": "Oil",
    "waste_to_energy": "Waste",
    "EU_import": "Imports",
    "storage_discharge": "Storage",
    "load_shedding": "Unserved",
}

TECH_COLOUR: dict[str, str] = {
    "Wind": "#5BA3D0",
    "Solar": "#F2C744",
    "Nuclear": "#B05BD0",
    "Hydro": "#3FB6C4",
    "Marine": "#2E8B8B",
    "Biomass": "#8FAE5D",
    "Gas": "#E8792B",
    "Coal": "#4D4D4D",
    "Oil": "#8B5A2B",
    "Waste": "#C45BAA",
    "Imports": "#9E9E9E",
    "Storage": "#7E57C2",
    "Unserved": "#FF1744",
}

# Carrier -> carbon class. Zero-carbon at the system boundary (wind, solar,
# nuclear, hydro, marine, storage). Low carbon: biogenic (120 gCO2/kWh) and the
# blended EU import (about 135 to 170 gCO2/kWh). High carbon: gas, coal, oil,
# and waste to energy (300 gCO2/kWh, the NESO Other factor).
CARRIER_CARBON_CLASS: dict[str, str] = {
    "wind_onshore": "Zero carbon", "wind_offshore": "Zero carbon",
    "solar_pv": "Zero carbon", "nuclear": "Zero carbon",
    "large_hydro": "Zero carbon", "small_hydro": "Zero carbon",
    "tidal_stream": "Zero carbon", "shoreline_wave": "Zero carbon",
    "storage_discharge": "Zero carbon", "load_shedding": "Zero carbon",
    "biomass": "Low carbon", "biogas": "Low carbon",
    "landfill_gas": "Low carbon", "sewage_gas": "Low carbon",
    "advanced_biofuel": "Low carbon", "EU_import": "Low carbon",
    "CCGT": "High carbon", "OCGT": "High carbon", "coal": "High carbon",
    "oil": "High carbon", "waste_to_energy": "High carbon",
}

CARBON_CLASS_COLOUR: dict[str, str] = {
    "Zero carbon": "#2CA25F",
    "Low carbon": "#FDAE61",
    "High carbon": "#D7301F",
}
CARBON_CLASS_ORDER = ["Zero carbon", "Low carbon", "High carbon"]

# Carrier -> renewable grouping. Biomass is counted as renewable here (it is a
# renewable fuel even though NESO assigns it 120 gCO2/kWh); nuclear is low
# carbon but not renewable, so it is its own group.
CARRIER_RENEWABLE: dict[str, str] = {
    "wind_onshore": "Renewable", "wind_offshore": "Renewable",
    "solar_pv": "Renewable", "large_hydro": "Renewable",
    "small_hydro": "Renewable", "tidal_stream": "Renewable",
    "shoreline_wave": "Renewable", "biomass": "Renewable",
    "biogas": "Renewable", "landfill_gas": "Renewable",
    "sewage_gas": "Renewable", "advanced_biofuel": "Renewable",
    "nuclear": "Nuclear",
    "CCGT": "Fossil", "OCGT": "Fossil", "coal": "Fossil",
    "oil": "Fossil", "waste_to_energy": "Fossil",
    "EU_import": "Imports",
    "storage_discharge": "Storage",
    "load_shedding": "Unserved",
}

RENEWABLE_COLOUR: dict[str, str] = {
    "Renewable": "#2CA25F",
    "Nuclear": "#B05BD0",
    "Fossil": "#E8792B",
    "Imports": "#9E9E9E",
    "Storage": "#7E57C2",
    "Unserved": "#FF1744",
}

# The three groupings the dashboard offers, keyed by the label shown in the UI.
GROUPINGS: dict[str, dict] = {
    "Technology": {"map": CARRIER_TECH, "colour": TECH_COLOUR, "order": None},
    "Carbon class": {"map": CARRIER_CARBON_CLASS, "colour": CARBON_CLASS_COLOUR,
                     "order": CARBON_CLASS_ORDER},
    "Renewable": {"map": CARRIER_RENEWABLE, "colour": RENEWABLE_COLOUR,
                  "order": ["Renewable", "Nuclear", "Fossil", "Imports",
                            "Storage", "Unserved"]},
}

# Carriers that count as renewable, for the headline renewable-share metric.
RENEWABLE_CARRIERS = {c for c, g in CARRIER_RENEWABLE.items() if g == "Renewable"}
ZERO_CARBON_CARRIERS = {c for c, g in CARRIER_CARBON_CLASS.items()
                        if g == "Zero carbon" and c != "load_shedding"}


def pretty(carrier: str) -> str:
    """Human label for a raw carrier name (falls back to the name itself)."""
    return CARRIER_LABEL.get(carrier, carrier)
