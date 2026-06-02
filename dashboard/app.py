"""
GB carbon-intensity dashboard (PyPSA-GB topology comparison, 2023).

A Streamlit app over the pre-computed topology-comparison dataset. It presents
the modelled hourly carbon intensity of the GB system for 2023 on the Zonal
17-bus, Reduced 32-bus, copperplate, and ETYS 2000-bus topologies against the
NESO national actual, in the NESO visual language.

Views (sidebar), in order:
  - Overview            headline intensities and the hourly series for a window.
  - Time-slice explorer generation / emissions mix pie + area for any day, week,
                        or month, grouped by technology, carbon class, or
                        renewable status.
  - Geographical map    NESO region choropleth (default), per-bus points, and a
                        Voronoi catchment fill, all generation-view intensity.
  - Calendar heatmap    hour-of-day by date intensity heatmap, NESO colour scale.
  - Validation          one scrolling page: model vs NESO scatter, intensity
                        duration curve, and top carriers by annual generation.

Run:
    streamlit run dashboard/app.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lib import carriers as C
from lib import data as D
from lib import theme as T

st.set_page_config(page_title="GB Carbon Intensity — PyPSA-GB",
                   page_icon="\U0001F50C", layout="wide")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.6rem; padding-bottom: 1rem;}
      [data-testid="stMetricValue"] {font-size: 1.5rem;}
      .prov-banner {background:#fff4e5; border-left:4px solid #e8792b;
        padding:0.5rem 0.9rem; border-radius:4px; font-size:0.9rem;
        color:#7a3e00; margin-bottom:0.6rem;}
    </style>
    """, unsafe_allow_html=True)

YEAR = 2023
AVAILABLE = D.available_topologies()
MODEL_OPTS = [k for k in D.MODEL_KEYS if k in AVAILABLE]


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------
def period_selector(key_prefix: str) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    """Sidebar window picker. Returns (start, end inclusive, label)."""
    ptype = st.sidebar.selectbox(
        "Period", ["Full year", "Month", "Week", "Day", "Custom range"],
        index=1, key=f"{key_prefix}_ptype")
    lo = pd.Timestamp(f"{YEAR}-01-01 00:00")
    hi = pd.Timestamp(f"{YEAR}-12-31 23:00")

    if ptype == "Full year":
        return lo, hi, f"full year {YEAR}"
    if ptype == "Month":
        months = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
        m = st.sidebar.selectbox("Month", months, index=0, key=f"{key_prefix}_m")
        mi = months.index(m) + 1
        start = pd.Timestamp(f"{YEAR}-{mi:02d}-01 00:00")
        end = (start + pd.offsets.MonthEnd(1)).replace(hour=23)
        return start, end, f"{m} {YEAR}"
    if ptype == "Week":
        d = st.sidebar.date_input("Week starting", value=pd.Timestamp(f"{YEAR}-01-02"),
                                  min_value=lo.date(), max_value=hi.date(),
                                  key=f"{key_prefix}_w")
        start = pd.Timestamp(d).normalize()
        end = start + pd.Timedelta(days=6, hours=23)
        return start, min(end, hi), f"week of {start.date()}"
    if ptype == "Day":
        d = st.sidebar.date_input("Day", value=lo.date(), min_value=lo.date(),
                                  max_value=hi.date(), key=f"{key_prefix}_d")
        start = pd.Timestamp(d).normalize()
        return start, start.replace(hour=23), f"{start.date()}"
    # Custom range
    rng = st.sidebar.date_input("Date range", value=(lo.date(), (lo + pd.Timedelta(days=13)).date()),
                                min_value=lo.date(), max_value=hi.date(),
                                key=f"{key_prefix}_c")
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        start = pd.Timestamp(rng[0]).normalize()
        end = pd.Timestamp(rng[1]).normalize().replace(hour=23)
    else:
        start, end = lo, hi
    return start, end, f"{start.date()} to {end.date()}"


