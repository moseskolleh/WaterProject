"""Pumping test report generator.

Covers the test details, data quality notes, diagnostic plots, the
aquifer parameters from every applicable method, and the safe yield
recommendation with its full basis. When discharge is missing the
report still carries the drawdown and recovery curves, the stabilised
level and available drawdown, with transmissivity and yield stated as
pending.
"""

from __future__ import annotations

from typing import Any

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import Config
from ..hydraulics.analysis import PumpingTestAnalysis
from ..hydraulics.plots import (
    plot_cooper_jacob,
    plot_recovery,
    plot_step_test,
    plot_test_overview,
    plot_theis,
)
from ..seasonal import MONTH_NAMES
from ..utils import fmt_num, safe_slug
from .citations import GLOSSARY, references_for
from .docx_utils import ReportBuilder


@dataclass
class PumpingReportInputs:
    analysis: PumpingTestAnalysis
    figures_dir: Path
    analyst_name: str = ""
    analyst_role: str = "Hydrogeologist"
    analyst_phone: str = ""
    include_qa_section: bool = True
    #: The certification gate for this report, from
    #: :func:`groundwater.readiness.assess_readiness`. When it is not
    #: certifiable the cover says so; when it is absent nothing is
    #: stamped, so an existing caller is unaffected.
    readiness: Any = None
    #: The seasonal projection from :func:`groundwater.seasonal.seasonal_yield`.
    #: Absent, section 5 reports the single figure as before.
    seasonal: Any = None


def _executive_summary(analysis: PumpingTestAnalysis) -> tuple[list[str], list[str]]:
    """Compose the pumping-test executive summary from the analysis."""
    test = analysis.test
    community = test.site.community or "the site"
    test_name = test.test_type.replace("+", " with ")
    yr = analysis.yield_recommendation
    t = analysis.transmissivity_m2_per_day
    if yr is not None and yr.safe_yield_m3_per_h:
        para = (
            f"A {test_name} pumping test was carried out on the borehole at "
            f"{community}. The recommended safe yield is "
            f"{fmt_num(yr.safe_yield_m3_per_h)} m3/h (safety factor "
            f"{yr.safety_factor:g} applied to the long term yield), with the "
            f"pump intake set at {fmt_num(yr.pump_installation_depth_m)} m "
            "below ground level."
        )
        key = [
            f"Transmissivity: {fmt_num(t)} m2/day." if t else "",
            f"Recommended safe yield: {yr.yield_range_text}.",
            f"Pump installation depth: {fmt_num(yr.pump_installation_depth_m)} m.",
            "Operate within the recommended rate and monitor the pumping level.",
        ]
    else:
        reason = (yr.pending_reason if yr and yr.pending_reason
                  else "the discharge is not recorded")
        para = (
            f"A {test_name} pumping test was carried out on the borehole at "
            f"{community}. The drawdown and recovery curves are valid, but the "
            "transmissivity and safe yield are pending because " + reason + "."
        )
        key = [
            f"Stabilised water level: {fmt_num(analysis.stabilised_level_m)} m."
            if analysis.stabilised_level_m is not None else "",
            f"Yield recommendation pending: {reason}.",
        ]
    return [para], key


