"""Drill-target siting suitability (prototype) tests."""

import numpy as np
import pytest

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


def test_the_suitability_surface_is_written_as_a_raster(tmp_path):
    """The grid was computed and thrown away; now it survives as a file."""
    rasterio = pytest.importorskip("rasterio")

    from groundwater.mapping import MapPoint, suitability_map

    points = [
        MapPoint("VES-1", 700000, 950000, 82.0, "Very good"),
        MapPoint("VES-2", 700400, 950300, 30.0, "Poor"),
        MapPoint("VES-3", 700200, 950500, 55.0, "Good"),
        MapPoint("VES-4", 700100, 950200, 61.0, "Good"),
    ]
    suitability_map(points, 28, path=tmp_path / "suitability.png")
    raster = tmp_path / "suitability.tif"
    assert raster.exists()

    with rasterio.open(raster) as dataset:
        band = dataset.read(1)
        assert dataset.crs.to_epsg() == 32628
        assert dataset.dtypes[0] == "float32"
        # scores stay scores
        assert 0 <= float(band[~np.isnan(band)].min()) <= 100
        assert 0 <= float(band[~np.isnan(band)].max()) <= 100
        # ground nobody surveyed is absent, not zero
        assert np.isnan(band).any(), "the hull mask did not reach the raster"
        assert not (band == 0).any(), "masked ground was written as a score of zero"


def test_the_raster_can_be_switched_off(tmp_path):
    from groundwater.mapping import MapPoint, suitability_map

    points = [
        MapPoint("VES-1", 700000, 950000, 82.0, "Very good"),
        MapPoint("VES-2", 700400, 950300, 30.0, "Poor"),
        MapPoint("VES-3", 700200, 950500, 55.0, "Good"),
    ]
    suitability_map(points, 28, path=tmp_path / "s.png", raster=False)
    assert not (tmp_path / "s.tif").exists()
