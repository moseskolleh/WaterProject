"""One-click bundle: every report the session has inputs for, zipped."""

from __future__ import annotations

import zipfile
from pathlib import Path

import streamlit as st

from groundwater.ingestion import check_all
from groundwater.reporting.costing import CostReportInputs, build_cost_report
from groundwater.reporting.geophysical import (
    GeophysicalReportInputs,
    build_geophysical_report,
)
from groundwater.reporting.pumping import PumpingReportInputs, build_pumping_report
from groundwater.reporting.quality import QualityReportInputs, build_quality_report
from groundwater.reporting.supervision import (
    SupervisionReportInputs,
    build_supervision_report,
)
from groundwater.supervision import evaluate_checklist

from .common import (
    app_config,
    cached_checklists,
    checklist_responses,
    convert_report_to_pdf,
    site_from_state,
    workdir,
)


def build_available_reports() -> list[Path]:
    """Build every standard report whose inputs exist in session state."""
    cfg = app_config()
    out = workdir()
    built: list[Path] = []

    ves = st.session_state.get("ves_results")
    if ves:
        soundings, results, interps = ves
        built.append(
            build_geophysical_report(
                GeophysicalReportInputs(
                    soundings=soundings,
                    inversions=results,
                    interpretations=interps,
                    figures_dir=out,
                    flags=check_all(
                        [(s.sounding_id, s.site) for s in soundings]
                    ),
                    include_qa_annex=True,
                ),
                out / "Geophysical_Survey_Report.docx",
                cfg,
            )
        )

    analysis = st.session_state.get("pump_analysis")
    if analysis is not None:
        built.append(
            build_pumping_report(
                PumpingReportInputs(analysis=analysis, figures_dir=out),
                out / "Pumping_Test_Report.docx",
                cfg,
            )
        )

    assessment = st.session_state.get("wq_assessment")
    if assessment is not None:
        built.append(
            build_quality_report(
                QualityReportInputs(assessment=assessment, figures_dir=out),
                out / "Water_Quality_Report.docx",
                cfg,
            )
        )

    estimate = st.session_state.get("cost_estimate")
    if estimate is not None:
        built.append(
            build_cost_report(
                CostReportInputs(
                    estimate=estimate,
                    site=site_from_state(),
                    figures_dir=out,
                ),
                out / "Cost_Estimate_Report.docx",
                cfg,
            )
        )

    items = cached_checklists()
    responses = checklist_responses(items)
    sup_assessment = evaluate_checklist(items, responses)
    if sup_assessment.answered:
        site = site_from_state()
        built.append(
            build_supervision_report(
                SupervisionReportInputs(
                    site=site,
                    items=items,
                    responses=responses,
                    assessment=sup_assessment,
                    supervisor=site.supervisor,
                    driller=site.contractor,
                    community_rep=st.session_state.get("meta_community_rep", ""),
                ),
                out / "Supervision_Checklist_Report.docx",
                cfg,
            )
        )

    return built


def build_reports_bundle() -> Path | None:
    """Zip the built reports with the BoQ and every generated figure.

    Returns None when the session has nothing to bundle yet. A handover
    report built in its tab joins the bundle as-is (its committee and
    sign-off inputs live in that tab).
    """
    out = workdir()
    built = build_available_reports()
    docx_files = sorted(set(built) | set(out.glob("*.docx")))
    if not docx_files:
        return None

    include: list[Path] = list(docx_files)
    for report in docx_files:
        pdf = convert_report_to_pdf(report)
        if pdf is not None:
            include.append(pdf)
    boq = out / "Bill_of_Quantities.xlsx"
    if boq.exists():
        include.append(boq)
    include.extend(sorted(out.glob("*.png")))

    slug = (
        (st.session_state.get("meta_community") or "groundwater")
        .replace(" ", "_")
    )
    bundle_path = out / f"{slug}_reports.zip"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in include:
            zf.write(path, arcname=path.name)
    return bundle_path
