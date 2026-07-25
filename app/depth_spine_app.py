"""Depth Spine — the borehole workspace, on one shared depth axis.

Evidence on the left, derived decisions on the right, and the screened
intervals directly manipulable. Nothing is computed in the browser: the
component draws a payload built by ``groundwater.depth_spine.view`` from the
same functions that produce the reports, and hands back the screens the
analyst moved so the design, the flags and the bill of quantities are
re-derived here.

Runs alongside the main toolkit rather than replacing it. From the repository
root:

    streamlit run app/depth_spine_app.py

The frontend is a committed React build in ui/depth-spine/dist; rebuild it with
``npm install && npm run build`` in ui/depth-spine/ after changing the UI. Set
DEPTH_SPINE_DEV=1 to point at the Vite dev server instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Import the groundwater package from this checkout, not a previously
# installed copy — same reason as app/streamlit_app.py.
_SRC = Path(__file__).resolve().parent.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
    for _mod in [m for m in list(sys.modules) if m.split(".")[0] == "groundwater"]:
        del sys.modules[_mod]

from groundwater.config import Config  # noqa: E402
from groundwater.depth_spine import available, build_view, depth_spine, load  # noqa: E402

st.set_page_config(
    page_title="Depth Spine — Groundwater Investigation Toolkit",
    page_icon="💧",
    layout="wide",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 2.2rem; max-width: 1460px; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner=False)
def _load(key: str):
    """Parse and analyse a sample project once per session."""
    return load(key)


st.title("Depth Spine")
st.caption(
    "Design · Water quality · Costing & BoQ for one borehole, on one depth axis. "
    "Drag a screen handle — or focus it and use the arrow keys — and the toolkit "
    "re-runs design_borehole and everything downstream of it."
)

projects = available()
if not projects:
    st.error(
        "No sample project with a drilling log was found under examples/data. "
        "The workspace needs a logged borehole to draw a section for."
    )
    st.stop()

with st.sidebar:
    st.header("Project")
    chosen = st.selectbox(
        "Sample project",
        projects,
        format_func=lambda p: p.name,
        help="Parsed through the normal ingestion chain, flags and all.",
    )
    st.caption(chosen.note)

    st.divider()
    st.header("Design rules")
    st.caption(
        "The defaults in config.py, which a project's config.yaml overrides. "
        "Changing one re-runs the design."
    )
    rules = Config()
    rules.design.sump_length_m = st.number_input(
        "Sump length (m)", 0.0, 10.0, float(rules.design.sump_length_m), 0.5
    )
    rules.design.gravel_pack_above_top_screen_m = st.number_input(
        "Gravel pack above top screen (m)",
        0.0,
        20.0,
        float(rules.design.gravel_pack_above_top_screen_m),
        0.5,
    )
    rules.design.sanitary_seal_depth_m = st.number_input(
        "Sanitary seal depth (m)", 0.0, 30.0, float(rules.design.sanitary_seal_depth_m), 0.5
    )
    rules.design.screen_slot_mm = st.select_slider(
        "Screen slot (mm)", [0.5, 0.75, 1.0, 1.5, 2.0], float(rules.design.screen_slot_mm)
    )

# The screens the analyst has placed, if any. Kept per project so switching
# projects does not carry one borehole's screens onto another.
state_key = f"screens::{chosen.key}"
screens = st.session_state.get(state_key)

inputs = _load(chosen.key)
inputs.config = rules
view = build_view(inputs, screens_m=screens)

result = depth_spine(view, key=f"spine::{chosen.key}")

# The component reports the intervals it moved; re-deriving them is this
# script's job, not the browser's.
if result and "screens" in result:
    incoming = result["screens"]
    normalised = (
        [(float(a), float(b)) for a, b in incoming] if incoming else None
    )
    if normalised != screens:
        st.session_state[state_key] = normalised
        st.rerun()

st.divider()

ledger = (result or {}).get("ledger") or {}
STAGE_LABEL = {"design": "Design", "quality": "Water quality", "costing": "Costing & BoQ"}

left, right = st.columns([3, 2])

with left:
    if ledger:
        st.subheader(f"Decision ledger — {len(ledger)} signed")
        for stage_id, record in ledger.items():
            overridden = record["status"] == "overridden"
            with st.container(border=True):
                head, meta = st.columns([3, 2])
                head.markdown(
                    f"**{STAGE_LABEL.get(stage_id, stage_id)}** — {record['value']}"
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
    else:
        st.info(
            "Nothing signed yet. Work through the stages and press **Accept** — or "
            "**Override…** with a reason — to write a decision back to Python."
        )

with right:
    st.subheader("This design")
    design_screens = view["design"]["screens"]
    st.write(
        "Screens: "
        + ", ".join(f"{s['top']:g}–{s['base']:g} m" for s in design_screens)
    )
    if screens:
        st.caption(
            "Placed by the analyst on the section. The casing string, annulus, "
            "flags and bill of quantities were re-derived from them."
        )
        if st.button("Back to the generated design"):
            del st.session_state[state_key]
            st.rerun()
    else:
        st.caption("Generated by design_borehole from the drilling log.")
    st.metric("Price to client", f"US$ {view['costing']['price']:,.0f}")
    st.metric("Safe yield", view["design"]["yield"].get("rangeText", "pending"))
