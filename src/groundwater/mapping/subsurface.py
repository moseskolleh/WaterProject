"""Subsurface maps and sections from the survey's own measurements.

Everything here is drawn from what the soundings measured and the
inversion interpreted, so unlike the geology and aquifer layers - which
are national datasets read at a site - these are maps of this site, at
the scale the site was surveyed at.

Five things the survey already knows and did not previously draw:

* **depth to bedrock**, the overburden the driller passes through,
* **aquifer thickness**, the saturated weathered and fractured section
  that decides whether the borehole is worth completing,
* **bedrock elevation**, the same surface as a landform rather than a
  depth - which is what shows a buried valley, where basement groundwater
  collects,
* **protective capacity**, the longitudinal conductance of the cover, so
  a productive but unprotected aquifer is not sited beside a latrine,
* **the apparent-resistivity pseudo-section**, the measurements
  themselves laid out along the traverse before any inversion has been
  believed.

Every interpolated surface is masked to the hull of the soundings, the
same rule the iso-resistivity and overburden maps already follow: a
contour 400 m from the nearest sounding is the interpolator continuing a
trend, and somebody will drill on it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap, LogNorm

from ..config import HouseStyle
from ..plotting import figure_context, save_figure
from .maps import MapPoint, _interpolated_map

#: The crystalline-basement protective-capacity classes, as
#: ``groundwater.ves.interpret`` rates them. The breaks are the standard
#: longitudinal-conductance classification and the colours run from
#: exposed (red) to protected (blue); the map and its key read from this
#: one table, so the two can never disagree.
PROTECTIVE_CLASSES: tuple[tuple[float, float, str, str], ...] = (
    (0.0, 0.1, "poor", "#B2182B"),
    (0.1, 0.2, "weak", "#EF8A62"),
    (0.2, 0.7, "moderate", "#FDDBC7"),
    (0.7, 5.0, "good", "#92C5DE"),
    (5.0, math.inf, "very good", "#2166AC"),
)

SUBSURFACE_CREDIT = (
    "Subsurface interpretation from this survey's vertical electrical "
    "soundings; no external dataset"
)


# ---------------------------------------------------------------------------
# Turning interpretations into mappable points
# ---------------------------------------------------------------------------

def _positioned(interpretations: list) -> list:
    return [
        interp for interp in interpretations
        if getattr(interp, "site_easting", None) is not None
        and getattr(interp, "site_northing", None) is not None
    ]


def subsurface_map_points(
    interpretations: list,
    attribute: str,
) -> list[MapPoint]:
    """Build :class:`~groundwater.mapping.maps.MapPoint` list for one quantity.

    ``attribute`` names a field of
    :class:`~groundwater.ves.interpret.SiteInterpretation`, for example
    ``depth_to_basement_m`` or ``aquifer_thickness_m``. Soundings without
    a position are dropped - they cannot be put on a map - and so are
    those whose value the interpretation left unset, because a sounding
    whose curve never reached basement has no depth to basement and
    plotting a zero there would draw basement at the surface.
    """
    points: list[MapPoint] = []
    for interp in _positioned(interpretations):
        value = getattr(interp, attribute, None)
        if value is None or not math.isfinite(float(value)):
            continue
        points.append(
            MapPoint(
                label=interp.sounding_id or "VES",
                easting=float(interp.site_easting),
                northing=float(interp.site_northing),
                value=float(value),
                kind="VES point",
            )
        )
    return points


def bedrock_elevation_points(interpretations: list) -> list[MapPoint]:
    """Bedrock surface elevation: ground level less the depth to basement.

    Needs both numbers at the same sounding. A survey that recorded no
    elevations gives an empty list rather than a bedrock surface at
    sea level, which is what subtracting a depth from nothing amounts to.
    """
    points: list[MapPoint] = []
    for interp in _positioned(interpretations):
        ground = getattr(interp, "site_elevation_m", None)
        depth = getattr(interp, "depth_to_basement_m", None)
        if ground is None or depth is None:
            continue
        points.append(
            MapPoint(
                label=interp.sounding_id or "VES",
                easting=float(interp.site_easting),
                northing=float(interp.site_northing),
                value=float(ground) - float(depth),
                kind="VES point",
            )
        )
    return points


def common_ab2_spacings(soundings: list) -> list[float]:
    """The AB/2 spacings every sounding in the survey actually measured.

    An iso-resistivity map compares one spacing across the site, so the
    spacings worth offering are the ones present in every curve. Offering
    a spacing two of five soundings skipped produces a map interpolated
    from three points and labelled as though it came from five.
    """
    if not soundings:
        return []
    shared: set[float] | None = None
    for sounding in soundings:
        present = {round(float(v), 4) for v in sounding.ab2 if math.isfinite(v)}
        shared = present if shared is None else (shared & present)
    return sorted(shared or set())


def iso_resistivity_points(
    soundings: list,
    ab2: float,
    tolerance: float = 1e-6,
) -> list[MapPoint]:
    """Measured apparent resistivity at one spacing, at each sounding.

    The reading is taken, not interpolated: a curve without that spacing
    contributes nothing rather than a value read off between its points.
    Where a Schlumberger segment change recorded the same AB/2 twice with
    different MN, the readings are averaged geometrically, which is how
    the two overlapping segments are spliced everywhere else in the
    toolkit.
    """
    points: list[MapPoint] = []
    for sounding in soundings:
        site = getattr(sounding, "site", None)
        if site is None or site.easting is None or site.northing is None:
            continue
        hits = [
            float(rho)
            for spacing, rho in zip(sounding.ab2, sounding.rho_app, strict=True)
            if abs(float(spacing) - ab2) <= max(tolerance, abs(ab2) * 1e-6)
            and math.isfinite(rho) and rho > 0
        ]
        if not hits:
            continue
        value = math.exp(sum(math.log(h) for h in hits) / len(hits))
        points.append(
            MapPoint(
                label=sounding.sounding_id or "VES",
                easting=float(site.easting),
                northing=float(site.northing),
                value=value,
                kind="VES point",
            )
        )
    return points


def _require_points(points: list[MapPoint], what: str, need: int = 3) -> None:
    if len(points) < need:
        raise ValueError(
            f"{'an' if what[:1] in 'aeiou' else 'a'} {what} needs at least "
            f"{need} soundings that carry both a "
            f"position and the value; {len(points)} do. Record the GPS "
            "position of every sounding on the field sheet."
        )


# ---------------------------------------------------------------------------
# The interpolated subsurface maps
# ---------------------------------------------------------------------------

def depth_to_bedrock_map(
    interpretations: list,
    zone: int,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Depth to bedrock",
):
    """Overburden the driller passes through before fresh basement.

    The same surface as the overburden thickness map, built from the
    interpretations rather than from a hand-assembled point list, so the
    Maps page can draw it without the caller re-deriving anything.
    """
    points = subsurface_map_points(interpretations, "depth_to_basement_m")
    _require_points(points, "depth to bedrock map")
    return _interpolated_map(
        points, zone, title=title, cbar_label="Depth to bedrock (m)",
        path=path, style=style, log_scale=False, cmap="YlOrBr",
    )


def aquifer_thickness_map(
    interpretations: list,
    zone: int,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Interpreted aquifer thickness",
):
    """Saturated weathered and fractured thickness, the yield's raw material."""
    points = subsurface_map_points(interpretations, "aquifer_thickness_m")
    _require_points(points, "aquifer thickness map")
    return _interpolated_map(
        points, zone, title=title,
        cbar_label="Interpreted aquifer thickness (m)",
        path=path, style=style, log_scale=False, cmap="GnBu",
    )


