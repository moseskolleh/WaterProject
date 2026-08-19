"""Templated .docx report generation.

Every builder the toolkit has is named here, so ``from
groundwater.reporting import X`` works for all of them rather than for
four out of ten.

None of them is imported until it is read. The .docx writer pulls
python-docx, and the geophysical report pulls the map and VES plotting
stacks with it, so a caller after one report should not pay for the
other ten. Deferring also keeps a half-finished builder from blocking
the rest, which is why the Phase 2 ones were deferred to begin with.
"""

from .._lazy import lazy_exports as _lazy_exports

__all__ = [
    "ReportBuilder",
    "build_asset_placard",
    "build_asset_record",
    "build_completion_report",
    "build_cost_report",
    "build_geophysical_report",
    "build_handover_report",
    "build_payment_certificate",
    "build_pumping_report",
    "build_quality_report",
    "build_supervision_report",
]

_LAZY = {
    "ReportBuilder": ".docx_utils",
    "build_asset_placard": ".registry",
    "build_asset_record": ".registry",
    "build_completion_report": ".completion",
    "build_cost_report": ".costing",
    "build_geophysical_report": ".geophysical",
    "build_handover_report": ".handover",
    "build_payment_certificate": ".procurement",
    "build_pumping_report": ".pumping",
    "build_quality_report": ".quality",
    "build_supervision_report": ".supervision",
}

# The submodules stayed reachable as attributes of the package while
# the eager imports bound them; keep that true without importing them.
_LAZY_MODULES = (
    "docx_utils",
    "geophysical",
    "completion",
    "pumping",
    "quality",
    "handover",
    "costing",
    "procurement",
    "supervision",
    "registry",
    "citations",
    "context",
)

__getattr__, __dir__ = _lazy_exports(__name__, _LAZY, _LAZY_MODULES)
