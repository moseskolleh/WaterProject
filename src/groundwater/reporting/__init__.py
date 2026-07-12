"""Templated .docx report generation."""

from .docx_utils import ReportBuilder
from .geophysical import build_geophysical_report

__all__ = ["ReportBuilder", "build_geophysical_report"]


def __getattr__(name):
    # Phase 2 report builders are imported lazily so Phase 1 users are
    # not blocked by missing optional pieces during development.
    if name == "build_completion_report":
        from .completion import build_completion_report

        return build_completion_report
    if name == "build_pumping_report":
        from .pumping import build_pumping_report

        return build_pumping_report
    if name == "build_quality_report":
        from .quality import build_quality_report

        return build_quality_report
    if name == "build_handover_report":
        from .handover import build_handover_report

        return build_handover_report
    raise AttributeError(name)
