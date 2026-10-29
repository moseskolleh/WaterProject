"""Write sealed_python.docx: a document python-docx wrote and this toolkit
sealed (PLAN.md step 8.1).

tests/webapp/make_reference.py records what the Python engine says of it,
one digit changed and as written, and parity.mjs has the browser engine
read the same bytes and say the same, so the two are held to one answer on
a package as python-docx and Python's zlib write one. The browser's own
document is fieldkit_browser.docx beside it, which the Python engine reads
the same way.

    python tests/webapp/fixtures/make_sealed_docx.py

The committed file is what both sides read, never a fresh run: python-docx
writes other parts in another version, and zlib builds write other bytes
for the same input, so a fresh document on another machine is another
document. tests/test_verification.py checks that what the builder writes
today has the same parts and facts. Run this only to change the document,
and regenerate reference.json after it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "sealed_python.docx"

#: The day it is issued on, an input like any other.
ISSUED_ON = "2026-10-29"


def build(path: Path) -> Path:
    """The document: a cover, the pumping gate's stamp and one sentence with
    a number in it, issued from one evidence file."""
    from groundwater import verification as V
    from groundwater.readiness import assess_readiness
    from groundwater.reporting.docx_utils import ReportBuilder

    builder = ReportBuilder(title="A sealed document", kind="pumping", config=None,
                            issue=V.Issue(issued_on=ISSUED_ON, evidence=(
                                V.evidence_entry("pumping test sheet", "t.xlsx", b"r"),)))
    builder.cover(["A SEALED DOCUMENT"], ["for parity"], [("Client", "Nobody")])
    builder.provisional_stamp(assess_readiness({}, "pumping"))
    builder.paragraph("The safe yield is 1.25 m3/h.")
    return builder.save(path)


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        data = build(Path(folder) / FIXTURE.name).read_bytes()
    FIXTURE.write_bytes(data)
    print(f"wrote {FIXTURE} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
