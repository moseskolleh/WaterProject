"""Templated .docx report generation.

Every builder the toolkit has is named here. The Phase 2 builders are still
imported lazily - some of them pull in matplotlib and python-docx machinery
that a caller who only wants ``ReportBuilder`` should not pay for - but the
list is now complete, so ``from groundwater.reporting import X`` works for
all of them rather than for four out of ten.
"""

from .docx_utils import ReportBuilder
from .geophysical import build_geophysical_report

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
    "build_asset_placard": ".registry",
    "build_asset_record": ".registry",
    "build_completion_report": ".completion",
    "build_cost_report": ".costing",
    "build_handover_report": ".handover",
    "build_payment_certificate": ".procurement",
    "build_pumping_report": ".pumping",
    "build_quality_report": ".quality",
    "build_supervision_report": ".supervision",
}


def __getattr__(name):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(name)
    from importlib import import_module

    return getattr(import_module(module, __name__), name)


def __dir__():
    return sorted(__all__)
