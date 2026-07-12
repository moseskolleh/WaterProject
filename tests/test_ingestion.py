import numpy as np

from groundwater.ingestion import (
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)


def test_ves_parsing(sample_data):
    soundings = read_ves_workbook(sample_data / "rokel" / "rokel_ves.xlsx")
    assert len(soundings) == 2
    a = soundings[0]
    assert a.sounding_id == "A (1)"
    assert a.n_readings == 18
    # leading-zero strings parse as numbers
    assert a.rho_app[13] == 78.7
    assert a.site.easting == 708958
    assert a.site.northing == 926355
    # duplicate AB/2 at segment changes preserved
    assert np.sum(a.ab2 == 40) == 2
    assert any(f.code == "segment_overlap" for f in a.flags)
    # second sounding carries the copy-over district error from the source
    assert soundings[1].site.district == "Port Loko"


def test_pumping_parsing_kuntolo(sample_data):
    test = read_pumping_workbook(sample_data / "kuntolo" / "kuntolo_step_test.xlsx")
    assert test.test_type.startswith("step")
    assert len(test.steps) == 3
    assert test.static_water_level_m == 19.28
    assert test.step_length_min == 60
    # irregular time spacing preserved
    assert list(test.steps[0].time_min[:3]) == [1.0, 2.0, 3.0]
    assert 55.0 in test.steps[0].time_min  # 52 -> 55 jump
    # incremental drawdown column ignored; water levels kept
    assert test.steps[0].water_level_m[0] == 10.80
    # recovery block read from its own column group
    assert test.recovery_time_min is not None
    assert len(test.recovery_time_min) == 44
    # discharge missing -> flagged as pending
    assert not test.has_discharge
    assert any(f.code == "missing_discharge" for f in test.flags)
    # the negative-drawdown anomaly on this sheet is flagged
    assert any(f.code == "water_level_above_static" for f in test.flags)


def test_pumping_parsing_dr_timbo(sample_data):
    test = read_pumping_workbook(sample_data / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    assert test.test_type.startswith("constant")
    assert len(test.steps) == 1
    assert test.steps[0].discharge_m3_per_h == 2.93
    assert test.static_water_level_m == 9.44
    assert test.recovery_time_min is not None
    # true drawdown recomputed from static level, not the increment column
    drawdown = test.drawdown(test.steps[0])
    assert abs(drawdown[-1] - (42.26 - 9.44)) < 1e-9


def test_drilling_parsing(sample_data):
    log = read_drilling_workbook(sample_data / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    assert log.total_depth_m == 70
    assert len(log.intervals) == 14
    assert log.intervals[0].top_m == 0 and log.intervals[0].bottom_m == 5
    assert log.water_strikes_m == [12.0, 30.0]
    assert log.grouting_depth_m == 20
    assert not any(f.code == "interval_overlap" for f in log.flags)


def test_quality_parsing(sample_data):
    sample = read_quality_workbook(sample_data / "dr_timbo" / "dr_timbo_water_quality.xlsx")
    assert len(sample.results) >= 25
    iron = sample.get("Iron")
    assert iron is not None and iron.value == 0.85
    nitrite = sample.get("Nitrite (as NO2)")
    assert nitrite.below_detection and nitrite.detection_limit == 0.01
