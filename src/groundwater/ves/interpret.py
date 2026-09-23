"""Hydrogeological interpretation of layered models.

The rules target crystalline basement terrain typical of Sierra Leone:
a lateritic or clayey cover, saprolite, a weathered/fractured zone
that forms the main aquifer, and fresh basement at depth. Thresholds
live in :class:`~groundwater.config.VESConfig` so they can be tuned
per area (coastal sedimentary sites use different ranges).

Outputs:

* per layer lithological/hydrogeological labels,
* possible water zones as depth ranges,
* estimated depth to (fresh) basement and aquifer thickness,
* a recommended maximum drilling depth,
* the ranked drilling preference table used in survey reports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..config import VESConfig
from ..models import DataFlag, LayeredModel, VESSounding
from ..utils import and_join, fmt_num, ordinal
from .classify import classify_curve, describe_curve_type
from .inversion import inversion_readings

__all__ = [
    "LayerInterpretation",
    "SiteInterpretation",
    "depth_of_investigation",
    "fit_confidence",
    "interpret_model",
    "drilling_preference_table",
    "rank_interpretations",
]


def depth_of_investigation(max_spacing_m: float, config: VESConfig | None = None) -> float:
    """How deep a sounding with this largest AB/2 actually resolves.

    One rule for the whole toolkit: the interpretation, the model panel of
    the curve figure, the layer column, the section and the drilling-depth
    cap all read it, so a document no longer shows the same half-space
    ending at 40 m in one figure and 80 m in the next.
    """
    config = config or VESConfig()
    return float(max_spacing_m) * config.depth_of_investigation_factor


def fit_confidence(fit_error_percent: float | None, config: VESConfig | None = None) -> float:
    """How far a model's misfit should discount what is read from it.

    1.0 at or under the target misfit, falling linearly to the floor at the
    unreliable level and staying there. A 26.8 percent two-layer fit is not
    a description of the curve, and a ranking that cannot see that prefers
    it over a 13 percent fit on 2.7 ohm-m of half-space resistivity.
    """
    config = config or VESConfig()
    if fit_error_percent is None:
        return 1.0
    target = config.target_fit_percent
    unreliable = max(config.unreliable_fit_percent, target + 1e-9)
    if fit_error_percent <= target:
        return 1.0
    frac = min((fit_error_percent - target) / (unreliable - target), 1.0)
    return 1.0 - (1.0 - config.fit_confidence_floor) * frac


@dataclass
class LayerInterpretation:
    number: int
    rho: float
    thickness_m: float | None  # None for the half space
    top_m: float
    bottom_m: float  # inf for the half space
    unit: str
    water_bearing: bool


@dataclass
class SiteInterpretation:
    sounding_id: str
    model: LayeredModel
    curve_type: str
    layers: list[LayerInterpretation]
    water_zones: list[tuple[float, float]]
    depth_to_basement_m: float | None
    aquifer_thickness_m: float
    max_drilling_depth_m: float
    investigation_depth_m: float
    score: float  # used for ranking between sites
    # Dar-Zarrouk parameters over the resolved overburden
    longitudinal_conductance_s: float = 0.0  # siemens, Sum(h/rho), full section
    transverse_resistance_t: float = 0.0  # ohm m2, Sum(h*rho), full section
    # conductance of the cover overlying the aquifer, used for protection
    protective_conductance_s: float = 0.0
    protective_capacity: str = ""  # from the protective (cover) conductance
    narrative: str = ""
    rank: int | None = None
    site_easting: float | None = None
    site_northing: float | None = None
    site_elevation_m: float | None = None
    flags: list = field(default_factory=list)
    #: True when the deepest water-bearing layer continues below the depth
    #: of investigation - the half-space, or a layer whose modelled base
    #: lies deeper than the sounding sees: the zone is open-ended at the
    #: depth of investigation, the aquifer thickness is a lower bound and
    #: the drilling depth a minimum
    basement_not_resolved: bool = False
    #: True when the deepest target plus the drilling margin lies below the
    #: depth of investigation, so the recommended depth was cut back to it
    #: and is a minimum rather than an estimate
    drilling_depth_capped: bool = False
    #: 0-1 discount from the fit quality and the unresolved basement,
    #: applied to the score and the suitability before ranking
    confidence: float = 1.0
    fit_error_percent: float | None = None
    #: "ok", "poor" (above the target) or "unreliable" (above the
    #: unreliable level), judged against the config the model was read with
    fit_quality: str = "ok"
    #: the largest AB/2 the sounding was expanded to; the depth of
    #: investigation is a fraction of it, not the spacing itself
    max_spacing_m: float | None = None


def _unit_label(
    rho: float, is_top: bool, is_bottom: bool, config: VESConfig
) -> tuple[str, bool]:
    """Label a layer and judge whether it is potentially water bearing."""
    lo, hi = config.fractured_zone_rho
    if is_top:
        if rho >= config.laterite_min_rho:
            return "dry lateritic topsoil / duricrust", False
        if rho >= hi:
            return "compact laterite / dry overburden", False
        if rho <= config.clay_max_rho:
            return "clayey topsoil", False
        return "topsoil / laterite", False
    if rho >= config.fresh_basement_min_rho:
        return "fresh basement", False
    if rho >= hi:
        if is_bottom:
            return "slightly weathered or fractured bedrock (limited water potential)", False
        return "compact or dry weathered rock (regolith)", False
    if rho <= config.clay_max_rho:
        return "clay rich saprolite (low permeability)", False
    if is_bottom:
        # A conductive half-space is the weathered zone the sounding did not
        # get to the bottom of, not fractured bedrock: fractured fresh
        # basement is hundreds to thousands of ohm-m, and the reading that
        # called 47 ohm-m "fractured bedrock with groundwater in fractures"
        # sent a client to drill 80 m into what is clay-rich saprolite.
        return (
            "weathered or fractured zone, potentially water bearing when "
            "saturated; its base is not resolved within the depth of "
            "investigation"
        ), True
    return "weathered / fractured zone, potentially water bearing when saturated", True


def interpret_model(
    sounding: VESSounding | None,
    model: LayeredModel,
    config: VESConfig | None = None,
) -> SiteInterpretation:
    """Interpret one layered model hydrogeologically."""
    config = config or VESConfig()
    rho = model.resistivities
    tops = model.depths_top
    bottoms = model.depths_bottom
    n = model.n_layers

    max_spacing: float | None = None
    # the spacings the inversion actually fitted: a reading it dropped (a
    # zero or a blank resistivity) extends no depth the model was fitted to
    used = inversion_readings(sounding)[0] if sounding is not None else np.array([])
    if len(used):
        max_spacing = float(np.max(used))
        investigation = depth_of_investigation(max_spacing, config)
    elif n > 1:
        investigation = float(bottoms[-2] * 2 + 20)
    else:
        # A bare half-space with no sounding carries no depth scale at all -
        # bottoms is just [inf], and bottoms[-2] used to raise IndexError.
        # Zero is the honest answer: nothing was resolved, so nothing is
        # recommended.
        investigation = 0.0

    layers: list[LayerInterpretation] = []
    for i in range(n):
        unit, water = _unit_label(
            float(rho[i]), is_top=(i == 0), is_bottom=(i == n - 1), config=config
        )
        layers.append(
            LayerInterpretation(
                number=i + 1,
                rho=float(rho[i]),
                thickness_m=float(model.thicknesses[i]) if i < n - 1 else None,
                top_m=float(tops[i]),
                bottom_m=float(bottoms[i]),
                unit=unit,
                water_bearing=water,
            )
        )

    # ---- water zones ------------------------------------------------------
    # A water-bearing half-space is a zone with a top and no base: it runs
    # to the depth of investigation because that is as far as the sounding
    # saw, not because anything ends there. The interpretation says so
    # rather than reporting the array's reach as an aquifer thickness.
    # A finite layer whose modelled base lies below the depth of
    # investigation is open-ended in the same way: the model put that base
    # where no reading reaches, and a zone "4 m to 60 m" from a sounding that
    # sees 40 m reports the model's extrapolation as a measured aquifer. A
    # water-bearing layer that starts at or below the depth of investigation
    # was never seen at all, so it is no zone, and the narrative says so.
    zones: list[tuple[float, float]] = []
    basement_not_resolved = False
    open_base: float | None = None  # the modelled base of the zone cut at the DOI
    unseen_tops: list[float] = []  # water-bearing layers below the DOI
    for layer in layers:
        if not layer.water_bearing:
            continue
        top = max(layer.top_m, 3.0)  # the top few metres are vadose
        if top >= investigation:
            unseen_tops.append(layer.top_m)
            continue
        bottom = min(layer.bottom_m, investigation)
        if layer.bottom_m > investigation:
            basement_not_resolved = bottom - top >= 1.0
            open_base = layer.bottom_m
        if bottom - top >= 1.0:
            zones.append((round(top), round(bottom)))
    # merge touching zones
    merged: list[tuple[float, float]] = []
    for zone in sorted(zones):
        if merged and zone[0] <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], zone[1]))
        else:
            merged.append(zone)
    zones = merged

    # ---- depth to basement -------------------------------------------------
    depth_to_basement = None
    for layer in layers:
        if layer.rho >= config.fresh_basement_min_rho and layer.top_m > 0:
            depth_to_basement = layer.top_m
            break
    if depth_to_basement is None and layers[-1].rho >= config.fractured_zone_rho[1]:
        depth_to_basement = layers[-1].top_m
    # A basement top below the depth of investigation is where the model
    # happened to put it, not a depth the sounding measured, and the siting
    # score and the bedrock map would otherwise read it as one.
    bedrock_unseen = depth_to_basement is not None and depth_to_basement > investigation
    if bedrock_unseen:
        depth_to_basement = None

    aquifer_thickness = sum(b - t for t, b in zones)

    # ---- recommended maximum drilling depth ---------------------------------
    # deepest target zone plus a margin, but never past the depth the
    # sounding actually investigated (taken as the maximum AB/2)
    if zones:
        deepest = zones[-1][1] + config.max_drilling_margin_m
    else:
        deepest = investigation
    # the cap used to be silent: a target and margin reaching past the depth
    # of investigation came out as "about 40 m", an estimate, when 40 m is
    # only where the survey stops seeing and the hole has further to go
    drilling_depth_capped = deepest > investigation
    step = config.round_drilling_depth_to_m
    # Round up to the nearest step, then re-apply the investigated-depth cap:
    # rounding after the min() could push the recommendation past the depth the
    # sounding actually resolved, defeating the cap.
    max_depth = math.ceil(min(deepest, investigation) / step) * step
    max_depth = min(max_depth, investigation)

    # ---- suitability score for ranking --------------------------------------
    score = 0.0
    for top, bottom in zones:
        thickness = bottom - top
        mid_rho = _zone_rho(layers, top, bottom)
        # favour thick zones with resistivities in the productive window
        lo, hi = config.fractured_zone_rho
        centre = math.sqrt(lo * hi)
        rho_term = 1.0 / (1.0 + abs(math.log(max(mid_rho, 1e-3) / centre)))
        score += thickness * rho_term
    if depth_to_basement is not None and depth_to_basement < 5 and not zones:
        score *= 0.5  # thin regolith and nothing water bearing

    # ---- how much to believe it -----------------------------------------------
    # The misfit and the unresolved basement discount the score before any
    # ranking reads it: a point is not preferred for a 2.7 ohm-m difference
    # in a half-space its curve fits twice as badly.
    err = model.fit_error_percent
    confidence = fit_confidence(err, config)
    if basement_not_resolved:
        confidence *= config.unresolved_basement_confidence
    score *= confidence

    flags: list[DataFlag] = []
    fit_quality = "ok"
    if err is not None and err > config.target_fit_percent:
        unreliable = err > config.unreliable_fit_percent
        fit_quality = "unreliable" if unreliable else "poor"
        flags.append(
            DataFlag(
                "warning",
                "poor_fit",
                f"The layered model reproduces the readings to {err:.1f} percent "
                f"(ERR), above the {config.target_fit_percent:g} percent target"
                + (
                    "; the model does not describe the curve and the layer "
                    "depths are indicative only."
                    if unreliable
                    else "; treat the layer depths as approximate."
                ),
                model.sounding_id or (sounding.sounding_id if sounding else ""),
            )
        )
    if basement_not_resolved:
        where = (
            "is the half-space: the sounding did not reach its base within the "
            f"{investigation:.0f} m it resolves"
            if open_base is None or not math.isfinite(open_base) else
            f"continues below the {investigation:.0f} m the sounding resolves: "
            f"the model puts its base at {fmt_num(open_base)} m, deeper than the "
            "readings reach"
        )
        flags.append(
            DataFlag(
                "info",
                "basement_not_resolved",
                f"The deepest water-bearing layer {where}, so the zone is "
                "open-ended, the aquifer thickness is a minimum and the drilling "
                "depth is a minimum.",
                model.sounding_id or (sounding.sounding_id if sounding else ""),
            )
        )

    curve_type = classify_curve(model)
    interp = SiteInterpretation(
        sounding_id=model.sounding_id or (sounding.sounding_id if sounding else ""),
        model=model,
        curve_type=curve_type,
        layers=layers,
        water_zones=zones,
        depth_to_basement_m=depth_to_basement,
        aquifer_thickness_m=aquifer_thickness,
        max_drilling_depth_m=max_depth,
        investigation_depth_m=investigation,
        score=score,
        flags=flags,
        basement_not_resolved=basement_not_resolved,
        drilling_depth_capped=drilling_depth_capped,
        confidence=confidence,
        fit_error_percent=err,
        fit_quality=fit_quality,
        max_spacing_m=max_spacing,
    )
    # ---- Dar-Zarrouk parameters and protective capacity ---------------------
    s_cond, t_res = _dar_zarrouk(layers)
    interp.longitudinal_conductance_s = s_cond
    interp.transverse_resistance_t = t_res
    # protective capacity uses only the cover above the aquifer, so a
    # conductive water-bearing zone is not counted as its own protection
    s_cover = _cover_conductance(layers)
    interp.protective_conductance_s = s_cover
    interp.protective_capacity = _protective_capacity(s_cover)

    if sounding is not None and sounding.site is not None:
        interp.site_easting = sounding.site.easting
        interp.site_northing = sounding.site.northing
        interp.site_elevation_m = sounding.site.elevation_m
    interp.narrative = _narrative(interp, unseen_tops, bedrock_unseen)
    return interp


def _dar_zarrouk(layers: list[LayerInterpretation]) -> tuple[float, float]:
    """Longitudinal conductance S = Sum(h/rho) and transverse resistance
    T = Sum(h*rho) over the finite (non-basement) layers."""
    s_cond = 0.0
    t_res = 0.0
    for layer in layers:
        if layer.thickness_m is None or layer.rho <= 0:
            continue
        s_cond += layer.thickness_m / layer.rho
        t_res += layer.thickness_m * layer.rho
    return s_cond, t_res


def _cover_conductance(layers: list[LayerInterpretation]) -> float:
    """Longitudinal conductance of the cover overlying the aquifer.

    Only the material above the shallowest water-bearing layer counts as
    protective cover, so a thick or conductive aquifer is not credited as
    its own contamination barrier. With no water-bearing layer the whole
    overburden is the cover.

    The top is taken from the layers, not from the reported water zones:
    those are floored at 3 m by the vadose rule and rounded for display, so
    a weathered aquifer reaching close to the surface had its own top 3 m -
    conductive, and therefore a large contribution - credited as its
    barrier, rating a poorly protected aquifer as moderately protected.
    """
    aquifer_top = min(
        (layer.top_m for layer in layers if layer.water_bearing),
        default=float("inf"),
    )
    s_cover = 0.0
    for layer in layers:
        if layer.thickness_m is None or layer.rho <= 0:
            continue
        cover_thickness = max(0.0, min(layer.bottom_m, aquifer_top) - layer.top_m)
        if cover_thickness > 0:
            s_cover += cover_thickness / layer.rho
    return s_cover


def _protective_capacity(s_cond: float) -> str:
    """Aquifer protective-capacity rating from the longitudinal conductance
    (standard crystalline-basement classification, siemens)."""
    if s_cond < 0.1:
        return "poor"
    if s_cond < 0.2:
        return "weak"
    if s_cond < 0.7:
        return "moderate"
    if s_cond < 5.0:
        return "good"
    return "very good"


def _zone_rho(layers: list[LayerInterpretation], top: float, bottom: float) -> float:
    """Thickness weighted geometric mean resistivity across a depth range."""
    total = 0.0
    acc = 0.0
    for layer in layers:
        lo = max(layer.top_m, top)
        hi = min(layer.bottom_m if math.isfinite(layer.bottom_m) else bottom, bottom)
        if hi > lo:
            acc += math.log(layer.rho) * (hi - lo)
            total += hi - lo
    return math.exp(acc / total) if total > 0 else 100.0


#: A thickness known only to within this factor or worse marks a boundary
#: the curve does not resolve (the linearised 1-sigma uncertainty).
POORLY_RESOLVED_FACTOR = 2.0


def poorly_resolved_boundaries(model: LayeredModel) -> list[tuple[float, float]]:
    """``(depth, factor)`` of each boundary whose thickness uncertainty factor
    is :data:`POORLY_RESOLVED_FACTOR` or more; empty for a model that carries
    no uncertainty (a transcribed one)."""
    factors = getattr(model, "h_uncertainty_factor", None)
    if factors is None:
        return []
    bottoms = model.depths_bottom
    return [(float(bottoms[i]), float(f)) for i, f in enumerate(factors)
            if f >= POORLY_RESOLVED_FACTOR]


def _narrative(
    interp: SiteInterpretation,
    unseen_tops: list[float] | tuple = (),
    bedrock_unseen: bool = False,
) -> str:
    """Interpretation paragraph for the report, one block per sounding."""
    n = interp.model.n_layers
    curve = describe_curve_type(interp.curve_type)
    # "resolves a 3 layer subsurface" over a boundary known only to x/ 3.7
    # claimed a layer the curve does not settle, a paragraph after the
    # sounding block said it was poorly resolved
    weak = poorly_resolved_boundaries(interp.model)
    if weak:
        opening = (
            f"The data at {interp.sounding_id} are fitted with a {n} layer model "
            f"({curve}), though the {'boundary' if len(weak) == 1 else 'boundaries'} "
            f"at {and_join([f'{fmt_num(z)} m' for z, _ in weak])} "
            f"{'is' if len(weak) == 1 else 'are'} poorly resolved, so the layer "
            "count is uncertain."
        )
    else:
        opening = f"The data at {interp.sounding_id} resolves a {n} layer subsurface ({curve})."
    parts = [opening]
    for layer in interp.layers:
        if layer.thickness_m is not None:
            span = (
                f"from {fmt_num(layer.top_m)} m to {fmt_num(layer.bottom_m)} m "
                f"({fmt_num(layer.thickness_m)} m thick)"
            )
        else:
            span = f"below {fmt_num(layer.top_m)} m"
        parts.append(
            f"Layer {layer.number} {span} has a resistivity of about "
            f"{fmt_num(layer.rho, 4)} ohm-m and is interpreted as {layer.unit}."
        )
    if interp.water_zones:
        zones_text = ", ".join(
            zone_text(t, b, open_ended=(interp.basement_not_resolved and (t, b) == interp.water_zones[-1]))
            for t, b in interp.water_zones
        )
        parts.append(
            "The unusually low resistivity within the interpreted fractured or "
            "weathered intervals is indicative of pore electrolyte, possibly "
            f"groundwater. The possible water zones are {zones_text}."
        )
        if interp.basement_not_resolved:
            parts.append(
                "The base of the deepest zone is not resolved: the sounding sees "
                f"to about {fmt_num(interp.investigation_depth_m)} m, and the "
                "conductive ground continues below that."
            )
    else:
        parts.append(
            "No clearly water bearing low resistivity zone is resolved at this "
            "point within the investigated depth."
        )
    if unseen_tops:
        one = len(unseen_tops) == 1
        parts.append(
            f"The water-bearing {'layer' if one else 'layers'} from "
            f"{and_join([f'{fmt_num(t)} m' for t in unseen_tops])} "
            f"{'lies' if one else 'lie'} below the "
            f"{fmt_num(interp.investigation_depth_m)} m the sounding resolves, so "
            f"{'it is not counted as a water zone' if one else 'they are not counted as water zones'}."
        )
    if interp.fit_error_percent is not None:
        err = interp.fit_error_percent
        if interp.fit_quality == "unreliable":
            parts.append(
                f"The model reproduces the readings to {fmt_num(err, 3)} percent "
                "(ERR), well above the target: it does not describe the curve "
                "closely, and the layer depths are indicative only."
            )
        elif interp.fit_quality == "poor":
            parts.append(
                f"The model reproduces the readings to {fmt_num(err, 3)} percent "
                "(ERR), above the target, so the layer depths are approximate."
            )
    if interp.depth_to_basement_m is not None:
        parts.append(
            f"The depth to bedrock is estimated at about "
            f"{fmt_num(interp.depth_to_basement_m)} m."
        )
    elif bedrock_unseen:
        parts.append(
            "The depth to bedrock is not resolved within the depth of "
            f"investigation (about {fmt_num(interp.investigation_depth_m)} m)."
        )
    if interp.longitudinal_conductance_s > 0:
        base = (
            "The Dar-Zarrouk longitudinal conductance of the section is "
            f"{fmt_num(interp.longitudinal_conductance_s, 3)} siemens and the "
            "transverse resistance is "
            f"{fmt_num(interp.transverse_resistance_t)} ohm m2."
        )
        if interp.water_zones:
            base += (
                " The cover overlying the water bearing zone has a longitudinal "
                f"conductance of {fmt_num(interp.protective_conductance_s, 3)} "
                f"siemens, indicating a {interp.protective_capacity} protective "
                "capacity against surface contamination."
            )
        else:
            base += (
                f" This gives a {interp.protective_capacity} protective capacity "
                "against surface contamination."
            )
        parts.append(base)
    return " ".join(parts)



def zone_text(top: float, bottom: float, open_ended: bool = False) -> str:
    """A water zone in prose: "8 m to 40 m", or open-ended, "8 m to at least
    40 m" - the deepest zone of a sounding that never reached its base."""
    if open_ended:
        return f"{int(top)} m to at least {int(bottom)} m"
    return f"{int(top)} m to {int(bottom)} m"


