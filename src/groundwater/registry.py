"""Borehole registry: institutional memory across completed projects.

A registry is a plain CSV of completed (or attempted) boreholes -
site, coordinates, depth, yield, quality verdict and price. It
accumulates across projects, giving a programme manager district
statistics (typical depth, price, yield), a map of the portfolio and
a sanity check for new sitings against what the district has actually
needed before.
"""

from __future__ import annotations

import csv
import io
from statistics import median

REGISTRY_FIELDS = [
    "community",
    "district",
    "latitude",
    "longitude",
    "date",
    "total_depth_m",
    "safe_yield_m3_per_h",
    "quality_verdict",
    "price_usd",
    "contractor",
    "remarks",
]

_NUMERIC_FIELDS = {
    "latitude", "longitude", "total_depth_m",
    "safe_yield_m3_per_h", "price_usd",
}


def _float(value) -> float | None:
    try:
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def registry_csv_bytes(rows: list[dict]) -> bytes:
    """Serialize registry rows to CSV in the canonical column order."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=REGISTRY_FIELDS,
                            extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if row.get(k) is None else row.get(k, ""))
                         for k in REGISTRY_FIELDS})
    return buf.getvalue().encode("utf-8")


def parse_registry_csv(text: str) -> list[dict]:
    """Registry rows from CSV text; unknown columns are dropped and
    numbers are parsed where the column is numeric."""
    rows: list[dict] = []
    for raw in csv.DictReader(io.StringIO(text)):
        row: dict = {}
        for field in REGISTRY_FIELDS:
            value = (raw.get(field) or "").strip()
            row[field] = _float(value) if field in _NUMERIC_FIELDS else value
        if any(v not in ("", None) for v in row.values()):
            rows.append(row)
    return rows


def district_summary(rows: list[dict]) -> list[dict]:
    """Per-district medians: boreholes, depth, price, yield."""
    by_district: dict[str, list[dict]] = {}
    for row in rows:
        district = str(row.get("district") or "").strip()
        if district:
            by_district.setdefault(district, []).append(row)

    def _median_of(items: list[dict], field: str) -> float | None:
        values = [v for v in (_float(i.get(field)) for i in items)
                  if v is not None]
        return median(values) if values else None

    summary = []
    for district in sorted(by_district):
        items = by_district[district]
        depth = _median_of(items, "total_depth_m")
        price = _median_of(items, "price_usd")
        yield_ = _median_of(items, "safe_yield_m3_per_h")
        summary.append({
            "District": district,
            "Boreholes": len(items),
            "Median depth (m)": round(depth, 1) if depth is not None else None,
            "Median price (USD)": round(price) if price is not None else None,
            "Median yield (m3/h)": round(yield_, 2) if yield_ is not None else None,
        })
    return summary


def depth_prior_note(
    rows: list[dict], district: str, planned_depth_m: float,
    min_records: int = 3,
) -> str | None:
    """A caution when the planned depth is far off the district's record.

    Returns None when the registry holds fewer than ``min_records``
    depths for the district or the planned depth sits within half to
    one-and-a-half times the district median.
    """
    district = (district or "").strip()
    if not district or not planned_depth_m:
        return None
    depths = [
        v for v in (
            _float(r.get("total_depth_m")) for r in rows
            if str(r.get("district") or "").strip().lower() == district.lower()
        )
        if v is not None and v > 0
    ]
    if len(depths) < min_records:
        return None
    typical = median(depths)
    if 0.5 * typical <= planned_depth_m <= 1.5 * typical:
        return None
    return (
        f"The planned depth ({planned_depth_m:g} m) is far from the "
        f"{typical:g} m median of {len(depths)} registered borehole(s) "
        f"in {district} District - worth double checking the siting."
    )
