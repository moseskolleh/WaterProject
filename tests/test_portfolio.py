"""Portfolio aggregation across many saved projects."""

from groundwater.mapping import plot_portfolio_map
from groundwater.portfolio import (
    classify_status,
    portfolio_points,
    portfolio_rows,
    portfolio_stats,
    site_detail,
    site_label,
    site_one_pager,
    verdict_state,
)

_SUMMARIES = [
    {
        "community": "Rokel", "district": "Port Loko",
        "easting": 694667.0, "northing": 936225.0, "utm_zone": 28,
        "status": "Successful", "total_depth_m": 50.0,
        "safe_yield_m3_per_h": 2.4, "water_verdict": "pass",
        "verdict_schema": 2,
        "cost_per_meter_usd": 130.0,
    },
    {
        "community": "Kuntolo", "district": "Tonkolili",
        "easting": 800000.0, "northing": 950000.0, "utm_zone": 28,
        "status": "Dry hole", "total_depth_m": 45.0,
    },
    {
        "community": "Dr Timbo", "district": "Bombali",
        "easting": 825127.0, "northing": 983069.0, "utm_zone": 28,
        "status": "sited", "safe_yield_m3_per_h": 1.0,
    },
]


def test_classify_status_returns_a_plain_serialisable_string():
    """Not an enum member: a project file, a map layer and a YAML dump all
    have to be able to carry it, and safe_dump cannot represent an enum."""
    import yaml

    status = classify_status({"status": "Successful"})
    assert type(status) is str
    assert yaml.safe_dump({"status": status})


def test_classify_status():
    assert classify_status({"status": "Successful"}) == "successful"
    assert classify_status({"status": "Dry hole"}) == "dry"
    assert classify_status({"status": "sited"}) == "sited"
    assert classify_status({"status": "", "total_depth_m": 40}) == "sited"
    assert classify_status({}) == "other"


def test_a_completed_dry_hole_is_not_a_success():
    """"Completed" describes the works, not the outcome, and "unsuccessful"
    contains "success". Matching the positive words first reported failed
    boreholes as successful and inflated the programme success rate."""
    for status in (
        "Completed - dry",
        "Complete (abandoned)",
        "Drilling complete, no water struck",
        "Unsuccessful",
        "Not successful",
    ):
        assert classify_status({"status": status}) == "dry", status
    # genuinely successful wording still classifies as such
    for status in ("Successful", "Completed and equipped", "Productive borehole"):
        assert classify_status({"status": status}) == "successful", status


def test_missing_utm_zone_infers_the_zone_consistently():
    """A hard-coded fallback zone put the site 6 degrees (~660 km) out.

    SiteMetadata assumed 28 and the portfolio assumed 29, so the same
    zone-less project resolved to two different continents' worth of
    longitude and dropped off the portfolio map.
    """
    from groundwater.models import SiteMetadata
    from groundwater.portfolio import _latlon

    for easting, northing in [(694667.0, 936225.0), (300000.0, 950000.0)]:
        site = SiteMetadata(community="X", easting=easting, northing=northing)
        assert site.latlon == _latlon({"easting": easting, "northing": northing})
        lat, lon = site.latlon
        assert 6.5 < lat < 10.5 and -13.5 < lon < -10.0


def test_portfolio_rows():
    rows = portfolio_rows(_SUMMARIES)
    assert len(rows) == 3
    rokel = rows[0]
    assert rokel["Community"] == "Rokel" and rokel["Status"] == "Successful"
    assert rokel["Water"] == "Safe" and rokel["Cost/m (USD)"] == 130


def test_portfolio_points_have_coordinates():
    points = portfolio_points(_SUMMARIES)
    assert len(points) == 3
    statuses = {p["status"] for p in points}
    assert statuses == {"successful", "dry", "sited"}
    # coordinates are in Sierra Leone's rough lat/lon window
    for p in points:
        assert 6.5 < p["lat"] < 10.5 and -13.5 < p["lon"] < -10.0


def test_portfolio_stats():
    stats = portfolio_stats(_SUMMARIES)
    assert stats["n_projects"] == 3
    assert stats["n_drilled"] == 2  # Rokel + Kuntolo have a depth
    assert stats["n_successful"] == 1
    assert stats["success_rate"] == 50.0  # 1 of 2 drilled
    assert stats["n_wq_assessed"] == 1
    assert stats["wq_compliant_rate"] == 100.0  # the one tested source is safe
    assert stats["wq_fail_rate"] == 0.0
    assert stats["wq_unproven_rate"] == 0.0
    assert stats["wq_counts"]["pass"] == 1
    assert abs(stats["mean_cost_per_meter_usd"] - 130.0) < 1e-6


def test_a_national_failure_is_never_counted_as_a_passing_supply():
    """The old single pass rate counted "aesthetic" as safe, and the
    aesthetic bucket held national-standard failures. A portfolio breaching
    the national standard at every site reported 100% passing."""
    summaries = [
        {"community": "A", "water_verdict": "national_fail", "verdict_schema": 2},
        {"community": "B", "water_verdict": "indeterminate", "verdict_schema": 2},
        {"community": "C", "water_verdict": "aesthetic", "verdict_schema": 2},
        {"community": "D", "water_verdict": "health_fail", "verdict_schema": 2},
    ]
    stats = portfolio_stats(summaries)
    assert stats["n_wq_assessed"] == 4
    assert stats["wq_fail_rate"] == 50.0        # national + health
    assert stats["wq_unproven_rate"] == 25.0
    assert stats["wq_compliant_rate"] == 25.0   # the aesthetic one only
    assert "wq_pass_rate" not in stats          # deliberately removed


