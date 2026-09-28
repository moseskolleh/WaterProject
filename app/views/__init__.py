"""The app's pages, one module each, and the address each is served at.

Each module has a ``render()`` that draws its page. ``streamlit_app.py``
registers them all with ``st.navigation`` and runs only the one on screen.
The titles are the ones the sidebar's grouped navigation lists
(``shared.NAV_GROUPS``); every title there has a module here.

The folder is not called ``pages``: Streamlit reads a ``pages/`` folder
beside the entry script as the old kind of multipage app, and runs the
first script run of a server process as one, listing every file in it as
a page of its own.
"""

from __future__ import annotations

import importlib


#: (title, url path, module name) for every page.
MODULES = (
    ("Overview", "overview", "overview"),
    ("Guided start", "guided-start", "guided_start"),
    ("Site maps", "site-maps", "site_maps"),
    ("Geophysics (VES)", "geophysics", "geophysics"),
    ("Borehole design", "borehole-design", "borehole_design"),
    ("Depth Spine", "depth-spine", "depth_spine"),
    ("Scanned sheets", "scanned-sheets", "scanned_sheets"),
    ("Pumping test", "pumping-test", "pumping_test"),
    ("Water quality", "water-quality", "water_quality"),
    ("Costing & BoQ", "costing", "costing"),
    ("Procurement", "procurement", "procurement"),
    ("Supervision", "supervision", "supervision"),
    ("Handover", "handover", "handover"),
    ("Templates", "templates", "templates"),
    ("Water points", "water-points", "water_points"),
    ("Coverage gap", "coverage-gap", "coverage_gap"),
    ("Portfolio", "portfolio", "portfolio"),
    ("Asset registry", "asset-registry", "asset_registry"),
)


def page_functions() -> list[tuple[str, str, object]]:
    """(title, url path, render function), looked up afresh on each call.

    Afresh, so that a module Streamlit reloaded after an edit, or a render
    a test has wrapped to see which page ran, is the one that runs.
    """
    return [(title, url, importlib.import_module(f"{__name__}.{name}").render)
            for title, url, name in MODULES]