def bedrock_elevation_map(
    interpretations: list,
    zone: int,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Bedrock surface elevation",
):
    """The basement surface as a landform.

    A depth map and an elevation map of the same contact are different
    pictures on sloping ground: the deepest overburden is not
    necessarily the lowest bedrock, and it is the low bedrock - the
    buried valley - that basement groundwater drains towards.
    """
    points = bedrock_elevation_points(interpretations)
    _require_points(points, "bedrock elevation map")
    return _interpolated_map(
        points, zone, title=title,
        cbar_label="Bedrock surface elevation (m)",
        path=path, style=style, log_scale=False, cmap="terrain",
    )


def transverse_resistance_map(
    interpretations: list,
    zone: int,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Transverse resistance (Dar-Zarrouk T)",
):
    """Transverse resistance, which tracks transmissivity in basement terrain.

    T = Sum(h x rho) over the overburden. It is not transmissivity and is
    not labelled as though it were: the two correlate where the
    resistivity of the water is roughly constant across a small area,
    which is the assumption, not a result.
    """
    points = subsurface_map_points(interpretations, "transverse_resistance_t")
    _require_points(points, "transverse resistance map")
    return _interpolated_map(
        points, zone, title=title,
        cbar_label="Transverse resistance (ohm m2)",
        path=path, style=style, log_scale=True, cmap="magma",
    )


