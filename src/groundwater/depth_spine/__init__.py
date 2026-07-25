"""The Depth Spine workspace: one shared depth axis for the whole borehole.

The frontend is a React build in ``ui/depth-spine/dist`` that draws the view
payload built by :mod:`groundwater.depth_spine.view` and reports back what the
analyst changed. It computes nothing: every figure it shows comes from the same
functions the reports use, so the section, the rail and the bill of quantities
cannot drift from the .docx.

Streamlit Community Cloud cannot run npm, so the build is committed; rebuild it
with ``npm install && npm run build`` in ``ui/depth-spine/``. Set
``DEPTH_SPINE_DEV=1`` to point at the Vite dev server instead.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

from .projects import SAMPLES, SampleProject, available, load
from .view import SpineInputs, build_view

__all__ = [
    "depth_spine",
    "build_view",
    "SpineInputs",
    "SampleProject",
    "SAMPLES",
    "available",
    "load",
]

_DEV = os.environ.get("DEPTH_SPINE_DEV") == "1"
_BUILD_DIR = Path(__file__).resolve().parents[3] / "ui" / "depth-spine" / "dist"

if _DEV:
    _component = components.declare_component(
        "depth_spine", url="http://localhost:5173"
    )
else:
    if not _BUILD_DIR.exists():  # pragma: no cover - deployment guard
        raise RuntimeError(
            f"Frontend build not found at {_BUILD_DIR}. "
            "Run `npm install && npm run build` in ui/depth-spine/."
        )
    _component = components.declare_component("depth_spine", path=str(_BUILD_DIR))


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
    return _component(view=view, key=key, default=default)
