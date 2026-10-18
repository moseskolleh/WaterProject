"""The desk study as a Word document (PLAN.md step 4.4), the eleventh.

Lays out :func:`groundwater.desk_study.desk_study_content`: the cover with
the site's names and position, the pre-field stamp on the page after it on
every copy, the executive summary, the area maps (the study area, the
locator, and the aquifer and geology maps the ground section reads), then
each section with its paragraphs, figures, tables and bullets, and the
references. The words and the numbers are all in the content; this module
only places them, as ``GWT.docx.deskStudyReport`` places the same content in
the browser.

The terrain figures are the ones the Site maps press drew, handed in by
their keys (``relief``, ``lineaments``, ``rose``, ``plan``); a figure the
content names and the press did not draw is left out, its section's text
standing. Nothing of the analysis is drawn again here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..desk_study import desk_study_content
from ..models import SiteMetadata
from ..waterpoints import DEFAULT_SEARCH_RADIUS_M
from .context import _figures_dir, add_area_section
from .docx_utils import ReportBuilder

__all__ = ["DeskStudyInputs", "build_desk_study_report"]

#: Each section's tables, by its key, with the widths their columns are
#: printed at (the page holds 16 cm between its margins). A table a section
#: does not have is passed over.
_WIDTHS = {
    "ground": [[3.6, 4.4, 8.0]],
    "water_points": [[2.6, 2.8, 7.4, 3.2]],
    "projects": [[4.4, 2.2, 2.8, 2.0, 2.2, 2.4]],
    "plan": [[1.8, 1.8, 2.0, 5.2, 5.2], [1.8, 1.2, 2.0, 3.8, 7.2]],
}

#: The water points marked on the study area map, nearest first, as many
#: as the Site maps page marks.
_MARKED = 40


@dataclass
class DeskStudyInputs:
    """Everything the desk study needs, as the Site maps page holds it.

    ``water_points`` are the points the Water points page loaded, as its
    reader parsed them, and ``search_radius_m`` the radius it searched;
    ``portfolio`` the earlier projects' summaries; ``terrain`` what
    :func:`~groundwater.desk_study.desk_study_terrain` kept of the last
    terrain press, and ``figures`` that press's PNG paths by key. Each is
    None where the page holds none.
    """

    site: SiteMetadata
    where: str = ""
    water_points: Iterable | None = None
    search_radius_m: float = DEFAULT_SEARCH_RADIUS_M
    portfolio: list[dict] | None = None
    terrain: dict | None = None
    figures: Mapping[str, str | Path] = field(default_factory=dict)
    #: The area maps go beside the document unless a directory is named.
    figures_dir: Path | None = None


def _marks(points, latlon) -> list[dict]:
    """The water points loaded, as the study area map marks them."""
    if points is None or latlon is None:
        return []
    from ..waterpoints import points_within

    near = points_within(points, latlon[0], latlon[1], float("inf"))
    return [{"lat": p.lat, "lon": p.lon, "kind": "water point"} for p in near[:_MARKED]]


def build_desk_study_report(inputs: DeskStudyInputs, out_path, config: Config | None = None) -> Path:
    """Write the desk study to ``out_path`` and return its path."""
    config = config or Config()
    site = inputs.site
    latlon = site.latlon
    points = list(inputs.water_points) if inputs.water_points is not None else None
    content = desk_study_content(site, inputs.where, latlon, water_points=points,
                                 search_radius_m=inputs.search_radius_m, portfolio=inputs.portfolio,
                                 terrain=inputs.terrain, config=config)
    rb = ReportBuilder(config.style, title=content["title"])
    rb.cover([content["title"]], [content["subtitle"]], [(label, value) for label, value in content["site_rows"]])
    rb.pre_field_stamp(content["stamp"]["title"], content["stamp"]["lead"])
    rb.table_of_contents()
    rb.executive_summary(content["summary"])

    add_area_section(rb, site, _figures_dir(inputs.figures_dir, out_path), config.style,
                     heading=content["site_heading"], level=1, detail=True, points=_marks(points, latlon))
    figures = {key: Path(path) for key, path in (inputs.figures or {}).items()}
    for section in content["sections"]:
        rb.heading(section["heading"], 1)
        for text in section["paragraphs"]:
            rb.paragraph(text, align="justify")
        for figure in section["figures"]:
            path = figures.get(figure["key"])
            if path is not None and path.exists():
                rb.figure(path, figure["caption"], width_cm=15.0)
        widths = _WIDTHS.get(section["key"], [])
        for k, table in enumerate(section["tables"]):
            rb.table(table["rows"], header=table["header"], caption=table["caption"],
                     col_widths_cm=widths[k] if k < len(widths) else None, font_size_pt=9.0)
        if section["bullets"]:
            rb.bullets(section["bullets"])
    rb.references(content["references"])
    return rb.save(out_path)
