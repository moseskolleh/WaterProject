"""Planar point-in-polygon over the bundled boundary layers.

The ray-casting test lived in two copies - ``coverage`` and
``mapping.regional`` - with a comment in one asking the reader to keep it
matching the other. They answer the same question (which chiefdom is this
water point in?) and disagreeing by a vertex would put a village in the
wrong district silently, so there is one copy here and both import it.

Both the crossing count and the bounding-box rejection are vectorised.
That is not a micro-optimisation at this scale: a national Water Point
Data Exchange pull is tens of thousands of points, and each one was being
walked against 166 chiefdoms, 251 rings and about 6,800 vertices in a
Python loop.
"""

from __future__ import annotations

from typing import Iterable, Sequence, TypeVar

import numpy as np

__all__ = ["point_in_ring", "ring_bbox", "RingIndex"]


def point_in_ring(lon: float, lat: float, ring: np.ndarray) -> bool:
    """True when (lon, lat) is inside the closed ring.

    Ray casting: count the ring edges that straddle the point's latitude
    and cross to the right of it. An odd count means inside.

    The count is taken over the whole ring in one pass. Iterating the edges
    in Python costs about eight times as much, because indexing a two-column
    numpy array row by row builds a pair of numpy scalars per edge.
    """
    y = ring[:, 1]
    y1, y2 = y[:-1], y[1:]
    straddles = (y1 > lat) != (y2 > lat)
    if not straddles.any():
        return False
    x = ring[:, 0]
    x1 = x[:-1][straddles]
    x2 = x[1:][straddles]
    ya = y1[straddles]
    yb = y2[straddles]
    x_cross = x1 + (lat - ya) * (x2 - x1) / (yb - ya)
    return bool(np.count_nonzero(lon < x_cross) & 1)


def ring_bbox(ring: np.ndarray) -> tuple[float, float, float, float]:
    """(min_lon, min_lat, max_lon, max_lat) for one ring."""
    return (
        float(ring[:, 0].min()),
        float(ring[:, 1].min()),
        float(ring[:, 0].max()),
        float(ring[:, 1].max()),
    )


Area = TypeVar("Area")


class RingIndex:
    """Every ring of a list of areas in one flat, numpy-searchable table.

    A sequential scan rejects the areas a point is not in one Python
    comparison at a time - 251 of them per point for the chiefdom layer.
    The same rejection is a single vectorised comparison over an (n, 4)
    array of bounding boxes here.

    Rings are held in the order a sequential scan would have visited them,
    area by area and part by part, so :meth:`locate` returns the same area
    that scan would have stopped at - including when polygons overlap.

    The index holds references to the areas' ring arrays rather than
    copying them, so mutating an area's geometry after building an index
    over it leaves the index stale.
    """

    __slots__ = ("_areas", "_rings", "_holes", "_bounds")

    def __init__(
        self,
        areas: Iterable[Area],
        boxes: Sequence[Sequence[tuple[float, float, float, float]]] | None = None,
    ) -> None:
        """Index ``areas``; each needs ``.rings`` and ``.holes``.

        ``boxes`` supplies per-area, per-ring bounding boxes when the caller
        already has them, so they are not recomputed.
        """
        self._areas: list[Area] = []
        self._rings: list[np.ndarray] = []
        self._holes: list[list[np.ndarray]] = []
        bounds: list[tuple[float, float, float, float]] = []
        for a, area in enumerate(areas):
            rings = area.rings
            holes = getattr(area, "holes", None) or []
            known = boxes[a] if boxes is not None and a < len(boxes) else None
            for i, ring in enumerate(rings):
                self._areas.append(area)
                self._rings.append(ring)
                self._holes.append(holes[i] if i < len(holes) else [])
                bounds.append(
                    known[i]
                    if known is not None and i < len(known)
                    else ring_bbox(ring)
                )
        self._bounds = (
            np.asarray(bounds, dtype=float).reshape(-1, 4)
            if bounds
            else np.empty((0, 4), dtype=float)
        )

    def __len__(self) -> int:
        return len(self._rings)

    def locate(self, lon: float, lat: float) -> Area | None:
        """The first area containing the point, or ``None`` for none.

        A point inside a ring but inside one of that ring's holes is not in
        that part of the area - Nongowa encloses Kenema Town - so the search
        carries on to the next ring rather than claiming it.
        """
        box = self._bounds
        candidates = np.nonzero(
            (box[:, 0] <= lon)
            & (lon <= box[:, 2])
            & (box[:, 1] <= lat)
            & (lat <= box[:, 3])
        )[0]
        for k in candidates:
            if not point_in_ring(lon, lat, self._rings[k]):
                continue
            if any(point_in_ring(lon, lat, hole) for hole in self._holes[k]):
                continue  # inside an enclave: it belongs to whatever is there
            return self._areas[k]
        return None
