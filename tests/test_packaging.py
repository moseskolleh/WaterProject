"""What a built wheel actually carries.

The toolkit is deployed by installing it, not by copying the checkout, so
anything the running app reads has to be inside the distribution. It was not:
the Depth Spine's frontend build lived in ``ui/`` (outside the package
entirely) and its static fallback was never declared as package data, so
every pip-installed copy reported the workspace unavailable and advised the
user to run npm - which a wheel install has no way to do.

These tests build a real wheel and look inside it. They need no npm: the
built assets are committed inside the package, and if they are missing the
test says so rather than passing quietly.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def wheel(tmp_path_factory) -> zipfile.ZipFile:
    out = tmp_path_factory.mktemp("wheel")
    # setuptools stages into ./build and only refreshes files it thinks are
    # newer, so a stale staging tree can put a file in the wheel that no
    # longer exists in the source. Start clean, or this test can pass on
    # yesterday's package data.
    shutil.rmtree(REPO / "build", ignore_errors=True)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "-w", str(out), str(REPO)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:  # pragma: no cover - build environment issue
        pytest.skip(f"could not build a wheel here:\n{result.stdout}\n{result.stderr}")
    wheels = list(out.glob("*.whl"))
    assert wheels, "pip wheel produced no wheel"
    return zipfile.ZipFile(wheels[0])


def test_the_wheel_carries_the_depth_spine_frontend(wheel):
    """The interactive component build, content-hashed asset names and all."""
    names = wheel.namelist()
    assert "groundwater/depth_spine/frontend/index.html" in names
    assets = [n for n in names
              if n.startswith("groundwater/depth_spine/frontend/assets/")]
    assert any(n.endswith(".js") for n in assets), assets
    assert any(n.endswith(".css") for n in assets), assets
    # a placeholder file would satisfy the name check but not the page
    for name in assets:
        assert wheel.getinfo(name).file_size > 1000, name


def test_the_wheel_carries_the_static_workspace(wheel):
    """The single-file fallback the in-browser build renders."""
    info = wheel.getinfo("groundwater/depth_spine/static/workspace.html")
    assert info.file_size > 10_000
    body = wheel.read("groundwater/depth_spine/static/workspace.html").decode("utf-8")
    assert "__SPINE_VIEW__" in body, "the payload placeholder must survive the build"


def test_every_bundled_font_is_the_file_its_manifest_names():
    """The fonts' provenance is a file beside them, not a sentence: a face
    swapped for a different cut, or added without a record, fails here."""
    import hashlib
    import json

    fonts = REPO / "src" / "groundwater" / "data" / "brand" / "fonts"
    manifest = json.loads((fonts / "manifest.json").read_text(encoding="utf-8"))
    recorded = {f["file"]: f for f in manifest["fonts"]}
    assert set(recorded) == {p.name for p in fonts.glob("*.woff2")}
    for name, entry in recorded.items():
        body = (fonts / name).read_bytes()
        assert hashlib.sha256(body).hexdigest() == entry["sha256"], name
        assert len(body) == entry["bytes"], name
        assert entry["license"] == "OFL-1.1", name
    # the licence names every family it covers
    notice = (fonts / "LICENSE-OFL.txt").read_text(encoding="utf-8")
    for family in {f["family"] for f in manifest["fonts"]}:
        assert f"\n{family}\n  Copyright" in notice, family
    # the browser app's copies are the same files
    for copy in (REPO / "docs" / "fonts").glob("*.woff2"):
        assert copy.read_bytes() == (fonts / copy.name).read_bytes(), copy.name


def test_the_wheel_carries_the_fonts_and_their_record(wheel):
    names = set(wheel.namelist())
    for expected in (
        "groundwater/data/brand/fonts/LICENSE-OFL.txt",
        "groundwater/data/brand/fonts/manifest.json",
        "groundwater/data/brand/fonts/ibm-plex-sans-latin-400.woff2",
        "groundwater/data/brand/fonts/ibm-plex-mono-latin-600.woff2",
    ):
        assert expected in names


def test_the_wheel_carries_the_bundled_data_tables(wheel):
    names = set(wheel.namelist())
    for expected in (
        "groundwater/data/who_guidelines.csv",
        "groundwater/data/borehole_cost_items.csv",
        "groundwater/data/sl_districts.csv",
        "groundwater/data/sl_chiefdoms_geoboundaries.geojson",
        # every Config() is built from it
        "groundwater/data/defaults.json",
    ):
        assert expected in names
    # the words the reports print, which the package reads at import
    text = sorted((REPO / "src" / "groundwater" / "data" / "text").glob("*.yaml"))
    assert text
    for path in text:
        assert f"groundwater/data/text/{path.name}" in names


def _optional_dependencies() -> dict[str, list[str]]:
    """The [project.optional-dependencies] table.

    Read without tomllib, which arrived in 3.11 while this package supports
    3.10 - and the CI matrix runs the floor, so importing it here would take
    the whole file down on the oldest version the project claims to support.
    """
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    section = re.search(
        r"^\[project\.optional-dependencies\]\s*$(.*?)(?=^\[)",
        text, re.MULTILINE | re.DOTALL,
    )
    assert section, "pyproject.toml has no [project.optional-dependencies]"
    extras: dict[str, list[str]] = {}
    for name, body in re.findall(r"^(\w+)\s*=\s*\[(.*?)\]", section.group(1),
                                 re.MULTILINE | re.DOTALL):
        extras[name] = re.findall(r'"([^"]+)"', body)
    return extras


def test_the_deployment_requirements_cover_the_declared_extras():
    """requirements.txt is what the hosted app installs.

    An extra the app imports but the deployment file omits is a feature that
    works locally and is missing in production - which is how the AI
    extraction path shipped without the anthropic client.
    """
    extras = _optional_dependencies()
    requirements = (REPO / "requirements.txt").read_text(encoding="utf-8").lower()
    for extra in ("app", "extract", "ai"):
        assert extras.get(extra), f"the '{extra}' extra was not found"
        for spec in extras[extra]:
            package = spec.split(">=")[0].split("<")[0].split("[")[0].strip().lower()
            assert package in requirements, (
                f"'{package}' is in the '{extra}' extra but not in "
                "requirements.txt, so the deployed app will not have it"
            )


def test_the_qr_oracles_are_declared_so_ci_installs_them():
    """The QR encoder is only as trustworthy as the things checking it.

    Both oracles are imported through ``importorskip``, so a run without
    them passes with the comparison quietly skipped. Naming them in the
    extra CI installs is what stops that from becoming the normal state.
    """
    dev = _optional_dependencies().get("dev") or []
    packages = {spec.split(">=")[0].split("<")[0].strip().lower() for spec in dev}
    assert "segno" in packages, "the independent encoder is not in the dev extra"
    assert packages & {"opencv-python-headless", "opencv-python"}, (
        "the decoder is not in the dev extra")


def test_the_raster_oracle_is_declared_so_ci_installs_it():
    """The GeoTIFF checks read the file back through GDAL and skip without
    it, so a wrongly georeferenced raster would ship looking fine."""
    dev = _optional_dependencies().get("dev") or []
    packages = {spec.split(">=")[0].split("<")[0].strip().lower() for spec in dev}
    assert "rasterio" in packages, "the GeoTIFF reader is not in the dev extra"


def test_the_geotiff_writer_needs_nothing_at_run_time():
    """The oracle must never become a dependency of the shipped code."""
    source = (REPO / "src" / "groundwater" / "geotiff.py").read_text(encoding="utf-8")
    for forbidden in ("rasterio", "osgeo", "gdal"):
        assert f"import {forbidden}" not in source, forbidden
        assert f"from {forbidden}" not in source, forbidden


def test_the_qr_encoder_needs_nothing_at_run_time():
    """The oracles must never become dependencies of the shipped code."""
    source = (REPO / "src" / "groundwater" / "qr.py").read_text(encoding="utf-8")
    for forbidden in ("segno", "cv2", "numpy", "PIL", "matplotlib"):
        assert f"import {forbidden}" not in source, forbidden


def test_frontend_dir_resolves_through_the_package():
    """Not through a path relative to the repository root.

    ``parents[3]`` from the installed module climbs out of site-packages, so
    the old resolution could only ever succeed in a source checkout.
    """
    from groundwater.depth_spine import frontend_dir

    found = frontend_dir()
    assert found is not None, "the committed component build should be found"
    assert (found / "index.html").is_file()


def test_the_ai_extra_floor_supports_structured_outputs():
    """The extractor sends output_config and adaptive thinking, which the
    anthropic SDK accepts from 0.78; an older client satisfied the previous
    floor and failed with a TypeError the moment Extract was pressed."""
    import re

    # read as text rather than with tomllib, which is 3.11+ and the matrix
    # starts at 3.10
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    spec = re.search(r'^ai = \["(anthropic[^"]*)"\]', text, re.M).group(1)
    floor = re.search(r">=\s*(\d+)\.(\d+)", spec)
    assert floor, spec
    assert (int(floor.group(1)), int(floor.group(2))) >= (0, 78)
    requirements = (REPO / "requirements.txt").read_text()
    assert spec in requirements
