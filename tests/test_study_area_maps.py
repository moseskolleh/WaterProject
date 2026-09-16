"""The study area, topographic and subsurface maps.

Three groups of assertions, and they are not the same kind of assertion.
The figures are checked for having been drawn at all - a PNG a report can
embed - because asserting on the contents of a raster is asserting on
matplotlib. What is checked properly is everything around the figure: the
readers, which parse real file formats byte for byte and must not quietly
mis-place a tile by a degree; the geometry, which decides whether a
cross-section through these soundings means anything; and the refusals,
which are the point of the whole module. A map that cannot be drawn
honestly must fail loudly rather than draw something plausible.
"""

from __future__ import annotations

import math
import struct

import numpy as np
import pytest

from groundwater.mapping import (
    ElevationGrid,
    apparent_resistivity_pseudosection,
    aquifer_thickness_map,
    bedrock_elevation_map,
    bedrock_elevation_points,
    common_ab2_spacings,
    depth_to_bedrock_map,
    iso_resistivity_points,
    load_elevation,
    plot_ground_profile,
    plot_study_area_map,
    plot_topographic_map,
    protective_capacity_map,
    read_esri_ascii,
    read_srtm_hgt,
    read_xyz,
    subsurface_map_points,
    transverse_resistance_map,
    traverse_profile,
)
from groundwater.mapping.subsurface import PROTECTIVE_CLASSES
from groundwater.mapping.terrain import hillshade, slope_percent
from groundwater.models import LayeredModel, SiteMetadata, VESSounding
from groundwater.ves import interpret_model

# Kuntolo, in basement terrain well inside the country, so the window is
# never half ocean and the chiefdom layer always has something to draw.
KUNTOLO = dict(easting=178000.0, northing=1000000.0, utm_zone=29)


def _site(**over) -> SiteMetadata:
    fields = dict(community="Kuntolo", district="Bombali", **KUNTOLO)
    fields.update(over)
    return SiteMetadata(**fields)


def _traverse(n: int = 5, scatter_m: float = 8.0, seed: int = 3):
    """A synthetic basement traverse: topsoil, weathered zone, fresh rock."""
    rng = np.random.default_rng(seed)
    ab2 = np.array([1, 1.5, 2, 3, 4, 6, 8, 10, 15, 20, 25, 32, 40, 50, 65, 80, 100.0])
    soundings, interps = [], []
    for k in range(n):
        easting = KUNTOLO["easting"] + k * 120.0 + rng.normal(0, scatter_m)
        northing = KUNTOLO["northing"] + k * 55.0 + rng.normal(0, scatter_m)
        site = _site(easting=easting, northing=northing,
                     elevation_m=70.0 + k * 3.5)
        rho_app = np.interp(
            np.log10(ab2), np.log10([1, 5, 20, 100]),
            [300.0, 120.0, 70.0 + k * 8, 900.0],
        )
        sounding = VESSounding(
            site=site, sounding_id=f"VES {k + 1}", ab2=ab2,
            mn=np.full(ab2.size, 0.5), rho_app=rho_app,
        )
        model = LayeredModel(
            resistivities=np.array([320.0, 55.0 + k * 9, 4200.0]),
            thicknesses=np.array([2.5 + k * 0.4, 14.0 + k * 5.5]),
            sounding_id=sounding.sounding_id,
        )
        interp = interpret_model(sounding, model)
        interp.site_easting = easting
        interp.site_northing = northing
        interp.site_elevation_m = site.elevation_m
        soundings.append(sounding)
        interps.append(interp)
    return soundings, interps


# ---------------------------------------------------------------------------
# Study area map
# ---------------------------------------------------------------------------

def test_study_area_map_renders_with_its_overlays(tmp_path):
    path = plot_study_area_map(
        _site(), path=tmp_path / "study.png", radius_km=25,
        points=[
            {"lat": 9.04, "lon": -12.05, "label": "VES 1", "kind": "VES point"},
            {"lat": 9.05, "lon": -12.06, "label": "BH 1", "kind": "borehole"},
            {"lat": 9.03, "lon": -12.04, "kind": "water point"},
        ],
    )
    assert path.stat().st_size > 30_000


def test_study_area_map_without_a_gps_fix_covers_the_recorded_area(tmp_path):
    """A district is still a study area, and the title says which."""
    site = SiteMetadata(community="Kuntoloh", district="Port Loko")
    path = plot_study_area_map(site, path=tmp_path / "study.png", radius_km=30)
    assert path.exists()


