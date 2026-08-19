"""Context map figures shared by the report builders.

When a site has coordinates, the reports embed the administrative
location map and the local geological and hydrogeological setting
maps, generated once into the report's figures directory.
"""

from __future__ import annotations

from pathlib import Path

from ..config import HouseStyle
from ..mapping import (
    area_window,
    plot_admin_map,
    plot_geological_map,
    plot_hydrogeology_map,
)
from ..models import SiteMetadata


def _figures_dir(figures_dir, out_path) -> Path:
    """Where a report's figures belong.

    A default of ``Path(".")`` meant a report built without one dropped its
    PNGs into whatever directory the process was started in - a user's home,
    a CI checkout, the repository root. The directory holding the document is
    always known by the time anything is drawn, and is where someone looking
    for the figures would look.
    """
    if figures_dir is not None:
        figures = Path(figures_dir)
    else:
        figures = Path(out_path).parent
    figures.mkdir(parents=True, exist_ok=True)
    return figures


def context_map_figures(
    site: SiteMetadata | None,
    figures_dir: str | Path,
    style: HouseStyle | None = None,
    local_radius_km: float = 40.0,
) -> dict[str, Path]:
    """Generate the context maps for a site.

    A GPS fix centres the local maps on the point. Without one they are
    centred on the recorded chiefdom, or failing that the district, and
    say so in their titles - the area is still worth mapping, and a
    report about a place that shows no map of it is worse than one whose
    map is a district rather than a point. Only a project that records
    neither a position nor an area gets nothing.

    Returns paths keyed ``admin``, ``geology`` and ``hydrogeology``.
    :func:`groundwater.mapping.area_window` gives the window they cover.
    The maps are redrawn on every build. They are cheap, and a map that
    was left on disk by an earlier run is a map of what the project used
    to say: reusing it is the one way this function can be wrong.
    """
    if site is None:
        return {}
    window = area_window(site, local_radius_km)
    if window is None:
        return {}
    figures = Path(figures_dir)
    figures.mkdir(parents=True, exist_ok=True)
    # the file name carries the centre of the window, so two sites in one
    # project keep their own maps rather than overwriting each other
    token = f"{window.lat:.4f}_{abs(window.lon):.4f}".replace(".", "p")
    out: dict[str, Path] = {}
    admin = figures / f"admin_map_{token}.png"
    plot_admin_map(site, path=admin, style=style)
    out["admin"] = admin
    geology = figures / f"geology_local_map_{token}.png"
    plot_geological_map(site, path=geology, style=style,
                        radius_km=local_radius_km)
    out["geology"] = geology
    hydro = figures / f"hydro_local_map_{token}.png"
    plot_hydrogeology_map(site, path=hydro, style=style,
                          radius_km=local_radius_km)
    out["hydrogeology"] = hydro
    return out


def area_map_note(site: SiteMetadata | None) -> str:
    """One sentence placing the site, for the paragraph above the map."""
    if site is None:
        return "No site metadata was supplied with this report."
    where = ", ".join(
        part for part in (site.community, site.chiefdom and f"{site.chiefdom} chiefdom",
                          site.district and f"{site.district} district")
        if part
    )
    if site.latlon is None:
        window = area_window(site)
        if window is None:
            return (
                (f"The site is recorded as {where}. " if where else "")
                + "Neither a GPS position nor an administrative area is "
                "recorded for it, so no map of the area can be drawn. A "
                "borehole that cannot be found again on the ground cannot be "
                "revisited or maintained: record the position on the field "
                "sheet and reissue this report."
            )
        return (
            (f"The site is recorded as {where}. " if where else "")
            + f"No GPS position is recorded for it, so the maps below cover "
            f"{window.label} rather than the borehole itself and carry no "
            "site marker. Record the position on the field sheet and reissue "
            "this report: a borehole that cannot be found again on the ground "
            "cannot be revisited or maintained."
        )
    lat, lon = site.latlon
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return (
        (f"The site is at {where}, " if where else "The site is at ")
        + f"{abs(lat):.5f} {ns}, {abs(lon):.5f} {ew}."
    )


def add_area_section(
    rb,
    site: SiteMetadata | None,
    figures_dir: str | Path,
    style: HouseStyle | None = None,
    *,
    heading: str | None = "Location and setting",
    level: int = 2,
    detail: bool = False,
    local_radius_km: float = 40.0,
) -> dict[str, Path]:
    """Put a map of the area into a report.

    Every report carries one, because every report is about a place and
    the reader has to be able to find it. ``detail`` adds the aquifer and
    geological setting maps as well as the locator; the geophysical and
    handover reports want those, a payment certificate does not.

    Returns the figure paths, so a caller that wants to say more about
    them can. Without coordinates nothing is drawn and the paragraph
    says why.
    """
    if heading:
        rb.heading(heading, level)
    rb.paragraph(area_map_note(site), align="justify")
    maps = context_map_figures(site, figures_dir, style,
                               local_radius_km=local_radius_km)
    if not maps:
        return {}
    window = area_window(site, local_radius_km)
    where = (window.label if window is not None
             else ((site.community if site is not None else "") or "the site"))
    rb.figure(
        maps["admin"],
        f"Location of {where}. Boundaries from geoBoundaries (CC BY 4.0).",
        width_cm=14.0,
    )
    if detail:
        rb.figure(
            maps["hydrogeology"],
            "Aquifer type and productivity around the site, from the BGS "
            "Africa Groundwater Atlas country map (CC BY-SA 4.0).",
            width_cm=14.0,
        )
        rb.figure(
            maps["geology"],
            "Geological setting around the site, from the USGS Geologic Map "
            "of Africa (1:5,000,000).",
            width_cm=14.0,
        )
    return maps
