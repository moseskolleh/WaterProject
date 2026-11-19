"""Whole numbers too large for a float, as a hand-edited project file can
hold them: the "too_large" entry of ``reference.json``.
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


def too_large_reference() -> dict:
    """Whole numbers too large for a float, as a hand-edited project file
    can hold them: YAML reads 400 digits as a whole number Python's float()
    cannot hold, and the browser's reader as Infinity. Python raised
    OverflowError on each of these where the browser left a blank; each is
    blank in both now. The file is carried as text, which both engines
    read, since the reference's own JSON cannot hold such a number in a
    way --check could compare. A summary's verdict schema is read as its
    other numbers are, so ".inf" (which Python's int() raised on) and such a
    number both read as no schema, and "2.0" as schema 2 in both. A
    calibration set file holding such a number is refused in the same words
    by both."""
    import re

    import yaml

    from groundwater import calibration_sets as CS
    from groundwater import ledger as L
    from groundwater import scorecards as SC
    from groundwater.photos import describe_provenance

    big = int("9" * 400)
    base = {"sha256": "ab" * 32, "taken_at": "2026-10-03T09:00:00Z", "time_source": "exif",
            "position_source": "exif", "position_note": "refused"}
    held = {
        "photos": [dict(base, position={"lat": big, "lon": -12.1}),
                   dict(base, position={"lat": 8.5, "lon": -big}),
                   dict(base, position={"lat": 8.5, "lon": -12.1, "accuracy_m": big})],
        "summaries": [{"community": "Rokel", "district": "Port Loko", "status": "Successful", "total_depth_m": big,
                       "safe_yield_m3_per_h": -big, "cost_per_meter_usd": big, "easting": big,
                       "northing": 936225.0, "utm_zone": big},
                      {"community": "Kenema", "total_depth_m": 45.0, "easting": 694667.0, "northing": 936225.0,
                       "utm_zone": big, "status": "Dry hole"},
                      {"community": "Bo", "water_verdict": "aesthetic", "verdict_schema": float("inf")},
                      {"community": "Kono", "water_verdict": "aesthetic", "verdict_schema": big},
                      {"community": "Kambia", "water_verdict": "aesthetic", "verdict_schema": "2.0"},
                      {"community": "Bonthe", "water_verdict": "aesthetic", "verdict_schema": -float("inf")}],
        "ledger": {"drilled": None, "project_id": "0a1b2c3d4e5f", "entries": [
            {"id": "a1", "point": {"sounding_id": "VES 1", "easting": big, "northing": 926355.5, "utm_zone": big},
             "prediction": {"depth_to_basement_m": big, "layers": [[0, big, 100], [5, 9, 40]],
                            "odds": {"probability": 0.5, "effective_n": big}},
             "before_outcome": True, "recorded_on": "2026-10-01",
             "outcome": {"total_depth_m": big, "water_strikes_m": [big, 12], "success": True,
                         "success_basis": "recorded_success", "utm_zone": big},
             "pairing": {"how": "only", "distance_m": big}}]},
        "works": {"id": "w1", "drilled": True, "contract": True, "variations_signed": big, "variations_unsigned": 0,
                  "variation_usd": 1.0, "logged_m": big, "claimed_m": 70.0, "forecast": big,
                  "checklist": {"drilling": {"answered": big, "failed": []}}},
    }
    text = yaml.safe_dump(held, sort_keys=False)
    file = yaml.safe_load(text)
    summaries = file["summaries"]
    plain = CS.set_yaml(CS.default_set())
    sets = []
    for key in ("boreholes", "success_yield_m3_per_h", "unknown"):
        bad = re.sub(rf"(\n *{key}: )\S+", lambda m: m.group(1) + "9" * 400, plain, count=1)
        assert bad != plain
        try:
            CS.read_set(bad)
        except ValueError as exc:
            sets.append({"yaml": bad, "refused": str(exc)})
        else:
            raise AssertionError(f"a set with {key} of 400 digits was read")
    return {
        "yaml": text,
        "sets": sets,
        "photos": [describe_provenance(r) for r in file["photos"]],
        "rows": clean(portfolio_rows(summaries)),
        "points": [[p["label"], clean(p["lat"]), clean(p["lon"]), p["status"]] for p in portfolio_points(summaries)],
        "stats": clean(portfolio_stats(summaries)),
        "details": [[list(row) for row in site_detail(s)] for s in summaries],
        "one_pagers": [site_one_pager(s) for s in summaries],
        "ledger": L.clean_ledger(file["ledger"]),
        "works": SC.clean_works(file["works"]),
    }
