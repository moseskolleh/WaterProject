"""Context map figures shared by the report builders.

When a site has coordinates, the reports embed the administrative
location map and the local geological and hydrogeological setting
maps, generated once into the report's figures directory.
"""

from __future__ import annotations

from pathlib import Path

from ..config import HouseStyle
from ..mapping import (
    plot_admin_map,
    plot_geological_map,
    plot_hydrogeology_map,
)
from ..models import SiteMetadata


def context_map_figures(
    site: SiteMetadata | None,
    figures_dir: str | Path,
    style: HouseStyle | None = None,
    local_radius_km: float = 40.0,
) -> dict[str, Path]:
    """Generate the context maps for a site (empty without coordinates).

    Returns paths keyed ``admin``, ``geology`` and ``hydrogeology``.
    The maps are redrawn on every build. They are cheap, and a map that
    was left on disk by an earlier run is a map of what the project used
    to say: reusing it is the one way this function can be wrong.
    """
    if site is None or site.latlon is None:
        return {}
    figures = Path(figures_dir)
    figures.mkdir(parents=True, exist_ok=True)
    # the file name carries the coordinates, so two sites in one project
    # keep their own maps rather than overwriting each other
    lat, lon = site.latlon
    token = f"{lat:.4f}_{abs(lon):.4f}".replace(".", "p")
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
