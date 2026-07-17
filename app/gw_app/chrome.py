"""Page configuration, styling and the header block."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

import groundwater

from .common import IN_BROWSER

_BRAND_DIR = Path(groundwater.__file__).resolve().parent / "data" / "brand"


def _brand(name: str) -> str | None:
    path = _BRAND_DIR / name
    return str(path) if path.exists() else None


def setup_page() -> None:
    """st.set_page_config and the global CSS; must run first."""
    icon = _brand("icon.png")
    logo = _brand("logo.png")
    st.set_page_config(
        page_title="Groundwater Toolkit",
        page_icon=icon or ":droplet:",
        layout="wide",
        menu_items={
            "About": (
                "Groundwater Investigation Toolkit - analysis and reporting "
                "for rural water supply borehole projects in Sierra Leone. "
                "Methods follow RWSN/UNICEF professional drilling guidance "
                "and WHO drinking water quality guidelines."
            ),
        },
    )

    st.markdown(
        """
        <style>
          .block-container { padding-top: 2.4rem; }
          div[data-testid="stMetric"] {
            background: var(--secondary-background-color, #F2F6FA);
            border: 1px solid rgba(31, 92, 139, 0.18);
            border-radius: 0.6rem;
            padding: 0.65rem 0.9rem;
          }
          div[data-testid="stMetric"] label { color: #1F5C8B; }
          button[data-baseweb="tab"] { font-size: 0.95rem; }
          div[data-testid="stSidebarUserContent"] .stCaption p { line-height: 1.35; }
          /* phones on site: tighter margins and finger-sized targets
             for the supervision checklist radios */
          @media (max-width: 640px) {
            .block-container {
              padding-left: 0.8rem;
              padding-right: 0.8rem;
            }
            div[role="radiogroup"] label {
              padding: 0.35rem 0.6rem;
              border: 1px solid rgba(31, 92, 139, 0.25);
              border-radius: 0.5rem;
              margin-right: 0.25rem;
            }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if logo:
        try:
            st.logo(logo, icon_image=icon)
        except Exception:
            pass


def render_header() -> None:
    st.title("Groundwater Investigation Toolkit")
    st.caption(
        "Vertical electrical soundings, pumping tests, water quality, "
        "borehole design, costing and drilling supervision for rural water "
        "supply projects in Sierra Leone."
    )
    if IN_BROWSER:
        st.info(
            "This demo runs entirely in your browser; nothing is uploaded to any "
            "server. Heavy steps such as the VES inversion take noticeably longer "
            "here than in the full installation. Every tab has bundled sample "
            "data so you can try it without your own files."
        )
