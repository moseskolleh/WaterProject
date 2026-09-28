"""Water quality: the laboratory results against the WHO and national limits."""

from __future__ import annotations

import streamlit as st

from groundwater.quality import (
    assess_sample,
    plot_piper,
    plot_stiff,
    PROVISIONAL_NATIONAL_NOTE,
    provisional_national_parameters,
    STATUS_LABELS as WQ_STATUS_LABELS,
    VERDICT_LONG,
)
from groundwater.reporting.quality import build_quality_report, QualityReportInputs
from groundwater.supervision import handpump_corrosion_check

from shared import (
    app_config,
    choose_input,
    figure,
    offer_download,
    parse_source,
    report_gate,
    show_flags,
    workdir,
    _working,
)

def render() -> None:
    st.header("Water quality assessment")
    st.caption(
        "Laboratory results against WHO and national standards, with "
        "ionic balance checks and Piper/Stiff diagrams."
    )
    path = choose_input(
        "Laboratory results (standard template)", "wq", ["xlsx"],
        ["dr_timbo/dr_timbo_water_quality.xlsx"],
    )
    if path is not None and (sample := parse_source("wq", path)[0]) is not None:
        assessment = assessed(sample)
        st.session_state.wq_assessment = assessment
        show_flags(assessment.flags)
        st.subheader("Verdict")
        _state = assessment.verdict_state
        st.markdown(f"**{VERDICT_LONG[_state]}**")
        if _state in ("health_fail", "national_fail"):
            st.error(assessment.verdict)
        elif _state == "indeterminate":
            # Not a warning and never a success: the toolkit is saying it
            # cannot tell, and the operator has to resolve that before the
            # supply is signed off.
            st.info(assessment.verdict)
        elif _state == "aesthetic":
            st.warning(assessment.verdict)
        else:
            st.success(assessment.verdict)

        ph_result = sample.get("pH")
        if ph_result is not None and ph_result.value is not None:
            corrosion = handpump_corrosion_check(ph_result.value)
            if corrosion.passed is False:
                st.warning(f"Handpump corrosion risk ({corrosion.measured}): "
                           f"{corrosion.message}")

        def _wq_value(r) -> str:
            """One text column: mixing floats with "< DL" breaks Arrow."""
            if r.value is None:
                return "< DL" if r.below_detection else ""
            # 10 significant figures: lossless for laboratory values while
            # keeping binary-float artefacts (0.30000000000000004) out
            return f"{r.value:.10g}"

        rows = [
            {
                "Parameter": r.parameter,
                "Value": _wq_value(r),
                "Unit": r.unit,
                "WHO health": r.who_health,
                "National": r.sl_standard,
                "Status": WQ_STATUS_LABELS.get(r.status, r.status),
            }
            for r in assessment.rows
        ]
        st.dataframe(rows, width="stretch")

        # A national exceedance reads as a compliance failure, so say plainly
        # when the limit it was judged against is not yet confirmed.
        if provisional := provisional_national_parameters():
            st.warning(
                f"{PROVISIONAL_NATIONAL_NOTE}\n\n"
                f"Unconfirmed: {', '.join(provisional)}."
            )

        if assessment.ionic is not None:
            st.write(
                f"Ionic balance: cations {assessment.ionic.sum_cations_meq:.2f} meq/L, "
                f"anions {assessment.ionic.sum_anions_meq:.2f} meq/L, "
                f"error {assessment.ionic.error_percent:+.1f}%"
            )
            col1, col2 = st.columns(2)
            col1.image(str(figure(plot_piper, [sample], file_name="piper.png")))
            col2.image(str(figure(plot_stiff, sample, file_name="stiff.png")))

        _quality_gate = report_gate("quality")
        if st.button("Build water quality report", key="build_wq_report"):
          with _working("Building the water quality report - drawing the Piper and Stiff diagrams..."):
            report_path = build_quality_report(
                QualityReportInputs(assessment=assessment, figures_dir=workdir(),
                                    readiness=_quality_gate),
                workdir() / "Water_Quality_Report.docx",
                app_config(),
            )
          offer_download(report_path, "Download water quality report (.docx)")


@st.cache_data(show_spinner=False, max_entries=16)
def assessed(sample):
    """The assessment of a sample, once for each distinct set of results."""
    return assess_sample(sample)
