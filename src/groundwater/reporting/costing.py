"""Borehole cost estimate report generator.

A short client-ready document: the basis of the estimate, the bill of
quantities, the cost and price roll-up and the assumptions, following
the RWSN Cost-Effective Boreholes methodology (cost first, price
separately, both breakdowns shown).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Config
from ..costing.model import CostEstimate
from ..costing.plots import plot_cost_breakdown
from ..models import SiteMetadata
from ..utils import fmt_num
from .docx_utils import ReportBuilder


@dataclass
class CostReportInputs:
    estimate: CostEstimate
    site: SiteMetadata | None = None
    figures_dir: Path = Path(".")
    prepared_by: str = ""


def build_cost_report(
    inputs: CostReportInputs,
    out_path: str | Path,
    config: Config | None = None,
) -> Path:
    config = config or Config()
    estimate = inputs.estimate
    site = inputs.site or SiteMetadata()
    figures = Path(inputs.figures_dir)
    figures.mkdir(parents=True, exist_ok=True)

    rb = ReportBuilder(
        config.style,
        title=f"Cost Estimate - {site.community or 'Borehole'}",
    )
    rb.cover(
        title_lines=["BOREHOLE COST ESTIMATE"],
        subtitle_lines=[
            f"at {site.community}" + (f", {site.district} District" if site.district else "")
            if site.community
            else "Drilled Water Well Construction",
        ],
        details=[
            ("Client", site.client),
            ("Project", site.project),
            ("Prepared by", inputs.prepared_by or site.contractor),
            ("Date", site.date),
        ],
    )
    rb.table_of_contents()

    # ---- 1 method ------------------------------------------------------
    rb.heading("1. Method", 1)
    rb.paragraph(
        "The estimate follows the Rural Water Supply Network (RWSN) "
        "Cost-Effective Boreholes methodology. Every line item carries a "
        "construction stage and a resource category, so the total can be "
        "broken down both ways. The estimate first establishes the cost "
        "of the works; the contract price is then derived by adding "
        "overheads and a margin, and a separate contingency allowance is "
        "shown for budget planning. Keeping cost and price apart follows "
        "the RWSN guidance for sustainable drilling enterprises.",
        align="justify",
    )
    rb.paragraph(
        "The unit rates are indicative values held in an editable "
        "catalogue and must be confirmed against current local prices "
        "before the estimate is used for contracting.",
        align="justify",
    )

    # ---- 2 basis -------------------------------------------------------
    rb.heading("2. Basis of the Estimate", 1)
    quantities = inputs.estimate.inputs
    rb.table(
        [
            ["Total depth", fmt_num(quantities.total_depth_m) + " m"],
            ["Overburden / hard rock",
             f"{fmt_num(quantities.overburden_m)} m / {fmt_num(quantities.bedrock_m)} m"],
            ["Plain casing / screen",
             f"{fmt_num(quantities.casing_m)} m / {fmt_num(quantities.screen_m)} m "
             f"({quantities.casing_diameter_in:g} inch)"],
            ["Drilled diameter", f"{quantities.borehole_diameter_in:g} inch"],
            ["Gravel packed interval", fmt_num(quantities.gravel_interval_m) + " m"],
            ["Mobilisation distance (one way)",
             fmt_num(quantities.mobilisation_distance_km) + " km"],
            ["Crew time on site", fmt_num(quantities.crew_days) + " days"],
            ["Development / test pumping",
             f"{fmt_num(quantities.development_hours)} h / "
             f"{fmt_num(quantities.test_pumping_hours)} h"],
            ["Water quality samples", fmt_num(quantities.wq_samples)],
            ["Handpumps included", fmt_num(quantities.handpumps)],
        ],
        header=["Quantity driver", "Value"],
        caption="Quantities driving the bill of quantities.",
    )
    if estimate.assumptions:
        rb.paragraph("Assumptions applied where inputs were not supplied:")
        rb.bullets(estimate.assumptions)

    # ---- 3 bill of quantities -------------------------------------------
    rb.heading("3. Bill of Quantities", 1)
    rows = [
        [
            r["Code"],
            r["Item"],
            r["Unit"],
            fmt_num(r["Quantity"]),
            f"{r['Rate (USD)']:,.2f}",
            f"{r['Amount (USD)']:,.2f}",
        ]
        for r in estimate.boq_rows()
    ]
    rb.table(
        rows,
        header=["Code", "Item", "Unit", "Qty", "Rate (USD)", "Amount (USD)"],
        caption="Bill of quantities at the catalogue unit rates.",
    )

    # ---- 4 summary -------------------------------------------------------
    rb.heading("4. Cost Summary", 1)
    rb.table(
        [list(row) for row in estimate.summary_rows()],
        header=["Item", "USD", "SLE"],
        caption=(
            "Cost and price roll-up. Local amounts use an exchange rate "
            f"of {estimate.exchange_rate_sle_per_usd:g} SLE per USD."
        ),
    )
    fig_path = figures / "cost_breakdown.png"
    if not fig_path.exists():
        plot_cost_breakdown(estimate, fig_path, config.style)
    rb.figure(fig_path, "Direct works cost by stage and by resource category.")

    # ---- 5 notes ---------------------------------------------------------
    rb.heading("5. Notes and Exclusions", 1)
    notes = [
        "Unit rates are indicative and must be confirmed against local "
        "supplier and contractor quotations before award.",
        "The estimate covers one production borehole; failed or abandoned "
        "holes, standby time and exceptional ground conditions are not "
        "included and should be covered by the contract conditions.",
        "Land access, community mobilisation and post-construction "
        "monitoring are excluded.",
    ]
    for flag in estimate.flags:
        notes.append(str(flag.message))
    rb.bullets(notes)

    return rb.save(out_path)
