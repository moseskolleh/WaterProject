"""Borehole design: the construction drawing and the completion report."""

from __future__ import annotations

import streamlit as st

from groundwater.design import draw_borehole_design
from groundwater.reporting.completion import (
    build_completion_report,
    CompletionReportInputs,
)
from groundwater.text import phrase
from groundwater.utils import fmt_num

from shared import (
    app_config,
    choose_input,
    figure,
    offer_download,
    page_design,
    parse_source,
    report_gate,
    show_flags,
    workdir,
    _working,
)

def render() -> None:
    st.header("Borehole design")
    st.caption(
        "A to-scale construction design from the drilling log, following "
        "the configured design rules."
    )
    # the co-pilot is a browser page; a feature in one app says so in both
    st.caption(phrase("drilling_copilot.browser_only"))
    path = choose_input(
        "Drilling log (standard template)", "log", ["xlsx"],
        ["dr_timbo/dr_timbo_drilling_log.xlsx"],
    )
    # The pumping test, when the Pumping test page has run one, is what the
    # completion report's design is built from; this page used to ask for a
    # static water level with nothing in the box and pass no pump intake at
    # all, so the intake checks never ran on the design this page hands on and
    # the two pages disagreed about the same borehole.
    _design_analysis = st.session_state.get("pump_analysis")
    _test_swl = (
        _design_analysis.test.static_water_level_m if _design_analysis else None
    )
    # The box shows the level the design uses: the test's, unless the analyst
    # typed another. It was prefilled only when the widget had never run, so
    # opening the app before loading a test left it at 0.0 under a caption
    # saying "Prefilled from the pumping test" while the design used the
    # test's level. shared.refresh_derived fills it in before any page runs,
    # because the test can change while this page is not on screen.
    swl_input = st.number_input("Static water level (m)", min_value=0.0, step=0.1,
                                key="design_swl")
    if _test_swl is not None:
        st.caption(
            f"Prefilled from the pumping test on this project "
            f"({fmt_num(_test_swl)} m). Type over it to design against another level."
        )
    log = parse_source("log", path)[0] if path is not None else None
    # while a log is selected here, the stored design is this page's and
    # follows the pumping test as this page would (shared.refresh_derived)
    st.session_state["_design_follows_page"] = log is not None
    if log is not None:
        show_flags(log.flags)
        design = page_design(log, _design_analysis, swl_input)
        st.session_state.borehole_design = design
        st.session_state.drilling_log = log
        col_table, col_draw = st.columns([2, 3])
        with col_table:
            st.table(design.summary_rows())
            # the annulus rule and the pump-intake checks are on the design
            # itself now, so the report and the browser app see them too
            show_flags(design.flags)
        with col_draw:
            drawing = figure(
                draw_borehole_design, design, log,
                title=("As-built borehole record" if design.as_built else "Borehole design")
                + f" - {log.site.community or 'site'}",
                file_name="design.png",
            )
            st.image(str(drawing))
            offer_download(drawing, "Download design drawing (.png)")
        st.info(
            "The Costing & BoQ page can price this design: casing, screen and "
            "gravel quantities carry over automatically."
        )

        # The completion report is the document the client is handed for the
        # borehole itself, and until now it was the one report the desktop app
        # could not produce - it had to be written from a script.
        st.subheader("Borehole completion report")
        st.caption(
            "Introduction, methodology, the drilling record, the borehole log "
            "table, the as-built construction, the pumping test, the "
            "installation, the water quality summary and the recommendations."
        )
        _completion_gate = report_gate("completion")
        if st.button("Build borehole completion report",
                     key="build_completion_report"):
          with _working("Building the borehole completion report..."):
            report_path = build_completion_report(
                CompletionReportInputs(
                    log=log,
                    design=design,
                    pumping=st.session_state.get("pump_analysis"),
                    quality=st.session_state.get("wq_assessment"),
                    figures_dir=workdir(),
                    readiness=_completion_gate,
                ),
                workdir() / "Borehole_Completion_Report.docx",
                app_config(),
            )
          offer_download(report_path,
                         "Download borehole completion report (.docx)")
