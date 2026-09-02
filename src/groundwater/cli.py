"""``groundwater``: the toolkit from the command line, for batch use.

The apps do one borehole at a time. An office that has to re-run forty saved
projects after a standards-table update, pool them into a programme table,
or hand a field team a fresh set of templates should not have to open each
file in a browser. Everything here is a thin wrapper over the same library
calls the apps make; nothing is computed differently.

    groundwater recompute PROJECT.yaml [--json OUT] [--sample-root DIR]
    groundwater portfolio FILES... [--csv OUT] [--map OUT.png]
    groundwater templates DIR
    groundwater extract FILE.pdf [--out DIR]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Sequence


def _summary_of(updates: dict) -> dict:
    """The headline numbers a batch run wants, from recomputed session updates."""
    out: dict = {}
    analysis = updates.get("pump_analysis")
    if analysis is not None:
        yr = analysis.yield_recommendation
        out["pumping"] = {
            "transmissivity_m2_per_day": analysis.transmissivity_m2_per_day,
            "transmissivity_source": analysis.transmissivity_source,
            "safe_yield_m3_per_h": yr.safe_yield_m3_per_h if yr else None,
            "pending_reason": yr.pending_reason if yr else "",
            "flags": [f.code for f in analysis.flags],
        }
    assessment = updates.get("wq_assessment")
    if assessment is not None:
        out["water_quality"] = {
            "verdict": assessment.verdict_state,
            "missing_essential": list(assessment.missing_essential),
        }
    design = updates.get("borehole_design")
    if design is not None:
        out["design"] = {
            "total_depth_m": design.total_depth_m,
            "screens": [(s.top_m, s.bottom_m) for s in design.screens],
            "flags": [f.code for f in design.flags],
        }
    ves = updates.get("ves_results")
    if ves is not None:
        soundings, results, interps = ves
        out["ves"] = [
            {
                "sounding": s.sounding_id,
                "layers": r.model.n_layers,
                "fit_error_percent": r.fit_error_percent,
                "max_drilling_depth_m": i.max_drilling_depth_m,
            }
            for s, r, i in zip(soundings, results, interps, strict=True)
        ]
    return out


def cmd_recompute(args: argparse.Namespace) -> int:
    """Rebuild a saved project's analyses and report every issue on one line."""
    from .project_io import deserialize_project
    from .recompute import recompute_results

    project = Path(args.project)
    updates = deserialize_project(project.read_bytes())
    sources = updates.get("sources") or {}
    if not sources:
        print(f"{project.name}: no data sources are saved in this file", file=sys.stderr)
        return 1
    discharges = {
        key[len("q_"):]: value
        for key, value in updates.items()
        if key.startswith("q_") and isinstance(value, (int, float)) and value
    }
    results = recompute_results(
        sources,
        discharges=discharges,
        design_swl=updates.get("design_swl"),
        sample_root=args.sample_root,
        tmp_dir=args.tmp_dir,
    )
    diagnostics = results.get("recompute_diagnostics") or {"ok": [], "issues": []}
    for label in diagnostics.get("ok", []):
        print(f"ok: {label}")
    worst = 0
    for issue in diagnostics.get("issues", []):
        record = issue.as_dict() if hasattr(issue, "as_dict") else dict(issue)
        print(f"{record['level']}: {record['label']}: {record['message']}")
        if record["level"] == "error":
            worst = 1
    summary = _summary_of(results)
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        print(f"summary written to {args.json}")
    else:
        for section, values in summary.items():
            print(f"{section}: {json.dumps(values, default=str)}")
    return worst


def cmd_portfolio(args: argparse.Namespace) -> int:
    """Pool saved project files into a comparison table and headline figures."""
    from .portfolio import portfolio_rows, portfolio_stats
    from .project_io import deserialize_project

    summaries = []
    skipped = []
    for name in args.files:
        path = Path(name)
        try:
            updates = deserialize_project(path.read_bytes())
        except (OSError, ValueError) as exc:
            skipped.append(f"{path.name}: {exc}")
            continue
        summary = updates.get("summary")
        if isinstance(summary, dict) and summary:
            summaries.append(summary)
        else:
            skipped.append(f"{path.name}: no summary block (save it again from the app)")
    for line in skipped:
        print(f"skipped {line}", file=sys.stderr)
    if not summaries:
        print("no readable project files", file=sys.stderr)
        return 1
    rows = portfolio_rows(summaries)
    stats = portfolio_stats(summaries)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"{len(rows)} rows written to {args.csv}")
    else:
        for row in rows:
            print("  ".join(f"{k}={v}" for k, v in row.items() if v not in (None, "")))
    for key in ("n_projects", "n_drilled", "n_successful", "success_rate",
                "mean_safe_yield_m3_per_h", "mean_cost_per_meter_usd",
                "wq_compliant_rate", "n_values_unreadable"):
        print(f"{key}: {stats.get(key)}")
    if args.map:
        from .mapping import plot_portfolio_map
        from .portfolio import portfolio_points

        plot_portfolio_map(portfolio_points(summaries), path=args.map)
        print(f"map written to {args.map}")
    return 0


def cmd_templates(args: argparse.Namespace) -> int:
    """Write every field template into a folder."""
    from .ingestion.templates import write_all_templates

    for path in write_all_templates(args.folder):
        print(path)
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Read a text-layer PDF field sheet into a review workbook."""
    from .extraction import extract_pdf_text, fill_ves_template, write_review_workbook

    source = Path(args.file)
    out_dir = Path(args.out or source.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    document = extract_pdf_text(source)
    review = write_review_workbook(document, out_dir / f"{source.stem}_review.xlsx")
    print(f"{document.document_kind}: review workbook {review}")
    if document.document_kind == "ves" and document.tables:
        filled = fill_ves_template(document, out_dir / f"{source.stem}_ves.xlsx")
        print(f"filled VES template {filled}")
    flagged = sum(len(getattr(table, "uncertain_cells", ())) for table in document.tables)
    if flagged:
        print(f"{flagged} cell(s) need checking; they are marked in the review workbook")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="groundwater",
        description="The Groundwater Investigation Toolkit from the command line.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("recompute", help="rebuild a saved project's analyses")
    p.add_argument("project", help="a project file saved by the app (.yaml)")
    p.add_argument("--json", help="write the headline results to this JSON file")
    p.add_argument("--sample-root", help="folder holding the bundled sample workbooks, "
                   "for a project that references one")
    p.add_argument("--tmp-dir", default=".", help="where saved sources are unpacked")
    p.set_defaults(func=cmd_recompute)

    p = sub.add_parser("portfolio", help="pool saved project files")
    p.add_argument("files", nargs="+", help="project files (.yaml or .gwt.json)")
    p.add_argument("--csv", help="write the comparison table here")
    p.add_argument("--map", help="write a status map (PNG) here")
    p.set_defaults(func=cmd_portfolio)

    p = sub.add_parser("templates", help="write the field templates")
    p.add_argument("folder")
    p.set_defaults(func=cmd_templates)

    p = sub.add_parser("extract", help="read a text-layer PDF field sheet")
    p.add_argument("file")
    p.add_argument("--out", help="folder for the review workbook (default: beside the PDF)")
    p.set_defaults(func=cmd_extract)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover - exercised through __main__
    sys.exit(main())
