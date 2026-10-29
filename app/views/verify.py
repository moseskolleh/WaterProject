"""Verify a document (PLAN.md step 8.1).

Whether the toolkit issued a .docx, whether it has changed since, whether it
was certifiable or provisional, and which evidence it was issued from
(:func:`groundwater.verification.verify_document`), checked against the issue
records of the project open in this session and of any project files added
here. Nothing leaves the machine the app runs on. The browser app has the
same page, which works with no network at all.
"""

from __future__ import annotations

import streamlit as st
import yaml

from groundwater.registry import trim_field
from groundwater.text import phrase, phrase_table
from groundwater.verification import (
    clean_issue_records,
    issue_records_of,
    lookup_code,
    verify_document,
)

from shared import kept_upload


def _records(files) -> tuple[list | None, int]:
    """The issue records to check against: this session's and its asset
    record's, and those of the project files added; None where none is held
    and no file was added. Also the number of files that could not be
    read."""
    held = issue_records_of({"issued": st.session_state.get("issued_documents") or [],
                             "asset": st.session_state.get("asset_record")})
    unread = 0
    for upload in files or []:
        try:
            payload = yaml.safe_load(upload.getvalue().decode("utf-8"))
        except (UnicodeDecodeError, yaml.YAMLError):
            unread += 1
            continue
        if not isinstance(payload, dict):
            unread += 1
            continue
        held += issue_records_of(payload)
    records = clean_issue_records(held)
    return (records if records or files else None), unread


def _result(report: dict, name: str) -> None:
    questions = phrase_table("verification.questions")
    show = {"verified": st.success, "unconfirmed": st.warning}.get(report["verdict"], st.error)
    show(f"**{report['lines'][0]}**  \n{name}")
    for key in ("issued", "changed", "readiness", "evidence"):
        if report["answers"].get(key):
            st.markdown(f"**{questions[key]}**")
            st.write(report["answers"][key])
    if report["facts"]:
        st.caption(report["lines"][-1])
        if report["facts"]["evidence"]:
            st.dataframe([{"Evidence file": f["name"], "What it is": f["what"], "SHA-256": f["sha256"]}
                          for f in report["facts"]["evidence"]], hide_index=True, width="stretch")
    if report["code"]:
        st.caption(f"{phrase('verification.cover_code', code=report['code'])} - "
                   f"SHA-256 of its manifest {report['sha256']}")


def render() -> None:
    st.header("Verify a document")
    st.caption(phrase("verification.page_lead"))

    document = st.file_uploader("The document (.docx)", type=["docx"], key="verify_document")
    st.caption(phrase("verification.document_lead"))
    files = kept_upload("Project files to check it against (.yaml or .gwt.json)", "verify_projects",
                        type=["yaml", "yml", "json"], accept_multiple_files=True)
    records, unread = _records(files)
    if unread:
        st.warning(f"{unread} file(s) could not be read as a project and were skipped.")
    st.write(phrase("verification.page_records", n=len(records)) if records is not None
             else phrase("verification.page_no_records"))
    if document is not None:
        _result(verify_document(document.getvalue(), records), document.name)

    st.subheader("Issued from this project")
    issued = clean_issue_records(st.session_state.get("issued_documents") or [])
    if issued:
        words = phrase_table("verification.readiness_words")
        st.dataframe([{"Code": r["code"], "Document": r["title"], "Issued on": r["issued_on"],
                       "Readiness": words[r["readiness"]], "SHA-256": r["sha256"]} for r in issued],
                     hide_index=True, width="stretch")
    else:
        st.caption(phrase("verification.none_issued"))

    st.subheader("Look up a code")
    st.caption(phrase("verification.lookup_lead"))
    typed = trim_field(st.text_input("Document code", key="verify_code", placeholder="0A1B-2C3D-5"))
    if typed:
        found = lookup_code(typed, records or [])
        show = st.success if found["records"] else st.warning
        show("\n\n".join(found["lines"]))
