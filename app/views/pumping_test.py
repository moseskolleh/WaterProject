"""Pumping test: the yield, the pump intake and the seasonal projection."""

from __future__ import annotations

import streamlit as st

from groundwater.hydraulics import analyse_pumping_test
from groundwater.hydraulics.analysis import (
    METHOD_LABELS,
    pump_intake_depth,
    test_type_text,
)
from groundwater.hydraulics.plots import (
    plot_cooper_jacob,
    plot_diagnostic,
    plot_recovery,
    plot_step_test,
    plot_test_overview,
)
from groundwater.hydraulics.spread import (
    diagnostic_text,
    diagnostic_thresholds_text,
    papadopulos_cooper_text,
    spread_paragraphs,
)
from groundwater.reporting.pumping import build_pumping_report, PumpingReportInputs
from groundwater.seasonal import MONTH_NAMES, month_of, seasonal_yield
from groundwater.text import phrase
from groundwater.utils import fmt_num

from field_kit_panel import field_kit_panel
from shared import (
    app_config,
    _band,
    choose_input,
    CONFIG,
    figure,
    _next_step,
    offer_download,
    parse_source,
    report_gate,
    show_flags,
    _source_signature,
    workdir,
    _working,
)

def render() -> None:
    st.header("Pumping test analysis")
    st.caption(
        "Constant discharge, step and recovery tests; missing discharges "
        "can be entered here and the yield analysis completes on the spot."
    )
    st.caption(phrase("pumping_copilot.browser_only"))
    path = choose_input(
        "Pumping test sheet (template .xlsx or field .docx)", "pump", ["xlsx", "docx"],
        ["dr_timbo/dr_timbo_constant_test.xlsx", "kuntolo/kuntolo_step_test.xlsx"],
    )
    test = parse_source("pump", path)[0] if path is not None else None
    if test is not None:
        st.success(
            f"Parsed {test_type_text(test.test_type)} with {len(test.steps)} pumping series "
            f"and {'a' if test.recovery_time_min is not None else 'no'} recovery record."
        )
        show_flags(test.flags)

        # The discharge boxes are keyed by step number, so they outlive the
        # sheet they were typed for: opening a second borehole whose sheet
        # also lacks discharges silently reused the first one's rates, and
        # transmissivity, safe yield and pump depth are all proportional to
        # them. Clear them when the source changes - but not on the run a
        # saved project is restored, which brings back both together.
        pump_sig = repr(_source_signature(st.session_state.get("src_pump")))
        if st.session_state.get("pump_source_sig") != pump_sig:
            st.session_state["pump_source_sig"] = pump_sig
            if not st.session_state.get("project_just_loaded"):
                for stale_q in [k for k in list(st.session_state)
                                if k.startswith("q_")]:
                    st.session_state.pop(stale_q, None)

        missing = [s for s in test.steps if s.discharge_m3_per_h is None]
        if missing:
            st.info("Enter discharge rates to complete the analysis (m3/h).")
            cols = st.columns(len(test.steps))
            for col, step in zip(cols, test.steps, strict=True):
                with col:
                    q = st.number_input(
                        f"{step.label} Q", min_value=0.0, value=0.0, step=0.1,
                        key=f"q_{step.step_number}",
                    )
                    if q > 0:
                        step.discharge_m3_per_h = q

        analysis = analysed(test)
        st.session_state.pump_analysis = analysis

        st.image(str(figure(plot_test_overview, test, file_name="overview.png")))

        col1, col2 = st.columns(2)
        with col1:
            if analysis.cooper_jacob is not None:
                swl = test.static_water_level_m
                step = test.steps[0]
                col1.image(str(figure(
                    plot_cooper_jacob, step.time_min, step.water_level_m - swl,
                    analysis.cooper_jacob, file_name="cj.png")))
        with col2:
            if analysis.recovery is not None:
                col2.image(str(figure(
                    plot_recovery, test.recovery_time_min, test.residual_drawdown(),
                    analysis.recovery.pumping_time_min, analysis.recovery,
                    file_name="rec.png")))
        if test.test_type.startswith("step"):
            st.image(str(figure(plot_step_test, test, analysis.step_test,
                                file_name="steps.png")))

        # the flow regime the readings show, and the large-diameter fit that
        # models the casing storage the straight lines read as aquifer
        if analysis.diagnostic is not None:
            st.image(str(figure(plot_diagnostic, analysis.diagnostic,
                                file_name="diagnostic.png")))
        st.caption(diagnostic_text(analysis.diagnostic))
        if analysis.diagnostic is not None:
            st.caption(diagnostic_thresholds_text(CONFIG.pumping))
        if analysis.papadopulos_cooper is not None:
            st.caption(papadopulos_cooper_text(analysis))

        st.subheader("Results")
        yr = analysis.yield_recommendation
        if yr is not None and yr.safe_yield_m3_per_h:
            st.markdown(
                "<div class='gw-callout' style='display:flex;gap:26px;"
                "align-items:center'>"
                "<div><span class='gw-cap'>Recommended safe yield</span>"
                f"<div class='gw-big'>{fmt_num(yr.safe_yield_m3_per_h)} "
                "<small>m³/h</small></div></div>"
                + (
                    "<div><span class='gw-cap'>Pump intake, below the casing top</span>"
                    f"<div class='gw-big'>"
                    f"{fmt_num(yr.pump_installation_depth_m)} "
                    "<small>m</small></div></div>"
                    if yr.pump_installation_depth_m else ""
                )
                + "</div>",
                unsafe_allow_html=True,
            )
            if yr.is_indicative:
                st.warning(yr.confidence_text, icon="⚠️")
            else:
                st.caption(yr.confidence_text)
        if yr is not None and yr.safe_yield_low_m3_per_h is not None:
            st.caption(
                f"Plausible range **{yr.safe_yield_low_m3_per_h:.2g} to "
                f"{yr.safe_yield_high_m3_per_h:.2g} m³/h**. "
                + yr.envelope_basis
            )
        # the bands from the data themselves, beside the assumptions' range
        for line in spread_paragraphs(analysis, CONFIG.pumping):
            st.caption(line)
        cols = st.columns(4)
        cols[0].metric(
            "Transmissivity",
            f"{analysis.transmissivity_m2_per_day:.1f} m2/day"
            if analysis.transmissivity_m2_per_day
            else "pending",
            help="Aquifer productivity class (BGS Africa Groundwater Atlas "
            "bands for basement aquifers). A handpump serving a village "
            "typically needs about 1 m3/h.",
        )
        if analysis.transmissivity_m2_per_day:
            cols[0].caption(
                _band(
                    analysis.transmissivity_m2_per_day,
                    [(1.0, "very low - handpump only, if at all"),
                     (10.0, "low to moderate - ample for a handpump"),
                     (100.0, "moderate to high - could support a small scheme")],
                    "high - motorised supply feasible",
                )
            )
        if yr is not None:
            cols[1].metric(
                "Available drawdown",
                f"{fmt_num(yr.available_drawdown_m)} m" if yr.available_drawdown_m else "n/a",
            )
            cols[2].metric(
                "Safe yield",
                f"{fmt_num(yr.safe_yield_m3_per_h)} m3/h" if yr.safe_yield_m3_per_h else "pending",
                help="Rate the borehole can be pumped at continuously over "
                "the design period, with the safety factor applied. It rests "
                "on assumed storativity and well radius, so design to the "
                "lower end of the range where the supply must not fail.",
            )
            if yr.safe_yield_m3_per_h:
                cols[2].caption(
                    _band(
                        yr.safe_yield_m3_per_h,
                        [(0.5, "below a handpump's working rate"),
                         (1.0, "marginal for a village handpump")],
                        "comfortable for a handpump supply",
                    )
                )
            cols[3].metric(
                "Pump intake",
                f"{fmt_num(yr.pump_installation_depth_m)} m"
                if yr.pump_installation_depth_m
                else "pending",
                help="Below the top of the casing, the datum the levels were "
                "measured from. Set where the drawdown the yield was computed "
                "on exists, and never above the level the test itself reached.",
            )
            st.caption(yr.basis)
            if yr.pump_depth_basis:
                st.caption(yr.pump_depth_basis)
        if analysis.disqualified:
            st.caption(
                "Not adopted for the yield: "
                + "; ".join(f"{METHOD_LABELS[k]} ({v})" for k, v in analysis.disqualified.items())
                + "."
            )

        _through_the_year(test, analysis)

    # printed before a test is run, so it is here whether or not one is loaded
    st.divider()
    field_kit_panel("pump")

    _next_step("Assess water quality →", "Water quality",
               "Yield established. Check the water is safe to drink.")