def test_study_area_map_needs_somewhere_to_centre_on(tmp_path):
    with pytest.raises(ValueError, match="somewhere to centre on"):
        plot_study_area_map(SiteMetadata(community="Nowhere"),
                            path=tmp_path / "study.png")


def test_study_area_map_takes_the_geological_tint(tmp_path):
    path = plot_study_area_map(_site(), path=tmp_path / "study_geo.png",
                               radius_km=20, show_geology=True)
    assert path.stat().st_size > 30_000


def test_a_zoomed_unit_map_says_what_scale_it_came_from():
    """The 1:5M caveat appears on a local window and not on a national map."""
    from groundwater.mapping.regional import _BGS_SOURCE_SCALE, _scale_caveat

    assert _scale_caveat(None, _BGS_SOURCE_SCALE) == ""
    assert _scale_caveat(200.0, _BGS_SOURCE_SCALE) == ""
    note = _scale_caveat(20.0, _BGS_SOURCE_SCALE, "Publisher says so.")
    assert "1:5,000,000" in note
    assert "2.5 km" in note
    assert note.endswith("Publisher says so.")


def test_a_local_unit_map_legends_only_what_is_in_the_window(tmp_path):
    """A legend naming formations that are not on the map is a wrong legend."""
    from groundwater.mapping.regional import _ring_in_box

    box = (-12.2, 8.9, -11.9, 9.2)
    inside = np.array([[-12.1, 9.0], [-12.0, 9.0], [-12.0, 9.1], [-12.1, 9.0]])
    # extents overlap the window, but the shape is nowhere near it: this is
    # the case the old extent-only test got wrong
    elsewhere = np.array([[-13.4, 7.0], [-11.0, 7.0], [-11.0, 7.05],
                          [-13.4, 7.0]])
    crossing = np.array([[-13.0, 9.05], [-11.0, 9.05], [-11.0, 9.06],
                         [-13.0, 9.05]])
    enclosing = np.array([[-14.0, 6.0], [-10.0, 6.0], [-10.0, 11.0],
                          [-14.0, 11.0], [-14.0, 6.0]])
    assert _ring_in_box(inside, box)
    assert not _ring_in_box(elsewhere, box)
    assert _ring_in_box(crossing, box), "a unit slicing the window is in view"
    assert _ring_in_box(enclosing, box), "a unit the window sits inside is in view"


# ---------------------------------------------------------------------------
# Elevation readers
# ---------------------------------------------------------------------------

def _write_hgt(path, side=1201, base=100.0):
    y = np.linspace(0, 1, side)[:, None]
    x = np.linspace(0, 1, side)[None, :]
    z = base + 200 * x + 60 * np.sin(y * 6)
    # the file runs north first, which is the flip the reader has to undo
    np.round(z[::-1, :]).astype(">i2").tofile(str(path))
    return z


def test_srtm_hgt_is_read_the_right_way_up_and_in_the_right_degree_square(tmp_path):
    path = tmp_path / "N08W013.hgt"
    z = _write_hgt(path)
    grid = read_srtm_hgt(path)

    assert grid.bounds == pytest.approx((-13.0, 8.0, -12.0, 9.0))
    assert grid.resolution_note.startswith("3 arc-second")
    # row 0 is the southern edge: the reader flipped the file, so the value
    # at the south-west corner is the one the source had at its last row
    assert grid.z[0, 0] == pytest.approx(z[0, 0], abs=1.0)
    assert grid.z[-1, 0] == pytest.approx(z[-1, 0], abs=1.0)
    # and east is higher, as it was written
    assert grid.z[0, -1] > grid.z[0, 0]


def test_an_srtm_tile_that_does_not_name_its_corner_is_refused(tmp_path):
    path = tmp_path / "elevation.hgt"
    _write_hgt(path)
    with pytest.raises(ValueError, match="does not name its corner"):
        read_srtm_hgt(path)


def test_an_srtm_tile_of_the_wrong_length_is_refused(tmp_path):
    path = tmp_path / "N08W013.hgt"
    path.write_bytes(struct.pack(">10h", *range(10)))
    with pytest.raises(ValueError, match="not a square"):
        read_srtm_hgt(path)