def group_columns(df: pd.DataFrame, grouping: str) -> pd.DataFrame:
    """Collapse per-carrier columns into the chosen grouping's columns."""
    gmap = C.GROUPINGS[grouping]["map"]
    mapped = {c: gmap.get(c, "Other") for c in df.columns}
    grouped = df.T.groupby(mapped).sum().T
    order = C.GROUPINGS[grouping]["order"]
    if order:
        cols = [g for g in order if g in grouped.columns]
        cols += [g for g in grouped.columns if g not in cols]
        grouped = grouped[cols]
    else:
        grouped = grouped[grouped.sum().sort_values(ascending=False).index]
    return grouped


def group_colours(grouping: str, groups) -> list[str]:
    cmap = C.GROUPINGS[grouping]["colour"]
    return [cmap.get(g, "#999999") for g in groups]


def provisional_note(key: str) -> None:
    if D.TOPOLOGIES[key]["provisional"]:
        st.markdown(
            '<div class="prov-banner"><b>ETYS 2000-bus is provisional.</b> '
            "From the suboptimal barrier interior point (HPC job 2899855). The "
            "annual mean (189 gCO2/kWh) is validated as the real congestion "
            "signature, but it carries a +0.36% generation-demand smear and two "
            "Northern Ireland imports on the NESO Other fallback. See "
            "deliverables/etys_data_validation.md.</div>",
            unsafe_allow_html=True)


def add_index_bands(fig: go.Figure) -> None:
    """Faint NESO-style intensity bands behind a time series."""
    for _label, lo, hi, colour in T.INDEX_BANDS:
        fig.add_hrect(y0=lo, y1=min(hi, 360), fillcolor=colour, opacity=0.06,
                      line_width=0, layer="below")


# --------------------------------------------------------------------------
# View: Overview
# --------------------------------------------------------------------------
def view_overview() -> None:
    st.subheader("National carbon intensity")
    start, end, label = period_selector("ov")
    combined = D.load_combined_ci().loc[start:end]

    series_keys = ["neso_actual"] + MODEL_OPTS
    cols = st.columns(len(series_keys))
    neso_mean = combined["neso_actual"].mean()
    for col, key in zip(cols, series_keys):
        if key not in combined:
            continue
        m = combined[key].mean()
        idx_label, _ = T.ci_index(m)
        delta = None if key == "neso_actual" else f"{m - neso_mean:+.1f} vs NESO"
        col.metric(D.TOPOLOGIES[key]["label"], f"{m:.0f} gCO2/kWh",
                   delta=delta, delta_color="off")
        col.caption(f"index: {idx_label}")

    st.caption(f"Means over {label}. Carbon intensity in gCO2 per kWh.")

    fig = go.Figure()
    add_index_bands(fig)
    for key in series_keys:
        if key not in combined:
            continue
        meta = D.TOPOLOGIES[key]
        fig.add_trace(go.Scatter(
            x=combined.index, y=combined[key], name=meta["label"],
            line=dict(color=T.TOPOLOGY_COLOUR.get(key), width=2.4 if key == "neso_actual" else 1.5),
            opacity=1.0 if key == "neso_actual" else 0.85))
    fig.update_layout(**T.base_layout(
        title=f"Hourly carbon intensity, {label}",
        yaxis_title="gCO2 / kWh", xaxis_title=None, height=460))
    fig.update_yaxes(range=[0, max(360, combined.max().max() * 1.05)])
    st.plotly_chart(fig, width='stretch')
    st.caption("Shaded bands are NESO-style intensity levels (very low to very "
               "high). NESO actual is the bold black line.")


