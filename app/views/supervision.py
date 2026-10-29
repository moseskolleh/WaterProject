"""Supervision: the stage checklists and the field acceptance checks."""

from __future__ import annotations

import base64

import streamlit as st

from groundwater.photos import describe_provenance, photo_provenance, utc_now_text
from groundwater.reporting.supervision import (
    build_supervision_report,
    SupervisionReportInputs,
)
from groundwater.supervision import (
    ChecklistResponse,
    disinfection_dose,
    evaluate_checklist,
    metres_reconciliation_check,
    sand_content_check,
    specific_capacity_check,
    stage_title,
    verticality_check,
)

from shared import (
    app_config,
    cached_checklists,
    cached_separation_distances,
    _next_step,
    offer_download,
    report_gate,
    site_from_state,
    workdir,
)

def _attach_evidence(item_id: str) -> None:
    """Keep the photograph just uploaded, with its provenance (on change).

    The record is made here, once, when the file arrives: made on every
    rerun, its attach time would move each time the page was drawn. This
    app runs on a server and cannot ask the phone or laptop in front of it
    for a position, so a photograph whose file carries none is recorded
    with none, and says why.
    """
    upload = st.session_state.get(f"upload_ev_{item_id}")
    if upload is None:
        return
    data = upload.getvalue()
    evidence = dict(st.session_state.get("sup_evidence") or {})
    evidence[item_id] = {
        "name": upload.name,
        "mime": upload.type or "image/jpeg",
        "b64": base64.b64encode(data).decode("ascii"),
        "provenance": photo_provenance(
            data, attached_at=utc_now_text(), position_note="unsupported"),
    }
    st.session_state["sup_evidence"] = evidence


def _remove_evidence(item_id: str) -> None:
    evidence = dict(st.session_state.get("sup_evidence") or {})
    evidence.pop(item_id, None)
    st.session_state["sup_evidence"] = evidence
    st.session_state.pop(f"upload_ev_{item_id}", None)


def _evidence_slot(item) -> None:
    """The photograph a checklist item needs, and where it came from."""
    photo = (st.session_state.get("sup_evidence") or {}).get(item.item_id)
    if isinstance(photo, dict) and photo.get("b64"):
        shown = describe_provenance(photo.get("provenance"))
        c1, c2 = st.columns([1, 3])
        try:
            c1.image(base64.b64decode(photo["b64"]), width=140)
        except Exception:  # noqa: BLE001 - an image the browser cannot draw is still evidence on file
            c1.caption(photo.get("name") or "photo")
        c2.caption("📷 " + " · ".join(
            part for part in (photo.get("name"), shown["time"], shown["position"],
                              shown["hash"]) if part))
        c2.button("Remove photograph", key=f"ev_remove_{item.item_id}",
                  on_click=_remove_evidence, args=(item.item_id,))
    else:
        st.file_uploader(
            "Photograph (this item needs one)", type=["jpg", "jpeg", "png"],
            key=f"upload_ev_{item.item_id}", on_change=_attach_evidence,
            args=(item.item_id,),
            help="Its capture time and GPS position are read from the file "
                 "where it carries them, and its SHA-256 is recorded.",
        )