def protective_capacity_map(
    interpretations: list,
    zone: int,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Aquifer protective capacity",
):
    """Longitudinal conductance of the cover, in its standard classes.

    Drawn in classes rather than on a continuous ramp, because the
    decision this map informs is categorical - is this aquifer protected
    enough to site a borehole near a latrine or a cattle crossing - and a
    smooth ramp invites reading a difference between 0.68 and 0.71
    siemens that the method does not support.

    Class colours and breaks come from :data:`PROTECTIVE_CLASSES`, the
    same table ``groundwater.ves.interpret`` rates a sounding against, so
    a point's colour and the word in its report cannot disagree.
    """
    style = style or HouseStyle()
    points = subsurface_map_points(interpretations, "protective_conductance_s")
    _require_points(points, "protective capacity map", need=1)

    bounds = [c[0] for c in PROTECTIVE_CLASSES]
    # the top class is unbounded; contouring needs a finite ceiling, so use
    # the largest value on this map or the class floor, whichever is bigger
    bounds.append(max(max(p.value for p in points if p.value is not None), 5.0) * 1.05)
    cmap = ListedColormap([c[3] for c in PROTECTIVE_CLASSES])
    norm = BoundaryNorm(bounds, cmap.N)

    from matplotlib.patches import Patch

    from .maps import (
        _clip_to_surveyed_ground,
        _extent,
        _figsize,
        _format_grid,
        _no_surface_note,
        _north_arrow,
        _pad_limits,
        _scale_bar,
        _surface,
    )

    with figure_context(style):
        fig, ax = plt.subplots(figsize=_figsize(style, *_extent(points)))
        _pad_limits(ax, points)
        if len(points) >= 3:
            e = np.array([p.easting for p in points])
            n = np.array([p.northing for p in points])
            v = np.array([p.value for p in points], dtype=float)
            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()
            gx, gy = np.meshgrid(np.linspace(x0, x1, 200), np.linspace(y0, y1, 200))
            grid = _surface(e, n, v, gx, gy)
            if grid is not None:
                grid, _clipped = _clip_to_surveyed_ground(ax, grid, e, n, gx, gy)
                ax.contourf(gx, gy, grid, levels=bounds, cmap=cmap, norm=norm,
                            alpha=0.8)
            else:
                _no_surface_note(ax, len(points))
        for p in points:
            colour = _protective_colour(p.value)
            ax.plot(p.easting, p.northing, "o", ms=11, mfc=colour,
                    mec="#222222", mew=1.3, zorder=6)
            ax.annotate(
                f"{p.label}\n{p.value:.2f} S", xy=(p.easting, p.northing),
                xytext=(9, 6), textcoords="offset points", fontsize=8,
                fontweight="bold", color="#222222", zorder=7,
            )
        _format_grid(ax, zone)
        _scale_bar(ax, style)
        _north_arrow(ax)
        ax.legend(
            handles=[
                Patch(facecolor=colour, edgecolor="#222222",
                      label=f"{name} ({lo:g}"
                            + (f"-{hi:g} S)" if math.isfinite(hi) else "+ S)"))
                for lo, hi, name, colour in PROTECTIVE_CLASSES
            ],
            loc="lower right", fontsize=7, framealpha=0.95,
            title="Longitudinal conductance of the cover",
            title_fontsize=7.5,
        )
        ax.set_title(title)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig


def _protective_colour(conductance: float | None) -> str:
    if conductance is None:
        return "#BBBBBB"
    for lo, hi, _name, colour in PROTECTIVE_CLASSES:
        if lo <= conductance < hi:
            return colour
    return PROTECTIVE_CLASSES[-1][3]


