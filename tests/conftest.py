"""Shared fixtures: sample data paths and the transcribed Rokel readings."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from groundwater.models import SiteMetadata, VESSounding

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "examples" / "data"


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


# ---------------------------------------------------------------------------
# A pumping test the analysis can establish a yield from
# ---------------------------------------------------------------------------

def theis_series(T=120.0, S=1e-3, Q=5.0, r=0.1, t_min=None):
    """Drawdown in the pumped well of an ideal Theis aquifer."""
    from scipy.special import exp1

    if t_min is None:
        t_min = np.array([1, 2, 3, 5, 7, 10, 15, 20, 30, 45, 60, 90, 120, 180,
                          240, 300, 360], float)
    u = r * r * S / (4 * T * (t_min / 1440.0))
    return t_min, (Q * 24.0) / (4 * np.pi * T) * exp1(u)


def synthetic_constant_test(t_min=None, drawdown=None, swl=10.0, q=5.0,
                            pump=40.0, depth=60.0, recovery=None,
                            T=120.0):
    """A six-hour constant test in an ideal aquifer, with recovery if asked.

    ``recovery`` is ``(t_prime_min, residual_drawdown_m)``, or ``True`` for
    the theoretical Theis recovery of the same aquifer. Long enough, and
    productive enough, that the analysis establishes its yield: the point
    of the fixture is a project with nothing to hold a certificate back.
    """
    from groundwater.models import PumpingStep, PumpingTest

    if t_min is None or drawdown is None:
        t_min, drawdown = theis_series(T=T, Q=q)
    step = PumpingStep(step_number=1, discharge_m3_per_h=q, time_min=t_min,
                       water_level_m=swl + drawdown)
    test = PumpingTest(
        site=SiteMetadata(community="synthetic"), test_type="constant",
        static_water_level_m=swl, borehole_depth_m=depth, pump_setting_m=pump,
        steps=[step], pumping_duration_min=float(t_min[-1]),
    )
    if recovery is True:
        t_rec = np.array([1, 2, 3, 5, 7, 10, 15, 20, 30, 45, 60, 90, 120], float)
        slope = 2.303 * (q * 24.0) / (4 * np.pi * T)
        recovery = (t_rec, slope * np.log10((float(t_min[-1]) + t_rec) / t_rec))
    if recovery is not None:
        t_rec, residual = recovery
        test.recovery_time_min = np.asarray(t_rec, float)
        test.recovery_level_m = swl + np.asarray(residual, float)
        test.test_type = "constant+recovery"
    return test


@pytest.fixture()
def established_analysis():
    """An analysis whose yield is established, not indicative."""
    from groundwater.hydraulics import analyse_pumping_test

    return analyse_pumping_test(synthetic_constant_test(recovery=True))
