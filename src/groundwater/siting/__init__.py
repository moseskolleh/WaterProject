"""Drill-target siting decision support (prototype).

Turns the hydrogeological interpretation the toolkit already computes into
a single, ranked "where should I drill?" answer: a transparent 0-100
suitability score per candidate VES point, a grade, a plain-language
rationale, and a drill-target map.

The score is a transparent weighted scorecard over features that a siting
hydrogeologist already weighs in crystalline basement terrain, so a water
manager can see *why* a point is preferred, not just that it is. It is a
starting point: as a programme accumulates its own (VES features ->
drilling outcome) pairs, the weights can be replaced by a fitted model.
"""

from .suitability import (
    SitingSuitability,
    SuitabilityComponents,
    assess_siting,
    suitability_map_points,
)

__all__ = [
    "SitingSuitability",
    "SuitabilityComponents",
    "assess_siting",
    "suitability_map_points",
]
