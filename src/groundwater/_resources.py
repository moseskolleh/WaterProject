"""Reading the data tables and map layers bundled in the wheel.

Every module that read a bundled file had grown its own few lines to do
it - coverage, mapping.regional three times over, mapping.lithology,
quality.standards, costing, supervision twice and readiness - each
spelling the package path and the encoding for itself. There is one way
here.

The map layers are the one thing held. :func:`bundled_json` parses a
bundled layer once per process, so coverage's chiefdom polygons and
mapping's chiefdom areas come off the same parse: mapping already kept
its own, and coverage re-read and re-parsed the 431 KB chiefdom layer on
every call. The parsed layer is shared, so a caller builds its own
objects from it and never changes it. The tables are small and the
modules that ask for them often already keep what they build from them.

A file the *caller* names is never held: it can change between calls,
and a stale answer there would be a wrong answer. Only the copy that
ships in the wheel is kept, because it cannot change while the process
runs.
"""

from __future__ import annotations

import functools
import json
from importlib import resources
from pathlib import Path

__all__ = ["bundled_text", "bundled_json"]


def bundled_text(name: str, path: str | Path | None = None) -> str:
    """Text of the bundled data file ``name``, or of ``path`` when given."""
    if path is not None:
        return Path(path).read_text(encoding="utf-8")
    return (resources.files("groundwater") / "data" / name).read_text(
        encoding="utf-8"
    )


@functools.lru_cache(maxsize=8)
def _bundled_json(name: str) -> dict:
    return json.loads(bundled_text(name))


def bundled_json(name: str, path: str | Path | None = None) -> dict:
    """Parsed JSON of the bundled file ``name``, or of ``path`` when given.

    The bundled copy is parsed once per process and shared; treat it as
    read-only. ``path`` is read afresh every time.
    """
    if path is not None:
        return json.loads(bundled_text(name, path))
    return _bundled_json(name)
