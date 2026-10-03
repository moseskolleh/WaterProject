"""The browser's pumping test co-pilot writes a sheet the Python reader reads.

PLAN.md step 2.1, rule 6: a field tool writes the template the parsers
already read, not a new ingestion path. The two workbooks under
``tests/webapp/fixtures/`` are what the co-pilot wrote when
``tests/webapp/copilot.mjs`` played the Dr Timbo and Kuntolo tests back
through it, and that suite fails if the co-pilot stops writing them cell for
cell. Here the Python reader reads them, and must find the test that was
run: the same times, levels and rate the browser's reader found.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from groundwater.hydraulics import analyse_pumping_test
from groundwater.ingestion.pumping import read_pumping_workbook

FIXTURES = Path(__file__).resolve().parent / "webapp" / "fixtures"

# examples/data/dr_timbo: 30 minutes at 2.93 m3/h, then an hour of recovery
TIMBO_PUMPING = [(1, 13.1), (2, 15.5), (3, 17.41), (4, 18.37), (5, 19.34),
                 (10, 27.34), (15, 30.76), (20, 33.34), (25, 37.77), (30, 42.26)]
TIMBO_RECOVERY = [(1, 42.2), (2, 41.78), (3, 41.39), (4, 41.14), (5, 39.67),
                  (10, 38.38), (15, 37.26), (20, 35.26), (25, 35.18), (30, 34.58),
                  (35, 33.85), (40, 33.18), (45, 32.55), (50, 31.95), (55, 31.05),
                  (60, 30.38)]


@pytest.fixture(scope="module")
def timbo():
    return read_pumping_workbook(FIXTURES / "copilot_dr_timbo.xlsx")


@pytest.fixture(scope="module")
def kuntolo():
    return read_pumping_workbook(FIXTURES / "copilot_kuntolo.xlsx")


def test_the_constant_test_reads_back_as_it_was_run(timbo):
    assert timbo.test_type == "constant+recovery"
    assert (timbo.static_water_level_m, timbo.pump_setting_m,
            timbo.borehole_depth_m) == (9.44, 67, 70)
    assert timbo.borehole_ref == "BH-1"
    assert len(timbo.steps) == 1
    step = timbo.steps[0]
    np.testing.assert_array_equal(step.time_min, [t for t, _ in TIMBO_PUMPING])
    np.testing.assert_array_equal(step.water_level_m, [w for _, w in TIMBO_PUMPING])
    # 20 litres in a mean of 24.6 s, written to the template's Step 1 Q cell
    assert step.discharge_m3_per_h == pytest.approx(2.927)
    np.testing.assert_array_equal(timbo.recovery_time_min, [t for t, _ in TIMBO_RECOVERY])
    np.testing.assert_array_equal(timbo.recovery_level_m, [w for _, w in TIMBO_RECOVERY])
    assert not [f for f in timbo.flags if f.level in ("error", "warning")]


def test_the_header_carries_the_site_the_gps_fix_and_the_date(timbo):
    site = timbo.site
    assert site.community == "Dr. Timbo's Residence"
    assert site.supervisor == "WiNGiN"
    assert site.date == "2026-10-03"
    # the device's fix at 8.4657 N, 13.2317 W, written as UTM 28N
    assert site.utm_zone == 28
    assert site.easting == pytest.approx(694667, abs=1)
    assert site.northing == pytest.approx(936225, abs=1)


def test_the_analysis_finds_the_casing_storage_the_co_pilot_warned_of(timbo):
    analysis = analyse_pumping_test(timbo)
    # 2.927 m3/h over 32.82 m of drawdown through a 5 inch casing and a 1.25
    # inch riser: the 117 minutes the co-pilot named at minute 30
    assert analysis.casing_storage_min == pytest.approx(117.5, abs=0.5)


def test_the_step_test_without_discharges_reads_back_with_its_reason(kuntolo):
    assert kuntolo.test_type == "step+recovery"
    assert [len(s.time_min) for s in kuntolo.steps] == [34, 34, 10]
    assert kuntolo.steps[1].time_min[0] == 61
    assert all(s.discharge_m3_per_h is None for s in kuntolo.steps)
    codes = {f.code for f in kuntolo.flags}
    assert {"missing_discharge", "level_below_pump"} <= codes
    # the stated reason is on the sheet and is not mistaken for a rate
    assert not codes & {"discharge_from_text", "discharge_ambiguous"}
    from groundwater.ingestion.common import load_grid

    grid, _ = load_grid(FIXTURES / "copilot_kuntolo.xlsx")
    assert grid[7][0] == "Discharge note"
    assert grid[7][1].startswith("Not measured (step 1: No bucket on site")
