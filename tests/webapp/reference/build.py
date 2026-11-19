"""``build()``: every entry of ``reference.json``, filled in the order the file
holds them.

``make_reference.py`` writes what ``build()`` returns with ``json.dumps`` and
no ``sort_keys``, so the order of the statements here is the order of the
file, and several entries are computed from ones filled before them (the
odds and the cost range from the range of models, the value of a measurement
and the decision numbers from both). Nothing here may be
reordered without regenerating the file. What reads the sample workbooks,
and the locals several entries share, stays in ``build()`` itself; a section
that needs none of them is one call into its module.
"""

from __future__ import annotations

from groundwater.costing import CostingInputs, inputs_from_design
from groundwater.design import design_borehole
from groundwater.geo import geodesic_distance_m, geographic_to_utm
from groundwater.hydraulics import analyse_pumping_test, test_type_text
from groundwater.ingestion import (
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from groundwater.models import DrillingLog, SiteMetadata
from groundwater.portfolio import classify_status
from groundwater.quality import assess_sample
from groundwater.siting import assess_siting
from groundwater.supervision.checklists import (
    legacy_item_ids,
    load_checklists,
    migrate_response_keys,
)
from groundwater.units import convert as unit_convert
from groundwater.ves.interpret import drilling_preference_table, interpret_model
from groundwater.ves.inversion import invert_sounding

from .allocation import allocation_reference
from .assets import (
    fault_reports_reference,
    fill_qr,
    fill_registry,
    rounds_reference,
    survival_reference,
)
from .bundle import bundle_reference
from .calibration import (
    calibration_in_force_reference,
    calibration_pooling_reference,
    calibration_reference,
    calibration_sets_reference,
)
from .common import clean, DATA, flags, site_dict
from .costing import (
    cost_range_reference,
    costing_siting_reference,
    measurement_reference,
)
from .decisions import decisions_reference
from .depth_spine import fill_spine
from .design import (
    design_case,
    DESIGN_CASES,
    drilling_case,
    DRILLING_CASES,
    GATE_FEET_LOG,
    GATE_SET_ASIDE_LOG,
    rising_main_reference,
)
from .desk_study import desk_study_reference
from .elevation import elevation_window_reference
from .extraction import extraction_reference, pdf_sheet_reference
from .field_kit import airlift_reference, field_kit_reference
from .geotiff import geotiff_reference, inflate_reference
from .ledger import ledger_reference
from .lineaments import lineament_reference
from .odds import _odds_range, odds_reference
from .photos import photo_evidence_reference
from .planning import fill_planning
from .portfolio import fill_portfolio
from .procurement import fill_procurement
from .pumping import (
    fill_step_analysis,
    pumping_cases,
    pumping_spread_reference,
    time_cells_reference,
)
from .quality import fill_quality, quality_units_reference
from .regional import regional_reference
from .sanitary import sanitary_reference
from .scorecards import scorecards_reference
from .survey_figures import survey_figures_reference
from .survey_plan import survey_plan_reference
from .terrain import terrain_reference
from .too_large import too_large_reference
from .verification import verification_reference
from .ves import (
    ves_bessel_reference,
    ves_fit_reference,
    ves_forward_reference,
    ves_range_reference,
    ves_text,
)


def build() -> dict:
    out: dict = {}

    soundings = read_ves_workbook(DATA / "rokel" / "rokel_ves.xlsx")
    out["ves"] = [
        {
            "id": s.sounding_id, "array": s.array_type,
            "ab2": clean(s.ab2), "mn": clean(s.mn), "rho": clean(s.rho_app),
            "site": site_dict(s.site), "flags": flags(s.flags),
        }
        for s in soundings
    ]

    log = read_drilling_workbook(DATA / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    out["drilling"] = {
        "ref": log.borehole_ref, "total": clean(log.total_depth_m),
        "strikes": clean(log.water_strikes_m),
        "intervals": [[clean(i.top_m), clean(i.bottom_m), i.description]
                      for i in log.intervals],
        "site": site_dict(log.site), "flags": flags(log.flags),
    }

    sample = read_quality_workbook(DATA / "dr_timbo" / "dr_timbo_water_quality.xlsx")
    out["quality"] = {
        "id": sample.sample_id, "ref": sample.borehole_ref,
        "lab": sample.laboratory,
        "results": [[r.parameter, clean(r.value), r.unit, r.below_detection,
                     clean(r.detection_limit)] for r in sample.results],
        "flags": flags(sample.flags),
    }

    test = read_pumping_workbook(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    out["pumping"] = {
        "type": test.test_type, "swl": clean(test.static_water_level_m),
        "depth": clean(test.borehole_depth_m), "pump": clean(test.pump_setting_m),
        "steps": [{"n": s.step_number, "q": clean(s.discharge_m3_per_h),
                   "t": clean(s.time_min), "wl": clean(s.water_level_m),
                   "label": s.label} for s in test.steps],
        "rec_t": clean(test.recovery_time_min),
        "rec_wl": clean(test.recovery_level_m),
        "duration": clean(test.pumping_duration_min),
        "flags": flags(test.flags),
    }

    step_test = read_pumping_workbook(DATA / "kuntolo" / "kuntolo_step_test.xlsx")
    out["step"] = {
        "type": step_test.test_type, "swl": clean(step_test.static_water_level_m),
        "nsteps": len(step_test.steps),
        "steps": [{"n": s.step_number, "q": clean(s.discharge_m3_per_h),
                   "npoints": len(s.time_min), "tmax": clean(float(s.time_min.max()))}
                  for s in step_test.steps],
        "flags": flags(step_test.flags),
    }

    analysis = analyse_pumping_test(test)
    rec = analysis.yield_recommendation
    out["analysis"] = {
        "T": clean(analysis.transmissivity_m2_per_day),
        "cj": clean(analysis.cooper_jacob.transmissivity_m2_per_day)
              if analysis.cooper_jacob else None,
        "rec": clean(analysis.recovery.transmissivity_m2_per_day)
               if analysis.recovery else None,
        "theis": clean(analysis.theis.transmissivity_m2_per_day)
                 if analysis.theis else None,
        "safe": clean(rec.safe_yield_m3_per_h),
        "low": clean(rec.safe_yield_low_m3_per_h),
        "high": clean(rec.safe_yield_high_m3_per_h),
        "pump_depth": clean(rec.pump_installation_depth_m),
        "range_text": rec.yield_range_text,
        "flags": [[f.level, f.code] for f in analysis.flags],
        # workstream 3: what the yield is worth, and why each method was or
        # was not adopted
        "source": analysis.transmissivity_source,
        "qualifies": analysis.adopted_fit()[2],
        "disqualified": sorted(analysis.disqualified),
        "casing_storage_min": clean(analysis.casing_storage_min),
        "u_check": analysis.cooper_jacob.u_check if analysis.cooper_jacob else None,
        "rec_intercept": clean(analysis.recovery.intercept_m) if analysis.recovery else None,
        "rec_intercept_fraction": clean(analysis.recovery.intercept_fraction)
                                  if analysis.recovery else None,
        "rec_pumping_time": clean(analysis.recovery.pumping_time_min)
                            if analysis.recovery else None,
        "theis_S": clean(analysis.theis.storativity) if analysis.theis else None,
        "confidence": rec.confidence,
        "confidence_reasons": list(rec.confidence_reasons),
        "confidence_text": rec.confidence_text,
        "specific_capacity": clean(rec.specific_capacity_m3hr_per_m),
        "specific_capacity_basis": rec.specific_capacity_basis,
        "pump_depth_basis": rec.pump_depth_basis,
        "deepest_level": clean(rec.deepest_pumping_level_m),
        "basis": rec.basis,
        "type_text": test_type_text(test.test_type),
    }

    fill_step_analysis(out)

    assessed = assess_sample(sample)
    out["assessed"] = {
        "verdict": assessed.verdict,
        "health": [r.parameter for r in assessed.health_exceedances],
        "wqi": clean(assessed.wqi.value) if assessed.wqi else None,
        "corros": assessed.corrosivity.classification,
        # The classification alone let the corrosivity sentences drift: the
        # browser went on saying the pH was "within the acceptability range"
        # for a sample flagged at 5.9 while the class it was checked on still
        # read "Strongly corrosive" on both sides.
        "corros_verdict": assessed.corrosivity.verdict,
        "corros_materials": assessed.corrosivity.materials_note,
        "national": [r.parameter for r in assessed.national_exceedances],
        "ionic": clean(assessed.ionic.error_percent) if assessed.ionic else None,
    }

    design = design_borehole(log=log, static_water_level_m=test.static_water_level_m,
                             pump_intake_m=52.0)
    from groundwater.design import lithology_bands
    out["design"] = {
        "depth": clean(design.total_depth_m),
        "screens": [[clean(s.top_m), clean(s.bottom_m)] for s in design.screens],
        "gravel": clean(list(design.gravel_pack)),
        "screen_len": clean(design.total_screen_length_m),
        # workstream 4: the log's own words decide the design
        "backfill": clean(list(design.backfill)),
        "annular_fill": design.annular_fill,
        "annulus_mm": clean(design.annulus_mm),
        "bore_in": clean(design.borehole_diameter_in),
        "as_built": design.as_built,
        "construction_note": design.construction_note,
        "pump_intake": clean(design.pump_intake_m),
        "basis": list(design.design_basis),
        "flags": [[f.level, f.code] for f in design.flags],
        "summary_rows": [list(r) for r in design.summary_rows()],
        "gravel_interval": clean(inputs_from_design(design).gravel_interval_m),
        "grout": clean(log.grouting_depth_m),
        "installed_screens": [list(map(clean, s)) for s in log.installed_screens_m],
        "bands": [[clean(t), clean(b), c.label] for t, b, c in lithology_bands(log.intervals)],
        # the seal the drawing shows is the seal the BoQ prices
        "seal": clean(list(design.sanitary_seal)),
        "cement_bags": clean(inputs_from_design(design).cement_bags),
    }

    # A manual estimate with its own seal rule: cement follows the seal given.
    _manual, _manual_notes = CostingInputs(
        total_depth_m=60.0, sanitary_seal_m=30.0).resolved()
    out["costing_manual"] = {
        "cement_bags": clean(_manual.cement_bags),
        "seal_note": next(n for n in _manual_notes if "grout seal" in n),
    }

    # The cost summary table a contract is signed on. The browser inlined its
    # own eight rows here with no VAT branch at all, so a VAT-set estimate
    # printed a contract price, then a contingency computed on a VAT-inclusive
    # budget, and no line saying where the difference went.
    from groundwater.costing import estimate_borehole_cost  # noqa: E402

    _cost_inputs, _ = CostingInputs(total_depth_m=60.0).resolved()
    # through clean(): summary_rows returns tuples, and --check compares the
    # fresh value against the parsed file, where a tuple has become a list
    out["cost_summary"] = clean({
        "no_vat": estimate_borehole_cost(_cost_inputs).summary_rows(),
        "vat": estimate_borehole_cost(
            _cost_inputs, vat_percent=15.0).summary_rows(),
    })

    # A real Streamlit project file, produced by the real serializer rather
    # than hand-written. Both apps claim they can read each other's projects,
    # and the browser could not read ANY of them: serialize_project always
    # writes rates_overrides, committee, sources, summary and asset, PyYAML
    # renders an empty one as {} or [] on one line, and the browser's parser
    # refused flow syntax outright. The hand-written fixture that was supposed
    # to guard this carried none of those five keys.
    from groundwater.project_io import deserialize_project, serialize_project  # noqa: E402

    _saved = serialize_project(
        {
            "meta_community": "Kuntoloh",
            "meta_district": "Western Area Rural",
            "project_summary": {
                "community": "Kuntoloh", "district": "Western Area Rural",
                "status": "Completed - dry", "total_depth_m": 52.0,
                "cost_per_meter_usd": 151.0,
            },
        },
        "0.2.0",
    ).decode("utf-8")
    out["streamlit_project_file"] = {
        "yaml": _saved,
        # what Python itself reads back out of those exact bytes
        "summary": deserialize_project(_saved.encode("utf-8"))["summary"],
    }

    # The supervision checklists: both engines must read the same ids out of
    # the CSV, and carry a positional answer onto the same stable id.
    _items = load_checklists()
    out["checklists"] = {
        "ids": [[i.item_id, i.legacy_id, i.checklist, i.section, i.critical,
                 i.photo_required]
                for i in _items],
        "legacy": legacy_item_ids(_items),
        "migrated": migrate_response_keys(
            {"chk_procurement-01": "yes", "rmk_drilling-03": "note",
             "chk_" + _items[10].item_id: "no", "chk_nowhere-99": "na"},
            _items),
    }

    inverted = invert_sounding(soundings[0])
    out["inversion"] = {
        "rho": clean(inverted.model.resistivities),
        "h": clean(inverted.model.thicknesses),
        "err": clean(inverted.fit_error_percent),
    }

    fill_spine(out, log, analysis, assessed)

    # The drill-target scorecard, over the real Rokel soundings.
    rokel_inversions = [invert_sounding(s) for s in soundings]
    rokel_interps = [
        interpret_model(s, inv.model)
        for s, inv in zip(soundings, rokel_inversions, strict=True)
    ]
    out["siting"] = [
        {
            "id": r.sounding_id, "rank": r.rank,
            "suitability": clean(r.suitability), "grade": r.grade,
            "components": {
                "aquifer_thickness": clean(r.components.aquifer_thickness),
                "resistivity_fit": clean(r.components.resistivity_fit),
                "overburden": clean(r.components.overburden),
                "basal_fracture": clean(r.components.basal_fracture),
            },
            "rationale": r.rationale,
        }
        for r in assess_siting(rokel_interps)
    ]
    # The interpretation itself, and the preference table a report prints
    # from it: the zones, the depth the survey resolves, the flags and the
    # narrative are the sentences a siting decision is argued from, and
    # they used to be held to nothing.
    out["interpretations"] = [
        {
            "id": i.sounding_id,
            "water_zones": [[clean(t), clean(b)] for t, b in i.water_zones],
            "max_drilling_depth_m": clean(i.max_drilling_depth_m),
            "investigation_depth_m": clean(i.investigation_depth_m),
            "max_spacing_m": clean(i.max_spacing_m),
            "basement_not_resolved": i.basement_not_resolved,
            "confidence": clean(i.confidence),
            "fit_quality": i.fit_quality,
            "flags": [[f.level, f.code, f.message] for f in i.flags],
            "narrative": i.narrative,
        }
        for i in rokel_interps
    ]
    out["preference"] = drilling_preference_table(rokel_interps)
    out["ves_text"] = ves_text(rokel_inversions, rokel_interps)
    out["ves_range"] = ves_range_reference(soundings, rokel_inversions)
    out["odds"] = odds_reference(
        rokel_interps, [sd.site for sd in soundings],
        [_odds_range(None if r["basement_m"] is None else
                     (r["basement_m"]["p10"], r["basement_m"]["p50"], r["basement_m"]["p90"]),
                     r["basement_unresolved"]) for r in out["ves_range"]["short"]])
    out["cost_range"] = cost_range_reference(out["ves_range"]["short"])
    out["measurement"] = measurement_reference(out["odds"], out["cost_range"])
    out["costing_siting"] = costing_siting_reference()
    out["decisions"] = decisions_reference(out["odds"], out["cost_range"])
    out["ledger"] = ledger_reference(rokel_interps, [sd.site for sd in soundings],
                                     out["ves_range"]["short"],
                                     [r["odds"] for r in out["odds"]["rokel"]])
    out["calibration"] = calibration_reference()
    out["calibration_sets"] = calibration_sets_reference()
    out["calibration_in_force"] = calibration_in_force_reference()
    out["calibration_pooling"] = calibration_pooling_reference()
    out["scorecards"] = scorecards_reference()
    out["allocation"] = allocation_reference()
    out["sanitary"] = sanitary_reference()
    out["rising_main"] = rising_main_reference()
    out["rounds"] = rounds_reference()
    out["survival"] = survival_reference()
    out["fault_reports"] = fault_reports_reference()
    out["verification"] = verification_reference()
    out["bundle"] = bundle_reference()

    # A siting survey with no borehole yet: the design comes from the
    # interpretation alone. The degenerate half-space used to make this an
    # 80 m hole with 48 m of screen at both Rokel points, from soundings that
    # resolve 40 m, and the browser built it from the same zone.
    ves_only = design_borehole(interpretation=rokel_interps[0])
    out["ves_only_design"] = {
        "depth": clean(ves_only.total_depth_m),
        "screens": [[clean(x.top_m), clean(x.bottom_m)] for x in ves_only.screens],
        "screen_len": clean(ves_only.total_screen_length_m),
        "basis": list(ves_only.design_basis),
    }

    # Geographic -> UTM, the direction a pasted phone position takes.
    out["geo"] = [
        {"lat": lat, "lon": lon,
         "easting": clean(geographic_to_utm(lat, lon).easting),
         "northing": clean(geographic_to_utm(lat, lon).northing),
         "zone": geographic_to_utm(lat, lon).zone}
        for lat, lon in ((8.4657, -13.2317), (8.7043, -11.4084), (7.9560, -11.7400))
    ]

    # Ground distance. Subtracting raw eastings across the 28N/29N boundary
    # put two sites 2.2 km apart 659 km apart, so both engines have to agree
    # on the same ellipsoidal answer, not merely on a close one.
    out["distance"] = [
        {"a": [8.50, -12.01], "b": [8.50, -11.99],
         "metres": clean(geodesic_distance_m(8.50, -12.01, 8.50, -11.99))},
        {"a": [8.4657, -13.2317], "b": [7.9647, -11.7383],
         "metres": clean(geodesic_distance_m(8.4657, -13.2317, 7.9647, -11.7383))},
        {"a": [8.0, -12.0], "b": [8.0, -12.0],
         "metres": clean(geodesic_distance_m(8.0, -12.0, 8.0, -12.0))},
    ]

    # Free-text borehole statuses, including the ones substring matching read
    # as successes ("incomplete" contains "complete").
    out["statuses"] = {
        raw: classify_status({"status": raw})
        for raw in ("Successful", "Completed - dry", "incomplete",
                    "not completed", "unproductive", "non-productive",
                    "low productivity", "in progress", "Sited", "visited",
                    "qwerty")
    }

    # Unit conversion, the layer both engines put every value through before
    # it is compared against a limit.
    out["units"] = [
        {"value": v, "from": f, "to": t, "result": clean(unit_convert(v, f, t))}
        for v, f, t in (
            (5.0, "ug/L", "mg/L"), (5.0, "ppb", "mg/L"), (0.5, "g/L", "mg/L"),
            (0.185, "mS/cm", "uS/cm"), (2.0, "CFU/mL", "CFU/100 mL"),
            (2.0, "L/s", "m3/h"), (120.0, "L/min", "m3/h"), (2.0, "h", "min"),
            (5.0, "gpm", "m3/h"), (5.0, "squiggles", "mg/L"),
            (5.0, "mg/L", "NTU"),
        )
    ]

    fill_quality(out)

    # The certification gate, over a project missing one thing at a time.
    from groundwater.ingestion.drilling import drilling_from_grid as _drilling_from_grid
    from groundwater.readiness import assess_readiness

    _log = read_drilling_workbook(DATA / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    _analysis = analyse_pumping_test(
        read_pumping_workbook(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx"))
    _assessment = assess_sample(
        read_quality_workbook(DATA / "dr_timbo" / "dr_timbo_water_quality.xlsx"))
    _design = design_borehole(
        log=_log, static_water_level_m=_analysis.test.static_water_level_m)
    _located = SiteMetadata(community="Dr. Timbo's", district="Western Area Rural",
                            easting=778000.0, northing=946000.0, utm_zone=28)
    _full = {"site": _located, "drilling_log": _log, "pump_analysis": _analysis,
             "wq_assessment": _assessment, "borehole_design": _design}
    _gate_cases = {
        "full": (_full, {}),
        "empty": ({}, {}),
        "no_site": (dict(_full, site=SiteMetadata(community="Nowhere")), {}),
        # a northing 500 km short: a position, but not one in the country
        "off_country": (dict(_full, site=SiteMetadata(
            community="Dr. Timbo's", district="Western Area Rural",
            easting=778000.0, northing=446000.0, utm_zone=28)), {}),
        "no_quality": (dict(_full, wq_assessment=None), {}),
        "overridden": (dict(_full, wq_assessment=None), {
            "water_quality_panel": {"reason": "lab result awaited", "by": "M. K."},
            "water_quality_evaluable": {"reason": "lab result awaited", "by": "M. K."},
        }),
        # The demonstration paths, which the two engines have to read the
        # same way: a bundled file whose readings were invented, and a
        # bundled file faithfully transcribed from a real survey. Both hold
        # the report back; only the first says nothing was measured.
        "synthetic_source": (dict(_full, sources={
            "wq": {"sample": "dr_timbo/dr_timbo_water_quality.xlsx"},
        }), {}),
        "bundled_source": (dict(_full, sources={
            "ves": {"name": "rokel_ves.xlsx", "b64": "x",
                    "sample": "rokel/rokel_ves.xlsx"},
        }), {}),
        # A bundled file whose measurements are real but whose blank columns
        # were filled in illustratively. Not blocking - it is a stated
        # assumption, which is the other half of the gate's output.
        "reconstructed_source": (dict(_full, sources={
            "log": {"sample": "dr_timbo/dr_timbo_drilling_log.xlsx"},
        }), {}),
        # The same synthetic workbook opened off disk by a script, with no
        # picker marker on it. Invented readings are invented whoever opened
        # the file, so this still fails.
        "synthetic_by_name": (dict(_full, sources={
            "wq": {"name": "dr_timbo_water_quality.xlsx"},
        }), {}),
        # But a faithfully transcribed example opened the same way is not a
        # demonstration: a script publishing the Rokel survey under the Rokel
        # name is reporting exactly what it says it is.
        "transcribed_by_name": (dict(_full, sources={
            "ves": {"name": "rokel_ves.xlsx"},
        }), {}),
        # An upload of the analyst's own file is not a demonstration, however
        # it is named - the check must not fire on everything with a source.
        "own_upload": (dict(_full, sources={
            "log": {"name": "kambia_drilling_log.xlsx", "b64": "x"},
        }), {}),
        # The one case an override is for: publishing the worked example
        # itself, with the reason on the cover.
        "demonstration_override": (dict(_full, sources={
            "wq": {"sample": "dr_timbo/dr_timbo_water_quality.xlsx"},
        }), {"field_data": {"reason": "published as a worked example",
                            "by": "M. K."}}),
        # A log in feet, converted: met, with the conversion stated beside
        # the gate. A log the reader set part of aside: not complete, and no
        # longer "every reading carried a unit". Degrees in the UTM boxes:
        # no position.
        "feet_log": (dict(_full, drilling_log=_drilling_from_grid(
            GATE_FEET_LOG, "case.xlsx")), {}),
        "log_set_aside": (dict(_full, drilling_log=_drilling_from_grid(
            GATE_SET_ASIDE_LOG, "case.xlsx")), {}),
        "degree_site": (dict(_full, site=SiteMetadata(
            community="Dr. Timbo's", district="Western Area Rural",
            easting=-13.2294, northing=8.4831)), {}),
    }
    out["readiness"] = {}
    for _name, (_state, _over) in _gate_cases.items():
        out["readiness"][_name] = {
            report: {
                "state": assess_readiness(_state, report, _over).state,
                "summary": assess_readiness(_state, report, _over).summary,
                "requirements": [
                    [r.key, r.state, r.detail, r.override_reason, r.override_by]
                    for r in assess_readiness(_state, report, _over).requirements
                ],
                # Stated assumptions travel onto the report beside the gate, so
                # the two engines have to state the same ones. Nothing compared
                # these, and the browser was silently stating none of them.
                "assumptions": assess_readiness(_state, report, _over).assumptions,
            }
            for report in ("completion", "handover", "quality", "pumping")
        }

    # The handover works list. Both engines build it from the same records
    # and it is what an interim payment is argued from, so the two have to
    # word it identically; nothing compared them until now.
    from groundwater.reporting.handover import (
        HandoverReportInputs, default_works,
    )

    def _works(**kw):
        return default_works(HandoverReportInputs(site=_located, **kw))

    out["handover_works"] = {
        "full": _works(log=_log, design=_design, pumping=_analysis,
                       quality=_assessment),
        "sited": _works(log=_log, design=_design, pumping=_analysis,
                        quality=_assessment, sited=True),
        "bare": _works(),
        # a sheet where nobody wrote the depth down: the bullet waits for a
        # figure rather than certifying a borehole drilled to "n/a"
        "no_depth": _works(log=DrillingLog(
            site=_located, drilling_method="Air rotary (DTH hammer)")),
    }

    fill_qr(out)
    fill_registry(out)

    # The seasonal yield model: the month read off the sheet, and the yield
    # at each scenario's water level.
    from groundwater.seasonal import month_of as _month_of
    from groundwater.seasonal import seasonal_yield as _seasonal_yield

    out["seasonal_dates"] = [
        {"text": t, "month": _month_of(t)[0], "note": _month_of(t)[1]}
        for t in ("10/05/2018", "25/04/2018", "04/25/2018", "2018-09-14",
                  "14 Sept 2018", "September 2018", "during the rains",
                  "05/2018", "", "31/13/2018", "2018/09/14")
    ]
    out["seasonal"] = {}
    for _label, _month, _band in (("august", 8, None), ("may", 5, None),
                                  ("september", 9, None), ("unknown", None, None),
                                  ("wide", 8, 4.5), ("zero", 8, 0.0)):
        _result = _seasonal_yield(_analysis, month=_month, annual_range_m=_band)
        out["seasonal"][_label] = clean(_result.as_dict())

    fill_planning(out)
    fill_procurement(out)

    # Rounding and %g, which the two languages get wrong in different ways.
    out["rounding"] = [
        {"value": v, "digits": d, "rounded": clean(round(v, d))}
        for v, d in ((0.15, 1), (14.05, 1), (2.675, 2), (0.5, 0), (1.5, 0),
                     (2.5, 0), (-0.15, 1), (2.34, 2), (2.345, 2), (0.125, 2),
                     (-2.5, 0), (45.05, 1), (150.5, 0))
    ]
    out["formatting"] = [
        {"value": v, "text": f"{v:g}"}
        for v in (1e6, 1e15, 999999.6, 1e5, 1e7, 1234567, 0.0001, 0.00001,
                  2.93, 0.0, 0.005, 1e-7,
                  # subnormals, whose shortest form can lie a decade away
                  # from their six-digit one
                  5e-324, 1e-323, 1e-321, 1e-320, 1e-319, 1e-318, 1.000004e-318, -1e-320, 3e-321)
    ]

    fill_portfolio(out)

    out["pdf_sheet"] = pdf_sheet_reference()
    out["extraction"] = extraction_reference()
    out["pumping_cases"] = pumping_cases()
    out["time_cells"] = time_cells_reference()
    out["quality_units"] = quality_units_reference()
    out["regional"] = regional_reference()
    out["survey_figures"] = survey_figures_reference(rokel_interps)
    out["design_cases"] = [design_case(spec) for spec in DESIGN_CASES]
    out["drilling_cases"] = [drilling_case(grid) for grid in DRILLING_CASES]
    out["gate_logs"] = {"feet": GATE_FEET_LOG, "set_aside": GATE_SET_ASIDE_LOG}
    out["photo_evidence"] = photo_evidence_reference()
    out["too_large"] = too_large_reference()
    out["field_kit"] = field_kit_reference()
    out["airlift"] = airlift_reference()
    out["pumping_spread"] = pumping_spread_reference()
    out["ves_forward"] = ves_forward_reference()
    out["ves_bessel"] = ves_bessel_reference()
    out["ves_fit"] = ves_fit_reference(rokel_inversions)
    out["inflate"] = inflate_reference()
    out["geotiff"] = geotiff_reference()
    out["elevation_window"] = elevation_window_reference()
    out["terrain"] = terrain_reference()
    out["lineaments"] = lineament_reference()
    out["survey_plan"] = survey_plan_reference()
    out["desk_study"] = desk_study_reference()
    return out