# ---------------------------------------------------------------------------
# The traverse: putting the soundings on a line
# ---------------------------------------------------------------------------

@dataclass
class TraverseProfile:
    """Soundings projected onto the best-fit line through them.

    ``chainage_m`` is the distance along that line from its first
    station, which is what a cross-section's horizontal axis wants.
    ``offset_m`` is how far each sounding sits off the line, and it is
    the number that decides whether a section through these points means
    anything: soundings scattered 300 m either side of a line are not a
    section, they are a map drawn edge-on, and ``straightness`` says so
    rather than leaving the figure to imply otherwise.
    """

    labels: list[str]
    chainage_m: np.ndarray
    offset_m: np.ndarray
    #: the largest perpendicular offset, in metres
    max_offset_m: float
    #: max offset as a fraction of the traverse length
    straightness: float
    #: bearing of the profile line, degrees clockwise from north
    bearing_deg: float
    eastings: np.ndarray
    northings: np.ndarray

    @property
    def is_collinear(self) -> bool:
        """True when the soundings sit close enough to a line to section.

        A tenth of the traverse length is the working rule: on a 400 m
        line that is 40 m, which is inside the positional error of a
        handheld GPS under canopy and well inside the lateral resolution
        of a Schlumberger sounding.
        """
        return self.straightness <= 0.10

    @property
    def length_m(self) -> float:
        return float(self.chainage_m.max() - self.chainage_m.min())


def traverse_profile(interpretations: list) -> TraverseProfile:
    """Project positioned soundings onto the best-fit line through them.

    The line is the principal axis of the positions (total least
    squares), not the line joining the first and last sounding: a
    traverse with a dog-leg in the middle has no reason to be summarised
    by its endpoints, and the endpoints are exactly the two stations most
    likely to have been added last and placed loosely.

    Soundings are returned in order along the line, which is the order a
    section draws them in. That is not always field order, and where it
    differs, field order was drawing the section back on itself.
    """
    positioned = _positioned(interpretations)
    if len(positioned) < 2:
        raise ValueError(
            f"{len(positioned)} of {len(interpretations)} soundings carry a "
            "position. A traverse needs at least two: record the GPS "
            "position of every sounding on the field sheet."
        )
    e = np.array([float(i.site_easting) for i in positioned])
    n = np.array([float(i.site_northing) for i in positioned])
    labels = [i.sounding_id or f"VES {k + 1}" for k, i in enumerate(positioned)]

    centre = np.array([e.mean(), n.mean()])
    coords = np.column_stack([e, n]) - centre
    # the principal axis is the first right singular vector
    _u, _s, vt = np.linalg.svd(coords, full_matrices=False)
    direction = vt[0]
    # The sign of a singular vector is arbitrary, so the same five soundings
    # handed over in a different order came back as a section drawn the other
    # way round - the same ground, mirrored, with the chainages reversed. The
    # line is made to run eastwards, or northwards where it is within a degree
    # of north-south, so a survey has one section rather than two.
    if direction[0] < 0 or (direction[0] == 0 and direction[1] < 0):
        direction = -direction
    normal = np.array([-direction[1], direction[0]])
    along = coords @ direction
    across = coords @ normal

    order = np.argsort(along)
    along, across = along[order], across[order]
    chainage = along - along.min()
    length = float(chainage.max()) or 1.0
    max_offset = float(np.abs(across).max())
    bearing = (math.degrees(math.atan2(direction[0], direction[1]))) % 180.0
    return TraverseProfile(
        labels=[labels[k] for k in order],
        chainage_m=chainage,
        offset_m=across,
        max_offset_m=max_offset,
        straightness=max_offset / length,
        bearing_deg=bearing,
        eastings=e[order],
        northings=n[order],
    )


