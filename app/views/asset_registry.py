"""Asset registry: the borehole's identifier and what has happened to it since."""

from __future__ import annotations

import re
from datetime import date

import streamlit as st

from groundwater.project_io import deserialize_project
from groundwater.registry import (
    asset_from_dict,
    asset_from_project,
    asset_state,
    asset_with_rising_main,
    AssetEvent,
    EVENT_KINDS,
    merge_events,
    parse_asset_id,
    registry_rows,
    registry_stats,
    Schedule,
    trim_field,
    validate_asset_id,
)
from groundwater.reporting.registry import (
    AssetReportInputs,
    build_asset_placard,
    build_asset_record,
)
from groundwater.reporting.rounds import build_round_sheet
from groundwater.rounds import (
    parse_area_mechanics,
    round_header,
    round_rows,
    round_text,
    rounds_text,
    service_rounds,
)
from groundwater.sanitary import (
    form_questions,
    form_rows,
    inspection_event,
    sanitary_risk,
)
from groundwater.text import phrase, phrase_table

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
    if _live is not None:
        # the rising main of the design as it now stands, whose interval the
        # routine inspection is due by (PLAN.md step 7.3)
        _live = asset_with_rising_main(_live, getattr(
            st.session_state.get("borehole_design"), "rising_main", None))

    st.subheader("This borehole")
    if _live is None:
        st.info(
            "This project has no recorded position yet, so it cannot be given "
            "an identifier - there would be nothing to find the borehole by. "
            "Enter the GPS position in the site details in the sidebar."
        )
    else:
        _state = asset_state(_live, schedule=Schedule.from_config(app_config()))
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
        # the routine inspection's interval is the one that differs from
        # borehole to borehole: it follows the design's rising main
        for _item in _state.due:
            if _item.key == "routine_inspection":
                st.caption(phrase("rounds.interval_line", title=_item.title,
                                  basis=_item.basis))
        _mechanic_field(_live)

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

        _sanitary_inspection(_live)

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
                                        readiness=report_gate("asset"),
                                        schedule=Schedule.from_config(app_config()),
                                        quality=st.session_state.get("wq_assessment"))
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
        _stats = registry_stats(_assets, schedule=Schedule.from_config(app_config()))
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
        _chase = (_stats["n_overdue_inspection"] + _stats["n_overdue_routine"]
                  + _stats["n_overdue_sample"])
        if _chase:
            st.info(
                f"{_stats['n_overdue_inspection']} overdue a sanitary "
                f"inspection, {_stats['n_overdue_routine']} overdue a routine "
                f"inspection, {_stats['n_overdue_sample']} overdue a water "
                "quality sample."
            )
        st.dataframe(registry_rows(_assets, schedule=Schedule.from_config(app_config())),
                     hide_index=True, width="stretch")

    st.divider()
    _service_rounds(_live, _assets)


def _mechanic_field(asset) -> None:
    """The area mechanic named on this borehole's record, whose service round
    it is on (PLAN.md step 7.3). Named here, it travels in the project file;
    a borehole with none named goes to the mechanic named for its chiefdom."""
    # no key: the field starts from the record shown, so another project's
    # borehole does not inherit the name typed for this one
    with st.form("asset_mechanic_form"):
        _name = st.text_input(
            "Area mechanic", value=asset.area_mechanic, placeholder="Area mechanic",
            help="Named on this borehole's record. With none named, the "
                 "service rounds look the chiefdom up.")
        if st.form_submit_button("Name the area mechanic"):
            asset.area_mechanic = trim_field(_name)
            st.session_state["asset_record"] = asset.as_dict()
            st.success("Area mechanic named." if asset.area_mechanic
                       else "Area mechanic cleared.")


