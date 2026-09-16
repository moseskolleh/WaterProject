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

from ..config import Config
from ..geo import infer_zone_for_sierra_leone
from ..mapping import (
    apparent_resistivity_pseudosection,
    aquifer_thickness_map,
    bedrock_elevation_map,
    depth_to_bedrock_map,
    geoelectric_section_along_traverse,
    protective_capacity_map,
    suitability_map,
    traverse_profile,
)
from ..models import DataFlag, VESSounding
from ..siting import assess_siting, suitability_map_points
from ..utils import fmt_num, safe_slug
from ..ves.classify import classify_curve
from ..ves.interpret import SiteInterpretation, drilling_preference_table
from ..ves.inversion import InversionResult
from ..ves.plots import plot_model_pseudosection, plot_sounding_curve
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


def _geology_for(district: str, override: str) -> str:
    if override:
        return override
    if "western" in (district or "").lower():
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
                                              community, district)
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
    rb.paragraph(_geology_for(district, inputs.geology_text), align="justify")
    # the soundings go on the study area map, so a reader can see the survey
    # laid out in the area rather than having to hold two figures together
    survey_overlay = [
        {"lat": s.site.latlon[0], "lon": s.site.latlon[1],
         "label": s.sounding_id, "kind": "VES point"}
        for s in soundings if s.site.latlon is not None
    ]
    context_maps = context_map_figures(site, inputs.figures_dir, config.style,
                                       points=survey_overlay)
    if context_maps:
        if "study_area" in context_maps:
            rb.figure(
                context_maps["study_area"],
                f"Study area at {community}, with the survey points and its "
                "location in Sierra Leone inset. Boundaries from "
                "geoBoundaries (CC BY 4.0).",
            )
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
    recon_date = inputs.reconnaissance_date or site.date
    rb.paragraph(
        "The aim of the reconnaissance survey was to select suitable points "
        "for the geophysical survey. Existing water points, environmental "
        "and other physical conditions were also assessed."
        + (f" The field reconnaissance survey was conducted on {recon_date}." if recon_date else ""),
        align="justify",
    )
    rb.paragraph("Geomorphological survey of the area", bold=True)
    rb.paragraph(
        inputs.reconnaissance_notes
        or (
            "The landscape and other physical features of the area were "
            "examined, including slopes, drainage lines and streams, since "
            "there is normally hydraulic continuity between groundwater and "
            "surface water."
        ),
        align="justify",
    )
    rb.paragraph(
        "Geological and hydrogeological survey to determine the formation "
        "of the area and identify possible features",
        bold=True,
    )
    rb.paragraph(
        "The weathered products overlying the bedrock were assessed as the "
        "principal prospect for groundwater, since groundwater occurs mostly "
        "in weathered and unconsolidated materials compared with "
        "consolidated and crystalline rocks.",
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
    if inputs.ground_profile_path and Path(inputs.ground_profile_path).exists():
        rb.figure(
            inputs.ground_profile_path,
            "Ground surface along the survey traverse, from the elevation "
            "recorded at each sounding.",
        )

    rb.paragraph("Selection of traverse line for the geophysical survey", bold=True)
    rb.paragraph(
        "The traverse line for the resistivity survey was selected on the "
        "basis of geomorphologic and geological/hydrogeological features as "
        "well as the location of the project area. Points for the vertical "
        "electrical soundings were selected considering the available space "
        "and the environmental and other physical conditions, and the "
        "proposed borehole locations were marked with pegs for "
        "identification.",
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

    rb.heading("3.2.1 Resistivity Profiling", 3)
    rb.paragraph(
        inputs.profiling_note
        or (
            "Electrical resistivity profiling is usually carried out along a "
            "selected traverse of 50 m to 100 m length at 10 m intervals to "
            "determine the lateral variation of subsurface resistivities and "
            "delineate anomalous points with groundwater potential. Where "
            "the available land extent does not permit profiling, the "
            "vertical electrical soundings are carried out at the selected "
            "points directly."
        ),
        align="justify",
    )

    rb.heading("3.2.2 Selection of VES Points", 3)
    labels = ", ".join(s.sounding_id for s in soundings)
    rb.paragraph(
        f"{len(soundings)} vertical electrical sounding point(s) were "
        "selected based on the available space and the location of the "
        "project area, considering geological, hydrogeological and "
        f"environmental conditions. The points are labelled {labels} in "
        "this report.",
        align="justify",
    )

    rb.heading("3.2.3 Vertical Electrical Sounding (VES)", 3)
    rb.paragraph(
        "Vertical electrical soundings were carried out with the aim of "
        "determining the formation resistivities and the depth to bedrock, "
        "as well as the possibility of finding water bearing fractures or "
        "aquifers at depth with their corresponding thicknesses. The "
        "Schlumberger electrode configuration and the required procedures "
        "were used for the soundings.",
        align="justify",
    )

    # ---- 4 data analysis ------------------------------------------------------
    rb.heading("4. Data Analysis and Interpretation", 1)
    # one inversion and one interpretation per sounding, built in lockstep by
    # every caller: a short list silently drops a point's whole analysis block
    # while the preference table below still ranks it
    for sounding, inversion, interp in zip(
        soundings, inputs.inversions, inputs.interpretations, strict=True
    ):
        _sounding_block(rb, sounding, inversion, interp, inputs.figures_dir)

    # ---- preference table -----------------------------------------------------
    rows = drilling_preference_table(inputs.interpretations)
    header = list(rows[0].keys()) if rows else []
    rb.table(
        [[row[h] for h in header] for row in rows],
        header=header,
        caption="List of VES points in order of preference for drilling.",
        font_size_pt=8.5,
    )

    # ---- drill-target suitability --------------------------------------------
    _suitability_block(rb, inputs, site)

    # ---- 5 conclusions and recommendations -------------------------------------
    rb.heading("5. Conclusions and Recommendations", 1)
    rb.paragraph("Conclusions:", bold=True)
    conclusions = _conclusions(inputs.interpretations, district, community)
    rb.bullets(conclusions)
    rb.paragraph("Recommendations:", bold=True)
    rb.bullets(_recommendations(inputs.interpretations))

    # ---- 6 limitations and uncertainty -----------------------------------------
    rb.heading("6. Limitations and Uncertainty", 1)
    rb.bullets(_limitations(inputs.inversions))

    # ---- QA annex (optional) -----------------------------------------------------
    if inputs.include_qa_annex and inputs.flags:
        rb.heading("Annex A. Data Verification Notes", 1)
        rb.paragraph(
            "The following checks were raised automatically during data "
            "processing and should be verified against the field notes."
        )
        rb.bullets([str(f) for f in inputs.flags])

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


def _limitations(inversions: list[InversionResult]) -> list[str]:
    """Honest, calibrated limitations for the VES interpretation."""
    items = [
        ("Resistivity models are not unique: different layered models can fit "
        "the same sounding curve almost equally well (the equivalence and "
        "suppression problem), so the interpreted layer depths and "
        "thicknesses carry an uncertainty of the order of plus or minus 20 "
        "percent."),
        ("A low resistivity layer can represent either a saturated, water "
        "bearing zone or a conductive clay; the interpretation is made from "
        "the geological context and must be confirmed by drilling."),
        ("The depth of investigation is limited to roughly the maximum "
        "electrode spacing, so any structure below the deepest reliable depth "
        "is not resolved."),
        ("The survey indicates groundwater potential only. The actual yield and "
        "water quality can be confirmed only by test drilling, test pumping "
        "and laboratory analysis."),
    ]
    errs = [inv.fit_error_percent for inv in inversions if inv.fit_error_percent is not None]
    if errs:
        items.insert(
            0,
            f"The fitted models reproduce the measured apparent resistivities "
            f"to within {max(errs):.1f} percent (ERR); a larger misfit means a "
            "less certain model.",
        )
    return items



def _site_slug(site) -> str:
    """Filename fragment identifying the survey site."""
    return safe_slug(getattr(site, "community", "") or "site", "site")


def _sounding_block(
    rb: ReportBuilder,
    sounding: VESSounding,
    inversion: InversionResult,
    interp: SiteInterpretation,
    figures_dir: Path,
) -> None:
    """One data analysis block per sounding: tables, figures, narrative."""
    site = sounding.site
    sid = sounding.sounding_id
    # site as well as sounding id: two surveys both with a sounding "A"
    # share one figures directory in an app session, and generation is
    # guarded by an existence check, so the second reused the first's curve.
    safe_id = f"{_site_slug(site)}_{safe_slug(sid, 'ves')}"

    # data table with the field sheet header block
    table_no = rb.next_table_number
    rb.paragraph(
        f"Table {table_no} presents the Schlumberger array VES data recorded "
        f"at point {sid}, from which the sounding curve of apparent "
        "resistivity against half the current electrode spacing (AB/2) in "
        f"Figure {rb.next_figure_number} is plotted.",
        align="justify",
    )
    rb.header_block_table(
        [
            ("Client", site.client), ("Community", site.community),
            ("Project", site.project or "Geophysical Survey"), ("Sounding Number", sid),
            ("District", site.district), ("GPS Coordinate East", fmt_num(site.easting, 7)),
            ("Date", site.date), ("GPS Coordinate North", fmt_num(site.northing, 7)),
            ("Field Supervisor", site.supervisor),
            ("Elevation", fmt_num(site.elevation_m) + " m" if site.elevation_m else ""),
        ]
    )
    rows = [
        [i + 1, fmt_num(a), fmt_num(m), fmt_num(r, 4)]
        # the parser appends AB/2, MN and rho per row (blank MN becomes NaN),
        # so a length mismatch means a hand-built sounding, not a short sheet
        for i, (a, m, r) in enumerate(
            zip(sounding.ab2, sounding.mn, sounding.rho_app, strict=True))
    ]
    rb.table(
        rows,
        header=["No.", "AB/2 (m)", "MN (m)", "Apparent Resistivity (ohm-m)"],
        caption=f"Schlumberger array VES data at point {sid}.",
        col_widths_cm=[1.5, 3.0, 3.0, 7.0],
    )

    # curve + model figure
    curve_path = figures_dir / f"ves_curve_{safe_id}.png"
    plot_sounding_curve(
        sounding, inversion.model, inversion.rho_calc, inversion.ab2, path=curve_path
    )
    rb.figure(curve_path, f"Schlumberger array VES curve and model at point {sid}.")

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
            h_cell = ""
        model_rows.append(
            [
                row["N"],
                rho_cell,
                h_cell,
                "0/0" if row["z_m"] == "0/0" else fmt_num(row["z_m"]),
            ]
        )
    err = inversion.fit_error_percent
    rb.table(
        model_rows,
        header=["N", "rho (ohm-m)", "h (m)", "z (m)"],
        caption=(
            f"Layered earth model at point {sid} "
            f"(curve type {classify_curve(inversion.model)}, ERR = {err:.1f}%). "
            "The (x/ factor) is the linearised 1-sigma uncertainty; a factor "
            "near 1 is well resolved and a large factor marks equivalence."
        ),
        col_widths_cm=[1.2, 4.6, 3.4, 2.8],
    )

    # pseudo-section figure
    pseudo_path = figures_dir / f"ves_pseudosection_{safe_id}.png"
    plot_model_pseudosection(
        inversion.model,
        path=pseudo_path,
        depth_max=interp.investigation_depth_m * 0.5,
        title=f"Layer section at {sid}",
    )
    rb.figure(
        pseudo_path,
        f"Pseudo-section showing resistivity and layer thicknesses at point {sid}.",
    )

    # interpretation paragraph
    rb.paragraph(interp.narrative, align="justify")
    rb.page_break()


def _suitability_block(rb: ReportBuilder, inputs, site) -> None:
    """Ranked drill-target suitability scorecard, map and recommendation."""
    suit = assess_siting(inputs.interpretations)
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
        [[s.rank, s.sounding_id, f"{s.suitability:.0f}", s.grade] for s in suit],
        header=["Rank", "VES point", "Suitability (0 to 100)", "Grade"],
        caption="Drill-target suitability of the surveyed points.",
        col_widths_cm=[1.8, 4.0, 4.5, 3.7],
    )
    best = suit[0]
    # The rest of the report (executive summary, conclusions, recommendations,
    # drilling-preference table) selects the preferred point by interpretation
    # score. Anchor the recommendation here to that same point so the document
    # never recommends one point in the summary and a different one here; where
    # the suitability scorecard's top differs, surface it as a note rather than
    # a competing recommendation.
    preferred_id = min(
        inputs.interpretations, key=lambda i: (-i.score, i.sounding_id)
    ).sounding_id
    preferred = next((s for s in suit if s.sounding_id == preferred_id), best)
    if preferred.sounding_id == best.sounding_id:
        rb.paragraph(
            f"Point {best.sounding_id} has the highest suitability "
            f"({best.suitability:.0f} out of 100, {best.grade.lower()}) and is the "
            f"recommended drilling target. {best.rationale}",
            align="justify",
        )
    else:
        rb.paragraph(
            f"The recommended drilling target is point {preferred.sounding_id} "
            f"(suitability {preferred.suitability:.0f} out of 100, "
            f"{preferred.grade.lower()}), consistent with the ranked results "
            f"elsewhere in this report. Point {best.sounding_id} scores highest "
            f"on the suitability scorecard ({best.suitability:.0f}); where the two "
            "measures differ, confirm the choice against the site conditions. "
            f"{preferred.rationale}",
            align="justify",
        )
    map_points = suitability_map_points(suit)
    if map_points:
        zone = site.utm_zone or infer_zone_for_sierra_leone(map_points[0].easting)
        smap = Path(inputs.figures_dir) / f"suitability_map_{_site_slug(site)}.png"
        suitability_map(map_points, zone, path=smap)
        rb.figure(
            smap,
            "Drill-target suitability of the surveyed points; greener is more "
            "suitable. The interpolated surface is blanked outside the ground "
            "the survey covered, except where the points lie on one line and "
            "enclose no area - the figure says so on its own face when that "
            "happens.",
        )
    _add_subsurface_figures(rb, inputs.soundings, inputs.interpretations,
                            inputs, site)


def _add_subsurface_figures(rb, soundings, interpretations, inputs, site) -> None:
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
    """
    figures_dir = Path(inputs.figures_dir)
    placed = [i for i in interpretations if i.site_easting is not None
              and i.site_northing is not None]
    if len(placed) < 3 and not inputs.subsurface_figures:
        return
    zone = site.utm_zone or (
        infer_zone_for_sierra_leone(placed[0].site_easting) if placed else 28
    )
    slug = _site_slug(site)
    made: list[tuple[Path, str]] = []
    plan = (
        (depth_to_bedrock_map, "depth_to_bedrock",
         ("Depth to bedrock across the surveyed ground, from the layered "
          "models. The surface is blanked outside the hull of the soundings.")),
        (aquifer_thickness_map, "aquifer_thickness",
         ("Interpreted thickness of the weathered and fractured zone - the "
          "section a borehole is completed in.")),
        (bedrock_elevation_map, "bedrock_elevation",
         ("The bedrock surface as a landform, from the ground elevation "
          "recorded at each sounding less its depth to basement. A low in "
          "this surface is a buried valley, which basement groundwater "
          "drains towards.")),
        (protective_capacity_map, "protective_capacity",
         ("Protective capacity of the cover over the aquifer, from the "
          "longitudinal conductance of the overlying layers. It rates how "
          "well the ground above the aquifer resists downward contamination; "
          "it says nothing about yield.")),
    )
    for fn, name, caption in plan:
        try:
            made.append((fn(placed, zone,
                            path=figures_dir / f"{name}_{slug}.png"), caption))
        except ValueError:
            continue  # the reason is per-figure and the others still stand
    try:
        made.append((
            geoelectric_section_along_traverse(
                placed, path=figures_dir / f"geoelectric_section_{slug}.png"),
            ("Interpreted geoelectric section along the traverse, with the "
             "soundings at their surveyed spacing rather than evenly spaced. "
             "Colour is layer resistivity; the dashed lines correlate "
             "boundaries between neighbouring soundings and are an "
             "interpretation, not a measured contact."),
        ))
    except (ValueError, KeyError):
        pass
    try:
        profile = traverse_profile(placed)
        pseudo = apparent_resistivity_pseudosection(
            soundings, profile, path=figures_dir / f"pseudosection_{slug}.png")
        caption = (
            "Apparent resistivity along the traverse, as measured. Unlike "
            "every other section in this report it involves no inversion: "
            "each point is a reading at the station and electrode spacing "
            "it was taken with. AB/2 is that spacing, not a depth."
        )
        if not profile.is_collinear:
            caption += (
                f" The soundings sit up to {profile.max_offset_m:.0f} m off "
                "the profile line, so this section cuts across the survey "
                "rather than along it."
            )
        made.append((pseudo, caption))
    except (ValueError, KeyError):
        pass
    made.extend(inputs.subsurface_figures)
    if not made:
        return
    rb.heading("Subsurface maps from the survey", 2)
    rb.paragraph(
        "The maps in this section are drawn from the soundings themselves "
        "rather than from a national dataset, so they carry the survey's own "
        "resolution. Each interpolated surface is blanked outside the ground "
        "the soundings enclose: a contour beyond the last peg is the "
        "interpolator continuing a trend, and a borehole gets sited on it.",
        align="justify",
    )
    for path, caption in made:
        rb.figure(path, caption)


def _executive_summary(
    soundings: list[VESSounding],
    interpretations: list[SiteInterpretation],
    community: str,
    district: str,
) -> tuple[list[str], list[str]]:
    """Compose the geophysical executive summary from the ranked results."""
    # Select the preferred point by the same key drilling_preference_table
    # uses (highest score, then sounding id). This does not rely on .rank,
    # which is only assigned later when that table is built, so the summary
    # is deterministic however many times the report is regenerated.
    best = min(interpretations, key=lambda i: (-i.score, i.sounding_id))
    n = len(soundings)
    zones = best.water_zones
    if zones:
        zone_txt = "; ".join(f"{int(t)} m to {int(b)} m" for t, b in zones)
        zone_sentence = (
            "The most promising water bearing zone at the preferred point "
            f"lies between {zone_txt}."
        )
    else:
        zone_txt = ""
        zone_sentence = (
            "No strongly water bearing zone was resolved at the preferred "
            "point within the investigated depth, so the result should be "
            "confirmed by test drilling."
        )
    para = (
        f"A geophysical siting survey using {n} vertical electrical sounding "
        f"point(s) was carried out at {community}"
        + (f", {district}" if district else "")
        + f". Point {best.sounding_id} is recommended as the preferred "
        f"drilling location, to a depth of about {best.max_drilling_depth_m:.0f} m. "
        + zone_sentence
    )
    key = [
        f"Preferred drilling point: {best.sounding_id}.",
        f"Recommended drilling depth: about {best.max_drilling_depth_m:.0f} m.",
    ]
    if zone_txt:
        key.append(f"Target water zone(s): {zone_txt}.")
    key.append(
        "Yield and water quality can only be confirmed by test drilling and "
        "test pumping."
    )
    return [para], key


def _conclusions(
    interpretations: list[SiteInterpretation], district: str, community: str
) -> list[str]:
    items = []
    if district and "western" in district.lower():
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
            zones = " and ".join(f"{int(t)} m to {int(b)} m" for t, b in interp.water_zones)
            items.append(
                f"The potential water zones at point {interp.sounding_id} are "
                f"found between {zones}."
            )
        else:
            items.append(
                f"No clearly water bearing zone was resolved at point "
                f"{interp.sounding_id} within the investigated depth."
            )
    best = min(interpretations, key=lambda i: i.rank or 99)
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


def _recommendations(interpretations: list[SiteInterpretation]) -> list[str]:
    best = min(interpretations, key=lambda i: i.rank or 99)
    others = [i for i in interpretations if i is not best]
    items = [
        (f"Drilling should be carried out at the selected point "
        f"{best.sounding_id} to confirm the existence of groundwater.")
    ]
    if others:
        items.append(
            "Point(s) "
            + ", ".join(i.sounding_id for i in others)
            + " are optional drilling points."
        )
    depths = "; ".join(
        f"{i.max_drilling_depth_m:.0f} m at point {i.sounding_id}"
        for i in sorted(interpretations, key=lambda i: i.rank or 99)
    )
    items.append(
        f"The maximum drilling depth should be {depths}, to cut across the "
        "probable water zones for sustainable productivity and a high yield "
        "of the borehole(s)."
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