# --------------------------------------------------------------------------
# View: Time-slice explorer (generation / emissions mix)
# --------------------------------------------------------------------------
def view_explorer() -> None:
    st.subheader("Generation and emissions mix")
    key = st.sidebar.selectbox("Topology", MODEL_OPTS,
                               format_func=lambda k: D.TOPOLOGIES[k]["label"],
                               key="ex_topo")
    grouping = st.sidebar.radio("Group by", list(C.GROUPINGS.keys()), key="ex_group")
    metric = st.sidebar.radio("Quantity", ["Generation (MWh)", "Emissions (tCO2)"],
                              key="ex_metric")
    start, end, label = period_selector("ex")
    provisional_note(key)

    kind = "generation" if metric.startswith("Generation") else "emissions"
    raw = D.load_hourly_carrier(key, kind).loc[start:end]
    gen_raw = D.load_hourly_carrier(key, "generation").loc[start:end]
    grouped = group_columns(raw, grouping)
    totals = grouped.sum()
    totals = totals[totals > 0]

    # Headline metrics for the window.
    total_gen_mwh = float(gen_raw.to_numpy().sum())
    em_win = D.load_hourly_carrier(key, "emissions").loc[start:end]
    total_em_t = float(em_win.to_numpy().sum())
    mean_ci = total_em_t / total_gen_mwh * 1000.0 if total_gen_mwh else float("nan")
    ren = float(gen_raw[[c for c in gen_raw.columns if c in C.RENEWABLE_CARRIERS]].to_numpy().sum())
    zc = float(gen_raw[[c for c in gen_raw.columns if c in C.ZERO_CARBON_CARRIERS]].to_numpy().sum())
    ren_share = ren / total_gen_mwh * 100 if total_gen_mwh else 0.0
    zc_share = zc / total_gen_mwh * 100 if total_gen_mwh else 0.0

    left, right = st.columns([3, 2])
    with left:
        unit = "MWh" if kind == "generation" else "tCO2"
        fig = go.Figure(go.Pie(
            labels=list(totals.index), values=list(totals.values), hole=0.45,
            marker=dict(colors=group_colours(grouping, totals.index)),
            sort=False, direction="clockwise",
            texttemplate="%{label}<br>%{percent}",
            hovertemplate="%{label}<br>%{value:,.0f} " + unit + "<br>%{percent}<extra></extra>"))
        fig.update_layout(**T.base_layout(
            title=f"{metric} by {grouping.lower()} — {label}", height=430,
            legend=dict(orientation="v", x=1.0, y=0.5)))
        st.plotly_chart(fig, width='stretch')
    with right:
        st.metric("Mean carbon intensity", f"{mean_ci:.0f} gCO2/kWh")
        st.metric("Total generation", f"{total_gen_mwh/1e3:,.0f} GWh")
        st.metric("Renewable share", f"{ren_share:.1f} %",
                  help="Wind, solar, hydro, marine, and biomass as a share of "
                       "generation. Excludes nuclear (low carbon, not renewable).")
        st.metric("Zero-carbon share", f"{zc_share:.1f} %",
                  help="Wind, solar, hydro, marine, nuclear, and storage.")
        st.caption(f"Window: {label}. Topology: {D.TOPOLOGIES[key]['label']}.")

    # Stacked area over the window.
    area = grouped.resample("1h").sum()
    figa = go.Figure()
    for g in grouped.columns:
        if grouped[g].sum() <= 0:
            continue
        figa.add_trace(go.Scatter(
            x=area.index, y=area[g], name=g, stackgroup="one", mode="lines",
            line=dict(width=0.5, color=C.GROUPINGS[grouping]["colour"].get(g, "#999999")),
            fillcolor=C.GROUPINGS[grouping]["colour"].get(g, "#999999")))
    unit = "MWh" if kind == "generation" else "tCO2"
    figa.update_layout(**T.base_layout(
        title=f"{metric} over time — {label}", yaxis_title=unit, height=340,
        hovermode="x unified"))
    st.plotly_chart(figa, width='stretch')


