"""Transparent drill-target suitability scorecard.

Each candidate VES point is scored 0-100 from four components a siting
hydrogeologist weighs in crystalline basement terrain:

* aquifer thickness   - total interpreted water-bearing thickness,
* resistivity fit     - how central the water-zone resistivity sits in the
                        productive fractured/weathered window (too high is
                        dry/fresh rock, too low is clay or, on the coast,
                        saline),
* overburden          - a favourable weathered profile (not too thin to
                        store water, not so deep that basement is out of
                        reach),
* basal fracture      - a water zone at or just above the weathered/fresh
                        basement contact, the prime basement target.

The weights are explicit and configurable. They are a defensible default,
not a calibrated model; the intended upgrade path is to fit them against
real drilling outcomes as a programme accumulates them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import VESConfig
from ..ves.interpret import SiteInterpretation

# component weights (must sum to 1.0)
_WEIGHTS = {
    "aquifer_thickness": 0.35,
    "resistivity_fit": 0.25,
    "overburden": 0.20,
    "basal_fracture": 0.20,
}
_THICKNESS_TARGET_M = 25.0  # aquifer thickness scoring saturates here


@dataclass
class SuitabilityComponents:
    """The four normalised (0-1) component scores behind a suitability."""

    aquifer_thickness: float
    resistivity_fit: float
    overburden: float
    basal_fracture: float


@dataclass
class SitingSuitability:
    sounding_id: str
    suitability: float  # 0-100
    grade: str  # Poor / Moderate / Good / Very good
    components: SuitabilityComponents
    rationale: str
    easting: float | None = None
    northing: float | None = None
    rank: int | None = None


def _grade(score: float) -> str:
    if score >= 75:
        return "Very good"
    if score >= 55:
        return "Good"
    if score >= 35:
        return "Moderate"
    return "Poor"


def _thickness_score(interp: SiteInterpretation) -> float:
    return min(interp.aquifer_thickness_m / _THICKNESS_TARGET_M, 1.0)


def _zone_geomean_rho(interp: SiteInterpretation) -> float | None:
    """Thickness-weighted geometric mean resistivity across the water zones."""
    acc = 0.0
    total = 0.0
    for top, bottom in interp.water_zones:
        for layer in interp.layers:
            lo = max(layer.top_m, top)
            hi = min(
                layer.bottom_m if math.isfinite(layer.bottom_m) else bottom, bottom
            )
            if hi > lo:
                acc += math.log(layer.rho) * (hi - lo)
                total += hi - lo
    return math.exp(acc / total) if total > 0 else None


def _resistivity_fit_score(interp: SiteInterpretation, config: VESConfig) -> float:
    mid = _zone_geomean_rho(interp)
    if mid is None:
        return 0.0
    lo, hi = config.fractured_zone_rho
    centre = math.sqrt(lo * hi)
    return 1.0 / (1.0 + abs(math.log(max(mid, 1e-3) / centre)))


def _overburden_score(interp: SiteInterpretation) -> float:
    dtb = interp.depth_to_basement_m
    if dtb is None:
        return 0.5  # unknown: neutral
    if dtb < 5:
        return 0.15  # too thin to store much water
    if dtb <= 35:
        return 1.0  # favourable weathered profile
    # deep overburden is still drillable but basement/target sits deeper
    return max(0.4, 1.0 - (dtb - 35) / 60.0)


def _basal_fracture_score(interp: SiteInterpretation) -> float:
    zones = interp.water_zones
    if not zones:
        return 0.0
    dtb = interp.depth_to_basement_m
    if dtb is not None:
        for top, bottom in zones:
            # a zone straddling or just above the fresh-basement contact is
            # the highest-yield basement target
            if top <= dtb <= bottom or abs(bottom - dtb) <= 5.0:
                return 1.0
    return 0.5


def _rationale(interp: SiteInterpretation, comp: SuitabilityComponents) -> str:
    if not interp.water_zones:
        return (
            "No water-bearing zone was resolved within the investigated depth, "
            "so the drilling prospect here is weak."
        )
    parts = []
    thick = interp.aquifer_thickness_m
    parts.append(
        f"about {thick:.0f} m of interpreted water-bearing thickness"
        + (" (thick)" if comp.aquifer_thickness >= 0.7 else
           " (modest)" if comp.aquifer_thickness >= 0.4 else " (thin)")
    )
    if comp.resistivity_fit >= 0.6:
        parts.append("resistivities well within the productive fracture window")
    elif comp.resistivity_fit >= 0.35:
        parts.append("resistivities near the edge of the productive window")
    else:
        parts.append("resistivities outside the ideal productive window")
    if comp.basal_fracture >= 1.0:
        parts.append("a fractured zone at the basement contact")
    if interp.depth_to_basement_m is not None and comp.overburden < 0.4:
        parts.append(
            f"overburden of about {interp.depth_to_basement_m:.0f} m that limits the target"
        )
    return "Driven by " + "; ".join(parts) + "."


def assess_siting(
    interpretations: list[SiteInterpretation],
    config: VESConfig | None = None,
) -> list[SitingSuitability]:
    """Score and rank candidate VES points by drilling suitability.

    Returns the results ranked most suitable first (rank 1 = best), so the
    first entry is the recommended drilling target.
    """
    config = config or VESConfig()
    results: list[SitingSuitability] = []
    for interp in interpretations:
        comp = SuitabilityComponents(
            aquifer_thickness=_thickness_score(interp),
            resistivity_fit=_resistivity_fit_score(interp, config),
            overburden=_overburden_score(interp),
            basal_fracture=_basal_fracture_score(interp),
        )
        score = 100.0 * (
            _WEIGHTS["aquifer_thickness"] * comp.aquifer_thickness
            + _WEIGHTS["resistivity_fit"] * comp.resistivity_fit
            + _WEIGHTS["overburden"] * comp.overburden
            + _WEIGHTS["basal_fracture"] * comp.basal_fracture
        )
        results.append(
            SitingSuitability(
                sounding_id=interp.sounding_id,
                suitability=round(score, 1),
                grade=_grade(score),
                components=comp,
                rationale=_rationale(interp, comp),
                easting=interp.site_easting,
                northing=interp.site_northing,
            )
        )
    # rank: highest suitability first, ties broken by sounding id for stability
    ranked = sorted(results, key=lambda r: (-r.suitability, r.sounding_id))
    for rank, result in enumerate(ranked, start=1):
        result.rank = rank
    return ranked


def suitability_map_points(results: list[SitingSuitability]):
    """Build MapPoints (value = suitability) for the drill-target map.

    Only points that carry coordinates are returned.
    """
    from ..mapping.maps import MapPoint

    points = []
    for r in results:
        if r.easting is None or r.northing is None:
            continue
        points.append(
            MapPoint(
                label=f"{r.sounding_id}",
                easting=float(r.easting),
                northing=float(r.northing),
                value=r.suitability,
                kind=r.grade,
            )
        )
    return points
