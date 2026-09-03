"""Aggregate many saved projects into a portfolio view.

A water manager oversees many boreholes, not one. Each saved project file
carries a small headline ``summary`` (site, status, yield, water verdict,
cost per metre); this module turns a list of those summaries into a
comparison table, a set of mapped points coloured by status, and portfolio
statistics. Pure and map-library-free, so it is unit-testable.
"""

from __future__ import annotations

import math
from .geo import infer_zone_for_sierra_leone, utm_to_geographic
from .quality.assess import VERDICT_LONG, VERDICT_ORDER, VERDICT_SHORT
from .site_status import (
    STATUS_COLORS,
    STATUS_LABELS,
    SiteStatus,
    classify_text,
    status_label,
)

__all__ = [
    "STATUS_COLORS",
    "STATUS_LABELS",
    "SiteStatus",
    "classify_status",
    "portfolio_rows",
    "portfolio_points",
    "portfolio_stats",
    "site_detail",
    "site_label",
    "site_one_pager",
    "verdict_state",
]

#: Verdict wire values written by the current code. Older project files
#: carry the three-value vocabulary and are translated on read; see
#: :func:`verdict_state`.
VERDICT_SCHEMA = 2

#: How a pre-schema project file's verdict is read now. "fail" was
#: unambiguously a health exceedance. "aesthetic" was written by code whose
#: aesthetic bucket also held national-standard exceedances, so it may be a
#: concealed compliance failure and must not be shown as merely a matter of
#: taste - it is read as unproven, which is the fail-closed reading.
_LEGACY_VERDICTS = {
    "fail": "health_fail",
    "aesthetic": "indeterminate",
    "pass": "pass",
}


def classify_status(summary: dict) -> str:
    """Normalise a project's free-text status into a portfolio class.

    Returns the plain wire string (``"successful"``, ``"dry"``, ...), not the
    :class:`SiteStatus` member. It compares equal to the member either way,
    and a plain string is what a saved project file, a map layer and a YAML
    dump can all carry - an enum member cannot be safe-dumped, and a caller
    who put one in a summary would only find that out at save time.

    An unrecognised status becomes ``"other"`` rather than anything positive.
    Substring matching used to read "incomplete" and "unproductive" as
    successes, which inflated every programme's reported success rate and
    painted failed holes green on the national map.
    """
    raw = str(summary.get("status") or "").strip()
    if not raw:
        found = (
            SiteStatus.SITED
            if summary.get("safe_yield_m3_per_h") or summary.get("total_depth_m")
            else SiteStatus.OTHER
        )
    else:
        found = classify_text(raw) or SiteStatus.OTHER
    return found.value


def verdict_state(summary: dict) -> tuple[str | None, bool]:
    """The water verdict held in a saved summary.

    Returns ``(state, from_legacy_file)``. ``state`` is ``None`` when the
    project carries no water quality result at all. ``from_legacy_file`` is
    True when the value had to be translated from the old three-value
    vocabulary, so the caller can say the reading is approximate.
    """
    raw = str(summary.get("water_verdict") or "").strip().lower()
    if not raw:
        return None, False
    schema = summary.get("verdict_schema")
    try:
        schema = int(schema or 0)
    except (TypeError, ValueError):
        schema = 0
    if schema >= VERDICT_SCHEMA:
        return (raw if raw in VERDICT_SHORT else None), False
    return _LEGACY_VERDICTS.get(raw), True