def zone_cell(top: float, bottom: float, open_ended: bool = False) -> str:
    """The same zone in a table cell: "8-40", or "8-40+" when open-ended."""
    return f"{int(top)}-{int(bottom)}" + ("+" if open_ended else "")


def drilling_depth_text(interp: SiteInterpretation) -> str:
    """The recommended drilling depth, as a minimum when the base of the
    water-bearing zone was never reached or the depth was cut back to the
    depth of investigation."""
    depth = f"{interp.max_drilling_depth_m:.0f} m"
    minimum = interp.basement_not_resolved or interp.drilling_depth_capped
    return f"at least {depth}" if minimum else f"about {depth}"


def ranking_weight(interp: SiteInterpretation, config: VESConfig | None = None) -> float:
    """The one number the points are ranked on.

    The suitability scorecard's geological score discounted by the
    interpretation's confidence, so the drilling-preference table, the
    executive summary and the suitability section all rank on the same
    quantity. There used to be two scores - the interpretation's own and
    the scorecard's - and a report could recommend one point in the
    summary and another in the scorecard section.
    """
    from ..siting.suitability import assess_siting  # circular at module level

    result = assess_siting([interp], config)[0]
    return result.suitability * result.confidence


def rank_interpretations(
    interpretations: list[SiteInterpretation],
    preferred_order: list[str] | None = None,
    config: VESConfig | None = None,
) -> list[SiteInterpretation]:
    """Assign ``rank`` (1 = most preferred) in place; return them ranked.

    Kept separate from the preference table so callers that only need the
    ranking - the dashboard, a reloaded project - get it without building the
    table. Every caller reading ``rank`` must have ranked first: an unranked
    set leaves every rank None, and "best" then falls back to whichever
    sounding happened to be parsed first.
    """
    # Keyed by the interpretation itself, not its sounding id: a sheet copied
    # without renumbering gives two soundings one id, and a weight looked up
    # by id gave both the last one's, so a point with no water zone could
    # rank first while the suitability table ranked the other.
    weight = {id(i): ranking_weight(i, config) for i in interpretations}
    if preferred_order:
        position = {sid: i for i, sid in enumerate(preferred_order)}
        ranked = sorted(
            interpretations,
            key=lambda i: (position.get(i.sounding_id, len(position)),
                           -weight[id(i)], i.sounding_id),
        )
    else:
        ranked = sorted(interpretations, key=lambda i: (-weight[id(i)], i.sounding_id))
    for rank, interp in enumerate(ranked, start=1):
        interp.rank = rank
    return ranked


