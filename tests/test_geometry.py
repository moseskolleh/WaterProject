"""The one point-in-polygon test the boundary lookups share."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from groundwater._geometry import RingIndex, point_in_ring
from groundwater.mapping.regional import load_chiefdoms


def _edge_by_edge(lon, lat, ring):
    """The ray cast coverage and mapping.regional each carried a copy of."""
    inside = False
    for (x1, y1), (x2, y2) in zip(ring[:-1], ring[1:], strict=True):
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_cross:
                inside = not inside
    return inside


def test_the_shared_ray_cast_answers_as_the_edge_by_edge_one_did():
    """Vectorising the crossing count must not move a village across a
    border, so it is checked where a ray cast is touchiest: on vertices,
    on edge midpoints, and a hair either side of them."""
    rng = np.random.default_rng(3)
    areas = load_chiefdoms()
    checked = 0
    for area in areas[::9]:
        for ring in area.rings:
            x0, y0 = ring.min(axis=0)
            x1, y1 = ring.max(axis=0)
            probes = [tuple(v) for v in ring[:: max(1, len(ring) // 12)]]
            probes += [tuple(v) for v in (ring[:-1] + ring[1:])[:: max(1, len(ring) // 12)] / 2]
            probes += list(zip(rng.uniform(x0, x1, 20), rng.uniform(y0, y1, 20), strict=True))
            for lon, lat in probes:
                for dx, dy in ((0, 0), (1e-7, 0), (-1e-7, 0), (0, 1e-7), (0, -1e-7)):
                    p = (float(lon) + dx, float(lat) + dy)
                    assert point_in_ring(*p, ring) == _edge_by_edge(*p, ring), (area.name, p)
                    checked += 1
    assert checked > 5000
    # a degenerate ring holds nothing, as before
    assert not point_in_ring(0.0, 0.0, np.zeros((1, 2)))


@dataclass
class _Area:
    name: str
    rings: list
    holes: list = field(default_factory=list)


def _square(x0, y0, size):
    return np.array([[x0, y0], [x0 + size, y0], [x0 + size, y0 + size],
                     [x0, y0 + size], [x0, y0]], dtype=float)


def test_the_index_answers_as_a_scan_in_layer_order():
    """The first area a sequential scan would stop at, overlaps and enclaves
    included - which is what the lookups did before the index existed."""
    town = _Area("Town", [_square(4, 4, 2)])
    around = _Area("Around", [_square(0, 0, 10)], holes=[[_square(4, 4, 2)]])
    overlap = _Area("Overlap", [_square(8, 8, 4)])
    island = _Area("Island", [_square(20, 20, 1), _square(0, 0, 1)])
    index = RingIndex([around, town, overlap, island])

    assert len(index) == 5
    assert index.locate(5.0, 5.0) is town        # the hole sends it on
    assert index.locate(1.0, 5.0) is around
    assert index.locate(9.0, 9.0) is around      # listed first, so it wins
    assert index.locate(11.0, 11.0) is overlap
    assert index.locate(20.5, 20.5) is island    # a second part
    assert index.locate(0.5, 0.5) is around      # the earlier area's ring
    assert index.locate(15.0, 15.0) is None
    assert RingIndex([]).locate(0.0, 0.0) is None
