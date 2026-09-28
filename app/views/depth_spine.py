"""Depth Spine: the whole borehole on one depth axis."""

from __future__ import annotations

import streamlit as st

from shared import (
    build_spine_view,
    component_available,
    CONFIG,
    depth_spine,
    _goto,
    _next_step,
    render_static,
    spine_design,
    SPINE_ERROR,
    _spine_frame_height,
    _spine_iframe,
    _spine_screen_editor,
    spine_screens_key,
    SpineInputs,
    static_build_available,
)

def render() -> None:
    st.header("Depth Spine")
    st.caption(
        "The whole borehole on one depth axis: the cuttings log, the casing "
        "string and the water levels registered against the same ruler, with "
        "the screened intervals editable. Everything shown is computed here, "
        "by the same functions that write the reports."
    )

    spine_log = st.session_state.get("drilling_log")

    if build_spine_view is None:
        st.info(
            "The Depth Spine workspace is not available in this deployment. "
            "Every figure it would show is on the Borehole design, Pumping "
            "test, Water quality and Costing pages."
        )
        if SPINE_ERROR:
            st.caption(f"Workspace unavailable: {SPINE_ERROR}")
    elif spine_log is None:
        st.info(
            "Load a drilling log on the Borehole design page first — the spine "
            "is drawn from the logged hole."
        )
        st.button(
            "Go to Borehole design", key="spine_goto_design",
            on_click=_goto, args=("Borehole design",),
        )
    else:
        analysis = st.session_state.get("pump_analysis")
        assessment = st.session_state.get("wq_assessment")

        # The screens the analyst has placed on the section, if any. Keyed by
        # the borehole so one hole's screens never land on another's.
        spine_key = spine_screens_key(spine_log)
        placed = st.session_state.get(spine_key)

        spine_view = build_spine_view(
            SpineInputs(
                name=spine_log.site.community or "Borehole",
                log=spine_log,
                analysis=analysis,
                assessment=assessment,
                config=CONFIG,
            ),
            screens_m=placed,
        )

        missing = []
        if analysis is None:
            missing.append("a pumping test")
        if assessment is None:
            missing.append("a water quality analysis")
        if missing:
            st.caption(
                "Showing the section and the bill of quantities. Load "
                + " and ".join(missing)
                + " to fill in the remaining stages."
            )

        interactive = component_available()
        result = None

        if interactive:
            result = depth_spine(spine_view, key="spine_workspace")

            # The component reports the intervals it moved; re-deriving them is
            # this script's job, not the browser's.
            if result and "screens" in result:
                incoming = result.get("screens")
                moved = (
                    [(float(a), float(b)) for a, b in incoming] if incoming else None
                )
                if moved != placed:
                    st.session_state[spine_key] = moved
                    st.rerun()
        elif static_build_available():
            # No server to serve a component from - the browser demo. The same
            # workspace goes into an iframe with the payload baked in, and the
            # screens are edited below instead of by dragging. Every figure is
            # still computed by the toolkit; only the gesture changes.
            _spine_iframe(render_static(spine_view), _spine_frame_height(spine_view))
            _spine_screen_editor(spine_view, spine_key, placed)
        else:
            st.warning(
                "The workspace needs either the component build or the static "
                "build. Both ship inside the package, so reinstall with "
                "`pip install --force-reinstall groundwater-toolkit`; in a "
                "source checkout run `npm install && npm run build:all` in "
                "ui/depth-spine/."
            )

        # An analyst-placed design is the project's design: the drawing, the
        # bill of quantities and the completion report all follow from the same
        # object, so a screen moved here is a screen moved everywhere.
        # shared.refresh_derived keeps it so on the runs this page is not on
        # screen.
        if placed:
            st.session_state.borehole_design = spine_design(spine_log, analysis, placed)
            col_note, col_reset = st.columns([4, 1])
            col_note.success(
                "Screens placed on the section. The Borehole design drawing, the "
                "Costing & BoQ page and the completion report now use this design."
            )
            if col_reset.button("Reset", key="spine_reset"):
                del st.session_state[spine_key]
                st.rerun()

        ledger = (result or {}).get("ledger") or {}
        if ledger:
            st.subheader("Decisions signed here")
            labels = {
                "design": "Design",
                "quality": "Water quality",
                "costing": "Costing & BoQ",
            }
            for stage_id, record in ledger.items():
                overridden = record["status"] == "overridden"
                with st.container(border=True):
                    head, meta = st.columns([3, 2])
                    head.markdown(
                        f"**{labels.get(stage_id, stage_id)}** — {record['value']}"
                        + (
                            "  ·  :orange[overridden]"
                            if overridden
                            else "  ·  :green[accepted]"
                        )
                    )
                    meta.caption(f"{record['signatory']} · {record['at']}")
                    if overridden:
                        st.caption(
                            f"Toolkit recommended **{record['recommended']}**. "
                            f"Reason given: {record['reason']}"
                        )
                    if not record["clean"]:
                        st.caption(":orange[Signed with a flag still open.]")
            st.session_state.spine_ledger = ledger

    _next_step("Price this design →", "Costing & BoQ",
               "Next: price the design on the section.",
               key="next_spine_costing")