# --------------------------------------------------------------------------
# View: Calendar heatmap
# --------------------------------------------------------------------------
def view_heatmap() -> None:
    st.subheader("Carbon-intensity heatmap (date by hour of day)")
    series_keys = ["neso_actual"] + MODEL_OPTS
    key = st.sidebar.selectbox("Series", series_keys,
                               format_func=lambda k: D.TOPOLOGIES[k]["label"],
                               key="hm_key")
    mode = st.sidebar.radio("Mode", ["Intensity", "Difference vs NESO"], key="hm_mode")
    provisional_note(key)

    combined = D.load_combined_ci()
    s = combined[key]
    if mode == "Difference vs NESO" and key != "neso_actual":
        s = (combined[key] - combined["neso_actual"])
    s = s.dropna()

    # Hour of day on the y-axis (24 legible rows), calendar date across the
    # x-axis (the season). Reading: horizontal bands are time-of-day patterns,
    # left-to-right is the year.
    df = pd.DataFrame({"v": s.to_numpy()},
                      index=pd.Index(s.index, name="t")).reset_index()
    df["date"] = df["t"].dt.normalize()
    df["hour"] = df["t"].dt.hour
    pivot = df.pivot_table(index="hour", columns="date", values="v")

    if mode == "Intensity":
        colorscale, zmin, zmax = T.CI_COLORSCALE, T.CI_MIN, T.CI_MAX
        cbar = "gCO2 / kWh"
        title = f"{D.TOPOLOGIES[key]['label']} hourly intensity, {YEAR}"
    else:
        colorscale = "RdBu_r"
        amax = float(np.nanpercentile(np.abs(pivot.to_numpy()), 98))
        zmin, zmax = -amax, amax
        cbar = "model minus NESO (gCO2/kWh)"
        title = f"{D.TOPOLOGIES[key]['label']} minus NESO, {YEAR}"

    fig = go.Figure(go.Heatmap(
        z=pivot.to_numpy(), x=pivot.columns, y=[f"{h:02d}:00" for h in pivot.index],
        colorscale=colorscale, zmin=zmin, zmax=zmax,
        colorbar=dict(title=cbar),
        hovertemplate="%{x|%b %d} %{y}<br>%{z:.0f}<extra></extra>"))
    fig.update_layout(**T.base_layout(title=title, height=470,
                                      xaxis_title=None, yaxis_title="hour of day (UTC)"))
    fig.update_xaxes(dtick="M1", tickformat="%b")
    st.plotly_chart(fig, width="stretch")
    st.caption("Each column is one day of 2023, each row one hour of the day. "
               "Evening-peak hours read as a persistent red band; midday in "
               "summer dips green. Switch to Difference vs NESO to see when and "
               "where a topology over- or under-states intensity.")


# --------------------------------------------------------------------------
# View: Geographical map
# --------------------------------------------------------------------------
def _map_points(buses: pd.DataFrame) -> None:
    """Per-bus markers: area by generation, colour by generation-view CI."""
    sizeref = 2.0 * buses["total_generation_mwh"].max() / (38 ** 2)
    labels = buses["dominant_carrier"].map(C.pretty)
    fig = go.Figure(go.Scattermap(
        lat=buses["lat"], lon=buses["lon"], mode="markers",
        marker=dict(
            size=buses["total_generation_mwh"], sizemode="area", sizeref=sizeref,
            sizemin=3, color=buses["gen_view_gCO2_per_kWh"],
            colorscale=T.CI_COLORSCALE, cmin=T.CI_MIN, cmax=T.CI_MAX,
            colorbar=dict(title="gCO2/kWh"), opacity=0.82),
        text=buses["bus"], customdata=np.stack([
            labels, buses["total_generation_mwh"] / 1e3,
            buses["gen_view_gCO2_per_kWh"]], axis=-1),
        hovertemplate="<b>%{text}</b><br>%{customdata[0]}<br>"
                      "%{customdata[1]:,.0f} GWh/yr<br>"
                      "%{customdata[2]:.0f} gCO2/kWh<extra></extra>"))
    fig.update_layout(
        map=dict(style="carto-positron", center=dict(lat=54.7, lon=-3.0), zoom=4.4),
        margin=dict(l=0, r=0, t=10, b=0), height=700)
    st.plotly_chart(fig, width="stretch")
    st.caption("Marker area is annual generation; colour is the generation-view "
               "intensity (local emissions / local generation) on the NESO "
               "green-to-red scale. Pure-renewable and nuclear buses sit at zero "
               "(green), thermal hubs high (red).")


