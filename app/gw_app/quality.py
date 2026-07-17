"""Water quality tab: standards comparison, diagrams and the report."""

from __future__ import annotations

import streamlit as st

from groundwater.ingestion import read_quality_workbook
from groundwater.quality import assess_sample, plot_piper, plot_stiff
from groundwater.reporting.quality import QualityReportInputs, build_quality_report
from groundwater.supervision import handpump_corrosion_check

from .common import (
    app_config,
    choose_input,
    offer_report_download,
    parse_upload,
    save_upload,
    show_flags,
    workdir,
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
    if path is not None and (sample := parse_upload(read_quality_workbook, path)) is not None:
        assessment = assess_sample(sample)
        st.session_state.wq_assessment = assessment
        show_flags(assessment.flags)
        st.subheader("Verdict")
        if assessment.health_exceedances:
            st.error(assessment.verdict)
        elif assessment.aesthetic_exceedances:
            st.warning(assessment.verdict)
        else:
            st.success(assessment.verdict)

        ph_result = sample.get("pH")
        if ph_result is not None and ph_result.value is not None:
            corrosion = handpump_corrosion_check(ph_result.value)
            if corrosion.passed is False:
                st.warning(f"Handpump corrosion risk ({corrosion.measured}): "
                           f"{corrosion.message}")

        rows = [
            {
                "Parameter": r.parameter,
                "Value": "< DL" if (r.below_detection and r.value is None) else r.value,
                "Unit": r.unit,
                "WHO health": r.who_health,
                "National": r.sl_standard,
                "Status": r.status,
            }
            for r in assessment.rows
        ]
        st.dataframe(rows, use_container_width=True)

        if assessment.ionic is not None:
            st.write(
                f"Ionic balance: cations {assessment.ionic.sum_cations_meq:.2f} meq/L, "
                f"anions {assessment.ionic.sum_anions_meq:.2f} meq/L, "
                f"error {assessment.ionic.error_percent:+.1f}%"
            )
            col1, col2 = st.columns(2)
            piper = workdir() / "piper.png"
            stiff = workdir() / "stiff.png"
            plot_piper([sample], path=piper)
            plot_stiff(sample, path=stiff)
            col1.image(str(piper))
            col2.image(str(stiff))

        if st.button("Build water quality report", key="build_wq_report"):
            report_path = build_quality_report(
                QualityReportInputs(assessment=assessment, figures_dir=workdir()),
                workdir() / "Water_Quality_Report.docx",
                app_config(),
            )
            offer_report_download(report_path, "Download water quality report (.docx)")

    with st.expander("🔬 Compare several samples"):
        st.caption(
            "Upload several laboratory workbooks - different boreholes, or "
            "the same point across seasons - for side by side verdicts, a "
            "combined Piper diagram and a parameter comparison."
        )
        uploads = st.file_uploader(
            "Laboratory results (several files)", type=["xlsx"],
            accept_multiple_files=True, key="wq_multi",
        )
        parsed = []
        for upload in uploads or []:
            saved = save_upload(upload)
            multi_sample = parse_upload(read_quality_workbook, saved)
            if multi_sample is not None:
                parsed.append(
                    (upload.name, multi_sample, assess_sample(multi_sample))
                )
        if parsed:
            st.dataframe(
                [
                    {
                        "File": name,
                        "Community": smp.site.community if smp.site else "",
                        "Date": smp.sample_date
                        or (smp.site.date if smp.site else ""),
                        "Verdict": a.verdict,
                        "Health exceedances": len(a.health_exceedances),
                        "Aesthetic": len(a.aesthetic_exceedances),
                    }
                    for name, smp, a in parsed
                ],
                use_container_width=True,
            )
            with_ionic = [smp for _, smp, a in parsed if a.ionic is not None]
            if len(with_ionic) >= 2:
                multi_piper = workdir() / "piper_multi.png"
                plot_piper(with_ionic, path=multi_piper)
                st.image(str(multi_piper))

            parameters: list[str] = []
            for _, smp, _ in parsed:
                for result in smp.results:
                    if result.value is not None and result.parameter not in parameters:
                        parameters.append(result.parameter)
            if parameters:
                if st.session_state.get("wq_trend_param") not in parameters:
                    st.session_state.pop("wq_trend_param", None)
                trend_pick = st.selectbox(
                    "Parameter to compare across the samples",
                    parameters, key="wq_trend_param",
                )
                trend_rows = []
                for name, smp, _ in parsed:
                    result = smp.get(trend_pick)
                    if result is not None and result.value is not None:
                        label = (
                            smp.sample_date
                            or (smp.site.date if smp.site else "")
                            or name
                        )
                        trend_rows.append(
                            {"Sample": label, "Value": float(result.value),
                             "Unit": result.unit}
                        )
                if trend_rows:
                    tc1, tc2 = st.columns([2, 3])
                    tc1.dataframe(trend_rows, use_container_width=True)
                    try:
                        import pandas as pd

                        tc2.bar_chart(
                            pd.DataFrame(trend_rows).set_index("Sample")["Value"]
                        )
                    except Exception:
                        pass  # chart is a nicety; the table stands alone
