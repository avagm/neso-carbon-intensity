"""
Cached data loaders for the carbon-intensity dashboard.

Everything the dashboard draws comes from the pre-computed CSVs under
results/2023_topology_default/ (per-topology system intensity, hourly
per-carrier generation and emissions, annual per-carrier totals, per-bus
generation-view intensity with coordinates) and the NESO truth series under
results/neso_2023/. No PyPSA network is touched at run time.

All model series use a naive UTC hourly index (PyPSA-GB snapshots). The NESO
actual series is published half-hourly with a tz-aware UTC stamp; it is averaged
to the hour and converted to the same naive UTC index so every series aligns on
one join key.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

REPO = Path(__file__).resolve().parents[2]

# Data resolution. The dashboard prefers the committed bundle under
# dashboard/data/ (so a fresh clone runs without the git-ignored working
# results/ tree), and falls back to the local working tree when developing.
# _data() takes a repo-relative path and returns whichever copy exists, bundle
# first. The bundle mirrors the repo's data layout, so a path like
# "results/2023_topology_default/zonal_17bus/system_carbon_intensity.csv"
# resolves to the same sub-path under dashboard/data/ if present.
BUNDLE = REPO / "dashboard" / "data"


def _data(rel: str) -> Path:
    bundled = BUNDLE / rel
    return bundled if bundled.exists() else REPO / rel


def _topo_file(key: str, fname: str) -> Path:
    return _data(f"results/2023_topology_default/{TOPOLOGIES[key]['dir']}/{fname}")

# Topology registry. `provisional` flags the ETYS suboptimal interior point
# (see deliverables/etys_data_validation.md). `has_map` is True where a
# buses_with_ci.csv exists (the copperplate shares the Reduced geometry, so it
# has no separate map).
TOPOLOGIES: dict[str, dict] = {
    "neso_actual": {"label": "NESO actual", "dir": None, "has_map": False,
                    "provisional": False, "is_model": False},
    "zonal_17bus": {"label": "Zonal 17-bus", "dir": "zonal_17bus",
                    "has_map": True, "provisional": False, "is_model": True},
    "reduced_32bus": {"label": "Reduced 32-bus", "dir": "reduced_32bus",
                      "has_map": True, "provisional": False, "is_model": True},
    "reduced_32bus_copperplate": {"label": "Reduced 32-bus (copperplate)",
                                   "dir": "reduced_32bus_copperplate",
                                   "has_map": False, "provisional": False,
                                   "is_model": True},
    "etys_2000bus": {"label": "ETYS 2000-bus",
                     "dir": "etys_2000bus", "has_map": True,
                     "provisional": True, "is_model": True},
}

MODEL_KEYS = [k for k, v in TOPOLOGIES.items() if v["is_model"]]


def available_topologies() -> dict[str, dict]:
    """Topologies whose directory and system CSV exist on disk."""
    out = {}
    for key, meta in TOPOLOGIES.items():
        if not meta["is_model"]:
            out[key] = meta
            continue
        if _topo_file(key, "system_carbon_intensity.csv").exists():
            out[key] = meta
    return out


@st.cache_data(show_spinner=False)
def load_system_ci(key: str) -> pd.DataFrame:
    """Hourly system intensity for one topology, naive UTC index."""
    df = pd.read_csv(_topo_file(key, "system_carbon_intensity.csv"),
                     parse_dates=["snapshot"], index_col="snapshot")
    df.index.name = "timestamp"
    return df


@st.cache_data(show_spinner=False)
def load_neso_hourly() -> pd.Series:
    """NESO national actual intensity, averaged to hourly, naive UTC index."""
    df = pd.read_csv(_data("results/neso_2023/national_intensity.csv"))
    idx = pd.to_datetime(df["from"], utc=True)
    s = pd.Series(df["actual"].to_numpy(), index=idx, name="neso_actual")
    s = s.resample("1h").mean()
    s.index = s.index.tz_localize(None)
    s.index.name = "timestamp"
    # The first NESO settlement period floors to 2022-12-31 23:00; clip to the
    # 2023 calendar so the series aligns one-to-one with the model snapshots.
    s = s[s.index >= "2023-01-01 00:00"]
    return s.dropna()


@st.cache_data(show_spinner=False)
def load_neso_hourly_filled() -> tuple[pd.Series, int]:
    """
    NESO actual on the full 8760-hour grid with the published gaps filled, for
    display only. NESO did not publish an actual carbon intensity for ~47 hours
    of 2023: a 45.5-hour outage on 20-22 October (rows entirely absent) plus five
    isolated settlement periods (present but null). Those isolated hours take the
    NESO forecast; the October block is time-interpolated. Returns the filled
    series and the number of filled hours.

    This backs the calendar heatmap so it has no confusing blank cells. Every
    statistic (Overview, Validation, the combined frame) uses load_neso_hourly(),
    the pure actual series, so headline numbers are unaffected by this fill.
    """
    df = pd.read_csv(_data("results/neso_2023/national_intensity.csv"))
    idx = pd.to_datetime(df["from"], utc=True)
    grid = pd.date_range("2023-01-01 00:00", "2023-12-31 23:30", freq="30min",
                         tz="UTC")
    actual = pd.Series(df["actual"].to_numpy(), index=idx).reindex(grid) \
        .resample("1h").mean()
    fcast = pd.Series(df["forecast"].to_numpy(), index=idx).reindex(grid) \
        .resample("1h").mean()
    actual.index = actual.index.tz_localize(None)
    fcast.index = fcast.index.tz_localize(None)

    missing = actual.isna()
    filled = actual.copy()
    filled[missing] = fcast[missing]                       # NESO forecast first
    filled = filled.interpolate(method="time", limit_area="inside")  # then bridge
    filled.name = "neso_actual"
    filled.index.name = "timestamp"
    return filled, int(missing.sum())


@st.cache_data(show_spinner=False)
def load_combined_ci() -> pd.DataFrame:
    """
    All available series on one naive UTC hourly index (outer join).
    Columns are topology keys; values are gCO2 per kWh. NESO included as
    neso_actual. Callers drop NaN per pair as needed.
    """
    cols = {}
    for key in MODEL_KEYS:
        if key in available_topologies():
            cols[key] = load_system_ci(key)["system_gCO2_per_kWh"]
    cols["neso_actual"] = load_neso_hourly()
    combined = pd.DataFrame(cols).sort_index()
    return combined


@st.cache_data(show_spinner=False)
def load_hourly_carrier(key: str, kind: str = "generation") -> pd.DataFrame:
    """
    Hourly per-carrier generation (MWh) or emissions (tCO2), naive UTC index.
    kind in {"generation", "emissions"}.
    """
    fname = ("hourly_generation_by_carrier.csv" if kind == "generation"
             else "hourly_emissions_by_carrier.csv")
    df = pd.read_csv(_topo_file(key, fname),
                     parse_dates=["snapshot"], index_col="snapshot")
    df.index.name = "timestamp"
    return df


@st.cache_data(show_spinner=False)
def load_annual_carrier(key: str) -> pd.DataFrame:
    """Annual generation and emissions per carrier for one topology."""
    return pd.read_csv(_topo_file(key, "generation_by_carrier.csv"),
                       index_col="carrier")


@st.cache_data(show_spinner=False)
def load_buses(key: str) -> pd.DataFrame | None:
    """Per-bus generation-view CI with coordinates, or None if not available."""
    path = _topo_file(key, "buses_with_ci.csv")
    if not path.exists():
        return None
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def load_neso_regions_geojson() -> dict | None:
    """The 14 NESO region polygons (GeoJSON dict), or None if not built."""
    path = _data("data/topology/neso_regions.geojson")
    if not path.exists():
        return None
    import json
    return json.loads(path.read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_region_intensity(key: str) -> pd.DataFrame | None:
    """Per-NESO-region generation-view CI for one topology, or None."""
    path = _topo_file(key, "neso_region_intensity.csv")
    if not path.exists():
        return None
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def load_bus_catchments(key: str) -> tuple[dict, pd.DataFrame] | None:
    """
    Voronoi bus-catchment polygons for one topology as (geojson, properties).
    The geojson is keyed on properties.bus; the DataFrame carries bus,
    gen_view_gCO2_per_kWh, and dominant_carrier per feature. None if not built.
    """
    import json
    path = _topo_file(key, "bus_catchments.geojson")
    if not path.exists():
        return None
    gj = json.loads(path.read_text(encoding="utf-8"))
    props = pd.DataFrame([f["properties"] for f in gj["features"]])
    return gj, props


@st.cache_data(show_spinner=False)
def load_bus_carrier(key: str, kind: str = "generation") -> pd.DataFrame | None:
    """
    Per-bus per-carrier annual matrix for one topology (index=bus, one column
    per carrier), or None if not built. kind in {"generation", "emissions"};
    generation is MWh, emissions tCO2. Drives the per-catchment mix pie (a
    catchment is one bus). Built by extract_dashboard_data.py --per-bus.
    """
    fname = (f"bus_carrier_{kind}.csv")
    path = _topo_file(key, fname)
    if not path.exists():
        return None
    return pd.read_csv(path, index_col="bus")


@st.cache_data(show_spinner=False)
def load_region_carrier(key: str, kind: str = "generation") -> pd.DataFrame | None:
    """
    Per-NESO-region per-carrier annual matrix (index=regionid), or None if not
    built. kind in {"generation", "emissions"}. Drives the per-region mix pie.
    Built by aggregate_neso_regions.py once the bus_carrier matrices exist.
    """
    path = _topo_file(key, f"region_carrier_{kind}.csv")
    if not path.exists():
        return None
    return pd.read_csv(path, index_col="regionid")


@st.cache_data(show_spinner=False)
def load_catchment_names(key: str) -> dict[str, str]:
    """
    Curated bus -> human-readable area name for one topology's catchments, or an
    empty dict if no names file exists. Source: data/topology/<dir>/catchment_names.csv.
    """
    rel_dir = TOPOLOGIES[key]["dir"]
    if rel_dir is None:
        return {}
    path = _data(f"data/topology/{rel_dir}/catchment_names.csv")
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    return dict(zip(df["bus"].astype(str), df["area_name"].astype(str)))


@st.cache_data(show_spinner=False)
def headline_table() -> pd.DataFrame:
    """Annual mean / std / min / max per available series over common hours."""
    combined = load_combined_ci()
    rows = []
    for col in combined.columns:
        s = combined[col].dropna()
        rows.append({
            "series": TOPOLOGIES[col]["label"],
            "key": col,
            "mean": s.mean(), "std": s.std(), "min": s.min(), "max": s.max(),
            "hours": int(s.notna().sum()),
        })
    return pd.DataFrame(rows).set_index("key")


def data_year_bounds() -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last model timestamp (the calendar covered by the data)."""
    combined = load_combined_ci()
    return combined.index.min(), combined.index.max()
