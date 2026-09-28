"""Coverage gap: people per working water point, by district or chiefdom."""

from __future__ import annotations

import json
from datetime import date

import streamlit as st

from groundwater.coverage import (
    chiefdom_coverage_rows,
    choropleth_values,
    counts_from_groups,
    coverage_rows,
    coverage_stats,
    expand_district_values,
    POPULATION_CREDIT,
)
from groundwater.mapping import plot_coverage_choropleth
from groundwater.planning import (
    AGEING_YEARS,
    CENSUS_YEAR,
    DEFAULT_GROWTH_RATE,
    planning_rows,
    planning_stats,
    project_population,
)
from groundwater.utils import plural
from groundwater.waterpoints import (
    fetch_water_points,
    WaterPointFetchError,
    WPDX_CREDIT,
)

from shared import (
    app_config,
    content_token,
    cov_chiefdom_population,
    cov_crosswalk,
    _cov_join,
    cov_population,
    figure,
    kept_upload,
    offer_download,
    show_flags,
    wpdx_points,
)

def render() -> None:
    st.header("Water coverage gap by district")
    st.caption(
        "Where are the underserved people? This ranks Sierra Leone's 16 "
        "districts by population per functional water point, joining the 2015 "
        "census district populations (Statistics Sierra Leone) with mapped "
        "water points from the Water Point Data Exchange (WPdx+, CC BY 4.0). "
        "Higher = more people per working source = higher priority. WPDx "
        "coverage is not exhaustive, so treat it as a planning signal, not a "
        "census of points."
    )
    cov_input = st.radio(
        "Water points source",
        ["Upload WPDx CSV export", "Live WPDx (national)"],
        key="cov_source", horizontal=True,
        help="Download your country's export from waterpointdata.org for a "
        "fully offline analysis, or fetch live (needs internet).",
    )
    cov_points = None
    # What the reader threw away belongs beside what it kept: an export that is
    # half unusable and a complete one both arrive as a number of water points,
    # and that number decides which chiefdom reads as served.
    cov_skipped: list = []
    cov_token = None
    if cov_input == "Upload WPDx CSV export":
        up = kept_upload("WPDx CSV export (.csv)", "cov_csv", type=["csv"])
        if up is not None:
            data = up.getvalue()
            cov_token = content_token(data)
            try:
                cov_points, cov_skipped = wpdx_points(
                    cov_token, _csv_text=data.decode("utf-8", "replace"))
            except Exception as exc:  # noqa: BLE001 - surfaced to the operator
                st.error(f"Could not read that CSV: {exc}")
    else:
        cov_limit = 200000
        if st.button("Fetch national water points", key="cov_fetch",
                     type="primary"):
            try:
                with st.spinner("Querying the Water Point Data Exchange..."):
                    # a bounding box around the country's centre; a high limit
                    # because a national pull (plus the box's Guinea/Liberia
                    # fringe, which the chiefdom join later discards) is tens of
                    # thousands of points
                    st.session_state["cov_points_raw"] = fetch_water_points(
                        8.46, -11.79, 300000.0, limit=cov_limit
                    )
                    # what the pull returned, named once, so its parse and
                    # its join are shared by every rerun and session
                    st.session_state["cov_points_token"] = content_token(json.dumps(
                        st.session_state["cov_points_raw"], sort_keys=True,
                        default=str).encode())
            except WaterPointFetchError as exc:
                st.session_state.pop("cov_points_raw", None)
                st.error(
                    f"{exc} Try the CSV upload option instead - the rest of "
                    "the toolkit works offline."
                )
        raw = st.session_state.get("cov_points_raw")
        if raw is not None:
            if len(raw) >= cov_limit:
                st.warning(
                    f"The national pull hit the {cov_limit:,}-row cap, so the "
                    "ranking may be partial. Prefer a filtered WPDx CSV export "
                    "for a complete, reproducible analysis."
                )
            cov_token = st.session_state.get("cov_points_token") or content_token(
                json.dumps(raw, sort_keys=True, default=str).encode())
            cov_points, cov_skipped = wpdx_points(cov_token, _records=raw)

    resolution = st.radio(
        "Resolution", ["District", "Chiefdom"], key="cov_resolution",
        horizontal=True,
        help="District population is exact; chiefdom aggregates the 2015 "
        "census onto the chiefdom polygons (district totals conserved).",
    )
    # What the reader could not use belongs with the source it came from, and
    # it has to appear whether or not anything survived. The case that matters
    # most is the one where nothing did: a WPdx export whose header did not
    # survive - a BOM makes the first column "\ufefflat_deg" - loses every
    # coordinate, so the page has nothing to rank and everything to explain.
    # Hung below the ranking, this said nothing at all in exactly that case,
    # and "No water points found in that source" reads as "this area has no
    # water points" rather than "this file did not load". The browser engine
    # had the same defect, for the same reason, in waterPointSourceNote().
    if cov_skipped:
        show_flags(cov_skipped)
    if cov_points is not None and not cov_points:
        st.warning(
            "No usable water point came back from that source; every row was "
            "discarded for the reason above."
            if cov_skipped else "No water points found in that source."
        )
    elif cov_points:
        chiefdom = resolution == "Chiefdom"
        members = None
        rows = None
        grouped = None
        area_population = None
        if chiefdom:
            unit = "chiefdom"
            try:
                grouped, unassigned = _cov_join(cov_token, "chiefdom", cov_points)
                counts = counts_from_groups(grouped)
                chief_pop, members = cov_chiefdom_population()
                area_population = chief_pop
                rows = chiefdom_coverage_rows(chief_pop, counts, cov_crosswalk())
            # e.g. a hand-edited crosswalk drops a census chiefdom
            except Exception as exc:  # noqa: BLE001 - reported with a fix hint
                st.error(
                    f"Could not build the chiefdom view: {exc}. "
                    "Fix data/sl_census_crosswalk.csv or use District resolution."
                )
        else:
            unit = "district"
            grouped, unassigned = _cov_join(cov_token, "district", cov_points)
            counts = counts_from_groups(grouped)
            area_population = cov_population()
            rows = coverage_rows(area_population, counts)
    if cov_points and rows is not None:
        _planning_view(chiefdom, unit, area_population, counts, grouped,
                       unassigned, members)


