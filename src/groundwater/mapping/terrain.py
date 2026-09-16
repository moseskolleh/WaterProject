"""Topography: elevation grids read from the field, and the maps drawn from them.

This module draws the land surface. It does not carry one. No digital
elevation model is bundled with the toolkit and none is downloaded, so
every topographic map here is drawn from a file the operator supplied,
and the figure names that file's source on its own face.

That is deliberate. A topographic map is read as measurement - a
hydrogeologist looking at a contour will site a borehole in the valley it
draws - and an elevation surface interpolated from the handful of spot
heights a survey happens to record is not a measurement of the landscape.
It is a guess about the ground between the pegs. So the survey's own
elevations are drawn as spot heights and as a ground profile along the
traverse, where they are exactly what they claim to be, and the contoured
map waits for a real elevation model.

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

import matplotlib.pyplot as plt
import numpy as np

from ..config import HouseStyle
from ..models import SiteMetadata
from ..plotting import figure_context, save_figure
from .regional import (
    ADMIN_CREDIT,
    AreaWindow,
    _geo_axes_finish,
    _mark_site,
    area_window,
    load_admin,
)

#: SRTM marks a void with this value; it is not an elevation.
_SRTM_VOID = -32768


def _land_cmap():
    """Matplotlib's ``terrain`` ramp with its bathymetry cut off.

    The lower quarter of ``terrain`` is blue, because the ramp is built
    for maps that carry the sea bed as well as the land. Used on a land
    elevation map it draws everything under about 25 m as water - which
    over the Sierra Leone coastal plain is most of the ground a borehole
    gets drilled into, and reads as a lagoon that is not there.
    """
    from matplotlib.colors import LinearSegmentedColormap

    base = plt.get_cmap("terrain")
    return LinearSegmentedColormap.from_list(
        "terrain_land", base(np.linspace(0.25, 1.0, 256))
    )

#: What ``.hgt`` side lengths mean, by the number of int16 samples in the file.
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
    """

    lons: np.ndarray
    lats: np.ndarray
    z: np.ndarray
    source: str = "user-supplied elevation model"
    #: metres per sample, for the resolution note on the figure
    resolution_note: str = ""

    def __post_init__(self) -> None:
        self.lons = np.asarray(self.lons, dtype=float)
        self.lats = np.asarray(self.lats, dtype=float)
        self.z = np.asarray(self.z, dtype=float)
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

    def window(self, lon: float, lat: float, radius_km: float) -> "ElevationGrid":
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
        return ElevationGrid(
            self.lons[x0:x1], self.lats[y0:y1], self.z[y0:y1, x0:x1],
            source=self.source, resolution_note=self.resolution_note,
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
        raise ValueError(
            f"'{path.name}' does not name its corner. An SRTM tile is named "
            "for its south-west corner, as in N08W013.hgt; the file itself "
            "carries no header saying where on Earth it is."
        )
    ns, lat_deg, ew, lon_deg = match.groups()
    lat0 = float(lat_deg) * (1 if ns == "N" else -1)
    lon0 = float(lon_deg) * (1 if ew == "E" else -1)

    raw = np.fromfile(str(path), dtype=">i2")
    side = int(round(math.sqrt(raw.size)))
    if side * side != raw.size or side not in _HGT_SIDES:
        raise ValueError(
            f"'{path.name}' holds {raw.size} samples, which is not a square "
            f"SRTM tile ({' or '.join(f'{s}x{s}' for s in _HGT_SIDES)})."
        )
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
    with open(path, "r", encoding="utf-8") as fh:
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
    with open(path, "r", encoding="utf-8") as fh:
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
    for axis, values in (("longitudes", lons), ("latitudes", lats)):
        steps = np.diff(values)
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


# ---------------------------------------------------------------------------
# Derived surfaces
# ---------------------------------------------------------------------------

def hillshade(
    grid: ElevationGrid,
    azimuth_deg: float = 315.0,
    altitude_deg: float = 45.0,
    vertical_exaggeration: float = 1.0,
) -> np.ndarray:
    """Shaded relief from the grid, 0 (shadow) to 1 (lit).

    The standard north-west sun, because relief lit from any other
    quarter reads as inverted to most people - valleys become ridges.

    The cell size is computed in metres at the grid's own latitude, so
    the slopes are real slopes and not a function of how far north the
    tile happens to be.
    """
    mean_lat = float(np.mean(grid.lats))
    dx = float(np.mean(np.diff(grid.lons))) * 111320.0 * math.cos(math.radians(mean_lat))
    dy = float(np.mean(np.diff(grid.lats))) * 110574.0
    z = np.where(np.isfinite(grid.z), grid.z, np.nanmean(grid.z))
    if not np.any(np.isfinite(z)):
        return np.full(grid.z.shape, 0.5)
    gy, gx = np.gradient(z * vertical_exaggeration, dy, dx)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az = math.radians(360.0 - azimuth_deg + 90.0)
    alt = math.radians(altitude_deg)
    shaded = (
        math.sin(alt) * np.cos(slope)
        + math.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    )
    return np.clip((shaded + 1.0) / 2.0, 0.0, 1.0)


def slope_percent(grid: ElevationGrid) -> np.ndarray:
    """Ground slope as a percentage, for siting and access notes."""
    mean_lat = float(np.mean(grid.lats))
    dx = float(np.mean(np.diff(grid.lons))) * 111320.0 * math.cos(math.radians(mean_lat))
    dy = float(np.mean(np.diff(grid.lats))) * 110574.0
    gy, gx = np.gradient(grid.z, dy, dx)
    return np.hypot(gx, gy) * 100.0


def _contour_interval(z: np.ndarray) -> float:
    """A round contour interval giving roughly a dozen lines.

    Sierra Leone's basement plains and the Freetown peninsula differ by
    two orders of magnitude in relief, so a fixed interval draws either
    two contours or four hundred.
    """
    finite = z[np.isfinite(z)]
    if finite.size == 0:
        return 10.0
    relief = float(finite.max() - finite.min())
    if relief <= 0:
        return 10.0
    target = relief / 12.0
    nice = 10 ** math.floor(math.log10(target))
    for mult in (10, 5, 2, 1):
        if nice * mult <= target * 2:
            return max(nice * mult, 1.0)
    return max(nice, 1.0)


# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------

def plot_topographic_map(
    grid: ElevationGrid,
    site: SiteMetadata | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    radius_km: float | None = None,
    title: str | None = None,
    contour_interval_m: float | None = None,
    spot_heights: list[tuple[float, float, str]] | None = None,
    show_hillshade: bool = True,
    admin_path: str | Path | None = None,
):
    """Topographic map of the study area: relief, contours and spot heights.

    ``grid`` is the elevation model; ``radius_km`` cuts a local window
    around the site out of it. The figure carries the model's own source
    and sample spacing, because a contour drawn from 90 m SRTM through a
    5 km window is a 90 m contour however finely it is plotted, and a
    reader deciding where to put a borehole is entitled to know that.

    ``spot_heights`` are ``(lon, lat, label)`` triples - the survey's own
    levelled points. They are drawn as measured values on top of the
    modelled surface, not blended into it: where the two disagree the
    reader can see both and the survey is the one that was on the ground.
    """
    style = style or HouseStyle()
    if radius_km is not None:
        window = area_window(site, radius_km, admin_path) if site is not None else None
        if window is not None:
            grid = grid.window(window.lon, window.lat, radius_km)
        else:
            centre_lon = float(np.mean(grid.lons))
            centre_lat = float(np.mean(grid.lats))
            grid = grid.window(centre_lon, centre_lat, radius_km)
    else:
        window = area_window(site, None, admin_path) if site is not None else None

    finite = grid.z[np.isfinite(grid.z)]
    if finite.size == 0:
        raise ValueError(
            "the elevation model holds no values over this window - every "
            "sample is a void. A map of voids is not a map of the ground."
        )
    interval = contour_interval_m or _contour_interval(grid.z)
    lo = math.floor(float(finite.min()) / interval) * interval
    hi = math.ceil(float(finite.max()) / interval) * interval
    levels = np.arange(lo, hi + interval, interval)

    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 5.6))
        extent = (
            float(grid.lons.min()), float(grid.lons.max()),
            float(grid.lats.min()), float(grid.lats.max()),
        )
        land = _land_cmap()
        ax.imshow(
            grid.z, extent=extent, origin="lower", cmap=land,
            vmin=float(finite.min()), vmax=float(finite.max()),
            interpolation="bilinear", zorder=1, aspect="auto",
        )
        if show_hillshade:
            ax.imshow(
                hillshade(grid), extent=extent, origin="lower", cmap="gray",
                alpha=0.35, interpolation="bilinear", zorder=2, aspect="auto",
            )
        mesh_lon, mesh_lat = np.meshgrid(grid.lons, grid.lats)
        if len(levels) > 1:
            cs = ax.contour(
                mesh_lon, mesh_lat, grid.z, levels=levels,
                colors="#5A3A1E", linewidths=0.6, zorder=3,
            )
            ax.clabel(cs, cs.levels[::2], fmt="%g", fontsize=6.5, inline=True)
        sm = plt.cm.ScalarMappable(
            cmap=land,
            norm=plt.Normalize(vmin=float(finite.min()), vmax=float(finite.max())),
        )
        cbar = fig.colorbar(sm, ax=ax, pad=0.02, shrink=0.85)
        cbar.set_label("Ground elevation (m)")

        # the survey's own levelled points, over the modelled surface
        for lon, lat, label in spot_heights or []:
            ax.plot(lon, lat, "o", ms=5, mfc="white", mec="#222222", mew=1.1,
                    zorder=7)
            ax.annotate(label, xy=(lon, lat), xytext=(5, 4),
                        textcoords="offset points", fontsize=7.5,
                        fontweight="bold", color="#222222", zorder=7)

        outline, _ = load_admin(admin_path)
        for ring in outline.rings:
            ax.plot(ring[:, 0], ring[:, 1], color="#333333", lw=1.0, zorder=5)
        if site is not None:
            _mark_site(ax, site, "#C1272D")
        ax.set_xlim(extent[0], extent[1])
        ax.set_ylim(extent[2], extent[3])
        credit = grid.source
        if grid.resolution_note:
            credit += f", {grid.resolution_note} sampling"
        _geo_axes_finish(ax, float(np.mean(ax.get_ylim())),
                         f"Elevation: {credit}. {ADMIN_CREDIT}")
        ax.text(
            0.01, 0.985,
            f"Contour interval {interval:g} m",
            transform=ax.transAxes, ha="left", va="top", fontsize=7,
            color="#333333", zorder=9,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#CCCCCC",
                      alpha=0.9),
        )
        if title is None:
            where = _where_label(site, window)
            title = f"Topographic map - {where}" if where else "Topographic map"
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def _where_label(site: SiteMetadata | None, window: AreaWindow | None) -> str:
    if window is not None:
        return window.label
    if site is not None and (site.community or ""):
        return site.community
    return ""


