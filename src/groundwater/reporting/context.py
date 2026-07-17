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
    Existing files are reused so repeated report builds stay
    reproducible and fast.
    """
    if site is None or site.latlon is None:
        return {}
    figures = Path(figures_dir)
    figures.mkdir(parents=True, exist_ok=True)
    # figure names carry the coordinates, so an existing map for a
    # DIFFERENT site is never reused when the coordinates change
    lat, lon = site.latlon
    token = f"{lat:.4f}_{abs(lon):.4f}".replace(".", "p")
    out: dict[str, Path] = {}
    admin = figures / f"admin_map_{token}.png"
    if not admin.exists():
        plot_admin_map(site, path=admin, style=style)
    out["admin"] = admin
    geology = figures / f"geology_local_map_{token}.png"
    if not geology.exists():
        plot_geological_map(site, path=geology, style=style,
                            radius_km=local_radius_km)
    out["geology"] = geology
    hydro = figures / f"hydro_local_map_{token}.png"
    if not hydro.exists():
        plot_hydrogeology_map(site, path=hydro, style=style,
                              radius_km=local_radius_km)
    out["hydrogeology"] = hydro
    return out