@st.fragment
def _planning_view(chiefdom, unit, area_population, counts, grouped,
                   unassigned, members) -> None:
    """The year, the growth rate and everything counted with them.

    Neither input is saved in the project file and nothing outside this
    part of the page reads them, so a change to either reruns it alone:
    the source is not read again and the join is not looked up again.
    """
    # One page, one population. The ranking and the map used the 2015
    # census while the planning view below projected it forward, so the
    # same district appeared twice on one screen with two different
    # numbers of people in it. The year governs the whole page, so it is
    # asked for before anything is counted.
    _plan_year = st.number_input(
        "Plan for year", min_value=CENSUS_YEAR, max_value=2050,
        value=max(date.today().year, CENSUS_YEAR), step=1, key="cov_year",
        help="The census is from 2015. A people-per-point figure without "
             "a year attached is a wrong number nobody notices.",
    )
    _plan_rate = st.number_input(
        "Annual population growth (%)", min_value=0.0, max_value=10.0,
        value=round(DEFAULT_GROWTH_RATE * 100, 2), step=0.1,
        key="cov_rate",
        help="The default is the rate implied by the 2004 and 2015 census "
             "totals. It is higher than recent international projections; "
             "use your programme's own figure if you have one.",
    )
    _census_population = area_population
    area_population, _projection = project_population(
        _census_population, int(_plan_year), rate=_plan_rate / 100.0)
    rows = (chiefdom_coverage_rows(area_population, counts, cov_crosswalk())
            if chiefdom else coverage_rows(area_population, counts))
    st.caption(_projection.note)
    stats = coverage_stats(rows)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"{unit.title()}s", stats["n_areas"])
    c2.metric(
        "Highest need",
        f"{stats['worst_served_people_per_point']:,.0f}/pt"
        if stats["worst_served_people_per_point"] is not None else "n/a",
        help=f"worst measurable ratio, in {stats['worst_served_area']}"
        if stats["worst_served_area"] else f"no {unit} has a functional "
        "mapped source",
    )
    c3.metric("No mapped source", stats["n_no_source"],
              help=f"{unit}s with no functional point in WPDx")
    c4.metric(
        "National avg",
        f"{stats['national_people_per_point']:,.0f}/pt"
        if stats["national_people_per_point"] is not None else "n/a",
    )
    # --- planning view -------------------------------------------------
    # The census is a decade old and the survey behind each point is
    # older than it looks. Both are made visible rather than folded into
    # one figure that reads as current.
    # the census figures, not the projected ones: planning_rows projects
    # them itself from the same year and rate, and projecting twice would
    # compound the growth
    _plan_rows, _projection = planning_rows(
        _census_population, grouped or {},
        as_of_year=int(_plan_year), rate=_plan_rate / 100.0)
    _plan_stats = planning_stats(_plan_rows, _projection)
    p1, p2, p3 = st.columns(3)
    p1.metric(
        f"Population {int(_plan_year)}",
        f"{_plan_stats['population']:,.0f}",
        delta=f"{_plan_stats['population'] - _plan_stats['census_population']:+,.0f}"
              " since the census",
    )
    p2.metric(
        f"People per point ({int(_plan_year)})",
        f"{_plan_stats['national_people_per_point']:,.0f}"
        if _plan_stats["national_people_per_point"] is not None else "n/a",
    )
    p3.metric(
        "...counting recent surveys only",
        f"{_plan_stats['national_people_per_recent_point']:,.0f}"
        if _plan_stats["national_people_per_recent_point"] is not None
        else "n/a",
        help="A point reported functional years ago is evidence about "
             "then. The gap between these two figures is the size of the "
             "assumption in the one on the left.",
    )
    if _plan_stats["n_stale_areas"]:
        _n_stale = _plan_stats["n_stale_areas"]
        st.warning(
            f"{plural(_n_stale, unit)} "
            f"{'rests' if _n_stale == 1 else 'rest'} on surveys "
            f"more than {AGEING_YEARS} years old: "
            + ", ".join(_plan_stats["stale_areas"][:8])
            + ("..." if _n_stale > 8 else "")
            + (
                ". Its coverage figures describe the year it was "
                "surveyed, not this one."
                if _n_stale == 1
                else ". Their coverage figures describe the year they were "
                "surveyed, not this one."
            )
        )
    if not _plan_stats["n_seasonality_recorded"]:
        st.info(
            f"None of these {_plan_stats['n_seasonality_unknown']:,} "
            "functional points records how many months of the year it "
            "yields water, so dry-season service cannot be separated from "
            "wet-season service. Silence is not a year-round supply."
        )
    else:
        st.caption(
            f"{_plan_stats['n_seasonality_recorded']:,} points record "
            f"their seasonality and {_plan_stats['n_seasonality_unknown']:,} "
            "do not; the dry-season column below is a band between "
            "counting the unrecorded ones and not counting them."
        )
    with st.expander("Planning table: freshness and dry-season service"):
        st.dataframe(
            [{"Rank": r.rank, unit.title(): r.name,
              f"Population {int(_plan_year)}": int(r.population),
              "Functional": r.functional_points,
              "Recently surveyed": r.recent_functional_points,
              "People / point": round(r.people_per_point)
              if r.people_per_point is not None else None,
              "...recent only": round(r.people_per_recent_point)
              if r.people_per_recent_point is not None else None,
              "Survey": r.freshness.label,
              "Year-round points": r.seasonal.n_year_round,
              "Seasonal points": r.seasonal.n_seasonal,
              "Dry-season people / point":
                  r.seasonal.people_per_point_band}
             for r in _plan_rows],
            hide_index=True, width="stretch",
        )

    if chiefdom:
        cov_map = figure(
            plot_coverage_choropleth,
            choropleth_values(rows), style=app_config().style,
            title="Water coverage gap by chiefdom",
            file_name="coverage_map.png",
        )
    else:
        cov_map = figure(
            plot_coverage_choropleth,
            expand_district_values(choropleth_values(rows), cov_crosswalk()),
            style=app_config().style,
            group_labels=cov_crosswalk(),
            file_name="coverage_map.png",
        )
    st.image(str(cov_map))
    offer_download(cov_map, "Download coverage map")
    st.subheader(f"{unit.title()} ranking (highest unmet need first)")
    st.dataframe(
        [({"Rank": r.rank, unit.title(): r.name}
          | ({"District": r.district} if chiefdom else {})
          | {"Population": int(r.population),
             "Water points": r.water_points,
             "Functional": r.functional_points,
             "People / functional point":
                 round(r.people_per_point) if r.people_per_point is not None
                 else None,
             "Status": r.status}) for r in rows],
        hide_index=True, width="stretch",
    )
    # The other place a record is lost: the reader could use the row, but
    # the join could not place it. That one belongs beside the ranking it
    # was left out of, because there is a ranking for it to be missing
    # from - unlike the parse-time discards reported with the source above.
    if unassigned:
        st.caption(
            f"{len(unassigned)} water point(s) fell outside every chiefdom "
            "polygon (border, offshore, or geometry held back by the "
            "boundary review) and were not counted in any area above."
        )
    if chiefdom and members:
        aggregated = {gb: names for gb, names in sorted(members.items())
                      if len(names) > 1}
        with st.expander(
            f"How chiefdoms were reconciled ({len(aggregated)} polygons "
            "aggregate 2+ census chiefdoms)"
        ):
            st.caption(
                "The boundary polygons predate the 2017 chiefdom split, so "
                "post-2017 census chiefdoms fold into their pre-2017 parent. "
                "District totals are exact; only which polygon a new "
                "chiefdom joins is best-effort. Edit "
                "data/sl_census_crosswalk.csv to correct any assignment."
            )
            st.dataframe(
                [{"Chiefdom polygon": gb, "Census chiefdoms": ", ".join(names)}
                 for gb, names in aggregated.items()],
                hide_index=True, width="stretch",
            )
    st.caption(f"{WPDX_CREDIT}. {POPULATION_CREDIT}.")
