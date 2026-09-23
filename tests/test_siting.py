"""Drill-target siting suitability (prototype) tests."""

from groundwater.ingestion import read_ves_workbook
from groundwater.siting import assess_siting, suitability_map_points
from groundwater.mapping import suitability_map
from groundwater.ves import interpret_model, invert_sounding


def _interps(sample_data):
    soundings = read_ves_workbook(sample_data / "rokel" / "rokel_ves.xlsx")
    inversions = [invert_sounding(s) for s in soundings]
    return [interpret_model(s, r.model)
            for s, r in zip(soundings, inversions, strict=True)]


def test_assess_siting_ranks_and_bounds(sample_data):
    results = assess_siting(_interps(sample_data))
    assert results, "expected at least one scored point"
    # ranked most suitable first, ranks are 1..n and dense
    assert [r.rank for r in results] == list(range(1, len(results) + 1))
    # ranked on suitability x confidence: a poor fit or an unresolved
    # basement discounts a point before it is compared with the others
    assert results[0].weighted == max(r.weighted for r in results)
    assert all(0.0 < r.confidence <= 1.0 for r in results)
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


def test_the_map_stars_the_recommended_point_and_writes_its_coordinates(tmp_path):
    """A drill-target map is walked to: the peg to drill at has to be the one
    unmistakable mark on it, with the grid coordinates beside it."""
    import matplotlib.pyplot as plt

    from groundwater.mapping import MapPoint, suitability_map_state

    points = [
        MapPoint(label="A (1)", easting=708958.0, northing=926355.0, value=48.0,
                 kind="Good", rank=1),
        MapPoint(label="B (2)", easting=727012.0, northing=916125.0, value=29.0,
                 kind="Good", rank=2),
    ]
    fig = suitability_map(points, zone=28)
    try:
        ax = fig.axes[0]
        legend = [t.get_text() for t in ax.get_legend().get_texts()]
        said = " ".join(t.get_text() for t in ax.texts)
    finally:
        plt.close(fig)
    assert "recommended drill target" in legend
    assert "E 708958" in said and "N 926355" in said
    # the weighted score is labelled as that, with its rank, and the grade
    # is named as the grade of the suitability: "29 - Good" paired a score
    # of 29 with a grade that 29 is not
    assert "Rank 2, weighted 29" in said and "Good suitability" in said
    assert "29 - Good" not in said
    assert suitability_map_state(points) == {
        "n_points": 2, "surface": False, "tie": False, "recommended": "A (1)",
        "leaders": ["A (1)"], "unplaced": [],
    }

    # two points within three weighted points are a tie: neither is starred
    points[1].value = 47.0
    fig = suitability_map(points, zone=28)
    try:
        ax = fig.axes[0]
        legend = [t.get_text() for t in ax.get_legend().get_texts()]
        said = " ".join(t.get_text() for t in ax.texts)
    finally:
        plt.close(fig)
    assert "recommended drill target" not in legend
    assert "indistinguishable" in said
    assert suitability_map_state(points)["tie"] is True


def _scored(sid, suitability, confidence=1.0, rank=None):
    from groundwater.siting import SitingSuitability, SuitabilityComponents

    return SitingSuitability(
        sounding_id=sid, suitability=suitability, grade="Very good",
        components=SuitabilityComponents(1.0, 1.0, 1.0, 1.0),
        rationale=f"Driven by {sid}.", rank=rank, confidence=confidence,
    )


