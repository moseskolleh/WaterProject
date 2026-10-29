"""Portfolio: many saved projects side by side."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from groundwater.mapping import geolibre, load_admin, plot_portfolio_map
from groundwater.portfolio import (
    portfolio_points,
    portfolio_rows,
    portfolio_stats,
    site_detail,
    site_label,
    site_one_pager,
)
from groundwater.text import phrase
from shared import (
    app_config,
    figure,
    issue_for,
    kept_upload,
    offer_download,
    project_file_evidence,
    project_files,
    put_set_in_force,
    record_issue,
    workdir,
)

def render() -> None:
    st.header("Borehole portfolio")
    st.caption(
        "See many boreholes side by side. Save a project from the sidebar "
        "(each file carries a short summary), then drop several of them here "
        "for a status map, a comparison table and headline figures - the "
        "programme view a water manager needs."
    )
    # the browser app saves .gwt.json; its summary block has the same schema
    # and the user guide promises either app can pool the other's files
    files = kept_upload(
        "Saved project files (.yaml or .gwt.json)", "portfolio_upload",
        type=["yaml", "yml", "json"], accept_multiple_files=True,
    )
    read, skipped = project_files(f.getvalue() for f in files or [])
    # each file pooled, by its hash, which a calibration report over the
    # pooled ledgers is issued from (PLAN.md step 8.1)
    evidence = [project_file_evidence(f.name, f.getvalue()) for f in files or []
                if not project_files([f.getvalue()])[1]]
    summaries = [summary for summary, _, _ in read]
    if skipped:
        st.warning(f"{skipped} file(s) could not be read as a project and were skipped.")
    pooled: list = []
    if not summaries:
        st.info("Upload two or more saved project files to build the portfolio.")
    else:
        stats = portfolio_stats(summaries)
        if stats.get("n_values_unreadable"):
            st.warning(
                f"{stats['n_values_unreadable']} value(s) in the uploaded summaries "
                "could not be read as numbers and are left blank (a hand-edited "
                "depth, yield or cost, for example)."
            )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Projects", stats["n_projects"])
        c2.metric("Successful", stats["n_successful"],
                  help=f"of {stats['n_drilled']} drilled")
        if stats["success_rate"] is not None:
            c3.metric("Success rate", f"{stats['success_rate']:.0f}%")
        if stats["mean_cost_per_meter_usd"] is not None:
            c4.metric("Mean cost/m", f"${stats['mean_cost_per_meter_usd']:.0f}")
        if stats["n_status_unrecognised"]:
            st.warning(
                f"{stats['n_status_unrecognised']} project(s) carry a status "
                "this toolkit does not recognise; they are counted as neither "
                "successful nor dry. Correct the status on the drilling log."
            )
        if stats["n_wq_assessed"]:
            # Three rates, not one. A single "pass rate" counted an aesthetic
            # exceedance as safe and hid national-standard failures inside it.
            w1, w2, w3 = st.columns(3)
            w1.metric(
                "Water: compliant", f"{stats['wq_compliant_rate']:.0f}%",
                help="Meets every health and national limit "
                     f"({stats['n_wq_assessed']} sampled)",
            )
            w2.metric(
                "Water: failing", f"{stats['wq_fail_rate']:.0f}%",
                help="Exceeds a health guideline or a national standard limit",
            )
            w3.metric(
                "Water: unproven", f"{stats['wq_unproven_rate']:.0f}%",
                help="Results incomplete or not evaluable - safety not established",
            )
        points = portfolio_points(summaries)
        if points:
            pmap = figure(plot_portfolio_map, points, style=app_config().style,
                          file_name="portfolio_map.png")
            st.image(str(pmap))
            if st.button("Build GeoLibre project", key="run_geolibre_portfolio",
                         help="The same portfolio as an interactive map file"):
                _, _districts = load_admin()
                path = geolibre.write_project(
                    geolibre.portfolio_project(points, districts=_districts),
                    workdir() / "portfolio.geolibre.json",
                )
                st.session_state["geolibre_portfolio"] = str(path)
            if st.session_state.get("geolibre_portfolio"):
                offer_download(Path(st.session_state["geolibre_portfolio"]),
                               "Download portfolio GeoLibre project")
        else:
            st.info("Add GPS coordinates to the projects to place them on the map.")
        st.subheader("Comparison")
        st.dataframe(
            portfolio_rows(summaries), hide_index=True, width="stretch"
        )

        _site_detail(summaries)
        _scorecards(read, evidence)
        pooled = _pooled_ledger(read, evidence)
    _calibration_sets(pooled)


def _scorecards(read, evidence=()) -> None:
    """The contractor scorecards over the files (PLAN.md step 6.3): the
    summary, the scorecards and the checks that failed on the page, and the
    whole report as a Word document, issued from the project files on the
    page (``evidence``). The browser app shows the same."""
    import hashlib
    import json

    from groundwater.reporting.scorecards import build_scorecard_report
    from groundwater.scorecards import scorecard_content

    st.subheader(phrase("scorecards.page_heading"))
    st.caption(phrase("scorecards.page_lead"))
    config = app_config()
    files = [(site_label(summary), works, ledger) for summary, ledger, works in read]
    issue = issue_for("scorecards", files=evidence)
    issued = issue.issued_on
    content = scorecard_content(files, issued, config)
    for text in content["summary"]:
        st.markdown(text)
    for section in content["sections"]:
        if section["key"] not in ("cards", "checks"):
            continue
        for table in section["tables"]:
            st.caption(table["caption"])
            st.dataframe([dict(zip(table["header"], row, strict=True)) for row in table["rows"]],
                         hide_index=True, width="stretch")
    # the report is offered while the files it was built from are the ones
    # on the page; other files want it built again
    basis = hashlib.sha256(json.dumps(files, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    if st.button(phrase("scorecards.page_build"), key="build_scorecards", help=phrase("scorecards.page_build_help")):
        path = build_scorecard_report(files, workdir() / "Contractor_Scorecards.docx", issued, config,
                                      issue=issue)
        record = record_issue(path)
        st.session_state["scorecard_report"] = {"path": str(path), "basis": basis,
                                                "code": record["code"] if record else ""}
    built = st.session_state.get("scorecard_report")
    if built and built["basis"] == basis:
        # not kept among the session's deliverables, which would go on
        # offering it once other files are on the page
        offer_download(Path(built["path"]), "Download the contractor scorecards (.docx)", keep=False)
        if built.get("code"):
            st.caption(phrase("verification.cover_code", code=built["code"]))


def _pooled_ledger(read, evidence=()) -> list:
    """The files' ledgers of predictions and outcomes, pooled (PLAN.md step
    5.1): each point once, the drilled ones listed beside what was found.
    Returns the pooled entries. ``evidence`` is the files', which a
    calibration report is issued from."""
    import json

    from groundwater.ledger import ledger_rows, ledger_summary, pool_ledgers

    st.subheader("Predictions and outcomes")
    pooled = pool_ledgers([(site_label(summary), ledger) for summary, ledger, _ in read])
    st.caption(ledger_summary(pooled))
    header, rows = ledger_rows(pooled)
    if rows:
        st.dataframe([dict(zip(header, row, strict=True)) for row in rows], hide_index=True,
                     width="stretch")
    if pooled:
        # every entry with its numbers, for the calibration that learns from
        # them (PLAN.md step 5.2); the browser app writes the same file
        path = workdir() / "pooled_ledger.json"
        path.write_text(json.dumps(pooled, indent=1, ensure_ascii=False), encoding="utf-8")
        offer_download(path, "Download the pooled ledger (.json)", keep=False)
        _calibration(pooled, evidence)
    return pooled


def _calibration(pooled, evidence=()) -> None:
    """The calibration report over the pooled ledgers (PLAN.md step 5.2):
    its summary and its two figures on the page, and the whole report, with
    the band, the odds and the hit rates, as a Word document, issued from
    the project files pooled (``evidence``)."""
    import hashlib
    import json

    from groundwater.calibration import calibration_content, depth_scores, odds_scores
    from groundwater.calibration_plots import plot_depth_calibration, plot_reliability
    from groundwater.reporting.calibration import build_calibration_report, figure_keys

    st.subheader("Calibration")
    config = app_config()
    issue = issue_for("calibration", files=evidence)
    issued = issue.issued_on
    content = calibration_content(pooled, issued, config)
    for text in content["summary"][1:]:
        st.markdown(text)
    keys = figure_keys(content)
    if "depth" in keys:
        st.image(str(figure(plot_depth_calibration, depth_scores(pooled, config), style=config.style,
                            file_name="calibration_depth.png")))
    if "reliability" in keys:
        st.image(str(figure(plot_reliability, odds_scores(pooled, config), style=config.style,
                            file_name="calibration_reliability.png")))
    # the report is offered while the files it was built from are the ones
    # on the page; another set of files wants it built again
    pooled_sig = hashlib.sha256(json.dumps(pooled, sort_keys=True).encode("utf-8")).hexdigest()
    if st.button("Build the calibration report (.docx)", key="build_calibration",
                 help="The band, the odds and the hit rates by geology, survey team and contractor"):
        path = build_calibration_report(pooled, workdir() / "Calibration_Report.docx", issued, config,
                                        figures_dir=workdir() / "calibration_figures", issue=issue)
        record = record_issue(path)
        st.session_state["calibration_report"] = {"path": str(path), "pooled": pooled_sig,
                                                  "code": record["code"] if record else ""}
    built = st.session_state.get("calibration_report")
    if built and built["pooled"] == pooled_sig:
        # not kept among the session's deliverables, which would go on
        # offering it once other files are on the page
        offer_download(Path(built["path"]), "Download the calibration report (.docx)", keep=False)
        if built.get("code"):
            st.caption(phrase("verification.cover_code", code=built["code"]))


def _calibration_sets(pooled) -> None:
    """The calibration set in force for the session (PLAN.md step 5.3): its
    name and what it changes, to download, to replace with a file or to
    return to the provisional default; with pooled ledgers, a set fitted to
    them and reviewed beside it; and sets other organisations adopted,
    pooled into one and reviewed the same way (PLAN.md step 5.5). Either is
    for a named person to adopt and put in force. Nothing changes until
    someone does."""
    import datetime
    import hashlib
    import json

    from groundwater.calibration_sets import (
        fit_set,
        in_force,
        set_changes,
        set_name,
        set_yaml,
    )

    st.subheader(phrase("calibration_sets.page_heading"))
    st.caption(phrase("calibration_sets.page_lead"))
    told = st.session_state.pop("calibration_told", None)
    if told is not None:
        (st.success if told[0] == "ok" else st.error)(told[1])
    config = app_config()
    held = in_force(config)
    st.markdown(phrase("calibration_sets.page_in_force", name=set_name(held)))
    for line in set_changes(held):
        st.markdown(f"- {line}")
    path = workdir() / "calibration.yaml"
    path.write_text(set_yaml(held), encoding="utf-8")
    offer_download(path, phrase("calibration_sets.page_download"), keep=False)
    st.caption(phrase("calibration_sets.page_share"))
    upload = st.file_uploader(phrase("calibration_sets.page_load"), type=["yaml", "yml"],
                              key="calibration_upload")
    st.button(phrase("calibration_sets.page_load_button"), key="calibration_load", disabled=upload is None,
              on_click=_load_set)
    if held["version"] != 0:
        st.button(phrase("calibration_sets.page_default"), key="calibration_default",
                  on_click=_return_to_default)
    today = datetime.date.today().isoformat()
    if not pooled:
        st.info(phrase("calibration_sets.page_fit_none"))
    else:
        # a fit is reviewed while the files it was fitted to and the set it
        # was fitted under are the ones on the page
        basis = hashlib.sha256(json.dumps([pooled, held], sort_keys=True).encode("utf-8")).hexdigest()
        if st.button(phrase("calibration_sets.page_fit"), key="calibration_fit",
                     help=phrase("calibration_sets.page_fit_help")):
            st.session_state["calibration_candidate"] = {"set": fit_set(pooled, today, config), "basis": basis}
        fitted = st.session_state.get("calibration_candidate")
        if fitted and fitted["basis"] == basis:
            _review(fitted["set"], config, held, today, "calibration", "calibration_candidate")
    _pool(config, held, today)


def _review(candidate, config, held, today, key: str, kept: str) -> None:
    """A fitted or pooled set's review beside the set in force, and where it
    fits anything, the name of whoever adopts it, their organisation and a
    contact, and the button that adopts it. ``key`` prefixes the widgets'
    keys and ``kept`` is the session key the set under review is kept in."""
    from groundwater.calibration_sets import set_review

    review = set_review(candidate, config)
    with st.container(border=True):
        st.markdown(f"**{review['title']}**")
        for line in review["summary"]:
            st.markdown(line)
        for table in review["tables"]:
            st.caption(table["caption"])
            st.dataframe([dict(zip(table["header"], row, strict=True)) for row in table["rows"]],
                         hide_index=True, width="stretch")
        if review["adoptable"]:
            st.text_input(phrase("calibration_sets.page_adopter"), key=f"{key}_adopter",
                          help=phrase("calibration_sets.page_adopter_help"))
            # the organisation the sidebar brands the reports with, to start
            st.text_input(phrase("calibration_sets.page_organisation"), key=f"{key}_organisation",
                          value=st.session_state.get("org_name", "") or "",
                          help=phrase("calibration_sets.page_organisation_help"))
            st.text_input(phrase("calibration_sets.page_contact"), key=f"{key}_contact",
                          help=phrase("calibration_sets.page_contact_help"))
            st.button(phrase("calibration_sets.page_adopt"), key=f"{key}_adopt", type="primary",
                      on_click=_adopt, args=(candidate, held, today, key, kept))


def _pool(config, held, today) -> None:
    """Calibration sets other organisations adopted, pooled into one
    (PLAN.md step 5.5) and reviewed beside the set in force. A file that is
    not a set, or a set that cannot be pooled, is refused in a sentence
    naming it, and nothing is pooled."""
    import hashlib
    import json

    st.markdown(f"**{phrase('calibration_sets.page_pool')}**")
    st.caption(phrase("calibration_sets.page_pool_help"))
    files = st.file_uploader(phrase("calibration_sets.page_pool_load"), type=["yaml", "yml"],
                             accept_multiple_files=True, key="calibration_pool_upload")
    st.button(phrase("calibration_sets.page_pool_button"), key="calibration_pool", disabled=not files,
              on_click=_pool_files, args=(config, today))
    pooled = st.session_state.get("calibration_pooled")
    # reviewed while the set in force it was pooled beside is the one in force
    basis = hashlib.sha256(json.dumps(held, sort_keys=True).encode("utf-8")).hexdigest()
    if pooled and pooled["basis"] == basis:
        _review(pooled["set"], config, held, today, "calibration_pool", "calibration_pooled")


def _pool_files(config, today) -> None:
    """Pool the uploaded set files (a button's callback, run before the
    page), or say why not."""
    import hashlib
    import json

    import yaml

    from groundwater.calibration_sets import in_force, pool_sets

    files = st.session_state.get("calibration_pool_upload") or []
    raws = []
    for upload in files:
        try:
            raws.append(yaml.safe_load(upload.getvalue().decode("utf-8", errors="replace")))
        except yaml.YAMLError:
            raws.append(None)
    st.session_state.pop("calibration_pooled", None)
    try:
        pooled = pool_sets(raws, today, config, labels=[upload.name for upload in files])
    except ValueError as exc:
        st.session_state["calibration_told"] = ("error", str(exc))
        return
    basis = hashlib.sha256(json.dumps(in_force(config), sort_keys=True).encode("utf-8")).hexdigest()
    st.session_state["calibration_pooled"] = {"set": pooled, "basis": basis}


def _put_in_force(s) -> bool:
    """Put ``s`` in force (a button's callback, run before the page), and
    say so on the page, or why not."""
    from groundwater.calibration_sets import set_name

    try:
        put_set_in_force(s)
    except ValueError as exc:
        st.session_state["calibration_told"] = ("error", str(exc))
        return False
    st.session_state["calibration_told"] = (
        "ok", phrase("calibration_sets.page_put_in_force", name=set_name(s)))
    return True


def _return_to_default() -> None:
    """Put the provisional default back in force."""
    from groundwater.calibration_sets import default_set

    _put_in_force(default_set())


def _load_set() -> None:
    """Put the uploaded calibration.yaml in force, read whole or refused."""
    from groundwater.calibration_sets import read_set

    upload = st.session_state.get("calibration_upload")
    if upload is None:
        return
    try:
        s = read_set(upload.getvalue().decode("utf-8", errors="replace"))
    except ValueError as exc:
        st.session_state["calibration_told"] = ("error", str(exc))
        return
    _put_in_force(s)


def _adopt(candidate, held, today, key: str, kept: str) -> None:
    """Adopt the set under review in the name typed beside it, for the
    organisation and contact typed with it, and put it in force."""
    from groundwater.calibration_sets import adopt_set

    try:
        adopted = adopt_set(candidate, st.session_state.get(f"{key}_adopter", ""), today, held,
                            organisation=st.session_state.get(f"{key}_organisation", ""),
                            contact=st.session_state.get(f"{key}_contact", ""))
    except ValueError as exc:
        st.session_state["calibration_told"] = ("error", str(exc))
        return
    if _put_in_force(adopted):
        st.session_state.pop(kept, None)


@st.fragment
def _site_detail(summaries) -> None:
    """One site's record and brief; picking another site reruns this alone."""
    st.subheader("Site detail")
    st.caption("Drill into one site for its full record and a one-page brief.")
    choice = st.selectbox(
        "Select a site", list(range(len(summaries))),
        format_func=lambda i: site_label(summaries[i], i),
        key="portfolio_site",
    )
    chosen = summaries[choice]
    st.table(
        [{"Field": field, "Value": value}
         for field, value in site_detail(chosen)]
    )
    _brief_name = (chosen.get("community") or "site").strip().replace(" ", "_")
    st.download_button(
        "Download site brief (.txt)", site_one_pager(chosen),
        file_name=f"{_brief_name}_brief.txt", mime="text/plain",
        key="portfolio_onepager",
    )