def build_pumping_report(
    inputs: PumpingReportInputs,
    out_path: str | Path,
    config: Config | None = None,
) -> Path:
    config = config or Config()
    analysis = inputs.analysis
    test = analysis.test
    site = test.site
    figures = Path(inputs.figures_dir)
    # Qualify figure filenames with the borehole: several reports share one
    # figures directory in an app session, and generation is guarded by an
    # existence check, so fixed names made the second report silently embed
    # the first borehole's curves.
    slug = safe_slug(test.borehole_ref or test.site.community, "bh")
    figures.mkdir(parents=True, exist_ok=True)

    rb = ReportBuilder(config.style, title=f"Pumping Test Report - {site.community}")
    rb.cover(
        title_lines=["PUMPING TEST REPORT"],
        subtitle_lines=[
            f"{test.test_type.replace('+', ' with ').title()} Test",
            f"at {site.community}" + (f", {site.district} District" if site.district else ""),
        ],
        details=[
            ("Client", site.client),
            ("Borehole", test.borehole_ref or "n/a"),
            ("Test date", site.date),
            ("Conducted by", site.supervisor),
        ],
    )
    rb.provisional_stamp(inputs.readiness)

    # ---- executive summary ------------------------------------------------
    exec_paras, exec_key = _executive_summary(analysis)
    rb.executive_summary(exec_paras, exec_key)

    # ---- 1 test details ---------------------------------------------------
    rb.heading("1. Test Details", 1)
    rb.header_block_table(
        [
            ("Community", site.community), ("Client", site.client),
            ("Borehole Ref. No.", test.borehole_ref or ""), ("Date", site.date),
            ("Test type", test.test_type), ("Conducted by", site.supervisor),
            ("Depth of borehole", fmt_num(test.borehole_depth_m) + " m" if test.borehole_depth_m else ""),
            ("Static water level", fmt_num(test.static_water_level_m) + " m" if test.static_water_level_m is not None else ""),
            ("Pump setting", fmt_num(test.pump_setting_m) + " m" if test.pump_setting_m else ""),
            ("Length of each step", fmt_num(test.step_length_min) + " min" if test.step_length_min else ""),
        ]
    )
    discharges = ", ".join(
        f"{s.label}: " + (f"{s.discharge_m3_per_h:g} m3/h" if s.discharge_m3_per_h else "not recorded")
        for s in test.steps
    )
    rb.paragraph(f"Discharge rates: {discharges}.")
    if not test.has_discharge:
        rb.paragraph(
            "The discharge rate was not recorded on the field sheet. The "
            "drawdown and recovery curves below remain valid; transmissivity "
            "and yield results are pending until the discharge is supplied.",
            bold=True,
        )

    # ---- 2 data ------------------------------------------------------------
    rb.heading("2. Field Data", 1)
    rb.paragraph(
        "True drawdown is computed as the measured water level minus the "
        "static water level. The drawdown column recorded on the field sheet "
        "holds the increment between successive readings and is not used "
        "directly. Reading intervals are irregular and are handled as "
        "recorded.",
        align="justify",
    )
    overview_path = figures / f"test_overview_{slug}.png"
    if not overview_path.exists():
        plot_test_overview(test, path=overview_path, style=config.style)
    fig_no = rb.figure(overview_path, "Water level record for the full test including recovery.")
    if analysis.stabilised_level_m is not None:
        rb.paragraph(
            f"The pumped water level stabilised at about "
            f"{fmt_num(analysis.stabilised_level_m)} m (Figure {fig_no})."
        )
    if analysis.max_drawdown_m is not None:
        rb.paragraph(
            f"The maximum drawdown reached {fmt_num(analysis.max_drawdown_m)} m "
            "below the static water level."
        )
    if inputs.include_qa_section and analysis.flags:
        rb.paragraph("Data verification notes:", bold=True)
        rb.bullets([str(f) for f in analysis.flags])

    # ---- 3 analysis ----------------------------------------------------------
    rb.heading("3. Analysis", 1)
    swl = test.static_water_level_m
    section = 0

    if analysis.cooper_jacob is not None:
        section += 1
        cj = analysis.cooper_jacob
        rb.heading(f"3.{section} Cooper-Jacob straight line method", 2)
        step = test.steps[0]
        t = step.time_min
        s = step.water_level_m - swl
        cj_path = figures / f"cooper_jacob_{slug}.png"
        if not cj_path.exists():
            plot_cooper_jacob(t, s, cj, path=cj_path, style=config.style)
        rb.figure(cj_path, "Drawdown against log time with the fitted straight line.")
        rb.paragraph(
            f"The late time slope is {fmt_num(cj.slope_m_per_log_cycle)} m per "
            f"log cycle over {cj.n_points} readings "
            f"(R squared {cj.r_squared:.3f}), giving a transmissivity of "
            f"{fmt_num(cj.transmissivity_m2_per_day)} m2/day at a discharge of "
            f"{fmt_num(cj.discharge_m3_per_h)} m3/h. {cj.u_check}.",
            align="justify",
        )
        if cj.storativity is not None:
            rb.paragraph(
                f"Storativity from the zero drawdown intercept: "
                f"{cj.storativity:.2e} (observation well data)."
            )

    if analysis.theis is not None:
        section += 1
        th = analysis.theis
        rb.heading(f"3.{section} Theis type curve fit", 2)
        step = test.steps[0]
        theis_path = figures / f"theis_fit_{slug}.png"
        if not theis_path.exists():
            plot_theis(step.time_min, step.water_level_m - swl, th, path=theis_path, style=config.style)
        rb.figure(theis_path, "Log-log drawdown with the fitted Theis curve.")
        s_note = "" if th.storativity_reliable else (
            " In a single pumped well storativity trades off against the "
            "effective well radius, so the fitted S is indicative only."
        )
        rb.paragraph(
            f"Least squares fitting of the Theis well function gives "
            f"T = {fmt_num(th.transmissivity_m2_per_day)} m2/day and "
            f"S = {th.storativity:.1e} (RMSE {fmt_num(th.rmse_m)} m).{s_note}",
            align="justify",
        )

    if analysis.recovery is not None:
        section += 1
        rec = analysis.recovery
        rb.heading(f"3.{section} Theis recovery method", 2)
        rec_path = figures / f"recovery_{slug}.png"
        if not rec_path.exists():
            plot_recovery(
                test.recovery_time_min, test.residual_drawdown(),
                test.pumping_duration_min, rec, path=rec_path, style=config.style,
            )
        rb.figure(rec_path, "Residual drawdown against t/t'.")
        rb.paragraph(
            f"The recovery slope is {fmt_num(rec.slope_m_per_log_cycle)} m per "
            f"log cycle (R squared {rec.r_squared:.3f}), giving "
            f"T = {fmt_num(rec.transmissivity_m2_per_day)} m2/day. Residual "
            f"drawdown at the end of monitoring was {fmt_num(rec.residual_at_end_m)} m. "
            "Recovery derived transmissivity is generally the most reliable "
            "single well estimate because it is unaffected by pumping rate "
            "fluctuations and well losses.",
            align="justify",
        )

    if analysis.step_test is not None:
        section += 1
        st = analysis.step_test
        rb.heading(f"3.{section} Step drawdown analysis (Hantush-Bierschenk)", 2)
        st_path = figures / f"step_test_{slug}.png"
        if not st_path.exists():
            plot_step_test(test, st, path=st_path, style=config.style)
        rb.figure(st_path, "Step drawdown data and the specific drawdown fit.")
        rows = [
            [s["step"], fmt_num(s["discharge_m3_per_h"]), fmt_num(s["drawdown_end_m"]),
             fmt_num(s["sw_over_q_day_per_m2"], 3), f"{s['efficiency_percent']:.0f}%"]
            for s in st.steps
        ]
        rb.table(
            rows,
            header=["Step", "Q (m3/h)", "End drawdown (m)", "s/Q (day/m2)", "Efficiency"],
            caption="Step test summary and well efficiency.",
        )
        rb.paragraph(
            f"The drawdown-discharge relationship is s = BQ + CQ2 with "
            f"B = {st.aquifer_loss_B:.3e} day/m2 (aquifer loss) and "
            f"C = {st.well_loss_C:.3e} day2/m5 (well loss), fitted with "
            f"R squared {st.r_squared:.3f}.",
            align="justify",
        )
    elif test.test_type.startswith("step") and not test.has_discharge:
        section += 1
        rb.heading(f"3.{section} Step drawdown analysis", 2)
        step_path = figures / f"step_test_{slug}.png"
        if not step_path.exists():
            plot_step_test(test, None, path=step_path, style=config.style)
        rb.figure(step_path, "Step drawdown curves (discharge pending).")
        rb.paragraph(
            "Hantush-Bierschenk analysis is pending until the discharge of "
            "each step is supplied.",
        )

    # ---- 4 results summary ------------------------------------------------
    rb.heading("4. Results Summary", 1)
    rows = []
    if analysis.cooper_jacob:
        rows.append(["Cooper-Jacob", fmt_num(analysis.cooper_jacob.transmissivity_m2_per_day)])
    if analysis.theis:
        rows.append(["Theis curve fit", fmt_num(analysis.theis.transmissivity_m2_per_day)])
    if analysis.recovery:
        rows.append(["Theis recovery", fmt_num(analysis.recovery.transmissivity_m2_per_day)])
    if rows:
        rb.table(rows, header=["Method", "Transmissivity (m2/day)"],
                 caption="Transmissivity estimates.")
    else:
        rb.paragraph("Transmissivity: pending (discharge not recorded).", bold=True)
    yr = analysis.yield_recommendation
    if yr is not None:
        summary_rows = [
            ["Specific capacity", fmt_num(yr.specific_capacity_m3hr_per_m) + " m3/h per m"
             if yr.specific_capacity_m3hr_per_m else "pending"],
            ["Available drawdown", fmt_num(yr.available_drawdown_m) + " m"
             if yr.available_drawdown_m else "n/a"],
            ["Usable drawdown", fmt_num(yr.usable_drawdown_m) + " m"
             if yr.usable_drawdown_m else "n/a"],
            ["Long term yield", fmt_num(yr.long_term_yield_m3_per_h) + " m3/h"
             if yr.long_term_yield_m3_per_h else "pending"],
            [f"Recommended safe yield (safety factor {yr.safety_factor:g})",
             yr.yield_range_text],
            ["Recommended pump installation depth",
             fmt_num(yr.pump_installation_depth_m) + " m" if yr.pump_installation_depth_m else "pending"],
        ]
        rb.table(summary_rows, header=["Quantity", "Value"], caption="Yield summary.")

    # ---- 5 recommendation ----------------------------------------------------
    rb.heading("5. Yield Recommendation", 1)
    if yr is not None:
        rb.paragraph(yr.basis, align="justify")
        if yr.envelope_basis:
            rb.paragraph(yr.envelope_basis, align="justify")
        if yr.safe_yield_m3_per_h:
            rb.bullets(
                [
                    f"Operate the borehole at no more than "
                    f"{fmt_num(yr.safe_yield_m3_per_h)} m3/h.",
                    f"Install the pump intake at {fmt_num(yr.pump_installation_depth_m)} m "
                    "below ground level.",
                    "Monitor the pumping water level and re-assess the yield if "
                    "the level approaches the pump intake.",
                ]
            )

    seasonal = inputs.seasonal
    if seasonal is not None and seasonal.is_established:
        rb.heading("5.1 Through the year", 2)
        rb.paragraph(
            "A pumping test measures one day. The borehole has to supply the "
            "village on the worst day, and those are months apart: the water "
            "table is recharged through the single wet season, peaks at the "
            "end of it and falls through the dry season to an annual low in "
            "April or May. The same test therefore means different things "
            "depending on when it was run, so the yield is reported here at "
            "each of three water levels rather than at one.",
            align="justify")
        if seasonal.month:
            rb.paragraph(
                f"This test was run in {MONTH_NAMES[seasonal.month - 1]}, the "
                f"{seasonal.season}.")
        elif seasonal.month_note:
            rb.paragraph(
                seasonal.month_note + " The whole annual range is therefore "
                "reserved, which is the conservative reading.", bold=True)
        rb.table(
            [[s.title, f"{s.decline_m:.1f}",
              fmt_num(s.static_water_level_m), fmt_num(s.available_drawdown_m),
              fmt_num(s.safe_yield_m3_per_h),
              fmt_num(s.pump_installation_depth_m)]
             for s in seasonal.scenarios],
            header=["Scenario", "Further decline (m)", "Static level (m)",
                    "Available drawdown (m)", "Safe yield (m3/h)",
                    "Pump intake (m)"],
            caption="Safe yield and pump setting at each seasonal water level",
        )
        rb.paragraph(
            f"The annual range used is {seasonal.annual_range_m:.1f} m - "
            f"{seasonal.range_source}. It is the one number here that a single "
            "test cannot measure, and every figure in the table moves with it.",
            italic=True)
        loss = seasonal.dry_season_loss_percent
        if loss and loss > 1:
            rb.paragraph(
                f"By the end of the dry season the borehole yields about "
                f"{loss:.0f}% less than it did on the day of the test.",
                bold=True)
        rb.bullets([s.note for s in seasonal.scenarios])
        if seasonal.pump_installation_depth_m is not None:
            rb.paragraph(
                "Set the pump intake at "
                f"{fmt_num(seasonal.pump_installation_depth_m)} m below ground "
                "level: deep enough for the drought case, because the pump is "
                "fitted once and a pump that draws air in a bad year loses the "
                "village its borehole in the year it is needed most.",
                bold=True)

    # ---- limitations -----------------------------------------------------------
    rb.heading("6. Limitations and Uncertainty", 1)
    rb.bullets(
        [
            "The analysis assumes a homogeneous, isotropic aquifer of large "
            "extent. A barrier or a recharge (stream or coast) boundary, if "
            "present, changes the late-time drawdown slope and would bias the "
            "transmissivity.",
            "In a single pumped well the storativity trades off against the "
            "effective well radius, so any storativity reported from this test "
            "is indicative only.",
            "The safe yield is projected to the design period from a short "
            "test; it should be confirmed by monitoring the pumping water "
            "level once the borehole is in service.",
            "Yield varies with the season. Section 5.1 projects the tested "
            "level to the annual low and to a drought year, but the size of "
            "the annual swing is assumed rather than measured; two water-level "
            "readings a year apart in this borehole would replace that "
            "assumption with a number.",
        ]
    )

    # ---- references and glossary -----------------------------------------------
    rb.references(references_for("pumping"))
    rb.glossary(GLOSSARY)

    rb.signature_block(
        name=inputs.analyst_name or site.supervisor,
        role=inputs.analyst_role,
        phone=inputs.analyst_phone,
        organisation=config.style.organisation,
    )
    return rb.save(out_path)
