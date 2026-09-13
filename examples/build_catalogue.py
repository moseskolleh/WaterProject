"""Index the worked examples, and pack each one up.

Somebody deciding whether this toolkit is worth their time reads an
example before they read the code, and the first question they ask of a
generated report is whether it is arguing from anything. So the index
this writes is built from the files themselves rather than from a
description of them: the counts come back out of the workbook readers,
and the verdict on each report comes out of the .docx the example
actually published - a report stamped provisional says so here, because
it says so on its own cover.

That is the point of the exercise. The Kuntoloh sheet has no discharge
written on it and the Dr Timbo sheets carry no GPS fix, which is what
field data is like; an index that quietly rounded those up to
"complete" would be advertising something the toolkit does not do.

Each case is also packed into a single zip - inputs, reports, figures
and derived tables - so a case can be handed over in one file. The
packs are built rather than committed: every file in them is already in
the repository, and they are byte-reproducible, so there is nothing to
be gained by storing a second copy.

Run from the repository root, after the three run scripts:

    python examples/build_catalogue.py             # index and packs
    python examples/build_catalogue.py --check     # verify the index
    python examples/build_catalogue.py --previews  # also render PDFs

``--previews`` needs LibreOffice (``soffice``/``libreoffice``, or the
path in ``GWT_SOFFICE``). It is skipped with a reason when there is
none, and nothing depends on its output.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))

from groundwater import Project  # noqa: E402
from groundwater.ingestion import (  # noqa: E402
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from groundwater.readiness import REQUIREMENTS  # noqa: E402
from groundwater.ves import read_ipi2win_models  # noqa: E402

CATALOGUE = HERE / "CATALOGUE.md"
PACKS = HERE / "packs"

# The worked cases, in the order somebody should read them: a siting survey,
# then a test whose result is pending, then a borehole all the way to handover.
# Each names the script that produces it and the workbooks it is produced from,
# so the counts below are recounted from the real files rather than repeated
# from a description of them.
CASES = [
    {
        "key": "rokel",
        "title": "Rokel - geophysical survey",
        "script": "run_rokel_geophysics.py",
        "shows": "Parse, consistency checks, inversion against the original "
                 "IPI2Win models, hydrogeological interpretation and a "
                 "drilling preference order.",
        "inputs": [("ves", "rokel/rokel_ves.xlsx"),
                   ("ipi2win", "rokel/rokel_ipi2win_models.xlsx")],
    },
    {
        "key": "kuntolo",
        "title": "Kuntoloh - step drawdown test",
        "script": "run_kuntolo_step_test.py",
        "shows": "The pending-yield path: curves and available drawdown now, "
                 "transmissivity and yield once somebody supplies the "
                 "discharges the sheet never recorded.",
        "inputs": [("pumping", "kuntolo/kuntolo_step_test.xlsx")],
    },
    {
        "key": "dr_timbo",
        "title": "Dr Timbo - drilling to handover",
        "script": "run_dr_timbo_completion.py",
        "shows": "Drilling log to borehole design and drawing, constant "
                 "discharge test, water quality assessment, and the "
                 "completion, quality and handover reports.",
        "inputs": [("drilling", "dr_timbo/dr_timbo_drilling_log.xlsx"),
                   ("pumping", "dr_timbo/dr_timbo_constant_test.xlsx"),
                   ("quality", "dr_timbo/dr_timbo_water_quality.xlsx")],
    },
]

# What a report's own cover says about itself. A report the gate passed
# carries no stamp at all, which is the only way to read "certifiable" off a
# document rather than off a fresh run of the code that wrote it.
STAMPS = [
    ("PROVISIONAL - NOT FOR CERTIFICATION", "provisional"),
    ("ISSUED ON OVERRIDE - NOT A CERTIFICATION", "issued on override"),
]


def count_inputs(role: str, path: Path) -> str:
    """What a workbook holds, according to the reader that reads it."""
    if role == "ves":
        soundings = read_ves_workbook(path)
        readings = sum(s.n_readings for s in soundings)
        return f"{len(soundings)} sounding(s), {readings} reading(s)"
    if role == "pumping":
        test = read_pumping_workbook(path)
        times, _ = test.all_times_levels()
        bits = [f"{test.test_type} test", f"{len(times)} water level reading(s)"]
        if test.steps:
            bits.append(f"{len(test.steps)} step(s)")
        if not test.has_discharge:
            bits.append("no discharge on the sheet")
        if test.flags:
            bits.append(f"{len(test.flags)} flag(s) raised by the reader")
        return ", ".join(bits)
    if role == "drilling":
        log = read_drilling_workbook(path)
        return (f"{len(log.intervals)} lithological interval(s) to "
                f"{log.total_depth_m:g} m")
    if role == "quality":
        sample = read_quality_workbook(path)
        return f"{len(sample.results)} determinand(s)"
    if role == "ipi2win":
        models = read_ipi2win_models(path)
        layers = sum(m.n_layers for m in models.values())
        return f"{len(models)} original model(s), {layers} layer(s)"
    raise ValueError(f"no reader for {role!r}")


def report_text(path: Path) -> str:
    """The visible text of a .docx, near enough to read a cover off."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", xml.replace("</w:p>", "\n"))


