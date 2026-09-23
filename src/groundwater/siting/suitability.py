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
    suitability: float  # 0-100, the geological score
    grade: str  # Poor / Moderate / Good / Very good
    components: SuitabilityComponents
    rationale: str
    easting: float | None = None
    northing: float | None = None
    rank: int | None = None
    #: 0-1: how far the model fit and an unresolved basement discount the
    #: score. The points are ranked on suitability x confidence, so a point
    #: whose curve was fitted to 27 percent does not outrank one fitted to
    #: 13 percent on a few ohm-m of half-space resistivity.
    confidence: float = 1.0

    @property
    def weighted(self) -> float:
        """The number the ranking is decided on."""
        return self.suitability * self.confidence


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
    open_ended = getattr(interp, "basement_not_resolved", False)
    parts.append(
        (f"at least {thick:.0f} m of interpreted water-bearing thickness, the "
         "base of the zone being below the depth the sounding resolves"
         if open_ended else
         f"about {thick:.0f} m of interpreted water-bearing thickness")
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
    text = "Driven by " + "; ".join(parts) + "."
    confidence = getattr(interp, "confidence", 1.0)
    if confidence < 1.0:
        reasons = []
        err = getattr(interp, "fit_error_percent", None)
        if getattr(interp, "fit_quality", "ok") != "ok":
            reasons.append(f"a model fit of {err:.1f} percent (ERR)")
        if open_ended:
            reasons.append("a basement the sounding did not reach")
        text += (
            f" Confidence {confidence:.2f}: "
            + " and ".join(reasons)
            + " discount the score before ranking."
        )
    return text


def tied_leaders(
    results: list["SitingSuitability"], within_points: float = 3.0
) -> tuple["SitingSuitability", "SitingSuitability"] | None:
    """The two highest-ranked points when the ranking cannot separate them.

    One test for every place that has to know: the tie sentence, the
    preference table's "=1st" and the summary, conclusions and
    recommendations, which otherwise named a single winner in the same
    document that called the two indistinguishable. Decided on the
    confidence-weighted scores as they are, not as printed. ``None`` when
    the ranking is clear or there is one point.
    """
    ranked = sorted(results, key=lambda r: r.rank if r.rank is not None else 99)
    if len(ranked) < 2:
        return None
    first, second = ranked[0], ranked[1]
    if abs(first.weighted - second.weighted) >= within_points:
        return None
    return first, second


def ranking_tie(results: list["SitingSuitability"], within_points: float = 3.0) -> str:
    """One sentence when the top two points cannot be told apart.

    Two weighted scores within a few points of each other are the same
    number for siting purposes: a table that ranks them 1st and 2nd on a
    difference hidden by rounding gives the client a preference with no
    visible basis. Returns "" when the ranking is clear or there is one point.
    """
    pair = tied_leaders(results, within_points)
    if pair is None:
        return ""
    first, second = pair
    # "by name only" is true only of equal scores; said of 82.3 against 79.5
    # it told the client the order was alphabetical when it was not
    gap = first.weighted - second.weighted
    if gap == 0:
        order = f"{first.sounding_id} is listed first by name only"
    else:
        ahead = f"{gap:.1f}" if round(gap, 1) >= 0.1 else "less than 0.1"
        order = (
            f"{first.sounding_id} is ahead by {ahead} points, within the "
            f"{within_points:g}-point margin the ranking cannot separate"
        )
    return (
        f"Points {first.sounding_id} and {second.sounding_id} are indistinguishable "
        f"on geophysical grounds (confidence-weighted suitability "
        f"{first.weighted:.1f} and {second.weighted:.1f}); {order}, and the choice "
        "between them should be made on access, sanitary distances and the "
        "community's preference."
    )


def suitability_verdict(results: list["SitingSuitability"], within_points: float = 3.0) -> str:
    """The paragraph under the suitability table: the target, or the tie.

    Worded once for both engines. A tie gives both points' rationale, since
    the reader is being asked to choose between them.
    """
    if not results:
        return ""
    tie = ranking_tie(results, within_points)
    if tie:
        pair = tied_leaders(results, within_points)
        return " ".join([tie] + [f"Point {r.sounding_id}: {r.rationale}" for r in pair])
    best = sorted(results, key=lambda r: r.rank if r.rank is not None else 99)[0]
    return (
        f"Point {best.sounding_id} ranks first (suitability "
        f"{best.suitability:.0f} out of 100, {best.grade.lower()}, confidence "
        f"{best.confidence:.2f}) and is the recommended drilling target. "
        f"{best.rationale}"
    )


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
                confidence=round(float(getattr(interp, "confidence", 1.0)), 3),
            )
        )
    # rank on the confidence-weighted score, highest first; ties broken by
    # sounding id for stability, and said in words by ranking_tie()
    ranked = sorted(results, key=lambda r: (-r.weighted, r.sounding_id))
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
                # the confidence-weighted score: the number the ranking is
                # decided on, so the map colours agree with the table's order
                value=round(r.weighted, 1),
                kind=r.grade,
                rank=r.rank,
            )
        )
    return points