def _service_rounds(asset, register) -> None:
    """What is due on a day at this borehole and at every borehole in the
    register, by area mechanic and in order, with the round sheets to print
    (PLAN.md step 7.3). The day is the page's input, today unless another is
    chosen; the engine never reads the clock."""
    st.subheader("Service rounds")
    st.caption(
        "What is due on the day below, at this borehole and at every borehole "
        "in the register above: the sanitary inspection, the routine "
        "inspection of the pump and rising main, and the water quality "
        "sample. Each borehole goes to the area mechanic named on its record, "
        "else to the one named for its chiefdom here. The browser app has the "
        "same rounds on its Asset registry page."
    )
    _when = st.date_input("Round drawn up on", value=date.today(), key="rounds_date")
    # org_ so it is saved with the project, as the browser keeps it in its store
    _text = st.text_area(
        "Area mechanics by chiefdom", key="org_area_mechanics", height=90,
        placeholder="One chiefdom a line: the chiefdom, a colon and the mechanic's name")
    _parsed = parse_area_mechanics(_text)
    for _line in _parsed["skipped"]:
        st.warning(_line)
    # this borehole first, so its record, kept in step with the design, is
    # the one read where the register holds the same borehole
    _assets = ([asset] if asset is not None else []) + list(register)
    _result = service_rounds(_assets, _when, Schedule.from_config(app_config()),
                             _parsed["entries"])
    _words = rounds_text(_result)
    for _line in _words["summary"]:
        st.write(_line)
    for _one in _result["rounds"]:
        _lines = round_text(_one)
        # a mechanic's name is typed by a person: its markdown is escaped
        st.markdown("**" + re.sub(r"([\\`*_\[\]<>#|~$])", r"\\\1", _lines[0]) + "**")
        for _line in _lines[1:]:
            st.caption(_line)
        st.dataframe([dict(zip(round_header(), row, strict=True)) for row in round_rows(_one)],
                     hide_index=True, width="stretch")
    if _result["rounds"]:
        st.caption(_words["method"])
        st.caption(_words["intervals"])
    if st.button("Build round sheets (.docx)", key="rounds_sheet",
                 disabled=not _result["n_boreholes"]):
        offer_download(
            build_round_sheet(_result, workdir() / f"rounds_{_result['as_of']}.docx",
                              app_config()),
            "Round sheets")


def _sanitary_inspection(asset) -> None:
    """The WHO form for a borehole with a handpump, and the risk statement.

    The inspection is recorded against the borehole like any other visit,
    so it travels in the project file and merges by content (PLAN.md step
    7.5). The statement is drawn after the form, so an inspection just
    recorded is the one it reads.
    """
    st.subheader(phrase("sanitary.heading"))
    st.caption(
        "Answer each question as found at the wellhead: yes where the risk "
        "is present. A question left unanswered is not counted as a no, so "
        "an incomplete form gives a range of scores. The statement reads the "
        "latest inspection with the E. coli count of the water quality "
        "sample on the Water quality page. The browser app has the same "
        "form on its Asset registry page."
    )
    words = phrase_table("sanitary.answer")
    with st.form("sanitary_form", clear_on_submit=True):
        st.markdown("**Record a sanitary inspection**")
        _c1, _c2 = st.columns([1, 2])
        _when = _c1.date_input("Date of the inspection", key="sanitary_when")
        _by = _c2.text_input("Inspected by", key="sanitary_by", placeholder="Name")
        _answers = [
            st.radio(f"{number}. {question}", ["-", "Y", "N"],
                     format_func=lambda k: words[k], horizontal=True,
                     key=f"sanitary_q{number}")
            for number, question in enumerate(form_questions(), start=1)
        ]
        _note = st.text_input("Note", key="sanitary_note",
                              placeholder="Anything else seen")
        if st.form_submit_button("Record the inspection"):
            asset.events = merge_events(
                asset.asset_id, asset.events,
                [inspection_event(_when.isoformat(), "".join(_answers),
                                  by=_by.strip(), note=_note)])
            st.session_state["asset_record"] = asset.as_dict()
            st.success("Recorded in the history. A form filled in again on "
                       "another phone merges with this one if it says the same.")

    risk = sanitary_risk(asset, date.today(), st.session_state.get("wq_assessment"))
    if risk["action"] is not None:
        st.metric("Action priority",
                  phrase_table("sanitary.priority_short")[risk["action"]])
    show = {"urgent": st.error, "higher": st.warning}.get(risk["action"] or "", st.info)
    show(risk["statement"])
    inspection = risk["inspection"]
    if inspection is not None:
        st.caption(phrase("sanitary.form_caption", when=inspection["label"]))
        st.dataframe(
            [{phrase("sanitary.col_number"): row[0],
              phrase("sanitary.col_question"): row[1],
              phrase("sanitary.col_answer"): row[2]}
             for row in form_rows(inspection["answers"], inspection["form"])],
            hide_index=True, width="stretch")
    st.caption(phrase("sanitary.basis"))


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