def plot_ground_profile(
    chainage_m: list[float] | np.ndarray,
    elevation_m: list[float] | np.ndarray,
    labels: list[str] | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Ground surface along the survey traverse",
    grid: ElevationGrid | None = None,
    lonlats: list[tuple[float, float]] | None = None,
):
    """The land surface along the traverse, from the survey's own levels.

    This is the honest topographic figure a survey can always draw: the
    elevations are measured at the pegs, and between them the line is
    drawn straight and says so. Where an elevation model is also
    supplied, its surface is drawn behind as a second line, so the two
    can be compared rather than silently averaged - a metre of
    disagreement over 200 m of traverse changes which end of the line
    the water runs to.
    """
    style = style or HouseStyle()
    chainage = np.asarray(chainage_m, dtype=float)
    elevation = np.asarray(elevation_m, dtype=float)
    if chainage.size != elevation.size:
        raise ValueError(
            f"{chainage.size} chainages and {elevation.size} elevations: a "
            "ground profile needs one elevation per station."
        )
    known = np.isfinite(elevation)
    if known.sum() < 2:
        raise ValueError(
            f"{int(known.sum())} of {elevation.size} stations carry an "
            "elevation. A ground profile needs at least two levelled "
            "points; record them on the field sheet."
        )
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 2.6))
        if grid is not None and lonlats is not None:
            modelled = np.array([
                grid.elevation_at(lon, lat) if grid.covers(lon, lat) else np.nan
                for lon, lat in lonlats
            ], dtype=float)
            if np.isfinite(modelled).sum() >= 2:
                ax.plot(chainage, modelled, "-", color="#888888", lw=1.2,
                        label=f"Elevation model ({grid.source})", zorder=2)
        ax.plot(chainage[known], elevation[known], "-o", color=style.accent_color,
                lw=1.8, ms=5, mfc="white", mew=1.4, label="Levelled at the station",
                zorder=3)
        ax.fill_between(chainage[known], elevation[known],
                        float(np.nanmin(elevation)) - 2.0,
                        color=style.accent_color, alpha=0.08, zorder=1)
        for x, y, label in zip(
            chainage, elevation, labels or [""] * chainage.size, strict=True
        ):
            if not math.isfinite(y) or not label:
                continue
            ax.annotate(label, xy=(x, y), xytext=(0, 7),
                        textcoords="offset points", ha="center", fontsize=7.5,
                        fontweight="bold", color="#222222")
        if known.sum() < elevation.size:
            ax.text(
                0.5, 0.02,
                f"{int(elevation.size - known.sum())} of {elevation.size} "
                "stations recorded no elevation and are not drawn.",
                transform=ax.transAxes, ha="center", va="bottom", fontsize=7,
                color="#B00020",
            )
        ax.set_xlabel("Distance along traverse (m)")
        ax.set_ylabel("Elevation (m)")
        ax.set_title(title)
        ax.legend(loc="best", fontsize=7.5)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig
