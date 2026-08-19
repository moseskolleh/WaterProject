"""Deferred re-exports for the subpackages (PEP 562).

Each subpackage re-exports its plotting and workbook-writing modules from
its ``__init__``, so importing ``groundwater.hydraulics`` for
``analyse_pumping_test`` also imported ``matplotlib.pyplot``, and
``groundwater.costing`` for a cost estimate also imported ``openpyxl``.
Those two cost about 480 ms and 240 ms; the whole package took a second
to import before it had done anything.

:func:`lazy_exports` keeps the names exactly where they were - ``from
groundwater.hydraulics import plot_recovery`` still works, and so does
``dir()`` - but the module behind a name is not imported until the name
is actually read. Once read, the value is written onto the package, so
the second lookup is an ordinary attribute access with no indirection.

This matters most where a cold start is visible: the browser build,
which compiles every import in WebAssembly, and the web app, which pays
it before the first page renders.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any, Callable, Iterable, Mapping

__all__ = ["lazy_exports"]


def lazy_exports(
    package: str,
    exports: Mapping[str, str],
    submodules: Iterable[str] = (),
) -> tuple[Callable[[str], Any], Callable[[], list[str]]]:
    """Build the ``__getattr__`` and ``__dir__`` a lazy package needs.

    ``exports`` maps each public name to the relative module that defines
    it (``{"plot_recovery": ".plots"}``). ``submodules`` names submodules
    that are themselves part of the public surface, so ``mapping.geolibre``
    keeps working without importing it up front.

    Use it as::

        __getattr__, __dir__ = lazy_exports(__name__, _LAZY, _LAZY_MODULES)
    """
    index = dict(exports)
    modules = set(submodules)

    def __getattr__(name: str) -> Any:
        if name in modules:
            value: Any = importlib.import_module(f".{name}", package)
        elif name in index:
            value = getattr(importlib.import_module(index[name], package), name)
        else:
            raise AttributeError(
                f"module {package!r} has no attribute {name!r}"
            )
        # cache on the package, so this runs once per name per process
        setattr(sys.modules[package], name, value)
        return value

    def __dir__() -> list[str]:
        return sorted(
            set(vars(sys.modules[package])) | set(index) | modules
        )

    return __getattr__, __dir__