def verdict(path: Path) -> str:
    text = report_text(path)
    for marker, label in STAMPS:
        if marker in text:
            return label
    return "certifiable"


# The gate's requirement titles, so what the cover lists is matched against
# what a requirement is actually called rather than against anything in the
# document that happens to be shaped like "Label: value".
TITLES = {title for title, _ in REQUIREMENTS.values()}


def outstanding(path: Path) -> list[str]:
    """The requirements a stamped report lists as outstanding, by title.

    Read from the stamp itself, which sits between the stamp title and the
    table of contents: the bullets there are the gate's own words for what
    the report is missing.
    """
    text = report_text(path)
    start = min((text.index(m) for m, _ in STAMPS if m in text), default=-1)
    if start < 0:
        return []
    end = text.find("Table of Contents", start)
    block = text[start:end if end > 0 else len(text)]
    found = [line.split(":", 1)[0].strip() for line in block.split("\n")
             if ":" in line and line.split(":", 1)[0].strip() in TITLES]
    return sorted(set(found))


def survey(case: dict) -> dict:
    """Everything the index says about one case, read off the files."""
    project = Project.open(HERE / "projects" / case["key"])
    reports = sorted(project.reports.glob("*.docx"))
    figures = sorted(project.figures.glob("*.png"))
    tables = sorted(project.processed.glob("*.csv")) if project.processed.exists() else []
    return {
        "case": case,
        "site": project.site,
        "inputs": [(role, HERE / "data" / rel, count_inputs(role, HERE / "data" / rel))
                   for role, rel in case["inputs"]],
        "reports": [(p, verdict(p), outstanding(p)) for p in reports],
        "figures": figures,
        "tables": tables,
    }


def pack(entry: dict) -> Path:
    """One zip per case: what went in, and everything that came out.

    Fixed timestamps and sorted entries, the same trick the .docx writer
    uses, so the same inputs always produce the same bytes and a pack can be
    compared rather than merely rebuilt.
    """
    PACKS.mkdir(parents=True, exist_ok=True)
    out = PACKS / f"{entry['case']['key']}.zip"
    root = HERE / "projects" / entry["case"]["key"]
    members: list[tuple[str, Path]] = [("project.yaml", root / "project.yaml")]
    for _, path, _ in entry["inputs"]:
        members.append((f"data/{path.name}", path))
    for path, _, _ in entry["reports"]:
        members.append((f"reports/{path.name}", path))
    for path in entry["figures"]:
        members.append((f"figures/{path.name}", path))
    for path in entry["tables"]:
        members.append((f"processed/{path.name}", path))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(members):
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, path.read_bytes())
    return out


def soffice() -> str | None:
    """LibreOffice, if this machine has one that can convert a document."""
    named = os.environ.get("GWT_SOFFICE")
    for candidate in (named, "soffice", "libreoffice"):
        if candidate and shutil.which(candidate):
            return shutil.which(candidate)
    return None


