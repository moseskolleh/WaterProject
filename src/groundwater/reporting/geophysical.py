"""Geophysical survey report generator.

Follows the structure of the Rokel example report: table of contents,
introduction, background and geology of the project area, field work
(reconnaissance with geomorphology and hydrogeology, traverse and VES
point selection, then survey method and instrument), data analysis
with one block per sounding (header and data table, curve and model
figure, layer pseudo-section, interpretation paragraph), the ranked
table of VES points in order of drilling preference, conclusions and
recommendations, and a signature block.

Every figure and table is numbered by the builder and referenced from
the body text; every number in the tables comes from the parsed raw
data or the fitted models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config, VESConfig
from ..mapping import (
    apparent_resistivity_pseudosection,
    aquifer_thickness_map,
    bedrock_elevation_map,
    depth_to_bedrock_map,
    geoelectric_section_along_traverse,
    ground_profile_along_traverse,
    ground_profile_state,
    points_enclose_an_area,
    protective_capacity_map,
    spacing_name,
    subsurface_map_points,
    suitability_map,
    suitability_map_state,
    survey_zone,
    traverse_profile,
    unplaced_text,
)
from ..models import DataFlag, LayeredModel, VESSounding
from ..siting import (
    assess_siting,
    ranking_tie,
    suitability_map_points,
    suitability_verdict,
    tied_leaders,
)
from ..mapping.lithology import region_of
from ..utils import and_join, fmt_num, plural, plural_noun, safe_slug, utm_text
from ..ves.classify import classify_curve
from ..ves.interpret import (
    SiteInterpretation,
    drilling_depth_text,
    drilling_preference_table,
    poorly_resolved_boundaries,
    rank_interpretations,
    zone_text,
)
from ..ves.inversion import InversionResult
from ..ves.plots import model_depth_m, plot_model_pseudosection, plot_sounding_curve
from .citations import GLOSSARY, references_for
from .context import context_map_figures
from .docx_utils import ReportBuilder

_DEFAULT_GEOLOGY = (
    "The project area lies within the crystalline basement terrain of Sierra "
    "Leone, where groundwater occurs mainly within the weathered overburden "
    "(regolith) and in fractured zones of the underlying bedrock. The "
    "weathered zone develops on granites, gneisses and related rocks, and its "
    "thickness and degree of fracturing control the groundwater potential. "
    "Groundwater quality and quantity can be favourable where the borehole "
    "position is properly located through appropriate hydrogeological and "
    "geophysical investigations."
)

_FREETOWN_GEOLOGY = (
    "The project area lies within the Freetown Basic Complex. The Freetown "
    "Complex is a layered gabbroic anorthosite intrusion emplaced against "
    "gneisses and schists of the Kasila Group, and it forms part of the "
    "Peninsula and Banana Islands. It is thought to have been formed by "
    "multiple injections of magma that occurred intermittently. Groundwater "
    "potential within the Freetown Basic Complex is found within weathered "
    "and fractured zones of these igneous (crystalline) rocks. Groundwater "
    "quality and quantity can be high if the borehole is properly located "
    "through appropriate hydrogeological and geophysical investigations."
)


@dataclass
class GeophysicalReportInputs:
    """Everything the geophysical survey report needs."""

    soundings: list[VESSounding]
    inversions: list[InversionResult]
    interpretations: list[SiteInterpretation]
    figures_dir: Path
    site_map_path: Path | None = None
    #: A real topographic map, drawn by
    #: :func:`groundwater.mapping.terrain.plot_topographic_map` from an
    #: elevation model the operator supplied. There is no default and none
    #: is generated: the toolkit bundles no elevation data, and a report
    #: that drew contours from nothing would be the worst figure in it.
    topographic_map_path: Path | None = None
    #: What the topographic map was drawn from, for its caption.
    topographic_map_credit: str = ""
    #: Ground surface along the traverse, from the levelled soundings.
    ground_profile_path: Path | None = None
    #: The study area at a readable scale, with its locator inset.
    study_area_map_path: Path | None = None
    #: Subsurface maps and sections built from this survey's own soundings,
    #: as ``(path, caption)`` pairs in the order they should appear.
    subsurface_figures: list[tuple[Path, str]] = field(default_factory=list)
    survey_photo_path: Path | None = None
    #: A previous interpretation of the same soundings, keyed by sounding
    #: id - the IPI2Win models transcribed from the original survey report,
    #: say. Each is drawn dashed on its curve figure and tabled beside the
    #: toolkit's model with its reported ERR and the ERR this toolkit gets
    #: for it on the same readings, so a difference is shown, not hidden.
    reference_models: dict | None = None
    reference_label: str = "IPI2Win model (as reported)"
    geology_text: str = ""
    reconnaissance_date: str = ""
    reconnaissance_notes: str = ""
    profiling_note: str = ""
    geologist_name: str = ""
    geologist_role: str = "Geologist / Field Supervisor"
    geologist_phone: str = ""
    flags: list[DataFlag] = field(default_factory=list)
    include_qa_annex: bool = False
    #: :class:`~groundwater.readiness.Readiness` for this report, from
    #: :func:`groundwater.readiness.assess_readiness`. When it is not
    #: certifiable the cover carries a PROVISIONAL stamp listing why.
    readiness: Any = None


def _geology_for(site, override: str) -> str:
    """The geology paragraph, from the map under the site.

    With a GPS fix the paragraph names the USGS unit the site sits on and
    the BGS aquifer class, through the same crosswalk the map legend uses,
    so the text and Figures 3 and 4 cannot disagree. Without a fix, the
    district's region decides; the Western Area gets the Freetown Complex
    paragraph because the whole peninsula is the Freetown Complex, not
    because the word "western" appears.
    """
    if override:
        return override
    district = getattr(site, "district", "") or ""
    latlon = getattr(site, "latlon", None)
    if latlon is not None:
        from ..mapping import aquifer_unit_at, geology_unit_at
        from ..mapping.lithology import describe
        from ..mapping.regional import _unit_district

        lat, lon = latlon
        unit = geology_unit_at(lat, lon)
        aquifer = aquifer_unit_at(lat, lon)
        parts = []
        if unit is not None:
            # Scoped by where the polygon is, as the map key is: scoped by
            # the sheet's district, a sheet that said Port Loko for a site on
            # the Freetown Complex got "Paleozoic Igneous (Pi)" here and
            # "Freetown Layered Complex" in the key of the figure beside it.
            told = describe(unit.glg, _unit_district(unit) or district)
            parts.append(
                "The site lies on the unit the USGS Geologic Map of Africa "
                f"maps as {unit.unit} ({unit.glg}). "
                + (told if told else "")
            )
        if aquifer is not None:
            parts.append(
                "The BGS Africa Groundwater Atlas classes the aquifer here as "
                f"{aquifer.unit}"
                + (f" ({aquifer.era.lower()})" if aquifer.era else "") + "."
            )
        if parts:
            return " ".join(p.strip() for p in parts) + (
                " Groundwater potential depends on the thickness of the "
                "weathered zone and the degree of fracturing beneath it, which "
                "the soundings below resolve."
            )
    if region_of(district) == "Western Area":
        return _FREETOWN_GEOLOGY
    return _DEFAULT_GEOLOGY


def build_geophysical_report(
    inputs: GeophysicalReportInputs,
    out_path: str | Path,
    config: Config | None = None,
) -> Path:
    """Write the geophysical survey report to ``out_path`` (.docx)."""
    config = config or Config()
    soundings = inputs.soundings
    if not soundings:
        raise ValueError("At least one sounding is required")
    site = soundings[0].site
    community = site.community or "the project area"
    district = site.district or ""
    client = site.client or "the client"

    rb = ReportBuilder(config.style, title=f"Geophysical Survey Report - {community}")

    # One ranking for the whole document, assigned before anything reads it:
    # the executive summary, the preference table, the suitability section
    # and the recommendations all name the same preferred point because they
    # all read `rank`, and rank is the confidence-weighted suitability.
    rank_interpretations(inputs.interpretations, config=config.ves)
    # One scorecard and one tie for the whole document. The study-area map,
    # the drill-target map, its caption and the text beside them all read
    # these: each map used to decide the tie again by a rule of its own, and
    # a report could call two points indistinguishable over a map that
    # starred one of them.
    suit = assess_siting(inputs.interpretations, config.ves)
    tie = ranking_tie(suit, within_points=config.ves.ranking_tie_points)
    # And the pair that tie names, for the summary, the conclusions and the
    # recommendations: a document that calls the top two indistinguishable in
    # one section and names a single preferred point in the others
    # contradicts itself. Both go through tied_leaders on the same margin.
    tied = _tied_pair(inputs.interpretations, config.ves)

    # ---- cover -------------------------------------------------------------
    rb.cover(
        title_lines=["GEOPHYSICAL SURVEY REPORT"],
        subtitle_lines=[
            "Groundwater Investigation for Borehole Siting",
            f"at {community}" + (f", {district} District"
                                 if district and "western" not in district.lower()
                                 else f", {district}" if district else ""),
        ],
        details=[
            ("Client", client),
            ("Project", site.project or "Geophysical Survey"),
            ("Survey date", soundings[0].site.date or ""),
            ("Prepared by", inputs.geologist_name or config.style.organisation or ""),
        ],
    )
    rb.provisional_stamp(inputs.readiness)

    # ---- table of contents ---------------------------------------------------
    rb.table_of_contents()

    # ---- executive summary ---------------------------------------------------
    exec_paras, exec_key = _executive_summary(soundings, inputs.interpretations,
                                              community, district, tied)
    rb.executive_summary(exec_paras, exec_key)

    # ---- 1 introduction --------------------------------------------------------
    rb.heading("1. Introduction", 1)
    rb.paragraph(
        "Geological and hydrogeological/geophysical investigations are "
        f"prerequisites for borehole drilling. {client} requested a "
        "geophysical investigation to site the borehole position at "
        f"{community}" + (f" in {district}" if district else "") + ". "
        "The study assessed the possibility of accessing groundwater in the "
        "project area, and the details of the investigations are documented "
        "in this report.",
        align="justify",
    )

    # ---- 2 background / geology ---------------------------------------------
    rb.heading("2. Background and Geology of the Project Area", 1)
    rb.paragraph(_geology_for(site, inputs.geology_text), align="justify")
    # the soundings go on the study area map, so a reader can see the survey
    # laid out in the area rather than having to hold two figures together;
    # the recommended one gets the one marker on a siting map that has to
    # be unmistakable, and the site star is not drawn on top of whichever
    # sounding happened to be first on the sheet. Two points the ranking
    # cannot separate get no star between them, as on the drill-target map.
    preferred = _preferred(inputs.interpretations)
    survey_overlay = [
        {"lat": s.site.latlon[0], "lon": s.site.latlon[1],
         "label": s.sounding_id,
         "kind": ("recommended point"
                  if s.sounding_id == preferred.sounding_id and not tie
                  else "VES point")}
        for s in soundings if s.site.latlon is not None
    ]
    context_maps = context_map_figures(site, inputs.figures_dir, config.style,
                                       points=survey_overlay, mark_site=False)
    if context_maps:
        if "study_area" in context_maps:
            caption = _study_area_caption(
                community, [p["label"] for p in survey_overlay],
                preferred.sounding_id, [s.sounding_id for s in suit[:2]], bool(tie),
            )
            spread = _survey_spread_km(soundings)
            if spread > 5.0:
                caption += (
                    f" The survey points are up to {spread:.1f} km apart, which "
                    "is unusually far for one site; the positions should be "
                    "checked against the field notes."
                )
            caption += " Boundaries from geoBoundaries (CC BY 4.0)."
            rb.figure(context_maps["study_area"], caption)
        rb.figure(
            context_maps["admin"],
            f"Location of {community}. Boundaries from geoBoundaries "
            "(CC BY 4.0).",
        )
        rb.figure(
            context_maps["hydrogeology"],
            "Aquifer type and productivity around the site, from the BGS "
            "Africa Groundwater Atlas country map (CC BY-SA 4.0).",
        )
        rb.figure(
            context_maps["geology"],
            "Geological setting around the site, from the USGS Geologic "
            "Map of Africa (1:5,000,000). The Geology of Sierra Leone map "
            "(Ministry of Water Resources/SALWACO, 2017) gives the "
            "detailed local formations.",
        )

    # ---- 3 field work -----------------------------------------------------------
    rb.heading("3. Field Work", 1)
    rb.heading("3.1 Reconnaissance Survey", 2)
    # What this section says has to be evidenced by the inputs. It used to
    # assert a reconnaissance dated the survey day, a geomorphological
    # survey of slopes and streams, and a formation assessment, for every
    # survey, whatever the sheets held: a client read a day of field work
    # nobody had recorded. A recorded date or notes are printed; without
    # them the section says so.
    if inputs.reconnaissance_date or inputs.reconnaissance_notes:
        rb.paragraph(
            "The reconnaissance survey selected the points for the "
            "geophysical survey"
            + (f" and was conducted on {inputs.reconnaissance_date}"
               if inputs.reconnaissance_date else "")
            + ".",
            align="justify",
        )
        if inputs.reconnaissance_notes:
            rb.paragraph("Field observations", bold=True)
            rb.paragraph(inputs.reconnaissance_notes, align="justify")
    else:
        rb.paragraph(
            "No reconnaissance record (date or field observations) was "
            "supplied with the sounding data, so none is reported here. The "
            "sounding points were taken as recorded on the field sheets"
            + (f", dated {site.date}" if site.date else "") + ".",
            align="justify",
        )
    rb.paragraph(
        "The weathered zone over the bedrock and the fractured rock beneath "
        "it are the groundwater prospects in this ground, and the soundings "
        "below are interpreted for both.",
        align="justify",
    )
    if inputs.site_map_path and Path(inputs.site_map_path).exists():
        # Captioned for what it is. This said "Topographic map of the project
        # area" over whatever figure a caller passed, and what callers pass is
        # a survey point location map: no elevation, no contour, no relief.
        # A reader looking for the valley on a topographic map and finding a
        # scatter of pegs has been told something untrue about the evidence.
        # A real topographic map needs an elevation model, which this toolkit
        # does not carry; groundwater.mapping.terrain draws one from a model
        # the operator supplies, and inputs.topographic_map_path is where it
        # goes when there is one.
        rb.figure(inputs.site_map_path,
                  f"Survey point location map of the project area at {community}.")
    if inputs.topographic_map_path and Path(inputs.topographic_map_path).exists():
        rb.figure(
            inputs.topographic_map_path,
            f"Topographic map of the project area at {community}. "
            f"{inputs.topographic_map_credit}".strip(),
        )
    else:
        # silent before: a report with no topographic map said nothing
        # about why, and a reader took the survey point map for one
        rb.paragraph(
            "No elevation model was supplied with this survey, so no "
            "topographic map is drawn: the toolkit bundles none and invents "
            "none. The elevations the crew recorded at the soundings are "
            "the ground levels this report has.",
            align="justify",
        )
    profile_path = inputs.ground_profile_path
    profile_caption = GROUND_PROFILE_CAPTION
    # why the survey's own profile is not drawn, for the "not drawn" list
    profile_refusal = ""
    if not (profile_path and Path(profile_path).exists()):
        profile_path, profile_caption, profile_refusal = _ground_profile_figure(
            inputs, community)
    if profile_path is not None:
        rb.figure(profile_path, profile_caption)

    rb.paragraph("Sounding positions", bold=True)
    placed = [s for s in soundings if s.site.easting is not None and s.site.northing is not None]
    # named only where the positions are drawn: the survey point map is a
    # figure a caller may or may not supply, and a sentence pointing at it
    # in a report without one sent the reader looking for a figure that is
    # not there
    if not placed:
        plotted_on = ""
    elif inputs.site_map_path and Path(inputs.site_map_path).exists():
        plotted_on = ", plotted on the survey point map"
    elif survey_overlay and "study_area" in (context_maps or {}):
        plotted_on = ", marked on the study area map"
    else:
        plotted_on = ""
    rb.paragraph(
        f"{plural(len(placed), 'sounding')} of {len(soundings)} "
        + ("carry" if len(placed) != 1 else "carries")
        + f" a recorded GPS position{plotted_on}. "
        + (inputs.profiling_note if inputs.profiling_note else
           "How the points were chosen on the ground is not recorded on the "
           "field sheets; where a traverse or profiling was run, its notes "
           "belong in the reconnaissance record above."),
        align="justify",
    )

    rb.heading("3.2 Geophysical Survey", 2)
    instrument = soundings[0].instrument or "Syscal Junior"
    rb.paragraph(
        "The geophysical survey consisted of electrical resistivity "
        "measurements, specifically vertical electrical sounding (VES) "
        f"using the {instrument} instrument.",
        align="justify",
    )
    if inputs.survey_photo_path and Path(inputs.survey_photo_path).exists():
        rb.figure(
            inputs.survey_photo_path,
            f"Geophysical survey using the {instrument} equipment.",
        )

    rb.heading("3.2.1 Vertical Electrical Sounding (VES)", 3)
    labels = ", ".join(s.sounding_id for s in soundings)
    arrays = sorted({(s.array_type or "schlumberger").capitalize() for s in soundings})
    rb.paragraph(
        f"{plural(len(soundings), 'vertical electrical sounding')} "
        f"({labels}) {'was' if len(soundings) == 1 else 'were'} recorded with "
        f"the {' and '.join(arrays)} electrode configuration, to determine the "
        "formation resistivities and the depth to bedrock, and whether water "
        "bearing fractures or a saturated weathered zone are present at depth "
        "and how thick they are. No resistivity profiling record was supplied"
        + ("." if not inputs.profiling_note else
           "; the profiling note above describes what was run."),
        align="justify",
    )

    # ---- 4 data analysis ------------------------------------------------------
    rb.heading("4. Data Analysis and Interpretation", 1)
    # one inversion and one interpretation per sounding, built in lockstep by
    # every caller: a short list silently drops a point's whole analysis block
    # while the preference table below still ranks it
    references = inputs.reference_models or {}
    for sounding, inversion, interp in zip(
        soundings, inputs.inversions, inputs.interpretations, strict=True
    ):
        _sounding_block(rb, sounding, inversion, interp, inputs.figures_dir,
                        config=config.ves,
                        reference_model=references.get(sounding.sounding_id),
                        reference_label=inputs.reference_label)

    # ---- preference table -----------------------------------------------------
    rows = drilling_preference_table(inputs.interpretations, config=config.ves)
    header = list(rows[0].keys()) if rows else []
    open_ended = any(i.basement_not_resolved for i in inputs.interpretations)
    rb.table(
        [[row[h] for h in header] for row in rows],
        header=header,
        caption=(
            "List of VES points in order of preference for drilling. The "
            "resistivities are those of the fitted layers, not the apparent "
            "resistivities read in the field."
            + (" A water zone marked + continues below the depth the "
               "sounding resolves, so its base and the drilling depth are "
               "minima." if open_ended else "")
            + (" The two points marked =1st cannot be told apart on "
               "geophysical grounds." if tied else "")
        ),
        font_size_pt=8.5,
    )

    # ---- drill-target suitability --------------------------------------------
    _suitability_block(rb, inputs, site, config.ves, suit=suit, tie=tie,
                       profile_refusal=profile_refusal)

    # ---- 5 conclusions and recommendations -------------------------------------
    rb.heading("5. Conclusions and Recommendations", 1)
    rb.paragraph("Conclusions:", bold=True)
    conclusions = _conclusions(inputs.interpretations, district, community, tied)
    rb.bullets(conclusions)
    rb.paragraph("Recommendations:", bold=True)
    rb.bullets(_recommendations(inputs.interpretations, tied))

    # ---- 6 limitations and uncertainty -----------------------------------------
    rb.heading("6. Limitations and Uncertainty", 1)
    rb.bullets(_limitations(inputs.inversions, inputs.interpretations, config.ves,
                            soundings))

    # ---- QA annex (optional) -----------------------------------------------------
    notes = _verification_notes(inputs.flags, soundings)
    if inputs.include_qa_annex and notes:
        rb.heading("Annex A. Data Verification Notes", 1)
        rb.paragraph(
            "The following checks were raised automatically during data "
            "processing and should be verified against the field notes."
        )
        rb.bullets([str(f) for f in notes])

    # ---- references and glossary -----------------------------------------------
    rb.references(references_for("geophysical"))
    rb.glossary(GLOSSARY)

    # ---- signature ------------------------------------------------------------
    rb.signature_block(
        name=inputs.geologist_name or soundings[0].site.supervisor or "",
        role=inputs.geologist_role,
        phone=inputs.geologist_phone,
        organisation=config.style.organisation,
    )

    return rb.save(out_path)


def depth_of_investigation_text(
    array_type: str, max_spacing_m: float, doi_m: float, config: VESConfig | None = None
) -> str:
    """How deep the soundings of one array resolve, in the array's own terms.

    Worded once for both engines. A Wenner sounding's spacing is a, and it
    used to be reported as "AB/2 expanded to 60 m" when AB/2 was 90 m.
    """
    config = config or VESConfig()
    fraction = config.depth_of_investigation_factor
    fraction_text = "half" if abs(fraction - 0.5) < 1e-9 else f"{fraction:g} times"
    if str(array_type).startswith("wenner"):
        # A M N B at equal spacing a: AB = 3a, so AB/2 is 1.5 a
        return (
            "A Wenner sounding resolves the ground to roughly "
            f"{fraction_text} its largest electrode spacing a, not to the spacing "
            f"itself: with a expanded to {fmt_num(max_spacing_m)} m (AB/2 of "
            f"{fmt_num(1.5 * max_spacing_m)} m) the depth of investigation here is "
            f"about {fmt_num(doi_m)} m, and any structure below it is not resolved."
        )
    return (
        "A Schlumberger sounding resolves the ground to roughly "
        f"{fraction_text} its largest AB/2, not to the spacing itself: with "
        f"AB/2 expanded to {fmt_num(max_spacing_m)} m the depth of "
        f"investigation here is about {fmt_num(doi_m)} m, and any "
        "structure below it is not resolved."
    )


def _limitations(
    inversions: list[InversionResult],
    interpretations: list[SiteInterpretation] | None = None,
    config: VESConfig | None = None,
    soundings: list[VESSounding] | None = None,
) -> list[str]:
    """Honest, calibrated limitations for the VES interpretation."""
    config = config or VESConfig()
    interpretations = interpretations or []
    # the reach of each array in its own terms, the soundings and the
    # interpretations being built in lockstep by every caller
    arrays = [s.array_type for s in soundings] if soundings else []
    reach: dict[str, tuple[float, float]] = {}
    for k, interp in enumerate(interpretations):
        if not (interp.max_spacing_m and interp.investigation_depth_m):
            continue
        kind = "wenner" if k < len(arrays) and arrays[k].startswith("wenner") else "schlumberger"
        spacing, doi = reach.get(kind, (0.0, 0.0))
        reach[kind] = (max(spacing, interp.max_spacing_m),
                       max(doi, interp.investigation_depth_m))
    if reach:
        depth_item = " ".join(
            depth_of_investigation_text(kind, spacing, doi, config)
            for kind, (spacing, doi) in sorted(reach.items())
        ) + " A layer that continues to that depth has no base in these data."
    else:
        depth_item = (
            "The depth of investigation is a fraction of the largest electrode "
            "spacing (roughly half of AB/2 for a Schlumberger sounding), so any "
            "structure below it is not resolved."
        )
    items = [
        ("Resistivity models are not unique: different layered models can fit "
        "the same sounding curve almost equally well (the equivalence and "
        "suppression problem), so the interpreted layer depths and "
        "thicknesses carry an uncertainty of the order of plus or minus 20 "
        "percent."),
        ("A low resistivity layer can represent either a saturated, water "
        "bearing zone or a conductive clay; the interpretation is made from "
        "the geological context and must be confirmed by drilling."),
        depth_item,
        ("The survey indicates groundwater potential only. The actual yield and "
        "water quality can be confirmed only by test drilling, test pumping "
        "and laboratory analysis."),
    ]
    errs = [inv.fit_error_percent for inv in inversions if inv.fit_error_percent is not None]
    if errs:
        worst = max(errs)
        sentence = (
            "The fitted models reproduce the measured apparent resistivities "
            f"to within {worst:.1f} percent (ERR); a larger misfit means a "
            "less certain model."
        )
        if worst > config.target_fit_percent:
            over = [
                inv.model.sounding_id or f"sounding {k + 1}"
                for k, inv in enumerate(inversions)
                if inv.fit_error_percent is not None
                and inv.fit_error_percent > config.target_fit_percent
            ]
            sentence += (
                f" The target is {config.target_fit_percent:g} percent, and "
                + ", ".join(over)
                + (" does" if len(over) == 1 else " do")
                + " not reach it: the layer depths there are indicative, and "
                "the ranking discounts them for it."
            )
        items.insert(0, sentence)
    return items


def _verification_notes(flags: list[DataFlag], soundings: list[VESSounding]) -> list[DataFlag]:
    """The caller's checks, then every warning the sheets raised, once each.

    The sounding flags stayed on the soundings: two overlap readings at
    AB/2 40 m disagreeing by a factor of 1.98, or a Wenner sheet carrying a
    Schlumberger MN column, reached no document, while the annex promised
    "the checks raised automatically during data processing". A flag with
    no context of its own is given its sounding's, so the reader can tell
    which sheet to check.
    """
    notes = list(flags)
    seen = {str(f) for f in notes}
    for sounding in soundings:
        for flag in sounding.flags:
            if flag.level not in ("warning", "error"):
                continue
            if not flag.context:
                flag = DataFlag(flag.level, flag.code, flag.message, sounding.sounding_id)
            if str(flag) not in seen:
                seen.add(str(flag))
                notes.append(flag)
    return notes


def _tied_pair(
    interpretations: list[SiteInterpretation], config: VESConfig
) -> list[SiteInterpretation]:
    """The two top-ranked points when the ranking cannot separate them, else [].

    Decided by :func:`~groundwater.siting.tied_leaders` on the unrounded
    confidence-weighted scores, the test the suitability section's tie
    sentence and the preference table's "=1st" use. The two ranked first
    here are the two it tests: both orders sort on the same weights.
    """
    if tied_leaders(assess_siting(interpretations, config), config.ranking_tie_points) is None:
        return []
    return sorted(interpretations, key=lambda i: i.rank or 99)[:2]


def models_tried_text(inversion: InversionResult, config: VESConfig | None = None) -> str:
    """"Models tried: ..." under a sounding's model table, or "".

    What else was tried, so the model in the table is seen as one choice
    among the candidates rather than the only reading of the curve. Worded
    once for both engines.
    """
    config = config or VESConfig()
    trials = [(n, e) for n, e in inversion.trials if e is not None]
    if len(trials) < 2:
        return ""
    tried = "; ".join(f"{n} layers, {e:.1f}%" for n, e in trials)
    chosen = inversion.model.n_layers
    target = config.target_fit_percent
    if inversion.fit_error_percent <= target:
        # "the simplest that reaches the target" was false whenever a
        # simpler model reached it too and was passed over because a richer
        # one more than halved its misfit (the parsimony rule)
        simpler = [n for n, e in trials if n < chosen and e <= target]
        if simpler:
            best_n = min(trials, key=lambda t: t[1])[0]
            ratio = config.parsimony_max_error_ratio
            cut = ("more than halves" if abs(ratio - 2.0) < 1e-9
                   else f"cuts by more than a factor of {ratio:g}")
            one = len(simpler) == 1
            why = (
                f"the {and_join([f'{n}-layer' for n in simpler])} "
                f"{'model also reaches' if one else 'models also reach'} the "
                f"{target:g} percent target, but "
                + (f"the {chosen}-layer model {cut} {'its' if one else 'their'} "
                   "misfit and is preferred"
                   if best_n == chosen else
                   f"the {best_n}-layer model {cut} {'its' if one else 'their'} "
                   f"misfit, and the {chosen}-layer model is the simplest it "
                   "does not better that far")
            )
        else:
            why = (
                f"the {chosen}-layer model is the simplest that reaches the "
                f"{target:g} percent target"
            )
    else:
        why = (
            f"none reaches the {target:g} percent target, "
            f"and the {chosen}-layer model is kept as the simplest within "
            f"{(config.parsimony_fallback_ratio - 1) * 100:.0f} percent of "
            "the best fit; the alternatives are equally admissible readings "
            "of the same curve"
        )
    return f"Models tried: {tried}. Of these {why}."


def poorly_resolved_text(model: LayeredModel) -> str:
    """The sentence naming each poorly resolved boundary, or "".

    Worded once for both engines, with the same test the interpretation
    softens its opening sentence on.
    """
    weak = poorly_resolved_boundaries(model)
    if not weak:
        return ""
    one = len(weak) == 1
    return (
        f"The {'boundary' if one else 'boundaries'} at "
        + and_join([f"{fmt_num(z)} m (x/ {f:.1f})" for z, f in weak])
        + f" {'is' if one else 'are'} poorly resolved: within "
        f"{'its' if one else 'their'} uncertainty the model collapses to one "
        f"with {'a layer fewer' if one else 'fewer layers'}, so the layer count "
        "above is a reading of the curve rather than a property of it."
    )


def _site_slug(site) -> str:
    """Filename fragment identifying the survey site."""
    return safe_slug(getattr(site, "community", "") or "site", "site")


def _study_area_caption(
    community: str,
    marked: list[str],
    preferred: str,
    leaders: list[str],
    tie: bool,
) -> str:
    """The study-area caption, worded from what was overlaid on the map.

    It used to promise the survey points and a star on the recommended
    point whatever the map held: over a map with no sounding on it, over
    a recommended point with no recorded position, and over two points the
    ranking calls indistinguishable, one of which carried the star.
    ``marked`` are the soundings drawn on the map.
    """
    if not marked:
        return (
            f"Study area at {community}, with its location in Sierra Leone "
            "inset. No sounding carries a recorded GPS position, so none is "
            "marked on it."
        )
    caption = (
        f"Study area at {community}, with the survey points and its location "
        "in Sierra Leone inset."
    )
    if tie and len(leaders) >= 2:
        caption += (
            f" {leaders[0]} and {leaders[1]} cannot be told apart on geophysical "
            "grounds, so neither is starred."
        )
        missing = [label for label in leaders[:2] if label not in marked]
        if missing:
            caption += " " + unplaced_text(missing, "the map")
    elif preferred in marked:
        caption += f" The star is the recommended drilling point, {preferred}."
    else:
        caption += (
            f" The recommended drilling point, {preferred}, has no recorded "
            "position and is not on the map."
        )
    return caption


def _survey_spread_km(soundings: list[VESSounding]) -> float:
    """The largest distance between any two positioned soundings, in km."""
    from ..geo import geodesic_distance_m

    placed = [s.site.latlon for s in soundings if s.site.latlon is not None]
    widest = 0.0
    for a in range(len(placed)):
        for b in range(a + 1, len(placed)):
            widest = max(widest, geodesic_distance_m(placed[a][0], placed[a][1],
                                                     placed[b][0], placed[b][1]))
    return widest / 1000.0


def _sounding_block(
    rb: ReportBuilder,
    sounding: VESSounding,
    inversion: InversionResult,
    interp: SiteInterpretation,
    figures_dir: Path,
    config: VESConfig | None = None,
    reference_model=None,
    reference_label: str = "reference model",
) -> None:
    """One data analysis block per sounding: tables, figures, narrative."""
    config = config or VESConfig()
    site = sounding.site
    sid = sounding.sounding_id
    # site as well as sounding id: two surveys both with a sounding "A"
    # share one figures directory in an app session, and generation is
    # guarded by an existence check, so the second reused the first's curve.
    safe_id = f"{_site_slug(site)}_{safe_slug(sid, 'ves')}"

    # data table with the field sheet header block
    table_no = rb.next_table_number
    # A Wenner sounding reaches this table now that the reader can take one,
    # and the table was hard-coded Schlumberger: the spacing column was
    # headed AB/2 although it held a, and the MN column printed "n/a" on
    # every row of a sounding that has no MN by construction.
    is_wenner = sounding.array_type.startswith("wenner")
    array_name = "Wenner" if is_wenner else "Schlumberger"
    spacing_text = (
        "the electrode spacing a"
        if is_wenner
        else "half the current electrode spacing (AB/2)"
    )
    rb.paragraph(
        f"Table {table_no} presents the {array_name} array VES data recorded "
        f"at point {sid}, from which the sounding curve of apparent "
        f"resistivity against {spacing_text} in "
        f"Figure {rb.next_figure_number} is plotted.",
        align="justify",
    )
    rb.header_block_table(
        [
            ("Client", site.client), ("Community", site.community),
            ("Project", site.project or "Geophysical Survey"), ("Sounding Number", sid),
            ("District", site.district), ("GPS Coordinate East", utm_text(site, "easting")),
            ("Date", site.date), ("GPS Coordinate North", utm_text(site, "northing")),
            ("Field Supervisor", site.supervisor),
            ("Elevation", fmt_num(site.elevation_m) + " m" if site.elevation_m else ""),
        ]
    )
    # the parser appends AB/2, MN and rho per row (blank MN becomes NaN),
    # so a length mismatch means a hand-built sounding, not a short sheet
    triples = list(zip(sounding.ab2, sounding.mn, sounding.rho_app, strict=True))
    if is_wenner:
        rows = [[i + 1, fmt_num(a), fmt_num(r, 4)] for i, (a, _m, r) in enumerate(triples)]
        header = ["No.", "a (m)", "Apparent Resistivity (ohm-m)"]
        widths = [1.5, 3.0, 7.0]
    else:
        rows = [[i + 1, fmt_num(a), fmt_num(m), fmt_num(r, 4)]
                for i, (a, m, r) in enumerate(triples)]
        header = ["No.", "AB/2 (m)", "MN (m)", "Apparent Resistivity (ohm-m)"]
        widths = [1.5, 3.0, 3.0, 7.0]
    rb.table(
        rows,
        header=header,
        caption=f"{array_name} array VES data at point {sid}.",
        col_widths_cm=widths,
    )

    # curve + model figure, drawn to the depth of investigation or to the
    # deepest fitted interface below it, with the reference interpretation
    # dashed beside the toolkit's where one exists
    curve_path = figures_dir / f"ves_curve_{safe_id}.png"
    plot_sounding_curve(
        sounding, inversion.model, inversion.rho_calc, inversion.ab2, path=curve_path,
        depth_max=interp.investigation_depth_m or None,
        reference_model=reference_model, reference_label=reference_label,
    )
    rb.figure(
        curve_path,
        # the array the table above names: a Wenner table used to be
        # followed by a figure captioned "Schlumberger array VES curve"
        f"{array_name} array VES curve and model at point {sid}."
        + (f" The dashed line is the {reference_label}." if reference_model is not None else "")
        + f" The model panel is drawn {_drawn_depth_text(inversion.model, interp)}.",
    )

    # model table (IPI2Win layout) with linearised uncertainty factors
    rho_fac = inversion.rho_uncertainty_factor
    h_fac = inversion.h_uncertainty_factor
    model_rows = []
    for i, row in enumerate(inversion.model.as_table()):
        rho_cell = fmt_num(row["rho_ohm_m"], 4)
        if rho_fac is not None and i < len(rho_fac):
            rho_cell += f" (x/ {rho_fac[i]:.1f})"
        if row["h_m"] is not None:
            h_cell = fmt_num(row["h_m"])
            if h_fac is not None and i < len(h_fac):
                h_cell += f" (x/ {h_fac[i]:.1f})"
        else:
            h_cell = "half-space"
        model_rows.append([row["N"], rho_cell, h_cell, _depth_to_top_cell(row["z_m"])])
    err = inversion.fit_error_percent
    rb.table(
        model_rows,
        header=["N", "rho (ohm-m)", "h (m)", "z (m)"],
        caption=(
            f"Layered earth model at point {sid} "
            f"(curve type {classify_curve(inversion.model)}, ERR = {err:.1f}%). "
            "z is the depth to the top of each layer. "
            "The (x/ factor) is the linearised 1-sigma uncertainty; a factor "
            "near 1 is well resolved and a large factor marks equivalence."
        ),
        col_widths_cm=[1.2, 4.6, 3.4, 2.8],
    )
    tried = models_tried_text(inversion, config)
    if tried:
        rb.paragraph(tried, align="justify")
    # a poorly resolved boundary is said to be one, in the sentence that
    # the table caption's factor already implies
    weak = poorly_resolved_text(inversion.model)
    if weak:
        rb.paragraph(weak, align="justify")
    if reference_model is not None:
        _reference_model_block(rb, sid, inversion, reference_model, reference_label,
                               sounding.array_type)

    # the interpreted layer column, drawn to the same depth as the model panel
    layer_path = figures_dir / f"ves_layer_section_{safe_id}.png"
    plot_model_pseudosection(
        inversion.model,
        path=layer_path,
        investigation_depth_m=interp.investigation_depth_m or None,
        title=f"Layer section at {sid}",
    )
    rb.figure(
        layer_path,
        f"Interpreted one-dimensional layer section at point {sid}: the "
        "resistivity and thickness of each fitted layer, drawn "
        f"{_drawn_depth_text(inversion.model, interp)}.",
    )

    # interpretation paragraph
    rb.paragraph(interp.narrative, align="justify")
    rb.page_break()


def _depth_to_top_cell(z) -> str:
    """The z column of a model table: the depth to the layer's top.

    ``as_table()`` writes the surface row's z as IPI2Win's "0/0", and the
    report used to print that as "half-space" - on the first layer, the one
    at the surface - while the real half-space row carried no label at all.
    """
    return "0" if z == "0/0" else fmt_num(z)


def _drawn_depth_text(model, interp: SiteInterpretation) -> str:
    """How deep a figure of one sounding's model is drawn, for its caption.

    Both figures of a sounding's model are drawn to
    :func:`~groundwater.ves.plots.model_depth_m`: the depth of
    investigation, or deeper where a fitted interface lies below it. The
    captions used to say "drawn to the depth of investigation (50 m)" over
    a panel running to 75 m.
    """
    doi = float(interp.investigation_depth_m or 0.0)
    drawn = model_depth_m(model, doi)
    if drawn <= doi:
        return f"to the depth of investigation ({fmt_num(doi)} m)"
    return (
        f"to {fmt_num(drawn)} m so that the deepest fitted interface stays on "
        f"it; the red line marks the depth of investigation ({fmt_num(doi)} m), "
        "below which the readings do not resolve the model"
    )


def _reference_model_block(rb, sid, inversion, reference_model, label,
                           array_type: str = "schlumberger") -> None:
    """The previous interpretation of the same curve, beside the toolkit's.

    The comparison the reader will make anyway is made for them: the
    reference model's layers, the ERR it reported, and the ERR this
    toolkit computes for that model on the same readings. Where the two
    ERRs disagree, the reader is told rather than left to find it.
    """
    from ..ves.forward import forward_schlumberger, forward_wenner
    from ..ves.inversion import fit_error_percent

    forward = forward_wenner if str(array_type).startswith("wenner") else forward_schlumberger
    recomputed = fit_error_percent(inversion.rho_obs, forward(reference_model, inversion.ab2))
    reported = reference_model.fit_error_percent
    rows = [
        [row["N"], fmt_num(row["rho_ohm_m"], 4),
         "half-space" if row["h_m"] is None else fmt_num(row["h_m"]),
         _depth_to_top_cell(row["z_m"])]
        for row in reference_model.as_table()
    ]
    caption = f"{label[0].upper() + label[1:]} at point {sid}"
    if reported is not None:
        caption += f", reported ERR = {reported:.1f}%"
    caption += f"; on the readings tabled above this toolkit computes ERR = {recomputed:.1f}%."
    rb.table(rows, header=["N", "rho (ohm-m)", "h (m)", "z (m)"], caption=caption,
             col_widths_cm=[1.2, 4.6, 3.4, 2.8])
    own = inversion.model
    sentences = []
    if reference_model.n_layers != own.n_layers:
        sentences.append(
            f"The reference interpretation has {reference_model.n_layers} layers "
            f"where this one has {own.n_layers}."
        )
    if reported is not None and abs(recomputed - reported) > 5.0:
        sentences.append(
            f"Its reported misfit ({reported:.1f} percent) is not reproduced on "
            f"these readings ({recomputed:.1f} percent): either the readings "
            "it was fitted to differ from the transcribed sheet, or the misfit "
            "was defined differently. Neither is settled here."
        )
    if sentences:
        rb.paragraph(" ".join(sentences), align="justify")


def _suitability_block(rb: ReportBuilder, inputs, site,
                       config: VESConfig | None = None, suit=None,
                       tie: str | None = None, profile_refusal: str = "") -> None:
    """Ranked drill-target suitability scorecard, map and recommendation.

    ``suit`` and ``tie`` are the report's one scorecard and tie sentence;
    ``profile_refusal`` is why the ground profile was not drawn, for the
    subsurface section's list of what was not.
    """
    config = config or VESConfig()
    if suit is None:
        suit = assess_siting(inputs.interpretations, config)
    if not suit:
        return
    rb.heading("Drill-target suitability", 2)
    rb.paragraph(
        "Each surveyed point is given a transparent suitability score from 0 "
        "to 100. The score combines the interpreted water-bearing thickness, "
        "how well the resistivity of the water zone sits within the productive "
        "fractured or weathered window, the overburden profile, and the "
        "presence of a fractured zone at the basement contact. The scores "
        "rank the points as drilling targets.",
        align="justify",
    )
    rb.table(
        [[s.rank, s.sounding_id, f"{s.suitability:.1f}", f"{s.confidence:.2f}",
          f"{s.weighted:.1f}", s.grade] for s in suit],
        header=["Rank", "VES point", "Suitability (0 to 100)", "Confidence",
                "Weighted", "Grade"],
        caption=(
            "Drill-target suitability of the surveyed points. Suitability is "
            "the geological score; confidence discounts it for a model fit "
            "above the target and for a water-bearing zone whose base the "
            "sounding never reached; the points are ranked on the weighted "
            "figure."
        ),
        col_widths_cm=[1.4, 3.0, 3.6, 2.4, 2.2, 3.4],
    )
    # the same rank the rest of the document carries: rank_interpretations()
    # ranks on the weighted suitability, so the table above and the preferred
    # point named everywhere else agree by construction
    if tie is None:
        tie = ranking_tie(suit, within_points=config.ranking_tie_points)
    rb.paragraph(suitability_verdict(suit, within_points=config.ranking_tie_points),
                 align="justify")
    # every point in one zone, the one the rest of the survey's figures are
    # drawn in, and the tie and the order the text above was written from
    zone = site.utm_zone or survey_zone(inputs.interpretations)
    map_points = suitability_map_points(suit, zone)
    if map_points:
        ranking = [s.sounding_id for s in suit]
        smap = Path(inputs.figures_dir) / f"suitability_map_{_site_slug(site)}.png"
        try:
            suitability_map(map_points, zone, path=smap, tie=bool(tie), ranking=ranking)
        except (ValueError, RuntimeError) as exc:
            rb.paragraph(f"The drill-target map could not be drawn: {exc}")
        else:
            state = suitability_map_state(map_points, tie=bool(tie), ranking=ranking)
            rb.figure(smap, _suitability_caption(state))

    _add_subsurface_figures(rb, inputs.soundings, inputs.interpretations,
                            inputs, site, profile_refusal=profile_refusal)


def _suitability_caption(state: dict) -> str:
    """The drill-target map's caption, from the state the map was drawn in.

    Each clause is a claim about the figure: that a star marks the target,
    or that none does because the two best points cannot be separated or
    the best has no position; that the colour between the pegs is
    interpolated ground, or that there is none.
    """
    caption = (
        "Drill-target suitability of the surveyed points, coloured by the "
        "confidence-weighted score; greener is more suitable. Each point is "
        "labelled with its rank and weighted score, and, where the map has "
        "room, with the grade of its suitability before the confidence "
        "discount, as in the table above."
    )
    if state["tie"]:
        caption += (
            " The two highest-ranked points cannot be told apart on "
            "geophysical grounds, so neither is starred."
        )
        if state["unplaced"]:
            caption += " " + unplaced_text(state["unplaced"], "the map")
    elif state["recommended"]:
        caption += (
            f" The star is the recommended target, {state['recommended']}, "
            "with its grid coordinates."
        )
    elif state["unplaced"]:
        caption += (
            f" The recommended target, {state['unplaced'][0]}, has no recorded "
            "position and is not on the map, so no point is starred."
        )
    if state["surface"]:
        caption += (
            " The surface between the points is interpolated and blanked "
            "outside the ground they enclose."
        )
    elif state["n_points"] >= 3:
        caption += (
            " The points lie on one line and enclose no area, so no surface is "
            "interpolated between them."
        )
    return caption


def _pseudosection_caption(spacing: str, profile) -> str:
    """The pseudo-section's caption, naming the spacing it was read against.

    It said "AB/2 is that spacing" over Wenner readings, whose spacing is a.
    """
    caption = (
        "Apparent resistivity along the traverse, as measured. Unlike every "
        "other section in this report it involves no inversion: each point is "
        "a reading at the station and electrode spacing it was taken with. "
        + {"AB/2": "AB/2 is that spacing, not a depth.",
           "a": "The Wenner spacing a is that spacing, not a depth."}.get(
            spacing, "AB/2 and a are those spacings, not depths.")
        + " Colour is interpolated only between stations within reach of each "
        "other."
    )
    if not profile.is_collinear:
        caption += (
            f" The soundings sit up to {profile.max_offset_m:.0f} m off the "
            "profile line, so this section cuts across the survey rather than "
            "along it."
        )
    return caption


#: The four subsurface maps: the function, the file stem, the name the "not
#: drawn" list gives it, and what the map is. What the figure then shows -
#: a surface or only the values at the points, and which values are minima -
#: is added by :func:`_subsurface_caption` from the points it was drawn from.
_SUBSURFACE_MAPS = (
    (depth_to_bedrock_map, "depth_to_bedrock", "depth to bedrock map",
     "Depth to bedrock across the surveyed ground, from the layered models."),
    (aquifer_thickness_map, "aquifer_thickness", "aquifer thickness map",
     ("Interpreted thickness of the weathered and fractured zone - the "
      "section a borehole is completed in.")),
    (bedrock_elevation_map, "bedrock_elevation", "bedrock elevation map",
     ("The bedrock surface as a landform, from the ground elevation "
      "recorded at each sounding less its depth to basement. A low in this "
      "surface is a buried valley, which basement groundwater drains towards.")),
    (protective_capacity_map, "protective_capacity", "protective capacity map",
     ("Protective capacity of the cover over the aquifer, from the "
      "longitudinal conductance of the overlying layers. It rates how well "
      "the ground above the aquifer resists downward contamination; it says "
      "nothing about yield.")),
)


def _subsurface_points(key: str, interpretations: list, zone: int) -> list:
    """The points a subsurface map is drawn from, as the map itself builds them."""
    from ..mapping import bedrock_elevation_points

    if key == "bedrock_elevation":
        return bedrock_elevation_points(interpretations, zone)
    attribute = {
        "depth_to_bedrock": "depth_to_basement_m",
        "aquifer_thickness": "aquifer_thickness_m",
        "protective_capacity": "protective_conductance_s",
    }[key]
    return subsurface_map_points(interpretations, attribute, zone)


def _subsurface_caption(what: str, points: list) -> tuple[str, bool]:
    """A subsurface map's caption, written from what the map shows.

    The captions were fixed strings, and "the surface is blanked outside
    the hull of the soundings" sat under a figure of three collinear
    soundings that said on its own face "surface not drawn". Returns the
    caption and whether a surface was drawn.
    """
    surface = len(points) >= 3 and points_enclose_an_area(
        [p.easting for p in points], [p.northing for p in points])
    caption = what
    if surface:
        caption += (" The surface is interpolated between the soundings and "
                    "blanked outside the ground they enclose.")
    elif len(points) >= 3:
        caption += (" The soundings lie on one line and enclose no area, so no "
                    "surface is drawn; the values are printed at the points.")
    else:
        caption += (" With fewer than three soundings no surface is drawn; "
                    "each point is coloured by its class.")
    minima = [p.label for p in points if p.minimum]
    if minima:
        caption += (
            f" The value at {', '.join(minima)} is a minimum, labelled "
            "\"at least\": the sounding did not resolve the base of the zone "
            "there."
        )
    return caption, surface


def _add_subsurface_figures(rb, soundings, interpretations, inputs, site,
                            profile_refusal: str = "") -> None:
    """Maps of the ground under the site, from the soundings themselves.

    Everything in this section is this survey's own measurement: the
    regional geology and aquifer maps earlier in the report are national
    datasets read at a point, and at 1:5,000,000 they cannot say what is
    under one village. These can, within the ground the survey covered.

    Each figure is attempted and skipped if the data will not support it,
    because the reasons differ per figure and none of them should cost
    the report the others: a survey whose curves never reached basement
    has no depth-to-bedrock map but still has an aquifer thickness map,
    and one that recorded no elevations has both but no bedrock surface.
    ``profile_refusal`` is why the ground profile in section 3 was not
    drawn, listed here with the rest.
    """
    figures_dir = Path(inputs.figures_dir)
    placed = [i for i in interpretations if i.site_easting is not None
              and i.site_northing is not None]
    if len(placed) < 2 and not inputs.subsurface_figures:
        return
    zone = site.utm_zone or survey_zone(interpretations) or 28
    slug = _site_slug(site)
    made: list[tuple[Path, str]] = []
    # what was not drawn, and why: a figure missing without a word reads as
    # "the survey did not attempt this", and the reason is usually a GPS
    # position nobody recorded, which a reviewer can ask for
    not_drawn: list[str] = []
    if profile_refusal:
        not_drawn.append(f"ground profile: {profile_refusal}")
    any_surface = False
    for fn, key, name, what in _SUBSURFACE_MAPS:
        try:
            # every interpretation, positioned or not, so a refusal can say
            # which soundings lack a position and which lack the value
            path = fn(interpretations, zone, path=figures_dir / f"{key}_{slug}.png")
        except (ValueError, RuntimeError) as exc:
            # the reason is per-figure and the others still stand; a Qhull
            # error on a straight traverse is a RuntimeError, and it used to
            # walk past this line and take the whole report down
            not_drawn.append(f"{name}: {exc}")
            continue
        caption, surface = _subsurface_caption(
            what, _subsurface_points(key, interpretations, zone))
        any_surface = any_surface or surface
        made.append((path, caption))
    try:
        made.append((
            geoelectric_section_along_traverse(
                interpretations, path=figures_dir / f"geoelectric_section_{slug}.png"),
            ("Interpreted geoelectric section along the traverse, with the "
             "soundings at their surveyed spacing rather than evenly spaced "
             "and drawn to the depth of investigation. Colour is layer "
             "resistivity; the dashed lines correlate boundaries between "
             "neighbouring soundings within reach of each other and are an "
             "interpretation, not a measured contact."),
        ))
    except (ValueError, KeyError, RuntimeError) as exc:
        not_drawn.append(f"geoelectric section: {exc}")
    try:
        # the soundings are the list the interpretations were made from, so
        # each station takes its own readings by position
        profile = traverse_profile(interpretations)
        pseudo = apparent_resistivity_pseudosection(
            soundings, profile, path=figures_dir / f"pseudosection_{slug}.png")
        made.append((pseudo, _pseudosection_caption(spacing_name(soundings), profile)))
    except (ValueError, KeyError, RuntimeError) as exc:
        not_drawn.append(f"apparent-resistivity pseudo-section: {exc}")
    made.extend(inputs.subsurface_figures)
    if not made and not not_drawn:
        return
    rb.heading("Subsurface maps from the survey", 2)
    if made:
        # the promise about interpolated surfaces is made only where one was
        # drawn: over three collinear soundings no map in the section has one
        rb.paragraph(
            "The maps in this section are drawn from the soundings themselves "
            "rather than from a national dataset, so they carry the survey's own "
            "resolution."
            + (" Each interpolated surface is blanked outside the ground the "
               "soundings enclose: a contour beyond the last peg is the "
               "interpolator continuing a trend, and a borehole gets sited on it."
               if any_surface else ""),
            align="justify",
        )
    for path, caption in made:
        rb.figure(path, caption)
    if not_drawn:
        rb.paragraph(
            ("Not drawn from this survey, and why:" if made else
             "No subsurface map or section could be drawn from this survey:"),
            bold=True,
        )
        rb.bullets([_sentence(reason) for reason in not_drawn])


GROUND_PROFILE_CAPTION = (
    "Ground surface along the survey traverse, from the elevation recorded at "
    "each sounding."
)


def _ground_profile_figure(inputs: GeophysicalReportInputs, community: str):
    """The ground profile the recorded levels support.

    Returns ``(path, caption, refusal)``. Two positioned soundings with
    elevations are a profile; fewer is silence, as it always was, because
    a survey that levelled nothing has no profile to be missing. A
    traverse that cannot be placed, or levels too far apart to join, is a
    refusal with its reason, for the report's list of what was not drawn:
    the profile follows the rules the section follows, where it used to
    draw the slope across 20.7 km that the section refused.
    """
    levelled = [
        i for i in inputs.interpretations
        if getattr(i, "site_easting", None) is not None
        and getattr(i, "site_northing", None) is not None
        and getattr(i, "site_elevation_m", None) is not None
    ]
    if len(levelled) < 2:
        return None, GROUND_PROFILE_CAPTION, ""
    path = Path(inputs.figures_dir) / f"ground_profile_{safe_slug(community, 'site')}.png"
    try:
        state = ground_profile_state(inputs.interpretations)
        ground_profile_along_traverse(inputs.interpretations, path=path)
    except (ValueError, RuntimeError) as exc:
        return None, GROUND_PROFILE_CAPTION, str(exc)
    return path, _ground_profile_caption(state), ""


def _ground_profile_caption(state: dict) -> str:
    """The profile's caption, saying what the figure leaves out and why."""
    caption = GROUND_PROFILE_CAPTION
    if state["missing"]:
        caption += (
            f" {state['missing']} of {len(state['labels'])} stations recorded no "
            "elevation and are not drawn."
        )
    if state["open_gaps"]:
        caption += (
            f" The line is not drawn across gaps wider than "
            f"{state['max_gap_m']:,.0f} m, where nothing was levelled between "
            "the stations."
        )
    return caption


