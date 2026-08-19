"""Borehole design: construction plan generation and schematic drawing."""

from .._lazy import lazy_exports
from .designer import BoreholeDesign, CasingSegment, design_borehole

__all__ = ["BoreholeDesign", "CasingSegment", "design_borehole", "draw_borehole_design"]

# Deferred: these pull matplotlib, openpyxl or python-docx, which the
# analysis half of this package does not need. See groundwater._lazy.
_LAZY = {
    "draw_borehole_design": ".drawing",
}

__getattr__, __dir__ = lazy_exports(__name__, _LAZY)
