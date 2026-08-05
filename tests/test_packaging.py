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

import shutil
import subprocess
import sys
import tomllib
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


def test_the_wheel_carries_the_bundled_data_tables(wheel):
    names = set(wheel.namelist())
    for expected in (
        "groundwater/data/who_guidelines.csv",
        "groundwater/data/borehole_cost_items.csv",
        "groundwater/data/sl_districts.csv",
        "groundwater/data/sl_chiefdoms_geoboundaries.geojson",
    ):
        assert expected in names


def test_the_deployment_requirements_cover_the_declared_extras():
    """requirements.txt is what the hosted app installs.

    An extra the app imports but the deployment file omits is a feature that
    works locally and is missing in production - which is how the AI
    extraction path shipped without the anthropic client.
    """
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]
    requirements = (REPO / "requirements.txt").read_text(encoding="utf-8").lower()
    for extra in ("app", "extract", "ai"):
        for spec in extras[extra]:
            package = spec.split(">=")[0].split("<")[0].split("[")[0].strip().lower()
            assert package in requirements, (
                f"'{package}' is in the '{extra}' extra but not in "
                "requirements.txt, so the deployed app will not have it"
            )


def test_frontend_dir_resolves_through_the_package():
    """Not through a path relative to the repository root.

    ``parents[3]`` from the installed module climbs out of site-packages, so
    the old resolution could only ever succeed in a source checkout.
    """
    from groundwater.depth_spine import frontend_dir

    found = frontend_dir()
    assert found is not None, "the committed component build should be found"
    assert (found / "index.html").is_file()
