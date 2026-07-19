"""Existing water points near a site: parsing, distance and the
rehabilitate-or-drill decision.

The records below are a small synthetic fixture shaped like WPDx+ rows
(Socrata returns every value as a string); they are test data, not real
water points. They sit due north of Makeni at known distances so the
geometry is deterministic.
"""

import io
import json

import pytest

from groundwater.waterpoints import (
    ASSESS_REHAB,
    DRILL_NEW,
    VERIFY_NEED,
    WaterPointFetchError,
    fetch_water_points,
    functionality_summary,
    parse_wpdx_records,
    points_within,
    rehab_vs_drill,
    water_points_near,
)

BASE_LAT, BASE_LON = 8.8817, -12.0442  # Makeni


def _north(metres: float) -> float:
    """Latitude that many metres due north of the base point."""
    return BASE_LAT + metres / 111194.93  # 1 deg lat at R=6371 km


def _wp(row_id, metres, status, status_id, source, tech="", year="2012"):
    return {
        "row_id": row_id,
        "lat_deg": f"{_north(metres):.6f}",
        "lon_deg": f"{BASE_LON}",
        "status_clean": status,
        "status_id": status_id,
        "water_source_clean": source,
        "water_tech_clean": tech,
        "install_year": year,
        "clean_adm2": "Bombali",
    }


# a working borehole 150 m away (inside the 500 m service radius)
P_WORKING_CLOSE = _wp("wp-1", 150, "Functional", "Yes", "Borehole",
                      "Hand Pump - India Mark II")
# a broken borehole 300 m away - a rehabilitation candidate
P_BROKEN = _wp("wp-2", 300, "Non-Functional", "No", "Borehole",
               "Hand Pump - Kardia", "2009")
# a working borehole 800 m away (beyond the service radius)
P_WORKING_FAR = _wp("wp-3", 800, "Functional", "Yes", "Borehole")
# an unknown-status protected well 600 m away
P_UNKNOWN = _wp("wp-4", 600, "", "Unknown", "Protected Shallow Well",
                "Rope Pump")
# a working point 5 km away (outside the 1 km search radius)
P_OUTSIDE = _wp("wp-5", 5000, "Functional", "Yes", "Borehole")
# a broken *surface water* point 250 m away - improved? no, so not a
# rehabilitation alternative to a borehole
P_SURFACE = _wp("wp-7", 250, "Non-Functional", "No", "Surface Water")
# malformed row with no coordinates - must be skipped, not crash
P_BAD = {"row_id": "wp-bad", "status_clean": "Functional"}

FULL = [P_WORKING_CLOSE, P_BROKEN, P_WORKING_FAR, P_UNKNOWN, P_OUTSIDE,
        P_SURFACE, P_BAD]


def test_parse_is_tolerant():
    points = parse_wpdx_records(FULL)
    assert len(points) == 6  # the coordinate-less bad row is dropped
    by_id = {p.row_id: p for p in points}
    assert by_id["wp-1"].functional is True
    assert by_id["wp-2"].functional is False
    assert by_id["wp-4"].functional is None  # unknown stays unknown
    # improved-source classification
    assert by_id["wp-1"].improved is True   # borehole
    assert by_id["wp-7"].improved is False  # surface water


def test_functional_from_needs_repair_and_abandoned():
    pts = parse_wpdx_records([
        _wp("a", 10, "Functional, needs repair", "", "Borehole"),
        _wp("b", 10, "Abandoned", "", "Borehole"),
    ])
    assert pts[0].functional is True   # still delivers water
    assert pts[1].functional is False


def test_functional_from_does_not_match_functionality_word():
    # "functionality" must not read as functional; status stays unknown
    pts = parse_wpdx_records([
        _wp("a", 10, "Unknown functionality", "", "Borehole"),
        _wp("b", 10, "functionality not reported", "", "Borehole"),
    ])
    assert pts[0].functional is None
    assert pts[1].functional is None


def test_functional_from_status_id_fallback():
    # no status text: fall back to the status_id "Yes"/"No" flag
    pts = parse_wpdx_records([
        _wp("a", 10, "", "Yes", "Borehole"),
        _wp("b", 10, "", "No", "Borehole"),
        _wp("c", 10, "", "Unknown", "Borehole"),
    ])
    assert [p.functional for p in pts] == [True, False, None]


def test_protected_spring_is_improved_but_unprotected_is_not():
    # "Protected Spring" contains "protected"; must not be mislabelled by the
    # "unprotected"/surface keywords (regression: bug flipped verify->drill).
    pts = parse_wpdx_records([
        _wp("a", 10, "Functional", "Yes", "Protected Spring"),
        _wp("b", 10, "Functional", "Yes", "Unprotected Spring"),
        _wp("c", 10, "Functional", "Yes", "Surface Water"),
    ])
    assert pts[0].improved is True
    assert pts[1].improved is False
    assert pts[2].improved is False


def test_working_protected_spring_in_service_radius_verifies_need():
    spring = _wp("sp", 200, "Functional", "Yes", "Protected Spring")
    near = points_within(parse_wpdx_records([spring]), BASE_LAT, BASE_LON, 1000.0)
    decision = rehab_vs_drill(near, BASE_LAT, BASE_LON)
    assert decision["recommendation"] == VERIFY_NEED


