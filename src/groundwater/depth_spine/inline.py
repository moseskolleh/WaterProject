"""Render the workspace as one self-contained page.

The in-browser demo runs Streamlit under WebAssembly, where there is no server
to serve a custom component's frontend from disk. ``st.components.v1.html`` is
core Streamlit, though - it puts a string in an iframe - so the same workspace
can be shown there by baking the payload into a single-file build.

What the demo loses is only the return trip: the screen handles cannot hand
intervals back for Python to re-derive. The page says so, and offers the same
edit through ordinary Streamlit inputs instead, so the demo reaches the same
designs by a different gesture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: The single-file build, carried inside the package.
#:
#: It lives here rather than beside the component build in ui/ because the
#: in-browser demo mounts the package into a filesystem where ui/ does not
#: exist. ``npm run build:inline`` writes it.
STATIC_BUILD = Path(__file__).resolve().parent / "static" / "workspace.html"

_PLACEHOLDER = "__SPINE_VIEW__"


def static_build_available() -> bool:
    return STATIC_BUILD.is_file()


def render_static(
    view: dict[str, Any],
    *,
    template: str | None = None,
    interactive: bool = False,
) -> str:
    """Return a complete HTML document with ``view`` baked in.

    ``template`` is the single-file build's markup; it is read from
    :data:`STATIC_BUILD` when not supplied, which keeps this function testable
    without the frontend having been built.
    """
    if template is None:
        if not static_build_available():
            raise RuntimeError(
                f"Static build not found at {STATIC_BUILD}. Run "
                "`npm install && npm run build:inline` in ui/depth-spine/."
            )
        template = STATIC_BUILD.read_text(encoding="utf-8")

    payload = json.dumps(
        {"view": view, "interactive": interactive},
        allow_nan=False,
    )
    # The payload is injected into a <script> block, so a literal "</script>"
    # inside any string - a laboratory name, a flag message - would end the
    # block early and break the page. JSON keeps the escape, the browser does
    # not see a closing tag.
    payload = payload.replace("</", "<\\/")

    if _PLACEHOLDER not in template:
        raise RuntimeError(
            f"{STATIC_BUILD} does not contain the {_PLACEHOLDER} placeholder; "
            "rebuild it with `npm run build:inline`."
        )
    return template.replace(_PLACEHOLDER, payload)