def render() -> None:
    st.header("Drilling supervision")
    st.caption(
        "Stage by stage checklists from the RWSN/UNICEF supervision "
        "guidance, plus the numeric acceptance checks a supervisor "
        "needs on site. Critical items stop acceptance when they fail."
    )

    checklist_items = cached_checklists()

    # Only the picked stage's widgets are rendered, and Streamlit discards the
    # state of a widget that a run does not draw. Answering a stage and moving
    # on therefore wiped the answers behind you. The widgets are keyed
    # "chkw_"/"rmkw_" and write through, on change, to the "chk_"/"rmk_" keys
    # that hold the answers and go into the project file; those are plain
    # state, so they survive a stage the run never drew.
    CHK_OPTIONS = ["Pending", "Yes", "No", "N/A"]

    def _store_answer(item_id: str) -> None:
        st.session_state[f"chk_{item_id}"] = st.session_state[f"chkw_{item_id}"]

    def _store_remark(item_id: str) -> None:
        st.session_state[f"rmk_{item_id}"] = st.session_state[f"rmkw_{item_id}"]

    def _responses() -> dict[str, ChecklistResponse]:
        responses: dict[str, ChecklistResponse] = {}
        for item in checklist_items:
            status = st.session_state.get(f"chk_{item.item_id}", "Pending")
            mapped = {"Pending": "pending", "Yes": "yes", "No": "no",
                      "N/A": "na"}.get(status, "pending")
            # a remark typed while the item was No must not linger on a
            # later Yes/N/A answer
            remark = (
                st.session_state.get(f"rmk_{item.item_id}", "")
                if mapped == "no"
                else ""
            )
            responses[item.item_id] = ChecklistResponse(item.item_id, mapped, remark)
        return responses

    responses = _responses()
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
    stage_pick = st.selectbox(
        "Supervision stage",
        stage_keys,
        format_func=lambda k: (
            f"{stage_title(k)}  "
            f"({progress_by_stage[k].answered}/{progress_by_stage[k].total})"
        ),
        key="sup_stage",
    )

    current_section = None
    for item in [i for i in checklist_items if i.checklist == stage_pick]:
        if item.section != current_section:
            current_section = item.section
            st.markdown(f"**{current_section}**")
        with st.container(border=True):
            label = item.text + (" 🔴 *critical*" if item.critical else "")
            st.markdown(label)
            if item.guidance:
                st.caption(item.guidance)
            saved = st.session_state.get(f"chk_{item.item_id}", "Pending")
            st.radio(
                "Status",
                CHK_OPTIONS,
                index=CHK_OPTIONS.index(saved) if saved in CHK_OPTIONS else 0,
                horizontal=True,
                key=f"chkw_{item.item_id}",
                on_change=_store_answer,
                args=(item.item_id,),
                label_visibility="collapsed",
            )
            if item.photo_required:
                _evidence_slot(item)
            if st.session_state.get(f"chk_{item.item_id}") == "No":
                st.text_input(
                    "Remark / action", key=f"rmkw_{item.item_id}",
                    value=st.session_state.get(f"rmk_{item.item_id}", ""),
                    on_change=_store_remark, args=(item.item_id,),
                    placeholder="What failed and what happens next",
                )

    st.divider()
    # Every measurement starts blank, and a check is run only on what was
    # entered. The boxes used to start at plausible values (50 mm over 60 m,
    # 0.1 cm3, 3.0 m3/h over 2.0 m, 60 m logged and invoiced), and all four
    # checks went into the report every time the page ran, so a record built
    # without opening this expander said in print that verticality, sand
    # content, specific capacity and the drilled metres had all passed,
    # against numbers nobody measured. The browser app only ever ran a check
    # whose inputs were typed; this now does the same.
    field_checks = []
    with st.expander("🧮 Field acceptance checks"):
        fc1, fc2 = st.columns(2)
        with fc1:
            st.markdown("**Chlorine disinfection dose (WHO 20 mg/L)**")
            d1, d2 = st.columns(2)
            water_col = d1.number_input("Water column (m)", 0.0, 200.0, None, 1.0,
                                        key="fx_watercol")
            casing_id = d2.number_input("Casing ID (mm)", 50.0, 400.0, None, 1.0,
                                        key="fx_casingid")
            if water_col is not None and casing_id is not None:
                st.caption(disinfection_dose(water_col, casing_id).summary())
            else:
                st.caption("Enter the water column and the casing inner diameter "
                           "for the dose.")

            st.markdown("**Verticality (plumb test)**")
            v1, v2 = st.columns(2)
            dev = v1.number_input("Deviation (mm)", 0.0, 1000.0, None, 5.0, key="fx_dev")
            vdepth = v2.number_input("Depth (m)", 1.0, 300.0, None, 1.0, key="fx_vdepth")
            if None not in (dev, vdepth, casing_id):
                v = verticality_check(dev, vdepth, casing_id)
                field_checks.append(v)
                (st.success if v.passed else st.error)(
                    f"{v.measured} vs {v.limit}: {v.message}")
            else:
                st.caption("Enter the deviation, the depth and the casing ID above "
                           "for the check.")

        with fc2:
            st.markdown("**Sand content (three 20 L samples)**")
            s1, s2, s3 = st.columns(3)
            sand = [
                s1.number_input("S1 (cm3)", 0.0, 10.0, None, 0.05, key="fx_sand1"),
                s2.number_input("S2 (cm3)", 0.0, 10.0, None, 0.05, key="fx_sand2"),
                s3.number_input("S3 (cm3)", 0.0, 10.0, None, 0.05, key="fx_sand3"),
            ]
            # the samples taken, as the browser reads them
            sand = [value for value in sand if value is not None]
            if sand:
                sc = sand_content_check(sand)
                field_checks.append(sc)
                (st.success if sc.passed else st.error)(f"{sc.measured}: {sc.message}")

            st.markdown("**Specific capacity (handpump rule)**")
            q1, q2 = st.columns(2)
            q_test = q1.number_input("Discharge (m3/h)", 0.0, 100.0, None, 0.1, key="fx_q")
            dd = q2.number_input("Drawdown (m)", 0.0, 100.0, None, 0.1, key="fx_dd")
            if q_test is not None and dd is not None:
                spc = specific_capacity_check(q_test, dd)
                field_checks.append(spc)
                if spc.passed is None:
                    st.info(spc.message)
                else:
                    (st.success if spc.passed else st.warning)(
                        f"{spc.measured}: {spc.message}")

            st.markdown("**Drilled metres reconciliation**")
            # Blank until typed, as the browser's are. Both used to start at
            # 60 m, so every project that opened this page saved 60 m logged
            # and 60 m invoiced whether anybody had counted them or not, and
            # the contractor scorecards read these two figures as the
            # record. The keys are new for the same reason: a file saved
            # before carries the 60 m under the old ones, which are not read.
            r1, r2 = st.columns(2)
            logged = r1.number_input("Metres in signed daily logs", 0.0,
                                     2000.0, None, 1.0, key="fx_logs_m")
            claimed = r2.number_input("Metres invoiced", 0.0, 2000.0, None,
                                      1.0, key="fx_invoiced_m")
            if logged is not None and claimed is not None:
                recon = metres_reconciliation_check(logged, claimed)
                field_checks.append(recon)
                (st.success if recon.passed else st.error)(recon.message)
            st.caption(
                "The daily report template for the driller is in the "
                "Templates page."
            )
        if not field_checks:
            st.caption("Enter measurements above to run the acceptance checks.")

    # measured, so they belong in the record the works are accepted against;
    # only what was measured
    st.session_state.field_checks = field_checks

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
        _sup_gate = report_gate("supervision")
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
                    field_checks=st.session_state.get("field_checks", []),
                    figures_dir=workdir(),
                    readiness=_sup_gate,
                    evidence=st.session_state.get("sup_evidence") or {},
                ),
                workdir() / "Supervision_Checklist_Report.docx",
                app_config(),
            )
            offer_download(report_path, "Download supervision report (.docx)")

    _next_step("Build the handover →", "Handover",
               "Quality assessed. Close the project out with the community.")