def test_drill_new_note_correct_for_unimproved_source_within_radius():
    # a functional but unimproved source 100 m away: DRILL_NEW, and the note
    # must not falsely claim it is "beyond the service radius".
    surface = _wp("sw", 100, "Functional", "Yes", "Surface Water")
    near = points_within(parse_wpdx_records([surface]), BASE_LAT, BASE_LON, 1000.0)
    decision = rehab_vs_drill(near, BASE_LAT, BASE_LON)
    assert decision["recommendation"] == DRILL_NEW
    assert "beyond" not in decision["headline"]
    assert "not an improved source" in decision["headline"]


def test_radius_boundaries_are_inclusive():
    # a point exactly at the radius counts as within it (the code uses <=).
    # use the point's own computed distance as the radius, so the boundary is
    # exact regardless of coordinate rounding.
    parsed = parse_wpdx_records([_wp("svc", 480, "Functional", "Yes", "Borehole")])
    d = points_within(parsed, BASE_LAT, BASE_LON, 10000.0)[0].distance_m
    assert len(points_within(parsed, BASE_LAT, BASE_LON, d)) == 1  # search <= is inclusive
    # a working improved source exactly at the service radius counts as serving
    near = points_within(parsed, BASE_LAT, BASE_LON, 10000.0)
    decision = rehab_vs_drill(near, BASE_LAT, BASE_LON, search_radius_m=10000.0,
                              service_radius_m=d)
    assert decision["recommendation"] == VERIFY_NEED


def test_points_within_filters_and_sorts():
    near = points_within(parse_wpdx_records(FULL), BASE_LAT, BASE_LON, 1000.0)
    ids = [p.row_id for p in near]
    assert "wp-5" not in ids  # 5 km away, excluded
    assert ids == ["wp-1", "wp-7", "wp-2", "wp-4", "wp-3"]  # nearest first
    assert near[0].distance_m < near[-1].distance_m


def test_functionality_summary_counts():
    near = points_within(parse_wpdx_records(FULL), BASE_LAT, BASE_LON, 1000.0)
    s = functionality_summary(near)
    assert s["total"] == 5
    assert s["functional"] == 2  # wp-1, wp-3
    assert s["non_functional"] == 2  # wp-2, wp-7
    assert s["unknown"] == 1  # wp-4
    assert s["functional_rate"] == 50.0  # 2 of 4 reported


def test_recommend_verify_need_when_working_source_serves_site():
    near = points_within(parse_wpdx_records(FULL), BASE_LAT, BASE_LON, 1000.0)
    decision = rehab_vs_drill(near, BASE_LAT, BASE_LON)
    assert decision["recommendation"] == VERIFY_NEED
    assert "150" in decision["headline"]


def test_recommend_assess_rehab_when_only_broken_improved_nearby():
    # drop the close working source; the broken borehole should now surface
    records = [P_BROKEN, P_WORKING_FAR, P_UNKNOWN, P_SURFACE]
    near = points_within(parse_wpdx_records(records), BASE_LAT, BASE_LON, 1000.0)
    decision = rehab_vs_drill(near, BASE_LAT, BASE_LON)
    assert decision["recommendation"] == ASSESS_REHAB
    assert decision["rehab_candidates"][0]["Source"] == "Borehole"
    # the broken *surface water* point is not offered as a rehab candidate
    assert all(c["Source"] != "Surface Water"
               for c in decision["rehab_candidates"])


def test_recommend_drill_new_when_nothing_nearby():
    decision = rehab_vs_drill([], BASE_LAT, BASE_LON)
    assert decision["recommendation"] == DRILL_NEW
    assert decision["n_nearby"] == 0


def test_recommend_drill_new_when_working_source_beyond_service_radius():
    near = points_within(parse_wpdx_records([P_WORKING_FAR]),
                         BASE_LAT, BASE_LON, 1000.0)
    decision = rehab_vs_drill(near, BASE_LAT, BASE_LON)
    assert decision["recommendation"] == DRILL_NEW
    assert "800" in decision["headline"]  # notes the nearest working source


# --- the guarded network client, exercised offline via an injected opener ---

class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def test_fetch_wraps_network_errors():
    def boom(request, timeout=None):
        raise OSError("network is unreachable")

    with pytest.raises(WaterPointFetchError):
        fetch_water_points(BASE_LAT, BASE_LON, urlopen=boom)


def test_fetch_returns_records_via_injected_opener():
    def opener(request, timeout=None):
        # the bbox query is on lat_deg/lon_deg, not a geo column
        assert "lat_deg" in request.full_url and "lon_deg" in request.full_url
        return _FakeResponse(json.dumps([P_WORKING_CLOSE, P_BROKEN]).encode())

    records = fetch_water_points(BASE_LAT, BASE_LON, urlopen=opener)
    assert len(records) == 2


def test_water_points_near_end_to_end_offline():
    def opener(request, timeout=None):
        return _FakeResponse(json.dumps(FULL).encode())

    points = water_points_near(BASE_LAT, BASE_LON, 1000.0, urlopen=opener)
    assert [p.row_id for p in points] == ["wp-1", "wp-7", "wp-2", "wp-4", "wp-3"]


def test_fetch_rejects_non_list_payload():
    def opener(request, timeout=None):
        return _FakeResponse(json.dumps({"error": "nope"}).encode())

    with pytest.raises(WaterPointFetchError):
        fetch_water_points(BASE_LAT, BASE_LON, urlopen=opener)
