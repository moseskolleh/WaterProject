"""The GeoLibre project file: what it must contain, and what it must not.

A project file is made to be handed to somebody - a client, a ministry, a
donor - and opened somewhere this toolkit is not running. So the tests
here are less about the schema than about the promises that travel with
it: that re-running produces the same bytes, that a CC BY-SA layer cannot
leave without its credit, that an unreported water point is not painted
green, and that nothing that reads like a credential can be written into
a file whose whole purpose is to be shared.
"""

import json
from pathlib import Path

import pytest

from groundwater.mapping import geolibre
from groundwater.mapping.geolibre import (
    area_features,
    build_project,
    data_link,
    geojson_layer,
    portfolio_features,
    portfolio_project,
    project_link,
    site_project,
    suitability_features,
    survey_point_features,
    unit_features,
    water_point_features,
    write_project,
)
from groundwater.mapping.maps import MapPoint
from groundwater.models import SiteMetadata
from groundwater.siting.suitability import SitingSuitability, SuitabilityComponents
from groundwater.waterpoints import WaterPoint

ZONE = 28


def _points():
    return [
        MapPoint("VES-1", 700000.0, 950000.0, value=180.0, kind="VES point"),
        MapPoint("VES-2", 700400.0, 950300.0, value=95.0, kind="VES point"),
    ]


def _site():
    return SiteMetadata(
        community="Rokel",
        chiefdom="Koya",
        district="Port Loko",
        client="SALWACO",
        easting=700000.0,
        northing=950000.0,
        utm_zone=ZONE,
    )


def _water_points():
    return [
        WaterPoint("a", 8.586, -12.99, True, "Functional", "Borehole",
                   "Hand Pump - India Mark II", 2011, "Port Loko",
                   distance_m=210.0, report_year=2016),
        WaterPoint("b", 8.587, -12.98, False, "Non-Functional", "Borehole",
                   "Hand Pump", 2009, "Port Loko", distance_m=640.0),
        WaterPoint("c", 8.588, -12.97, None, "", "Protected Spring", "",
                   None, "Port Loko"),
    ]


def _suitability():
    components = SuitabilityComponents(0.8, 0.7, 0.9, 1.0)
    return [
        SitingSuitability("VES-1", 82.0, "Very good", components, "thick zone",
                          easting=700000.0, northing=950000.0, rank=1),
        SitingSuitability("VES-2", 30.0, "Poor", components, "thin zone",
                          easting=700400.0, northing=950300.0, rank=2),
        # no position: a table row, not a map feature
        SitingSuitability("VES-3", 50.0, "Moderate", components, "unknown"),
    ]


# --------------------------------------------------------------- geometry


def test_survey_points_unproject_to_the_site_position():
    """A projected MapPoint lands where the site's own lat/lon says it does."""
    features = survey_point_features(_points()[:1], ZONE)
    lon, lat = features[0]["geometry"]["coordinates"]
    expected_lat, expected_lon = _site().latlon
    assert lon == pytest.approx(expected_lon, abs=1e-6)
    assert lat == pytest.approx(expected_lat, abs=1e-6)
    assert features[0]["properties"]["utm_zone"] == "28N"


