"""Elevation models: the grid, and the readers for the files an operator has.

Reading a model is kept apart from drawing it (:mod:`.terrain`), so that a
caller after the heights alone - the terrain analysis, or a test - does not
import matplotlib to get them. Nothing imported here loads it, and
``tests/test_imports.py`` holds that.

Three formats are read, all with numpy alone, because a drilling
supervisor with a laptop in Makeni can obtain any of them and cannot
install GDAL:

``.hgt``
    An SRTM-format tile, as NASA and others publish it: raw big-endian
    int16, 1201x1201 (3 arc-second) or 3601x3601 (1 arc-second), no
    header at all. The filename carries the south-west corner
    (``N08W013.hgt``); nothing in the file says whose survey it is.
``.asc`` / ``.grd``
    An ESRI ASCII grid: six header lines then the rows, north to south.
    Every GIS exports it.
``.xyz`` / ``.csv``
    Three columns of longitude, latitude, elevation on a regular grid,
    in any row order. What a phone GPS logger and most online elevation
    services hand back.

``.tif`` / ``.tiff``
    A GeoTIFF, as Copernicus GLO-30, FABDEM and EarthExplorer SRTM tiles
    are published and as QGIS saves a clip, read by
    :mod:`groundwater.geotiff`, which needs no GDAL either.

A void in any of them (SRTM's -32768, the grid's own NODATA value) is
carried through as NaN rather than as a number, so a hole in the data is
drawn as a hole rather than as a hollow in the ground.

The elevation layer
-------------------
The apps never read a whole tile. :func:`read_elevation` opens each file
for its layout alone, plans the square to read around the site
(:func:`plan_window`: the square shown, the margin analysed beyond it,
and the cap on cells) and reads only the blocks of each file that square
meets (:func:`read_window`). On the way it does what turns files into one
elevation model the toolkit can stand behind:

* it takes WGS 84 longitude and latitude only, and refuses a projected
  copy by name, because such a copy has already been resampled;
* it joins tiles on one lattice and refuses rather than resamples, and
  where tiles overlap their heights must agree to the bit;
* it voids a height that is not a plausible ground level and counts it,
  rather than refusing the file over one cell;
* it takes a missing tile of a product that publishes no tiles of open
  sea as sea, with no height, only when every height on the full edges
  of the tiles beside it is at sea level;
* it says where the files came from only when their names and their
  georeferencing agree, or when the operator says so.

Every sentence it writes is in ``data/text/terrain.yaml``, and the
browser's elevation layer in ``docs/js/gwt-core.js`` does the same
arithmetic with the same operations, so the two engines read the same
window to the bit.
"""

from __future__ import annotations

import contextlib
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..config import TerrainConfig
from ..geotiff import (
    GeoTiffError,
    GeoTiffLayout,
    block_ranges,
    decode_block,
    open_geotiff,
    read_geotiff,
)
from ..text import phrase
from ..utils import and_join