def _map_catchments(key: str) -> None:
    """Voronoi catchment fill: the area nearest each bus, coloured by its CI."""
    cat = D.load_bus_catchments(key)
    if cat is None:
        st.info("Catchment polygons not found. Run "
                "`python scripts/build_bus_catchments.py` for this topology.")
        return
    geojson, props = cat
    fig = go.Figure(go.Choroplethmap(
        geojson=geojson, locations=props["bus"],
        z=props["gen_view_gCO2_per_kWh"], featureidkey="properties.bus",
        colorscale=T.CI_COLORSCALE, zmin=T.CI_MIN, zmax=T.CI_MAX,
        marker=dict(opacity=0.78, line=dict(width=0.4, color="white")),
        colorbar=dict(title="gCO2/kWh"),
        text=props["bus"], customdata=np.stack([
            props["dominant_carrier"].map(C.pretty)], axis=-1),
        hovertemplate="<b>%{text}</b><br>%{z:.0f} gCO2/kWh<br>"
                      "largest: %{customdata[0]}<extra></extra>"))
    fig.update_layout(
        map=dict(style="carto-positron", center=dict(lat=54.7, lon=-3.0), zoom=4.4),
        margin=dict(l=0, r=0, t=10, b=0), height=700)
    st.plotly_chart(fig, width="stretch")
    st.caption(f"GB tiled into {len(props)} catchments, one per bus: every "
               "location is coloured by the generation-view intensity of its "
               "nearest bus. This is the point map filled in. On the coarse "
               "networks it is a handful of large regions; on ETYS a fine mosaic. "
               "Offshore and interconnector buses are excluded.")


def _map_regions(key: str) -> None:
    """Choropleth of the 14 NESO regions, coloured by regional generation-view CI."""
    geojson = D.load_neso_regions_geojson()
    region = D.load_region_intensity(key)
    if geojson is None or region is None:
        st.info("NESO region data not found. Run "
                "`python scripts/aggregate_neso_regions.py` for this topology.")
        return
    fig = go.Figure(go.Choroplethmap(
        geojson=geojson, locations=region["regionid"],
        z=region["gen_view_gCO2_per_kWh"], featureidkey="properties.regionid",
        colorscale=T.CI_COLORSCALE, zmin=T.CI_MIN, zmax=T.CI_MAX,
        marker=dict(opacity=0.78, line=dict(width=1, color="white")),
        colorbar=dict(title="gCO2/kWh"),
        text=region["shortname"], customdata=np.stack([
            region["shortname"], region["total_generation_twh"],
            region["dominant_carrier"].map(C.pretty)], axis=-1),
        hovertemplate="<b>%{customdata[0]}</b><br>%{z:.0f} gCO2/kWh<br>"
                      "%{customdata[1]:.1f} TWh/yr<br>"
                      "largest: %{customdata[2]}<extra></extra>"))
    fig.update_layout(
        map=dict(style="carto-positron", center=dict(lat=54.7, lon=-3.0), zoom=4.4),
        margin=dict(l=0, r=0, t=10, b=0), height=700)
    st.plotly_chart(fig, width="stretch")
    nb = int(region["n_buses_with_generation"].sum())
    filled = int((region.get("fill_method", pd.Series(dtype=str)) == "nearest_bus").sum())
    fill_note = (f" {filled} region(s) with no modelled bus take the nearest "
                 "bus's value." if filled else "")
    st.caption(f"All {len(region)} NESO carbon-intensity regions (GB GSP groups), "
               f"coloured by generation-weighted regional intensity aggregated "
               f"from {nb} modelled buses.{fill_note} Generation view: where "
               "carbon-emitting generation sits, not the NESO consumption-side "
               "regional series. Offshore and interconnector buses are excluded.")