def test_srtm_voids_survive_as_voids_rather_than_as_a_depth(tmp_path):
    side = 1201
    z = np.full((side, side), 120, dtype=">i2")
    z[600, 600] = -32768
    z.tofile(str(tmp_path / "N08W013.hgt"))
    grid = read_srtm_hgt(tmp_path / "N08W013.hgt")
    assert np.isnan(grid.z).sum() == 1
    assert np.nanmin(grid.z) == 120  # the void did not become the lowest ground


def test_esri_ascii_grid_reads_corner_and_centre_headers(tmp_path):
    corner = tmp_path / "corner.asc"
    corner.write_text(
        "ncols 3\nnrows 2\nxllcorner -13.0\nyllcorner 8.0\ncellsize 0.01\n"
        "NODATA_value -9999\n"
        "10 11 12\n20 21 -9999\n",
        encoding="utf-8",
    )
    grid = read_esri_ascii(corner)
    # xllcorner is the cell's outer edge, so the first centre is half a cell in
    assert grid.lons[0] == pytest.approx(-12.995)
    assert grid.lats[0] == pytest.approx(8.005)
    # the file runs north first, so its last row is this grid's first
    assert grid.z[0].tolist() == [20.0, 21.0, pytest.approx(float("nan"), nan_ok=True)] \
        or (grid.z[0, 0] == 20.0 and math.isnan(grid.z[0, 2]))
    assert grid.z[1].tolist() == [10.0, 11.0, 12.0]

    centre = tmp_path / "centre.asc"
    centre.write_text(
        "ncols 2\nnrows 2\nxllcenter -13.0\nyllcenter 8.0\ncellsize 0.01\n"
        "1 2\n3 4\n",
        encoding="utf-8",
    )
    assert read_esri_ascii(centre).lons[0] == pytest.approx(-13.0)