@st.cache_data(show_spinner=False, max_entries=16)
def analysed(test):
    """The analysis of a test, once for each distinct test and discharges.

    The test is hashed by what it holds, discharges typed on this page
    included, so a rerun that changes neither is not fitted again.
    """
    return analyse_pumping_test(test, CONFIG.pumping)


@st.fragment
def _through_the_year(test, analysis) -> None:
    """The seasonal projection and the report, which rerun on their own.

    The month and the swing change nothing above them, so a change to
    either reruns this part of the page alone. Neither is saved in the
    project file, so the sidebar's Save project, drawn on the last full run,
    does not fall behind. The borehole design follows them (it takes the
    intake the report prints) and is brought up to date on the next full
    run, before any page reads it.
    """
    # --- through the year ------------------------------------------
    # A test measures one day; the borehole has to supply the village on
    # the worst one, and those are months apart.
    st.subheader("Through the year")
    _read_month, _month_note = month_of(test.site.date)
    _choices = [0] + list(range(1, 13))
    _picked = st.selectbox(
        "Month the test was run",
        _choices,
        index=_choices.index(_read_month) if _read_month else 0,
        format_func=lambda m: ("not known" if m == 0 else MONTH_NAMES[m - 1]),
        key="seasonal_month",
        help="The water table is highest at the end of the rains and "
             "lowest in April or May, so when the test was run changes "
             "what it proves. Read from the field sheet where it can be.",
    )
    # not named _band: that is the helper the yield bands above are drawn
    # with, and shadowing it would break them
    _swing = st.number_input(
        "Annual water-table swing (m)",
        min_value=0.0, max_value=30.0, step=0.5,
        value=float(app_config().pumping.seasonal_allowance_m),
        key="seasonal_range",
        help="Wet-season high to dry-season low in this borehole. A single "
             "test cannot measure it; two readings six months apart can. "
             "Every figure below moves with it.",
    )
    if _month_note:
        st.warning(_month_note)
    _seasonal = seasonal_yield(
        analysis, app_config().pumping,
        month=(_picked or None), annual_range_m=_swing)
    if not _seasonal.is_established:
        st.info(_seasonal.pending_reason or
                "The seasonal projection is not available for this test.")
    else:
        st.write(_seasonal.summary)
        st.dataframe(
            [{"Scenario": sc.title,
              "Further decline (m)": round(sc.decline_m, 1),
              "Static level (m)": round(sc.static_water_level_m, 2),
              "Available drawdown (m)": round(sc.available_drawdown_m, 1)
              if sc.available_drawdown_m else None,
              "Safe yield (m3/h)": round(sc.safe_yield_m3_per_h, 2)
              if sc.safe_yield_m3_per_h else None,
              "Pump intake (m)": sc.pump_installation_depth_m}
             for sc in _seasonal.scenarios],
            hide_index=True, width="stretch",
        )
        _loss = _seasonal.dry_season_loss_percent
        if _loss and _loss > 1:
            st.warning(
                f"By the end of the dry season this borehole yields about "
                f"{_loss:.0f}% less than it did on the day of the test. "
                "Size the supply on the dry-season figure."
            )
        _intake, _intake_why = pump_intake_depth(analysis, _seasonal)
        if _intake is not None:
            st.info(
                f"Set the pump intake at {fmt_num(_intake)} m below the top "
                f"of the casing, {_intake_why or 'deep enough for the drought case'}. "
                "The pump is fitted once, and one that draws air in a bad year "
                "loses the village its borehole in the year it is needed most."
            )
        st.caption(
            f"The annual range used is {_seasonal.annual_range_m:.1f} m - "
            f"{_seasonal.range_source}."
        )

    _pump_gate = report_gate("pumping")
    if st.button("Build pumping test report", key="build_pump_report"):
      with _working("Building the pumping test report..."):
        report_path = build_pumping_report(
            PumpingReportInputs(analysis=analysis, figures_dir=workdir(),
                                readiness=_pump_gate, seasonal=_seasonal),
            workdir() / "Pumping_Test_Report.docx",
            app_config(),
        )
      offer_download(report_path, "Download pumping test report (.docx)")
