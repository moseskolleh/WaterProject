import json

import numpy as np
import pytest

from groundwater.design import design_borehole
from groundwater.ingestion import read_drilling_workbook, read_quality_workbook
from groundwater.mapping import MapPoint, export_geojson, iso_resistivity_map
from groundwater.models import SiteMetadata, WaterQualityResult, WaterQualitySample
from groundwater.quality import assess_sample, ionic_balance
from groundwater.quality.standards import Limit, load_standards, normalise_parameter


def test_standards_table_loads():
    table = load_standards()
    assert "iron" in table
    assert table["nitrate (as no3)"].who_health.maximum == 50
    assert table["ph"].who_aesthetic.minimum == 6.5


def test_limit_parsing():
    assert Limit.parse("50").maximum == 50
    ph = Limit.parse("6.5-8.5")
    assert ph.exceeded_by(5.9) and ph.exceeded_by(9.0) and not ph.exceeded_by(7.0)


def test_parameter_aliases():
    assert normalise_parameter("Sulphate") == "sulfate"
    assert normalise_parameter("E.coli") == "e. coli"
    assert normalise_parameter("NITRATE") == "nitrate (as no3)"


def test_assessment_flags_exceedances(sample_data):
    sample = read_quality_workbook(sample_data / "dr_timbo" / "dr_timbo_water_quality.xlsx")
    assessment = assess_sample(sample)
    by_name = {r.parameter: r for r in assessment.rows}
    assert by_name["Manganese"].status == "exceeds_health"
    assert by_name["Iron"].status in ("exceeds_national", "exceeds_aesthetic")
    assert by_name["pH"].status in ("exceeds_national", "exceeds_aesthetic")
    assert by_name["Chloride"].status == "within_limits"
    assert by_name["Arsenic"].status == "below_detection"
    assert "Manganese" in assessment.verdict


def _sample_with(nitrate, nitrite):
    return WaterQualitySample(
        site=SiteMetadata(community="Test"),
        results=[
            WaterQualityResult(parameter="Nitrate (as NO3)", value=nitrate, unit="mg/L"),
            WaterQualityResult(parameter="Nitrite (as NO2)", value=nitrite, unit="mg/L"),
        ],
    )


def test_combined_nitrate_nitrite_rule_flags_false_pass():
    # NO3=40 (<50) and NO2=2 (<3) each pass, but 40/50 + 2/3 = 1.47 > 1
    assessment = assess_sample(_sample_with(40.0, 2.0))
    combined = [r for r in assessment.rows if r.parameter.startswith("Nitrate + nitrite")]
    assert combined and combined[0].status == "exceeds_health"
    assert any(f.code == "nitrate_nitrite_combined" for f in assessment.flags)
    assert assessment.health_exceedances  # verdict now treats it as unsafe


def test_combined_nitrate_nitrite_rule_passes_when_low():
    # 10/50 + 0.5/3 = 0.37 < 1, and neither individually exceeds
    assessment = assess_sample(_sample_with(10.0, 0.5))
    assert not any(r.parameter.startswith("Nitrate + nitrite") for r in assessment.rows)


def test_ionic_balance(sample_data):
    sample = read_quality_workbook(sample_data / "dr_timbo" / "dr_timbo_water_quality.xlsx")
    result = ionic_balance(sample)
    assert result is not None
    assert abs(result.error_percent) < 5


