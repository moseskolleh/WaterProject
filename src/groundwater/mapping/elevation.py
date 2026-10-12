"""Elevation models: the grid, and the readers for the files an operator has.

Reading a model is kept apart from drawing it (:mod:`.terrain`), so that a
caller after the heights alone - the terrain analysis, or a test - does not
import matplotlib to get them. Nothing imported here loads it, and
``tests/test_imports.py`` holds that.

Three formats are read, all with numpy alone, because a drilling
supervisor with a laptop in Makeni can obtain any of them and cannot
install GDAL:

``.hgt``
    An SRTM tile as NASA publishes it: raw big-endian int16, 1201x1201
    (3 arc-second) or 3601x3601 (1 arc-second), no header at all. The
    filename carries the south-west corner (``N08W013.hgt``).
``.asc`` / ``.grd``
    An ESRI ASCII grid: six header lines then the rows, north to south.
    Every GIS exports it.
``.xyz`` / ``.csv``
    Three columns of longitude, latitude, elevation on a regular grid,
    in any row order. What a phone GPS logger and most online elevation
    services hand back.

A void in any of them (SRTM's -32768, the grid's own NODATA value) is
carried through as NaN rather than as a number, so a hole in the data is
drawn as a hole rather than as a hollow in the ground.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..text import phrase

__all__ = [
    "ElevationGrid",
    "grid_fill_probe",
    "load_elevation",
    "read_esri_ascii",
    "read_srtm_hgt",
    "read_xyz",
]

#: SRTM marks a void with this value; it is not an elevation.
_SRTM_VOID = -32768

#: What ``.hgt`` side lengths mean, by the number of int16 samples in the file.
#: The sides are also written out in ``terrain.hgt_size``, the sentence both
#: engines print for a file of neither size.
_HGT_SIDES = {1201: "3 arc-second (about 90 m)", 3601: "1 arc-second (about 30 m)"}


@dataclass
class ElevationGrid:
    """A regular grid of ground elevations in geographic coordinates.

    ``lons`` and ``lats`` are the cell-centre coordinates of the columns
    and rows; ``z`` is ``(len(lats), len(lons))`` metres above the datum
    the source used, with NaN where the source had no value. ``lats``
    ascends, so row 0 is the southern edge - matplotlib's convention, not
    the raster convention, and the readers flip northern-first files to
    match rather than leaving each caller to remember which way up its
    data came.

    ``source`` is what the figure credits. It is not decoration: a
    contour map with no stated source is a contour map nobody can check.
    It stays the short label legends print; ``credit`` is what a licence
    asks a figure to add beside it.
    """

    lons: np.ndarray
    lats: np.ndarray
    z: np.ndarray
    source: str = "user-supplied elevation model"
    #: metres per sample, for the resolution note on the figure
    resolution_note: str = ""
    #: the credit a licence asks for beside the label, empty where no
    #: licence is known
    credit: str = ""
    #: the product the files were recognised as (``copernicus_glo30``,
    #: ``srtm`` or ``hgt``), or ``unidentified``
    source_id: str = "unidentified"
    #: the names of the files the grid was read from
    files: tuple[str, ...] = ()
    #: every file comes from a product that writes the sea as exactly 0 m
    #: and publishes no tiles of open sea, so low ground at the edge is sea
    #: rather than a fill value
    sea_clean: bool = False

    def __post_init__(self) -> None:
        self.lons = np.asarray(self.lons, dtype=float)
        self.lats = np.asarray(self.lats, dtype=float)
        self.z = np.asarray(self.z, dtype=float)
        self.files = tuple(self.files)
        if self.z.shape != (len(self.lats), len(self.lons)):
            raise ValueError(
                f"elevation grid is {self.z.shape}, but {len(self.lats)} "
                f"latitudes and {len(self.lons)} longitudes were given"
            )

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """``(lon_min, lat_min, lon_max, lat_max)`` of the cell centres."""
        return (
            float(self.lons.min()), float(self.lats.min()),
            float(self.lons.max()), float(self.lats.max()),
        )

    def covers(self, lon: float, lat: float) -> bool:
        lon_min, lat_min, lon_max, lat_max = self.bounds
        return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max

    def elevation_at(self, lon: float, lat: float) -> float | None:
        """Bilinear elevation at a point, or ``None`` outside or in a void."""
        if not self.covers(lon, lat):
            return None
        ix = float(np.interp(lon, self.lons, np.arange(len(self.lons))))
        iy = float(np.interp(lat, self.lats, np.arange(len(self.lats))))
        x0, y0 = int(math.floor(ix)), int(math.floor(iy))
        x1 = min(x0 + 1, len(self.lons) - 1)
        y1 = min(y0 + 1, len(self.lats) - 1)
        fx, fy = ix - x0, iy - y0
        corners = np.array([
            [self.z[y0, x0], self.z[y0, x1]],
            [self.z[y1, x0], self.z[y1, x1]],
        ], dtype=float)
        if not np.all(np.isfinite(corners)):
            return None  # a void is not an elevation, and averaging one is worse
        top = corners[0, 0] * (1 - fx) + corners[0, 1] * fx
        bottom = corners[1, 0] * (1 - fx) + corners[1, 1] * fx
        return float(top * (1 - fy) + bottom * fy)

    def window(self, lon: float, lat: float, radius_km: float) -> ElevationGrid:
        """The part of the grid inside a square window, for a local map.

        A whole SRTM tile is 1201x1201 samples and a 5 km site map wants
        about 120 of them across. Contouring the whole tile to show a
        tenth of a degree of it is slow and, worse, flattens the colour
        ramp onto the range of a mountain range the site is nowhere near.

        The window keeps one row and column beyond each edge where the
        grid has them, so a contour crossing the frame is drawn to the
        frame rather than stopping short of it.
        """
        dlat = radius_km / 111.32
        dlon = radius_km / (111.32 * max(math.cos(math.radians(lat)), 1e-6))
        ix = np.where((self.lons >= lon - dlon) & (self.lons <= lon + dlon))[0]
        iy = np.where((self.lats >= lat - dlat) & (self.lats <= lat + dlat))[0]
        if len(ix) < 2 or len(iy) < 2:
            raise ValueError(
                f"the elevation model covers {_bounds_text(self.bounds)}, which "
                f"holds fewer than two samples of the {radius_km:g} km window "
                f"around {abs(lat):.4f} {'N' if lat >= 0 else 'S'}, "
                f"{abs(lon):.4f} {'E' if lon >= 0 else 'W'}. Supply a model "
                "covering the site, or widen the window."
            )
        x0, x1 = max(ix[0] - 1, 0), min(ix[-1] + 2, len(self.lons))
        y0, y1 = max(iy[0] - 1, 0), min(iy[-1] + 2, len(self.lats))
        # a window of a model is still that model: its credit and source go
        # with it
        return ElevationGrid(
            self.lons[x0:x1], self.lats[y0:y1], self.z[y0:y1, x0:x1],
            source=self.source, resolution_note=self.resolution_note,
            credit=self.credit, source_id=self.source_id, files=self.files,
            sea_clean=self.sea_clean,
        )


def _bounds_text(bounds: tuple[float, float, float, float]) -> str:
    lon_min, lat_min, lon_max, lat_max = bounds
    return (
        f"{abs(lat_min):.3f}-{abs(lat_max):.3f} "
        f"{'N' if lat_min >= 0 else 'S'}, "
        f"{abs(lon_max):.3f}-{abs(lon_min):.3f} "
        f"{'E' if lon_min >= 0 else 'W'}"
    )


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def read_srtm_hgt(path: str | Path) -> ElevationGrid:
    """Read one SRTM ``.hgt`` tile.

    The file is nothing but samples - big-endian int16, northern row
    first - so the corner comes from the name (``N08W013.hgt`` is the
    tile whose south-west corner is 8 N, 13 W) and the resolution from
    the file's own length. A name that does not carry a corner is an
    error rather than a guess: placing a tile in the wrong degree square
    puts the contours 100 km from the site with nothing on the figure to
    say so.
    """
    path = Path(path)
    match = re.match(
        r"^([NS])(\d{2})([EW])(\d{3})", path.stem.upper()
    )
    if match is None:
        raise ValueError(phrase("terrain.hgt_name", file=path.name))
    ns, lat_deg, ew, lon_deg = match.groups()
    lat0 = float(lat_deg) * (1 if ns == "N" else -1)
    lon0 = float(lon_deg) * (1 if ew == "E" else -1)

    raw = np.fromfile(str(path), dtype=">i2")
    side = int(round(math.sqrt(raw.size)))
    if side * side != raw.size or side not in _HGT_SIDES:
        raise ValueError(phrase("terrain.hgt_size", file=path.name, n=raw.size))
    grid = raw.reshape(side, side).astype(float)
    grid[grid == _SRTM_VOID] = np.nan
    # the file runs north to south; ElevationGrid runs south to north
    grid = grid[::-1, :]
    step = 1.0 / (side - 1)
    lons = lon0 + np.arange(side) * step
    lats = lat0 + np.arange(side) * step
    return ElevationGrid(
        lons, lats, grid,
        source=f"SRTM tile {path.stem.upper()} (NASA/USGS, public domain)",
        resolution_note=_HGT_SIDES[side],
    )


def read_esri_ascii(path: str | Path) -> ElevationGrid:
    """Read an ESRI ASCII grid (``.asc``).

    Six header lines then the rows, north first. ``xllcorner`` gives the
    outer edge of the first cell and ``xllcenter`` its centre; both are
    accepted, and the difference between them is half a cell - which at
    3 arc-seconds is 45 m, enough to move a contour off a valley.
    """
    path = Path(path)
    header: dict[str, float] = {}
    rows: list[list[float]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if not parts:
                continue
            key = parts[0].lower()
            if key in {
                "ncols", "nrows", "xllcorner", "yllcorner", "xllcenter",
                "yllcenter", "cellsize", "nodata_value",
            }:
                header[key] = float(parts[1])
                continue
            rows.append([float(v) for v in parts])

    for required in ("ncols", "nrows", "cellsize"):
        if required not in header:
            raise ValueError(f"'{path.name}' has no {required} in its header")
    ncols, nrows = int(header["ncols"]), int(header["nrows"])
    cell = header["cellsize"]
    if "xllcenter" in header:
        x0, y0 = header["xllcenter"], header["yllcenter"]
    else:
        x0 = header["xllcorner"] + cell / 2.0
        y0 = header["yllcorner"] + cell / 2.0

    flat = np.array([v for row in rows for v in row], dtype=float)
    if flat.size != ncols * nrows:
        raise ValueError(
            f"'{path.name}' declares {nrows}x{ncols} cells but holds "
            f"{flat.size} values"
        )
    grid = flat.reshape(nrows, ncols)
    nodata = header.get("nodata_value")
    if nodata is not None:
        grid = np.where(grid == nodata, np.nan, grid)
    grid = grid[::-1, :]  # the file runs north to south
    return ElevationGrid(
        x0 + np.arange(ncols) * cell,
        y0 + np.arange(nrows) * cell,
        grid,
        source=f"elevation grid {path.name}",
        resolution_note=f"{cell * 111320:.0f} m cell",
    )


def read_xyz(path: str | Path) -> ElevationGrid:
    """Read longitude, latitude, elevation columns onto a regular grid.

    Row order does not matter; the distinct longitudes and latitudes are
    recovered and each triple placed in its cell. Any cell no row filled
    stays NaN, so a partial export is a map with a hole in it rather than
    a map with a fabricated hollow.

    A file whose points do not sit on a regular grid is refused. Gridding
    scattered heights is interpolation, and interpolating a landscape
    from scattered points is the thing this module will not do quietly.
    """
    path = Path(path)
    values: list[tuple[float, float, float]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line[0] in "#;":
                continue
            parts = re.split(r"[,\s;]+", line)
            if len(parts) < 3:
                continue
            try:
                values.append((float(parts[0]), float(parts[1]), float(parts[2])))
            except ValueError:
                continue  # a header row, named or not
    if len(values) < 4:
        raise ValueError(
            f"'{path.name}' holds {len(values)} usable rows; an elevation "
            "grid needs at least a 2x2 block of longitude, latitude, elevation."
        )
    arr = np.array(values, dtype=float)
    lons = np.unique(np.round(arr[:, 0], 9))
    lats = np.unique(np.round(arr[:, 1], 9))
    if len(lons) < 2 or len(lats) < 2:
        raise ValueError(
            f"'{path.name}' spans {len(lons)} longitudes and {len(lats)} "
            "latitudes; a grid needs at least two of each."
        )
    if len(lons) * len(lats) < len(arr):
        raise ValueError(
            f"'{path.name}' holds {len(arr)} rows over a "
            f"{len(lats)}x{len(lons)} grid, so some cells are given twice. "
            "This reader places points on a grid; it does not interpolate."
        )
    # A regular grid has evenly spaced columns and rows. Without this, any
    # scatter of points is a "grid" whose axes are the distinct coordinates
    # that happen to appear, and searchsorted drops each reading into a cell
    # chosen by rounding - a landscape assembled out of nothing.
    for axis, coords in (("longitudes", lons), ("latitudes", lats)):
        steps = np.diff(coords)
        if len(steps) > 1 and steps.std() > steps.mean() * 0.01:
            raise ValueError(
                f"'{path.name}' has unevenly spaced {axis}, so its points do "
                "not lie on a regular grid. This reader places points on a "
                "grid; it does not interpolate a surface from scattered "
                "heights."
            )
    filled = int(np.isfinite(grid_fill_probe(arr, lons, lats)).sum())
    cells = len(lons) * len(lats)
    if filled * 2 < cells:
        raise ValueError(
            f"'{path.name}' fills {filled} of {cells} cells in the "
            f"{len(lats)}x{len(lons)} grid its coordinates imply. That is a "
            "scatter of points rather than a grid with gaps in it, and this "
            "reader does not interpolate a surface from scattered heights."
        )
    grid = np.full((len(lats), len(lons)), np.nan)
    ix = np.searchsorted(lons, np.round(arr[:, 0], 9))
    iy = np.searchsorted(lats, np.round(arr[:, 1], 9))
    grid[iy, ix] = arr[:, 2]
    step = float(np.median(np.diff(lons))) if len(lons) > 1 else 0.0
    return ElevationGrid(
        lons, lats, grid,
        source=f"elevation grid {path.name}",
        resolution_note=f"{step * 111320:.0f} m cell" if step else "",
    )


def grid_fill_probe(
    arr: np.ndarray, lons: np.ndarray, lats: np.ndarray
) -> np.ndarray:
    """The grid an XYZ file would produce, for counting how full it is."""
    grid = np.full((len(lats), len(lons)), np.nan)
    grid[np.searchsorted(lats, np.round(arr[:, 1], 9)),
         np.searchsorted(lons, np.round(arr[:, 0], 9))] = arr[:, 2]
    return grid


_READERS = {
    ".hgt": read_srtm_hgt,
    ".asc": read_esri_ascii,
    ".grd": read_esri_ascii,
    ".xyz": read_xyz,
    ".csv": read_xyz,
    ".txt": read_xyz,
}


def load_elevation(path: str | Path) -> ElevationGrid:
    """Read an elevation model, choosing the reader by file extension."""
    path = Path(path)
    reader = _READERS.get(path.suffix.lower())
    if reader is None:
        raise ValueError(
            f"'{path.name}' is not an elevation format this toolkit reads. "
            f"It reads {', '.join(sorted(_READERS))}: an SRTM .hgt tile, an "
            "ESRI ASCII grid, or longitude/latitude/elevation columns. A "
            "GeoTIFF can be converted with `gdal_translate -of AAIGrid`."
        )
    return reader(path)
