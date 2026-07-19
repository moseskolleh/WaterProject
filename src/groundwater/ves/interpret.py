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
from ..models import LayeredModel, VESSounding
from ..utils import fmt_num, ordinal
from .classify import classify_curve, describe_curve_type

__all__ = [
    "LayerInterpretation",
    "SiteInterpretation",
    "interpret_model",
    "drilling_preference_table",
]


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
        return "fractured bedrock, low resistivity indicative of groundwater in fractures", True
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

    investigation = (
        float(np.max(sounding.ab2)) if sounding is not None else float(bottoms[-2] * 2 + 20)
    )

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
    zones: list[tuple[float, float]] = []
    for layer in layers:
        if not layer.water_bearing:
            continue
        top = max(layer.top_m, 3.0)  # the top few metres are vadose
        bottom = layer.bottom_m if math.isfinite(layer.bottom_m) else investigation
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

    aquifer_thickness = sum(b - t for t, b in zones)

    # ---- recommended maximum drilling depth ---------------------------------
    # deepest target zone plus a margin, but never past the depth the
    # sounding actually investigated (taken as the maximum AB/2)
    if zones:
        deepest = zones[-1][1] + config.max_drilling_margin_m
    else:
        deepest = investigation
    step = config.round_drilling_depth_to_m
    max_depth = min(deepest, investigation)
    max_depth = math.ceil(max_depth / step) * step

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
    )
    # ---- Dar-Zarrouk parameters and protective capacity ---------------------
    s_cond, t_res = _dar_zarrouk(layers)
    interp.longitudinal_conductance_s = s_cond
    interp.transverse_resistance_t = t_res
    # protective capacity uses only the cover above the aquifer, so a
    # conductive water-bearing zone is not counted as its own protection
    s_cover = _cover_conductance(layers, zones)
    interp.protective_conductance_s = s_cover
    interp.protective_capacity = _protective_capacity(s_cover)

    if sounding is not None and sounding.site is not None:
        interp.site_easting = sounding.site.easting
        interp.site_northing = sounding.site.northing
        interp.site_elevation_m = sounding.site.elevation_m
    interp.narrative = _narrative(interp)
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


def _cover_conductance(
    layers: list[LayerInterpretation], water_zones: list[tuple[float, float]]
) -> float:
    """Longitudinal conductance of the cover overlying the aquifer.

    Only the material above the shallowest water-bearing zone counts as
    protective cover, so a thick or conductive aquifer is not credited as
    its own contamination barrier. With no water zone the whole overburden
    is the cover.
    """
    aquifer_top = min((t for t, _ in water_zones), default=float("inf"))
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


def _narrative(interp: SiteInterpretation) -> str:
    """Interpretation paragraph for the report, one block per sounding."""
    n = interp.model.n_layers
    parts = [
        f"The data at {interp.sounding_id} resolves a {n} layer subsurface "
        f"({describe_curve_type(interp.curve_type)})."
    ]
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
        zones_text = ", ".join(f"{int(t)} m to {int(b)} m" for t, b in interp.water_zones)
        parts.append(
            "The unusually low resistivity within the interpreted fractured or "
            "weathered intervals is indicative of pore electrolyte, possibly "
            f"groundwater. The possible water zones are {zones_text}."
        )
    else:
        parts.append(
            "No clearly water bearing low resistivity zone is resolved at this "
            "point within the investigated depth."
        )
    if interp.depth_to_basement_m is not None:
        parts.append(
            f"The depth to bedrock is estimated at about "
            f"{fmt_num(interp.depth_to_basement_m)} m."
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


def drilling_preference_table(
    interpretations: list[SiteInterpretation],
    preferred_order: list[str] | None = None,
) -> list[dict]:
    """Ranked drilling preference table (one row per VES point).

    Matches the survey report layout: layers with thickness, depth and
    resistivity, possible water zones, maximum drilling depth and the
    ranking. Ranks are assigned from the suitability score (1st = most
    preferred). When sites score close together the choice is a
    professional judgment call, so ``preferred_order`` (a list of
    sounding ids, most preferred first) lets the analyst set the
    ranking explicitly; unlisted sites follow after, by score.
    """
    if preferred_order:
        position = {sid: i for i, sid in enumerate(preferred_order)}
        ranked = sorted(
            interpretations,
            key=lambda i: (position.get(i.sounding_id, len(position)), -i.score),
        )
    else:
        ranked = sorted(interpretations, key=lambda i: (-i.score, i.sounding_id))
    for rank, interp in enumerate(ranked, start=1):
        interp.rank = rank
    rows = []
    for i, interp in enumerate(interpretations, start=1):
        layer_numbers = "\n".join(str(l.number) for l in interp.layers)
        thicknesses = "\n".join(
            fmt_num(l.thickness_m) if l.thickness_m is not None else ""
            for l in interp.layers
        )
        depths = "\n".join(
            fmt_num(l.bottom_m) if math.isfinite(l.bottom_m) else ""
            for l in interp.layers
        )
        rhos = "\n".join(fmt_num(l.rho, 4) for l in interp.layers)
        zones = "\n".join(f"{int(t)}-{int(b)}" for t, b in interp.water_zones) or "none resolved"
        rows.append(
            {
                "No.": i,
                "VES Point": interp.sounding_id,
                "Layer": layer_numbers,
                "Thickness (m)": thicknesses,
                "Depth (m)": depths,
                "Apparent Resistivity (Ohm-m)": rhos,
                "Possible Water Zones (m)": zones,
                "Max Drilling Depth (m)": f"{interp.max_drilling_depth_m:.0f} m",
                "Ranking": ordinal(interp.rank),
            }
        )
    return rows