def view_map() -> None:
    st.subheader("Geographical carbon intensity")
    style = st.sidebar.radio(
        "Map style",
        ["NESO regions", "Points (per bus)", "Catchment areas"],
        key="map_style",
        help="NESO regions: the 14 GSP-group regions. Points: one marker per "
             "bus. Catchment areas: the point map filled in (each bus owns its "
             "nearest area).")

    if style == "NESO regions":
        keys = [k for k in MODEL_OPTS if D.load_region_intensity(k) is not None]
        if not keys:
            st.info("No NESO region data found. Run "
                    "`python scripts/aggregate_neso_regions.py`.")
            return
        key = st.sidebar.selectbox("Topology", keys,
                                   format_func=lambda k: D.TOPOLOGIES[k]["label"],
                                   key="map_topo_region")
        provisional_note(key)
        _map_regions(key)
        return

    if style == "Catchment areas":
        keys = [k for k in MODEL_OPTS if D.load_bus_catchments(k) is not None]
        if not keys:
            st.info("No catchment data found. Run "
                    "`python scripts/build_bus_catchments.py`.")
            return
        key = st.sidebar.selectbox("Topology", keys,
                                   format_func=lambda k: D.TOPOLOGIES[k]["label"],
                                   key="map_topo_catch")
        provisional_note(key)
        _map_catchments(key)
        return

    # Points
    keys = [k for k in MODEL_OPTS if D.TOPOLOGIES[k]["has_map"]
            and D.load_buses(k) is not None]
    key = st.sidebar.selectbox("Topology", keys,
                               format_func=lambda k: D.TOPOLOGIES[k]["label"],
                               key="map_topo")
    provisional_note(key)
    buses = D.load_buses(key).copy()
    buses = buses[buses["total_generation_mwh"] > 0].dropna(
        subset=["gen_view_gCO2_per_kWh"])
    _map_points(buses)


# --------------------------------------------------------------------------
# View: Validation vs NESO
# --------------------------------------------------------------------------
def _metrics(model: pd.Series, truth: pd.Series) -> dict:
    df = pd.concat([model.rename("m"), truth.rename("t")], axis=1).dropna()
    m, t = df["m"].to_numpy(), df["t"].to_numpy()
    return {"n": len(df), "R": np.corrcoef(m, t)[0, 1],
            "RMSE": np.sqrt(np.mean((m - t) ** 2)), "bias": np.mean(m - t)}


def _scatter_vs_neso(key: str, combined: pd.DataFrame) -> go.Figure:
    df = pd.concat([combined[key].rename("m"),
                    combined["neso_actual"].rename("t")], axis=1).dropna()
    mk = _metrics(combined[key], combined["neso_actual"])
    lim = 340
    fig = go.Figure(go.Histogram2d(
        x=df["t"], y=df["m"], colorscale="YlOrRd", nbinsx=70, nbinsy=70,
        showscale=False))
    fig.add_trace(go.Scatter(x=[0, lim], y=[0, lim], mode="lines",
                             line=dict(color="#333", dash="dash"), showlegend=False))
    fig.update_layout(**T.base_layout(
        title=D.TOPOLOGIES[key]["label"], height=430, hovermode="closest"))
    fig.update_xaxes(title="NESO actual (gCO2/kWh)", range=[0, lim])
    fig.update_yaxes(title="model (gCO2/kWh)", range=[0, lim])
    fig.add_annotation(x=0.05, y=0.95, xref="paper", yref="paper", align="left",
                       showarrow=False, bgcolor="rgba(255,255,255,0.85)",
                       font=dict(size=13),
                       text=f"R = {mk['R']:.3f}<br>RMSE = {mk['RMSE']:.1f}"
                            f"<br>bias = {mk['bias']:+.1f}")
    return fig