LAYER_RESISTIVITY_COLUMN = "Layer resistivity (ohm-m)"


def drilling_preference_table(
    interpretations: list[SiteInterpretation],
    preferred_order: list[str] | None = None,
    config: VESConfig | None = None,
) -> list[dict]:
    """Ranked drilling preference table (one row per VES point, most
    preferred first).

    Matches the survey report layout: layers with thickness, depth and
    resistivity, possible water zones, maximum drilling depth and the
    ranking. Ranks are assigned from the confidence-weighted suitability
    (1st = most preferred; "=1st" for a top pair the ranking cannot
    separate). When sites score close together the choice is a
    professional judgment call, so ``preferred_order`` (a list of
    sounding ids, most preferred first) lets the analyst set the
    ranking explicitly; unlisted sites follow after, by score.

    The resistivity column holds the inverted layer resistivities, and is
    named so: apparent resistivity is the field reading at a spacing, and
    the two are not the same number.
    """
    config = config or VESConfig()
    ranked = rank_interpretations(interpretations, preferred_order, config)
    # The rows in the order of preference the caption promises; they used to
    # follow the sheets, so a table "in order of preference" could open on
    # its 2nd. Two points the ranking cannot separate are both "=1st",
    # decided by the same test as the tie sentence, unless the analyst has
    # set the order, which is then a judgment and not a score.
    tied: set[int] = set()
    if not preferred_order and len(ranked) >= 2:
        from ..siting.suitability import assess_siting, tied_leaders  # circular

        if tied_leaders(assess_siting(interpretations, config), config.ranking_tie_points):
            tied = {id(ranked[0]), id(ranked[1])}
    rows = []
    for i, interp in enumerate(ranked, start=1):
        layer_numbers = "\n".join(str(layer.number) for layer in interp.layers)
        thicknesses = "\n".join(
            fmt_num(layer.thickness_m) if layer.thickness_m is not None else ""
            for layer in interp.layers
        )
        depths = "\n".join(
            fmt_num(layer.bottom_m) if math.isfinite(layer.bottom_m) else ""
            for layer in interp.layers
        )
        rhos = "\n".join(fmt_num(layer.rho, 4) for layer in interp.layers)
        zones = "\n".join(
            zone_cell(t, b, open_ended=(interp.basement_not_resolved
                                        and (t, b) == interp.water_zones[-1]))
            for t, b in interp.water_zones
        ) or "none resolved"
        rows.append(
            {
                "No.": i,
                "VES Point": interp.sounding_id,
                "Layer": layer_numbers,
                "Thickness (m)": thicknesses,
                "Depth (m)": depths,
                LAYER_RESISTIVITY_COLUMN: rhos,
                "Possible Water Zones (m)": zones,
                "Max Drilling Depth (m)": drilling_depth_text(interp),
                "Ranking": "=1st" if id(interp) in tied else ordinal(interp.rank),
            }
        )
    return rows
