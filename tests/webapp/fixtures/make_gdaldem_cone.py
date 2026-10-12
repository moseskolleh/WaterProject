"""Write gdaldem_cone.json: gdaldem's own shading of the cone the surface tests light.

tests/test_terrain_surface.py holds the multidirectional hillshade of the
terrain analysis to gdaldem -multidirectional, which is what the figures say
it is, and the topographic map's single sun to gdaldem's hillshade at 315
degrees. GDAL's Python bindings (osgeo) are in neither the dev extra nor CI,
so the test compares against this file, written once by gdaldem itself; the
live comparison runs only where osgeo is installed, and there, under the GDAL
that wrote the file, it also requires gdaldem to write the same bytes again.

Run it in an environment that has osgeo:

    PYTHONPATH=src python tests/webapp/fixtures/make_gdaldem_cone.py

The committed file was made with GDAL 3.13.3, the conda-forge build with its
Python 3.13 bindings, in a micromamba environment holding python=3.13, gdal,
numpy and pyyaml. The cone, its metric and the way each row is handed to
gdaldem are the test module's own (_gdaldem_cone and _gdaldem_record), so the
file and the test cannot drift apart; the test also checks that the heights
and cell sizes the file was made from are the cone's.
"""

from __future__ import annotations

import importlib.util
import json
import platform
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "gdaldem_cone.json"
TESTS = HERE.parents[1] / "test_terrain_surface.py"

#: The file's header; {gdal} and {python} are the versions that wrote it.
ABOUT = (
    "gdaldem hillshade's bytes for the 13 by 15 cone of tests/test_terrain_surface.py (_gdaldem_cone), "
    "made with GDAL {gdal} through its Python bindings under Python {python} by "
    "tests/webapp/fixtures/make_gdaldem_cone.py, run once and committed as it came out. Each inner row was "
    "handed to gdaldem as a three-row band in metres, with that row's cell size (dx, dy) and an explicit "
    "scale of 1, at the altitude given and a z-factor of 1. multidirectional is -multidirectional and "
    "azimuth_315 the single sun at 315 degrees: for each inner row, south first, the bytes of its inner "
    "cells, west first. z holds the heights, south row first, as float32 values."
)


def _text(record: dict) -> str:
    """The record as JSON with one row of the grid on a line, so that a
    change shows as a change to the rows it touches."""
    lines = ["{"]
    keys = list(record)
    for n, key in enumerate(keys):
        value = record[key]
        end = "," if n < len(keys) - 1 else ""
        if isinstance(value, list) and value and isinstance(value[0], list):
            rows = ",\n".join("  " + json.dumps(row) for row in value)
            lines.append(f" {json.dumps(key)}: [\n{rows}\n ]{end}")
        else:
            lines.append(f" {json.dumps(key)}: {json.dumps(value)}{end}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    from osgeo import gdal

    gdal.UseExceptions()
    spec = importlib.util.spec_from_file_location("terrain_surface_tests", TESTS)
    assert spec is not None and spec.loader is not None
    tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tests)
    record = tests._gdaldem_record(gdal)
    rows = record.pop("z")
    about = ABOUT.format(gdal=record["gdal"], python=platform.python_version())
    record = {"about": about, **record, "z": rows}
    FIXTURE.write_text(_text(record), encoding="utf-8")
    print(f"wrote {FIXTURE.name} with GDAL {record['gdal']}")


if __name__ == "__main__":
    main()