def test_an_ascii_grid_that_does_not_hold_what_it_declares_is_refused(tmp_path):
    path = tmp_path / "short.asc"
    path.write_text(
        "ncols 3\nnrows 3\nxllcorner -13\nyllcorner 8\ncellsize 0.01\n1 2 3\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="declares 3x3 cells"):
        read_esri_ascii(path)


def test_xyz_columns_are_placed_on_the_grid_whatever_order_they_arrive_in(tmp_path):
    path = tmp_path / "points.xyz"
    path.write_text(
        "# lon lat elevation\n"
        "-13.00 8.01 40\n"
        "-12.99 8.00 20\n"
        "-13.00 8.00 10\n"
        "-12.99 8.01 30\n",
        encoding="utf-8",
    )
    grid = read_xyz(path)
    assert grid.z.shape == (2, 2)
    assert grid.z[0, 0] == 10 and grid.z[1, 1] == 30


def test_unevenly_spaced_points_are_refused_rather_than_interpolated(tmp_path):
    """Gridding scattered heights is the thing this module will not do."""
    path = tmp_path / "scatter.xyz"
    path.write_text(
        "-13.000 8.000 10\n-12.990 8.000 20\n-12.937 8.000 35\n"
        "-13.000 8.010 30\n-12.990 8.010 40\n-12.937 8.010 55\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unevenly spaced longitudes"):
        read_xyz(path)


def test_a_thin_scatter_on_a_regular_lattice_is_refused_too(tmp_path):
    """Evenly spaced is not the same as a grid: most cells must be filled."""
    path = tmp_path / "sparse.xyz"
    # a tidy 4x4 lattice with only the diagonal recorded
    rows = [f"{-13.0 + k * 0.01:.3f} {8.0 + k * 0.01:.3f} {10 * k}"
            for k in range(4)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="fills 4 of 16 cells"):
        read_xyz(path)


def test_a_grid_with_a_hole_in_it_is_still_a_grid(tmp_path):
    """A partial export is a map with a gap, not a refusal."""
    path = tmp_path / "holed.xyz"
    rows = [
        f"{-13.0 + i * 0.01:.3f} {8.0 + j * 0.01:.3f} {10 * (i + j)}"
        for i in range(3) for j in range(3)
        if not (i == 1 and j == 1)
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    grid = read_xyz(path)
    assert np.isnan(grid.z).sum() == 1


def test_load_elevation_names_the_formats_it_reads(tmp_path):
    path = tmp_path / "dem.tif"
    path.write_bytes(b"II*\x00")
    with pytest.raises(ValueError) as excinfo:
        load_elevation(path)
    message = str(excinfo.value)
    assert ".hgt" in message and ".asc" in message
    assert "gdal_translate" in message, "say how to convert a GeoTIFF"


# ---------------------------------------------------------------------------
# Elevation grid and topographic map
# ---------------------------------------------------------------------------

def _grid(n=60, relief=180.0) -> ElevationGrid:
    lons = np.linspace(-12.2, -11.9, n)
    lats = np.linspace(8.9, 9.2, n)
    z = relief * np.sin(np.linspace(0, math.pi, n))[None, :] + 40
    return ElevationGrid(lons, lats, np.repeat(z, n, axis=0),
                         source="test grid", resolution_note="90 m cell")


def test_an_elevation_grid_checks_its_own_shape():
    with pytest.raises(ValueError, match="latitudes and"):
        ElevationGrid(np.arange(3.0), np.arange(4.0), np.zeros((3, 3)))


def test_elevation_at_a_point_is_bilinear_and_refuses_voids():
    grid = _grid()
    assert grid.elevation_at(0.0, 0.0) is None, "outside the grid is not zero"
    inside = grid.elevation_at(-12.05, 9.05)
    assert inside is not None and 40 <= inside <= 230

    holed = _grid()
    holed.z[:] = 100.0
    holed.z[30, 30] = np.nan
    assert holed.elevation_at(float(holed.lons[30]), float(holed.lats[30])) is None


def test_a_window_that_the_model_does_not_cover_says_so():
    with pytest.raises(ValueError, match="Supply a model covering the site"):
        _grid().window(-5.0, 5.0, 10.0)


def test_hillshade_lights_the_north_west_and_stays_in_range():
    grid = _grid()
    shade = hillshade(grid)
    assert shade.shape == grid.z.shape
    assert shade.min() >= 0.0 and shade.max() <= 1.0
    # a slope facing the sun is brighter than the one facing away
    west_facing = shade[:, 10].mean()
    east_facing = shade[:, -10].mean()
    assert not math.isclose(west_facing, east_facing, rel_tol=1e-3)


def test_slope_is_reported_as_a_percentage_of_real_ground():
    flat = _grid(relief=0.0)
    assert slope_percent(flat).max() == pytest.approx(0.0, abs=1e-9)
    assert slope_percent(_grid(relief=400.0)).max() > slope_percent(_grid()).max()


def test_topographic_map_renders_with_contours_and_spot_heights(tmp_path):
    path = plot_topographic_map(
        _grid(), _site(), path=tmp_path / "topo.png",
        spot_heights=[(-12.05, 9.05, "VES 1  84 m")],
    )
    assert path.stat().st_size > 30_000


def test_a_topographic_map_of_nothing_but_voids_is_refused(tmp_path):
    grid = _grid()
    grid.z[:] = np.nan
    with pytest.raises(ValueError, match="every sample is a void"):
        plot_topographic_map(grid, _site(), path=tmp_path / "topo.png")


def test_ground_profile_needs_two_levelled_stations(tmp_path):
    with pytest.raises(ValueError, match="at least two levelled"):
        plot_ground_profile([0, 100, 200], [70.0, float("nan"), float("nan")],
                            path=tmp_path / "profile.png")


def test_ground_profile_draws_the_stations_it_has(tmp_path):
    path = plot_ground_profile(
        [0, 120, 260, 400], [70.0, 73.5, float("nan"), 81.0],
        labels=["VES 1", "VES 2", "VES 3", "VES 4"],
        path=tmp_path / "profile.png",
    )
    assert path.stat().st_size > 10_000


def test_a_ground_profile_needs_one_elevation_per_station(tmp_path):
    with pytest.raises(ValueError, match="one elevation per station"):
        plot_ground_profile([0, 100], [70.0, 71.0, 72.0],
                            path=tmp_path / "profile.png")


# ---------------------------------------------------------------------------
# Subsurface maps
# ---------------------------------------------------------------------------

def test_subsurface_points_drop_what_cannot_be_mapped():
    _soundings, interps = _traverse()
    assert len(subsurface_map_points(interps, "aquifer_thickness_m")) == 5

    interps[0].site_easting = None          # no position
    interps[1].depth_to_basement_m = None   # never reached basement
    placed = subsurface_map_points(interps, "depth_to_basement_m")
    assert [p.label for p in placed] == ["VES 3", "VES 4", "VES 5"]


def test_bedrock_elevation_needs_both_the_ground_and_the_depth():
    _soundings, interps = _traverse()
    assert len(bedrock_elevation_points(interps)) == 5
    # ground level less depth to basement, at the sounding
    first = bedrock_elevation_points(interps)[0]
    assert first.value == pytest.approx(
        interps[0].site_elevation_m - interps[0].depth_to_basement_m
    )

    for interp in interps:
        interp.site_elevation_m = None
    assert bedrock_elevation_points(interps) == [], \
        "no elevations means no bedrock surface, not a surface at sea level"


def test_subsurface_maps_render(tmp_path):
    _soundings, interps = _traverse()
    for name, fn in (
        ("depth", depth_to_bedrock_map),
        ("aquifer", aquifer_thickness_map),
        ("bedrock", bedrock_elevation_map),
        ("transverse", transverse_resistance_map),
        ("protective", protective_capacity_map),
    ):
        path = fn(interps, zone=29, path=tmp_path / f"{name}.png")
        assert path.stat().st_size > 20_000, name


def test_a_surface_from_two_soundings_is_refused(tmp_path):
    _soundings, interps = _traverse(n=2)
    with pytest.raises(ValueError, match="at least 3 soundings"):
        aquifer_thickness_map(interps, zone=29, path=tmp_path / "aq.png")


def test_protective_classes_cover_the_range_without_a_gap():
    """The map's colours and the report's words read one table."""
    from groundwater.ves.interpret import _protective_capacity

    assert PROTECTIVE_CLASSES[0][0] == 0.0
    assert PROTECTIVE_CLASSES[-1][1] == math.inf
    for (_lo, hi, _name, _colour), (next_lo, *_rest) in zip(
        PROTECTIVE_CLASSES, PROTECTIVE_CLASSES[1:], strict=False
    ):
        assert hi == next_lo, "the classes must not leave a conductance unrated"
    # and the words match the ones the interpretation writes into the report
    for lo, hi, name, _colour in PROTECTIVE_CLASSES:
        probe = lo + (0.05 if math.isinf(hi) else (hi - lo) / 2)
        assert _protective_capacity(probe) == name


# ---------------------------------------------------------------------------
# The traverse and the pseudo-section
# ---------------------------------------------------------------------------

def test_the_traverse_orders_soundings_along_its_own_line():
    _soundings, interps = _traverse()
    profile = traverse_profile(interps)
    assert list(profile.labels) == [f"VES {k}" for k in range(1, 6)]
    assert profile.chainage_m[0] == pytest.approx(0.0)
    assert np.all(np.diff(profile.chainage_m) > 0)
    # 120 m east and 55 m north per station, five stations
    assert profile.length_m == pytest.approx(528.0, rel=0.1)
    assert profile.is_collinear


def test_a_traverse_is_the_same_section_whichever_order_it_arrives_in():
    """Field order is not always along the line; the section draws the line.

    The principal axis comes back from an SVD, whose singular vectors have
    an arbitrary sign, so the same five soundings handed over reversed used
    to produce the same ground mirrored - the section drawn the other way
    round, with the chainages running backwards.
    """
    _soundings, interps = _traverse()
    forwards = traverse_profile(interps)
    backwards = traverse_profile(list(reversed(interps)))
    assert list(backwards.labels) == list(forwards.labels)
    assert backwards.chainage_m == pytest.approx(forwards.chainage_m)
    assert backwards.bearing_deg == pytest.approx(forwards.bearing_deg)


def test_scattered_soundings_are_reported_as_not_a_section():
    _soundings, interps = _traverse(scatter_m=250.0, seed=11)
    profile = traverse_profile(interps)
    assert profile.max_offset_m > 100
    assert not profile.is_collinear, \
        "soundings this scattered do not make a cross-section"


def test_a_traverse_needs_two_positioned_soundings():
    _soundings, interps = _traverse(n=3)
    for interp in interps[1:]:
        interp.site_easting = None
    with pytest.raises(ValueError, match="1 of 3 soundings carry a position"):
        traverse_profile(interps)


def test_pseudosection_renders_from_the_readings(tmp_path):
    soundings, interps = _traverse()
    profile = traverse_profile(interps)
    path = apparent_resistivity_pseudosection(
        soundings, profile, path=tmp_path / "pseudo.png")
    assert path.stat().st_size > 20_000


def test_pseudosection_without_positions_says_the_axis_is_not_ground_distance(
    tmp_path,
):
    soundings, _interps = _traverse()
    path = apparent_resistivity_pseudosection(
        soundings, None, path=tmp_path / "pseudo.png")
    assert path.exists()


def test_a_pseudosection_of_one_sounding_is_refused(tmp_path):
    soundings, _interps = _traverse(n=1)
    with pytest.raises(ValueError, match="at least two soundings"):
        apparent_resistivity_pseudosection(soundings, None,
                                           path=tmp_path / "pseudo.png")


# ---------------------------------------------------------------------------
# Iso-resistivity, from the measured curves
# ---------------------------------------------------------------------------

def test_only_spacings_every_sounding_measured_are_offered():
    soundings, _interps = _traverse()
    shared = common_ab2_spacings(soundings)
    assert shared[0] == 1.0 and shared[-1] == 100.0

    # one sounding stops short: the spacings past it are no longer shared
    soundings[2].ab2 = soundings[2].ab2[:10]
    soundings[2].rho_app = soundings[2].rho_app[:10]
    assert max(common_ab2_spacings(soundings)) == 20.0
    assert common_ab2_spacings([]) == []


def test_iso_resistivity_takes_the_reading_rather_than_interpolating_one():
    soundings, _interps = _traverse()
    points = iso_resistivity_points(soundings, 20.0)
    assert len(points) == 5
    measured = float(
        soundings[0].rho_app[list(soundings[0].ab2).index(20.0)]
    )
    assert points[0].value == pytest.approx(measured)

    # a spacing nobody measured contributes nothing at all
    assert iso_resistivity_points(soundings, 17.3) == []


def test_a_repeated_spacing_across_a_segment_change_is_averaged_once():
    """A Schlumberger segment change records one AB/2 twice, not two points."""
    site = _site()
    sounding = VESSounding(
        site=site, sounding_id="VES 1",
        ab2=np.array([10.0, 20.0, 20.0, 40.0]),
        mn=np.array([0.5, 0.5, 5.0, 5.0]),
        rho_app=np.array([100.0, 200.0, 800.0, 300.0]),
    )
    points = iso_resistivity_points([sounding], 20.0)
    assert len(points) == 1
    assert points[0].value == pytest.approx(math.sqrt(200.0 * 800.0))


def test_the_section_is_drawn_at_the_soundings_real_spacing(tmp_path):
    """Evenly spaced columns read as a uniformly thickening weathered zone."""
    _soundings, interps = _traverse()
    from groundwater.mapping import geoelectric_section_along_traverse

    path = geoelectric_section_along_traverse(
        interps, path=tmp_path / "section.png")
    assert path.stat().st_size > 20_000

    # the chainages it draws at are the surveyed ones, not 0/100/200/300
    profile = traverse_profile(interps)
    assert profile.chainage_m[1] != pytest.approx(100.0, abs=1.0)


def test_a_section_through_one_sounding_is_refused(tmp_path):
    _soundings, interps = _traverse(n=1)
    from groundwater.mapping import geoelectric_section_along_traverse

    with pytest.raises(ValueError, match="at least two"):
        geoelectric_section_along_traverse(interps,
                                           path=tmp_path / "section.png")


def test_a_column_stands_for_the_ground_the_sounding_reached(tmp_path):
    """Two soundings 20 km apart are not two columns 8 km wide."""
    from groundwater.ves.plots import plot_geoelectric_section

    models = [
        LayeredModel(resistivities=np.array([300.0, 60.0, 4000.0]),
                     thicknesses=np.array([2.0, 18.0]), sounding_id="A"),
        LayeredModel(resistivities=np.array([280.0, 55.0, 3800.0]),
                     thicknesses=np.array([2.5, 20.0]), sounding_id="B"),
    ]
    wide = plot_geoelectric_section(models, positions=[0.0, 20000.0],
                                    labels=["A", "B"])
    narrow = plot_geoelectric_section(models, positions=[0.0, 20000.0],
                                      labels=["A", "B"], half_width_m=80.0)
    # the drawn column is a filled polygon; its width is what changed
    def widest(fig):
        spans = [
            float(np.ptp(coll.get_paths()[0].vertices[:, 0]))
            for coll in fig.axes[0].collections if coll.get_paths()
        ]
        return max(spans) if spans else 0.0

    assert widest(wide) > 3000, "the old default really is kilometres wide"
    assert widest(narrow) < 500, "the reach-limited column is metres wide"
    plot_geoelectric_section(models, positions=[0.0, 20000.0],
                             labels=["A", "B"], half_width_m=80.0,
                             path=tmp_path / "section.png")


def test_a_correlation_across_ground_nobody_surveyed_says_so():
    """The dashed lines are a proposal when the gap dwarfs the reach."""
    from groundwater.mapping.subsurface import _correlation_note

    _soundings, close = _traverse()
    profile = traverse_profile(close)
    reach = max(i.investigation_depth_m for i in close)
    # stations ~130 m apart, soundings reaching 100 m: correlation is fine
    assert _correlation_note(profile, reach) == ""

    # push the last sounding 20 km away and it is not fine
    far = close[:]
    far[-1].site_easting = float(far[-1].site_easting) + 20_000.0
    note = _correlation_note(traverse_profile(far), reach)
    assert "no measurement between them" in note
    assert "times the" in note


def test_the_note_is_silent_when_there_is_nothing_to_measure_it_against():
    from groundwater.mapping.subsurface import _correlation_note

    _soundings, interps = _traverse()
    assert _correlation_note(traverse_profile(interps), 0.0) == ""


# ---------------------------------------------------------------------------
# Lithology: what the geology polygons are made of
# ---------------------------------------------------------------------------

def test_the_freetown_peninsula_is_named_for_its_rock_not_its_age():
    """The user's complaint, as a test.

    The bundled USGS layer calls the one polygon over the Western Area
    "Paleozoic Igneous". It is the Freetown Layered Complex - Jurassic
    layered gabbro - and a driller told "Paleozoic Igneous" has been
    given a wrong age and no rock at all.
    """
    from groundwater.mapping.lithology import lithology_for

    rock = lithology_for("Pi", "Western Area")
    assert rock is not None
    assert rock.formation_name == "Freetown Layered Complex"
    assert rock.formation_code == "Jf"
    assert "gabbro" in rock.lithology
    assert "Jurassic" in rock.era_actual
    assert rock.usgs_era_wrong, "the source's age for this polygon is wrong"
    note = rock.provenance_note("Paleozoic Igneous")
    # both ages are stated: the source is not silently corrected
    assert "Paleozoic Igneous" in note and "Jurassic" in note
    assert "1:5,000,000 one either way" in note


def test_the_coastal_plain_is_the_bullom_group():
    from groundwater.mapping.lithology import lithology_for

    rock = lithology_for("Qe", "Western Area")
    assert rock.formation_name == "Bullom Group"
    assert "sand" in rock.lithology and "clay" in rock.lithology
    assert "saline" in rock.aquifer_character, "the coastal risk has to be said"


def test_a_class_annotated_for_one_region_is_not_applied_to_another():
    """The Freetown gabbro is not under Kono, and must not be claimed to be."""
    from groundwater.mapping.lithology import lithology_for

    assert lithology_for("Pi", "Kono") is None
    assert lithology_for("Pi", None) is None


def test_the_units_that_are_not_in_sierra_leone_are_left_unnamed():
    """'Ordovician' and 'Silurian' are in Guinea, not Sierra Leone.

    Every one of their vertices is in the Bove Basin, inside the bundled
    window only because the clip box reaches 10.15 N. Naming them for a
    Sierra Leonean formation would put a name on another country's ground.
    """
    from groundwater.mapping.lithology import lithology_for
    from groundwater.mapping.regional import _point_in_ring, load_admin, load_geology

    outline, _ = load_admin()
    units = load_geology()
    for code in ("O", "S"):
        rings = [u.ring for u in units if u.glg == code]
        assert rings, code
        inside = sum(
            1 for ring in rings for v in ring
            if any(_point_in_ring(v[0], v[1], r) for r in outline.rings)
        )
        assert inside == 0, f"{code} now reaches Sierra Leone; revisit the crosswalk"
        assert lithology_for(code, "Bombali") is None


def test_the_basement_class_admits_it_is_not_one_rock():
    """'Precambrian' covers most of the country and at least ten formations."""
    from groundwater.mapping.lithology import lithology_for

    rock = lithology_for("pCm", "Kono")
    assert "Leonean granite" in rock.formation_name
    assert "Rokel River" in rock.lithology, "the metasediments inside it are named"
    assert "not one rock" in rock.aquifer_character


def test_every_crosswalk_row_says_where_it_came_from():
    from groundwater.mapping.lithology import load_crosswalk

    rows = load_crosswalk()
    assert rows
    for row in rows:
        assert row.basis in {"legend", "published"}, row.usgs_code
        assert row.usgs_code and row.region
