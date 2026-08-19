"""Templated .docx report generation."""

from .._lazy import lazy_exports

__all__ = ["ReportBuilder", "build_geophysical_report"]

# Every builder is imported on first use. The Phase 2 builders were
# already deferred by hand, so that a half-finished one could not block
# the rest, and that still holds; the two Phase 1 names join them because
# the .docx writer pulls python-docx and the geophysical report pulls the
# map and VES plotting stacks with it. A caller after one report should
# not pay for the other five.
_LAZY = {
    "ReportBuilder": ".docx_utils",
    "build_geophysical_report": ".geophysical",
    "build_completion_report": ".completion",
    "build_pumping_report": ".pumping",
    "build_quality_report": ".quality",
    "build_handover_report": ".handover",
}

__getattr__, __dir__ = lazy_exports(__name__, _LAZY)
