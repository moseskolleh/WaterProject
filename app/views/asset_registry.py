"""Asset registry: the borehole's identifier and what has happened to it since."""

from __future__ import annotations

import streamlit as st

from groundwater.project_io import deserialize_project
from groundwater.registry import (
    asset_from_dict,
    asset_from_project,
    asset_state,
    AssetEvent,
    EVENT_KINDS,
    merge_events,
    parse_asset_id,
    registry_rows,
    registry_stats,
    validate_asset_id,
)
from groundwater.reporting.registry import (
    AssetReportInputs,
    build_asset_placard,
    build_asset_record,
)

from shared import (
    app_config,
    kept_upload,
    offer_download,
    _project_state,
    report_gate,
    workdir,
)

def render() -> None:
    st.header("Borehole asset registry")
    st.caption(
        "A drilling project ends; the borehole does not. This page holds the "
        "other half: a stable identifier that outlives the project file, the "
        "maintenance history recorded against it, and what that history says "
        "is true today. Nothing here is assumed - a borehole nobody has "
        "reported on is not working, it is unknown."
    )

    _asset = st.session_state.get("asset_record")
    _draft = asset_from_project(_project_state())
    if not _asset and _draft is not None:
        _asset = _draft.as_dict()
    _live = asset_from_dict(_asset) if _asset else None

    st.subheader("This borehole")
    if _live is None:
        st.info(
            "This project has no recorded position yet, so it cannot be given "
            "an identifier - there would be nothing to find the borehole by. "
            "Enter the GPS position in the site details in the sidebar."
        )
    else:
        _state = asset_state(_live)
        _c1, _c2, _c3 = st.columns([2, 1, 1])
        _c1.metric("Identifier", _live.asset_id)
        _c2.metric("Status", _state.label)
        if _state.days_out_of_service is not None:
            _c3.metric("Out of service", f"{_state.days_out_of_service} days")
        st.caption(
            "The identifier is derived from the position, so two teams at the "
            "same wellhead with no connection between them arrive at the same "
            "one. The last character is a check character: it catches every "
            "single mistyped character and every transposition of two."
        )
        st.write(_state.detail)
        _outstanding = [i for i in _state.due if i.state in ("overdue", "unknown")]
        if _outstanding:
            for _item in _outstanding:
                st.warning(_item.detail)
        else:
            for _item in _state.due:
                st.caption(_item.detail)

        with st.form("asset_event_form", clear_on_submit=True):
            st.markdown("**Record what happened**")
            _f1, _f2, _f3 = st.columns([1, 1, 2])
            _when = _f1.date_input("Date", key="asset_event_when")
            _kind = _f2.selectbox(
                "What happened", list(EVENT_KINDS),
                format_func=lambda k: EVENT_KINDS[k][0], key="asset_event_kind")
            _by = _f3.text_input("Recorded by", key="asset_event_by",
                                 placeholder="Name")
            _note = st.text_input("Note", key="asset_event_note",
                                  placeholder="What was found or done")
            if st.form_submit_button("Add to the history"):
                _events = merge_events(
                    _live.asset_id, _live.events,
                    [AssetEvent(when=_when.isoformat(), kind=_kind,
                                note=_note, by=_by)])
                _live.events = _events
                st.session_state["asset_record"] = _live.as_dict()
                st.success("Recorded. The history is append-only: a mistake is "
                           "corrected by recording the correction.")
        st.caption(
            "The history travels inside the saved project file, so a record "
            "kept only in this browser is one bad laptop away from gone."
        )

        if _live.events:
            st.subheader("History")
            st.dataframe(
                [{"Date": e.when or "(no date)", "Event": e.label,
                  "Note": e.note, "Recorded by": e.by} for e in _live.events],
                hide_index=True, width="stretch",
            )

        _r1, _r2 = st.columns(2)
        if _r1.button("Build identification plate (.docx)", key="asset_placard"):
            _inputs = AssetReportInputs(asset=_live, figures_dir=workdir(),
                                        readiness=report_gate("placard"))
            offer_download(
                build_asset_placard(_inputs,
                                    workdir() / f"placard_{_live.asset_id}.docx",
                                    app_config()),
                "Borehole identification plate")
        if _r2.button("Build asset record (.docx)", key="asset_record_report"):
            _inputs = AssetReportInputs(asset=_live, figures_dir=workdir(),
                                        readiness=report_gate("asset"))
            offer_download(
                build_asset_record(_inputs,
                                   workdir() / f"asset_{_live.asset_id}.docx",
                                   app_config()),
                "Borehole asset record")

    st.divider()
    _look_up_an_identifier()

    st.divider()
    st.subheader("Many boreholes")
    st.caption(
        "Drop in saved project files to see the whole register: what is "
        "working, what is not, and what is overdue a visit."
    )
    _files = kept_upload(
        "Saved project files (.yaml)", "registry_upload", type=["yaml", "yml"],
        accept_multiple_files=True)
    _assets, _dropped = [], 0
    for _uploaded in _files or []:
        try:
            _updates = deserialize_project(_uploaded.getvalue())
        except Exception:  # noqa: BLE001 - a bad file is dropped and counted
            _dropped += 1
            continue
        _record = asset_from_dict(_updates.get("asset") or {})
        if _record is None:
            _dropped += 1
            continue
        _assets.append(_record)
    if _dropped:
        st.warning(
            f"{_dropped} file(s) carried no readable asset record and were "
            "skipped. A project file only carries one once the borehole has "
            "been given an identifier on this page."
        )
    if not _assets:
        st.info("Upload saved project files that carry an asset record.")
    else:
        _stats = registry_stats(_assets)
        _s1, _s2, _s3, _s4 = st.columns(4)
        _s1.metric("Boreholes", _stats["n_assets"])
        _s2.metric("Working", _stats["n_functional"])
        _s3.metric("Not working", _stats["n_non_functional"])
        _s4.metric("Condition unknown", _stats["n_unknown"])
        if _stats["functionality_rate"] is not None:
            st.metric("Functionality rate", f"{_stats['functionality_rate']:.0f}%",
                      help="Over the boreholes whose condition is actually "
                           "known. A rate computed over silence is the number "
                           "that makes these registers untrustworthy.")
        if _stats["n_unknown"]:
            st.warning(
                f"{_stats['n_unknown']} borehole(s) have nothing recorded "
                "against them at all. That is not the same as nothing having "
                "happened to them."
            )
        _chase = _stats["n_overdue_inspection"] + _stats["n_overdue_sample"]
        if _chase:
            st.info(
                f"{_stats['n_overdue_inspection']} overdue a sanitary "
                f"inspection, {_stats['n_overdue_sample']} overdue a water "
                "quality sample."
            )
        st.dataframe(registry_rows(_assets), hide_index=True, width="stretch")


@st.fragment
def _look_up_an_identifier() -> None:
    """Check an identifier read off a plate; typing one reruns this alone."""
    st.subheader("Look up an identifier")
    _typed = st.text_input(
        "Identifier from a headworks plate", key="asset_lookup",
        placeholder="SL-WAR-8FEEVKQ-T")
    if _typed:
        _ok, _reason = validate_asset_id(_typed)
        if _ok:
            st.success(f"That is a valid identifier: {parse_asset_id(_typed)}")
        else:
            st.error(_reason)
