"""Handover: the closing report for the client and the community."""

from __future__ import annotations

import streamlit as st

from groundwater.community_sheet import community_sheet_content
from groundwater.project_io import committee_records
from groundwater.reporting.community_sheet import build_community_sheet
from groundwater.reporting.handover import (
    build_handover_report,
    CommitteeMember,
    HandoverReportInputs,
)

from groundwater.text import languages, phrase

from shared import (
    _file_stem,
    app_config,
    DEFAULT_COMMITTEE,
    evidence_bundle,
    issue_for,
    kept_upload,
    offer_document,
    offer_download,
    report_gate,
    session_documents,
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
            issue=issue_for("handover"),
        )
        # feeds the lifecycle stepper on the Overview page
        st.session_state["handover_built"] = True
        offer_document(report_path, "Download handover report (.docx)")

    _community_sheet_section(pumping, quality, committee_rows, _handover_gate)
    _evidence_bundle_section()


def _community_sheet_section(pumping, quality, committee_rows, gate) -> None:
    """The community handover sheet (PLAN.md step 9.1): what it needs that the
    page does not already hold, what it will say, and the button. The browser
    app's Handover page has the same card; what the sheet says is worked out
    by one function in each engine, held together by the parity suite."""
    st.subheader("Community handover sheet")
    st.caption(phrase("community_sheet.about"))
    held = st.session_state.get("asset_record") or {}
    if "ho_sheet_asset" not in st.session_state and held.get("asset_id"):
        # the borehole the Asset registry page is on, where there is one
        st.session_state["ho_sheet_asset"] = held["asset_id"]
    # The choice of language is offered only where a translation is: one that
    # names who translated it and who checked it, and has no fault
    # (groundwater.text.languages). With none, the sheet is English and says
    # so (PLAN.md step 9.2).
    offered = {language["code"]: language["name"] for language in languages()}
    if st.session_state.get("ho_sheet_language") not in offered:
        # English, or a project saved where a translation was installed and
        # opened where it is not
        st.session_state["ho_sheet_language"] = ""
    c1, c2, c3 = st.columns(3) if offered else (*st.columns(2), None)
    hours = c1.number_input(
        "Hours the pump is used each day", min_value=0.0, max_value=24.0, value=None,
        step=0.5, key="ho_sheet_hours", help="for the amount of water in a day")
    asset_id = c2.text_input(
        "Borehole identifier", key="ho_sheet_asset",
        help="as on its plate, from the Asset registry")
    language = ""
    if c3 is not None:
        language = c3.selectbox(
            "Language of the sheet", ["", *offered], key="ho_sheet_language",
            format_func=lambda code: offered.get(code, "English"),
            help="what the translation has no words for is printed in English")
    # a project resting on a bundled example says so across the sheet's top,
    # even where the handover report's requirement was overridden
    example = any(req.key == "field_data" and req.state in ("unmet", "overridden")
                  for req in gate.requirements)
    # the table as the session keeps it: plain text, whatever the editor held
    # (an emptied cell of a data frame comes back as the text "nan")
    members = [{key.lower(): "" if value == "nan" else value for key, value in row.items()}
               for row in committee_records(committee_rows)]
    given = dict(
        analysis=pumping, quality=quality, committee=members,
        asset_id=asset_id or "", hours_per_day=hours, example=example, config=app_config(),
        language=language or "")
    try:
        content = community_sheet_content(site_from_state(), **given)
    except ValueError as exc:
        # a report address the registry will not print on a plate, or a link
        # too long for the square
        st.error(str(exc))
        return
    st.markdown("**What the sheet will say**")
    if content["example"]:
        st.warning(content["example"])
    st.markdown(f"- {content['water']['headline']}\n- {content['quality']['headline']}")
    st.markdown("**What it could not say, and why**")
    st.caption("\n".join(f"- {note}" for note in content["notes"]))
    if st.button("Community sheet (.docx)", key="build_community_sheet"):
        folder = workdir() / "community_sheet"
        # a sheet in another language is a file of its own beside the English
        name = f"community_sheet_{language}.docx" if language else "community_sheet.docx"
        try:
            path = build_community_sheet(site_from_state(), folder / name,
                                         folder, issue=issue_for("community_sheet"), **given)
        except ValueError as exc:
            st.error(f"Could not build the community sheet: {exc}")
        else:
            offer_document(path, "Download the community sheet (.docx)")


def _evidence_bundle_section() -> None:
    """One evidence bundle for the borehole (PLAN.md step 8.3): the sheets as
    uploaded, the documents issued with their manifests and the figures they
    embed, the issue records and a manifest.json of every file's SHA-256.
    The browser app's Handover page has the same card."""
    st.subheader("Evidence bundle")
    st.caption(phrase("bundle.page_lead"))
    held = session_documents()
    if held:
        st.caption(phrase("bundle.page_documents"))
        st.dataframe([{"Document built in this session": name} for name, _ in held],
                     hide_index=True, width="stretch")
    else:
        st.caption(phrase("bundle.page_no_documents"))
    added = kept_upload("Documents issued earlier (.docx)", "bundle_documents", type=["docx"],
                        accept_multiple_files=True)
    if st.button("Build the evidence bundle", key="build_bundle"):
        try:
            built = evidence_bundle([(f.name, f.getvalue()) for f in added or []])
        except ValueError as exc:
            st.error(str(exc))
            return
        site = site_from_state()
        path = workdir() / f"Evidence_Bundle_{_file_stem(site.community or site.project)}.zip"
        path.write_bytes(built["bytes"])
        offer_download(path, "Download evidence bundle (.zip)")
        st.caption(phrase("bundle.built", files=len(built["facts"]["files"]),
                          documents=len(built["facts"]["documents"]), sha256=built["sha256"]))
