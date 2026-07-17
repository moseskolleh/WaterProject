"""Guided start tab: three-step wizard for a new project."""

from __future__ import annotations

import streamlit as st

from groundwater.costing import CostingInputs
from groundwater.ingestion import read_ves_workbook

from . import status
from .common import (
    cached_rates,
    choose_input,
    compute_cost_estimate,
    parse_upload,
    run_ves_inversion,
    site_from_state,
    top_interpretation,
)

_WIZ_STEPS = ("Site details", "Siting (VES)", "Costing", "Ready to drill")


def render() -> None:
    wiz_step = int(st.session_state.get("wiz_step", 0))

    with st.expander("📋 Project status", expanded=(wiz_step == 3)):
        status.render_board()

    st.header("Guided project setup")
    st.caption(
        "Three short steps to a sited, costed borehole project. Every "
        "result carries over to the full tabs, where you can fine tune."
    )
    st.progress(
        wiz_step / (len(_WIZ_STEPS) - 1),
        text=f"Step {min(wiz_step, 2) + 1} of 3: {_WIZ_STEPS[wiz_step]}"
        if wiz_step < 3
        else "Setup complete",
    )

    def _wiz_go(step: int) -> None:
        st.session_state.wiz_step = step

    # read fresh where needed, so the step that has just run the
    # inversion sees its own result
    _top_interp = top_interpretation

    site = site_from_state()

    if wiz_step == 0:
        st.subheader("1. Who and where")
        st.write(
            "Fill the **Site details** panel in the sidebar (already "
            "open). The wizard checks it off as you go; a saved project "
            "file loads everything at once."
        )
        checks = [
            ("Community", bool(site.community)),
            ("Area and district", bool(site.district)),
            ("Client", bool(site.client)),
            ("GPS coordinates", site.latlon is not None),
        ]
        for label, done in checks:
            st.markdown(("✅ " if done else "⬜ ") + label)
        ready = bool(site.community and site.district)
        if not ready:
            st.info("Community and district are needed to continue.")
        elif site.latlon is None:
            st.warning(
                "No GPS coordinates yet: maps and report locations will "
                "be blank until they are entered. You can continue."
            )
        st.button(
            "Next: Siting (VES) →", key="wiz_next", type="primary",
            disabled=not ready, on_click=_wiz_go, args=(1,),
        )

    elif wiz_step == 1:
        st.subheader("2. Where to drill and how deep")
        st.write(
            "Upload the VES field workbook (or try the bundled sample) "
            "and run the inversion. The best ranked sounding sets the "
            "drilling depth for the cost estimate."
        )
        wiz_path = choose_input(
            "VES workbook (standard template)", "wiz_ves", ["xlsx"],
            ["rokel/rokel_ves.xlsx"],
        )
        if wiz_path is not None:
            wiz_soundings = parse_upload(read_ves_workbook, wiz_path)
            if wiz_soundings:
                st.success(f"Parsed {len(wiz_soundings)} sounding(s).")
                if st.button("Run siting analysis", key="wiz_run_ves",
                             type="primary"):
                    run_ves_inversion(wiz_soundings)
            else:
                st.error("No soundings found in the workbook.")
        # read after the run button so a fresh result unlocks Next now
        top_interp = _top_interp()
        if top_interp is not None:
            st.metric(
                f"Recommended site: {top_interp.sounding_id}",
                f"drill to {top_interp.max_drilling_depth_m:g} m",
                help="Best ranked sounding; see the VES survey tab for "
                "curves, water zones and the full preference table.",
            )
        with st.expander("No VES data? Enter the planned depth directly"):
            st.number_input(
                "Planned drilling depth (m)", 0.0, 300.0, 0.0, 5.0,
                key="wiz_manual_depth",
                on_change=lambda: st.session_state.pop("_wiz_load_grace", None),
            )
        depth_known = (
            top_interp is not None
            or st.session_state.get("wiz_manual_depth", 0.0) > 0
        )
        col_b, col_n = st.columns([1, 3])
        col_b.button("← Back", key="wiz_back", on_click=_wiz_go, args=(0,))
        col_n.button(
            "Next: Costing →", key="wiz_next", type="primary",
            disabled=not depth_known, on_click=_wiz_go, args=(2,),
        )

    elif wiz_step == 2:
        st.subheader("3. What it will cost")
        top_interp = _top_interp()
        if top_interp is not None:
            default_depth = float(top_interp.max_drilling_depth_m)
            default_over = float(top_interp.depth_to_basement_m or 0.0)
            st.caption(
                f"Depth prefilled from the siting result "
                f"({top_interp.sounding_id}); adjust if needed."
            )
        else:
            default_depth = float(st.session_state.get("wiz_manual_depth", 60.0))
            default_over = 0.0
        # refresh the prefill when a new siting result arrives. The
        # signature is a string so the project file carries it and a
        # loaded project's adjusted values survive the first rerun.
        prefill_sig = f"{default_depth:.1f}:{default_over:.1f}"
        if st.session_state.get("wiz_prefill_sig") != prefill_sig:
            st.session_state["wiz_prefill_sig"] = prefill_sig
            # consume the load grace here, not at end of run: this block
            # only executes on the costing step, which a loaded project
            # may reach many runs after the load itself
            if not st.session_state.pop("_wiz_load_grace", False):
                st.session_state.pop("wiz_cost_depth", None)
                st.session_state.pop("wiz_cost_over", None)
        else:
            st.session_state.pop("_wiz_load_grace", None)
        c1, c2, c3 = st.columns(3)
        wiz_depth = c1.number_input("Total depth (m)", 1.0, 300.0,
                                    default_depth or 60.0, 1.0,
                                    key="wiz_cost_depth")
        wiz_over = c2.number_input(
            "Overburden (m)", 0.0, 300.0, default_over, 1.0,
            key="wiz_cost_over",
            help="0 applies the rule of thumb (half the depth, up to 30 m).",
        )
        wiz_dist = c3.number_input(
            "Distance from contractor base, one way (km)", 0.0, 1000.0,
            100.0, 10.0, key="wiz_cost_dist",
        )
        if st.button("Estimate the cost", key="wiz_cost_run", type="primary"):
            compute_cost_estimate(
                CostingInputs(
                    total_depth_m=wiz_depth,
                    overburden_m=wiz_over or None,
                    mobilisation_distance_km=wiz_dist,
                ),
                cached_rates(),
            )
        wiz_est = st.session_state.get("cost_estimate")
        if wiz_est is not None:
            m1, m2, m3 = st.columns(3)
            m1.metric("Total cost", f"${wiz_est.total_cost_usd:,.0f}")
            m2.metric("Contract price", f"${wiz_est.price_usd:,.0f}")
            m3.metric("Per metre", f"${wiz_est.cost_per_meter_usd:,.0f}/m")
            st.caption(
                "Using the bundled indicative rates and default "
                "percentages; open the Costing tab to edit unit rates, "
                "margins, VAT and the bill of quantities."
            )
        col_b, col_n = st.columns([1, 3])
        col_b.button("← Back", key="wiz_back", on_click=_wiz_go, args=(1,))
        col_n.button(
            "Finish →", key="wiz_next", type="primary",
            disabled=wiz_est is None, on_click=_wiz_go, args=(3,),
        )

    else:
        st.subheader("Ready to drill")
        top_interp = _top_interp()
        est = st.session_state.get("cost_estimate")
        summary = [
            f"**Site**: {site.community or 'not set'}"
            + (f", {site.district} District" if site.district else ""),
        ]
        if top_interp is not None:
            summary.append(
                f"**Siting**: drill at {top_interp.sounding_id} to "
                f"{top_interp.max_drilling_depth_m:g} m"
            )
        if est is not None:
            summary.append(
                f"**Budget**: planning budget ${est.budget_usd:,.0f} "
                f"(price ${est.price_usd:,.0f})"
            )
        st.success("\n\n".join(summary))
        st.markdown(
            "**What happens next**\n"
            "1. **Supervision** tab: work the checklists from procurement "
            "through drilling to handover; critical items gate acceptance.\n"
            "2. **Borehole design** tab: once the drilling log exists, "
            "generate the as-built design (it feeds the costing and the "
            "reports).\n"
            "3. **Pumping test** and **Water quality** tabs: safe yield "
            "and the WHO/national verdict.\n"
            "4. **Handover** tab: the closing report with the committee "
            "and sign off.\n"
            "5. **Maps** tab: location, geology and aquifer maps for the "
            "reports.\n\n"
            "Save your work with **Project file** in the sidebar - it "
            "carries everything you have entered."
        )
        col_b, col_r = st.columns([1, 3])
        col_b.button("← Back", key="wiz_back", on_click=_wiz_go, args=(2,))
        col_r.button("Start a new guided setup", key="wiz_restart",
                     on_click=_wiz_go, args=(0,))