def view_validation() -> None:
    st.subheader("Validation against NESO actual")
    combined = D.load_combined_ci()

    st.markdown("#### Model versus NESO, hourly density")
    st.caption("Each panel is the 2D density of hourly model-vs-NESO pairs for "
               "2023 (gCO2/kWh). The dashed line is y = x. The three coarse "
               "topologies sit below NESO (bias negative); ETYS sits above it "
               "(positive bias, the congestion signature).")
    for i in range(0, len(MODEL_OPTS), 2):
        cols = st.columns(2)
        for col, key in zip(cols, MODEL_OPTS[i:i + 2]):
            col.plotly_chart(_scatter_vs_neso(key, combined), width="stretch")

    st.divider()
    st.markdown("#### Intensity duration curve")
    fig = go.Figure()
    for key in ["neso_actual"] + MODEL_OPTS:
        s = combined[key].dropna().sort_values(ascending=False).to_numpy()
        fig.add_trace(go.Scatter(
            x=np.linspace(0, 100, len(s)), y=s, name=D.TOPOLOGIES[key]["label"],
            line=dict(color=T.TOPOLOGY_COLOUR.get(key),
                      width=3.0 if key == "neso_actual" else 1.8)))
    fig.update_layout(**T.base_layout(
        title=f"Intensity duration curve, {YEAR}", height=560,
        xaxis_title="% of hours exceeded", yaxis_title="gCO2 / kWh",
        hovermode="x unified"))
    st.plotly_chart(fig, width="stretch")
    st.caption("Every hour sorted from highest to lowest intensity. The flat high "
               "floor on ETYS reflects thermal generation forced behind binding "
               "transmission constraints, never reaching the clean hours the "
               "coarse topologies and NESO do.")

    st.divider()
    st.markdown("#### Top carriers by annual generation")
    key = st.selectbox("Topology", MODEL_OPTS,
                       format_func=lambda k: D.TOPOLOGIES[k]["label"],
                       key="val_topo")
    provisional_note(key)
    ann = D.load_annual_carrier(key).sort_values("generation_twh", ascending=True)
    ann = ann[ann["generation_twh"] > 0.05]
    klass = [C.CARRIER_CARBON_CLASS.get(c, "High carbon") for c in ann.index]
    fig = go.Figure(go.Bar(
        x=ann["generation_twh"], y=[C.pretty(c) for c in ann.index],
        orientation="h", marker=dict(color=[C.CARBON_CLASS_COLOUR[k] for k in klass]),
        customdata=np.stack([ann["mean_factor_gCO2_per_kWh"]], axis=-1),
        hovertemplate="%{y}<br>%{x:.1f} TWh<br>%{customdata[0]:.0f} gCO2/kWh<extra></extra>"))
    for cls in C.CARBON_CLASS_ORDER:
        fig.add_trace(go.Bar(x=[None], y=[None], name=cls,
                             marker=dict(color=C.CARBON_CLASS_COLOUR[cls])))
    fig.update_layout(**T.base_layout(
        title=f"Annual generation by carrier, {D.TOPOLOGIES[key]['label']}, {YEAR}",
        height=620, xaxis_title="TWh", yaxis_title=None, hovermode="closest"),
        barmode="stack", showlegend=True)
    st.plotly_chart(fig, width="stretch")
    st.caption("Bars coloured by carbon class: green zero, amber low (biogenic "
               "and imports), red high (gas, coal, oil, waste to energy).")


# --------------------------------------------------------------------------
# Router
# --------------------------------------------------------------------------
def main() -> None:
    st.sidebar.title("GB Carbon Intensity")
    st.sidebar.caption(f"PyPSA-GB topology comparison, {YEAR}")
    view = st.sidebar.radio(
        "View",
        ["Overview", "Time-slice explorer", "Geographical map",
         "Calendar heatmap", "Validation"],
        key="view")
    st.sidebar.divider()

    {"Overview": view_overview,
     "Time-slice explorer": view_explorer,
     "Geographical map": view_map,
     "Calendar heatmap": view_heatmap,
     "Validation": view_validation}[view]()

    st.sidebar.divider()
    with st.sidebar.expander("About the data"):
        st.markdown(
            "Modelled hourly system carbon intensity from PyPSA-GB (commit "
            "`074ea25e`), post-processed with the NESO published emission "
            "factors. NESO actual is the national series from the Carbon "
            "Intensity API. ETYS 2000-bus is provisional (see "
            "`deliverables/etys_data_validation.md`).")


if __name__ == "__main__":
    main()