def _sentence(text: str) -> str:
    text = text.strip()
    return text[0].upper() + text[1:] + ("" if text.endswith(".") else ".")


def _executive_summary(
    soundings: list[VESSounding],
    interpretations: list[SiteInterpretation],
    community: str,
    district: str,
    tied: list[SiteInterpretation] | tuple = (),
) -> tuple[list[str], list[str]]:
    """Compose the geophysical executive summary from the ranked results.

    With ``tied`` (the two points the ranking cannot separate) the summary
    offers both, as the suitability section does, instead of recommending
    the one that happens to be listed first.
    """
    # The preferred point is the one ranked first; build_geophysical_report
    # ranks before anything reads it, and the fallback keeps an unranked
    # list deterministic.
    best = _preferred(interpretations)
    where = f"point {best.sounding_id}" if tied else "the preferred point"
    n = len(soundings)
    zones = best.water_zones
    if zones:
        zone_txt = "; ".join(
            zone_text(t, b, open_ended=(best.basement_not_resolved and (t, b) == zones[-1]))
            for t, b in zones
        )
        zone_sentence = (
            f"The most promising water bearing zone at {where} "
            f"lies from {zone_txt}."
        )
        if best.basement_not_resolved:
            zone_sentence += (
                " Its base is not resolved: the sounding sees to about "
                f"{best.investigation_depth_m:.0f} m and the conductive ground "
                "continues below that, so the thickness is a minimum."
            )
    else:
        zone_txt = ""
        zone_sentence = (
            f"No strongly water bearing zone was resolved at {where} "
            "within the investigated depth, so the result should be "
            "confirmed by test drilling."
        )
    if tied:
        first, second = tied
        choice = (
            f". Points {first.sounding_id} and {second.sounding_id} cannot be "
            "told apart on geophysical grounds, so either is a drilling "
            "location, the choice between them to be made on access, sanitary "
            "distances and the community's preference; the drilling depth is "
            f"{drilling_depth_text(first)} at {first.sounding_id} and "
            f"{drilling_depth_text(second)} at {second.sounding_id}. "
        )
        key = [
            (f"Drilling points the survey cannot separate: {first.sounding_id} "
             f"and {second.sounding_id}."),
            (f"Recommended drilling depth: {drilling_depth_text(first)} at "
             f"{first.sounding_id}; {drilling_depth_text(second)} at "
             f"{second.sounding_id}."),
        ]
    else:
        choice = (
            f". Point {best.sounding_id} is recommended as the preferred "
            f"drilling location, to a depth of {drilling_depth_text(best)}. "
        )
        key = [
            f"Preferred drilling point: {best.sounding_id}.",
            f"Recommended drilling depth: {drilling_depth_text(best)}.",
        ]
    para = (
        f"A geophysical siting survey using {n} vertical electrical sounding "
        f"{'point' if n == 1 else 'points'} was carried out at {community}"
        + (f", {district}" if district else "")
        + choice
        + zone_sentence
    )
    if zone_txt:
        key.append(
            f"Target water {plural_noun(len(zones), 'zone')}"
            + (f" at {best.sounding_id}" if tied else "")
            + f": {zone_txt}."
        )
    if best.fit_error_percent is not None:
        fit = f"Model fit at {where}: ERR {best.fit_error_percent:.1f} percent"
        if best.fit_quality == "unreliable":
            fit += (" (well above target; the layer depths are indicative only "
                    f"and the ranking confidence is {best.confidence:.2f})")
        elif best.fit_quality == "poor":
            fit += (" (above target; the layer depths are approximate and the "
                    f"ranking confidence is {best.confidence:.2f})")
        key.append(fit + ".")
    key.append(
        "Yield and water quality can only be confirmed by test drilling and "
        "test pumping."
    )
    return [para], key


