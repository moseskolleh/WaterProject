"""Portfolio aggregation across many saved projects."""

from groundwater.mapping import plot_portfolio_map
from groundwater.portfolio import (
    classify_status,
    portfolio_points,
    portfolio_rows,
    portfolio_stats,
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