def test_rings_are_closed_even_when_the_source_is_not():
    """GeoJSON requires a closed ring; the bundled data does not always close."""

    class Area:
        level, name, district = "ADM3", "Koya", "Port Loko"
        rings = [[(-13.0, 8.5), (-12.9, 8.5), (-12.9, 8.6)]]
        holes = [[]]

    ring = area_features([Area()])[0]["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    assert len(ring) == 4


def test_enclaves_survive_as_interior_rings():
    """Nongowa encloses Kenema Town: drop the hole and the town disappears."""

    class Area:
        level, name, district = "ADM3", "Nongowa", "Kenema"
        rings = [[(-11.3, 7.8), (-11.1, 7.8), (-11.1, 8.0), (-11.3, 8.0)]]
        holes = [[[(-11.25, 7.85), (-11.2, 7.85), (-11.2, 7.9), (-11.25, 7.9)]]]

    coordinates = area_features([Area()])[0]["geometry"]["coordinates"]
    assert len(coordinates) == 2, "the interior ring was dropped"


def test_multipart_areas_become_multipolygons():
    class Area:
        level, name, district = "ADM2", "Western Area", ""
        rings = [
            [(-13.3, 8.4), (-13.2, 8.4), (-13.2, 8.5)],
            [(-13.1, 8.4), (-13.0, 8.4), (-13.0, 8.5)],
        ]
        holes = [[], []]

    assert area_features([Area()])[0]["geometry"]["type"] == "MultiPolygon"


# ------------------------------------------------------------------ colour


def test_an_unreported_water_point_is_grey_not_green():
    """Absence of bad news is not good news - the registry's rule, on a map."""
    features = water_point_features(_water_points())
    by_status = {f["properties"]["status"]: f["properties"] for f in features}
    assert by_status["Functional"]["marker-color"] == "#2E7D5B"
    assert by_status["Non-functional"]["marker-color"] == "#B23A2E"
    assert by_status["Unknown"]["marker-color"] == "#6B7785"


def test_suitability_without_a_position_is_not_mapped():
    features = suitability_features(_suitability(), ZONE)
    assert [f["properties"]["sounding"] for f in features] == ["VES-1", "VES-2"]
    assert features[0]["properties"]["marker-color"] == "#1A9850"  # Very good
    assert features[1]["properties"]["marker-color"] == "#D73027"  # Poor


def test_portfolio_status_colours_match_the_printed_map():
    from groundwater.site_status import STATUS_COLORS

    points = [
        {"label": "A", "lat": 8.5, "lon": -13.0, "status": "successful"},
        {"label": "B", "lat": 8.6, "lon": -12.9, "status": "dry"},
        {"label": "C", "lat": 8.7, "lon": -12.8, "status": "nonsense"},
    ]
    features = portfolio_features(points)
    colours = [f["properties"]["marker-color"] for f in features]
    assert colours == [
        STATUS_COLORS["successful"],
        STATUS_COLORS["dry"],
        STATUS_COLORS["other"],  # unrecognised is grey, never guessed at
    ]


# ------------------------------------------------------------- the project


def test_the_project_frames_what_it_contains():
    project = site_project(site=_site(), survey_points=_points(), zone=ZONE)
    view = project["mapView"]
    lat, lon = _site().latlon
    assert view["center"][0] == pytest.approx(lon, abs=0.01)
    assert view["center"][1] == pytest.approx(lat, abs=0.01)
    assert 10 < view["zoom"] <= 20, "a 400 m survey should not open at country scale"
    west, south, east, north = view["bbox"]
    assert west <= lon <= east and south <= lat <= north


def test_an_empty_project_falls_back_to_the_country():
    project = build_project("nothing", [])
    assert project["layers"] == []
    assert project["mapView"]["zoom"] == pytest.approx(7.0)
    assert "bbox" not in project["mapView"]


def test_empty_layers_are_dropped_rather_than_written():
    """A legend entry for an empty layer claims something was found."""
    project = build_project(
        "p", [geojson_layer("Empty", []), geojson_layer("Full", [
            {"type": "Feature", "geometry": {"type": "Point",
                                             "coordinates": [-13.0, 8.5]},
             "properties": {}}])])
    assert [layer["name"] for layer in project["layers"]] == ["Full"]


def test_layers_are_ordered_context_first_site_last():
    project = site_project(
        site=_site(),
        zone=ZONE,
        survey_points=_points(),
        suitability=_suitability(),
        water_points=_water_points(),
        hydrogeology=[],
    )
    names = [layer["name"] for layer in project["layers"]]
    assert names.index("Existing water points") < names.index("Survey points")
    assert names[-1] == "Site", "the site must draw on top of its own context"


def test_duplicate_layer_names_get_distinct_ids():
    feature = {"type": "Feature",
               "geometry": {"type": "Point", "coordinates": [-13.0, 8.5]},
               "properties": {}}
    project = build_project(
        "p", [geojson_layer("Sites", [feature]), geojson_layer("Sites", [feature])]
    )
    ids = [layer["id"] for layer in project["layers"]]
    assert len(set(ids)) == 2, ids
    assert set(project["styles"]) == set(ids)


def test_styles_are_keyed_by_layer_id():
    project = site_project(site=_site(), survey_points=_points(), zone=ZONE)
    for layer in project["layers"]:
        assert project["styles"][layer["id"]] is layer["style"]


def test_projected_inputs_without_a_zone_are_refused():
    """Guessing a zone puts half the country in the Atlantic."""
    with pytest.raises(ValueError, match="zone"):
        site_project(survey_points=_points())


# ------------------------------------------------------- promises it keeps


def test_the_same_data_writes_the_same_bytes(tmp_path):
    """Re-running on the same raw data produces byte-identical output."""
    first = write_project(
        site_project(site=_site(), survey_points=_points(), zone=ZONE),
        tmp_path / "a.geolibre.json",
    )
    second = write_project(
        site_project(site=_site(), survey_points=_points(), zone=ZONE),
        tmp_path / "b.geolibre.json",
    )
    assert first.read_bytes() == second.read_bytes()
    assert first.read_text(encoding="utf-8").endswith("}\n")


def test_layer_ids_are_stable_slugs_not_random_uuids():
    ids = {
        layer["name"]: layer["id"]
        for layer in site_project(
            site=_site(), survey_points=_points(), zone=ZONE
        )["layers"]
    }
    assert ids["Survey points"] == "survey-points"
    assert ids["Site"] == "site"


def test_every_licensed_layer_carries_its_own_credit():
    from groundwater.mapping.regional import ADMIN_CREDIT, HYDRO_CREDIT
    from groundwater.waterpoints import WPDX_CREDIT

    class Unit:
        glg, unit, era, color = "B-L", "low productivity", "basement", "#AACCEE"
        ring = [(-13.0, 8.5), (-12.9, 8.5), (-12.9, 8.6)]

    class Area:
        level, name, district = "ADM3", "Koya", "Port Loko"
        rings = [[(-13.0, 8.5), (-12.9, 8.5), (-12.9, 8.6)]]
        holes = [[]]

    project = site_project(
        site=_site(),
        zone=ZONE,
        water_points=_water_points(),
        chiefdoms=[Area()],
        hydrogeology=[Unit()],
    )
    credits = project["metadata"]["attribution"]
    # the ShareAlike layer above all: inlining it carries the obligation
    assert HYDRO_CREDIT in credits
    assert ADMIN_CREDIT in credits
    assert WPDX_CREDIT in credits
    by_name = {layer["name"]: layer for layer in project["layers"]}
    assert by_name["Aquifer productivity"]["metadata"]["attribution"] == HYDRO_CREDIT


def test_a_credential_cannot_be_written_into_a_shared_file():
    for key in ("api_key", "ANTHROPIC_API_KEY", "token", "password"):
        with pytest.raises(ValueError, match="credential"):
            build_project("p", [], metadata={key: "sk-secret"})


def test_no_basemap_is_requested_by_default():
    """The file must not make the app's first unannounced network call."""
    project = build_project("p", [])
    assert project["basemapStyleUrl"] == ""
    assert project["basemapVisible"] is False


def test_the_written_file_is_valid_json_of_the_declared_version(tmp_path):
    path = write_project(
        portfolio_project(
            [{"label": "A", "lat": 8.5, "lon": -13.0, "status": "successful"}]
        ),
        tmp_path / "portfolio.geolibre.json",
    )
    project = json.loads(path.read_text(encoding="utf-8"))
    assert project["version"] == geolibre.PROJECT_FORMAT_VERSION
    assert project["layers"][0]["type"] == "geojson"
    assert project["layers"][0]["source"] == {"type": "geojson"}
    assert project["legend"]["groupByLayer"] is True


def test_geology_units_keep_their_datasets_own_colours():
    class Unit:
        glg, unit, era, color = "pCm", "Precambrian", "Precambrian", "#E8B54D"
        ring = [(-13.0, 8.5), (-12.9, 8.5), (-12.9, 8.6)]

    assert unit_features([Unit()])[0]["properties"]["fill"] == "#E8B54D"


# ----------------------------------------------------------------- links


def test_links_carry_the_url_and_the_options():
    assert project_link("https://x/p.geolibre.json") == (
        "https://web.geolibre.app/?url=https://x/p.geolibre.json"
    )
    viewer = project_link("https://x/p.json", viewer=True, theme="dark")
    assert "layout=viewer" in viewer and "theme=dark" in viewer
    assert data_link("https://x/a.geojson", style_url="https://x/s.json") == (
        "https://web.geolibre.app/?data=https://x/a.geojson&style=https://x/s.json"
    )


def test_a_self_hosted_deployment_can_be_pointed_at():
    link = project_link("https://x/p.json", app="https://gis.example.org/")
    assert link.startswith("https://gis.example.org/?url=")


# ---------------------------------------------------- framing and windowing


class _Unit:
    """A geology/aquifer polygon, positioned by the caller."""

    def __init__(self, west, south, east, north, color="#AACCEE"):
        self.glg, self.unit, self.era, self.color = "u", "unit", "class", color
        self.ring = [(west, south), (east, south), (east, north), (west, north)]


def test_the_camera_opens_on_the_survey_not_on_the_country():
    """The geology layer covers Sierra Leone. Opening on it loses the survey."""
    country = _Unit(-13.5, 6.9, -10.2, 10.0)
    project = site_project(
        site=_site(), zone=ZONE, survey_points=_points(), geology=[country]
    )
    lat, lon = _site().latlon
    assert project["mapView"]["center"][0] == pytest.approx(lon, abs=0.01)
    assert project["mapView"]["zoom"] > 14, (
        "a 400 m survey framed at country zoom is three pixels"
    )
    # the context layer is still there to zoom out to
    assert "Geology" in [layer["name"] for layer in project["layers"]]


def test_framing_falls_back_when_no_focal_layer_has_features():
    """A project written before any fieldwork still frames on what it has."""
    project = site_project(geology=[_Unit(-13.5, 6.9, -10.2, 10.0)])
    assert project["mapView"]["zoom"] < 10
    assert project["mapView"]["bbox"][0] == pytest.approx(-13.5)


def test_a_single_point_is_not_framed_at_maximum_zoom():
    project = build_project(
        "one",
        [geojson_layer("Site", [{"type": "Feature",
                                 "geometry": {"type": "Point",
                                              "coordinates": [-13.0, 8.5]},
                                 "properties": {}}])],
    )
    assert project["mapView"]["zoom"] < 18, "a point has no extent to fill"
    west, south, east, north = project["mapView"]["bbox"]
    assert east > west and north > south


def test_a_window_keeps_the_ground_around_the_site_and_drops_the_rest():
    near = _Unit(-13.3, 8.5, -13.1, 8.7)
    far = _Unit(-11.0, 7.0, -10.8, 7.2)
    project = site_project(
        site=_site(), zone=ZONE, geology=[near, far], window_km=40
    )
    geology = [l for l in project["layers"] if l["name"] == "Geology"][0]
    assert len(geology["geojson"]["features"]) == 1, "the far unit was kept"


def test_an_overlapping_polygon_is_kept_whole_not_clipped():
    """A bounding-box test, not a clip: nothing is invented at the edge."""
    from groundwater.mapping.geolibre import features_within, window_around

    wide = unit_features([_Unit(-14.0, 6.0, -10.0, 11.0)])
    kept = features_within(wide, window_around(8.59, -13.18, 40))
    assert len(kept) == 1
    assert kept[0]["geometry"]["coordinates"] == wide[0]["geometry"]["coordinates"]


def test_a_window_needs_a_position_to_be_centred_on():
    """Without coordinates there is no window, so nothing is filtered away."""
    project = site_project(
        geology=[_Unit(-11.0, 7.0, -10.8, 7.2)], window_km=5
    )
    assert len(project["layers"][0]["geojson"]["features"]) == 1


def test_window_around_narrows_with_latitude():
    from groundwater.mapping.geolibre import window_around

    west, south, east, north = window_around(8.59, -13.18, 40.0)
    assert (north - south) == pytest.approx(2 * 40.0 / 111.32, rel=1e-6)
    assert (east - west) > (north - south), "a degree of longitude is shorter here"


# ------------------------------------------------- the two apps must agree

# The standalone web app carries its own port of this module. The toolkit's
# rule is that the browser engine is held to the package's numbers, so the
# port is held to this module's output: same inputs, same project. The check
# runs the browser file in node rather than in a real browser, because the
# builder touches no DOM - it is data in, JSON out.
#
# Only the computed layers are compared. The bundled boundary, geology and
# aquifer layers are deliberately *not*: the web app ships its own copy of
# those datasets rounded to five decimal places to keep the download down,
# and the package reads the unrounded source. That difference is a decision
# recorded in web/build_webapp_data.py, not drift.

_JS_DRIVER = r"""
import { readFileSync, writeFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
for (const f of ['support.js', 'gwt-data.js', 'gwt-core.js', 'gwt-geolibre.js']) {
  vm.runInContext(readFileSync(process.argv[2] + '/' + f, 'utf8'), sandbox,
    { filename: f });
}
const G = sandbox.GWT.geolibre;
const input = JSON.parse(readFileSync(process.argv[3], 'utf8'));
const project = G.siteProject(input.site);
const wanted = ['Site', 'Drill-target suitability', 'Existing water points',
  'Sanitary protection zones'];
const computed = {};
for (const layer of project.layers) {
  if (wanted.includes(layer.name)) computed[layer.name] = layer;
}
writeFileSync(process.argv[4], JSON.stringify({
  mapView: project.mapView,
  computed,
  portfolio: G.portfolioProject(input.portfolio),
  slug: G.slug('Drill-target suitability'),
  version: G.PROJECT_FORMAT_VERSION,
  webApp: G.WEB_APP,
  links: input.links.map((l) => (l.kind === 'data'
    ? G.dataLink(l.url, l.options)
    : G.projectLink(l.url, l.options))),
  area: G.siteProject(input.area),
}, null, 2));
"""


def test_the_browser_builder_agrees_with_this_one(tmp_path):
    """The standalone app's port must write the same project this does."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")

    repo = Path(__file__).resolve().parents[1]
    site = _site()
    lat, lon = site.latlon
    portfolio = [
        {"label": "Rokel", "lat": 8.586, "lon": -12.99, "status": "successful"},
        {"label": "Kuntolo", "lat": 8.9, "lon": -11.9, "status": "dry"},
    ]
    water = _water_points()
    payload = {
        "site": {
            "community": site.community,
            "chiefdom": site.chiefdom,
            "district": site.district,
            "client": site.client,
            "lat": lat,
            "lon": lon,
            "zone": ZONE,
            "suitability": [
                {
                    "sounding_id": s.sounding_id,
                    "suitability": s.suitability,
                    "grade": s.grade,
                    "rationale": s.rationale,
                    "easting": s.easting,
                    "northing": s.northing,
                    "rank": s.rank,
                }
                for s in _suitability()
            ],
            "waterPoints": [
                {
                    "lat": w.lat,
                    "lon": w.lon,
                    "functional": w.functional,
                    "status_text": w.status,
                    "source": w.source,
                    "technology": w.technology,
                    "improved": w.improved,
                    "installed": w.install_year,
                    "report_year": w.report_year,
                    "months_per_year": w.months_per_year,
                    "distance_m": w.distance_m,
                }
                for w in water
            ],
        },
        "portfolio": portfolio,
        "links": _LINK_CASES,
        # The same area handed to both sides. The two *resolvers* -
        # regional.area_window here, areaWindow in the app - are separate
        # implementations over data rounded differently, so they can place a
        # chiefdom a little differently. That is theirs to agree on; what has
        # to match is what each builder does once given the same answer.
        "area": {"community": "Rokel", "chiefdom": "Koya",
                 "district": "Port Loko",
                 "area": {"lon": -13.05, "lat": 8.62, "radiusKm": 22.0,
                          "label": "Koya chiefdom", "exact": False}},
    }
    (tmp_path / "input.json").write_text(json.dumps(payload), encoding="utf-8")
    driver = tmp_path / "driver.mjs"
    driver.write_text(_JS_DRIVER, encoding="utf-8")
    out = tmp_path / "out.json"
    result = subprocess.run(
        [node, str(driver), str(repo / "docs" / "js"),
         str(tmp_path / "input.json"), str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    js = json.loads(out.read_text(encoding="utf-8"))

    mine = site_project(
        site=site,
        zone=ZONE,
        suitability=_suitability(),
        water_points=water,
    )
    assert js["version"] == geolibre.PROJECT_FORMAT_VERSION
    assert js["webApp"] == geolibre.GEOLIBRE_WEB_APP
    assert js["slug"] == "drill-target-suitability"
    assert js["mapView"] == mine["mapView"]

    by_name = {layer["name"]: layer for layer in mine["layers"]}
    for name in ("Site", "Drill-target suitability", "Existing water points",
                 "Sanitary protection zones"):
        assert js["computed"][name] == by_name[name], f"{name} differs"

    assert js["portfolio"] == portfolio_project(portfolio)
    assert js["links"] == [_python_link(case) for case in _LINK_CASES]

    # given the same area, both builders must frame it the same way, mark no
    # position, and say the same thing about why
    from groundwater.mapping.regional import AreaWindow

    mine_area = site_project(
        site=SiteMetadata(community="Rokel", chiefdom="Koya",
                          district="Port Loko"),
        area=AreaWindow(-13.05, 8.62, 22.0, "Koya chiefdom", False),
    )
    assert js["area"]["mapView"] == mine_area["mapView"]
    assert js["area"]["metadata"] == mine_area["metadata"]
    assert js["area"]["name"] == mine_area["name"]
    assert "Site" not in [layer["name"] for layer in js["area"]["layers"]]


# The link cases both builders are checked against. A signed URL is the one
# that matters: its own query string has to survive being carried inside
# another one.
_LINK_CASES = [
    {"kind": "project", "url": "https://x/p.geolibre.json", "options": {}},
    {"kind": "project", "url": "https://x/p.json?sig=a&expires=1", "options": {}},
    {"kind": "project", "url": "https://x/p.json",
     "options": {"viewer": True, "theme": "dark"}},
    {"kind": "project", "url": "https://x/p.json", "options": {"maponly": True}},
    {"kind": "data", "url": "https://x/a b.geojson",
     "options": {"styleUrl": "https://x/s.json?v=2"}},
]


def _python_link(case):
    options = case["options"]
    if case["kind"] == "data":
        return data_link(case["url"], style_url=options.get("styleUrl"))
    return project_link(
        case["url"],
        viewer=options.get("viewer", False),
        theme=options.get("theme"),
        maponly=options.get("maponly", False),
    )


# ------------------------------------------------ what the review found


def test_a_national_inventory_cannot_ride_into_a_site_project():
    """The web app's coverage page fetches up to 200,000 points into the same
    place the site page reads them from. They are one of the layers the camera
    frames on, so letting them through would not merely make the file large -
    it would open the project on Sierra Leone with the survey lost inside it.
    """
    near = WaterPoint("near", 8.59, -13.18, True, "Functional", "Borehole",
                      "Hand Pump", 2011, "Port Loko")
    far = WaterPoint("far", 7.95, -11.20, True, "Functional", "Borehole",
                     "Hand Pump", 2011, "Kenema")
    project = site_project(
        site=_site(), zone=ZONE, water_points=[near, far], window_km=40
    )
    layer = [l for l in project["layers"] if l["name"] == "Existing water points"][0]
    assert len(layer["geojson"]["features"]) == 1, "the far point was embedded"
    # and the camera still opens on the survey, not on the country
    assert project["mapView"]["zoom"] > 11


def test_without_a_window_every_water_point_is_kept():
    """The filter is a guard against a national pull, not a silent trim."""
    points = _water_points()
    project = site_project(site=_site(), zone=ZONE, water_points=points)
    layer = [l for l in project["layers"] if l["name"] == "Existing water points"][0]
    assert len(layer["geojson"]["features"]) == len(points)


def test_a_signed_url_survives_being_carried_inside_another_one():
    """A published project URL is itself a URL. Its own query string has to be
    encoded, or the outer query swallows it: ``?sig=a&expires=1`` would hand
    GeoLibre an ``expires`` parameter of its own and truncate the address.
    """
    link = project_link("https://x/p.json?sig=a&expires=1")
    assert link == "https://web.geolibre.app/?url=https://x/p.json%3Fsig%3Da%26expires%3D1"
    # exactly one parameter reaches GeoLibre, and it is the whole URL
    from urllib.parse import parse_qs, urlparse

    query = parse_qs(urlparse(link).query)
    assert list(query) == ["url"]
    assert query["url"] == ["https://x/p.json?sig=a&expires=1"]


def test_a_valueless_parameter_is_written_bare():
    """The GeoLibre documentation writes ``&maponly``, not ``&maponly=``."""
    link = project_link("https://x/p.json", maponly=True)
    assert link.endswith("&maponly")


def test_a_space_in_a_url_is_encoded():
    assert data_link("https://x/a b.geojson") == (
        "https://web.geolibre.app/?data=https://x/a%20b.geojson"
    )


def test_a_credential_nested_in_metadata_is_refused():
    """A guard that reads only the top level waves the file through anyway."""
    with pytest.raises(ValueError, match="credential"):
        build_project("p", [], metadata={"service": {"api_key": "sk-secret"}})
    with pytest.raises(ValueError, match="credential"):
        build_project("p", [], metadata={"services": [{"auth_token": "x"}]})


def test_a_credential_in_a_layer_is_refused():
    feature = {"type": "Feature",
               "geometry": {"type": "Point", "coordinates": [-13.0, 8.5]},
               "properties": {}}
    layer = geojson_layer("Sites", [feature])
    layer["metadata"]["source"] = {"api_key": "sk-secret"}
    with pytest.raises(ValueError, match="credential"):
        build_project("p", [layer])


def test_writing_checks_again_because_that_is_where_the_file_appears(tmp_path):
    """A project assembled by hand never passed through the other check."""
    project = build_project("p", [])
    project["metadata"]["nested"] = {"access_token": "sk-secret"}
    with pytest.raises(ValueError, match="credential"):
        write_project(project, tmp_path / "leaky.geolibre.json")
    assert not (tmp_path / "leaky.geolibre.json").exists()


def test_the_error_says_where_the_credential_was_found():
    with pytest.raises(ValueError, match=r"project metadata\.service"):
        build_project("p", [], metadata={"service": {"api_key": "x"}})


# ------------------------------------------- a site with no GPS fix

def _no_fix(**kwargs):
    return SiteMetadata(community="Rokel", **kwargs)


def test_a_site_with_only_a_chiefdom_still_gets_a_project():
    """area_window resolves it to the chiefdom, and the map opens there."""
    project = site_project(site=_no_fix(chiefdom="Koya", district="Port Loko"))
    assert 9 < project["mapView"]["zoom"] < 13, "a chiefdom is not a country"
    assert "Koya chiefdom" in project["metadata"]["position"]


def test_a_site_with_only_a_district_falls_back_to_it():
    project = site_project(site=_no_fix(district="Port Loko"))
    assert "Port Loko district" in project["metadata"]["position"]
    assert project["mapView"]["zoom"] < 11


def test_a_centroid_is_never_drawn_as_a_position():
    """A dot at a chiefdom centroid is indistinguishable on screen from a
    surveyed wellhead, and a reader who cannot tell will measure from it.
    """
    project = site_project(
        site=_no_fix(chiefdom="Koya"), chiefdoms=[], geology=[]
    )
    assert "Site" not in [layer["name"] for layer in project["layers"]]


def test_the_file_says_the_centre_is_a_centroid():
    """Framing alone does not tell a reader opening this somewhere else."""
    project = site_project(site=_no_fix(chiefdom="Koya"))
    assert "not a surveyed position" in project["metadata"]["position"]
    assert project["metadata"]["area"] == "Koya chiefdom"


def test_a_gps_fix_is_still_a_position_and_still_gets_a_marker():
    project = site_project(site=_site(), zone=ZONE)
    assert "Site" in [layer["name"] for layer in project["layers"]]
    assert "position" not in project["metadata"], (
        "a real fix must not be labelled an area centroid"
    )


def test_a_site_with_nothing_to_locate_it_is_not_placed_anywhere():
    """No community-name geocoding: a name is not a position."""
    project = site_project(site=_no_fix())
    assert "position" not in project["metadata"]
    assert "area" not in project["metadata"]


def test_an_area_can_be_supplied_instead_of_resolved():
    from groundwater.mapping.regional import AreaWindow

    project = site_project(
        site=_no_fix(),
        area=AreaWindow(-11.0, 8.0, 25.0, "Somewhere chiefdom", False),
    )
    assert project["metadata"]["area"] == "Somewhere chiefdom"
    assert project["mapView"]["center"] == [-11.0, 8.0]


def test_the_project_is_named_for_the_area_when_the_site_is_unnamed():
    from groundwater.mapping.regional import AreaWindow

    project = site_project(
        site=SiteMetadata(district="Port Loko"),
        area=AreaWindow(-12.8, 8.8, 30.0, "Port Loko district", False),
    )
    assert project["name"] == "Port Loko district"


def test_an_area_is_honoured_with_no_site_at_all():
    """A supplied area used to be ignored unless a site came with it, which
    produced the one thing a project file must never do: metadata saying it
    was centred on an area while the camera sat on the country.
    """
    from groundwater.mapping.regional import AreaWindow, load_geology

    area = AreaWindow(-11.0, 8.0, 25.0, "Somewhere chiefdom", False)
    project = site_project(area=area, geology=load_geology())
    assert project["mapView"]["center"] == [-11.0, 8.0]
    assert project["mapView"]["zoom"] > 9, "not framed on the country"
    geology = [l for l in project["layers"] if l["name"] == "Geology"][0]
    assert len(geology["geojson"]["features"]) < 92, "context was not windowed"
    assert project["name"] == "Somewhere chiefdom"


def test_the_words_and_the_camera_never_disagree():
    """Whenever the metadata claims an area, the camera must be on it."""
    from groundwater.mapping.regional import AreaWindow

    area = AreaWindow(-12.0, 9.0, 30.0, "Karene district", False)
    for kwargs in (
        {"area": area},
        {"area": area, "site": SiteMetadata(community="Rokel")},
        {"area": area, "site": SiteMetadata(community="Rokel", district="Karene")},
    ):
        project = site_project(**kwargs)
        assert area.label in project["metadata"]["position"]
        assert project["mapView"]["center"] == [-12.0, 9.0], (
            "the file says one place and opens on another"
        )


def test_a_site_in_a_post_2017_district_can_be_exported():
    """Karene and Falaba are offered by both apps and have no polygon of
    their own in the bundled boundary release."""
    for district in ("Karene", "Falaba"):
        project = site_project(site=SiteMetadata(community="X", district=district))
        assert project["metadata"]["area"] == f"{district} district"
        assert project["mapView"]["zoom"] > 7.96, "framed on the country"


# ------------------------------------------- sanitary protection zones


def test_a_protection_ring_is_its_distance_on_the_ground():
    """20 m must be 20 m at this latitude, not 20 m at the equator."""
    import math

    from groundwater.geo import geographic_to_utm
    from groundwater.mapping.geolibre import protection_zone_features

    lat, lon = 8.59, -13.1827
    ring = [f for f in protection_zone_features(lat, lon)
            if f["properties"]["min_distance_m"] == 20][0]
    centre = geographic_to_utm(lat, lon)
    spread = []
    for point_lon, point_lat in ring["geometry"]["coordinates"][0]:
        utm = geographic_to_utm(point_lat, point_lon, centre.zone)
        spread.append(math.hypot(utm.easting - centre.easting,
                                 utm.northing - centre.northing))
    # the slack is the six-decimal coordinate rounding, about 0.11 m
    assert 19.8 < min(spread) and max(spread) < 20.2, (min(spread), max(spread))


def test_the_rings_are_drawn_widest_first():
    """A 1000 m ring drawn over a 3 m one hides it."""
    from groundwater.mapping.geolibre import protection_zone_features

    widths = [f["properties"]["min_distance_m"]
              for f in protection_zone_features(8.59, -13.1827)]
    assert widths == sorted(widths, reverse=True)
    assert widths[0] == 1000 and widths[-1] == 3


def test_every_separation_distance_is_drawn():
    from groundwater.mapping.geolibre import protection_zone_features
    from groundwater.supervision import load_separation_distances

    features = protection_zone_features(8.59, -13.1827)
    assert len(features) == len(load_separation_distances())
    assert {f["properties"]["structure"] for f in features} == {
        d.structure for d in load_separation_distances()
    }


def test_a_ring_says_what_it_means():
    """A circle on a map is not self-explanatory: it could as easily be
    read as the area the borehole serves."""
    from groundwater.mapping.geolibre import protection_zone_features

    latrine = [f for f in protection_zone_features(8.59, -13.1827)
               if "Septic" in f["properties"]["structure"]][0]
    assert "must be at least 20 m from the borehole" in latrine["properties"]["meaning"]
    assert "stay clear" in latrine["properties"]["meaning"]


def test_the_zones_are_drawn_but_do_not_decide_the_camera():
    """The two 1000 m rings would otherwise frame every site the same way."""
    project = site_project(site=_site(), zone=ZONE)
    assert "Sanitary protection zones" in [l["name"] for l in project["layers"]]
    assert project["mapView"]["zoom"] > 16, "the 1000 m rings took over the camera"


def test_a_site_with_no_fix_gets_no_rings():
    """A ring drawn round a chiefdom centroid would be a separation
    distance from a place nobody surveyed."""
    project = site_project(site=SiteMetadata(community="Rokel", chiefdom="Koya"))
    assert "Sanitary protection zones" not in [l["name"] for l in project["layers"]]


def test_the_zones_can_be_left_out():
    project = site_project(site=_site(), zone=ZONE, protection_zones=False)
    assert "Sanitary protection zones" not in [l["name"] for l in project["layers"]]