def _preferred(interpretations: list[SiteInterpretation]) -> SiteInterpretation:
    """The point ranked first, or a deterministic stand-in when unranked."""
    return min(interpretations, key=lambda i: (i.rank or 99, -i.score, i.sounding_id))


def _conclusions(
    interpretations: list[SiteInterpretation], district: str, community: str,
    tied: list[SiteInterpretation] | tuple = (),
) -> list[str]:
    items = []
    if district and region_of(district) == "Western Area":
        items.append(
            "The project area is part of the Freetown Basic Complex "
            "lithological formation."
        )
    items.append(
        "Groundwater potential (quality and quantity) could be favourable at "
        "depth within weathered zones and fractured bedrock."
    )
    for interp in interpretations:
        if interp.water_zones:
            zones = " and ".join(
                zone_text(t, b, open_ended=(interp.basement_not_resolved
                                            and (t, b) == interp.water_zones[-1]))
                for t, b in interp.water_zones
            )
            items.append(
                f"The potential water zones at point {interp.sounding_id} are "
                f"found from {zones}."
                + (" The base of the deepest zone lies below the depth the "
                   "sounding resolves." if interp.basement_not_resolved else "")
            )
        else:
            items.append(
                f"No clearly water bearing zone was resolved at point "
                f"{interp.sounding_id} within the investigated depth."
            )
    best = _preferred(interpretations)
    if tied:
        items.append(
            f"Points {tied[0].sounding_id} and {tied[1].sounding_id} cannot be "
            "separated by the results and data analysis; either may be drilled, "
            "and the choice between them rests on access, sanitary distances "
            "and the community's preference."
        )
    else:
        items.append(
            f"Point {best.sounding_id} is selected as the preferred point for "
            "drilling according to the results and data analysis."
        )
    items.append(
        "It is premature to estimate quantities, which can only be "
        "determined during test drilling and test pumping."
    )
    items.append(
        "The borehole locations were selected within both national and "
        "international borehole siting guidelines."
    )
    return items


