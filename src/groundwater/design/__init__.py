"""Borehole design: construction plan generation and schematic drawing."""

from .designer import (
    AS_BUILT_NOTE,
    DESIGN_NOTE,
    BoreholeDesign,
    CasingSegment,
    design_borehole,
    logged_diameter_in,
    seal_depth_for,
)
from .drawing import draw_borehole_design
from .lithology import (
    LITHOLOGY_CLASSES,
    LithologyClass,
    fracture_ranges,
    is_clayey,
    lithology_bands,
    lithology_class,
)

__all__ = [
    "AS_BUILT_NOTE",
    "DESIGN_NOTE",
    "LITHOLOGY_CLASSES",
    "BoreholeDesign",
    "CasingSegment",
    "LithologyClass",
    "design_borehole",
    "draw_borehole_design",
    "fracture_ranges",
    "is_clayey",
    "lithology_bands",
    "lithology_class",
    "logged_diameter_in",
    "seal_depth_for",
]