def test_a_legacy_aesthetic_verdict_is_read_as_unproven():
    """A pre-schema "aesthetic" was written by code whose aesthetic bucket
    also held national exceedances, so it may hide a compliance failure and
    must not be shown as merely a matter of taste."""
    assert verdict_state({"water_verdict": "aesthetic"}) == ("indeterminate", True)
    assert verdict_state({"water_verdict": "fail"}) == ("health_fail", True)
    assert verdict_state({"water_verdict": "pass"}) == ("pass", True)
    assert verdict_state({}) == (None, False)
    # a current file is taken at face value
    assert verdict_state(
        {"water_verdict": "aesthetic", "verdict_schema": 2}
    ) == ("aesthetic", False)


def test_an_unfinished_or_unproductive_hole_is_not_a_success():
    """Substring matching read "incomplete" and "unproductive" as successes,
    inflating every programme's reported success rate."""
    for status in ("incomplete", "Incomplete - rig broke down", "not completed",
                   "Uncompleted", "partially complete"):
        assert classify_status({"status": status}) == "in_progress", status
    for status in ("unproductive", "Unproductive", "non-productive",
                   "low productivity"):
        assert classify_status({"status": status}) == "dry", status
    # a status nobody can read is never anything positive
    assert classify_status({"status": "qwerty"}) == "other"
    # a bare "sit" substring no longer counts as a siting
    for status in ("visited", "deposit sampled", "in transit"):
        assert classify_status({"status": status}) == "other", status


def test_portfolio_map_renders(tmp_path):
    out = plot_portfolio_map(portfolio_points(_SUMMARIES), path=tmp_path / "portfolio.png")
    assert out.exists() and out.stat().st_size > 0


def test_points_without_coordinates_are_dropped():
    assert portfolio_points([{"community": "No GPS", "status": "sited"}]) == []


def test_site_label():
    assert site_label(_SUMMARIES[0]) == "Rokel (Port Loko)"
    assert site_label({"community": "Foo"}) == "Foo"
    assert site_label({}) == "(unnamed site)"
    # an index prefix keeps otherwise-identical labels unambiguous
    assert site_label(_SUMMARIES[0], index=2) == "3. Rokel (Port Loko)"


def test_site_detail_present_fields_only():
    detail = dict(site_detail(_SUMMARIES[0]))
    assert detail["Community"] == "Rokel"
    assert detail["District"] == "Port Loko"
    assert detail["Status"] == "Successful"
    assert detail["Total depth"] == "50.0 m"
    assert detail["Safe yield"] == "2.40 m3/h"
    assert detail["Water quality"] == "Safe to drink"
    assert detail["Cost per metre"] == "$130"
    assert "N," in detail["Location"] and "W" in detail["Location"]
    # a sparse site omits absent fields rather than showing blanks
    sparse = dict(site_detail({"community": "No GPS", "status": "sited"}))
    assert set(sparse) == {"Community", "Status"}
    assert "Location" not in sparse


def test_site_detail_shows_location_from_utm():
    # a UTM-only summary still gets a Location, shown as converted lat/lon
    detail = dict(site_detail({"community": "X", "easting": 700000.0,
                               "northing": 950000.0, "utm_zone": 28}))
    assert "N," in detail["Location"] and detail["Location"].endswith("W")


def test_site_one_pager_contains_key_facts():
    text = site_one_pager(_SUMMARIES[0])
    assert text.startswith("SITE BRIEF - Rokel (Port Loko)")
    assert "Safe yield:" in text
    assert "2.40 m3/h" in text
    assert "Cost per metre:" in text


def test_a_hand_edited_number_blanks_one_cell_not_the_whole_page():
    """One ``total_depth_m: 52 m`` in one of forty files used to take the
    portfolio page down with a traceback that named no file."""
    edited = [
        {"community": "A", "total_depth_m": "52 m", "safe_yield_m3_per_h": "n/a",
         "cost_per_meter_usd": "abc", "utm_zone": "28N", "easting": 800000.0,
         "northing": 950000.0, "status": "Successful"},
        {"community": "B", "total_depth_m": 40.0, "safe_yield_m3_per_h": 1.5,
         "cost_per_meter_usd": 120.0, "status": "Successful"},
    ]
    rows = portfolio_rows(edited)
    assert rows[0]["Depth (m)"] is None and rows[0]["Safe yield (m3/h)"] is None
    assert rows[1]["Depth (m)"] == 40.0
    detail = dict(site_detail(edited[0]))
    assert "Total depth" not in detail and "Cost per metre" not in detail
    # the zone string could not be read, so it was inferred from the easting
    assert detail["Location"].startswith("8.58")
    stats = portfolio_stats(edited)
    assert stats["mean_safe_yield_m3_per_h"] == 1.5
    assert stats["n_values_unreadable"] == 3
    assert portfolio_stats(_SUMMARIES)["n_values_unreadable"] == 0
