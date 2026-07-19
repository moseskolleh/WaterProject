"""Recomputing analysis objects from saved project sources."""

from groundwater.ingestion import read_ves_workbook
from groundwater.recompute import recompute_results
from groundwater.ves import interpret_model, invert_sounding


def test_recompute_from_bundled_samples(sample_data, tmp_path):
    sources = {
        "ves": {"sample": "rokel/rokel_ves.xlsx"},
        "pump": {"sample": "dr_timbo/dr_timbo_constant_test.xlsx"},
        "wq": {"sample": "dr_timbo/dr_timbo_water_quality.xlsx"},
        "log": {"sample": "dr_timbo/dr_timbo_drilling_log.xlsx"},
    }
    out = recompute_results(
        sources, discharges={}, design_swl=9.44,
        sample_root=sample_data, tmp_dir=tmp_path,
    )
    # every result was rebuilt
    assert set(out) == {
        "ves_results", "pump_analysis", "wq_assessment",
        "borehole_design", "drilling_log",
    }
    soundings, results, interps = out["ves_results"]
    assert len(soundings) == len(results) == len(interps) >= 1
    assert out["pump_analysis"].transmissivity_m2_per_day is not None
    assert out["wq_assessment"].rows
    assert out["borehole_design"].total_depth_m > 0

    # recomputed VES matches a direct computation from the same file
    direct = read_ves_workbook(sample_data / "rokel" / "rokel_ves.xlsx")
    direct_interp = interpret_model(direct[0], invert_sounding(direct[0]).model)
    assert interps[0].sounding_id == direct_interp.sounding_id
    assert interps[0].protective_capacity == direct_interp.protective_capacity


def test_recompute_from_uploaded_bytes(sample_data, tmp_path):
    raw = (sample_data / "dr_timbo" / "dr_timbo_water_quality.xlsx").read_bytes()
    out = recompute_results(
        {"wq": {"name": "wq.xlsx", "bytes": raw}},
        sample_root=None, tmp_dir=tmp_path,
    )
    assert "wq_assessment" in out and out["wq_assessment"].rows


def test_recompute_applies_saved_discharges(sample_data, tmp_path):
    # the Kuntolo step test has no discharges on the sheet; supply them
    out = recompute_results(
        {"pump": {"sample": "kuntolo/kuntolo_step_test.xlsx"}},
        discharges={"1": 1.5, "2": 2.2, "3": 3.0},
        sample_root=sample_data, tmp_dir=tmp_path,
    )
    analysis = out["pump_analysis"]
    # with discharges supplied the step analysis and yield now resolve
    assert analysis.step_test is not None


def test_missing_sources_return_empty(tmp_path):
    assert recompute_results({}, sample_root=None, tmp_dir=tmp_path) == {}


def test_bad_sources_are_skipped_not_raised(sample_data, tmp_path):
    # corrupt bytes, a filename traversal attempt, and a sample outside the
    # sample tree must all be skipped without raising
    out = recompute_results(
        {
            "wq": {"name": "../../evil.xlsx", "bytes": b"not a workbook"},
            "log": {"sample": "../../../etc/passwd"},
        },
        sample_root=sample_data, tmp_dir=tmp_path,
    )
    assert out == {}
    # the traversal name did not escape tmp_dir
    assert not (tmp_path.parent / "evil.xlsx").exists()
