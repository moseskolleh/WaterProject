"""Reading the data tables and map layers bundled in the wheel.

Two things live here. The first is one way of getting at a bundled file,
because ``coverage`` and ``mapping.regional`` had grown a near-identical
private reader each.

The second is :func:`cache_bundled`. The catalogues - WHO guideline
values, unit rates, supervision checklists, district and chiefdom
boundaries - are fixed tables shipped inside the wheel, but every call to
a loader re-read and re-parsed one. A single report run parsed the water
quality standards twenty-five times, and the chiefdom boundary layer is
155 KB of GeoJSON that becomes several hundred numpy arrays.

A file the *caller* names is never cached: it can change between calls,
and a stale answer there would be a wrong answer. Only the copy that
ships in the wheel is held, and only because it cannot change while the
process runs.
"""

from __future__ import annotations

import functools
import json
from importlib import resources
from pathlib import Path
from typing import Callable, TypeVar

__all__ = ["bundled_text", "bundled_json", "cache_bundled"]


def bundled_text(name: str, path: str | Path | None = None) -> str:
    """Text of the bundled data file ``name``, or of ``path`` when given."""
    if path is not None:
        return Path(path).read_text(encoding="utf-8")
    return (resources.files("groundwater") / "data" / name).read_text(
        encoding="utf-8"
    )


def bundled_json(name: str, path: str | Path | None = None) -> dict:
    """Parsed JSON of the bundled data file ``name``, or of ``path``."""
    return json.loads(bundled_text(name, path))


T = TypeVar("T")


def cache_bundled(loader: Callable[..., T]) -> Callable[..., T]:
    """Parse the bundled table once per process; re-read any override.

    Wraps a loader whose arguments are all optional paths. When every
    argument is absent or ``None`` the loader is reading what ships in the
    wheel, and the parse is kept. Pass a path and it is read afresh.

    What a cached call returns is shared with every other cached call, so
    treat it as read-only. Use ``cache_clear()`` on the wrapped loader to
    drop the held parse.
    """
    missing = object()
    held: object = missing

    @functools.wraps(loader)
    def wrapper(*args, **kwargs):
        nonlocal held
        overridden = any(a is not None for a in args) or any(
            v is not None for v in kwargs.values()
        )
        if overridden:
            return loader(*args, **kwargs)
        if held is missing:
            held = loader()
        return held

    def cache_clear() -> None:
        nonlocal held
        held = missing

    wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]
    return wrapper
