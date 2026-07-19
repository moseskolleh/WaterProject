"""Aggregate many saved projects into a portfolio view.

A water manager oversees many boreholes, not one. Each saved project file
carries a small headline ``summary`` (site, status, yield, water verdict,
cost per metre); this module turns a list of those summaries into a
comparison table, a set of mapped points coloured by status, and portfolio
statistics. Pure and map-library-free, so it is unit-testable.
"""

from __future__ import annotations

from .geo import utm_to_geographic

# status classes and their map colours (red = problem, green = good)
STATUS_COLORS = {
    "successful": "#2E7D5B",
    "dry": "#B23A2E",
    "sited": "#17527E",
    "other": "#C1772A",
}
STATUS_LABELS = {
    "successful": "Successful",
    "dry": "Dry / failed",
    "sited": "Sited (not drilled)",
    "other": "Other / in progress",
}


def classify_status(summary: dict) -> str:
    """Normalise a project's free-text status into a portfolio class."""
    raw = str(summary.get("status") or "").strip().lower()
    if not raw:
        return "sited" if summary.get("safe_yield_m3_per_h") or summary.get(
            "total_depth_m"
        ) else "other"
    if "success" in raw or "complete" in raw or "productive" in raw:
        return "successful"
    if "dry" in raw or "fail" in raw or "abandon" in raw or "unsuccess" in raw:
        return "dry"
    if "sit" in raw:  # "sited", "siting"
        return "sited"
    return "other"


def _latlon(summary: dict):
    easting = summary.get("easting")
    northing = summary.get("northing")
    if not easting or not northing:
        return None
    zone = int(summary.get("utm_zone") or 29)
    try:
        return utm_to_geographic(float(easting), float(northing), zone)
    except Exception:  # noqa: BLE001 - a bad coordinate simply drops the point
        return None


def portfolio_rows(summaries: list[dict]) -> list[dict]:
    """Formatted comparison rows, one per project."""
    rows = []
    for s in summaries:
        status = classify_status(s)
        yield_ = s.get("safe_yield_m3_per_h")
        cost = s.get("cost_per_meter_usd")
        verdict = str(s.get("water_verdict") or "").lower()
        rows.append(
            {
                "Community": s.get("community") or "(unnamed)",
                "District": s.get("district") or "",
                "Status": STATUS_LABELS[status],
                "Depth (m)": round(float(s["total_depth_m"]), 1)
                if s.get("total_depth_m") else None,
                "Safe yield (m3/h)": round(float(yield_), 2) if yield_ else None,
                "Water": {"fail": "Treat before use", "aesthetic": "Aesthetic only",
                          "pass": "Safe"}.get(verdict, ""),
                "Cost/m (USD)": round(float(cost), 0) if cost else None,
            }
        )
    return rows


def portfolio_points(summaries: list[dict]) -> list[dict]:
    """Mapped points ``{label, lat, lon, status}`` for projects with coordinates."""
    points = []
    for s in summaries:
        latlon = _latlon(s)
        if latlon is None:
            continue
        points.append(
            {
                "label": s.get("community") or "site",
                "lat": latlon[0],
                "lon": latlon[1],
                "status": classify_status(s),
            }
        )
    return points


def portfolio_stats(summaries: list[dict]) -> dict:
    """Headline portfolio statistics for the KPI tiles."""
    n = len(summaries)
    statuses = [classify_status(s) for s in summaries]
    drilled = [s for s in summaries if s.get("total_depth_m")]
    n_successful = statuses.count("successful")
    yields = [float(s["safe_yield_m3_per_h"]) for s in summaries
              if s.get("safe_yield_m3_per_h")]
    costs = [float(s["cost_per_meter_usd"]) for s in summaries
             if s.get("cost_per_meter_usd")]
    verdicts = [str(s.get("water_verdict") or "").lower() for s in summaries
                if s.get("water_verdict")]
    wq_safe = sum(1 for v in verdicts if v in ("pass", "aesthetic"))
    return {
        "n_projects": n,
        "n_drilled": len(drilled),
        "n_successful": n_successful,
        "success_rate": (n_successful / len(drilled) * 100.0) if drilled else None,
        "mean_safe_yield_m3_per_h": (sum(yields) / len(yields)) if yields else None,
        "mean_cost_per_meter_usd": (sum(costs) / len(costs)) if costs else None,
        "wq_pass_rate": (wq_safe / len(verdicts) * 100.0) if verdicts else None,
    }
