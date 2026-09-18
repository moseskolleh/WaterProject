"""The regional maps say where things are, at the scale they are drawn.

The scale caveat quoted an 80 km window on maps drawn at 52 km and
135 km; the same USGS polygon was named for the site's district rather
than its own; chiefdom names went onto client maps truncated to fifteen
characters; Guinea and Liberia were painted the same blue as the
Atlantic; graticule ticks past the frame grew every map; the study area
was hard-wired to 80 km across.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from groundwater.mapping import cartography as carto  # noqa: E402
from groundwater.mapping.regional import (  # noqa: E402
    _home_district,
    _unit_district,
    area_window,
    canonical_chiefdom,
    chiefdom_of,
    foreign_land_rings,
    load_admin,
    load_chiefdoms,
    load_geology,
    plot_admin_map,
    plot_geological_map,
)
from groundwater.models import SiteMetadata  # noqa: E402
from groundwater.reporting.context import study_area_radius_km  # noqa: E402


def _texts(fig) -> str:
    return " ".join(t.get_text() for t in fig.findobj(match=matplotlib.text.Text))


def test_the_caveat_describes_the_window_that_was_drawn():
    """A district window is the district's size, whatever radius was asked."""
    site = SiteMetadata(community="Kuntoloh", district="Port Loko")
    window = area_window(site, 40.0)
    assert window is not None and not window.exact
    assert window.radius_km != 40.0
    fig = plot_geological_map(site=site, radius_km=40.0)
    text = _texts(fig)
    plt.close(fig)
    assert f"{2 * window.radius_km:g} km window" in text or "km window" not in text
    assert "80 km window" not in text


def test_a_polygon_is_named_for_where_it_is_not_for_the_site():
    """The Freetown Complex is the Freetown Complex on a Kuntolo map too."""
    freetown = next(u for u in load_geology() if u.glg == "Pi")
    assert _unit_district(freetown).startswith("Western Area")
    fig = plot_geological_map(
        site=SiteMetadata(community="Kuntoloh", district="Port Loko",
                          easting=727012, northing=916125, utm_zone=28),
        radius_km=60.0,
    )
    text = _texts(fig)
    plt.close(fig)
    assert "Freetown Layered Complex" in text
    assert "Paleozoic Igneous (Pi)" not in text      # the age the crosswalk calls wrong
    # and the Precambrian polygon over the coastal plain says what it spans
    assert "Rokel River Group belt" in text


def test_chiefdom_names_are_printed_in_full():
    areas = {a.name: a for a in load_chiefdoms()}
    assert areas["Sanda Magbolont"].label == "Sanda Magbolontor"
    assert areas["Bureh Kasseh Ma"].label == "Bureh Kasseh Maconteh"
    assert areas["Kaffu Bullom"].label == "Kaffu Bullom"
    assert canonical_chiefdom("Sanda Magbolontor") == "Sanda Magbolont"
    assert canonical_chiefdom("sanda magbolont") == "Sanda Magbolont"
    assert canonical_chiefdom("Kaffu Bullom") == "Kaffu Bullom"
    # an operator typing the full name gets the chiefdom window
    window = area_window(SiteMetadata(chiefdom="Sanda Magbolontor", district="Karene"))
    assert window is not None and window.label == "Sanda Magbolontor chiefdom"
    # and a point in it is told the full name
    lon, lat = areas["Sanda Magbolont"].label_point
    name, district = chiefdom_of(lat, lon)
    assert name == "Sanda Magbolontor" and district == "Karene"


def test_the_land_across_the_border_is_land():
    outline, _ = load_admin()
    fig, ax = plt.subplots()
    ax.set_xlim(-14.0, -9.5)
    ax.set_ylim(6.5, 10.5)
    rings = foreign_land_rings((-14.0, 6.5, -9.5, 10.5))
    assert rings
    carto.sea_and_neighbours(ax, outline.rings, carto.LAND, foreign_rings=rings)
    faces = {p.get_facecolor()[:3] for p in ax.patches}
    to_rgb = lambda h: tuple(int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))  # noqa: E731
    assert any(np.allclose(f, to_rgb(carto.FOREIGN_LAND), atol=0.01) for f in faces)
    plt.close(fig)


def test_graticule_ticks_stay_inside_the_frame():
    fig, ax = plt.subplots()
    ax.set_xlim(-13.37, -12.13)
    ax.set_ylim(8.11, 9.29)
    carto.graticule(ax)
    assert ax.get_xlim() == (-13.37, -12.13)
    assert ax.get_ylim() == (8.11, 9.29)
    assert all(-13.37 <= x <= -12.13 for x in ax.get_xticks())
    assert 3 <= len(ax.get_xticks()) <= 7          # not thirteen at 0.1 degree
    plt.close(fig)


def test_the_tints_survive_a_photocopy():
    tones = dict(carto.GEOLOGY_COLOURS, sea=carto.SEA, paper=carto.LAND,
                 unmapped=carto.NOT_MAPPED)
    keys = list(tones)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            gap = abs(carto.relative_luminance(tones[a]) - carto.relative_luminance(tones[b]))
            assert gap >= 0.05, (a, b, gap)


def test_the_declutter_keeps_names_off_the_site_and_inside_the_frame():
    extent = (0.0, 0.0, 10.0, 10.0)
    kept = carto.declutter([(5.0, 5.0, "Home"), (5.0, 9.9, "Top")], extent,
                           reserved=[(4.5, 4.5, 5.5, 5.5)])
    assert [k[2] for k in kept] == []            # Home is on the star, Top runs off the frame
    kept = carto.declutter([(5.0, 5.0, "Home"), (5.0, 8.0, "Up")], extent)
    assert [k[2] for k in kept] == ["Home", "Up"]


def test_the_location_map_highlights_the_district_the_position_resolves_to():
    _, districts = load_admin()
    name, names, chiefdoms = _home_district(
        SiteMetadata(community="Rokel", district="Western Area",
                     easting=708958, northing=926355, utm_zone=28), districts)
    assert name == "Western Area Rural" and names == {"western area rural"}
    name, names, chiefdoms = _home_district(SiteMetadata(district="Western Area"), districts)
    assert names == {"western area urban", "western area rural"}
    name, names, chiefdoms = _home_district(SiteMetadata(district="Karene"), districts)
    assert name == "Karene" and not names and len(chiefdoms) >= 5
    fig = plot_admin_map(SiteMetadata(community="Kamakwie", district="Karene"))
    assert "Karene District" in _texts(fig)
    plt.close(fig)


def test_the_study_area_is_drawn_at_the_scale_its_points_need():
    site = SiteMetadata(easting=708958, northing=926355, utm_zone=28)
    assert study_area_radius_km(site, []) == 10.0
    far = [{"lat": 8.2826, "lon": -12.9390}, {"lat": 8.3759, "lon": -13.1024}]
    radius = study_area_radius_km(site, far)
    # B (2) is 20.7 km from the site the map is centred on: it has to fit
    assert 26.0 < radius < 30.0
    assert study_area_radius_km(site, far, ceiling_km=12.0) == 12.0
