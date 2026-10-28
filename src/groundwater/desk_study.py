"""The desk study: what is known of a site before anyone travels to it.

PLAN.md step 4.4. The day before a field visit, a hydrogeologist puts
together what the maps, the inventories and earlier work already say about
the site: the geology and the aquifer class under it, the terrain and its
lineament candidates where an elevation model was analysed, the water
points the inventory records nearby, the earlier projects in the portfolio
within 5 km with any depth or yield they recorded, the odds of a working
borehole from the ground alone, and the survey plan laid across the
candidates (step 4.3). This module works that out as plain data, in a form
both engines build the same way (``C.deskStudyContent`` in
``docs/js/gwt-core.js`` is its port, held to it by the parity suite), and
the two document writers lay it out.

Every number in the content is already written as text, through the
catalogue in ``data/text/desk_study.yaml`` and the engines' shared
formatters, so the two engines' content can be compared whole.

The terrain is analysed on the Site maps page, and neither app keeps the
analysis once its figures are drawn: :func:`desk_study_terrain` takes from
it what the desk study says, small enough to keep beside the figures, with
the site it was laid round. A desk study whose site has moved since then
leaves the terrain out and says so.

The WPdx+ inventory carries no depth or yield for its points, and neither
engine's reader reads one. The depths and yields near the site are the
earlier projects', where their files hold them, and the content says so.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .config import Config
from .geo import geodesic_distance_m, geographic_to_utm
from .mapping.lineaments import ROSE_BANDS, LineamentAnalysis, lineament_lonlat
from .mapping.lithology import describe, lithology_for
from .mapping.regional import _unit_district, aquifer_unit_at, geology_unit_at
from .mapping.survey import SurveyPlan, line_station, survey_sounding_text
from .portfolio import _latlon, _num, classify_status, site_label, summary_holds_degrees, verdict_state
from .reporting.citations import references_for
from .site_status import status_label
from .quality.assess import VERDICT_SHORT
from .siting.odds import odds_basis_text, odds_headline, odds_prior_text, prior_odds
from .text import phrase
from .utils import and_join, fmt_num, sum_in_order
from .waterpoints import DEFAULT_SEARCH_RADIUS_M, SERVICE_RADIUS_M, points_within

__all__ = [
    "PORTFOLIO_RADIUS_M",
    "WATER_POINTS_LISTED",
    "desk_study_content",
    "desk_study_terrain",
    "site_ground",
]

#: The earlier projects a desk study lists lie within this distance of the
#: site: PLAN.md step 4.4's 5 km.
PORTFOLIO_RADIUS_M = 5000.0
#: The water points a desk study lists, nearest first; it counts them all.
WATER_POINTS_LISTED = 15
#: How far the site may have moved since the terrain was analysed round it
#: before the desk study leaves the terrain out. A metre: the plan's pegs are
#: placed to the decimetre, and a position typed again the same is the same.
_TERRAIN_SITE_TOLERANCE_M = 1.0


def site_ground(latlon, district: str = "") -> dict:
    """The ground under a position on the bundled maps.

    The USGS geology unit (``glg``, ``unit``), the formation the crosswalk
    names it (``formation``) and the sentence it gives it (``lithology``:
    the formation, the rock and what it means for a borehole), both scoped
    by where the polygon lies, as the map key is, and the
    BGS aquifer class (``bgs_code``, ``aquifer``, and ``aquifer_geology``, the
    rock the atlas names). Each is "" where the maps have nothing, or where
    there is no position.
    """
    out = {"glg": "", "unit": "", "formation": "", "lithology": "", "bgs_code": "", "aquifer": "",
           "aquifer_geology": ""}
    if latlon is None:
        return out
    lat, lon = latlon
    unit = geology_unit_at(lat, lon)
    if unit is not None:
        out["glg"], out["unit"] = unit.glg, unit.unit
        scope = _unit_district(unit) or district
        row = lithology_for(unit.glg, scope)
        out["formation"] = row.formation_name if row is not None else ""
        out["lithology"] = describe(unit.glg, scope)
    aquifer = aquifer_unit_at(lat, lon)
    if aquifer is not None:
        out["bgs_code"], out["aquifer"] = aquifer.glg, aquifer.unit
        out["aquifer_geology"] = aquifer.era
    return out


def _position(lat: float, lon: float) -> str:
    return phrase("desk_study.position", lat=lat, lon=abs(lon))


def desk_study_terrain(lineaments: LineamentAnalysis, plan: SurveyPlan | None, lons, lats,
                       captions: Mapping, label: str) -> dict:
    """What a desk study says of an analysed terrain, small enough to keep.

    ``lineaments`` and ``plan`` are what the press found and laid (``plan``
    None where the site has no GPS fix); ``lons`` and ``lats`` the analysed
    window's cell centres; ``captions`` the terrain, lineament and plan
    captions merged, as the page shows them; ``label`` what the files are,
    as the read names them. The candidates are counted and their length
    added in the order they were found; the band is the 10-degree band of
    strike that holds the greatest length, the first of any tie, as the
    survey plan's strike line takes it.
    """
    found = lineaments.lineaments
    valleys = sum(1 for item in found if item.kind == "valley")
    totals = [lineaments.rose_valley_m[b] + lineaments.rose_ridge_m[b] for b in range(ROSE_BANDS)]
    band = 0
    for b in range(1, ROSE_BANDS):
        if totals[b] > totals[band]:
            band = b
    out = {
        "label": label,
        "site": None,
        "candidates": len(found),
        "valleys": valleys,
        "ridges": len(found) - valleys,
        "km": sum_in_order(item.length_m for item in found) / 1000.0,
        "band_low": band * 10.0,
        "band_high": band * 10.0 + 10.0,
        "band_km": totals[band] / 1000.0,
        "near": None,
        "basis": None,
        "captions": {key: str(captions[key]) for key in ("relief", "lineaments", "rose", "plan", "plan_note")
                     if key in captions},
        "lines": [],
        "soundings": [],
    }
    if plan is None:
        return out
    lon, lat = plan.site_lonlat
    out["site"] = [lat, lon]
    out["near"] = len(plan.near)
    out["basis"] = plan.basis
    for line in plan.lines:
        lon0, lat0 = lineament_lonlat(plan, lons, lats, line_station(line, line.first))
        lon1, lat1 = lineament_lonlat(plan, lons, lats, line_station(line, line.last))
        out["lines"].append([phrase("survey_plan.line_name", line=line.id), f"{line.bearing_deg:.0f}",
                             f"{line.length_m:g}", _position(lat0, lon0), _position(lat1, lon1)])
    for x in plan.soundings:
        lon, lat = lineament_lonlat(plan, lons, lats, x.point)
        out["soundings"].append([phrase("survey_plan.ves_name", n=x.id), str(x.line), f"{x.at_m:.1f}",
                                 _position(lat, lon), survey_sounding_text(plan, x)])
    return out


def _water_rows(points) -> list[dict]:
    """The water points as the desk study reads them, whatever reader
    parsed them: the browser shows a point's technology where its source is
    blank, and so does this."""
    return [{"lat": p.lat, "lon": p.lon, "functional": p.functional, "improved": p.improved,
             "source": p.source or p.technology, "installed": p.install_year} for p in points]


def _water_section(latlon, water_points, radius_m: float) -> tuple[dict, dict | None]:
    section = {"key": "water_points", "heading": phrase("desk_study.water_heading"),
               "paragraphs": [], "tables": [], "figures": [], "bullets": []}
    if latlon is None:
        section["paragraphs"].append(phrase("desk_study.water_no_position"))
        return section, None
    if water_points is None:
        section["paragraphs"].append(phrase("desk_study.water_not_loaded"))
        return section, None
    lat, lon = latlon
    near = points_within(water_points, lat, lon, radius_m)
    rows = _water_rows(near)
    # points_within stamps every point it keeps with its distance
    distances = [p.distance_m if p.distance_m is not None else 0.0 for p in near]
    if not rows:
        section["paragraphs"].append(phrase("desk_study.water_none", radius=radius_m))
        return section, {"total": 0, "working": 0, "serving": 0, "rehab": 0}
    working = sum(1 for r in rows if r["functional"] is True)
    broken = sum(1 for r in rows if r["functional"] is False)
    unknown = len(rows) - working - broken
    serving = sum(1 for r, d in zip(rows, distances, strict=True)
                  if r["functional"] is True and r["improved"] and d <= SERVICE_RADIUS_M)
    rehab = sum(1 for r, d in zip(rows, distances, strict=True)
                if r["functional"] is False and r["improved"] and d <= SERVICE_RADIUS_M)
    paragraphs = [phrase("desk_study.water_counts", total=len(rows), radius=radius_m, working=working,
                         broken=broken, unknown=unknown)]
    nearest = next((d for r, d in zip(rows, distances, strict=True)
                    if r["functional"] is True and r["improved"]), None)
    if serving:
        paragraphs.append(phrase("desk_study.water_serving", count=serving, radius=SERVICE_RADIUS_M))
    elif nearest is not None:
        paragraphs.append(phrase("desk_study.water_nearest", distance=nearest))
    else:
        paragraphs.append(phrase("desk_study.water_no_working", radius=radius_m))
    if rehab:
        paragraphs.append(phrase("desk_study.water_rehab", count=rehab, radius=SERVICE_RADIUS_M))
    paragraphs.append(phrase("desk_study.water_depth"))
    status = {True: phrase("desk_study.water_working"), False: phrase("desk_study.water_broken"),
              None: phrase("desk_study.water_unknown")}
    table_rows = [[fmt_num(d), status[r["functional"]], r["source"],
                   str(r["installed"]) if r["installed"] is not None else ""]
                  for r, d in zip(rows[:WATER_POINTS_LISTED], distances, strict=False)]
    section["paragraphs"] = paragraphs
    section["tables"].append({
        "caption": phrase("desk_study.water_caption", radius=radius_m),
        "header": [phrase("desk_study.water_col_distance"), phrase("desk_study.water_col_status"),
                   phrase("desk_study.water_col_source"), phrase("desk_study.water_col_installed")],
        "rows": table_rows,
    })
    if len(rows) > WATER_POINTS_LISTED:
        section["paragraphs"].append(phrase("desk_study.water_more", count=len(rows) - WATER_POINTS_LISTED,
                                            radius=radius_m))
    return section, {"total": len(rows), "working": working, "serving": serving, "rehab": rehab}


def _water_quality(summary: dict) -> str:
    state, legacy = verdict_state(summary)
    water = VERDICT_SHORT.get(state, "") if state else ""
    return water + "*" if water and legacy else water


def _projects_section(latlon, portfolio) -> tuple[dict, int | None]:
    km = PORTFOLIO_RADIUS_M / 1000.0
    section = {"key": "projects", "heading": phrase("desk_study.projects_heading", km=km),
               "paragraphs": [], "tables": [], "figures": [], "bullets": []}
    if latlon is None:
        section["paragraphs"].append(phrase("desk_study.projects_no_position"))
        return section, None
    if portfolio is None:
        section["paragraphs"].append(phrase("desk_study.projects_not_loaded"))
        return section, None
    lat, lon = latlon
    near, unplaced, degrees = [], 0, []
    for summary in portfolio:
        at = _latlon(summary)
        if at is None:
            # a project whose boxes hold degrees is named, so that it can be
            # put right, rather than counted with those that record nothing
            if summary_holds_degrees(summary):
                degrees.append(site_label(summary))
            else:
                unplaced += 1
            continue
        distance = geodesic_distance_m(lat, lon, at[0], at[1])
        if distance <= PORTFOLIO_RADIUS_M:
            near.append((distance, summary))
    near.sort(key=lambda item: item[0])
    if not near:
        section["paragraphs"].append(phrase("desk_study.projects_none", km=km))
    else:
        statuses = [classify_status(s) for _, s in near]
        successful = statuses.count("successful")
        section["paragraphs"].append(phrase("desk_study.projects_found", count=len(near), km=km,
                                            drilled=successful + statuses.count("dry"),
                                            successful=successful))
        rows = []
        for (distance, summary), state in zip(near, statuses, strict=True):
            depth = _num(summary.get("total_depth_m"))
            yield_ = _num(summary.get("safe_yield_m3_per_h"))
            rows.append([site_label(summary), f"{distance / 1000.0:.1f}", status_label(state),
                         f"{depth:.1f}" if depth else "", f"{yield_:.2f}" if yield_ else "",
                         _water_quality(summary)])
        section["tables"].append({
            "caption": phrase("desk_study.projects_caption", km=km),
            "header": [phrase("desk_study.projects_col_project"), phrase("desk_study.projects_col_distance"),
                       phrase("desk_study.projects_col_status"), phrase("desk_study.projects_col_depth"),
                       phrase("desk_study.projects_col_yield"), phrase("desk_study.projects_col_water")],
            "rows": rows,
        })
    if degrees:
        section["paragraphs"].append(phrase("desk_study.projects_degrees", count=len(degrees),
                                            names=and_join(degrees)))
    if unplaced:
        section["paragraphs"].append(phrase("desk_study.projects_unplaced", count=unplaced))
    return section, len(near)


def _ground_section(latlon, ground: dict, odds) -> dict:
    section = {"key": "ground", "heading": phrase("desk_study.ground_heading"),
               "paragraphs": [], "tables": [], "figures": [], "bullets": []}
    if latlon is None:
        section["paragraphs"].append(phrase("desk_study.ground_no_position"))
        return section
    section["paragraphs"].append(phrase("desk_study.ground_lead"))
    none = phrase("desk_study.ground_none")
    geology = ([phrase("desk_study.ground_unit", unit=ground["unit"], code=ground["glg"]), ground["lithology"]]
               if ground["glg"] else [none, ""])
    if not ground["bgs_code"]:
        aquifer = [none, ""]
    elif odds.matched != "fallback" and odds.yield_q1_l_per_s is not None:
        aquifer = [phrase("desk_study.ground_unit", unit=ground["aquifer"], code=ground["bgs_code"]),
                   phrase("desk_study.ground_yield", q1=odds.yield_q1_l_per_s, q3=odds.yield_q3_l_per_s)]
    else:
        aquifer = [phrase("desk_study.ground_unit", unit=ground["aquifer"], code=ground["bgs_code"]),
                   phrase("desk_study.ground_no_yield")]
    section["tables"].append({
        "caption": phrase("desk_study.ground_caption"),
        "header": [phrase("desk_study.ground_col_map"), phrase("desk_study.ground_col_unit"),
                   phrase("desk_study.ground_col_meaning")],
        "rows": [[phrase("desk_study.ground_map_geology")] + geology,
                 [phrase("desk_study.ground_map_aquifer")] + aquifer],
    })
    return section


def _terrain_usable(terrain, latlon) -> bool:
    """Whether the terrain was analysed round this site: its plan's site
    within a metre of the position, or, with neither a fix nor a plan, the
    terrain as it is."""
    if terrain is None:
        return False
    if terrain["site"] is None or latlon is None:
        return terrain["site"] is None and latlon is None
    lat, lon = terrain["site"]
    return geodesic_distance_m(latlon[0], latlon[1], lat, lon) <= _TERRAIN_SITE_TOLERANCE_M


def _terrain_section(terrain, usable: bool) -> dict:
    section = {"key": "terrain", "heading": phrase("desk_study.terrain_heading"),
               "paragraphs": [], "tables": [], "figures": [], "bullets": []}
    if terrain is None:
        section["paragraphs"].append(phrase("desk_study.terrain_none"))
        return section
    if not usable:
        section["paragraphs"].append(phrase("desk_study.terrain_elsewhere"))
        return section
    captions = terrain["captions"]
    if terrain["candidates"]:
        found = phrase("desk_study.terrain_found", label=terrain["label"], candidates=terrain["candidates"],
                       valleys=terrain["valleys"], ridges=terrain["ridges"], km=terrain["km"],
                       band_low=terrain["band_low"], band_high=terrain["band_high"], band_km=terrain["band_km"])
        if terrain["near"]:
            found += " " + phrase("desk_study.terrain_near", near=terrain["near"], radius=SERVICE_RADIUS_M)
        elif terrain["near"] is not None:
            found += " " + phrase("desk_study.terrain_near_none", radius=SERVICE_RADIUS_M)
        section["paragraphs"].append(found)
    else:
        section["paragraphs"].append(phrase("desk_study.terrain_found_none", label=terrain["label"]))
    for key in ("relief", "lineaments") + (("rose",) if terrain["candidates"] else ()):
        if key in captions:
            section["figures"].append({"key": key, "caption": captions[key]})
    return section


def _plan_section(terrain, usable: bool) -> dict:
    section = {"key": "plan", "heading": phrase("desk_study.plan_heading"),
               "paragraphs": [], "tables": [], "figures": [], "bullets": []}
    if terrain is None or not usable:
        section["paragraphs"].append(phrase("desk_study.plan_no_terrain"))
        return section
    captions = terrain["captions"]
    if "plan" in captions:
        section["paragraphs"].append(captions["plan"])
    if terrain["lines"]:
        section["figures"].append({"key": "plan", "caption": captions.get("plan_note", "")})
        section["tables"].append({
            "caption": phrase("desk_study.plan_lines_caption"),
            "header": [phrase("desk_study.plan_col_line"), phrase("desk_study.plan_col_bearing"),
                       phrase("desk_study.plan_col_length"), phrase("desk_study.plan_col_start"),
                       phrase("desk_study.plan_col_end")],
            "rows": [list(row) for row in terrain["lines"]],
        })
    if terrain["soundings"]:
        section["tables"].append({
            "caption": phrase("desk_study.plan_soundings_caption"),
            "header": [phrase("desk_study.plan_col_sounding"), phrase("desk_study.plan_col_line"),
                       phrase("desk_study.plan_col_along"), phrase("desk_study.plan_col_position"),
                       phrase("desk_study.plan_col_where")],
            "rows": [list(row) for row in terrain["soundings"]],
        })
    return section


def desk_study_content(site, where: str, latlon, *, water_points: Iterable | None = None,
                       search_radius_m: float = DEFAULT_SEARCH_RADIUS_M,
                       portfolio: Iterable[dict] | None = None, terrain: dict | None = None,
                       config: Config | None = None) -> dict:
    """Everything the desk study says, as plain data.

    ``site`` gives the names (its community, chiefdom and district);
    ``where`` is the place as the terrain captions name it; ``latlon`` the
    site's GPS position, or None. ``water_points`` are the points the Water
    points page loaded, as its reader parsed them (None where none were
    loaded), looked at within ``search_radius_m``; ``portfolio`` the earlier
    projects' summaries (None where no portfolio was loaded); ``terrain``
    what :func:`desk_study_terrain` kept of the last analysis (None where
    none was run). Both engines return the same structure, which the two
    document writers lay out: a title, the stamp, the summary, the site's
    rows (for the cover's details, under ``site_heading``), and the
    sections, each with its paragraphs, tables, figures (a key the writer
    draws, and a caption) and bullets.
    """
    config = config or Config()
    where = str(where or "").strip() or phrase("desk_study.where_unnamed")
    district = str(getattr(site, "district", "") or "")
    ground = site_ground(latlon, district)
    odds = prior_odds(ground["bgs_code"] or None, ground["glg"] or None, config)
    usable = _terrain_usable(terrain, latlon)
    # the terrain the desk study speaks of: None where none was kept or it is elsewhere
    kept = terrain if usable else None

    rows = []
    for key, attr in (("desk_study.site_community", "community"), ("desk_study.site_chiefdom", "chiefdom"),
                      ("desk_study.site_district", "district")):
        value = str(getattr(site, attr, "") or "").strip()
        if value:
            rows.append([phrase(key), value])
    if latlon is None:
        rows.append([phrase("desk_study.site_position"), phrase("desk_study.no_position")])
    else:
        utm = geographic_to_utm(latlon[0], latlon[1])
        rows.append([phrase("desk_study.site_position"), _position(latlon[0], latlon[1])])
        rows.append([phrase("desk_study.site_utm"), phrase("desk_study.utm", zone=utm.zone, easting=utm.easting,
                                                          northing=utm.northing)])

    water, counts = _water_section(latlon, water_points, float(search_radius_m))
    projects, near_projects = _projects_section(latlon, portfolio)

    odds_section = {"key": "odds", "heading": phrase("desk_study.odds_heading"),
                    "paragraphs": [odds_headline(odds), odds_basis_text(odds)[0], odds_prior_text(odds)],
                    "tables": [], "figures": [], "bullets": []}
    if latlon is None:
        odds_section["paragraphs"].append(phrase("desk_study.odds_no_position"))
    odds_section["paragraphs"].append(phrase("desk_study.odds_note"))

    checks = [phrase("desk_study.check_ground")]
    if latlon is None:
        checks.append(phrase("desk_study.check_position"))
    if counts and counts["serving"]:
        checks.append(phrase("desk_study.check_serving", radius=SERVICE_RADIUS_M))
    if counts and counts["rehab"]:
        checks.append(phrase("desk_study.check_rehab"))
    if kept is not None and kept["lines"]:
        if kept["basis"] == "candidates":
            checks.append(phrase("desk_study.check_candidates"))
        checks.append(phrase("desk_study.check_pegs"))
    if terrain is None:
        checks.append(phrase("desk_study.check_terrain"))
    checks_section = {"key": "checks", "heading": phrase("desk_study.checks_heading"),
                      "paragraphs": [], "tables": [], "figures": [], "bullets": checks}

    summary = []
    if latlon is not None:
        rock = ground["formation"] or ground["unit"]
        if ground["glg"] and ground["bgs_code"]:
            summary.append(phrase("desk_study.summary_ground", unit=rock, aquifer=ground["aquifer"]))
        elif ground["glg"]:
            summary.append(phrase("desk_study.summary_ground_partial", unit=rock))
        else:
            summary.append(phrase("desk_study.summary_no_ground"))
    summary.append(odds_headline(odds))
    if kept is not None and kept["site"] is not None:
        if kept["basis"] == "candidates":
            summary.append(phrase("desk_study.summary_terrain", candidates=kept["candidates"],
                                  lines=len(kept["lines"]), soundings=len(kept["soundings"])))
        elif kept["basis"] == "strike":
            summary.append(phrase("desk_study.summary_terrain_strike", candidates=kept["candidates"],
                                  radius=SERVICE_RADIUS_M))
        else:
            summary.append(phrase("desk_study.summary_terrain_none", candidates=kept["candidates"]))
    if counts is not None and counts["total"]:
        summary.append(phrase("desk_study.summary_water", total=counts["total"], radius=float(search_radius_m),
                              working=counts["working"]))
    elif counts is not None:
        summary.append(phrase("desk_study.summary_water_none", radius=float(search_radius_m)))
    if near_projects:
        summary.append(phrase("desk_study.summary_projects", count=near_projects,
                              km=PORTFOLIO_RADIUS_M / 1000.0))
    elif near_projects is not None:
        summary.append(phrase("desk_study.summary_projects_none", km=PORTFOLIO_RADIUS_M / 1000.0))

    return {
        "title": phrase("desk_study.title", where=where),
        "subtitle": phrase("desk_study.subtitle"),
        "where": where,
        "site_heading": phrase("desk_study.site_heading"),
        "stamp": {"title": phrase("desk_study.stamp_title"), "lead": phrase("desk_study.stamp_lead")},
        "summary": summary,
        "site_rows": rows,
        "sections": [
            _ground_section(latlon, ground, odds),
            _terrain_section(terrain, usable),
            water,
            projects,
            odds_section,
            _plan_section(terrain, usable),
            checks_section,
        ],
        "references": references_for("desk_study"),
    }
