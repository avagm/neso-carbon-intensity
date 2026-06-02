"""
Visual theme for the dashboard: a NESO-style carbon-intensity colour scale and
shared Plotly layout defaults.

The NESO Carbon Intensity site colours intensity on a green (clean) to red
(dirty) scale and bins it into named index levels (very low to very high). NESO
resets the numeric thresholds annually (see reference.md section 1.2), so the
bands below are the dashboard's own fixed bands in the NESO visual language,
anchored to gCO2 per kWh; they are for display, not an assertion of NESO's
current thresholds.
"""
from __future__ import annotations

# Continuous green -> amber -> red scale for carbon intensity, as Plotly
# [fraction, colour] stops over the domain CI_MIN..CI_MAX gCO2 per kWh.
CI_MIN = 0.0
CI_MAX = 350.0
CI_COLORSCALE = [
    [0.00, "#157f3c"],   # deep green, very low
    [0.16, "#4caf50"],   # green, low
    [0.36, "#c2d72e"],   # yellow-green
    [0.52, "#f2c744"],   # amber, moderate
    [0.70, "#e8792b"],   # orange, high
    [0.86, "#d7301f"],   # red, very high
    [1.00, "#7f0000"],   # dark red, extreme
]

# Named index bands in the NESO style (gCO2 per kWh, dashboard bands).
INDEX_BANDS = [
    ("very low", 0, 50, "#157f3c"),
    ("low", 50, 120, "#4caf50"),
    ("moderate", 120, 200, "#f2c744"),
    ("high", 200, 300, "#e8792b"),
    ("very high", 300, 10_000, "#d7301f"),
]

# Stable per-topology accent colours for line / scatter overlays.
TOPOLOGY_COLOUR: dict[str, str] = {
    "neso_actual": "#111111",
    "zonal_17bus": "#1f77b4",
    "reduced_32bus": "#d9541a",
    "reduced_32bus_copperplate": "#7fb3d5",
    "etys_2000bus": "#8e44ad",
}

PLOTLY_TEMPLATE = "plotly_white"


def ci_index(value: float) -> tuple[str, str]:
    """Return (index label, colour) for a carbon-intensity value."""
    for label, lo, hi, colour in INDEX_BANDS:
        if lo <= value < hi:
            return label, colour
    return "very high", "#d7301f"


def base_layout(**overrides) -> dict:
    """
    Common Plotly layout keyword arguments; merge with chart-specific ones.

    Title is placed top-left and the horizontal legend sits just below it, in an
    enlarged top margin, so the two never overlap. Pass title as a string (it
    becomes the title text) or a dict (merged into the title spec). Any other
    keyword (legend, margin, hovermode, ...) overrides the default wholesale.
    """
    title = overrides.pop("title", None)
    layout = dict(
        template=PLOTLY_TEMPLATE,
        margin=dict(l=10, r=10, t=86, b=46),
        font=dict(family="Inter, Segoe UI, system-ui, sans-serif", size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0,
                    font=dict(size=12)),
        hovermode="x unified",
        title=dict(x=0.0, xanchor="left", y=0.975, yanchor="top",
                   font=dict(size=16, color="#1a1a1a")),
    )
    if isinstance(title, str):
        layout["title"]["text"] = title
    elif isinstance(title, dict):
        layout["title"].update(title)
    layout.update(overrides)
    return layout
