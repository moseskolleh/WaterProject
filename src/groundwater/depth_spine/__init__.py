"""The Depth Spine workspace: one shared depth axis for the whole borehole.

Two ways to render it, because two deployments can support different things:

``depth_spine``
    The Streamlit custom component. Interactive - the analyst drags the screens
    and the intervals come back for :func:`view.build_view` to re-derive. Needs
    a server that can serve the built frontend from disk, so it needs the real
    Streamlit runtime.

``render_static``
    A self-contained page for :func:`streamlit.components.v1.html`. Draws the
    identical workspace with the payload baked in, and reports nothing back.
    This is what the in-browser (WebAssembly) demo gets, where there is no
    server to serve a component from.

Both draw the same payload, so the demo shows the same figures as the app; only
the screen handles are inert. Importing this module never requires either build
to be present - the guards fire when you actually try to render.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .inline import STATIC_BUILD, render_static, static_build_available
from .projects import SAMPLES, SampleProject, available, load
from .view import SpineInputs, build_view

__all__ = [
    "depth_spine",
    "render_static",
    "static_build_available",
    "component_available",
    "build_view",
    "SpineInputs",
    "SampleProject",
    "SAMPLES",
    "available",
    "load",
    "BUILD_DIR",
    "STATIC_BUILD",
]

BUILD_DIR = Path(__file__).resolve().parents[3] / "ui" / "depth-spine" / "dist"

_component = None


def component_available() -> bool:
    """True when the interactive component can be declared and rendered."""
    if os.environ.get("DEPTH_SPINE_DEV") == "1":
        return True
    if not BUILD_DIR.is_dir():
        return False
    try:
        import streamlit.components.v1  # noqa: F401
    except Exception:
        return False
    return True


def _declare():
    """Declare the component on first use.

    Declaring at import time would make the module unimportable wherever the
    frontend build is absent - which is exactly where the static fallback is
    needed - so this is deliberately lazy.
    """
    global _component
    if _component is not None:
        return _component
    import streamlit.components.v1 as components

    if os.environ.get("DEPTH_SPINE_DEV") == "1":
        _component = components.declare_component(
            "depth_spine", url="http://localhost:5173"
        )
    else:
        if not BUILD_DIR.is_dir():
            raise RuntimeError(
                f"Frontend build not found at {BUILD_DIR}. "
                "Run `npm install && npm run build` in ui/depth-spine/."
            )
        _component = components.declare_component("depth_spine", path=str(BUILD_DIR))
    return _component


def depth_spine(
    view: dict[str, Any],
    *,
    key: str | None = None,
    default: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Render the workspace and return what the analyst did in it.

    Returns ``None`` until something happens, then a dict with ``screens``
    (the intervals moved on the section, as ``[[top, base], ...]``, to feed
    back into :func:`build_view`) and ``ledger`` (one record per signed-off
    stage: the certified value, the recommendation, the reason where it was
    overridden, the signatory and the timestamp).
    """
    return _declare()(view=view, key=key, default=default)
