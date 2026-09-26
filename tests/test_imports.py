"""The subpackages defer their plotting, workbook and report modules.

A name re-exported from a subpackage is bound when it is first read, not
when the package is imported (see ``groundwater._lazy``). These pin both
halves of that: every public name is still there, and importing a
package for its analysis does not import the plotting stack with it.
"""

from __future__ import annotations

import importlib
import pkgutil
import subprocess
import sys

import pytest

import groundwater

SUBPACKAGES = sorted(
    info.name for info in pkgutil.iter_modules(groundwater.__path__) if info.ispkg
)


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_every_public_name_is_still_there(name):
    """Deferring a name must not lose it, from attribute access or dir()."""
    package = importlib.import_module(f"groundwater.{name}")
    listed = set(dir(package))
    for export in package.__all__:
        assert export in listed, f"groundwater.{name}.{export} is missing from dir()"
        assert getattr(package, export) is not None
    # a submodule stays reachable as an attribute, as the eager imports left it
    for info in pkgutil.iter_modules(package.__path__):
        assert getattr(package, info.name).__name__ == f"groundwater.{name}.{info.name}"
    with pytest.raises(AttributeError):
        package.no_such_name  # noqa: B018 - the lookup is the test


def test_analysis_imports_leave_the_plotting_stack_alone():
    """Importing a package for its analysis loads neither pyplot, openpyxl
    nor python-docx; reading a plotting name loads what that name needs.

    Run in a fresh interpreter, because this one has long since imported
    all three.
    """
    code = (
        "import sys\n"
        "import groundwater.hydraulics, groundwater.costing, groundwater.quality\n"
        "import groundwater.mapping, groundwater.reporting, groundwater.ingestion\n"
        "heavy = ('matplotlib.pyplot', 'openpyxl', 'docx')\n"
        "print(sorted(m for m in heavy if m in sys.modules))\n"
        "from groundwater.hydraulics import plot_theis\n"
        "from groundwater.hydraulics.plots import plot_theis as direct\n"
        "print(plot_theis is direct, 'matplotlib.pyplot' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    before, after = result.stdout.splitlines()
    assert before == "[]"
    assert after == "True True"
