"""Geophysics (VES): the sounding curves, the interpretation and the drill target."""

from __future__ import annotations

import html as _html

import streamlit as st

from groundwater.geo import infer_zone_for_sierra_leone
from groundwater.ingestion import check_all
from groundwater.mapping import suitability_map
from groundwater.reporting.geophysical import (
    build_geophysical_report,
    GeophysicalReportInputs,
)
from groundwater.siting import assess_siting, suitability_map_points
from groundwater.text import phrase
from groundwater.ves.interpret import (
    drilling_depth_text,
    drilling_preference_table,
    zone_cell,
)
from groundwater.ves.model_range import (
    model_range_rows,
    model_range_text,
    sample_model_range,
)
from groundwater.ves.plots import plot_sounding_curve

from shared import (
    app_config,
    _band,
    choose_input,
    figure,
    _next_step,
    offer_download,
    _offer_raster,
    parse_source,
    report_gate,
    run_ves_inversion,
    show_flags,
    site_from_state,
    workdir,
    _working,
)


def _ranges_for(results) -> list:
    """The range of models sampled around these very inversions, or Nones.

    Kept against the inversions they were sampled around, so a new run of
    the inversion shows no range until one is sampled again."""
    kept = st.session_state.get("ves_ranges")
    if kept is not None and kept[0] is results:
        return kept[1]
    return [None] * len(results)


def _sample_ranges(soundings, results) -> list:
    """Sample the range of models for every sounding, with a progress bar.

    A few seconds a sounding: thousands of forward calls and a handful of
    fits, which is why it waits for its button rather than running with the
    inversion."""
    ranges = []
    progress = st.progress(0.0, text="Sampling the range of models")
    for i, (sounding, result) in enumerate(zip(soundings, results, strict=True)):
        def told(fraction, _label, i=i, sid=sounding.sounding_id):
            progress.progress(min((i + fraction) / len(results), 1.0),
                              text=f"Sampling the range of models: {sid}")
        ranges.append(sample_model_range(sounding, result, app_config(), told))
    progress.empty()
    st.session_state.ves_ranges = (results, ranges)
    return ranges


