"""Depth Spine — the redesigned borehole workspace, as a preview app.

One shared depth axis for the whole borehole: evidence on the left, derived
decisions on the right, and the screened interval directly manipulable so the
design, the acceptance checks and the bill of quantities move together.

Runs alongside the main toolkit rather than replacing it. Start it from the
repository root:

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

from groundwater.depth_spine import depth_spine, samples  # noqa: E402

st.set_page_config(
    page_title="Depth Spine — Geomentaqua Groundwater Toolkit",
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

st.title("Depth Spine")
st.caption(
    "Design · Water quality · Costing & BoQ, on one shared depth axis. Drag "
    "either green handle on the screened interval — or focus it and use the "
    "arrow keys — and watch the derived decisions, the live checks and the "
    "bill of quantities recompute."
)

bh = samples.borehole()
analysis = samples.analysis()

with st.sidebar:
    st.header("Field inputs")
    st.caption("Change what came off the rig and the whole workspace re-derives.")

    hyd = bh["hydraulics"]
    hyd["restLevel"] = st.number_input(
        "Static water level (m)", 0.0, 40.0, float(hyd["restLevel"]), 0.1
    )
    hyd["pumpingLevel"] = st.number_input(
        "Stabilised pumping level (m)", 0.0, 45.0, float(hyd["pumpingLevel"]), 0.1
    )
    hyd["testRate"] = st.number_input(
        "Constant-rate discharge Q (L/s)", 0.05, 10.0, float(hyd["testRate"]), 0.01
    )
    hyd["safetyFactor"] = st.slider(
        "Safety factor on the test rate", 0.4, 1.0, float(hyd["safetyFactor"]), 0.05
    )
    hyd["drawdownPerLogCycle"] = st.number_input(
        "Δs per log cycle (m)", 0.1, 10.0, float(hyd["drawdownPerLogCycle"]), 0.01
    )

    st.divider()
    st.subheader("Construction")
    con = bh["construction"]
    con["sanitarySealBase"] = st.number_input(
        "Sanitary seal base (m)", 0.0, 20.0, float(con["sanitarySealBase"]), 0.5
    )
    con["screen"]["slotWidth"] = st.select_slider(
        "Slot aperture (mm)",
        [0.5, 0.75, 1.0, 1.5, 2.0],
        float(con["screen"]["slotWidth"]),
    )
    strikes = st.text_input(
        "Water strikes (m, comma separated)",
        ", ".join(str(s) for s in bh["waterStrikes"]),
    )
    try:
        bh["waterStrikes"] = [float(s.strip()) for s in strikes.split(",") if s.strip()]
    except ValueError:
        st.warning("Could not read the strike depths — using the sample values.")

    st.divider()
    st.subheader("Water quality")
    st.caption("Push a determinand over its guideline and watch the verdict turn.")
    for det_id, label, lo, hi, step in [
        ("iron", "Iron (mg/L) · WHO 0.3", 0.0, 3.0, 0.05),
        ("ph", "pH · operational 6.5–8.5", 4.0, 9.5, 0.1),
        ("nitrate", "Nitrate as NO₃ (mg/L) · WHO 50", 0.0, 120.0, 1.0),
        ("arsenic", "Arsenic (mg/L) · WHO 0.01", 0.0, 0.05, 0.001),
    ]:
        current = next(d for d in analysis["determinands"] if d["id"] == det_id)["value"]
        samples.set_determinand(
            analysis, det_id, st.slider(label, lo, hi, float(current), step)
        )

ledger = depth_spine(bh, analysis, key="workspace")

st.divider()

STAGE_LABEL = {
    "design": "Design",
    "quality": "Water quality",
    "costing": "Costing & BoQ",
}

if ledger:
    st.subheader(f"Decision ledger — {len(ledger)} of 3 signed")
    for stage_id, record in ledger.items():
        overridden = record["status"] == "overridden"
        with st.container(border=True):
            head, meta = st.columns([3, 2])
            head.markdown(
                f"**{STAGE_LABEL.get(stage_id, stage_id)}** — {record['value']}"
                + ("  ·  :orange[overridden]" if overridden else "  ·  :green[accepted]")
            )
            meta.caption(f"{record['signatory']} · {record['at']}")
            if overridden:
                st.caption(
                    f"Toolkit recommended **{record['recommended']}**. "
                    f"Reason given: {record['reason']}"
                )
            if not record["clean"]:
                st.caption(":orange[Signed with a check still flagged.]")
    st.json(ledger, expanded=False)
else:
    st.info(
        "Nothing signed yet. Work through the stages in the workspace and press "
        "**Accept** — or **Override…** with a reason — to write a decision back "
        "to Python."
    )
