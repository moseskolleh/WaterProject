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
    if sounding is not None and sounding.site is not None:
        interp.site_easting = sounding.site.easting
        interp.site_northing = sounding.site.northing
        interp.site_elevation_m = sounding.site.elevation_m
    interp.narrative = _narrative(interp)
    return interp


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
    return " ".join(parts)


def drilling_preference_table(
    interpretations: list[SiteInterpretation],
) -> list[dict]:
    """Ranked drilling preference table (one row per VES point).

    Matches the survey report layout: layers with thickness, depth and
    resistivity, possible water zones, maximum drilling depth and the
    ranking. Ranks are assigned here (1st = most preferred).
    """
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
