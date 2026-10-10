"""Costing & BoQ: the cost estimate, the bill of quantities and a programme."""

from __future__ import annotations

import streamlit as st

from groundwater.costing import (
    CostingInputs,
    estimate_programme_cost,
    inputs_from_design,
    plot_cost_breakdown,
    plot_cost_distribution,
    plot_programme_gantt,
    sample_programme_cost,
    write_boq_workbook,
)
from groundwater.costing.distribution import (
    cost_range_header,
    cost_range_rows,
    cost_range_text,
    programme_range_rows,
    programme_range_text,
)
from groundwater.reporting.costing import build_cost_report, CostReportInputs
from groundwater.siting.odds import programme_offer, programme_rate
from groundwater.text import phrase, phrase_table

from shared import (
    app_config,
    cached_rates,
    compute_cost_estimate,
    cost_spread_for,
    cost_spread_inputs,
    first_point_survey,
    _manual_costing_rules,
    _next_step,
    offer_download,
    report_gate,
    show_flags,
    site_from_state,
    workdir,
)

def _first_point_odds():
    """The chance of a working borehole at the survey's first-ranked point,
    or None before a survey is inverted."""
    return first_point_survey()[0]


def _show_spread(text: list[str], rows: list[list[str]], chart, caption: str) -> None:
    """The planning figure: which figure is which, then the sentences, the
    table and the curve (PLAN.md step 3.4)."""
    st.subheader(phrase("cost_range.heading"))
    st.info(text[0])
    for line in text[1:]:
        st.markdown(line)
    header = cost_range_header()
    st.table([dict(zip(header, row, strict=True)) for row in rows])
    st.image(str(chart), caption=caption)


def _use_rate(rate: float) -> None:
    st.session_state["cost_prog_success"] = rate