def geoelectric_section_along_traverse(
    interpretations: list,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str | None = None,
    depth_max: float | None = None,
):
    """The interpreted section, drawn at the soundings' real spacing.

    :func:`groundwater.ves.plots.plot_geoelectric_section` already draws
    this picture, but it has to be told where the soundings are and its
    default is to space them 100 m apart in the order they were handed
    over. A survey that walked 40 m between two pegs and 300 m to the
    next came out evenly spaced, which reads as a uniformly thickening
    weathered zone when what the ground did was thicken over 40 m and
    hold for 300.

    This projects the soundings onto the best-fit line through their
    recorded positions and hands the real chainages over, so the
    horizontal axis is ground distance. Where the soundings are too
    scattered for a line to mean anything the title says so, rather than
    the figure implying a section nobody could walk.
    """
    from ..ves.plots import plot_geoelectric_section

    profile = traverse_profile(interpretations)
    by_id = {
        (interp.sounding_id or f"VES {k + 1}"): interp
        for k, interp in enumerate(interpretations)
    }
    ordered = [by_id[label] for label in profile.labels if label in by_id]
    if len(ordered) < 2:
        raise ValueError(
            "the traverse and the interpretations share fewer than two "
            "sounding identifiers, so the section cannot be placed"
        )
    if title is None:
        title = (
            f"Interpreted geoelectric section, {profile.length_m:.0f} m along "
            f"bearing {profile.bearing_deg:.0f} degrees"
        )
        if not profile.is_collinear:
            title += (
                f" (soundings up to {profile.max_offset_m:.0f} m off the line)"
            )
    # A column stands for the ground the sounding sampled, which is about
    # its largest electrode half-spacing either side of the peg - not for
    # an equal share of the profile. Two Rokel soundings 20 km apart came
    # out as two columns 8 km wide, which claims each sounding measured
    # 8 km of ground.
    reach = max(
        (float(getattr(i, "investigation_depth_m", 0.0)) for i in ordered),
        default=0.0,
    )
    if depth_max is None and reach > 0:
        # the section is drawn to the depth the soundings resolve, the same
        # rule as every other figure, and never so shallow that a fitted
        # interface falls off the bottom of it
        deepest_interface = max(
            (float(i.model.depths_top[-1]) for i in ordered if i.model.n_layers > 1),
            default=0.0,
        )
        depth_max = max(reach, deepest_interface * 1.2 + 2.0)
    # A boundary is correlated between two stations only when they are
    # within the correlation rule of each other. Two Rokel soundings 20.7 km
    # apart used to come out as a 60 m section with a dashed horizon joining
    # them: a line between two points in different chiefdoms, called a
    # section. Where no pair of neighbours is within reach there is no
    # section to draw and the caller is told why; where some are, the
    # boundaries are correlated across those gaps only.
    gaps = np.diff(np.asarray(profile.chainage_m, float))
    wide = _wide_gaps(profile, reach)
    if wide and all(wide):
        widest = float(gaps.max())
        raise ValueError(
            f"the soundings are {widest:,.0f} m apart, about {widest / reach:.0f} "
            f"times the {reach:,.0f} m they resolve; a section between them would "
            "join two measurements with no measurement between, so none is drawn. "
            "A section needs stations within a few times the depth of "
            "investigation of each other."
        )
    return plot_geoelectric_section(
        [interp.model for interp in ordered],
        positions=[float(x) for x in profile.chainage_m],
        labels=[interp.sounding_id or "VES" for interp in ordered],
        path=path, style=style, depth_max=depth_max, title=title,
        half_width_m=reach or None,
        correlate=[not w for w in wide] or None,
        note=_correlation_note(profile, reach, wide),
    )


#: Stations further apart than this many times the depth of investigation
#: have nothing measured between them: no boundary is correlated across
#: such a gap, and a survey with no closer pair gets no section at all.
CORRELATION_REACH_MULTIPLE = 10.0


def _wide_gaps(profile: "TraverseProfile", reach_m: float) -> list[bool]:
    """Which gaps between neighbouring stations are too wide to correlate."""
    if reach_m <= 0 or len(profile.chainage_m) < 2:
        return []
    gaps = np.diff(np.asarray(profile.chainage_m, float))
    return [bool(gap > reach_m * CORRELATION_REACH_MULTIPLE) for gap in gaps]