def render() -> None:
    st.header("VES survey analysis")
    st.caption(
        "Upload the VES workbook, run the inversion and get sounding "
        "curves, water zones and a drilling preference table."
    )
    # the co-pilot is a browser page; a feature in one app says so in both
    st.caption(phrase("ves_copilot.browser_only"))
    path = choose_input(
        "VES workbook (standard template)", "ves", ["xlsx"],
        ["rokel/rokel_ves.xlsx"],
    )
    if path is not None:
        # a sheet the reader could not use is named with the reason, rather
        # than a three-sheet workbook quietly coming back as two soundings
        soundings, _skipped_sheets = parse_source("ves", path)
        show_flags(_skipped_sheets)
        if soundings is None:
            pass
        elif not soundings:
            st.error("No soundings found in the workbook.")
        else:
            st.success(f"Parsed {len(soundings)} sounding(s).")
            for s in soundings:
                show_flags(s.flags)
            show_flags(check_all([(s.sounding_id, s.site) for s in soundings]))

            if st.button("Run inversion and interpretation", key="run_ves",
                         type="primary"):
                run_ves_inversion(soundings)

    if "ves_results" in st.session_state:
        soundings, results, interps = st.session_state.ves_results
        ranges = _ranges_for(results)
        if st.button(
            "Sample the range of models", key="ves_range",
            help="Sample the models that fit each sounding about as well as its "
            "best fit, for the P10 to P90 of basement, the weathered zone and "
            "the drilling depth. A few seconds a sounding.",
        ):
            ranges = _sample_ranges(soundings, results)
        for sounding, result, interp, model_range in zip(
            soundings, results, interps, ranges, strict=True
        ):
            with st.container(border=True):
                st.subheader(f"{sounding.sounding_id}")
                col_fig, col_txt = st.columns([3, 2])
                fig_path = figure(
                    plot_sounding_curve,
                    sounding, result.model, result.rho_calc, result.ab2,
                    file_name=f"curve_{sounding.sounding_id.replace(' ', '_')}.png",
                    model_range=model_range,
                )
                col_fig.image(str(fig_path))
                col_txt.metric(
                    "Model fit (ERR)", f"{result.fit_error_percent:.1f}%",
                    help="Root-mean-square difference between the measured "
                    "curve and the layered model. Under 5% is an excellent "
                    "fit; 5-10% is acceptable; above 10% treat the layer "
                    "depths as indicative and weight the drilling decision "
                    "on the curve shape and local knowledge.",
                )
                col_txt.caption(
                    "Fit: " + _band(
                        result.fit_error_percent,
                        [(5.0, "excellent - depths well constrained"),
                         (10.0, "acceptable for siting")],
                        "poor - treat the layer depths as indicative only",
                    )
                )
                col_txt.metric(
                    "Water bearing zones",
                    ", ".join(
                        zone_cell(t, b, open_ended=(interp.basement_not_resolved
                                                    and (t, b) == interp.water_zones[-1]))
                        + " m"
                        for t, b in interp.water_zones
                    ) or "none",
                    help="A zone marked + continues below the depth the sounding "
                    "resolves: its base and the drilling depth are minima.",
                )
                col_txt.write(interp.narrative)
                if model_range is not None:
                    # beside the best fit, never in place of it
                    col_txt.info(" ".join(model_range_text(model_range)))
                    col_txt.table([dict(zip(("", "P10", "P50", "P90"), row, strict=True))
                                   for row in model_range_rows(model_range)])
        st.subheader("Drilling preference")
        st.table(drilling_preference_table(interps))

        # The headline the client actually asks for, promoted first-class
        _best_interp = min(
            interps, key=lambda i: (i.rank or 99, -i.score),
        ) if interps else None
        if _best_interp is not None and _best_interp.max_drilling_depth_m:
            _zones = ", ".join(
                zone_cell(t, b, open_ended=(_best_interp.basement_not_resolved
                                            and (t, b) == _best_interp.water_zones[-1]))
                + " m"
                for t, b in _best_interp.water_zones
            )
            st.markdown(
                "<div class='gw-callout'>"
                "<span class='gw-cap'>Recommended drilling depth — "
                f"{_html.escape(_best_interp.sounding_id)}</span>"
                f"<div class='gw-big'>{_html.escape(drilling_depth_text(_best_interp))}</div>"
                + (f"<p>Water bearing zones at {_html.escape(_zones)}.</p>"
                   if _zones else "")
                + "</div>",
                unsafe_allow_html=True,
            )

        with st.expander("🎯 Drill-target suitability (prototype)", expanded=True):
            st.caption(
                "A transparent 0-100 suitability score per point, combining "
                "aquifer thickness, resistivity fit, overburden and any "
                "fracture at the basement contact. It answers 'where should I "
                "drill?' and, as real drilling outcomes accumulate, the weights "
                "can be replaced by a fitted model."
            )
            suitability = assess_siting(interps)
            st.dataframe(
                [
                    {
                        "Rank": s.rank,
                        "Point": s.sounding_id,
                        "Suitability": f"{s.suitability:.0f}/100",
                        "Grade": s.grade,
                        "Why": s.rationale,
                    }
                    for s in suitability
                ],
                hide_index=True,
                width="stretch",
            )
            best = suitability[0]
            st.success(
                f"Recommended drill target: **{best.sounding_id}** "
                f"({best.suitability:.0f}/100, {best.grade}).",
                icon="🎯",
            )
            map_points = suitability_map_points(suitability)
            if map_points:
                zone = site_from_state().utm_zone or infer_zone_for_sierra_leone(
                    map_points[0].easting)
                smap = figure(suitability_map, map_points, zone,
                              file_name="suitability_map.png")
                st.image(str(smap))
                _offer_raster(smap)
            else:
                st.info(
                    "Add GPS coordinates to the VES points (sidebar site "
                    "details) to draw the drill-target map."
                )

        _geo_gate = report_gate("geophysical")
        if st.button("Build geophysical survey report", key="build_geo_report"):
          with _working("Building the geophysical survey report - drawing the "
                        "context maps and writing the document..."):
            report_path = build_geophysical_report(
                GeophysicalReportInputs(
                    soundings=soundings,
                    inversions=results,
                    interpretations=interps,
                    figures_dir=workdir(),
                    flags=check_all([(s.sounding_id, s.site) for s in soundings]),
                    include_qa_annex=True,
                    readiness=_geo_gate,
                    model_ranges=ranges,
                ),
                workdir() / "Geophysical_Survey_Report.docx",
                app_config(),
            )
          offer_download(report_path, "Download geophysical survey report (.docx)")

    _next_step("Cost this borehole →", "Costing & BoQ",
               "Siting done. Price the borehole at the recommended depth.")
