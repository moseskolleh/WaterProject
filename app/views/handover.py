"""Handover: the closing report for the client and the community."""

from __future__ import annotations

import streamlit as st

from groundwater.project_io import committee_records
from groundwater.reporting.handover import (
    build_handover_report,
    CommitteeMember,
    HandoverReportInputs,
)

from shared import (
    app_config,
    DEFAULT_COMMITTEE,
    offer_download,
    report_gate,
    site_from_state,
    workdir,
)

def render() -> None:
    st.header("Project handover report")
    st.caption(
        "The closing deliverable for the client and the community. Answer "
        "the questions below; results already produced in the other pages "
        "(design, pumping test, water quality) attach automatically."
    )

    design = st.session_state.get("borehole_design")
    log = st.session_state.get("drilling_log")
    pumping = st.session_state.get("pump_analysis")
    quality = st.session_state.get("wq_assessment")
    a1, a2, a3 = st.columns(3)
    a1.metric("Borehole design", "attached" if design is not None else "not yet",
              help="Produce it in the Borehole design page and it attaches here.")
    a2.metric("Pumping test", "attached" if pumping is not None else "not yet",
              help="Analyse a test in the Pumping test page.")
    a3.metric("Water quality", "attached" if quality is not None else "not yet",
              help="Assess a sample in the Water quality page.")
    st.caption(
        "Community, district, client, contractor and supervisor come from "
        "the site details in the sidebar."
    )

    st.subheader("1. The water point")
    h1, h2 = st.columns(2)
    pump_type = h1.text_input(
        "Pump installed (type and model)", key="ho_pump_type",
        placeholder="e.g. India Mark II handpump",
    )
    tariff = h2.text_input(
        "Tariff arrangement agreed with the community", key="ho_tariff",
        placeholder="e.g. 5 SLE per household per month",
    )

    st.subheader("2. WASH committee")
    st.caption("Who is responsible for the water point? Add one row per member.")
    # The editor keeps only its edits (under "ho_committee"), applied to the
    # rows it is given, and Streamlit forgets them when another page is on
    # screen. Coming back to an editor with no edits, it starts from the
    # table as last edited; while it has edits, from the same rows as before,
    # or they would be applied twice.
    if "ho_committee" not in st.session_state and st.session_state.get("ho_committee_data"):
        st.session_state["ho_committee_rows"] = st.session_state["ho_committee_data"]
    committee_rows = st.data_editor(
        st.session_state.get("ho_committee_rows", DEFAULT_COMMITTEE),
        key="ho_committee",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
    )
    # keep a clean, serialisable copy of the committee so it survives reruns
    # and is saved with the project (the data_editor key holds only an edit
    # delta, which is not itself persistable)
    st.session_state["ho_committee_data"] = committee_records(committee_rows)
    committee_notes = st.text_input(
        "Notes on the committee (training received, bank account, ...)",
        key="ho_committee_notes",
    )

    st.subheader("3. Works and sign off")
    works_text = st.text_area(
        "Works completed (one per line; leave empty for the standard list "
        "built from the attached results)",
        key="ho_works",
        height=100,
    )
    recs_text = st.text_area(
        "Extra recommendations (one per line, optional)",
        key="ho_recs",
        height=80,
    )
    s1, s2, s3 = st.columns(3)
    contractor_rep = s1.text_input("Contractor representative", key="ho_contractor_rep")
    client_rep = s2.text_input("Client representative", key="ho_client_rep")
    community_rep = s3.text_input("Community representative", key="ho_community_rep")

    _handover_gate = report_gate("handover")
    if st.button("Build handover report", key="build_handover", type="primary"):
        committee = [
            CommitteeMember(
                role=str(row.get("Role") or "").strip(),
                name=str(row.get("Name") or "").strip(),
                phone=str(row.get("Phone") or "").strip(),
            )
            for row in committee_rows
            if str(row.get("Role") or "").strip() or str(row.get("Name") or "").strip()
        ]
        report_path = build_handover_report(
            HandoverReportInputs(
                site=site_from_state(),
                log=log,
                design=design,
                pumping=pumping,
                quality=quality,
                figures_dir=workdir(),
                works_completed=[w.strip() for w in works_text.splitlines() if w.strip()],
                sited="ves_results" in st.session_state,
                committee=committee,
                committee_notes=committee_notes,
                tariff_note=tariff,
                pump_type=pump_type,
                extra_recommendations=[r.strip() for r in recs_text.splitlines() if r.strip()],
                readiness=_handover_gate,
                contractor_rep=contractor_rep,
                client_rep=client_rep,
                community_rep=community_rep,
            ),
            workdir() / "Handover_Report.docx",
            app_config(),
        )
        # feeds the lifecycle stepper on the Overview page
        st.session_state["handover_built"] = True
        offer_download(report_path, "Download handover report (.docx)")
