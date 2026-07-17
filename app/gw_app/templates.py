"""Templates tab: blank field data templates for the field team."""

from __future__ import annotations

import streamlit as st

from groundwater.ingestion.templates import write_all_templates

from .common import offer_download, workdir


def render() -> None:
    st.header("Blank field data templates")
    st.write("Download the standard templates for the field team.")
    template_dir = workdir() / "templates"
    if st.button("Generate templates", key="gen_templates"):
        for template in write_all_templates(template_dir):
            offer_download(template, f"Download {template.name}")
