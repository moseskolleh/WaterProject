"""Reading the bundled data: one reader, the layers parsed once."""

from __future__ import annotations

import json

from groundwater._resources import bundled_json, bundled_text
from groundwater.coverage import load_chiefdom_polys
from groundwater.mapping.regional import load_chiefdoms


def test_a_bundled_layer_is_parsed_once_and_a_named_file_every_time(tmp_path):
    """The copy in the wheel cannot change while the process runs; a file
    the caller names can, and a stale answer there would be a wrong one."""
    assert bundled_json("sl_geology_usgs.geojson") is bundled_json("sl_geology_usgs.geojson")

    layer = tmp_path / "layer.geojson"
    layer.write_text(json.dumps({"features": []}), encoding="utf-8")
    assert bundled_json("sl_geology_usgs.geojson", layer) == {"features": []}
    layer.write_text(json.dumps({"features": [1]}), encoding="utf-8")
    assert bundled_json("sl_geology_usgs.geojson", layer) == {"features": [1]}
    assert bundled_text("who_guidelines.csv", layer) == layer.read_text(encoding="utf-8")


def test_both_chiefdom_readers_build_their_own_rings_from_one_parse():
    """coverage and mapping share the parse, not the arrays: what each
    loader returns is the caller's to keep."""
    first, second = load_chiefdom_polys(), load_chiefdom_polys()
    assert first[0].rings[0] is not second[0].rings[0]
    areas = {area.name: area for area in load_chiefdoms()}
    for poly in first:
        area = areas[poly.name]
        assert len(area.rings) == len(poly.rings)
        for mine, theirs in zip(poly.rings, area.rings, strict=True):
            assert (mine == theirs).all()
