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

The weights are explicit and configurable (``VESConfig.suitability_weights``,
from ``data/defaults.json``). They are a defensible default, not a calibrated
model. A calibration set (PLAN.md step 5.3, calibration_sets.py) fits them
against the boreholes a programme has drilled, and puts its own in force once
a named person adopts it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import VESConfig
from ..ves.interpret import SiteInterpretation

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
    #: where the interpretation stood in the list assess_siting was given.
    #: A page pairs the row with what else it worked out for that point by
    #: this, not by the sounding id: a sheet copied without renumbering gives
    #: two points one id.
    index: int | None = None

    @property
    def weighted(self) -> float:
        """The number the ranking is decided on."""
        return self.suitability * self.confidence


def _exact(weighted: float) -> float:
    """A weighted score, or a difference of two, to the 0.0001 it is exact to.

    The score is held to 0.1 and the confidence to 0.001, so their product
    is a multiple of 0.0001; in doubles it is not always the one nearest
    it. 32.0 x 0.85 is 27.2 and 34.0 x 0.8 is 27.200000000000003, so the
    second point outranked the first by a last bit, where equal scores are
    ranked by sounding id. Compared at four places, equal products are
    equal.
    """
    return round(weighted, 4)


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


def _water_zone_rho(interp) -> float | None:
    """The thickness-weighted geometric mean resistivity of the water-bearing
    layers inside the water zones; None where there are none.

    Only the water-bearing layers: the zones are rounded to whole metres, so
    every layer inside a zone took in the slice of dry layer or basement the
    rounding added. A 150 ohm-m layer from 5.4 to 14.6 m has the zone 5 to
    15 m, and 0.4 m each of 1,500 ohm-m above it and 5,000 ohm-m below put
    its mean at 189 ohm-m, so it scored 0.713 for the fit where the same
    layer from 5.6 to 14.4 m scored 0.854, and the thicker water layer
    ranked second. The odds read the water-zone resistivity through this
    too. The logarithms are taken relative to the first such layer's
    resistivity, so a zone of one resistivity reads exactly that and not a
    rounding error either side of an edge (exp(ln 50) is 49.999...).
    """
    reference = 0.0
    acc = 0.0
    total = 0.0
    for top, bottom in interp.water_zones:
        for layer in interp.layers:
            if not layer.water_bearing:
                continue
            lo = max(layer.top_m, top)
            hi = min(layer.bottom_m if math.isfinite(layer.bottom_m) else bottom, bottom)
            if hi > lo:
                if total == 0.0:
                    reference = layer.rho
                acc += math.log(layer.rho / reference) * (hi - lo)
                total += hi - lo
    return reference * math.exp(acc / total) if total > 0 else None


def _resistivity_fit_score(interp: SiteInterpretation, config: VESConfig) -> float:
    mid = _water_zone_rho(interp)
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
    results: list[SitingSuitability], within_points: float = 3.0
) -> tuple[SitingSuitability, SitingSuitability] | None:
    """The two highest-ranked points when the ranking cannot separate them.

    One test for every place that has to know: the tie sentence, the
    preference table's "=1st" and the summary, conclusions and
    recommendations, which otherwise named a single winner in the same
    document that called the two indistinguishable. Decided on the gap
    between the confidence-weighted scores, to the tenth of a point the tie
    sentence prints it to: 64.1 less 61.1 is 2.999999999999993 in doubles,
    and a gap of 2.96 prints as 3.0, so both were called "ahead by 3.0
    points, within the 3-point margin" while 80.0 against 77.0 was not.
    Rounded so, a gap the sentence would print at the margin or above is
    not a tie, and gaps that print alike are treated alike. ``None`` when
    the ranking is clear or there is one point.
    """
    ranked = sorted(results, key=lambda r: r.rank if r.rank is not None else 99)
    if len(ranked) < 2:
        return None
    first, second = ranked[0], ranked[1]
    if round(abs(_gap(first, second)), 1) >= within_points:
        return None
    return first, second


def _gap(first: SitingSuitability, second: SitingSuitability) -> float:
    """How far the first point's weighted score is ahead of the second's,
    to the 0.0001 it is exact to (:func:`_exact`)."""
    return _exact(first.weighted - second.weighted)


def ranking_tie(results: list[SitingSuitability], within_points: float = 3.0) -> str:
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
    gap = _gap(first, second)
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


def suitability_verdict(results: list[SitingSuitability], within_points: float = 3.0) -> str:
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
    for index, interp in enumerate(interpretations):
        comp = SuitabilityComponents(
            aquifer_thickness=_thickness_score(interp),
            resistivity_fit=_resistivity_fit_score(interp, config),
            overburden=_overburden_score(interp),
            basal_fracture=_basal_fracture_score(interp),
        )
        weights = config.suitability_weights
        score = 100.0 * (
            weights["aquifer_thickness"] * comp.aquifer_thickness
            + weights["resistivity_fit"] * comp.resistivity_fit
            + weights["overburden"] * comp.overburden
            + weights["basal_fracture"] * comp.basal_fracture
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
                index=index,
            )
        )
    # rank on the confidence-weighted score, highest first, compared to the
    # 0.0001 it is exact to; equal scores are ranked by sounding id, and a
    # tie is said in words by ranking_tie()
    ranked = sorted(results, key=lambda r: (-_exact(r.weighted), r.sounding_id))
    for rank, result in enumerate(ranked, start=1):
        result.rank = rank
    return ranked


def suitability_map_points(results: list[SitingSuitability], zone: int | None = None):
    """Build MapPoints (value = suitability) for the drill-target map.

    Only points that carry coordinates are returned, all in the UTM zone
    ``zone`` (by default the zone of the first placed point): a survey on
    the 28N/29N boundary records its soundings in both, and a map that
    subtracted the two sets of eastings drew 400 m of ground 660 km wide.
    """
    from ..geo import infer_zone_for_sierra_leone
    from ..mapping.maps import MapPoint, to_zone

    points = []
    for r in results:
        if r.easting is None or r.northing is None:
            continue
        if zone is None:
            zone = infer_zone_for_sierra_leone(float(r.easting))
        easting, northing = to_zone(r.easting, r.northing, zone)
        points.append(
            MapPoint(
                label=f"{r.sounding_id}",
                easting=easting,
                northing=northing,
                # the confidence-weighted score: the number the ranking is
                # decided on, so the map colours agree with the table's order
                value=round(r.weighted, 1),
                # the grade of the suitability before the confidence
                # discount, the one the ranked table prints; the map names
                # it as that grade rather than pairing it with the weighted
                # score, which it does not grade
                kind=r.grade,
                rank=r.rank,
            )
        )
    return points
