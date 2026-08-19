"""Borehole design: construction plan generation and schematic drawing."""

from .._lazy import lazy_exports as _lazy_exports
from .designer import BoreholeDesign, CasingSegment, design_borehole

__all__ = ["BoreholeDesign", "CasingSegment", "design_borehole", "draw_borehole_design"]

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
)

__getattr__, __dir__ = _lazy_exports(__name__, _LAZY, _LAZY_MODULES)