def test_design_column_is_contiguous(sample_data):
    log = read_drilling_workbook(sample_data / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    design = design_borehole(log=log, static_water_level_m=9.44)
    # casing string covers 0 to total depth with no gaps or overlaps
    cursor = 0.0
    for segment in design.segments:
        assert abs(segment.top_m - cursor) < 1e-9
        assert segment.bottom_m > segment.top_m
        cursor = segment.bottom_m
    assert abs(cursor - design.total_depth_m) < 1e-9
    # screens respect the SWL margin
    for screen in design.screens:
        assert screen.top_m >= 9.44 + 5.0 - 1e-9
    # annulus zones are contiguous: seal, backfill, gravel
    assert design.sanitary_seal[1] == design.backfill[0]
    assert design.backfill[1] == design.gravel_pack[0]
    assert design.gravel_pack[1] == design.total_depth_m


def test_design_from_ves_interpretation(rokel_ves_a):
    from groundwater.models import LayeredModel
    from groundwater.ves import interpret_model

    model = LayeredModel(np.array([832.14, 2102.8, 36.71]), np.array([1.0, 7.37]),
                         sounding_id="A (1)")
    interp = interpret_model(rokel_ves_a, model)
    design = design_borehole(interpretation=interp, static_water_level_m=6.0)
    assert design.total_depth_m == interp.max_drilling_depth_m
    assert design.screens


def test_geojson_export(tmp_path):
    points = [
        MapPoint("A (1)", 708958, 926355, kind="VES point"),
        MapPoint("B (2)", 709020, 926300, kind="VES point"),
    ]
    path = export_geojson(points, zone=28, path=tmp_path / "points.geojson")
    data = json.loads(path.read_text())
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 2
    lon, lat = data["features"][0]["geometry"]["coordinates"]
    assert -13.2 < lon < -13.0 and 8.3 < lat < 8.5


def test_iso_resistivity_map(tmp_path):
    points = [
        MapPoint("V1", 708900, 926300, value=150.0),
        MapPoint("V2", 709000, 926350, value=80.0),
        MapPoint("V3", 708950, 926420, value=220.0),
    ]
    path = iso_resistivity_map(points, zone=28, ab2=40, path=tmp_path / "iso.png")
    assert path.exists() and path.stat().st_size > 10_000


def test_iso_map_needs_three_points(tmp_path):
    points = [MapPoint("V1", 0, 0, value=1.0), MapPoint("V2", 10, 10, value=2.0)]
    with pytest.raises(ValueError):
        iso_resistivity_map(points, zone=28, ab2=40, path=tmp_path / "iso.png")


def test_an_interpolated_surface_stops_at_the_surveyed_ground():
    """Outside the hull of the points there is no measurement behind the colour.

    A contour 400 m from the nearest sounding is the interpolator continuing a
    trend, and it is read as data: somebody sites a borehole on it. The
    iso-resistivity and overburden maps padded their grid 25% past the points
    and filled every gap by nearest neighbour, so the surface ran to the edge
    of the frame in a shade indistinguishable from measured ground.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    from groundwater.mapping.maps import _clip_to_surveyed_ground

    # a triangle of points, and a grid that reaches well outside it
    e = np.array([0.0, 100.0, 50.0])
    n = np.array([0.0, 0.0, 100.0])
    gx, gy = np.meshgrid(np.linspace(-200, 300, 40), np.linspace(-200, 300, 40))
    grid = np.ones_like(gx)

    fig, ax = plt.subplots()
    try:
        clipped, did_clip = _clip_to_surveyed_ground(ax, grid, e, n, gx, gy)
    finally:
        plt.close(fig)

    assert did_clip is True
    inside = clipped[np.argmin(abs(gy[:, 0] - 25)), np.argmin(abs(gx[0] - 50))]
    assert not np.isnan(inside), "the middle of the survey lost its surface"
    corner = clipped[0, 0]
    assert np.isnan(corner), "the surface still runs past the surveyed ground"


def test_points_on_one_line_say_so_rather_than_pretending_to_clip():
    """A traverse encloses no area, which is an ordinary survey, not an error.

    There is no hull to clip to, so the surface is drawn and the figure carries
    the warning itself - a caption can be skipped, a line across the middle of
    the figure cannot.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    from groundwater.mapping.maps import _clip_to_surveyed_ground

    e = np.array([0.0, 50.0, 100.0])
    n = np.array([0.0, 0.0, 0.0])
    gx, gy = np.meshgrid(np.linspace(-50, 150, 20), np.linspace(-50, 50, 20))
    grid = np.ones_like(gx)

    fig, ax = plt.subplots()
    try:
        clipped, did_clip = _clip_to_surveyed_ground(ax, grid, e, n, gx, gy)
        said = [t.get_text() for t in ax.texts]
    finally:
        plt.close(fig)

    assert did_clip is False
    assert not np.isnan(clipped).any(), "a traverse should still get a surface"
    assert any("not clipped" in text for text in said), said


def test_the_iso_map_actually_clips(monkeypatch, tmp_path):
    """The helper is only worth having if the maps that mislead call it."""
    from groundwater import mapping
    from groundwater.mapping import MapPoint, maps

    calls = []
    real = maps._clip_to_surveyed_ground

    def spy(ax, grid, e, n, gx, gy):
        calls.append(len(e))
        return real(ax, grid, e, n, gx, gy)

    monkeypatch.setattr(maps, "_clip_to_surveyed_ground", spy)
    points = [
        MapPoint(label="A", easting=700000.0, northing=900000.0, value=120.0),
        MapPoint(label="B", easting=700400.0, northing=900000.0, value=240.0),
        MapPoint(label="C", easting=700200.0, northing=900400.0, value=80.0),
    ]
    mapping.iso_resistivity_map(points, zone=28, ab2=40, path=tmp_path / "iso.png")
    assert calls == [3], "the iso-resistivity surface is drawn without a clip"
