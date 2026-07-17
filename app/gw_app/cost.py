"""Costing tab: single borehole estimate, BoQ and programme packaging."""

from __future__ import annotations

import csv
import io

import streamlit as st

from groundwater.costing import (
    CostingInputs,
    RateItem,
    estimate_programme_cost,
    inputs_from_design,
    plot_cost_breakdown,
    plot_programme_gantt,
    write_boq_workbook,
)
from groundwater.reporting.costing import CostReportInputs, build_cost_report

from .common import (
    app_config,
    cached_rates,
    compute_cost_estimate,
    offer_download,
    offer_report_download,
    show_flags,
    site_from_state,
    workdir,
)


def _apply_rates_csv() -> None:
    """Apply an uploaded rate catalogue CSV (button callback)."""
    upload = st.session_state.get("rates_csv_upload")
    if upload is None:
        return
    try:
        rows = list(csv.DictReader(
            io.StringIO(upload.getvalue().decode("utf-8-sig"))
        ))
        known = {r.code for r in cached_rates()}
        applied = {}
        for row in rows:
            code = (row.get("code") or "").strip()
            if code in known:
                applied[code] = float(row["unit_cost_usd"])
        if not applied:
            raise ValueError("no known rate codes in the file")
    except Exception:
        st.session_state["rates_csv_error"] = True
        return
    overrides = dict(st.session_state.get("rates_overrides", {}))
    overrides.update(applied)
    st.session_state["rates_overrides"] = overrides
    # reset the editor so it shows the applied values
    st.session_state.pop("rates_editor", None)
    st.session_state["rates_csv_applied"] = len(applied)


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
            f"Use the design from the Borehole design tab "
            f"({design.total_depth_m:g} m, {design.casing_diameter_in:g} inch casing)",
            value=True,
            key="cost_use_design",
        )

    # a keyed widget ignores a changed value= once it has state, so
    # reset the field when the design source changes or is toggled.
    # The signature is a string so the project file carries it and a
    # loaded project's depth is not wiped by a false "source changed".
    design_sig = (
        f"{bool(use_design)}:"
        f"{float(design.total_depth_m) if design else 0.0:.1f}"
    )
    if st.session_state.get("cost_design_sig") != design_sig:
        st.session_state["cost_design_sig"] = design_sig
        if not st.session_state.get("project_just_loaded"):
            st.session_state.pop("cost_depth", None)

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
        success_rate = c10.number_input(
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
        rate_rows = [
            {
                "Code": r.code,
                "Stage": r.stage,
                "Item": r.item,
                "Unit": r.unit,
                "Rate (USD)": float(overrides.get(r.code, r.unit_cost_usd)),
            }
            for r in base_rates
        ]
        try:
            edited = st.data_editor(
                rate_rows,
                key="rates_editor",
                hide_index=True,
                disabled=["Code", "Stage", "Item", "Unit"],
                use_container_width=True,
            )
        except Exception:
            # very old or limited runtimes: show read-only rates instead
            st.dataframe(rate_rows, use_container_width=True)
            edited = rate_rows
        edited_by_code = {row["Code"]: row for row in edited}
        rates = [
            RateItem(
                code=r.code, stage=r.stage, category=r.category, item=r.item,
                unit=r.unit, quantity_basis=r.quantity_basis,
                unit_cost_usd=float(
                    edited_by_code.get(r.code, {}).get(
                        "Rate (USD)", overrides.get(r.code, r.unit_cost_usd)
                    )
                ),
                note=r.note,
            )
            for r in base_rates
        ]
        # remember the working rates so the project file carries them
        st.session_state.rates_overrides = {
            r.code: r.unit_cost_usd for r in rates
        }

        # share the price book between projects: download the working
        # rates, or apply a CSV another project exported
        st.divider()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["code", "stage", "category", "item", "unit",
                        "quantity_basis", "unit_cost_usd", "note"])
        for r in rates:
            writer.writerow([r.code, r.stage, r.category, r.item, r.unit,
                             r.quantity_basis, f"{r.unit_cost_usd:g}", r.note])
        rc1, rc2 = st.columns(2)
        rc1.download_button(
            "Download rate catalogue (.csv)",
            buf.getvalue().encode("utf-8"),
            file_name="unit_rates.csv",
            key="rates_csv_download",
            help="The working rates including your edits - a price book "
            "the team can share and reuse on other projects.",
        )
        with rc2:
            st.file_uploader(
                "Apply a shared rate catalogue",
                type=["csv"], key="rates_csv_upload",
                help="A CSV with 'code' and 'unit_cost_usd' columns; "
                "unknown codes are ignored.",
            )
            st.button("Apply uploaded rates", key="rates_csv_apply",
                      on_click=_apply_rates_csv)
        applied = st.session_state.pop("rates_csv_applied", None)
        if applied is not None:
            st.success(f"Applied {applied} rate(s) from the uploaded catalogue.")
        if st.session_state.pop("rates_csv_error", False):
            st.error(
                "Could not read that file as a rate catalogue "
                "(needs 'code' and 'unit_cost_usd' columns)."
            )

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
            st.dataframe(estimate.boq_rows(), use_container_width=True)
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

        st.caption(
            "The report cover uses the site details from the sidebar."
        )
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
                    ),
                    workdir() / "Cost_Estimate_Report.docx",
                    app_config(),
                )
                offer_report_download(report_path, "Download cost estimate report (.docx)")

    st.divider()
    with st.expander("📦 Programme: a package of boreholes"):
        st.caption(
            "Costs a multi-borehole contract with one mobilisation, moves "
            "between nearby sites, and dry attempts carried by the "
            "successful wells, following the procurement guide's contract "
            "packaging rules. Uses the single borehole inputs and rates "
            "above."
        )
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
            st.session_state.programme_estimate = (programme, gantt_path)
        if "programme_estimate" in st.session_state:
            programme, gantt_path = st.session_state.programme_estimate
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
