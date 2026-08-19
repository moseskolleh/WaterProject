"""Data ingestion: standard templates, parsers and consistency checks."""

from .._lazy import lazy_exports as _lazy_exports
from .checks import check_site_consistency, check_all

__all__ = [
    "write_all_templates",
    "read_ves_workbook",
    "read_ves_csv",
    "read_pumping_workbook",
    "read_pumping_docx",
    "read_drilling_workbook",
    "read_quality_workbook",
    "check_site_consistency",
    "check_all",
]

# Deferred: every reader here opens openpyxl or python-docx, and the
# template writer builds styled workbooks. Importing this package to
# check a site's metadata should not load either. See groundwater._lazy.
_LAZY = {
    "write_all_templates": ".templates",
    "read_ves_workbook": ".ves",
    "read_ves_csv": ".ves",
    "read_pumping_workbook": ".pumping",
    "read_pumping_docx": ".pumping",
    "read_drilling_workbook": ".drilling",
    "read_quality_workbook": ".waterquality",
}

# The submodules stayed reachable as attributes of the package while
# the eager imports bound them; keep that true without importing them.
_LAZY_MODULES = (
    "templates",
    "ves",
    "pumping",
    "drilling",
    "waterquality",
    "checks",
    "common",
)

__getattr__, __dir__ = _lazy_exports(__name__, _LAZY, _LAZY_MODULES)