def test_a_near_tie_is_not_said_to_be_ordered_by_name():
    """82.3 against 79.5 was "VES 2 is listed first by name only": the order
    was the score's, inside the margin the ranking cannot separate."""
    from groundwater.siting import ranking_tie, suitability_verdict, tied_leaders

    near = [_scored("VES 2", 82.3, rank=1), _scored("VES 1", 79.5, rank=2)]
    sentence = ranking_tie(near, within_points=3.0)
    assert ("VES 2 is ahead by 2.8 points, within the 3-point margin the ranking "
            "cannot separate") in sentence
    assert "by name only" not in sentence
    verdict = suitability_verdict(near, within_points=3.0)
    assert verdict.startswith(sentence)
    assert "Point VES 2: Driven by VES 2." in verdict and "Point VES 1: Driven by VES 1." in verdict

    equal = [_scored("VES 1", 80.0, rank=1), _scored("VES 2", 80.0, rank=2)]
    assert "VES 1 is listed first by name only" in ranking_tie(equal)

    clear = [_scored("VES 2", 82.3, rank=1), _scored("VES 1", 60.0, rank=2)]
    assert tied_leaders(clear) is None and ranking_tie(clear) == ""
    assert suitability_verdict(clear).startswith(
        "Point VES 2 ranks first (suitability 82 out of 100, very good, confidence 1.00)")
    # decided on the scores as they are, not as printed
    assert tied_leaders([_scored("A", 82.96, rank=1), _scored("B", 79.95, rank=2)]) is None

def _star_and_note(points, **kw):
    import matplotlib.pyplot as plt

    fig = suitability_map(points, zone=29, **kw)
    try:
        ax = fig.axes[0]
        legend = [t.get_text() for t in ax.get_legend().get_texts()]
        said = " ".join(t.get_text() for t in ax.texts)
    finally:
        plt.close(fig)
    return "recommended drill target" in legend, said


def test_a_recommended_point_with_no_position_is_not_starred_by_proxy():
    """VES 3 ranks first and has no GPS: the map holds only ranks 2 and 3,
    and neither the star nor the caption may pass to the runner-up."""
    from groundwater.mapping import MapPoint, suitability_map_state

    points = [
        MapPoint(label="VES 1", easting=178000.0, northing=1000000.0, value=68.4,
                 kind="Good", rank=2),
        MapPoint(label="VES 2", easting=178080.0, northing=1000040.0, value=63.0,
                 kind="Good", rank=3),
    ]
    ranking = ["VES 3", "VES 1", "VES 2"]
    state = suitability_map_state(points, tie=False, ranking=ranking)
    assert state["recommended"] is None
    assert state["unplaced"] == ["VES 3"]
    starred, said = _star_and_note(points, tie=False, ranking=ranking)
    assert not starred
    assert "VES 3, has no recorded position" in said


def test_the_map_takes_the_tie_it_is_given():
    """The ranking's tie, on its own margin, is the map's: a project margin
    of 5 points ties 48 and 44, and the map no longer stars one of them."""
    from groundwater.mapping import MapPoint, suitability_map_state

    points = [
        MapPoint(label="A", easting=178000.0, northing=1000000.0, value=48.0,
                 kind="Good", rank=1),
        MapPoint(label="B", easting=178100.0, northing=1000050.0, value=44.0,
                 kind="Good", rank=2),
    ]
    assert suitability_map_state(points)["tie"] is False
    starred, said = _star_and_note(points, tie=True, ranking=["A", "B"])
    assert not starred and "indistinguishable" in said
    assert suitability_map_state(points, tie=True, ranking=["A", "B"])["tie"] is True
    # and a tie with the runner-up off the map says so
    state = suitability_map_state(points[:1], tie=True, ranking=["A", "B"])
    assert state["leaders"] == ["A", "B"] and state["unplaced"] == ["B"]


def test_map_points_are_brought_into_one_zone():
    """Three soundings 400 m apart either side of 12 W, each recorded in its
    own zone, are one survey: the map points share a zone and the spread
    between them is metres, not the 660 km between the two zones' eastings."""
    from groundwater.geo import geographic_to_utm
    from groundwater.siting.suitability import SitingSuitability, SuitabilityComponents

    comp = SuitabilityComponents(1.0, 1.0, 1.0, 1.0)
    results = []
    for k, lon in enumerate((-12.0036, -11.9964, -11.995)):
        utm = geographic_to_utm(8.9, lon)
        results.append(SitingSuitability(
            sounding_id=f"VES {k + 1}", suitability=70.0 + k, grade="Good",
            components=comp, rationale="", easting=utm.easting,
            northing=utm.northing, rank=3 - k))
    points = suitability_map_points(results, zone=28)
    eastings = [p.easting for p in points]
    assert max(eastings) - min(eastings) < 1000.0
    assert all(e > 550_000 for e in eastings)