def render() -> None:
    st.header("Borehole costing")
    st.caption(
        "Cost estimate and bill of quantities following the RWSN "
        "Cost-Effective Boreholes methodology: cost first, price "
        "separately, both stage and resource breakdowns."
    )

    design = st.session_state.get("borehole_design")
    use_design = False
    if design is not None:
        use_design = st.toggle(
            f"Use the design from the Borehole design page "
            f"({design.total_depth_m:g} m, {design.casing_diameter_in:g} inch casing)",
            value=True,
            key="cost_use_design",
        )

    # a keyed widget ignores a changed value= once it has state, so the
    # depth is reset when the design source changes or is toggled. The
    # design can change while this page is not on screen, so that is done by
    # shared.refresh_derived, before any page runs (cost_design_sig).

    col1, col2, col3 = st.columns(3)
    with col1:
        depth = st.number_input(
            "Total depth (m)", min_value=1.0,
            value=float(design.total_depth_m) if use_design else 60.0,
            step=1.0, key="cost_depth", disabled=use_design,
        )
    with col2:
        overburden = st.number_input(
            "Overburden thickness (m)", min_value=0.0, value=0.0, step=1.0,
            key="cost_overburden",
            help="Weathered zone drilled by rotary; 0 applies the rule of "
            "thumb (half the depth, at most 30 m).",
        )
    with col3:
        distance = st.number_input(
            "Mobilisation distance, one way (km)", min_value=0.0, value=100.0,
            step=10.0, key="cost_distance",
        )

    with st.expander("Adjust assumptions and percentages"):
        c1, c2, c3, c4 = st.columns(4)
        overheads_pct = c1.number_input("Overheads (%)", 0.0, 100.0, 15.0, 1.0,
                                        key="cost_overheads",
                                        help="RWSN: usually 10 to 20 percent of contract value.")
        margin_pct = c2.number_input("Margin (%)", 0.0, 100.0, 20.0, 1.0,
                                     key="cost_margin")
        contingency_pct = c3.number_input("Contingency (%)", 0.0, 100.0, 10.0, 1.0,
                                          key="cost_contingency")
        fx = c4.number_input("Exchange rate (SLE per USD)", 1.0, 1000.0, 23.0, 0.5,
                             key="cost_fx")
        c5, c6, c7, c8 = st.columns(4)
        handpumps = c5.number_input("Handpumps", 0, 5, 1, key="cost_handpumps")
        samples = c6.number_input("Water quality samples", 0, 10, 1, key="cost_samples")
        dev_hours = c7.number_input("Development (h)", 0.0, 200.0, 6.0, 1.0,
                                    key="cost_dev_hours")
        test_hours = c8.number_input("Test pumping (h)", 0.0, 200.0, 30.0, 1.0,
                                     key="cost_test_hours")
        c9, c10 = st.columns(2)
        vat_pct = c9.number_input(
            "VAT/GST (%) - optional", 0.0, 50.0, 0.0, 1.0, key="cost_vat",
            help="Optional; leave at 0 to keep tax out of the price. "
            "Sierra Leone GST is 15 percent where it applies.",
        )
        c10.number_input(
            "Expected success rate (%)", 1.0, 100.0, 100.0, 5.0,
            key="cost_success",
            help="Under a no water no pay contract the successful wells "
            "must carry the failures: price / success rate.",
        )

    with st.expander("Unit rate catalogue (edit to match local prices)"):
        st.caption(
            "Bundled rates are indicative; confirm against local quotations. "
            "Rates are in USD."
        )
        base_rates = cached_rates()
        overrides = st.session_state.get("rates_overrides", {})
        # the minimum and maximum the distribution draws from, kept in
        # proportion to the rate as it is edited (read-only here)
        working = [r.with_likely(float(overrides.get(r.code, r.unit_cost_usd)))
                   for r in base_rates]
        rate_rows = [
            {
                "Code": r.code,
                "Stage": r.stage,
                "Item": r.item,
                "Unit": r.unit,
                "Rate (USD)": r.unit_cost_usd,
                "Min (USD)": round(r.triangle()[0], 2),
                "Max (USD)": round(r.triangle()[2], 2),
            }
            for r in working
        ]
        try:
            edited = st.data_editor(
                rate_rows,
                key="rates_editor",
                hide_index=True,
                disabled=["Code", "Stage", "Item", "Unit", "Min (USD)", "Max (USD)"],
                width="stretch",
            )
        except Exception:  # noqa: BLE001 - read-only fallback, said out loud
            # very old or limited runtimes: show read-only rates instead
            st.caption(
                "This Streamlit build cannot render the editable rate "
                "table, so the rates below are read-only."
            )
            st.dataframe(rate_rows, width="stretch")
            edited = rate_rows
        edited_by_code = {row["Code"]: row for row in edited}
        rates = [
            # an edited rate keeps its relative spread, so the distribution is
            # drawn around the rate typed here
            r.with_likely(float(
                edited_by_code.get(r.code, {}).get(
                    "Rate (USD)", overrides.get(r.code, r.unit_cost_usd)
                )
            ))
            for r in base_rates
        ]
        # remember the working rates so the project file carries them
        st.session_state.rates_overrides = {
            r.code: r.unit_cost_usd for r in rates
        }

    if st.button("Estimate cost", key="run_cost", type="primary"):
        if use_design and design is not None:
            inputs = inputs_from_design(
                design, mobilisation_distance_km=distance,
                overburden_m=overburden or None,
            )
        else:
            inputs = CostingInputs(
                total_depth_m=depth,
                overburden_m=overburden or None,
                mobilisation_distance_km=distance,
                **_manual_costing_rules(),
            )
        inputs.handpumps = int(handpumps)
        inputs.wq_samples = int(samples)
        inputs.development_hours = float(dev_hours)
        inputs.test_pumping_hours = float(test_hours)
        compute_cost_estimate(
            inputs, rates,
            overheads_percent=overheads_pct,
            margin_percent=margin_pct,
            contingency_percent=contingency_pct,
            vat_percent=vat_pct,
            exchange_rate_sle_per_usd=fx,
        )

    estimate = st.session_state.get("cost_estimate")
    if estimate is not None:
        show_flags(estimate.flags)
        cols = st.columns(4)
        cols[0].metric("Direct works cost", f"${estimate.direct_cost_usd:,.0f}")
        cols[1].metric(
            "Total cost",
            f"${estimate.total_cost_usd:,.0f}",
            help="Direct works plus overheads - what the job costs the contractor.",
        )
        cols[2].metric("Cost per metre", f"${estimate.cost_per_meter_usd:,.0f}/m")
        cols[3].metric(
            "Contract price",
            f"${estimate.price_usd:,.0f}",
            help="Total cost plus margin; the contingency for budgeting sits on top.",
        )
        st.caption(
            f"Planning budget with contingency: "
            f"**${estimate.budget_usd:,.0f}** "
            f"(SLE {estimate.in_local(estimate.budget_usd):,.0f} at "
            f"{estimate.exchange_rate_sle_per_usd:g} SLE/USD)."
        )
        if st.session_state.get("cost_success", 100.0) < 100.0:
            rate = st.session_state["cost_success"]
            st.warning(
                f"No water no pay at {rate:g}% success: each successful "
                f"well must be priced at "
                f"${estimate.price_per_successful_well_usd(rate):,.0f} "
                "to carry the expected failures."
            )

        if "cost_artifacts" not in st.session_state:
            chart_path = workdir() / "cost_breakdown.png"
            plot_cost_breakdown(estimate, chart_path, app_config().style)
            boq_path = workdir() / "Bill_of_Quantities.xlsx"
            write_boq_workbook(estimate, boq_path)
            st.session_state.cost_artifacts = (chart_path, boq_path)
        chart_path, boq_path = st.session_state.cost_artifacts
        st.image(str(chart_path))

        col_boq, col_sum = st.columns([3, 2])
        with col_boq:
            st.subheader("Bill of quantities")
            st.dataframe(estimate.boq_rows(), width="stretch")
        with col_sum:
            st.subheader("Summary")
            st.table(
                [
                    {"Item": label, "USD": usd, "SLE": sle}
                    for label, usd, sle in estimate.summary_rows()
                ]
            )
        if estimate.assumptions:
            with st.expander("Assumptions applied"):
                for assumption in estimate.assumptions:
                    st.markdown(f"- {assumption}")

        # sampled with the estimate, so there is one whenever there is an
        # estimate made on this page or in the guided start
        kept_spread = cost_spread_for(estimate)
        if kept_spread is not None:
            spread, spread_chart = kept_spread
            _show_spread(cost_range_text(spread), cost_range_rows(spread), spread_chart,
                         phrase("cost_range.figure_caption"))

        st.caption(
            "The report cover uses the site details from the sidebar."
        )
        _cost_gate = report_gate("costing", scope="estimate")
        dl1, dl2 = st.columns(2)
        with dl1:
            offer_download(boq_path, "Download bill of quantities (.xlsx)")
        with dl2:
            if st.button("Build cost estimate report", key="build_cost_report"):
                report_path = build_cost_report(
                    CostReportInputs(
                        estimate=estimate,
                        site=site_from_state(),
                        figures_dir=workdir(),
                        readiness=_cost_gate,
                        # the package roll-up, when one has been estimated:
                        # it is the number a programme is budgeted against
                        programme=(st.session_state.get("programme_estimate")
                                   or (None,))[0],
                        distribution=(kept_spread or (None,))[0],
                        programme_distribution=(
                            st.session_state.get("programme_estimate") or (None,) * 4)[2],
                    ),
                    workdir() / "Cost_Estimate_Report.docx",
                    app_config(),
                )
                offer_download(report_path, "Download cost estimate report (.docx)")

    st.divider()
    with st.expander("📦 Programme: a package of boreholes"):
        st.caption(
            "Costs a multi-borehole contract with one mobilisation, moves "
            "between nearby sites, and dry attempts carried by the "
            "successful wells, following the procurement guide's contract "
            "packaging rules. Uses the single borehole inputs and rates "
            "above."
        )
        # The survey's odds are offered beside the typed rate, never put in
        # its place without a click: a programme estimate that moved because
        # a sounding was inverted on another page would change silently.
        offered = _first_point_odds()
        if offered is not None:
            rate = programme_rate(offered)
            st.info(programme_offer(offered))
            st.button(phrase("odds.programme_use", p=rate), key="use_survey_odds",
                      on_click=_use_rate, args=(rate,))
        p1, p2, p3 = st.columns(3)
        n_wells = p1.number_input("Successful boreholes required", 1, 500, 10,
                                  key="cost_prog_n")
        inter_km = p2.number_input("Average distance between sites (km)",
                                   0.0, 200.0, 15.0, 1.0, key="cost_prog_km")
        prog_success = p3.number_input("Siting success rate (%)", 1.0, 100.0,
                                       80.0, 5.0, key="cost_prog_success")
        if st.button("Estimate programme", key="run_programme"):
            per_well = CostingInputs(
                total_depth_m=depth,
                overburden_m=overburden or None,
                mobilisation_distance_km=distance,
                **_manual_costing_rules(),
                handpumps=int(handpumps),
                wq_samples=int(samples),
                development_hours=float(dev_hours),
                test_pumping_hours=float(test_hours),
            )
            programme = estimate_programme_cost(
                per_well, int(n_wells), rates=rates,
                inter_site_distance_km=inter_km,
                success_rate_percent=prog_success,
                overheads_percent=overheads_pct,
                margin_percent=margin_pct,
                contingency_percent=contingency_pct,
                vat_percent=vat_pct,
                exchange_rate_sle_per_usd=fx,
            )
            gantt_path = workdir() / "programme_gantt.png"
            plot_programme_gantt(programme, gantt_path, app_config().style)
            # the planning figure for the package, drawn at the same depth
            # as the single borehole's and at the rate typed for it
            spread_inputs = cost_spread_inputs()
            programme_spread = sample_programme_cost(
                per_well, int(n_wells), rates=rates, inter_site_distance_km=inter_km,
                success_rate_percent=prog_success, depth=spread_inputs["depth"],
                overheads_percent=overheads_pct, margin_percent=margin_pct,
                contingency_percent=contingency_pct, vat_percent=vat_pct,
                config=app_config(),
            )
            marks = phrase_table("cost_range.marks")
            spread_path = workdir() / "programme_distribution.png"
            plot_cost_distribution(
                programme_spread.curve,
                [(marks["estimate"], programme_spread.estimate_usd),
                 (marks["budget"], programme_spread.budget_usd)],
                spread_path, app_config().style, title=marks["programme_title"])
            st.session_state.programme_estimate = (programme, gantt_path,
                                                   programme_spread, spread_path)
        if "programme_estimate" in st.session_state:
            programme, gantt_path, programme_spread, spread_path = (
                st.session_state.programme_estimate)
            g1, g2, g3 = st.columns(3)
            g1.metric("Attempts planned", programme.n_attempted)
            g2.metric("Contract price",
                      f"${programme.price_with_vat_usd:,.0f}")
            g3.metric("Per successful borehole",
                      f"${programme.price_per_successful_well_usd:,.0f}")
            st.table(
                [
                    {"Item": label, "USD": usd, "SLE": sle}
                    for label, usd, sle in programme.summary_rows()
                ]
            )
            st.image(str(gantt_path))
            with st.expander("Programme assumptions"):
                for assumption in programme.assumptions:
                    st.markdown(f"- {assumption}")
            _show_spread([phrase("cost_range.which_is_which")]
                         + programme_range_text(programme_spread),
                         programme_range_rows(programme_spread), spread_path,
                         phrase("cost_range.programme_figure_caption"))

    _next_step("Start supervision →", "Supervision",
               "Budget agreed. Work the checklists as the rig arrives.")
