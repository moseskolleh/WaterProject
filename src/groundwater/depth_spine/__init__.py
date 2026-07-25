"""Streamlit custom component wrapping the Depth Spine borehole workspace.

The frontend is the React build in ``ui/depth-spine/dist``. Streamlit Community Cloud
cannot run npm, so that build is committed; rebuild it with ``npm run build``
in ``ui/depth-spine/`` whenever the frontend changes.

Set ``DEPTH_SPINE_DEV=1`` to point the component at the Vite dev server
on http://localhost:5173 instead, for hot reloading while developing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import streamlit.components.v1 as components

_DEV = os.environ.get("DEPTH_SPINE_DEV") == "1"
_BUILD_DIR = (
    Path(__file__).resolve().parents[3] / "ui" / "depth-spine" / "dist"
)

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
    _component = components.declare_component(
        "depth_spine", path=str(_BUILD_DIR)
    )


def depth_spine(
    borehole: dict[str, Any] | None = None,
    sample: dict[str, Any] | None = None,
    *,
    key: str | None = None,
    default: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Render the borehole workspace — design, water quality, costing.

    Parameters
    ----------
    borehole:
        The borehole model. Omit to use the frontend's Dr Timbo BH-01 sample.
    sample:
        The water quality analysis. Omit to use the bundled sample.
    key:
        Streamlit widget key.
    default:
        Value returned before anything has been signed off.

    Returns
    -------
    The decision ledger: one record per stage that has been signed, each with
    the certified value, the toolkit's recommendation, the reason where the
    figure was overridden, the signatory and the timestamp.
    """
    return _component(borehole=borehole, sample=sample, key=key, default=default)
