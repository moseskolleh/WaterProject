"""Vertical electrical sounding analysis."""

from .._lazy import lazy_exports as _lazy_exports
from .arrays import geometric_factor, apparent_resistivity
from .forward import forward_schlumberger, forward_wenner, forward_for_sounding
from .inversion import invert_sounding, InversionResult
from .ipi2win import read_ipi2win_models
from .classify import classify_curve
from .interpret import interpret_model, drilling_preference_table, SiteInterpretation
from .splice import splice_segments

__all__ = [
    "geometric_factor",
    "apparent_resistivity",
    "forward_schlumberger",
    "forward_wenner",
    "forward_for_sounding",
    "invert_sounding",
    "InversionResult",
    "read_ipi2win_models",
    "classify_curve",
    "interpret_model",
    "drilling_preference_table",
    "SiteInterpretation",
    "splice_segments",
]

# ``plots`` pulls matplotlib and nothing here needs it, so it is bound on
# first use rather than imported. See groundwater._lazy.
_LAZY_MODULES = (
    "arrays",
    "forward",
    "inversion",
    "ipi2win",
    "classify",
    "interpret",
    "splice",
    "plots",
)

__getattr__, __dir__ = _lazy_exports(__name__, {}, _LAZY_MODULES)