def _correlation_note(profile: "TraverseProfile", reach_m: float,
                      wide: list[bool] | None = None) -> str:
    """What is not correlated on the section, and why.

    A sounding sees the ground under it, to a lateral reach of roughly
    its largest electrode half-spacing. Joining a layer boundary across
    a gap many times that is drawing a line between two points and
    calling it a horizon. The classic rule of thumb is that correlation
    needs stations no more than a few times the depth of investigation
    apart; beyond about ten times there is nothing between them at all,
    and the section leaves such a gap uncorrelated and says so.
    """
    if wide is None:
        wide = _wide_gaps(profile, reach_m)
    if reach_m <= 0 or len(profile.chainage_m) < 2 or not any(wide):
        return ""
    gaps = np.diff(np.asarray(profile.chainage_m, float))
    parts = [
        f"{profile.labels[k]} to {profile.labels[k + 1]} ({gaps[k]:,.0f} m, about "
        f"{gaps[k] / reach_m:.0f} times the {reach_m:,.0f} m the soundings reached)"
        for k, is_wide in enumerate(wide) if is_wide
    ]
    return (
        "No boundary is correlated across the gap "
        + "; ".join(parts)
        + ": there is no measurement between those stations, and a dashed "
        "line across them would be a proposal drawn as a horizon."
    )


# ---------------------------------------------------------------------------
# The pseudo-section
# ---------------------------------------------------------------------------

