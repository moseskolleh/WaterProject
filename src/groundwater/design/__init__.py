"""Borehole design: construction plan generation and schematic drawing."""

from .._lazy import lazy_exports as _lazy_exports
from .designer import (
    AS_BUILT_NOTE,
    DESIGN_NOTE,
    BoreholeDesign,
    CasingSegment,
    design_borehole,
    logged_diameter_in,
    pump_intake_floor,
    seal_depth_for,
)
from .lithology import (
    LITHOLOGY_CLASSES,
    LithologyClass,
    fracture_ranges,
    is_clayey,
    lithology_bands,
    lithology_class,
    read_fractures,
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
    "pump_intake_floor",
    "read_fractures",
    "seal_depth_for",
]

# Deferred: these pull matplotlib, openpyxl or python-docx, which the
# analysis half of this package does not need. See groundwater._lazy.
_LAZY = {
    "draw_borehole_design": ".drawing",
}

# The submodules stayed reachable as attributes of the package while
# the eager imports bound them; keep that true without importing them.
_LAZY_MODULES = (
    "designer",
    "drawing",
    "lithology",
)

__getattr__, __dir__ = _lazy_exports(__name__, _LAZY, _LAZY_MODULES)