def _recommendations(
    interpretations: list[SiteInterpretation],
    tied: list[SiteInterpretation] | tuple = (),
) -> list[str]:
    best = _preferred(interpretations)
    if tied:
        chosen = list(tied)
        items = [
            (f"Drilling should be carried out at point {tied[0].sounding_id} or "
             f"point {tied[1].sounding_id}, which the survey cannot separate, to "
             "confirm the existence of groundwater.")
        ]
    else:
        chosen = [best]
        items = [
            (f"Drilling should be carried out at the selected point "
            f"{best.sounding_id} to confirm the existence of groundwater.")
        ]
    others = [i for i in interpretations if not any(i is c for c in chosen)]
    if others:
        items.append(
            ("Point " if len(others) == 1 else "Points ")
            + ", ".join(i.sounding_id for i in others)
            + (" is an optional drilling point." if len(others) == 1
               else " are optional drilling points.")
        )
    depths = "; ".join(
        f"{drilling_depth_text(i)} at point {i.sounding_id}"
        for i in sorted(interpretations, key=lambda i: (i.rank or 99, i.sounding_id))
    )
    # A depth is a minimum for one of two reasons, and the sentence names the
    # ones that apply: the water-bearing zone runs on below the depth of
    # investigation, or the zone ends inside it but the margin drilled below
    # it does not.
    open_ended = any(i.basement_not_resolved for i in interpretations)
    capped = any(i.drilling_depth_capped and not i.basement_not_resolved
                 for i in interpretations)
    reason = (
        "the water-bearing zone, or the margin drilled below it, runs past what "
        "the survey resolves" if open_ended and capped else
        "the water-bearing zone continues below what the survey resolves"
        if open_ended else
        "the margin drilled below the deepest water zone runs past what the "
        "survey resolves" if capped else ""
    )
    items.append(
        f"The drilling depth should be {depths}, to cut across the probable "
        "water zones."
        + (f" Where the depth is a minimum, {reason}: drill on while the "
           "formation is water bearing, guided by the strikes and the "
           "penetration rate, and stop in fresh rock."
           if reason else "")
    )
    items.append(
        "The borehole must be constructed using correct and standard "
        "materials such as standard uPVC screens and plain casings and well "
        "sorted gravel pack."
    )
    items.append(
        "Both physico-chemical and bacteriological tests should be carried "
        "out on water samples from the completed well."
    )
    return items
