"""
AppTest smoke + interaction checks for the geographical map view.

Exercises the new interactive region and catchment maps (focus selectbox, mix
pie, ranking table) across topologies and mix groupings, plus the ETYS plain
fall-back, and confirms no view raises. Run:

    python -m pytest dashboard/tests/test_map_interactions.py -q
    # or, without pytest:
    python dashboard/tests/test_map_interactions.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# The app does `from lib import ...`; Streamlit puts the script dir on sys.path
# under `streamlit run`, but AppTest does not, so add dashboard/ here.
DASH = Path(__file__).resolve().parents[1]
if str(DASH) not in sys.path:
    sys.path.insert(0, str(DASH))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(DASH / "app.py")


def _fresh():
    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    at.sidebar.radio(key="view").set_value("Geographical map").run()
    return at


def _set(at, key, value):
    """Set a sidebar selectbox/radio by key if present, then rerun."""
    for w in (*at.sidebar.selectbox, *at.sidebar.radio):
        if w.key == key:
            w.set_value(value).run()
            return True
    return False


def test_region_map_all_topologies_and_groupings():
    at = _fresh()
    _set(at, "map_style", "NESO regions")
    for topo in ("zonal_17bus", "reduced_32bus", "etys_2000bus"):
        if not _set(at, "map_topo_region", topo):
            continue
        for grouping in ("Technology", "Carbon class", "Renewable"):
            _set(at, "mapmix_region", grouping)
            assert not at.exception, f"region {topo}/{grouping}: {at.exception}"
        # the ranking table renders as a dataframe element
        assert len(at.dataframe) >= 1, f"no ranking table for region {topo}"


def test_catchment_map_coarse_and_etys():
    at = _fresh()
    _set(at, "map_style", "Catchment areas")
    # Coarse topologies: interactive panel + ranking table.
    for topo in ("zonal_17bus", "reduced_32bus"):
        if not _set(at, "map_topo_catch", topo):
            continue
        assert not at.exception, f"catchment {topo}: {at.exception}"
        assert len(at.dataframe) >= 1, f"no ranking table for catchment {topo}"
    # ETYS: plain fall-back, must not raise.
    if _set(at, "map_topo_catch", "etys_2000bus"):
        assert not at.exception, f"etys catchment: {at.exception}"


def test_points_map_still_works():
    at = _fresh()
    _set(at, "map_style", "Points (per bus)")
    assert not at.exception, f"points: {at.exception}"


def test_heatmap_neso_has_no_gaps():
    """NESO calendar heatmap must render with the published gaps filled."""
    from lib import data as D
    filled, n_filled = D.load_neso_hourly_filled()
    assert len(filled) == 8760, f"expected 8760 hours, got {len(filled)}"
    assert int(filled.isna().sum()) == 0, "filled NESO series still has gaps"
    assert n_filled > 0, "expected some hours to have been filled"

    at = AppTest.from_file(APP, default_timeout=90)
    at.run()
    at.sidebar.radio(key="view").set_value("Calendar heatmap").run()
    for series in ("neso_actual", "reduced_32bus"):
        _set(at, "hm_key", series)
        for m in ("Intensity", "Difference vs NESO"):
            _set(at, "hm_mode", m)
            assert not at.exception, f"heatmap {series}/{m}: {at.exception}"


if __name__ == "__main__":
    test_region_map_all_topologies_and_groupings()
    test_catchment_map_coarse_and_etys()
    test_points_map_still_works()
    test_heatmap_neso_has_no_gaps()
    print("OK: all map + heatmap interaction checks passed")
