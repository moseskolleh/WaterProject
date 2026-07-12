"""Data ingestion: standard templates, parsers and consistency checks."""

from .templates import write_all_templates
from .ves import read_ves_workbook, read_ves_csv
from .pumping import read_pumping_workbook, read_pumping_docx
from .drilling import read_drilling_workbook
from .waterquality import read_quality_workbook
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
