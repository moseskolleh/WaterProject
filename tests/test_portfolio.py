"""Portfolio aggregation across many saved projects."""

from groundwater.mapping import plot_portfolio_map
from groundwater.portfolio import (
    classify_status,
    portfolio_points,
    portfolio_rows,
    portfolio_stats,
    site_detail,
    site_label,
    site_one_pager,
)

_SUMMARIES = [
    {
        "community": "Rokel", "district": "Port Loko",
        "easting": 694667.0, "northing": 936225.0, "utm_zone": 28,
        "status": "Successful", "total_depth_m": 50.0,
        "safe_yield_m3_per_h": 2.4, "water_verdict": "pass",
        "cost_per_meter_usd": 130.0,
    },
    {
        "community": "Kuntolo", "district": "Tonkolili",
        "easting": 800000.0, "northing": 950000.0, "utm_zone": 28,
        "status": "Dry hole", "total_depth_m": 45.0,
    },
    {
        "community": "Dr Timbo", "district": "Bombali",
        "easting": 825127.0, "northing": 983069.0, "utm_zone": 28,
        "status": "sited", "safe_yield_m3_per_h": 1.0,
    },
]


def test_classify_status():
    assert classify_status({"status": "Successful"}) == "successful"
    assert classify_status({"status": "Dry hole"}) == "dry"
    assert classify_status({"status": "sited"}) == "sited"
    assert classify_status({"status": "", "total_depth_m": 40}) == "sited"
    assert classify_status({}) == "other"


def test_portfolio_rows():
    rows = portfolio_rows(_SUMMARIES)
    assert len(rows) == 3
    rokel = rows[0]
    assert rokel["Community"] == "Rokel" and rokel["Status"] == "Successful"
    assert rokel["Water"] == "Safe" and rokel["Cost/m (USD)"] == 130


def test_portfolio_points_have_coordinates():
    points = portfolio_points(_SUMMARIES)
    assert len(points) == 3
    statuses = {p["status"] for p in points}
    assert statuses == {"successful", "dry", "sited"}
    # coordinates are in Sierra Leone's rough lat/lon window
    for p in points:
        assert 6.5 < p["lat"] < 10.5 and -13.5 < p["lon"] < -10.0


def test_portfolio_stats():
    stats = portfolio_stats(_SUMMARIES)
    assert stats["n_projects"] == 3
    assert stats["n_drilled"] == 2  # Rokel + Kuntolo have a depth
    assert stats["n_successful"] == 1
    assert stats["success_rate"] == 50.0  # 1 of 2 drilled
    assert stats["wq_pass_rate"] == 100.0  # the one tested source is safe
    assert abs(stats["mean_cost_per_meter_usd"] - 130.0) < 1e-6


def test_portfolio_map_renders(tmp_path):
    out = plot_portfolio_map(portfolio_points(_SUMMARIES), path=tmp_path / "portfolio.png")
    assert out.exists() and out.stat().st_size > 0


def test_points_without_coordinates_are_dropped():
    assert portfolio_points([{"community": "No GPS", "status": "sited"}]) == []


def test_site_label():
    assert site_label(_SUMMARIES[0]) == "Rokel (Port Loko)"
    assert site_label({"community": "Foo"}) == "Foo"
    assert site_label({}) == "(unnamed site)"
    # an index prefix keeps otherwise-identical labels unambiguous
    assert site_label(_SUMMARIES[0], index=2) == "3. Rokel (Port Loko)"


def test_site_detail_present_fields_only():
    detail = dict(site_detail(_SUMMARIES[0]))
    assert detail["Community"] == "Rokel"
    assert detail["District"] == "Port Loko"
    assert detail["Status"] == "Successful"
    assert detail["Total depth"] == "50.0 m"
    assert detail["Safe yield"] == "2.40 m3/h"
    assert detail["Water quality"] == "Safe to drink"
    assert detail["Cost per metre"] == "$130"
    assert "N," in detail["Location"] and "W" in detail["Location"]
    # a sparse site omits absent fields rather than showing blanks
    sparse = dict(site_detail({"community": "No GPS", "status": "sited"}))
    assert set(sparse) == {"Community", "Status"}
    assert "Location" not in sparse


def test_site_detail_shows_location_from_utm():
    # a UTM-only summary still gets a Location, shown as converted lat/lon
    detail = dict(site_detail({"community": "X", "easting": 700000.0,
                               "northing": 950000.0, "utm_zone": 28}))
    assert "N," in detail["Location"] and detail["Location"].endswith("W")


def test_site_one_pager_contains_key_facts():
    text = site_one_pager(_SUMMARIES[0])
    assert text.startswith("SITE BRIEF - Rokel (Port Loko)")
    assert "Safe yield:" in text
    assert "2.40 m3/h" in text
    assert "Cost per metre:" in text
