"""Groundwater toolkit web interface.

Lets the field team upload data files in the standard templates and
produces the analysis figures and client-ready reports without
touching code. Covers the full project lifecycle: VES siting surveys,
pumping tests, water quality, borehole design, cost estimation and
drilling supervision checklists.

The tab implementations live in the ``gw_app`` package next to this
script; this entrypoint wires up the page chrome, the sidebar and the
tab bar (ordered to follow the suggested workflow).

Run from the repository root:

    streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Always import the groundwater package from the repository checkout
# this app ships with, not from a previously installed copy. Streamlit
# Community Cloud pulls new source on every push but only reinstalls
# packages when requirements.txt changes, so without this the app file
# can be newer than the installed package and imports break.
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
    for _mod in [m for m in list(sys.modules) if m.split(".")[0] == "groundwater"]:
        del sys.modules[_mod]

# the app package (gw_app) lives next to this script
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import streamlit as st

from gw_app import (
    chrome,
    common,
    cost,
    design,
    extract,
    guide,
    handover,
    maps,
    pump,
    quality,
    registry,
    sidebar,
    supervision,
    templates,
    ves,
)

chrome.setup_page()

sidebar.render()

chrome.render_header()

(
    tab_guide,
    tab_ves,
    tab_cost,
    tab_supervision,
    tab_design,
    tab_pump,
    tab_quality,
    tab_handover,
    tab_maps,
    tab_registry,
    tab_extract,
    tab_templates,
) = st.tabs(
    [
        "🚀 Guided start",
        "📈 VES survey",
        "💰 Costing",
        "✅ Supervision",
        "🛠️ Borehole design",
        "⏱️ Pumping test",
        "🧪 Water quality",
        "🤝 Handover",
        "🗺️ Maps",
        "📇 Registry",
        "📄 Scanned sheets",
        "📋 Templates",
    ]
)

# tab blocks execute in source order each rerun (display order is set
# by the labels above): VES before costing so a fresh inversion is
# visible to the costing prefills within the same run
with tab_guide:
    guide.render()
with tab_ves:
    ves.render()
with tab_pump:
    pump.render()
with tab_quality:
    quality.render()
with tab_design:
    design.render()
with tab_cost:
    cost.render()
with tab_supervision:
    supervision.render()
with tab_handover:
    handover.render()
with tab_maps:
    maps.render()
with tab_registry:
    registry.render()
with tab_extract:
    extract.render()
with tab_templates:
    templates.render()

# the post-load grace flag protects restored inputs for exactly one
# full run; every tab has rendered by this point
st.session_state.pop("project_just_loaded", None)

# autosave the project after the full run, so a refresh costs nothing
common.autosave_project()