def _num(value):
    """A finite float, or None for anything that is not one.

    Summaries come out of project files people edit by hand; one
    ``total_depth_m: 52 m`` in one of forty files used to take the whole
    portfolio page down with a traceback that named no file. The browser
    app already reads such a value as blank, so the two now agree.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _latlon(summary: dict):
    easting = _num(summary.get("easting"))
    northing = _num(summary.get("northing"))
    if not easting or not northing:
        return None
    # same fallback as SiteMetadata.utm: a hard-coded zone dropped every
    # zone-less project 6 degrees off, into the Atlantic and off the map
    zone = int(_num(summary.get("utm_zone")) or 0) or infer_zone_for_sierra_leone(
        easting
    )
    try:
        return utm_to_geographic(easting, northing, zone)
    except Exception:  # noqa: BLE001 - a bad coordinate simply drops the point
        return None


def portfolio_rows(summaries: list[dict]) -> list[dict]:
    """Formatted comparison rows, one per project."""
    rows = []
    for s in summaries:
        depth = _num(s.get("total_depth_m"))
        yield_ = _num(s.get("safe_yield_m3_per_h"))
        cost = _num(s.get("cost_per_meter_usd"))
        state, legacy = verdict_state(s)
        water = VERDICT_SHORT.get(state, "") if state else ""
        if water and legacy:
            # An asterisk rather than a silent reinterpretation: the value was
            # translated from an older file and the reader should know.
            water += "*"
        rows.append(
            {
                "Community": s.get("community") or "(unnamed)",
                "District": s.get("district") or "",
                "Status": status_label(classify_status(s)),
                "Depth (m)": round(depth, 1) if depth else None,
                "Safe yield (m3/h)": round(yield_, 2) if yield_ else None,
                "Water": water,
                "Cost/m (USD)": round(cost, 0) if cost else None,
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


def site_label(summary: dict, index: int | None = None) -> str:
    """A short, human label for one site, e.g. "Rokel (Port Loko)".

    When ``index`` is given it is prefixed (``"1. Rokel (Port Loko)"``) so a
    selector stays unambiguous even if two sites share a community name.
    """
    community = summary.get("community") or "(unnamed site)"
    district = summary.get("district")
    label = f"{community} ({district})" if district else community
    return f"{index + 1}. {label}" if index is not None else label


def site_detail(summary: dict) -> list[tuple[str, str]]:
    """Formatted (field, value) detail rows for one site, present fields only.

    Pure and display-library-free: the app renders these as a table and the
    one-pager writes them as lines, so both stay consistent.
    """
    rows: list[tuple[str, str]] = []

    def add(label: str, value) -> None:
        if value not in (None, ""):
            rows.append((label, value))

    add("Community", summary.get("community"))
    add("District", summary.get("district"))
    add("Chiefdom", summary.get("chiefdom"))
    add("Status", status_label(classify_status(summary)))
    latlon = _latlon(summary)
    if latlon is not None:
        add("Location", f"{latlon[0]:.5f} N, {abs(latlon[1]):.5f} W")
    depth = _num(summary.get("total_depth_m"))
    add("Total depth", f"{depth:.1f} m" if depth else None)
    yield_ = _num(summary.get("safe_yield_m3_per_h"))
    add("Safe yield", f"{yield_:.2f} m3/h" if yield_ else None)
    state, legacy = verdict_state(summary)
    if state is not None:
        add(
            "Water quality",
            VERDICT_LONG[state]
            + (" (read from an older project file)" if legacy else ""),
        )
    cost = _num(summary.get("cost_per_meter_usd"))
    add("Cost per metre", f"${cost:.0f}" if cost else None)
    return rows


def site_one_pager(summary: dict) -> str:
    """A plain-text one-page site brief for download."""
    title = site_label(summary)
    header = f"SITE BRIEF - {title}"
    lines = [header, "=" * len(header), ""]
    for label, value in site_detail(summary):
        lines.append(f"{label + ':':16s}{value}")
    lines += ["", "Generated by the Groundwater Investigation Toolkit."]
    return "\n".join(lines)


def portfolio_stats(summaries: list[dict]) -> dict:
    """Headline portfolio statistics for the KPI tiles.

    There is deliberately no single "water pass rate". The old one counted
    an aesthetic exceedance as safe *and* carried national-standard
    failures inside the aesthetic bucket, so a portfolio breaching the
    national standard everywhere still showed 100% passing. Three rates
    replace it - compliant, failing and unproven - and they are reported
    separately precisely so nobody can read one of them as all three.
    """
    n = len(summaries)
    drilled = [s for s in summaries if s.get("total_depth_m")]
    # Count successes over the same population the rate divides by (drilled
    # holes), so success_rate can never exceed 100% - a summary classified
    # "successful" but carrying no depth is not a drilled hole.
    n_successful = sum(1 for s in drilled if classify_status(s) == SiteStatus.SUCCESSFUL)
    n_unrecognised = sum(
        1
        for s in summaries
        if s.get("status") and classify_status(s) == SiteStatus.OTHER
    )
    yields = [y for y in (_num(s.get("safe_yield_m3_per_h")) for s in summaries) if y]
    costs = [c for c in (_num(s.get("cost_per_meter_usd")) for s in summaries) if c]
    # values that were written but cannot be read as numbers; the page says
    # how many rather than pretending the means cover every project
    n_unreadable = sum(
        1
        for s in summaries
        for key in ("total_depth_m", "safe_yield_m3_per_h", "cost_per_meter_usd")
        if s.get(key) not in (None, "") and _num(s.get(key)) is None
    )

    counts = {state: 0 for state in VERDICT_ORDER}
    counts["unknown"] = 0
    assessed = 0
    for s in summaries:
        if not s.get("water_verdict"):
            continue
        assessed += 1
        state, _ = verdict_state(s)
        counts[state if state in counts else "unknown"] += 1

    def rate(total: int):
        return (total / assessed * 100.0) if assessed else None

    return {
        "n_projects": n,
        "n_drilled": len(drilled),
        "n_values_unreadable": n_unreadable,
        "n_successful": n_successful,
        "n_status_unrecognised": n_unrecognised,
        "success_rate": (n_successful / len(drilled) * 100.0) if drilled else None,
        "mean_safe_yield_m3_per_h": (sum(yields) / len(yields)) if yields else None,
        "mean_cost_per_meter_usd": (sum(costs) / len(costs)) if costs else None,
        "n_wq_assessed": assessed,
        "wq_counts": counts,
        # meets every health AND national limit; aesthetic reservations only
        "wq_compliant_rate": rate(counts["pass"] + counts["aesthetic"]),
        "wq_fail_rate": rate(counts["health_fail"] + counts["national_fail"]),
        "wq_unproven_rate": rate(counts["indeterminate"] + counts["unknown"]),
    }
