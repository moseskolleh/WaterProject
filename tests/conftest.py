"""Shared fixtures: sample data paths and the transcribed Rokel readings."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from groundwater.models import SiteMetadata, VESSounding

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "examples" / "data"


@pytest.fixture(autouse=True)
def _autosave_tmp(tmp_path, monkeypatch):
    """Keep app autosaves out of the real home directory during tests."""
    monkeypatch.setenv("GW_AUTOSAVE_DIR", str(tmp_path / "autosaves"))


@pytest.fixture(scope="session", autouse=True)
def sample_data():
    """Build the example datasets once for the whole test session."""
    import subprocess
    import sys

    if not (DATA / "rokel" / "rokel_ves.xlsx").exists():
        subprocess.run(
            [sys.executable, str(REPO / "examples" / "build_sample_data.py")],
            check=True,
        )
    return DATA


@pytest.fixture()
def rokel_ves_a() -> VESSounding:
    ab2 = [1, 2, 3, 3, 4, 5, 7, 10, 10, 15, 20, 30, 40, 40, 50, 70, 70, 80]
    mn = [0.4, 0.4, 0.4, 0.8, 0.8, 0.8, 0.8, 0.8, 1.5, 1.5, 1.5, 1.5, 1.5, 7.6, 7.6, 7.6, 14, 14]
    rho = [1165, 1193, 1303, 1317, 1502, 1500, 1432, 1392, 961.0, 715.5,
           732.0, 162.0, 156.1, 78.7, 52.1, 55.8, 53.2, 47.9]
    return VESSounding(
        site=SiteMetadata(community="Rokel", district="Western Area",
                          easting=708958, northing=926355, utm_zone=28),
        sounding_id="A (1)",
        ab2=np.array(ab2, float),
        mn=np.array(mn, float),
        rho_app=np.array(rho, float),
    )
