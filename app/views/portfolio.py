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
from shared import (
    app_config,
    figure,
    kept_upload,
    offer_download,
    project_files,
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
    summaries = [summary for summary, _ in read]
    if skipped:
        st.warning(f"{skipped} file(s) could not be read as a project and were skipped.")
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
        _pooled_ledger(read)


def _pooled_ledger(read) -> None:
    """The files' ledgers of predictions and outcomes, pooled (PLAN.md step
    5.1): each point once, the drilled ones listed beside what was found."""
    import json

    from groundwater.ledger import ledger_rows, ledger_summary, pool_ledgers

    st.subheader("Predictions and outcomes")
    pooled = pool_ledgers([(site_label(summary), ledger) for summary, ledger in read])
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