def previews(entries: list[dict], binary: str) -> list[Path]:
    """A PDF of every report, for reading page breaks and captions on screen."""
    out_dir = PACKS / "previews"
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for entry in entries:
        for path, _, _ in entry["reports"]:
            result = subprocess.run(
                [binary, "--headless", "--convert-to", "pdf",
                 "--outdir", str(out_dir), str(path)],
                capture_output=True, text=True, timeout=300, check=False)
            pdf = out_dir / (path.stem + ".pdf")
            if pdf.exists():
                made.append(pdf)
            else:
                print(f"  ! {path.name}: {(result.stderr or result.stdout).strip()[:120]}")
    return made


def render(entries: list[dict]) -> str:
    """The index, as Markdown."""
    lines = [
        "# Worked examples",
        "",
        "Generated by `python examples/build_catalogue.py`. Every count below",
        "is read back out of the workbook by the reader the toolkit uses, and",
        "every verdict is read off the report's own cover.",
        "",
        f"{len(entries)} case(s). `examples/README.md` says which parts of each",
        "dataset are transcribed from a real document and which are illustrative;",
        "read it before quoting a number out of a generated report.",
        "",
    ]
    for entry in entries:
        case, site = entry["case"], entry["site"]
        lines += [
            f"## {case['title']}",
            "",
            f"`python examples/{case['script']}` -> `examples/projects/{case['key']}/`",
            "",
            case["shows"],
            "",
            f"- Site: {site.community or '-'}"
            + (f", {site.district} district" if site.district else "")
            + (f" ({site.client})" if site.client else ""),
            "- Inputs:",
        ]
        for role, path, counted in entry["inputs"]:
            lines.append(f"  - `{path.name}` ({role}): {counted}")
        lines.append("- Reports:")
        for path, said, items in entry["reports"]:
            note = f" - outstanding: {', '.join(items)}" if items else ""
            lines.append(f"  - `{path.name}`: {said}{note}")
        lines.append(
            f"- Figures: {len(entry['figures'])}"
            + (f"; derived tables: {len(entry['tables'])}" if entry["tables"] else "")
        )
        lines.append("")
    lines += [
        "## Packs",
        "",
        "`python examples/build_catalogue.py` writes one zip per case into",
        "`examples/packs/`, holding the input workbooks, the reports, the",
        "figures and any derived tables. They are built rather than committed:",
        "every file in them is already in the repository, and they are",
        "byte-reproducible, so a second copy would only go stale.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="compare the committed index against a fresh run instead of "
             "rewriting it; exit non-zero if it is out of date",
    )
    parser.add_argument(
        "--previews", action="store_true",
        help="also render each report to PDF (needs LibreOffice)",
    )
    args = parser.parse_args()

    entries = [survey(case) for case in CASES]
    index = render(entries)

    if args.check:
        if not CATALOGUE.exists():
            print(f"{CATALOGUE} is missing; run this without --check to create it")
            return 1
        if CATALOGUE.read_text(encoding="utf-8") != index:
            print(f"{CATALOGUE} is out of date. Regenerate it with:\n"
                  "  python examples/build_catalogue.py")
            return 1
        print(f"{CATALOGUE} agrees with the published examples "
              f"({len(entries)} case(s))")
        return 0

    CATALOGUE.write_text(index, encoding="utf-8")
    print(f"wrote {CATALOGUE} ({len(entries)} case(s))")
    for entry in entries:
        out = pack(entry)
        print(f"  {out.relative_to(REPO)} ({out.stat().st_size / 1024:.0f} KB, "
              f"{len(entry['reports'])} report(s), {len(entry['figures'])} figure(s))")

    if args.previews:
        binary = soffice()
        if not binary:
            print("previews skipped: no LibreOffice on this machine. Install "
                  "libreoffice-writer, or point GWT_SOFFICE at a soffice "
                  "binary, and run again.")
        else:
            made = previews(entries, binary)
            print(f"  {len(made)} PDF preview(s) in {PACKS / 'previews'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