def apparent_resistivity_pseudosection(
    soundings: list,
    profile: TraverseProfile | None = None,
    path: str | Path | None = None,
    style: HouseStyle | None = None,
    title: str = "Apparent resistivity pseudo-section along the traverse",
):
    """The measurements themselves, laid out along the traverse.

    Every other subsurface figure in this module is drawn from the
    inverted layer models, which are one interpretation of the curves
    among several that fit them. This one is not: each cell is a reading
    off the instrument, plotted at the station it was taken at and the
    electrode spacing it was taken with. If the inversion is wrong, this
    figure is still right.

    The vertical axis is AB/2 - the electrode half-spacing - and is
    labelled as such rather than converted to a depth. Current spreads
    further as the electrodes spread, so a larger AB/2 does see deeper,
    but the pseudo-depth conversions are rules of thumb that vary with
    the very layering the section is being drawn to reveal. Calling a
    measurement geometry a depth is how a pseudo-section starts being
    read as a cross-section.

    ``profile`` places the stations; without one the soundings are laid
    out in the order given, evenly spaced, and the figure says so.
    """
    style = style or HouseStyle()
    if len(soundings) < 2:
        raise ValueError(
            f"a pseudo-section needs at least two soundings; got {len(soundings)}"
        )
    by_id = {s.sounding_id or f"VES {k + 1}": s for k, s in enumerate(soundings)}
    if profile is not None:
        ordered = [by_id[label] for label in profile.labels if label in by_id]
        stations = [
            float(x) for label, x in zip(profile.labels, profile.chainage_m, strict=True)
            if label in by_id
        ]
        x_label = "Distance along traverse (m)"
        spaced_evenly = False
    else:
        ordered = list(soundings)
        stations = [float(k) * 100.0 for k in range(len(ordered))]
        x_label = "Station (evenly spaced; no positions recorded)"
        spaced_evenly = True
    if len(ordered) < 2:
        raise ValueError(
            "the traverse profile and the soundings share fewer than two "
            "sounding identifiers, so the stations cannot be placed"
        )

    xs: list[float] = []
    ys: list[float] = []
    vs: list[float] = []
    for station, sounding in zip(stations, ordered, strict=True):
        for ab2, rho in zip(sounding.ab2, sounding.rho_app, strict=True):
            if not (math.isfinite(ab2) and math.isfinite(rho)) or rho <= 0:
                continue
            xs.append(station)
            ys.append(float(ab2))
            vs.append(float(rho))
    if len(vs) < 4:
        raise ValueError(
            f"{len(vs)} usable readings across {len(ordered)} soundings; a "
            "pseudo-section needs a curve at each station."
        )

    x = np.array(xs)
    y = np.array(ys)
    v = np.array(vs)
    # Colour is interpolated between two stations only when they are within
    # the correlation rule of each other; between a pair further apart
    # there is no measurement, and a continuous banded fill across 20 km
    # read as a 20 km resistivity cross-section.
    max_gap = float(np.max(y)) * 0.5 * CORRELATION_REACH_MULTIPLE
    uncorrelated: list[tuple[str, str, float]] = []
    for k in range(len(stations) - 1):
        gap = stations[k + 1] - stations[k]
        if gap > max_gap:
            uncorrelated.append((ordered[k].sounding_id or "VES",
                                 ordered[k + 1].sounding_id or "VES", gap))
    with figure_context(style):
        fig, ax = plt.subplots(figsize=(style.figure_width_in, 3.4))
        vmin = max(float(v.min()), 1.0)
        vmax = max(float(v.max()), vmin * 1.05)
        norm = LogNorm(vmin=vmin, vmax=vmax)
        # Levels spaced the way the colours are. Asking for a plain level
        # count under a log norm gets evenly spaced levels in ohm-m, which
        # a log ramp then squeezes into two bands: a section spanning 60 to
        # 900 ohm-m came out one flat colour with a stripe through it, and
        # the fill disagreed with the very readings drawn on top of it.
        levels = np.logspace(math.log10(vmin), math.log10(vmax), 14)
        # a triangulated fill between the readings, then the readings
        # themselves on top: the colour between two stations is
        # interpolation and the dots are where the instrument actually was
        if len(np.unique(x)) >= 2 and len(np.unique(y)) >= 2:
            from matplotlib.tri import Triangulation

            tri = Triangulation(x, np.log10(y))
            span = x[tri.triangles].max(axis=1) - x[tri.triangles].min(axis=1)
            tri.set_mask(span > max_gap)
            if not tri.mask.all():
                ax.tricontourf(tri, v, levels=levels, cmap="viridis",
                               norm=norm, alpha=0.85, extend="both")
        sc = ax.scatter(x, np.log10(y), c=v, cmap="viridis", norm=norm,
                        s=22, edgecolors="white", linewidths=0.6, zorder=5)
        cbar = fig.colorbar(sc, ax=ax, pad=0.02)
        cbar.set_label("Apparent resistivity (ohm-m)")
        # decade ticks, but only the ones the readings reach: an 80 m spread
        # does not get a 100 m tick
        ticks = [t for t in np.unique(np.round(np.log10(y)))
                 if y.min() / 1.5 <= 10 ** t <= y.max() * 1.5]
        ax.set_yticks(ticks)
        ax.set_yticklabels([f"{10 ** t:g}" for t in ticks])
        ax.invert_yaxis()
        ax.set_ylabel("AB/2 (m)")
        ax.set_xlabel(x_label)
        # station names above the frame, clear of the shallowest readings;
        # the end stations lean inwards so they stay on the page
        for k, (station, sounding) in enumerate(zip(stations, ordered, strict=True)):
            ha = "center"
            if len(stations) > 1 and k == 0:
                ha = "left"
            elif len(stations) > 1 and k == len(stations) - 1:
                ha = "right"
            ax.annotate(
                sounding.sounding_id or "VES", xy=(station, np.log10(y.min())),
                xytext=(0, 4), textcoords="offset points", ha=ha,
                va="bottom", fontsize=7.5, fontweight="bold",
                color=style.accent_color, annotation_clip=False,
            )
        notes = [
            ("AB/2 is the electrode half-spacing, not a depth: a deeper "
             "reading is a wider spread, not a measured horizon."),
        ]
        if uncorrelated:
            notes.append(
                "No colour is interpolated across "
                + "; ".join(f"{a} to {b} ({gap:,.0f} m)" for a, b, gap in uncorrelated)
                + ": nothing was measured between those stations."
            )
        if spaced_evenly:
            notes.append(
                "Stations are drawn evenly spaced because no sounding "
                "positions were recorded; the horizontal scale is not ground "
                "distance."
            )
        elif profile is not None and not profile.is_collinear:
            notes.append(
                f"The soundings sit up to {profile.max_offset_m:.0f} m off the "
                f"profile line ({profile.straightness * 100:.0f}% of its "
                f"{profile.length_m:.0f} m length), so this section cuts "
                "across the survey rather than along it."
            )
        ax.text(
            0.5, -0.30, "  ".join(notes), transform=ax.transAxes, ha="center",
            va="top", fontsize=6.8, color="#555555", wrap=True,
        )
        ax.set_title(title)
        ax.grid(True, color="#DDDDDD", lw=0.4)
        fig.tight_layout()
        if path is not None:
            return save_figure(fig, path, style)
        return fig
