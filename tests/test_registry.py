"""Borehole registry: CSV round trip, district statistics, priors."""

from groundwater.registry import (
    REGISTRY_FIELDS,
    depth_prior_note,
    district_summary,
    parse_registry_csv,
    registry_csv_bytes,
)


def _rows():
    return [
        {"community": "Kuntolo", "district": "Bombali", "latitude": 8.9,
         "longitude": -12.1, "date": "2025-11-02", "total_depth_m": 55.0,
         "safe_yield_m3_per_h": 2.4, "quality_verdict": "Suitable",
         "price_usd": 9200.0, "contractor": "AquaDrill", "remarks": ""},
        {"community": "Masongbo", "district": "Bombali", "latitude": 8.85,
         "longitude": -12.05, "date": "2026-01-15", "total_depth_m": 61.0,
         "safe_yield_m3_per_h": 1.9, "quality_verdict": "Suitable",
         "price_usd": 10100.0, "contractor": "AquaDrill", "remarks": ""},
        {"community": "Rokel", "district": "Western Area Rural",
         "latitude": 8.38, "longitude": -13.1, "date": "2026-02-20",
         "total_depth_m": 75.0, "safe_yield_m3_per_h": None,
         "quality_verdict": "", "price_usd": None, "contractor": "",
         "remarks": "dry attempt"},
        {"community": "Makeni East", "district": "Bombali", "latitude": None,
         "longitude": None, "date": "", "total_depth_m": 58.0,
         "safe_yield_m3_per_h": 2.1, "quality_verdict": "Suitable",
         "price_usd": 9800.0, "contractor": "", "remarks": ""},
    ]


def test_csv_round_trip():
    rows = _rows()
    text = registry_csv_bytes(rows).decode("utf-8")
    back = parse_registry_csv(text)
    assert len(back) == len(rows)
    assert back[0]["community"] == "Kuntolo"
    assert back[0]["total_depth_m"] == 55.0
    assert back[2]["price_usd"] is None
    assert set(back[0]) == set(REGISTRY_FIELDS)


def test_parse_tolerates_unknown_and_blank_columns():
    text = (
        "community,district,total_depth_m,extra_column\n"
        "Kuntolo,Bombali,55,ignored\n"
        ",,,\n"
    )
    rows = parse_registry_csv(text)
    assert len(rows) == 1
    assert rows[0]["total_depth_m"] == 55.0
    assert "extra_column" not in rows[0]


def test_district_summary_medians():
    summary = district_summary(_rows())
    bombali = next(s for s in summary if s["District"] == "Bombali")
    assert bombali["Boreholes"] == 3
    assert bombali["Median depth (m)"] == 58.0
    assert bombali["Median price (USD)"] == 9800
    western = next(s for s in summary if s["District"] == "Western Area Rural")
    assert western["Median yield (m3/h)"] is None


def test_depth_prior_note():
    rows = _rows()
    # within half to one-and-a-half of the 58 m median: silent
    assert depth_prior_note(rows, "Bombali", 60.0) is None
    # far outside: cautioned
    note = depth_prior_note(rows, "Bombali", 150.0)
    assert note is not None and "Bombali" in note
    # too few records for a prior: silent
    assert depth_prior_note(rows, "Western Area Rural", 200.0) is None
    assert depth_prior_note(rows, "", 60.0) is None
