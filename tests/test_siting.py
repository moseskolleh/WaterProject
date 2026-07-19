"""Drill-target siting suitability (prototype) tests."""

from groundwater.ingestion import read_ves_workbook
from groundwater.siting import assess_siting, suitability_map_points
from groundwater.mapping import suitability_map
from groundwater.ves import interpret_model, invert_sounding


def _interps(sample_data):
    soundings = read_ves_workbook(sample_data / "rokel" / "rokel_ves.xlsx")
    inversions = [invert_sounding(s) for s in soundings]
    return [interpret_model(s, r.model) for s, r in zip(soundings, inversions)]


def test_assess_siting_ranks_and_bounds(sample_data):
    results = assess_siting(_interps(sample_data))
    assert results, "expected at least one scored point"
    # ranked most suitable first, ranks are 1..n and dense
    assert [r.rank for r in results] == list(range(1, len(results) + 1))
    assert results[0].suitability == max(r.suitability for r in results)
    for r in results:
        assert 0.0 <= r.suitability <= 100.0
        assert r.grade in ("Poor", "Moderate", "Good", "Very good")
        # components are normalised
        c = r.components
        for v in (c.aquifer_thickness, c.resistivity_fit, c.overburden, c.basal_fracture):
            assert 0.0 <= v <= 1.0
        assert r.rationale


def test_suitability_grade_tracks_score(sample_data):
    for r in assess_siting(_interps(sample_data)):
        expected = (
            "Very good" if r.suitability >= 75 else
            "Good" if r.suitability >= 55 else
            "Moderate" if r.suitability >= 35 else "Poor"
        )
        assert r.grade == expected


def test_suitability_map_renders(sample_data, tmp_path):
    results = assess_siting(_interps(sample_data))
    points = suitability_map_points(results)
    if not points:
        return  # sample lacks coordinates; nothing to draw
    zone = 29
    out = suitability_map(points, zone, path=tmp_path / "suitability.png")
    assert out.exists() and out.stat().st_size > 0
