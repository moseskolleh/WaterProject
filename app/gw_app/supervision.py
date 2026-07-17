"""Supervision tab: stage checklists, field acceptance checks, sign off."""

from __future__ import annotations

import streamlit as st

from groundwater.reporting.supervision import (
    SupervisionReportInputs,
    build_supervision_report,
)
from groundwater.supervision import (
    disinfection_dose,
    evaluate_checklist,
    metres_reconciliation_check,
    sand_content_check,
    specific_capacity_check,
    stage_title,
    verticality_check,
)

from .common import (
    app_config,
    cached_checklists,
    cached_separation_distances,
    checklist_responses,
    offer_report_download,
    site_from_state,
    workdir,
)


def render() -> None:
    st.header("Drilling supervision")
    st.caption(
        "Stage by stage checklists from the RWSN/UNICEF supervision "
        "guidance, plus the numeric acceptance checks a supervisor "
        "needs on site. Critical items stop acceptance when they fail."
    )

    checklist_items = cached_checklists()

    responses = checklist_responses(checklist_items)
    assessment = evaluate_checklist(checklist_items, responses)
    top1, top2, top3 = st.columns([1, 1, 2])
    top1.metric("Items answered", f"{assessment.answered}/{assessment.total}")
    top2.metric("Critical failures", assessment.critical_failures)
    with top3:
        st.progress(assessment.percent / 100.0)
        if assessment.critical_failures:
            st.error(assessment.verdict)
        else:
            st.info(assessment.verdict)

    stage_keys: list[str] = []
    for item in checklist_items:
        if item.checklist not in stage_keys:
            stage_keys.append(item.checklist)
    progress_by_stage = {s.stage: s for s in assessment.stages}
    incomplete = [
        k for k in stage_keys
        if progress_by_stage[k].answered < progress_by_stage[k].total
    ]
    sel_col, jump_col = st.columns([3, 1])
    with sel_col:
        stage_pick = st.selectbox(
            "Supervision stage",
            stage_keys,
            format_func=lambda k: (
                f"{stage_title(k)}  "
                f"({progress_by_stage[k].answered}/{progress_by_stage[k].total})"
            ),
            key="sup_stage",
        )
    if incomplete:
        jump_col.button(
            "Resume →", key="sup_jump",
            help="Jump to the first stage with unanswered items.",
            on_click=lambda k=incomplete[0]: st.session_state.update(sup_stage=k),
        )

    stage_items = [i for i in checklist_items if i.checklist == stage_pick]
    section_progress: dict[str, list[int]] = {}
    for item in stage_items:
        answered = responses[item.item_id].status != "pending"
        totals = section_progress.setdefault(item.section, [0, 0])
        totals[0] += int(answered)
        totals[1] += 1

    current_section = None
    for item in stage_items:
        if item.section != current_section:
            current_section = item.section
            done, total = section_progress[current_section]
            st.markdown(f"**{current_section}**  ({done}/{total})")
        with st.container(border=True):
            label = item.text + (" 🔴 *critical*" if item.critical else "")
            st.markdown(label)
            if item.guidance:
                st.caption(item.guidance)
            st.radio(
                "Status",
                ["Pending", "Yes", "No", "N/A"],
                horizontal=True,
                key=f"chk_{item.item_id}",
                label_visibility="collapsed",
            )
            if st.session_state.get(f"chk_{item.item_id}") == "No":
                st.text_input(
                    "Remark / action", key=f"rmk_{item.item_id}",
                    placeholder="What failed and what happens next",
                )

    st.divider()
    with st.expander("🗒️ Daily drilling log"):
        st.caption(
            "One row per drilling day, entered on site. The totals feed "
            "the drilled-metres reconciliation below and the log is "
            "carried in the project file."
        )
        _EMPTY_DAY = {"Date": "", "From (m)": None, "To (m)": None,
                      "Rig hours": None, "Remarks": ""}
        if "daily_log_base" not in st.session_state:
            st.session_state["daily_log_base"] = (
                st.session_state.get("daily_log_rows") or [dict(_EMPTY_DAY)]
            )
        edited_days = st.data_editor(
            st.session_state["daily_log_base"],
            key="daily_log_editor",
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            column_config={
                "Date": st.column_config.TextColumn("Date"),
                "From (m)": st.column_config.NumberColumn(
                    "From (m)", min_value=0.0, step=0.5),
                "To (m)": st.column_config.NumberColumn(
                    "To (m)", min_value=0.0, step=0.5),
                "Rig hours": st.column_config.NumberColumn(
                    "Rig hours", min_value=0.0, step=0.5),
                "Remarks": st.column_config.TextColumn("Remarks"),
            },
        )

        def _day_number(row, key):
            try:
                value = float(row.get(key) or 0.0)
            except (TypeError, ValueError):
                return 0.0
            return value

        # keep a plain copy for the project file and the totals
        st.session_state["daily_log_rows"] = [
            {k: (v if v is not None else "") for k, v in row.items()}
            for row in edited_days
            if any(str(v or "").strip() for v in row.values())
        ]
        logged_metres = sum(
            max(0.0, _day_number(r, "To (m)") - _day_number(r, "From (m)"))
            for r in edited_days
        )
        logged_hours = sum(_day_number(r, "Rig hours") for r in edited_days)
        days = len(st.session_state["daily_log_rows"])
        if days:
            st.caption(
                f"{days} day(s) logged: {logged_metres:g} m drilled, "
                f"{logged_hours:g} rig hours."
            )
            st.button(
                f"Use the logged total ({logged_metres:g} m) in the "
                "reconciliation",
                key="daily_log_apply",
                on_click=lambda m=logged_metres: st.session_state.update(
                    fx_logged=float(m)
                ),
            )

    with st.expander("🧮 Field acceptance checks"):
        fc1, fc2 = st.columns(2)
        with fc1:
            st.markdown("**Chlorine disinfection dose (WHO 20 mg/L)**")
            d1, d2 = st.columns(2)
            water_col = d1.number_input("Water column (m)", 0.0, 200.0, 40.0, 1.0,
                                        key="fx_watercol")
            casing_id = d2.number_input("Casing ID (mm)", 50.0, 400.0, 103.0, 1.0,
                                        key="fx_casingid")
            st.caption(disinfection_dose(water_col, casing_id).summary())

            st.markdown("**Verticality (plumb test)**")
            v1, v2 = st.columns(2)
            dev = v1.number_input("Deviation (mm)", 0.0, 1000.0, 50.0, 5.0, key="fx_dev")
            vdepth = v2.number_input("Depth (m)", 1.0, 300.0, 60.0, 1.0, key="fx_vdepth")
            v = verticality_check(dev, vdepth, casing_id)
            (st.success if v.passed else st.error)(f"{v.measured} vs {v.limit}: {v.message}")

        with fc2:
            st.markdown("**Sand content (three 20 L samples)**")
            s1, s2, s3 = st.columns(3)
            sand = [
                s1.number_input("S1 (cm3)", 0.0, 10.0, 0.1, 0.05, key="fx_sand1"),
                s2.number_input("S2 (cm3)", 0.0, 10.0, 0.1, 0.05, key="fx_sand2"),
                s3.number_input("S3 (cm3)", 0.0, 10.0, 0.1, 0.05, key="fx_sand3"),
            ]
            sc = sand_content_check(sand)
            (st.success if sc.passed else st.error)(f"{sc.measured}: {sc.message}")

            st.markdown("**Specific capacity (handpump rule)**")
            q1, q2 = st.columns(2)
            q_test = q1.number_input("Discharge (m3/h)", 0.0, 100.0, 3.0, 0.1, key="fx_q")
            dd = q2.number_input("Drawdown (m)", 0.0, 100.0, 2.0, 0.1, key="fx_dd")
            spc = specific_capacity_check(q_test, dd)
            if spc.passed is None:
                st.info(spc.message)
            else:
                (st.success if spc.passed else st.warning)(f"{spc.measured}: {spc.message}")

            st.markdown("**Drilled metres reconciliation**")
            r1, r2 = st.columns(2)
            logged = r1.number_input("Metres in signed daily logs", 0.0,
                                     2000.0, 60.0, 1.0, key="fx_logged")
            claimed = r2.number_input("Metres invoiced", 0.0, 2000.0, 60.0,
                                      1.0, key="fx_claimed")
            recon = metres_reconciliation_check(logged, claimed)
            (st.success if recon.passed else st.error)(recon.message)
            st.caption(
                "The daily report template for the driller is in the "
                "Templates tab."
            )

    with st.expander("📏 Minimum separation distances"):
        st.table(
            [
                {
                    "Structure": d.structure,
                    "Minimum distance (m)": f"{d.min_distance_m:g}",
                    "Note": d.note,
                }
                for d in cached_separation_distances()
            ]
        )
        st.caption("Adapted from FGN/NWRI 2010 via the RWSN supervision guide.")

    with st.expander("📝 Checklist record and sign off"):
        st.caption(
            "Community, client, contractor and supervisor come from the "
            "site details in the sidebar."
        )
        st.text_input("Community representative (sign off)",
                      key="meta_community_rep")
        if st.button("Build supervision checklist report", key="build_sup_report"):
            site = site_from_state()
            report_path = build_supervision_report(
                SupervisionReportInputs(
                    site=site,
                    items=checklist_items,
                    responses=responses,
                    assessment=assessment,
                    supervisor=site.supervisor,
                    driller=site.contractor,
                    community_rep=st.session_state.get("meta_community_rep", ""),
                ),
                workdir() / "Supervision_Checklist_Report.docx",
                app_config(),
            )
            offer_report_download(report_path, "Download supervision report (.docx)")
