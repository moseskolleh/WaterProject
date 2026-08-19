"""Pumping test analysis: aquifer parameters, safe yield and diagnostics."""

from .._lazy import lazy_exports as _lazy_exports
from .analysis import (
    CooperJacobResult,
    TheisResult,
    RecoveryResult,
    StepTestResult,
    YieldRecommendation,
    PumpingTestAnalysis,
    analyse_pumping_test,
    cooper_jacob,
    theis_fit,
    theis_recovery,
    hantush_bierschenk,
)

__all__ = [
    "CooperJacobResult",
    "TheisResult",
    "RecoveryResult",
    "StepTestResult",
    "YieldRecommendation",
    "PumpingTestAnalysis",
    "analyse_pumping_test",
    "cooper_jacob",
    "theis_fit",
    "theis_recovery",
    "hantush_bierschenk",
    "plot_test_overview",
    "plot_cooper_jacob",
    "plot_theis",
    "plot_recovery",
    "plot_step_test",
]

# Deferred: these pull matplotlib, openpyxl or python-docx, which the
# analysis half of this package does not need. See groundwater._lazy.
_LAZY = {
    "plot_test_overview": ".plots",
    "plot_cooper_jacob": ".plots",
    "plot_theis": ".plots",
    "plot_recovery": ".plots",
    "plot_step_test": ".plots",
}

# The submodules stayed reachable as attributes of the package while
# the eager imports bound them; keep that true without importing them.
_LAZY_MODULES = (
    "analysis",
    "plots",
)

__getattr__, __dir__ = _lazy_exports(__name__, _LAZY, _LAZY_MODULES)
