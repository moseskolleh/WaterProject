"""Pumping test tab: parsing, analysis, figures and the report."""

from __future__ import annotations

import streamlit as st

from groundwater.hydraulics import analyse_pumping_test
from groundwater.hydraulics.plots import (
    plot_cooper_jacob,
    plot_recovery,
    plot_step_test,
    plot_test_overview,
)
from groundwater.ingestion import read_pumping_docx, read_pumping_workbook
from groundwater.reporting.pumping import PumpingReportInputs, build_pumping_report
from groundwater.utils import fmt_num

from .common import (
    CONFIG,
    app_config,
    choose_input,
    offer_report_download,
    parse_upload,
    show_flags,
    workdir,
)


def render() -> None:
    st.header("Pumping test analysis")
    st.caption(
        "Constant discharge, step and recovery tests; missing discharges "
        "can be entered here and the yield analysis completes on the spot."
    )
    path = choose_input(
        "Pumping test sheet (template .xlsx or field .docx)", "pump", ["xlsx", "docx"],
        ["dr_timbo/dr_timbo_constant_test.xlsx", "kuntolo/kuntolo_step_test.xlsx"],
    )
    if path is not None:
        test = parse_upload(
            read_pumping_docx if path.suffix == ".docx" else read_pumping_workbook,
            path,
        )
    if path is not None and test is not None:
        st.success(
            f"Parsed {test.test_type} test with {len(test.steps)} pumping series "
            f"and {'a' if test.recovery_time_min is not None else 'no'} recovery record."
        )
        show_flags(test.flags)

        missing = [s for s in test.steps if s.discharge_m3_per_h is None]
        if missing:
            st.info("Enter discharge rates to complete the analysis (m3/h).")
            cols = st.columns(len(test.steps))
            for col, step in zip(cols, test.steps):
                with col:
                    q = st.number_input(
                        f"{step.label} Q", min_value=0.0, value=0.0, step=0.1,
                        key=f"q_{step.step_number}",
                    )
                    if q > 0:
                        step.discharge_m3_per_h = q

        analysis = analyse_pumping_test(test, CONFIG.pumping)
        st.session_state.pump_analysis = analysis

        overview = workdir() / "overview.png"
        plot_test_overview(test, path=overview)
        st.image(str(overview))

        col1, col2 = st.columns(2)
        with col1:
            if analysis.cooper_jacob is not None:
                cj_path = workdir() / "cj.png"
                swl = test.static_water_level_m
                step = test.steps[0]
                plot_cooper_jacob(step.time_min, step.water_level_m - swl,
                                  analysis.cooper_jacob, path=cj_path)
                st.image(str(cj_path))
        with col2:
            if analysis.recovery is not None:
                rec_path = workdir() / "rec.png"
                plot_recovery(test.recovery_time_min, test.residual_drawdown(),
                              test.pumping_duration_min, analysis.recovery, path=rec_path)
                st.image(str(rec_path))
        if test.test_type.startswith("step"):
            st_path = workdir() / "steps.png"
            plot_step_test(test, analysis.step_test, path=st_path)
            st.image(str(st_path))

        st.subheader("Results")
        yr = analysis.yield_recommendation
        cols = st.columns(4)
        cols[0].metric(
            "Transmissivity",
            f"{analysis.transmissivity_m2_per_day:.1f} m2/day"
            if analysis.transmissivity_m2_per_day
            else "pending",
        )
        if yr is not None:
            cols[1].metric(
                "Available drawdown",
                f"{fmt_num(yr.available_drawdown_m)} m" if yr.available_drawdown_m else "n/a",
            )
            cols[2].metric(
                "Safe yield",
                f"{fmt_num(yr.safe_yield_m3_per_h)} m3/h" if yr.safe_yield_m3_per_h else "pending",
            )
            cols[3].metric(
                "Pump depth",
                f"{fmt_num(yr.pump_installation_depth_m)} m"
                if yr.pump_installation_depth_m
                else "pending",
            )
            st.caption(yr.basis)

        if st.button("Build pumping test report", key="build_pump_report"):
            report_path = build_pumping_report(
                PumpingReportInputs(analysis=analysis, figures_dir=workdir()),
                workdir() / "Pumping_Test_Report.docx",
                app_config(),
            )
            offer_report_download(report_path, "Download pumping test report (.docx)")
