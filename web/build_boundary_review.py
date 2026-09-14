"""Quarantine chiefdom geometry that cannot be trusted to place a borehole.

The chiefdom polygons are how a site with a GPS fix gets a chiefdom and
a district: ``groundwater.mapping.chiefdom_of`` walks them and the
crosswalk turns the answer into one of the sixteen current districts.
That makes a mislabelled polygon quietly expensive. It does not look
like an error; it looks like a borehole in the wrong district, on the
report, in the programme table and in the coverage figures that decide
where to drill next.

geoBoundaries builds its ADM3 layer by dissolving same-named units, and
a name collision there produces exactly that: geometry filed under a
chiefdom it does not belong to. ``split_koya_feature`` in
``web/build_geodata.py`` already repairs one instance by hand. This
script finds the same class of defect mechanically - a piece of a
chiefdom sitting implausibly far from the rest of it - takes it out of
the layer used for lookups, and writes it to a review file with the
measurements that justified the decision, so the judgement can be
re-examined rather than taken on trust.

Nothing is reassigned. Geometry that shares a boundary with a
neighbouring chiefdom is evidence of where it probably belongs, not
authority for putting it there; the review file names the likely owner
and leaves the decision to somebody who can check it against a
gazetteer.

Run from the repository root, after ``web/build_geodata.py`` and before
``web/build_webapp_data.py`` (the chiefdom layer it repairs is bundled
into the browser app):

    python web/build_boundary_review.py             # repair and review
    python web/build_boundary_review.py --check     # verify, don't rewrite

Rewrites ``src/groundwater/data/sl_chiefdoms_geoboundaries.geojson``
and writes ``src/groundwater/data/boundary_review.geojson``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "src" / "groundwater" / "data"
CHIEFDOMS = DATA / "sl_chiefdoms_geoboundaries.geojson"
REVIEW = DATA / "boundary_review.geojson"

# How far a piece of a chiefdom may sit from the rest of it before it stops
# being an island and starts being somebody else's ground. Sierra Leone's
# genuinely detached chiefdom parts are coastal islands and river islets: the
# furthest is 24.9 km out (Kpaka, in Pujehun). The one piece this rule catches
# is 246.7 km away, an order of magnitude beyond any of them, so the threshold
# sits in a gap rather than on a judgement.
DETACHED_KM = 50.0

ATTRIBUTION = (
    "Chiefdom geometry withheld from "
    "src/groundwater/data/sl_chiefdoms_geoboundaries.geojson pending review. "
    "Derived from geoBoundaries (gbOpen, CC BY 4.0): Runfola, D. et al. "
    "(2020). PLoS ONE 15(4): e0231866."
)


def polygons(feature: dict) -> list:
    """The polygons of a feature, whether it is a Polygon or a MultiPolygon."""
    geometry = feature["geometry"]
    return (geometry["coordinates"] if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]])


def ring_area(ring: list) -> float:
    """Unsigned shoelace area in square degrees."""
    return abs(sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
                   for i in range(len(ring) - 1)) / 2)


def ring_centre(ring: list) -> tuple[float, float]:
    return (sum(p[0] for p in ring) / len(ring),
            sum(p[1] for p in ring) / len(ring))


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Ground distance between two lon/lat pairs, near enough for a threshold."""
    mid = math.radians((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * 111.32 * math.cos(mid),
                      (a[1] - b[1]) * 110.57)


def sq_km(ring: list) -> float:
    """Ring area in square kilometres at its own latitude."""
    return ring_area(ring) * 111.32 * 110.57 * math.cos(math.radians(ring_centre(ring)[1]))


def detached(feature: dict) -> list[tuple[int, dict]]:
    """The polygons of a feature that sit too far from its main body.

    The main body is the largest polygon: a chiefdom is where most of it is,
    and every real multi-part chiefdom here is a coast or a river island
    within sight of its own mainland.
    """
    parts = polygons(feature)
    if len(parts) < 2:
        return []
    main = max(parts, key=lambda p: ring_area(p[0]))
    home = ring_centre(main[0])
    out = []
    for index, part in enumerate(parts):
        if part is main:
            continue
        distance = km_between(ring_centre(part[0]), home)
        if distance >= DETACHED_KM:
            out.append((index, {"distance_km": round(distance, 1)}))
    return out


def neighbours(ring: list, features: list, exclude: str) -> list[dict]:
    """Which other chiefdoms this ring shares boundary vertices with.

    A piece of ground cut out of the wrong chiefdom still sits on its real
    neighbour's boundary, so shared vertices say where it came from. It is
    evidence, not authority - the rings are simplified independently, so a
    shared vertex means the two were drawn from one boundary, and nothing
    more.
    """
    mine = {tuple(p) for p in ring}
    found = []
    for other in features:
        if other["properties"]["name"] == exclude:
            continue
        for part in polygons(other):
            shared = mine & {tuple(p) for p in part[0]}
            if shared:
                found.append({
                    "chiefdom": other["properties"]["name"],
                    "district": other["properties"].get("district", ""),
                    "shared_vertices": len(shared),
                })
    found.sort(key=lambda n: -n["shared_vertices"])
    merged: dict[str, dict] = {}
    for entry in found:
        seen = merged.setdefault(entry["chiefdom"], dict(entry, shared_vertices=0))
        seen["shared_vertices"] += entry["shared_vertices"]
    return sorted(merged.values(), key=lambda n: -n["shared_vertices"])


def measure(name: str, district: str, part: list, features: list) -> dict:
    """One withheld part, with the measurements the decision rests on.

    Measured against the layer as it stands, so a review entry stays true as
    the data around it changes: the parent chiefdom and the neighbour it
    shares a boundary with are both still in the layer, only this piece of
    ground is not.
    """
    ring = part[0]
    parent = next((f for f in features if f["properties"]["name"] == name), None)
    distance = 0.0
    if parent is not None:
        home = ring_centre(max(polygons(parent), key=lambda p: ring_area(p[0]))[0])
        distance = km_between(ring_centre(ring), home)
    near = neighbours(ring, features, name)
    proposed = near[0] if near else None
    return {
        "type": "Feature",
        "properties": {
            "name": name,
            "district": district,
            "reason": "detached_from_parent",
            "distance_km": round(distance, 1),
            "area_km2": round(sq_km(ring), 2),
            "vertices": len(ring) - 1,
            "shares_boundary_with": near,
            "proposed_owner": proposed["chiefdom"] if proposed else "",
            "proposed_district": proposed["district"] if proposed else "",
            "decision": (
                "Withheld from chiefdom lookups. Shares a boundary with "
                f"{proposed['chiefdom']} ({proposed['district']}), which is "
                "where it most likely belongs, but a shared boundary is not "
                "authority for reassigning ground: confirm against a "
                "gazetteer before moving it."
            ) if proposed else (
                "Withheld from chiefdom lookups. Nothing shares a boundary "
                "with it, so there is nothing to propose."
            ),
        },
        "geometry": {"type": "Polygon", "coordinates": part},
    }


def review(features: list, already: list) -> tuple[list, list]:
    """Split the layer into the geometry to keep and the geometry to review.

    ``already`` is what a previous run withheld. It is carried forward and
    re-measured rather than rediscovered, because it is no longer in the layer
    to be found: the review file is the standing record of what was taken out,
    and running this twice must not quietly empty it.
    """
    kept, withheld = [], []
    for feature in features:
        strays = detached(feature)
        if not strays:
            kept.append(feature)
            continue
        parts = polygons(feature)
        name = feature["properties"]["name"]
        district = feature["properties"].get("district", "")
        stray_indices = {index for index, _ in strays}
        remaining = [p for i, p in enumerate(parts) if i not in stray_indices]
        for index, _ in strays:
            withheld.append((name, district, parts[index]))
        repaired = dict(feature)
        repaired["geometry"] = (
            {"type": "Polygon", "coordinates": remaining[0]} if len(remaining) == 1
            else {"type": "MultiPolygon", "coordinates": remaining}
        )
        kept.append(repaired)

    carried = [(f["properties"]["name"], f["properties"].get("district", ""),
                f["geometry"]["coordinates"]) for f in already]
    seen = {json.dumps(part) for _, _, part in withheld}
    for entry in carried:
        if json.dumps(entry[2]) not in seen:
            withheld.append(entry)
    withheld.sort(key=lambda e: (e[0], -sq_km(e[2][0])))
    return kept, [measure(name, district, part, kept)
                  for name, district, part in withheld]


def build() -> tuple[str, str, list]:
    """The repaired chiefdom layer and the review file, as they should be written."""
    payload = json.loads(CHIEFDOMS.read_text(encoding="utf-8"))
    already = (json.loads(REVIEW.read_text(encoding="utf-8"))["features"]
               if REVIEW.exists() else [])
    kept, withheld = review(payload["features"], already)
    repaired = dict(payload, features=kept)
    review_payload = {
        "type": "FeatureCollection",
        "name": "boundary_review",
        "description": ATTRIBUTION,
        "features": withheld,
    }
    return (json.dumps(repaired, separators=(",", ":")),
            json.dumps(review_payload, separators=(",", ":")),
            withheld)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="compare the committed files against a fresh run instead of "
             "rewriting them; exit non-zero if either is out of date",
    )
    args = parser.parse_args()
    chiefdoms, review_text, withheld = build()

    if args.check:
        stale = []
        if CHIEFDOMS.read_text(encoding="utf-8") != chiefdoms:
            stale.append(str(CHIEFDOMS))
        if not REVIEW.exists() or REVIEW.read_text(encoding="utf-8") != review_text:
            stale.append(str(REVIEW))
        if stale:
            print("out of date: " + ", ".join(stale))
            print("Regenerate with:\n  python web/build_boundary_review.py")
            return 1
        print(f"the chiefdom layer and its review are current "
              f"({len(withheld)} part(s) withheld)")
        return 0

    CHIEFDOMS.write_text(chiefdoms, encoding="utf-8")
    REVIEW.write_text(review_text, encoding="utf-8")
    print(f"wrote {CHIEFDOMS} ({CHIEFDOMS.stat().st_size / 1024:.0f} KB)")
    print(f"wrote {REVIEW} ({len(withheld)} part(s) withheld)")
    for feature in withheld:
        p = feature["properties"]
        print(f"  {p['name']} ({p['district']}): {p['area_km2']} km2, "
              f"{p['distance_km']} km from the rest of it"
              + (f", shares a boundary with {p['proposed_owner']} "
                 f"({p['proposed_district']})" if p["proposed_owner"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