__all__ = [
    "ElevationFile",
    "ElevationGrid",
    "ElevationRead",
    "PlanBlock",
    "PlanEdge",
    "RowMetric",
    "WindowCentre",
    "WindowPlan",
    "elevation_label_and_credit",
    "file_notes",
    "grid_fill_probe",
    "hgt_layout",
    "identify_source",
    "load_elevation",
    "open_elevation_file",
    "plan_window",
    "read_elevation",
    "read_esri_ascii",
    "read_srtm_hgt",
    "read_window",
    "read_xyz",
    "row_metric",
    "sin_cos_deg",
    "wgs84_cell_size",
    "window_centre",
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
    #: the product every file was recognised as, or the operator declared
    #: (``copernicus_glo30``, ``srtm`` or ``hgt``), else ``unidentified``
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
    # Credited as the windowed read credits an undeclared .hgt: NASA's SRTM,
    # NASADEM and void-filled compilations all come in this format, so the
    # file alone says nothing of its source. The file is described directly
    # rather than through the accept step, which would refuse a tile within
    # a degree of a pole that this reader has always read.
    found = ElevationFile(path.name, 2 * raw.size, hgt_layout(path.name, 2 * raw.size), "hgt", "hgt")
    label, credit, _, _, sea_clean = elevation_label_and_credit([found])
    return ElevationGrid(
        lons, lats, grid, source=label, resolution_note=_HGT_SIDES[side], credit=credit, source_id="hgt",
        files=(path.name,), sea_clean=sea_clean,
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


def _read_geotiff_grid(path: str | Path) -> ElevationGrid:
    """Read a whole GeoTIFF elevation model.

    The file must be in WGS 84 longitude and latitude, as every tile
    Copernicus, NASA and USGS publish is, and is refused with the same
    sentences the windowed read gives otherwise. A height outside the
    plausible range is voided as the windowed read voids it. Nothing caps
    the size, as nothing caps ``.hgt``: this is the whole-file read for the
    command line and the tests, and the apps read windows.
    """
    path = Path(path)
    raster = read_geotiff(path)
    found = _elevation_file(path.name, raster.layout.size, raster.layout, "geotiff")
    cfg = TerrainConfig()
    z = raster.z
    z[np.isinf(z) | (z < cfg.implausible_below_m) | (z > cfg.implausible_above_m)] = np.nan
    label, credit, _, _, sea_clean = elevation_label_and_credit([found])
    layout = raster.layout
    middle = layout.y0 - (layout.height // 2) * layout.sy
    dx, dy = wgs84_cell_size(middle, layout.sx, layout.sy)
    return ElevationGrid(
        raster.x, raster.y, z, source=label, resolution_note=_cell_note(dx, dy), credit=credit,
        source_id=_set_source([found.source_id]), files=(path.name,), sea_clean=sea_clean,
    )


_READERS = {
    ".hgt": read_srtm_hgt,
    ".tif": _read_geotiff_grid,
    ".tiff": _read_geotiff_grid,
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
            f"It reads {', '.join(sorted(_READERS))}: an SRTM .hgt tile, a "
            "GeoTIFF in longitude and latitude, an ESRI ASCII grid, or "
            "longitude/latitude/elevation columns."
        )
    return reader(path)


# ---------------------------------------------------------------------------
# Files as layouts: GeoTIFF, and .hgt as if it were one
# ---------------------------------------------------------------------------

#: An .hgt name: the south-west corner. ASCII letters and digits only, so
#: that the browser's regular expression, which knows no others, agrees.
_HGT_NAME = re.compile(r"^([NSns])([0-9]{2})([EWew])([0-9]{3})")

#: What a file's source is recognised from: its name without the extension,
#: letters in either case. re.ASCII keeps case folding and digits to ASCII,
#: as the browser's expressions have them.
_COPERNICUS_NAME = re.compile(r"^Copernicus_DSM_(?:COG_)?10_([NS])(\d{2})_00_([EW])(\d{3})_00_DEM$",
                              re.IGNORECASE | re.ASCII)
_SRTM_NAME = re.compile(r"^([ns])(\d{2})_([ew])(\d{3})_[13]arc_v[23]$", re.IGNORECASE | re.ASCII)
_FABDEM_NAME = re.compile(r"_fabdem_v1-\d", re.IGNORECASE | re.ASCII)

#: Products that write the sea as exactly 0 m and publish no tiles of open
#: sea, so a tile missing from a set of them may be sea
_SEA_AT_0 = ("copernicus_glo30", "srtm", "hgt")

#: How a product is named in a sentence
_PRODUCT_NAMES = {"copernicus_glo30": "Copernicus GLO-30", "srtm": "SRTM", "hgt": "SRTM"}

#: What the operator may declare a set to be: the product, or another
#: source in their own words
_DECLARED_KINDS = ("detect", "copernicus_glo30", "srtm", "other")

#: Within this much of a whole degree, a file's first centre is on it
_DEGREE_TOL = 1e-9
_ARCSEC = 1.0 / 3600.0


def _is_hgt(name: str) -> bool:
    return name[-4:].lower() == ".hgt"


def _stem(name: str) -> str:
    """The name without its extension: up to its last dot, unless that is
    the first character."""
    dot = name.rfind(".")
    return name[:dot] if dot > 0 else name


def hgt_layout(name: str, size: int) -> GeoTiffLayout:
    """An SRTM-format ``.hgt`` tile described as the GeoTIFF reader describes
    a file, so that a window of it is read block by block as a GeoTIFF's is.

    The file has no header: its corner comes from its name and its
    resolution from its length. It is big-endian int16 with -32768 for no
    data, northern row first, and each row is taken as a strip of its own,
    so a window reads only its own rows. Cells are centred on whole
    fractions of a degree from the named corner (PixelIsPoint), and the
    1201 or 3601 samples a side include both edges of the degree.
    """
    match = _HGT_NAME.match(name)
    if match is None:
        raise GeoTiffError("terrain.hgt_name", file=name)
    side = {2 * 1201 * 1201: 1201, 2 * 3601 * 3601: 3601}.get(size)
    if side is None:
        raise GeoTiffError("terrain.hgt_size", file=name, n=size // 2)
    ns, lat_deg, ew, lon_deg = match.groups()
    lat0 = int(lat_deg) * (1 if ns in "Nn" else -1)
    lon0 = int(lon_deg) * (1 if ew in "Ee" else -1)
    step = 1.0 / (side - 1)
    return GeoTiffLayout(
        name=name, size=size, byte_order=">", bigtiff=False, width=side, height=side, bits=16,
        sample_format=2, compression=1, predictor=1, predictor_applied=False, tiled=False,
        block_width=side, block_height=1, rows_per_strip=1,
        offsets=[2 * side * j for j in range(side)], byte_counts=[2 * side] * side,
        model_type=2, raster_type=2, epsg=4326, datum=None, angular_unit=None,
        x0=float(lon0), y0=float(lat0 + 1), sx=step, sy=step, nodata=_SRTM_VOID, ifd_index=0,
    )


@dataclass(frozen=True)
class ElevationFile:
    """One file of an elevation model, opened for its layout alone.

    ``kind`` is ``"geotiff"`` or ``"hgt"``. ``source_id`` is what the file
    was recognised as from its name and georeferencing together
    (``copernicus_glo30``, ``srtm``, ``hgt`` or ``unidentified``), and
    ``notes`` the catalogue ids of what is said about it alone
    (``terrain.name_mismatch``, ``terrain.looks_copernicus``,
    ``terrain.fabdem_licence``); :func:`file_notes` writes them out.
    """

    name: str
    size: int
    layout: GeoTiffLayout
    kind: str
    source_id: str
    notes: tuple[str, ...] = ()


def open_elevation_file(name: str, size: int, read_at: Callable[[int, int], bytes]) -> ElevationFile:
    """Open one file through ``read_at(offset, length)``, reading only what
    describes it: a GeoTIFF's directories, or nothing at all for ``.hgt``.

    A file is ``.hgt`` by its name and a GeoTIFF otherwise, which its
    first bytes then have to bear out. It is refused here, with its own
    sentence, unless it is in WGS 84 longitude and latitude and clear of
    the poles; then its source is recognised.
    """
    if _is_hgt(name):
        return _elevation_file(name, size, hgt_layout(name, size), "hgt")
    return _elevation_file(name, size, open_geotiff(name, size, read_at), "geotiff")


def _elevation_file(name: str, size: int, layout: GeoTiffLayout, kind: str) -> ElevationFile:
    _accept(layout, name)
    source_id, notes = identify_source(name, layout)
    return ElevationFile(name, size, layout, kind, source_id, notes)


def _accept(layout: GeoTiffLayout, name: str) -> None:
    """Refuse a file that is not in WGS 84 longitude and latitude, in
    degrees, with every cell centre more than a degree from a pole.

    A file carrying a GDAL mask is refused first: the cells it hides
    usually hold 0, which would read as ground at sea level. A projected
    file is named by its CRS, because the operator can then tell which copy
    of the tile they sent. Georeferencing no elevation model has - an
    origin that is infinite or not a number, longitudes beyond any map,
    cells under 1e-7 or over 1 degree - is refused before the poles are
    looked at, since each would otherwise reach the window arithmetic as
    an infinity or a hang; the test is written so that NaN fails it. At a
    pole a cell has no width east to west, and the window arithmetic
    divides by it.
    """
    if layout.has_mask:
        raise GeoTiffError("terrain.internal_mask", file=name)
    model = layout.model_type
    if model == 1:
        raise GeoTiffError("terrain.projected", file=name, crs=_projected_name(layout.epsg))
    if model is None:
        raise GeoTiffError("terrain.no_crs", file=name)
    if model != 2:
        raise GeoTiffError("terrain.not_wgs84", file=name, crs=f"GeoTIFF model type {model}")
    wgs84 = layout.epsg == 4326 or (layout.epsg in (None, 32767) and layout.datum == 6326)
    if not wgs84 or layout.angular_unit not in (None, 9102):
        raise GeoTiffError("terrain.not_wgs84", file=name, crs=_geographic_name(layout))
    east = layout.x0 + (layout.width - 1) * layout.sx
    south = layout.y0 - (layout.height - 1) * layout.sy
    if not (layout.x0 >= -540.0 and east <= 540.0 and south >= -90.0 and layout.y0 <= 90.0
            and layout.sx >= 1e-7 and layout.sx <= 1.0 and layout.sy >= 1e-7 and layout.sy <= 1.0):
        raise GeoTiffError("terrain.bad_georeference", file=name)
    if not (south > -89.0 and layout.y0 < 89.0):
        raise GeoTiffError("terrain.polar", file=name)


def _projected_name(epsg: int | None) -> str:
    """A projected CRS as the refusal names it: the UTM zones and the
    Sierra Leone 1968 grid by name, anything else by its EPSG code."""
    if epsg is None or epsg == 32767:
        return "a projected system with no EPSG code"
    if 32601 <= epsg <= 32660 or 32701 <= epsg <= 32760:
        return f"WGS 84 / UTM zone {epsg % 100}{'N' if epsg < 32700 else 'S'} (EPSG {epsg})"
    if epsg in (2161, 2162):
        return f"Sierra Leone 1968 / UTM zone {28 if epsg == 2161 else 29}N (EPSG {epsg})"
    return f"EPSG {epsg}"


def _geographic_name(layout: GeoTiffLayout) -> str:
    """A geographic CRS that is not WGS 84 in degrees, as the refusal names it."""
    epsg, datum, unit = layout.epsg, layout.datum, layout.angular_unit
    if epsg is not None and epsg != 32767:
        text = f"EPSG {epsg}"
    elif datum == 6326:
        text = "WGS 84"
    elif datum is not None and datum != 32767:
        text = f"a geographic system on datum EPSG {datum}"
    else:
        text = "a geographic system with no EPSG code"
    if unit is not None and unit != 9102:
        text += f" in angular unit EPSG {unit}"
    return text


# ---------------------------------------------------------------------------
# Where a file came from, and what the figures must say about it
# ---------------------------------------------------------------------------

def _spacing_is(value: float, step: float) -> bool:
    return abs(value - step) <= 1e-12


def _on_degree(value: float) -> bool:
    # finite first: math.floor of an infinity or NaN raises, where the
    # browser's Math.floor carries it on
    return math.isfinite(value) and abs(value - math.floor(value + 0.5)) <= _DEGREE_TOL


def _inside_square(layout: GeoTiffLayout, lon0: int, lat0: int) -> bool:
    """Every cell centre lies in the 1-degree square whose south-west corner
    is (lon0, lat0), give or take a billionth of a degree; so a tile of
    3600 or of 3601 samples a side passes."""
    east = layout.x0 + (layout.width - 1) * layout.sx
    south = layout.y0 - (layout.height - 1) * layout.sy
    return (layout.x0 >= lon0 - _DEGREE_TOL and east <= lon0 + 1 + _DEGREE_TOL
            and south >= lat0 - _DEGREE_TOL and layout.y0 <= lat0 + 1 + _DEGREE_TOL)


def _named_corner(match: re.Match) -> tuple[int, int, str]:
    """(lon0, lat0, tile code such as "N08 W012") from a name's four groups."""
    ns, lat_deg, ew, lon_deg = (group.upper() for group in match.groups())
    lat0 = int(lat_deg) * (1 if ns == "N" else -1)
    lon0 = int(lon_deg) * (1 if ew == "E" else -1)
    return lon0, lat0, f"{ns}{lat_deg} {ew}{lon_deg}"


def _glo30_fingerprint(layout: GeoTiffLayout) -> bool:
    """Laid out as a Copernicus GLO-30 tile is, whatever its name.

    Nothing in a tile says it is Copernicus, so this only prompts the
    operator; it never credits.
    """
    return (layout.model_type == 2 and layout.epsg == 4326
            and _spacing_is(layout.sx, _ARCSEC) and _spacing_is(layout.sy, _ARCSEC)
            and layout.raster_type == 2 and _on_degree(layout.x0) and _on_degree(layout.y0)
            and layout.sample_format == 3 and layout.bits == 32 and not layout.has_nodata_tag
            and layout.geo_ascii == "WGS 84|")


def identify_source(name: str, layout: GeoTiffLayout) -> tuple[str, tuple[str, ...]]:
    """What product a file is, from its name and georeferencing together,
    and the catalogue ids of what must be said about it.

    A tile holds nothing that identifies it, and operators rename files, so
    the name is believed only when the georeferencing bears it out: a file
    named as Copernicus names a GLO-30 tile must be in EPSG 4326 at one
    arc-second with every centre inside the degree square it names.
    Anything else is a file of unstated source, which is never credited to
    a product; a file laid out exactly as a GLO-30 tile prompts the
    operator to say so instead.
    """
    if _is_hgt(name):
        return "hgt", ()
    stem = _stem(name)
    match = _COPERNICUS_NAME.match(stem)
    if match is not None:
        lon0, lat0, _ = _named_corner(match)
        if (layout.model_type == 2 and layout.epsg == 4326 and _spacing_is(layout.sx, _ARCSEC)
                and _spacing_is(layout.sy, _ARCSEC) and _inside_square(layout, lon0, lat0)):
            return "copernicus_glo30", ()
        return "unidentified", ("terrain.name_mismatch",)
    match = _SRTM_NAME.match(stem)
    if match is not None:
        lon0, lat0, _ = _named_corner(match)
        spacing = next((step for step in (_ARCSEC, 1.0 / 1200.0) if _spacing_is(layout.sx, step)), None)
        if spacing is not None and _spacing_is(layout.sy, spacing) and _inside_square(layout, lon0, lat0):
            return "srtm", ()
    if _FABDEM_NAME.search(stem):
        return "unidentified", ("terrain.fabdem_licence",)
    if _glo30_fingerprint(layout):
        return "unidentified", ("terrain.looks_copernicus",)
    return "unidentified", ()


def file_notes(found: ElevationFile, declared: tuple[str, str] = ("detect", "")) -> tuple[str, ...]:
    """What is said about one file alone, written out.

    Once the operator has declared the source, a note about how the file
    would otherwise be credited no longer applies; the FABDEM licence
    warning does.
    """
    kind, _ = _declaration(declared)
    out = []
    for ident in found.notes:
        if kind != "detect" and ident != "terrain.fabdem_licence":
            continue
        if ident == "terrain.name_mismatch":
            out.append(phrase("terrain.name_mismatch", file=found.name))
        elif ident == "terrain.looks_copernicus":
            out.append(phrase("terrain.looks_copernicus", file=found.name))
        else:
            out.append(phrase("terrain.fabdem_licence", file=found.name))
    return tuple(out)


def _declaration(declared: tuple[str, str]) -> tuple[str, str]:
    """The operator's declaration, with another source of no stated name
    read as no declaration at all."""
    kind, text = declared
    if kind not in _DECLARED_KINDS:
        raise ValueError(f"the source declared is {kind!r}, not one of {', '.join(_DECLARED_KINDS)}")
    if kind == "other" and not text.strip():
        return "detect", ""
    return kind, text.strip()


def _declared_sources(files: Sequence[ElevationFile], declared: tuple[str, str]) -> tuple[str, ...]:
    """Each file's source once the declaration is applied: the declaration
    wins, and a source in the operator's own words is no product the
    toolkit knows."""
    kind, _ = _declaration(declared)
    if kind == "detect":
        return tuple(f.source_id for f in files)
    return tuple(kind if kind != "other" else "unidentified" for _ in files)


def _set_source(sources: Sequence[str]) -> str:
    return sources[0] if sources and all(s == sources[0] for s in sources) else "unidentified"


def _tile_code(name: str) -> str:
    stem = _stem(name)
    match = _COPERNICUS_NAME.match(stem) or _SRTM_NAME.match(stem)
    return _named_corner(match)[2] if match is not None else name


def elevation_label_and_credit(files: Sequence[ElevationFile], declared: tuple[str, str] = ("detect", "")
                               ) -> tuple[str, str, str | None, str, bool]:
    """``(label, credit, notice, surface note, sea_clean)`` for a set of files.

    The label names the files and where they came from; the credit is what
    a licence asks a figure drawn from them to carry ("" where none is
    known); the notice is the Copernicus licence's liability sentence,
    printed wherever the set holds a Copernicus file; the surface note
    says what the heights are heights of. The operator's declaration wins
    over what the names say. ``sea_clean`` is True when every file comes
    from a product that writes the sea as exactly 0 m and publishes no
    tiles of open sea.
    """
    kind, text = _declaration(declared)
    ordered = sorted(files, key=_plan_key)
    names = and_join([f.name for f in ordered])
    copernicus = phrase("terrain.credit_copernicus_modified")
    liability = phrase("terrain.copernicus_liability")
    if kind == "copernicus_glo30":
        return (phrase("terrain.label_declared", declared=_PRODUCT_NAMES[kind], files=names), copernicus,
                liability, phrase("terrain.surface_copernicus"), True)
    if kind == "srtm":
        return (phrase("terrain.label_declared", declared=_PRODUCT_NAMES[kind], files=names),
                phrase("terrain.credit_srtm"), None, phrase("terrain.surface_srtm"), True)
    if kind == "other":
        return (phrase("terrain.label_declared", declared=text, files=names), "", None,
                phrase("terrain.surface_unknown"), False)
    sources = [f.source_id for f in ordered]
    found = [f for f in ordered if f.source_id == "copernicus_glo30"]
    if found and len(found) == len(ordered):
        tiles = and_join([_tile_code(f.name) for f in found])
        return (phrase("terrain.label_copernicus", n=len(found), tiles=tiles), copernicus, liability,
                phrase("terrain.surface_copernicus"), True)
    if found and all(s in ("copernicus_glo30", "unidentified") for s in sources):
        rest = and_join([f.name for f in ordered if f.source_id != "copernicus_glo30"])
        tiles = and_join([_tile_code(f.name) for f in found])
        return (phrase("terrain.label_mixed", n=len(found), tiles=tiles, files=rest), copernicus, liability,
                phrase("terrain.surface_unknown"), False)
    if sources and all(s == "srtm" for s in sources):
        tiles = and_join([_tile_code(f.name) for f in ordered])
        return (phrase("terrain.label_srtm", n=len(ordered), tiles=tiles), phrase("terrain.credit_srtm"), None,
                phrase("terrain.surface_srtm"), True)
    if sources and all(s == "hgt" for s in sources):
        return (phrase("terrain.label_hgt", n=len(ordered), files=names), "", None,
                phrase("terrain.surface_srtm"), True)
    return (phrase("terrain.label_unidentified", files=names), "", None, phrase("terrain.surface_unknown"),
            False)


# ---------------------------------------------------------------------------
# Degrees and metres, with the same bits in both engines
# ---------------------------------------------------------------------------

_D2R = math.pi / 180.0
_A = 6378137.0                   # WGS 84, as groundwater.geo has it
_FLAT = 1.0 / 298.257223563
_E2 = _FLAT * (2.0 - _FLAT)


def _factorial(k: int) -> float:
    """k! as an exact integer, then a double: exact for k <= 18 (< 2**53)."""
    product = 1
    for n in range(2, k + 1):
        product *= n
    return float(product)


# The Taylor coefficients, worked out at load rather than typed as decimal
# literals, so that the browser's copies are the same doubles by
# construction: 1/k! is one correctly rounded division in both engines.
_SIN = tuple((-1.0 if n % 2 else 1.0) / _factorial(2 * n + 1) for n in range(9))
_COS = tuple((-1.0 if n % 2 else 1.0) / _factorial(2 * n) for n in range(10))


def sin_cos_deg(d: float) -> tuple[float, float]:
    """The sine and cosine of ``d`` degrees, from additions, multiplications
    and one floor, so that both engines give the same bits.

    ``math.sin`` and V8's ``Math.sin`` differ in the last bit for some
    inputs, and the cell sizes of every row are worked out from these. The
    angle is first reduced to within 45 degrees of a right angle, which is
    exact, then a Taylor polynomial is summed in a fixed order. At a right
    angle the answer is exactly 0 or 1; elsewhere it is within about 1e-15
    of the true value. Something that is not a finite number gives NaN.
    """
    d = float(d)
    if not math.isfinite(d):
        return math.nan, math.nan
    q = math.floor(d / 90.0 + 0.5)
    r = d - 90.0 * q
    x = r * _D2R
    x2 = x * x
    s = _SIN[8]
    for k in range(7, -1, -1):
        s = s * x2 + _SIN[k]
    s = s * x
    c = _COS[9]
    for k in range(8, -1, -1):
        c = c * x2 + _COS[k]
    return ((s, c), (c, -s), (-s, -c), (-c, s))[q % 4]


def wgs84_cell_size(lat: float, step_lon: float, step_lat: float) -> tuple[float, float]:
    """The east-west and north-south size in metres of a cell centred at
    latitude ``lat`` and ``step_lon`` by ``step_lat`` degrees, on the WGS 84
    ellipsoid: the radii of curvature in the prime vertical (N) and the
    meridian (M) at that latitude, times the step in radians."""
    s, c = sin_cos_deg(lat)
    den = 1.0 - _E2 * (s * s)
    rt = math.sqrt(den)
    n = _A / rt
    m = (_A * (1.0 - _E2)) / (den * rt)
    return (n * c) * (step_lon * _D2R), m * (step_lat * _D2R)


@dataclass(frozen=True)
class RowMetric:
    """Each row's cell size: ``dx`` east-west and ``dy`` north-south in
    metres, ``dg`` the diagonal, and ``au_row`` the cell's area in whole
    units of 0.01 square metres (an integer, so areas add up exactly in
    any order). Row 0 is the southern row, as in the grid."""

    dx: np.ndarray
    dy: np.ndarray
    dg: np.ndarray
    au_row: np.ndarray


def row_metric(lons: np.ndarray, lats: np.ndarray) -> RowMetric:
    """The cell size of every row of a grid with these centres.

    A cell 1 arc-second wide is 0.26% narrower at the north edge of a
    Sierra Leone tile than at its south edge, so each row has its own
    size. Scalar arithmetic in a loop over the rows, never numpy's
    vectorised sine, so that the browser's loop gives the same bits.
    """
    width, height = len(lons), len(lats)
    if width < 2 or height < 2:
        raise ValueError(f"a {height} by {width} grid has no step between its cells to measure")
    step_lon = (float(lons[width - 1]) - float(lons[0])) / (width - 1)
    step_lat = (float(lats[height - 1]) - float(lats[0])) / (height - 1)
    dx = np.empty(height)
    dy = np.empty(height)
    dg = np.empty(height)
    au = np.empty(height, dtype=np.int64)
    for r in range(height):
        x, y = wgs84_cell_size(float(lats[r]), step_lon, step_lat)
        dx[r], dy[r] = x, y
        dg[r] = math.sqrt(x * x + y * y)
        au[r] = math.floor(x * y * 100.0 + 0.5)
    return RowMetric(dx, dy, dg, au)


def _cell_note(dx: float, dy: float) -> str:
    return f"about {dx:.0f} by {dy:.0f} m"


def _coordinates(lon: float, lat: float) -> str:
    """A point as the read report writes one: 9.03487 N, 11.92862 W."""
    return (f"{abs(lat):.5f} {'N' if lat >= 0 else 'S'}, "
            f"{abs(lon):.5f} {'E' if lon >= 0 else 'W'}")


# ---------------------------------------------------------------------------
# The window: where it is centred, which cells it holds, which blocks to read
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WindowCentre:
    """Where the window is centred, and what to call the place.

    ``exact`` is True for a GPS fix. ``note`` is the sentence saying how
    the centre was chosen when it was not a fix, or None.
    """

    lon: float
    lat: float
    label: str
    exact: bool
    note: str | None = None


def window_centre(site, files: Sequence[ElevationFile]) -> WindowCentre:
    """Centre the window on the site: its GPS fix, else its chiefdom, else
    its district, as every other local map is centred; with no location at
    all, on the middle of the files.

    ``area_window`` is imported here rather than at the top of the module,
    because its module draws maps and loads pyplot as it is imported; the
    elevation layer loads it only when a site is given.
    """
    if site is not None:
        from .regional import area_window

        area = area_window(site)
        if area is not None:
            note = None if area.exact else phrase("terrain.centre_area", label=area.label)
            return WindowCentre(float(area.lon), float(area.lat), area.label, bool(area.exact), note)
    if not files:
        raise ValueError("no elevation files to centre the window on")
    west, south, east, north = _extent(files)
    lon, lat = (west + east) / 2.0, (south + north) / 2.0
    return WindowCentre(lon, lat, _coordinates(lon, lat), False, phrase("terrain.centre_no_site"))


def _extent(files: Sequence[ElevationFile]) -> tuple[float, float, float, float]:
    """(west, south, east, north): the bounding box of the files' cell
    centres, which holds any gap between them too."""
    west = min(f.layout.x0 for f in files)
    east = max(f.layout.x0 + (f.layout.width - 1) * f.layout.sx for f in files)
    south = min(f.layout.y0 - (f.layout.height - 1) * f.layout.sy for f in files)
    north = max(f.layout.y0 for f in files)
    return west, south, east, north


@dataclass(frozen=True)
class PlanEdge:
    """A full edge of a supplied tile beside a missing one: row ``row`` or
    column ``column`` of file ``file`` (an index into the plan's files),
    whose heights decide whether missing tile ``missing`` is sea."""

    missing: int
    file: int
    row: int | None
    column: int | None


@dataclass(frozen=True)
class PlanBlock:
    """One read: block ``index`` of file ``file``, its bytes at ``offset``
    and ``length`` (``rows`` as :func:`geotiff.block_ranges` gives them),
    whether its cells meet the window, and which edges it holds."""

    file: int
    index: int
    offset: int
    length: int
    rows: tuple[int, int] | None
    window: bool
    edges: tuple[int, ...]


@dataclass(frozen=True)
class WindowPlan:
    """Which cells the window holds and which blocks of which files to read.

    The files are in plan order: the greatest ``y0`` first, then the
    smallest ``x0``, then the name in UTF-16 code-unit order. The first
    file's lattice is the reference: ``x0``, ``y0``, ``sx``, ``sy``, and
    ``offsets`` gives each file's first cell on it as (column, row), row 0
    north. The window is ``width`` by ``height`` cells of every
    ``stride``-th lattice cell, centred on lattice cell (``ci``, ``cj``),
    ``hx`` and ``hy`` cells each side of it; the square shown is ``hxs``
    and ``hys`` each side. ``lons`` and ``lats`` are the cell centres,
    ``lats`` from the south. ``dx`` and ``dy`` are the centre cell's size
    in metres at stride 1. ``tile`` is the cells a 1-degree tile spans when
    the set is one of whole tiles of a product that publishes no tiles of
    open sea, else 0; ``missing`` the tiles (column, row) the window meets
    that no file supplies.
    """

    files: tuple[ElevationFile, ...]
    sources: tuple[str, ...]
    declared: tuple[str, str]
    offsets: tuple[tuple[int, int], ...]
    x0: float
    y0: float
    sx: float
    sy: float
    centre: WindowCentre
    ci: int
    cj: int
    stride: int
    hx: int
    hy: int
    hxs: int
    hys: int
    width: int
    height: int
    radius_km: float
    margin_km: float
    dx: float
    dy: float
    lons: np.ndarray = field(repr=False)
    lats: np.ndarray = field(repr=False)
    tile: int
    missing: tuple[tuple[int, int], ...]
    edges: tuple[PlanEdge, ...]
    blocks: tuple[PlanBlock, ...]

    @property
    def cells(self) -> int:
        return self.width * self.height

    @property
    def shown(self) -> tuple[int, int, int, int]:
        """The square shown as rows ``r0:r1`` and columns ``c0:c1`` of the
        window. It is centred, so it is the same counted from either edge."""
        return (self.hy - self.hys, self.hy + self.hys + 1, self.hx - self.hxs, self.hx + self.hxs + 1)

    def tile_code(self, tile: tuple[int, int]) -> str:
        """A tile of the reference lattice named by its south-west corner,
        as tiles are: "N07 W013"."""
        lon0 = math.floor(self.x0 + 0.5) + tile[0]
        lat0 = math.floor(self.y0 + 0.5) - 1 - tile[1]
        return f"{'N' if lat0 >= 0 else 'S'}{abs(lat0):02d} {'E' if lon0 >= 0 else 'W'}{abs(lon0):03d}"


def _plan_key(found: ElevationFile) -> tuple[float, float, bytes]:
    # UTF-16 code units, as the browser's string comparison has them; a
    # code point order would put U+E000..U+FFFF after a supplementary-plane
    # character where JavaScript puts it before
    return (-found.layout.y0, found.layout.x0, found.name.encode("utf-16-be", "surrogatepass"))


def _steps(first: int, count: int, start: int, stride: int, n: int) -> tuple[int, int] | None:
    """Which window positions ``q`` in ``0..n-1``, at lattice cell
    ``start + stride*q``, fall in lattice cells ``first..first+count-1``:
    ``(q_lo, q_hi)`` inclusive, or None."""
    delta = first - start
    q_lo = max(0, -((-delta) // stride))
    q_hi = min(n - 1, (delta + count - 1) // stride)
    return (q_lo, q_hi) if q_lo <= q_hi else None


def _block_origin(layout: GeoTiffLayout, index: int, rows: tuple[int, int] | None) -> tuple[int, int]:
    """The image row and column of a block's first cell (of ``rows[0]``
    for a strip read in part), row 0 north."""
    if layout.tiled:
        across = -(-layout.width // layout.block_width)
        row0, col0 = index // across * layout.block_height, index % across * layout.block_width
    else:
        row0, col0 = index * layout.block_height, 0
    return row0 + (rows[0] if rows is not None else 0), col0


def _block_shape(layout: GeoTiffLayout, index: int, rows: tuple[int, int] | None) -> tuple[int, int]:
    """How many image rows and columns a block (or the rows of it read) holds."""
    row0, col0 = _block_origin(layout, index, None)
    if rows is not None:
        return rows[1] - rows[0], layout.width
    return (min(layout.block_height, layout.height - row0), min(layout.block_width, layout.width - col0))


def plan_window(files: Sequence[ElevationFile], centre: WindowCentre, radius_km: float,
                cfg: TerrainConfig | None = None, stride: int = 1, margin_km: float | None = None,
                declared: tuple[str, str] = ("detect", "")) -> WindowPlan:
    """Plan the window: check that the files join, work out which cells it
    holds, and list the blocks of each file to read.

    ``radius_km`` is the half-side of the square shown; the analysis also
    reads ``margin_km`` (by default ``cfg.analysis_buffer_km``; the
    topographic map passes 0) beyond it on every side, and the cap on cells
    applies to the whole, once the centre is known to lie on a file (else
    it lies in a gap between them or outside them); the cap on blocks
    applies to the blocks the plan names, counted before they are listed.
    ``stride`` reads every stride-th lattice cell, for the Python app's wide
    topographic map; 0 picks the least stride that fits under the cap.
    ``declared`` is the operator's statement of the source, which wins over
    what the names say.

    The steps, the arithmetic and the order of the refusals are the
    browser's (``C.planElevationWindow``), so that both engines plan the
    same window from the same files.
    """
    cfg = TerrainConfig() if cfg is None else cfg
    margin = cfg.analysis_buffer_km if margin_km is None else float(margin_km)
    radius = float(radius_km)
    if not files:
        raise ValueError("no elevation files to plan a window over")
    if stride < 0:
        raise ValueError(f"a stride of {stride} reads no cells")

    # 1-2. plan order, one file per name, one kind of file
    ordered = sorted(files, key=_plan_key)
    seen: set[str] = set()
    for found in ordered:
        if found.name in seen:
            raise GeoTiffError("terrain.duplicate_name", file=found.name)
        seen.add(found.name)
    for found in ordered[1:]:
        if found.kind != ordered[0].kind:
            raise GeoTiffError("terrain.mixed_formats", a=ordered[0].name, b=found.name)
    sources = _declared_sources(ordered, declared)

    # 3. one lattice, the reference file's
    ref = ordered[0].layout
    x0, y0, sx, sy = ref.x0, ref.y0, ref.sx, ref.sy
    offsets = [(0, 0)]
    for found in ordered[1:]:
        lay = found.layout
        if abs(lay.sx - sx) > 1e-9 * sx or abs(lay.sy - sy) > 1e-9 * sy:
            raise GeoTiffError("terrain.join_spacing", a=ordered[0].name, b=found.name)
        ex, ey = (lay.x0 - x0) / sx, (y0 - lay.y0) / sy
        # written so that an infinite or NaN offset fails, finite first
        # because math.floor of one raises
        if not (math.isfinite(ex) and math.isfinite(ey) and abs(ex - math.floor(ex + 0.5)) <= 1e-6
                and abs(ey - math.floor(ey + 0.5)) <= 1e-6):
            raise GeoTiffError("terrain.join_phase", a=ordered[0].name, b=found.name)
        offsets.append((math.floor(ex + 0.5), math.floor(ey + 0.5)))

    # 4. one product
    first = None
    for k, source in enumerate(sources):
        if source == "unidentified":
            continue
        if first is None:
            first = k
        elif source != sources[first]:
            raise GeoTiffError("terrain.join_products", a=ordered[first].name, pa=_PRODUCT_NAMES[sources[first]],
                               b=ordered[k].name, pb=_PRODUCT_NAMES[source])

    # 5. the centre cell; a centre no finite cell index reaches lies on no
    # file (math.floor of an infinity or NaN raises, where the browser's
    # Math.floor carries it on to the same refusal)
    fi, fj = (centre.lon - x0) / sx + 0.5, (y0 - centre.lat) / sy + 0.5
    ci = math.floor(fi) if math.isfinite(fi) else None
    cj = math.floor(fj) if math.isfinite(fj) else None

    # 8, before the cap: the centre must lie on a file, so that a centre off
    # the files is told so rather than given a radius that would not help.
    # It lies in a gap between them when the files' bounding box holds it,
    # judged on whole cells so the engines cannot disagree.
    boxes = [(oi, oi + f.layout.width, oj, oj + f.layout.height) for (oi, oj), f in zip(offsets, ordered, strict=True)]
    if ci is None or cj is None or not any(i0 <= ci < i1 and j0 <= cj < j1 for i0, i1, j0, j1 in boxes):
        extent = _bounds_text(_extent(ordered))
        if (ci is not None and cj is not None and min(b[0] for b in boxes) <= ci < max(b[1] for b in boxes)
                and min(b[2] for b in boxes) <= cj < max(b[3] for b in boxes)):
            raise GeoTiffError("terrain.site_gap", where=centre.label, extent=extent)
        raise GeoTiffError("terrain.site_outside", where=centre.label, extent=extent)

    # 6. the half sizes from the centre cell's size
    dx_c, dy_c = wgs84_cell_size(y0 - cj * sy, sx, sy)
    hx = math.ceil((radius + margin) * 1000 / dx_c)
    hy = math.ceil((radius + margin) * 1000 / dy_c)
    hxs = math.ceil(radius * 1000 / dx_c)
    hys = math.ceil(radius * 1000 / dy_c)
    if stride == 0:
        stride = _least_stride(hx, hy, cfg.max_cells)
    if stride > 1:
        hx, hy, hxs, hys = -(-hx // stride), -(-hy // stride), -(-hxs // stride), -(-hys // stride)
    width, height = 2 * hx + 1, 2 * hy + 1

    # 7. the cap, on everything analysed, and the least window analysed. When
    # the margin alone is over the cap no radius fits, and the sentence says
    # to lower the margin rather than offer a radius of 0 km.
    if width * height > cfg.max_cells:
        hx0 = -(-math.ceil(1000 * margin / dx_c) // stride)
        hy0 = -(-math.ceil(1000 * margin / dy_c) // stride)
        if (2 * hx0 + 1) * (2 * hy0 + 1) > cfg.max_cells:
            raise GeoTiffError("terrain.margin_too_many_cells", margin=margin, cap=cfg.max_cells)
        h = math.floor((math.sqrt(cfg.max_cells) - 1) / 2)
        fit = max(0.0, math.floor((h * min(dx_c, dy_c) * stride - 1000 * margin) / 100) / 10)
        raise GeoTiffError("terrain.too_many_cells", radius=radius, margin=margin, cap=cfg.max_cells, fit=fit)
    if width < 3 or height < 3:
        raise GeoTiffError("terrain.too_small", w=width, h=height)

    # 9. the axes, origin plus index times step, never arange or linspace
    lons = x0 + (ci + stride * (np.arange(width) - hx)) * sx
    lats = y0 - (cj + stride * (hy - np.arange(height))) * sy

    # 10. missing 1-degree tiles of a product that publishes no sea tiles
    i_first, j_first = ci - stride * hx, cj - stride * hy
    tile, missing, edges = _missing_tiles(ordered, sources, offsets, sx, i_first, j_first, stride, width,
                                          height)

    # the blocks, counted before any is listed: each costs a decode of its
    # own, so a file cut into tiny blocks is refused here however few cells
    # the window holds. A block holding both window cells and an edge is
    # counted once for each, so the count bounds the decodes from above.
    counts = _count_blocks(ordered, offsets, i_first, j_first, stride, width, height, edges)
    if sum(counts) > cfg.max_blocks:
        most = counts.index(max(counts))
        raise GeoTiffError("terrain.too_many_blocks", file=ordered[most].name, n=sum(counts), cap=cfg.max_blocks)

    blocks = _plan_blocks(ordered, offsets, i_first, j_first, stride, width, height, edges)
    return WindowPlan(
        files=tuple(ordered), sources=sources, declared=_declaration(declared), offsets=tuple(offsets),
        x0=x0, y0=y0, sx=sx, sy=sy, centre=centre, ci=ci, cj=cj, stride=stride, hx=hx, hy=hy,
        hxs=hxs, hys=hys, width=width, height=height, radius_km=radius, margin_km=margin, dx=dx_c, dy=dy_c,
        lons=lons, lats=lats, tile=tile, missing=missing, edges=edges, blocks=blocks,
    )


def _missing_tiles(files: Sequence[ElevationFile], sources: Sequence[str], offsets: Sequence[tuple[int, int]],
                   sx: float, i_first: int, j_first: int, stride: int, width: int, height: int
                   ) -> tuple[int, tuple[tuple[int, int], ...], tuple[PlanEdge, ...]]:
    """The tiles the window meets that no file supplies, and the full edges
    of the supplied tiles beside each, when every file is a whole 1-degree
    tile of a product that publishes no tiles of open sea; else none.

    A tile is numbered on the reference lattice by integer division, so the
    numbering is exact. A file supplies the tile its first cell lies in.
    """
    p = math.floor(1 / sx + 0.5)
    whole = all(source in _SEA_AT_0 for source in sources) and all(
        f.layout.width in (p, p + 1) and f.layout.height in (p, p + 1)
        and _on_degree(f.layout.x0) and _on_degree(f.layout.y0) for f in files)
    if not whole:
        return 0, (), ()
    supplied: dict[tuple[int, int], list[int]] = {}
    for k, (oi, oj) in enumerate(offsets):
        supplied.setdefault((oi // p, oj // p), []).append(k)
    columns = sorted({(i_first + stride * k) // p for k in range(width)})
    rows = sorted({(j_first + stride * q) // p for q in range(height)})
    missing = tuple((tx, ty) for ty in rows for tx in columns if (tx, ty) not in supplied)
    edges = []
    for m, (tx, ty) in enumerate(missing):
        # the neighbour to the north gives its last row, to the south its
        # first, to the west its last column, to the east its first
        for (nx, ny), side in (((tx, ty - 1), "last_row"), ((tx, ty + 1), "first_row"),
                               ((tx - 1, ty), "last_column"), ((tx + 1, ty), "first_column")):
            for k in supplied.get((nx, ny), []):
                lay = files[k].layout
                if side == "last_row":
                    edges.append(PlanEdge(m, k, lay.height - 1, None))
                elif side == "first_row":
                    edges.append(PlanEdge(m, k, 0, None))
                elif side == "last_column":
                    edges.append(PlanEdge(m, k, None, lay.width - 1))
                else:
                    edges.append(PlanEdge(m, k, None, 0))
    return p, missing, tuple(edges)


def _least_stride(hx: int, hy: int, cap: int) -> int:
    """The least stride at which a window of ``hx`` and ``hy`` cells each
    side of its centre holds no more than ``cap`` cells, by binary search.

    The cells held, (2*ceil(hx/s) + 1) * (2*ceil(hy/s) + 1), never grow as
    the stride s grows, and none below sqrt(cells / cap) can fit, so the
    search runs from there to max(hx, hy, 1), where the window is at most 3
    by 3. A cap under 9 then fits nothing, and the cap refuses the window.
    Stepping up a stride at a time instead took longer than any operator
    waits once a damaged cell size made the window enormous.
    """
    def fits(stride: int) -> bool:
        return (2 * -(-hx // stride) + 1) * (2 * -(-hy // stride) + 1) <= cap

    low = max(1, math.ceil(math.sqrt((2 * hx + 1) * (2 * hy + 1) / cap)))
    high = max(hx, hy, 1, low)
    while low < high:
        middle = (low + high) // 2
        if fits(middle):
            high = middle
        else:
            low = middle + 1
    return low


def _blocks_met(extent: int, size: int, first: int, stride: int, n: int) -> int:
    """How many blocks of ``size`` cells along an axis of ``extent`` cells
    hold one of the window's cells ``first + stride*q`` (q from 0 to n - 1),
    in the file's own cell numbering: worked out a block at a time over the
    blocks the window spans, never a cell at a time."""
    low, high = max(first, 0), min(first + stride * (n - 1) + 1, extent)
    if low >= high:
        return 0
    return sum(1 for b in range(low // size, (high - 1) // size + 1)
               if _steps(b * size, min(size, extent - b * size), first, stride, n) is not None)


def _count_blocks(files: Sequence[ElevationFile], offsets: Sequence[tuple[int, int]], i_first: int,
                  j_first: int, stride: int, width: int, height: int, edges: Sequence[PlanEdge]) -> list[int]:
    """The blocks each file gives up, counted without listing them: the
    block rows holding a window row times the block columns holding a window
    column (a strip spans every column, so it is one block column), and the
    blocks holding each full edge, a row of tiles or a column of them (or
    of strips)."""
    counts = []
    for k, (found, (oi, oj)) in enumerate(zip(files, offsets, strict=True)):
        lay = found.layout
        count = (_blocks_met(lay.height, lay.block_height, j_first - oj, stride, height)
                 * _blocks_met(lay.width, lay.block_width, i_first - oi, stride, width))
        for edge in edges:
            if edge.file == k and edge.row is not None:
                count += -(-lay.width // lay.block_width)
            elif edge.file == k:
                count += -(-lay.height // lay.block_height)
        counts.append(count)
    return counts


def _plan_blocks(files: Sequence[ElevationFile], offsets: Sequence[tuple[int, int]], i_first: int,
                 j_first: int, stride: int, width: int, height: int,
                 edges: Sequence[PlanEdge]) -> tuple[PlanBlock, ...]:
    """The blocks to read, file by file in plan order and each file's
    blocks in its own order: those the window's cells lie in, and those
    holding the edges, each block once."""
    planned = []
    for k, (found, (oi, oj)) in enumerate(zip(files, offsets, strict=True)):
        lay = found.layout
        wanted: dict[tuple[int, tuple[int, int] | None], list] = {}
        span_rows = (j_first - oj, j_first - oj + stride * (height - 1) + 1)
        span_cols = (i_first - oi, i_first - oi + stride * (width - 1) + 1)
        for index, offset, length, rows in block_ranges(lay, *span_rows, *span_cols):
            row0, col0 = _block_origin(lay, index, rows)
            count_rows, count_cols = _block_shape(lay, index, rows)
            if (_steps(row0 + oj, count_rows, j_first, stride, height) is None
                    or _steps(col0 + oi, count_cols, i_first, stride, width) is None):
                continue  # a block between the strided cells
            wanted.setdefault((index, rows), [offset, length, True, []])
        for e, edge in enumerate(edges):
            if edge.file != k:
                continue
            if edge.row is not None:
                ranges = block_ranges(lay, edge.row, edge.row + 1, 0, lay.width)
            else:
                assert edge.column is not None
                ranges = block_ranges(lay, 0, lay.height, edge.column, edge.column + 1)
            for index, offset, length, rows in ranges:
                wanted.setdefault((index, rows), [offset, length, False, []])[3].append(e)
        for (index, rows), (offset, length, window, held) in sorted(
                wanted.items(), key=lambda item: (item[0][0], item[0][1] or (-1, -1))):
            planned.append(PlanBlock(k, index, offset, length, rows, window, tuple(held)))
    return tuple(planned)


# ---------------------------------------------------------------------------
# Reading the window
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ElevationRead:
    """A window read from the files, and what the read report says of it.

    ``grid`` holds the heights (row 0 south), its label, credit and
    source; ``assumed_sea`` is True where a missing tile was taken as open
    sea, which has no height (its cells are NaN in ``grid.z`` too).
    ``shown`` is the square shown as rows ``r0:r1`` and columns ``c0:c1``
    of the grid. ``cells`` counts the window; ``voids`` the cells the files
    mark as holding no data, ``implausible`` those whose height could not
    be ground, ``uncovered`` those no file covers (not counting assumed
    sea, which ``assumed`` counts); ``coverage`` is the share of the window
    the files supply.

    ``notes`` is the read report, sentence by sentence in the order the
    apps print it: what was read, how the window was centred when it was
    not on a GPS fix, the margin, the gaps, the sea taken as sea, the voids
    and the implausible heights, and what kind of surface the heights
    describe. ``prompts`` is what is said about single files (a name that
    does not match its georeferencing, a tile laid out as Copernicus's, a
    FABDEM licence). ``surface`` and ``notice`` (the Copernicus liability
    sentence, or None) are also given alone, for the figures and the
    downloads; ``figure_credit`` is the credit line a figure carries.
    ``reasons`` says why each cell holds what it does, row 0 south as in
    the grid: 0 a height, 1 no data in the file, 2 a height that could not
    be ground, 3 no file supplies it (assumed sea included). The read
    report counts them; the parity suite holds them cell by cell.
    """

    grid: ElevationGrid
    assumed_sea: np.ndarray
    shown: tuple[int, int, int, int]
    cells: int
    voids: int
    uncovered: int
    implausible: int
    coverage: float
    centre: WindowCentre
    notes: tuple[str, ...]
    assumed: int = 0
    prompts: tuple[str, ...] = ()
    surface: str = ""
    notice: str | None = None
    figure_credit: str = ""
    reasons: np.ndarray | None = field(default=None, repr=False)
    plan: WindowPlan | None = field(default=None, repr=False)


#: Reads of one file closer than this are made as one, as the browser
#: merges its slices; no merged read is longer than _MERGE_MAX
_MERGE_GAP = 65536
_MERGE_MAX = 16 * 1048576


def _read_blocks(plan: WindowPlan, read_at_by_name: Mapping[str, Callable[[int, int], bytes]]):
    """The bytes of each planned block, in plan order, reading neighbouring
    blocks of a file together."""
    out: list[bytes] = [b""] * len(plan.blocks)
    by_file: dict[int, list[int]] = {}
    for b, block in enumerate(plan.blocks):
        if block.length:
            by_file.setdefault(block.file, []).append(b)
    for k, members in by_file.items():
        read_at = read_at_by_name[plan.files[k].name]
        members.sort(key=lambda b: plan.blocks[b].offset)
        groups: list[list[int]] = []
        start = end = 0
        for b in members:
            block = plan.blocks[b]
            if (groups and block.offset <= end + _MERGE_GAP
                    and max(end, block.offset + block.length) - start <= _MERGE_MAX):
                groups[-1].append(b)
                end = max(end, block.offset + block.length)
            else:
                groups.append([b])
                start, end = block.offset, block.offset + block.length
        for group in groups:
            first = plan.blocks[group[0]].offset
            last = max(plan.blocks[g].offset + plan.blocks[g].length for g in group)
            data = read_at(first, last - first)
            for g in group:
                at = plan.blocks[g].offset - first
                out[g] = data[at:at + plan.blocks[g].length]
    return out


def read_window(plan: WindowPlan, read_at_by_name: Mapping[str, Callable[[int, int], bytes]],
                cfg: TerrainConfig | None = None, progress=None) -> ElevationRead:
    """Read the planned window, block by block, into one grid.

    Each block's samples are judged first (no data, an implausible height,
    or a height), then written where they fall. Where files overlap, the
    first file's height is kept and every other file's height there must be
    the same to the bit; any that differ refuse the join. A missing tile is
    taken as open sea, with no height, only when every height on the full
    edges of the supplied tiles beside it is at or below sea level; any
    other cell no file covers is a gap. ``read_at_by_name`` maps each
    file's name to its ``read_at(offset, length)``. ``progress(fraction,
    label)``, when given, is told how far the read has gone.
    """
    cfg = TerrainConfig() if cfg is None else cfg
    label_read = phrase("terrain.stage_read")
    if progress is not None:
        progress(0.0, label_read)
    width, height, stride = plan.width, plan.height, plan.stride
    i_first, j_first = plan.ci - stride * plan.hx, plan.cj - stride * plan.hy
    win = np.full((height, width), np.nan)          # row 0 north while reading
    why = np.full((height, width), 3, dtype=np.uint8)
    owner = np.full((height, width), -1, dtype=np.int32)
    edge_count = [0] * len(plan.missing)
    edge_land = [False] * len(plan.missing)
    disagreements, largest, pair = 0, 0.0, None
    bounds = (cfg.implausible_below_m, cfg.implausible_above_m)

    data = _read_blocks(plan, read_at_by_name)
    for b, block in enumerate(plan.blocks):
        lay = plan.files[block.file].layout
        values, reasons = decode_block(lay, block.index, data[b], block.rows, bounds)
        row0, col0 = _block_origin(lay, block.index, block.rows)
        if block.window:
            oi, oj = plan.offsets[block.file]
            down = _steps(row0 + oj, values.shape[0], j_first, stride, height)
            across = _steps(col0 + oi, values.shape[1], i_first, stride, width)
            if down is not None and across is not None:
                # window cell (q, k) is the block's cell (stride*q - dr, stride*k - dc)
                (q0, q1), (k0, k1) = down, across
                dr, dc = row0 + oj - j_first, col0 + oi - i_first
                pick = (slice(stride * q0 - dr, stride * q1 - dr + 1, stride),
                        slice(stride * k0 - dc, stride * k1 - dc + 1, stride))
                v, rsn = values[pick], reasons[pick]
                cell = (slice(q0, q1 + 1), slice(k0, k1 + 1))
                w, y, o = win[cell], why[cell], owner[cell]
                value = rsn == 0
                held = y == 0
                clash = value & held & (w != v)
                if clash.any():
                    disagreements += int(clash.sum())
                    largest = max(largest, float(np.abs(w[clash] - v[clash]).max()))
                    if pair is None:
                        first = np.argwhere(clash)[0]
                        pair = (plan.files[int(o[first[0], first[1]])].name, plan.files[block.file].name)
                new = value & ~held
                w[new] = v[new]
                y[new] = 0
                o[new] = block.file
                void = ~value & ~held
                y[void] = np.minimum(y[void], rsn[void])
        for e in block.edges:
            edge = plan.edges[e]
            if edge.row is not None:
                line_values, line_reasons = values[edge.row - row0], reasons[edge.row - row0]
            else:
                assert edge.column is not None
                line_values, line_reasons = values[:, edge.column - col0], reasons[:, edge.column - col0]
            finite = line_values[line_reasons == 0]
            edge_count[edge.missing] += int(finite.size)
            if (finite > cfg.sea_level_m).any():
                edge_land[edge.missing] = True
        if progress is not None:
            progress((b + 1) / len(plan.blocks), label_read)

    if disagreements:
        assert pair is not None
        raise GeoTiffError("terrain.join_disagree", a=pair[0], b=pair[1], n=disagreements, m=largest)

    # a missing tile is sea, with no height, when the full edges beside it
    # hold heights and every one of them is at or below sea level
    sea = np.zeros((height, width), dtype=bool)
    sea_tiles = []
    if plan.missing:
        tile_x = (i_first + stride * np.arange(width)) // plan.tile
        tile_y = (j_first + stride * np.arange(height)) // plan.tile
        for m, (tx, ty) in enumerate(plan.missing):
            if edge_count[m] and not edge_land[m]:
                # a tile is named only when some window cell of it is taken
                # as sea: a window reaching just the row or column an .hgt
                # tile shares with the next meets that tile without a cell
                # of it going uncovered
                hit = (tile_y[:, None] == ty) & (tile_x[None, :] == tx) & (why == 3)
                if hit.any():
                    sea |= hit
                    sea_tiles.append(plan.tile_code((tx, ty)))
    if not (why == 0).any():
        raise GeoTiffError("terrain.no_elevations", radius=plan.radius_km, where=plan.centre.label)

    cells = width * height
    voids = int((why == 1).sum())
    implausible = int((why == 2).sum())
    assumed = int(sea.sum())
    uncovered = int((why == 3).sum()) - assumed
    label, credit, notice, surface, sea_clean = elevation_label_and_credit(plan.files, plan.declared)
    dx, dy = plan.dx * stride, plan.dy * stride
    # the files read are those with a block in the plan, an edge block
    # included, in plan order; the label and credit stay the whole set's
    names = [plan.files[k].name for k in sorted({block.file for block in plan.blocks})]
    grid = ElevationGrid(
        plan.lons, plan.lats, np.ascontiguousarray(win[::-1]), source=label,
        resolution_note=_cell_note(dx, dy), credit=credit, source_id=_set_source(plan.sources),
        files=tuple(names), sea_clean=sea_clean,
    )

    # the summary counts the square shown, which is what its radius describes;
    # the margin read beyond it has a sentence of its own
    r0, r1, c0, c1 = plan.shown
    notes = [phrase("terrain.read_summary", n=len(names), names=and_join(names), cells=(r1 - r0) * (c1 - c0),
                    dx=dx, dy=dy, where=plan.centre.label, radius=plan.radius_km)]
    if plan.centre.note:
        notes.append(plan.centre.note)
    if plan.margin_km > 0:
        notes.append(phrase("terrain.read_margin", margin=plan.margin_km))
    if uncovered and 200 * uncovered < cells:
        notes.append(phrase("terrain.read_uncovered_little", count=uncovered))
    elif uncovered:
        notes.append(phrase("terrain.read_uncovered", pct=_percent(uncovered, cells)))
    if assumed and 200 * assumed < cells:
        notes.append(phrase("terrain.read_assumed_sea_little", count=assumed, n=len(sea_tiles),
                            tiles=and_join(sea_tiles), level=cfg.sea_level_m,
                            product=_PRODUCT_NAMES[_set_source(plan.sources)]))
    elif assumed:
        notes.append(phrase("terrain.read_assumed_sea", pct=_percent(assumed, cells), n=len(sea_tiles),
                            tiles=and_join(sea_tiles), level=cfg.sea_level_m,
                            product=_PRODUCT_NAMES[_set_source(plan.sources)]))
    if voids:
        notes.append(phrase("terrain.read_voids", n=voids))
    if implausible:
        notes.append(phrase("terrain.read_implausible", n=implausible, lo=cfg.implausible_below_m,
                            hi=cfg.implausible_above_m))
    notes.append(surface)
    figure_credit = (phrase("terrain.figure_credit", label=label, credit=credit, dx=dx, dy=dy) if credit
                     else phrase("terrain.figure_credit_bare", label=label, dx=dx, dy=dy))
    prompts = tuple(note for f in plan.files for note in file_notes(f, plan.declared))
    if progress is not None:
        progress(1.0, label_read)
    return ElevationRead(
        grid=grid, assumed_sea=sea[::-1].copy(), shown=plan.shown, cells=cells, voids=voids,
        uncovered=uncovered, implausible=implausible, coverage=(cells - uncovered - assumed) / cells,
        centre=plan.centre, notes=tuple(notes), assumed=assumed, prompts=prompts, surface=surface,
        notice=notice, figure_credit=figure_credit, reasons=why[::-1].copy(), plan=plan,
    )


def _percent(count: int, cells: int) -> int:
    """``count`` as a whole percentage of ``cells``, half up, in integers
    alone so that both engines give the same figure: a read report saying
    "100%" while some cell was read would contradict itself, so a share
    short of the whole is at most 99. A share under half a percent has a
    sentence of its own ("less than 1%") and never comes here."""
    pct = (200 * count + cells) // (2 * cells)
    return 99 if count < cells and pct == 100 else pct


def read_elevation(sources: Sequence[tuple[str, str | Path | bytes]], site=None, radius_km: float | None = None,
                   cfg: TerrainConfig | None = None, stride: int = 1, margin_km: float | None = None,
                   declared: tuple[str, str] = ("detect", ""), progress=None) -> ElevationRead:
    """Read the window around a site from GeoTIFF or ``.hgt`` files.

    ``sources`` are ``(name, path or bytes)`` pairs, the name being what
    the operator called the file (a kept upload's path need not end in
    it). ``radius_km`` is the half-side of the square shown, by default
    ``cfg.analysis_radius_km``; ``margin_km`` the margin analysed beyond
    it, by default ``cfg.analysis_buffer_km``. The files are opened for
    their layouts, the window is planned and only the blocks it needs are
    read: a 48 MB tile gives up a few megabytes for a 10 km window.
    """
    cfg = TerrainConfig() if cfg is None else cfg
    radius = cfg.analysis_radius_km if radius_km is None else radius_km
    with contextlib.ExitStack() as stack:
        readers: dict[str, Callable[[int, int], bytes]] = {}
        files = []
        for name, source in sources:
            size, readers[name] = _reader(source, stack)
            files.append(open_elevation_file(name, size, readers[name]))
        centre = window_centre(site, files)
        plan = plan_window(files, centre, radius, cfg, stride, margin_km, declared)
        return read_window(plan, readers, cfg, progress)


def _reader(source: str | Path | bytes, stack: contextlib.ExitStack
            ) -> tuple[int, Callable[[int, int], bytes]]:
    """A file's size and its ``read_at(offset, length)``, seeking in the
    file on disk (kept open until ``stack`` closes) or slicing its bytes."""
    if isinstance(source, (bytes, bytearray, memoryview)):
        data = bytes(source)
        return len(data), lambda offset, length: data[offset:offset + length]
    handle = stack.enter_context(Path(source).open("rb"))  # noqa: SIM115 - the stack closes it

    def read_at(offset: int, length: int) -> bytes:
        handle.seek(offset)
        return handle.read(length)

    return Path(source).stat().st_size, read_at
