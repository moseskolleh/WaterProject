"""VES survey tab: inversion, interpretation and the survey report."""

from __future__ import annotations

import streamlit as st

from groundwater.ingestion import check_all, read_ves_workbook
from groundwater.reporting.geophysical import (
    GeophysicalReportInputs,
    build_geophysical_report,
)
from groundwater.ves.interpret import drilling_preference_table
from groundwater.ves.plots import plot_sounding_curve

from .common import (
    app_config,
    choose_input,
    offer_report_download,
    parse_upload,
    run_ves_inversion,
    show_flags,
    workdir,
)


def render() -> None:
    st.header("VES survey analysis")
    st.caption(
        "Upload the VES workbook, run the inversion and get sounding "
        "curves, water zones and a drilling preference table."
    )
    path = choose_input(
        "VES workbook (standard template)", "ves", ["xlsx"],
        ["rokel/rokel_ves.xlsx"],
    )
    if path is not None:
        soundings = parse_upload(read_ves_workbook, path)
        if soundings is None:
            pass
        elif not soundings:
            st.error("No soundings found in the workbook.")
        else:
            st.success(f"Parsed {len(soundings)} sounding(s).")
            for s in soundings:
                show_flags(s.flags)
            show_flags(check_all([(s.sounding_id, s.site) for s in soundings]))

            if st.button("Run inversion and interpretation", key="run_ves",
                         type="primary"):
                run_ves_inversion(soundings)

    if "ves_results" in st.session_state:
        soundings, results, interps = st.session_state.ves_results
        for sounding, result, interp in zip(soundings, results, interps):
            with st.container(border=True):
                st.subheader(f"{sounding.sounding_id}")
                col_fig, col_txt = st.columns([3, 2])
                fig_path = workdir() / f"curve_{sounding.sounding_id.replace(' ', '_')}.png"
                plot_sounding_curve(
                    sounding, result.model, result.rho_calc, result.ab2, path=fig_path
                )
                col_fig.image(str(fig_path))
                col_txt.metric("Model fit (ERR)", f"{result.fit_error_percent:.1f}%")
                col_txt.metric(
                    "Water bearing zones",
                    ", ".join(f"{int(t)}-{int(b)} m" for t, b in interp.water_zones)
                    or "none",
                )
                col_txt.write(interp.narrative)
        st.subheader("Drilling preference")
        st.table(drilling_preference_table(interps))

        if st.button("Build geophysical survey report", key="build_geo_report"):
            report_path = build_geophysical_report(
                GeophysicalReportInputs(
                    soundings=soundings,
                    inversions=results,
                    interpretations=interps,
                    figures_dir=workdir(),
                    flags=check_all([(s.sounding_id, s.site) for s in soundings]),
                    include_qa_annex=True,
                ),
                workdir() / "Geophysical_Survey_Report.docx",
                app_config(),
            )
            offer_report_download(report_path, "Download geophysical survey report (.docx)")
