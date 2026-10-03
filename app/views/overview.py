"""Overview: the project dashboard."""

from __future__ import annotations

import html as _html

import streamlit as st

from groundwater.geo import infer_zone_for_sierra_leone
from groundwater.quality import VERDICT_SHORT
from groundwater.ves.interpret import drilling_depth_text

from shared import (
    _BAR_COLORS,
    _deliverables,
    _goto,
    _rows_html,
    site_from_state,
    _status_chip,
    _stepper_html,
    _VERDICT_CHIP,
)

def render() -> None:
    _ov_site = site_from_state()
    _ov_ves = st.session_state.get("ves_results")
    _ov_log = st.session_state.get("drilling_log")
    _ov_pump = st.session_state.get("pump_analysis")
    _ov_wq = st.session_state.get("wq_assessment")
    _ov_design = st.session_state.get("borehole_design")
    _ov_cost = st.session_state.get("cost_estimate")

    _chip_label, _chip_css = _status_chip()
    _ov_title = _html.escape(_ov_site.community or "New project")
    if _ov_site.district:
        _ov_title += f" — {_html.escape(_ov_site.district)} District"
    _head_l, _head_r = st.columns([3, 1])
    with _head_l:
        st.markdown(
            f"<h2 style='margin:0 0 2px'>{_ov_title} "
            f"<span class='gw-chip {_chip_css}'>{_chip_label}</span></h2>",
            unsafe_allow_html=True,
        )
        _sub = []
        if _ov_site.latlon is not None:
            _lat, _lon = _ov_site.latlon
            _sub.append(f"{_lat:.4f}° N, {abs(_lon):.4f}° W")
        if _ov_site.chiefdom:
            _sub.append(f"{_ov_site.chiefdom} Chiefdom")
        if _ov_site.client:
            _sub.append(_ov_site.client)
        st.caption(" · ".join(_sub) or
                   "The whole borehole lifecycle in one workspace.")
    with _head_r:
        st.button("Generate handover →", key="ov_go_handover",
                  type="primary", width="stretch",
                  on_click=_goto, args=("Handover",))

    # Lifecycle state, derived from what has actually been produced
    st.markdown(
        _stepper_html([
            ("Sited", _ov_ves is not None),
            ("Drilled", _ov_log is not None),
            ("Tested", _ov_pump is not None),
            ("Assessed", _ov_wq is not None),
            ("Handover", bool(st.session_state.get("handover_built"))),
        ]),
        unsafe_allow_html=True,
    )

    _has_results = any(x is not None for x in (
        _ov_ves, _ov_log, _ov_pump, _ov_wq, _ov_cost,
    ))
    if not _has_results:
        st.markdown(
            "<div class='gw-card'><span class='gw-cap'>Getting started</span>"
            "<div style='font-size:0.86rem;color:#b0b0b0;line-height:1.5'>"
            "Nothing has been analysed yet. Work through the guided start, "
            "or open any page from the sidebar - every page offers bundled "
            "sample data (Rokel, Dr Timbo, Kuntolo) so you can try the whole "
            "lifecycle without your own files. Loading a saved project file "
            "from the sidebar restores a previous session, analyses and "
            "all.</div></div>",
            unsafe_allow_html=True,
        )
        _cta1, _cta2, _cta3 = st.columns(3)
        _cta1.button("🚀 Open guided start", key="ov_go_guide",
                     width="stretch",
                     on_click=_goto, args=("Guided start",))
        _cta2.button("📈 Run a VES analysis", key="ov_go_ves",
                     width="stretch",
                     on_click=_goto, args=("Geophysics (VES)",))
        _cta3.button("💰 Estimate a borehole", key="ov_go_cost",
                     width="stretch",
                     on_click=_goto, args=("Costing & BoQ",))
    else:
        _col1, _col2, _col3 = st.columns(3)

        with _col1:
            # Site card
            _site_rows: list[tuple[str, str]] = []
            if _ov_site.district:
                _site_rows.append(("District", _ov_site.district))
            if _ov_site.chiefdom:
                _site_rows.append(("Chiefdom", _ov_site.chiefdom))
            if _ov_site.easting and _ov_site.northing:
                # an unrecorded zone is inferred from the easting here too,
                # so the card prints a zone rather than the word None
                _ov_zone = (_ov_site.utm_zone
                            or infer_zone_for_sierra_leone(_ov_site.easting))
                _site_rows.append((
                    "UTM",
                    (f"{_ov_site.easting:.0f} E · {_ov_site.northing:.0f} N "
                    f"({_ov_zone}N)"),
                ))
            _wp = st.session_state.get("wp_result")
            if _wp and _wp.get("decision"):
                _wp_sum = _wp["decision"].get("summary", {})
                if _wp_sum.get("total") is not None:
                    _site_rows.append((
                        "Water points nearby",
                        (f"{_wp_sum['total']} "
                        f"({_wp_sum.get('functional', 0)} functional)"),
                    ))
            st.markdown(
                "<div class='gw-card'><span class='gw-cap'>Site</span>"
                + (_rows_html(_site_rows) or
                   "<div class='gw-row'><span>No site details yet - set "
                   "them in the sidebar.</span></div>")
                + "</div>",
                unsafe_allow_html=True,
            )

            # Siting / geophysics card
            if _ov_ves is not None:
                _soundings, _results, _interps = _ov_ves
                _best = min(
                    _interps, key=lambda i: (i.rank or 99, -i.score),
                ) if _interps else None
                _ves_rows = [("Soundings analysed", str(len(_results)))]
                if _best is not None:
                    _ves_rows.append(("Preferred site", _best.sounding_id))
                    if _best.depth_to_basement_m:
                        _ves_rows.append((
                            "Depth to basement",
                            f"{_best.depth_to_basement_m:.1f} m",
                        ))
                    if _best.max_drilling_depth_m:
                        _ves_rows.append((
                            "Recommended drilling depth",
                            drilling_depth_text(_best),
                        ))
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Geophysics"
                    "</span>" + _rows_html(_ves_rows) + "</div>",
                    unsafe_allow_html=True,
                )

        with _col2:
            # Borehole card (design first, else the drilling log)
            if _ov_design is not None:
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Borehole"
                    "</span>" + _rows_html(_ov_design.summary_rows()[:6])
                    + "</div>",
                    unsafe_allow_html=True,
                )
            elif _ov_log is not None:
                # total_depth_m is optional: a partially filled log template
                # parses with no depth
                _log_rows = [(
                    "Drilled depth",
                    f"{_ov_log.total_depth_m:.0f} m"
                    if _ov_log.total_depth_m else "pending",
                )]
                if _ov_log.status:
                    _log_rows.append(("Outcome", _ov_log.status))
                if _ov_log.water_strikes_m:
                    _log_rows.append((
                        "Water strikes",
                        ", ".join(f"{w:g} m" for w in _ov_log.water_strikes_m),
                    ))
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Borehole"
                    "</span>" + _rows_html(_log_rows) + "</div>",
                    unsafe_allow_html=True,
                )

            # Pumping test card
            if _ov_pump is not None:
                _yr = _ov_pump.yield_recommendation
                if _yr is not None and _yr.safe_yield_m3_per_h:
                    _pump_head = (
                        f"<div class='gw-big'>{_yr.safe_yield_m3_per_h:.2f} "
                        "<small>m³/h safe yield</small></div>"
                    )
                else:
                    _reason = (_yr.pending_reason if _yr is not None else
                               "discharge pending")
                    _pump_head = (
                        "<span class='gw-chip gw-chip-amber'>Pending</span>"
                        f"<div style='font-size:0.75rem;color:#8c8c8c;"
                        f"margin-top:6px'>{_html.escape(_reason)}</div>"
                    )
                _pump_rows = []
                _t = _ov_pump.transmissivity_m2_per_day
                if _t:
                    _pump_rows.append(("Transmissivity", f"{_t:.1f} m²/day"))
                if _ov_pump.max_drawdown_m:
                    _pump_rows.append(
                        ("Max drawdown", f"{_ov_pump.max_drawdown_m:.2f} m"))
                if _yr is not None and _yr.pump_installation_depth_m:
                    _pump_rows.append((
                        "Pump setting",
                        f"{_yr.pump_installation_depth_m:.0f} m",
                    ))
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Pumping test"
                    "</span>" + _pump_head + _rows_html(_pump_rows) + "</div>",
                    unsafe_allow_html=True,
                )

        with _col3:
            # Water quality card
            if _ov_wq is not None:
                _wq_state = _ov_wq.verdict_state
                _wq_chip = (_VERDICT_CHIP[_wq_state], VERDICT_SHORT[_wq_state])
                if _wq_state == "health_fail":
                    _wq_note = ", ".join(
                        r.parameter for r in _ov_wq.health_exceedances[:4])
                elif _wq_state == "national_fail":
                    _wq_note = ", ".join(
                        r.parameter for r in _ov_wq.national_exceedances[:4])
                elif _wq_state == "indeterminate":
                    _wq_note = "; ".join(_ov_wq.uncertainties[:2])
                elif _wq_state == "aesthetic":
                    _wq_note = ", ".join(
                        r.parameter for r in _ov_wq.aesthetic_exceedances[:4])
                else:
                    _wq_note = "All measured parameters within guideline"
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Water quality"
                    " — WHO</span>"
                    f"<span class='gw-chip {_wq_chip[0]}'>{_wq_chip[1]}</span>"
                    f"<div style='font-size:0.75rem;color:#8c8c8c;"
                    f"margin-top:6px'>{_html.escape(_wq_note)}</div>"
                    + _rows_html([
                        ("Parameters assessed", str(len(_ov_wq.rows))),
                    ])
                    + "</div>",
                    unsafe_allow_html=True,
                )

            # Cost card with the by-stage breakdown bar
            if _ov_cost is not None:
                _stages = [(s, v) for s, v in _ov_cost.by_stage() if v > 0]
                _total = sum(v for _, v in _stages) or 1.0
                _bar_colors = _BAR_COLORS
                _bar = "".join(
                    f"<div style='width:{100 * v / _total:.1f}%;"
                    f"background:{_bar_colors[i % len(_bar_colors)]}'></div>"
                    for i, (_, v) in enumerate(_stages)
                )
                _legend = "".join(
                    f"<span><i style='background:"
                    f"{_bar_colors[i % len(_bar_colors)]}'></i>"
                    f"{_html.escape(s)}</span>"
                    for i, (s, _) in enumerate(_stages)
                )
                st.markdown(
                    "<div class='gw-card'><span class='gw-cap'>Cost estimate"
                    "</span>"
                    f"<div class='gw-big'>US$ {_ov_cost.price_usd:,.0f} "
                    "<small>price</small></div>"
                    f"<div style='font:400 10px \"IBM Plex Mono\",monospace;"
                    f"color:#b0b0b0'>RWSN model · "
                    f"US$ {_ov_cost.cost_per_meter_usd:,.0f}/m</div>"
                    f"<div class='gw-bar'>{_bar}</div>"
                    f"<div class='gw-legend'>{_legend}</div></div>",
                    unsafe_allow_html=True,
                )

            # Report readiness card
            _chk_done = any(
                str(v) in ("Yes", "No", "N/A")
                for k, v in st.session_state.items() if k.startswith("chk_")
            )
            _report_state = [
                ("Geophysical survey", _ov_ves is not None),
                ("Borehole completion", _ov_log is not None),
                ("Pumping test", _ov_pump is not None),
                ("Water quality", _ov_wq is not None),
                ("Cost estimate", _ov_cost is not None),
                ("Supervision record", _chk_done),
                ("Handover", bool(st.session_state.get("handover_built"))),
            ]
            _n_ready = sum(1 for _, ready in _report_state if ready)
            _report_rows = "".join(
                "<div class='gw-report-row'><span>" + _html.escape(name)
                + "</span><span class='gw-chip "
                + ("gw-chip-green'>Ready" if ready else "gw-chip-grey'>—")
                + "</span></div>"
                for name, ready in _report_state
            )
            st.markdown(
                "<div class='gw-card'><span class='gw-cap'>Reports — "
                f"{_n_ready} / {len(_report_state)} ready</span>"
                + _report_rows + "</div>",
                unsafe_allow_html=True,
            )

    # Everything built this session, in one place. A build button is true for
    # a single rerun, so its download button used to disappear as soon as the
    # user touched anything else and the report had to be rebuilt to get it.
    # Every file is built on another page, and only the page on screen runs,
    # so the list is complete by the time the Overview reads it.
    _built = _deliverables()
    if _built:
        st.divider()
        st.subheader("📦 Deliverables")
        st.caption(
            f"{len(_built)} file(s) built this session. They live only in this "
            "session - download what you need before closing the tab, or save "
            "the project file and rebuild them later."
        )
        for _i, (_label, _path) in enumerate(_built):
            _c1, _c2 = st.columns([3, 1])
            _c1.write(f"**{_path.name}**  \n{_label}")
            with open(_path, "rb") as _fh:
                _c2.download_button(
                    "Download", _fh.read(), file_name=_path.name,
                    key=f"deliverable_{_i}", width="stretch",
                )
