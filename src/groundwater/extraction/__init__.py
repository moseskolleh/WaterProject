"""Scanned field sheet extraction workflow.

Turns scanned field sheets and PDFs into the standard data templates
with low-confidence values flagged for manual review.

Two extraction paths share one output structure
(:class:`~groundwater.extraction.models.ExtractedDocument`):

* :func:`extract_pdf_text` - rule based, for PDFs with a text layer
  (no API key needed).
* :class:`ClaudeExtractor` - AI assisted, for photos and scans
  (requires ``pip install groundwater-toolkit[ai]`` and an Anthropic
  API key).

Both feed :func:`write_review_workbook`, which produces an Excel
review file with uncertain cells highlighted, and (for recognised
document kinds) a filled standard template ready for the parsers.
"""

from .._lazy import lazy_exports as _lazy_exports
from .models import ExtractedDocument, ExtractedField, ExtractedTable, UncertainCell
from .pdf_text import extract_pdf_text
from .review import write_review_workbook, fill_ves_template

__all__ = [
    "ExtractedDocument",
    "ExtractedField",
    "ExtractedTable",
    "UncertainCell",
    "extract_pdf_text",
    "write_review_workbook",
    "fill_ves_template",
    "ClaudeExtractor",
]

# ClaudeExtractor is bound on first use: it needs the optional ``anthropic``
# dependency, and the rest of this package works without it.
_LAZY = {"ClaudeExtractor": ".claude"}
_LAZY_MODULES = ("models", "pdf_text", "review", "claude")

__getattr__, __dir__ = _lazy_exports(__name__, _LAZY, _LAZY_MODULES)
