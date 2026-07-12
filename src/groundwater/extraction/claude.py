"""AI assisted extraction of scanned field sheets with Claude.

Sends the scan (image or PDF) to the Claude API and gets back the
header fields and data tables as structured JSON with a confidence per
value, which feeds the same review workflow as the rule based path.

Requires the optional dependency (``pip install
groundwater-toolkit[ai]``) and an Anthropic API key (the SDK reads
``ANTHROPIC_API_KEY`` from the environment).
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from .models import (
    ExtractedDocument,
    ExtractedField,
    ExtractedTable,
    UncertainCell,
)

_MODEL = "claude-opus-4-8"

_SCHEMA = {
    "type": "object",
    "properties": {
        "document_kind": {
            "type": "string",
            "enum": ["ves", "pumping_test", "drilling_log", "water_quality", "unknown"],
        },
        "header": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {
                        "type": "number",
                        "description": "0 to 1; below 0.85 means needs manual review",
                    },
                },
                "required": ["name", "value", "confidence"],
                "additionalProperties": False,
            },
        },
        "tables": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "columns": {"type": "array", "items": {"type": "string"}},
                    "rows": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "required": ["title", "columns", "rows"],
                "additionalProperties": False,
            },
        },
        "uncertain_cells": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "table_index": {"type": "integer"},
                    "row": {"type": "integer"},
                    "column": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["table_index", "row", "column", "reason"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["document_kind", "header", "tables", "uncertain_cells", "notes"],
    "additionalProperties": False,
}

_PROMPT = """You are transcribing a groundwater field data sheet from Sierra Leone
(vertical electrical sounding, pumping test, drilling log or water quality
laboratory sheet).

Extract:
1. document_kind: which sheet type this is.
2. header: every label/value pair from the header block (community, client,
   district, date, borehole reference, static water level, GPS coordinates,
   elevation, supervisor and so on). Use the label wording from the sheet.
3. tables: every data table, with its column headings and every row, in
   order. Transcribe numbers exactly as written, including leading zeros
   (for example 078.7). Do not invent values for illegible cells; write an
   empty string and flag the cell.
4. uncertain_cells: every table cell you are not fully certain about
   (handwriting hard to read, smudges, ambiguous digits), with a short
   reason. Indices are zero based; row counts data rows only.
5. Give each header field a confidence between 0 and 1. Use values below
   0.85 whenever a reasonable person could read the handwriting differently.

Accuracy matters more than completeness: flag anything doubtful rather than
guessing silently."""


class ClaudeExtractor:
    """Extract field sheet content from scans using the Claude API."""

    def __init__(self, model: str = _MODEL, api_key: str | None = None):
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "AI extraction needs the anthropic SDK; install with "
                "'pip install groundwater-toolkit[ai]'"
            ) from exc
        self._anthropic = anthropic
        self.model = model
        self.client = (
            anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        )

    # ------------------------------------------------------------------

    def extract(self, path: str | Path) -> ExtractedDocument:
        """Extract a scanned sheet (PNG, JPEG, WebP, GIF or PDF)."""
        path = Path(path)
        media_type = mimetypes.guess_type(path.name)[0] or "application/pdf"
        data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")

        if media_type == "application/pdf":
            source_block = {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": data,
                },
            }
        elif media_type.startswith("image/"):
            source_block = {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": data},
            }
        else:
            raise ValueError(f"Unsupported file type for extraction: {media_type}")

        response = self.client.messages.create(
            model=self.model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": [source_block, {"type": "text", "text": _PROMPT}],
                }
            ],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError(
                "The extraction request was declined by the model; check the "
                "document content."
            )
        text = next(b.text for b in response.content if b.type == "text")
        payload = json.loads(text)
        return self._to_document(payload, str(path))

    # ------------------------------------------------------------------

    @staticmethod
    def _to_document(payload: dict, source: str) -> ExtractedDocument:
        header = [
            ExtractedField(
                name=f.get("name", ""),
                value=f.get("value", ""),
                confidence=float(f.get("confidence", 0.5)),
            )
            for f in payload.get("header", [])
        ]
        tables = [
            ExtractedTable(
                title=t.get("title", f"Table {i + 1}"),
                columns=[str(c) for c in t.get("columns", [])],
                rows=[[str(c) for c in row] for row in t.get("rows", [])],
            )
            for i, t in enumerate(payload.get("tables", []))
        ]
        uncertain = [
            UncertainCell(
                table_index=int(c.get("table_index", 0)),
                row=int(c.get("row", 0)),
                column=int(c.get("column", 0)),
                reason=c.get("reason", ""),
            )
            for c in payload.get("uncertain_cells", [])
        ]
        return ExtractedDocument(
            source=source,
            document_kind=payload.get("document_kind", "unknown"),
            header=header,
            tables=tables,
            uncertain_cells=uncertain,
            notes=payload.get("notes", ""),
            extractor="claude",
        )
