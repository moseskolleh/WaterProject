"""Borehole design tab: as-built design from the drilling log."""

from __future__ import annotations

import streamlit as st

from groundwater.design import design_borehole, draw_borehole_design
from groundwater.ingestion import read_drilling_workbook
from groundwater.supervision import annular_space_check

from .common import (
    CONFIG,
    choose_input,
    offer_download,
    parse_upload,
    show_flags,
    workdir,
)


def render() -> None:
    st.header("Borehole design")
    st.caption(
        "A to-scale construction design from the drilling log, following "
        "the configured design rules."
    )
    path = choose_input(
        "Drilling log (standard template)", "log", ["xlsx"],
        ["dr_timbo/dr_timbo_drilling_log.xlsx"],
    )
    swl_input = st.number_input("Static water level (m)", min_value=0.0, value=0.0, step=0.1)
    if path is not None and (log := parse_upload(read_drilling_workbook, path)) is not None:
        show_flags(log.flags)
        design = design_borehole(
            log=log,
            static_water_level_m=swl_input or None,
            rules=CONFIG.design,
        )
        st.session_state.borehole_design = design
        st.session_state.drilling_log = log
        col_table, col_draw = st.columns([2, 3])
        with col_table:
            st.table(design.summary_rows())
            annulus = annular_space_check(
                design.borehole_diameter_in,
                design.casing_diameter_in * 25.4,
            )
            note = f"Annular space {annulus.measured}: {annulus.message}"
            if annulus.passed:
                st.caption(note)
            else:
                st.warning(note)
        with col_draw:
            drawing = workdir() / "design.png"
            draw_borehole_design(
                design, log, path=drawing,
                title=f"Borehole design - {log.site.community or 'site'}",
            )
            st.image(str(drawing))
            offer_download(drawing, "Download design drawing (.png)")
        st.info(
            "The Costing tab can price this design: casing, screen and "
            "gravel quantities carry over automatically."
        )
