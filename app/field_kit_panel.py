"""The Field kit button, on the Templates and Pumping test pages.

PLAN.md step 2.5: printed sheets and quick cards for a crew with no device.
The browser app builds the same kit, from the same content
(groundwater.field_kit, which its gwt-core.js port is held to by parity), on
its own Templates and Pumping test pages.
"""

from __future__ import annotations

import streamlit as st

from groundwater.reporting.field_kit import build_field_kit
from groundwater.text import phrase

from shared import app_config, offer_download, site_from_state, workdir


def known_boreholes() -> list[str]:
    """The borehole identifiers the project's sheets name, drilling log first."""
    analysis = st.session_state.get("pump_analysis")
    records = (st.session_state.get("drilling_log"),
               analysis.test if analysis is not None else None)
    refs: list[str] = []
    for record in records:
        ref = getattr(record, "borehole_ref", "") if record is not None else ""
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def field_kit_panel(key: str, known: list[str] | None = None) -> None:
    """The kit's description, the boreholes to print for, and the button."""
    st.subheader("Field kit")
    st.caption(phrase("field_kit.about"))
    names = st.text_area(
        "Boreholes (one identifier a line, as the sheet should print it)",
        value="\n".join(known if known is not None else known_boreholes()),
        key=f"{key}_fieldkit_boreholes",
    )
    if st.button("Field kit (.docx)", key=f"{key}_fieldkit_build"):
        folder = workdir() / "field_kit"
        try:
            path = build_field_kit(site_from_state(), names.splitlines(),
                                   folder / "field_kit.docx", folder, app_config())
        except ValueError as exc:
            st.error(f"Could not build the field kit: {exc}")
        else:
            offer_download(path, "Download the field kit (.docx)")
