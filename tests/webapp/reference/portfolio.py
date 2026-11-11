"""The portfolio view: the "portfolio" and "portfolio_edited" entries of
``reference.json``.
"""

from __future__ import annotations

from groundwater.portfolio import (
    portfolio_points,
    portfolio_rows,
    portfolio_stats,
    site_detail,
    site_one_pager,
)

from .common import clean


def fill_portfolio(out: dict) -> None:
    """Fill "portfolio" and "portfolio_edited".

    It fills ``out`` in place, where build() calls it: build.py says why."""
    # The portfolio view, over summaries chosen to exercise every status class
    # and the zone-inference fallback.
    summaries = [
        {"community": "Rokel", "district": "Port Loko", "easting": 235000.0,
         "northing": 963000.0, "status": "sited"},
        {"community": "Dr. Timbo", "district": "Western Area Rural",
         "easting": 778000.0, "northing": 946000.0, "utm_zone": 28,
         "status": "Completed - successful", "total_depth_m": 45.0,
         "safe_yield_m3_per_h": 2.34, "water_verdict": "pass",
         "verdict_schema": 2, "cost_per_meter_usd": 133.0},
        {"community": "Kuntoloh", "district": "Western Area Rural",
         "status": "Completed - dry", "total_depth_m": 52.0,
         "water_verdict": "aesthetic", "cost_per_meter_usd": 151.0},
    ]
    out["portfolio"] = {
        "rows": clean(portfolio_rows(summaries)),
        "points": [[p["label"], clean(p["lat"]), clean(p["lon"]), p["status"]]
                   for p in portfolio_points(summaries)],
        "stats": clean(portfolio_stats(summaries)),
        "detail": [list(row) for row in site_detail(summaries[1])],
        "one_pager": site_one_pager(summaries[1]),
    }
    # summaries as hand-edited files hold them: numbers written as text the
    # two engines read alike, and texts neither reads ("52 m", "0x10", a
    # blank, an exponent past the largest number), which leave a cell blank
    # where the browser printed NaN
    edited = [
        {"community": "Rokel", "district": "Port Loko", "status": "Completed", "total_depth_m": "52 m",
         "safe_yield_m3_per_h": "1.2 m3/h", "cost_per_meter_usd": " 85 ", "easting": "235000",
         "northing": " 963000 ", "utm_zone": "28.0"},
        {"community": "Kuntoloh", "total_depth_m": "0x10", "safe_yield_m3_per_h": "  ",
         "cost_per_meter_usd": "1_000", "easting": 778000.0, "northing": "abc", "status": "Dry hole"},
        {"community": "Bo", "total_depth_m": "4.5e1", "safe_yield_m3_per_h": True, "cost_per_meter_usd": [],
         "status": "", "easting": 778000.0, "northing": 946000.0, "utm_zone": "Zone 28"},
        {"community": "Kenema", "total_depth_m": "1e999", "safe_yield_m3_per_h": "+.5", "cost_per_meter_usd": "5.",
         "status": "Successful"},
    ]
    out["portfolio_edited"] = {
        "summaries": edited,
        "rows": clean(portfolio_rows(edited)),
        "points": [[p["label"], clean(p["lat"]), clean(p["lon"]), p["status"]] for p in portfolio_points(edited)],
        "stats": clean(portfolio_stats(edited)),
        "details": [[list(row) for row in site_detail(s)] for s in edited],
        "one_pagers": [site_one_pager(s) for s in edited],
    }
