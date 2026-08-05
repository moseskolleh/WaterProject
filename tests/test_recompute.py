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
    # every result was rebuilt, and nothing failed quietly
    assert set(out) == {
        "ves_results", "pump_analysis", "wq_assessment",
        "borehole_design", "drilling_log", "recompute_diagnostics",
    }
    assert out["recompute_diagnostics"]["issues"] == []
    assert set(out["recompute_diagnostics"]["ok"]) == {"ves", "pump", "wq", "log"}
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
    out = recompute_results({}, sample_root=None, tmp_dir=tmp_path)
    # the diagnostics key is always present, so loading a second project
    # clears the first one's banner rather than leaving a stale one on screen
    assert set(out) == {"recompute_diagnostics"}
    assert out["recompute_diagnostics"] == {"ok": [], "issues": []}


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
    assert set(out) == {"recompute_diagnostics"}
    # the traversal name did not escape tmp_dir
    assert not (tmp_path.parent / "evil.xlsx").exists()


def test_a_failed_source_is_reported_not_swallowed(sample_data, tmp_path):
    """A silently dropped result reads as "never sampled", not as "failed".

    A project whose water-quality workbook no longer parsed came back looking
    like a borehole nobody had ever tested: the stage showed as not started,
    the portfolio summary carried no verdict, and the handover report was
    written without a water-quality section - with nothing anywhere saying a
    file had failed to load.
    """
    out = recompute_results(
        {
            "wq": {"name": "lab.xlsx", "bytes": b"not a workbook"},
            "log": {"sample": "dr_timbo/dr_timbo_drilling_log.xlsx"},
        },
        sample_root=sample_data, tmp_dir=tmp_path,
    )
    # the good source still came through: one failure does not cost the rest
    assert "drilling_log" in out
    diagnostics = out["recompute_diagnostics"]
    assert diagnostics["ok"] == ["log"]
    issues = diagnostics["issues"]
    assert len(issues) == 1
    issue = issues[0]
    assert issue["source"] == "wq"
    assert issue["result"] == "wq_assessment"
    assert issue["label"] == "Water quality"
    assert issue["level"] == "error"
    assert issue["code"] == "parse_error"
    assert issue["context"] == "lab.xlsx"
    assert issue["detail"]                      # the exception is kept
    assert "not" in issue["message"].lower()
    # JSON-safe by construction, so it survives st.session_state and a save
    import json
    json.dumps(diagnostics)


def test_a_missing_bundled_sample_says_so(sample_data, tmp_path):
    out = recompute_results(
        {"wq": {"sample": "nowhere/gone.xlsx"}},
        sample_root=sample_data, tmp_dir=tmp_path,
    )
    issues = out["recompute_diagnostics"]["issues"]
    assert [i["code"] for i in issues] == ["missing_sample"]
    assert issues[0]["context"] == "nowhere/gone.xlsx"


def test_a_hand_edited_payload_does_not_abort_the_whole_load(sample_data, tmp_path):
    """bytes() on a str payload used to escape _materialize entirely.

    It propagated out of recompute_results and was caught by the app's
    blanket handler, which discarded every other result that had already
    been rebuilt.
    """
    out = recompute_results(
        {
            "wq": {"name": "lab.xlsx", "bytes": "this is a string"},
            "log": {"sample": "dr_timbo/dr_timbo_drilling_log.xlsx"},
        },
        sample_root=sample_data, tmp_dir=tmp_path,
    )
    assert "drilling_log" in out
    assert [i["code"] for i in out["recompute_diagnostics"]["issues"]] == ["bad_payload"]
