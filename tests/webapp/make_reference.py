"""Produce the reference values the browser app is checked against.

Runs the Python toolkit over the bundled sample workbooks and writes
``tests/webapp/reference.json``. ``tests/webapp/parity.mjs`` then runs the
same inputs through the JavaScript engine in headless Chromium and
compares the two, so the standalone web app cannot silently drift away
from the package it was ported from.

    python tests/webapp/make_reference.py            # regenerate the file
    python tests/webapp/make_reference.py --check    # verify it, don't rewrite
    node tests/webapp/parity.mjs

The committed file is checked in so ``parity.mjs`` runs without a Python
environment, and ``--check`` is what CI uses to keep it honest.

Producing the file needs the ``extract`` extra (``pip install -e
'.[dev,extract]'``): one of the reference values is what the Python PDF
reader makes of an unruled field sheet, and that reader is pdfplumber
backed. Reading the file needs nothing.

``--check`` compares within a tolerance rather than byte for byte. The
inversion and the Theis fit go through LAPACK, which is not bit
reproducible across BLAS builds: the same input gives 1.4021310045105808
on one machine and 1.4021310045105801 on another. Those last digits carry
no information about the toolkit, so requiring them to match would make CI
fail on a runner upgrade while a genuine change of a millimetre in a
screen depth slipped through. The tolerance is tight enough that any real
change in behaviour still fails.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np

from groundwater.depth_spine.view import SpineInputs, build_view
from groundwater.costing import CostingInputs, inputs_from_design
from groundwater.design import design_borehole
from groundwater.hydraulics import analyse_pumping_test, test_type_text
from groundwater.ingestion import (
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from groundwater.models import (
    DrillingLog,
    SiteMetadata,
    WaterQualityResult,
    WaterQualitySample,
)
from groundwater.portfolio import (
    classify_status,
    portfolio_points,
    portfolio_rows,
    portfolio_stats,
    site_detail,
    site_one_pager,
)
from groundwater.geo import geodesic_distance_m, geographic_to_utm
from groundwater.quality import assess_sample
from groundwater.units import convert as unit_convert
from groundwater.siting import assess_siting
from groundwater.supervision.checklists import (
    legacy_item_ids,
    load_checklists,
    migrate_response_keys,
)
from groundwater.ves.interpret import drilling_preference_table, interpret_model
from groundwater.ves.inversion import invert_sounding

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "examples" / "data"
OUT = Path(__file__).resolve().parent / "reference.json"


def clean(value):
    """JSON-safe: NaN becomes null, numpy scalars become plain floats."""
    # bool before the numeric branches: bool is a subclass of int, and a
    # stabilised flag written out as 0 compares unequal to the browser's false.
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) else f
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.ndarray):
        return [clean(v) for v in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    # Dicts have to recurse too. Without this a mapping passed through here
    # came back untouched, so a tuple inside one stayed a tuple - identical
    # in the written JSON, but --check compares the fresh value against the
    # parsed file, and ("a", "b") != ["a", "b"]. That reads as 107 places
    # where the browser disagrees with the toolkit when nothing disagrees
    # at all, and a numpy scalar in the same position would survive too.
    if isinstance(value, dict):
        return {key: clean(v) for key, v in value.items()}
    return value


def site_dict(site):
    return {
        "client": site.client, "project": site.project,
        "community": site.community, "chiefdom": site.chiefdom,
        "district": site.district, "project_ref": site.project_ref,
        "easting": clean(site.easting), "northing": clean(site.northing),
        "elevation_m": clean(site.elevation_m), "supervisor": site.supervisor,
        "contractor": site.contractor,
    }


def flags(items):
    return [[f.level, f.code, f.message] for f in items]


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

    # The step test with the discharges an analyst would type in: the first
    # step ends above static and gets no drawdown fit, the recovery is read
    # against an equivalent time, and the two-step Hantush-Bierschenk line
    # says it is exact by construction.
    step_q = read_pumping_workbook(DATA / "kuntolo" / "kuntolo_step_test.xlsx")
    for step, q in zip(step_q.steps, (1.5, 2.2, 3.0), strict=True):
        step.discharge_m3_per_h = q
    step_analysis = analyse_pumping_test(step_q)
    step_rec = step_analysis.yield_recommendation
    out["step_analysis"] = {
        "T": clean(step_analysis.transmissivity_m2_per_day),
        "source": step_analysis.transmissivity_source,
        "qualifies": step_analysis.adopted_fit()[2],
        "cj": clean(step_analysis.cooper_jacob.transmissivity_m2_per_day)
              if step_analysis.cooper_jacob else None,
        "theis": clean(step_analysis.theis.transmissivity_m2_per_day)
                 if step_analysis.theis else None,
        "rec": clean(step_analysis.recovery.transmissivity_m2_per_day)
               if step_analysis.recovery else None,
        "rec_pumping_time": clean(step_analysis.recovery.pumping_time_min)
                            if step_analysis.recovery else None,
        "rec_equivalent": step_analysis.recovery.equivalent_time
                          if step_analysis.recovery else None,
        "B": clean(step_analysis.step_test.aquifer_loss_B) if step_analysis.step_test else None,
        "C": clean(step_analysis.step_test.well_loss_C) if step_analysis.step_test else None,
        "two_point": step_analysis.step_test.two_point if step_analysis.step_test else None,
        "safe": clean(step_rec.safe_yield_m3_per_h),
        "pump_depth": clean(step_rec.pump_installation_depth_m),
        "confidence": step_rec.confidence,
        "confidence_reasons": list(step_rec.confidence_reasons),
        "pump_depth_basis": step_rec.pump_depth_basis,
        "specific_capacity_basis": step_rec.specific_capacity_basis,
        "flags": [[f.level, f.code] for f in step_analysis.flags],
        "type_text": test_type_text(step_q.test_type),
        # the sheet's own step numbers, not a count of the steps that fitted
        "step_numbers": [s["step"] for s in step_analysis.step_test.steps]
                        if step_analysis.step_test else None,
    }

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
        "ids": [[i.item_id, i.legacy_id, i.checklist, i.section, i.critical]
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

    # The Depth Spine payload: the workspace decides nothing on its own, so
    # every figure it draws has to come back identical in the browser.
    spine = build_view(SpineInputs(
        name="Dr Timbo", log=log, analysis=analysis, assessment=assessed,
    ))
    spine_edited = build_view(
        SpineInputs(name="Dr Timbo", log=log, analysis=analysis,
                    assessment=assessed),
        screens_m=[(18.0, 30.0)],
    )
    out["spine"] = {
        "total_depth": clean(spine["section"]["totalDepth"]),
        "domain": clean(spine["section"]["domain"]),
        "lithology": [[clean(u["top"]), clean(u["base"]), u["aquifer"]]
                      for u in spine["section"]["lithology"]],
        "strikes": clean(spine["section"]["waterStrikes"]),
        "segments": [[s["kind"], clean(s["top"]), clean(s["base"])]
                     for s in spine["section"]["segments"]],
        "levels": {k: clean(v) for k, v in spine["section"]["levels"].items()},
        "screen_limits": {k: clean(v)
                          for k, v in spine["section"]["screenLimits"].items()},
        "screens": [[clean(s["top"]), clean(s["base"])]
                    for s in spine["design"]["screens"]],
        "total_screen_m": clean(spine["design"]["totalScreenM"]),
        "screen_share": clean(spine["design"]["screenShare"]),
        "yield_safe": clean(spine["design"]["yield"].get("safeYieldM3PerH")),
        "yield_range": spine["design"]["yield"].get("rangeText"),
        "yield_pump_depth": clean(spine["design"]["yield"].get("pumpDepthM")),
        "methods": [[m["label"], clean(m["transmissivity"])]
                    for m in spine["design"]["yield"].get("methods", [])],
        "design_flags": [[f["level"], f["code"]] for f in spine["design"]["flags"]],
        "cost_direct": clean(spine["costing"]["directCost"]),
        "cost_total": clean(spine["costing"]["totalCost"]),
        "cost_price": clean(spine["costing"]["price"]),
        "cost_per_metre": clean(spine["costing"]["costPerMetre"]),
        "by_stage": [[r["label"], clean(r["amount"]), clean(r["share"])]
                     for r in spine["costing"]["byStage"]],
        "quantity_basis": {k: clean(v)
                           for k, v in spine["costing"]["quantityBasis"].items()},
        "quality_verdict": spine["quality"]["verdict"],
        "quality_health": spine["quality"]["healthExceedances"],
        "quality_aesthetic": spine["quality"]["aestheticExceedances"],
        "quality_ratios": [[r["parameter"], clean(r["ratio"]), r["limitName"],
                            r["limitKind"]] for r in spine["quality"]["rows"]],
        "piper_percent": {k: clean(v)
                          for k, v in spine["quality"]["piper"]["percent"].items()},
        "edited_screens": [[clean(s["top"]), clean(s["base"])]
                           for s in spine_edited["design"]["screens"]],
        "edited_cost_direct": clean(spine_edited["costing"]["directCost"]),
        "edited": spine_edited["edited"],
    }

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

    # The verdict, over samples chosen to reach every state.
    def _wq(*results):
        return WaterQualitySample(site=SiteMetadata(community="Ref"),
                                  results=list(results))

    _panel = [
        WaterQualityResult("E. coli", 0.0, "CFU/100 mL"),
        WaterQualityResult("Arsenic", 0.001, "mg/L"),
        WaterQualityResult("Fluoride", 0.3, "mg/L"),
        WaterQualityResult("Nitrate (as NO3)", 5.0, "mg/L"),
    ]
    _cases = {
        "empty": _wq(),
        "pass": _wq(*_panel, WaterQualityResult("pH", 7.2, "pH units")),
        "aesthetic": _wq(*_panel, WaterQualityResult("Iron", 0.5, "mg/L")),
        # Aluminium used to be the national_fail case, on a WHO health value
        # of 0.9 mg/L that WHO does not set. Total coliforms above zero is
        # the real one: a national limit failure that is not a health
        # guideline failure and not faecal contamination.
        "national_fail": _wq(*_panel,
                             WaterQualityResult("Total coliforms", 5.0, "CFU/100 mL")),
        # a count the laboratory saw and did not put a number to, and a
        # ">100" inside its limit: both used to read as "not measured"
        "unquantified_count": _wq(*_panel, WaterQualityResult(
            "Total coliforms", None, "CFU/100 mL", greater_than=0.0)),
        "greater_than_inside_limit": _wq(*_panel, WaterQualityResult(
            "Sulfate", None, "mg/L", greater_than=100.0)),
        "health_fail": _wq(*_panel, WaterQualityResult("Arsenic", 0.5, "mg/L")),
        "micrograms": _wq(*_panel, WaterQualityResult("Lead", 5.0, "ug/L")),
        "bad_unit": _wq(*_panel, WaterQualityResult("Iron", 0.1, "wibbles")),
        "shallow_dl": _wq(*_panel, WaterQualityResult(
            "Cadmium", None, "mg/L", detection_limit=0.05, below_detection=True)),
        "unknown_parameter": _wq(
            *_panel, WaterQualityResult("Glyphosate", 0.4, "mg/L")),
        # the charge balance cannot be computed, and used to say nothing
        "no_ionic_balance": _wq(WaterQualityResult("Calcium", 40.0, "mg/L")),
    }
    out["verdicts"] = {}
    for name, sample in _cases.items():
        a = assess_sample(sample)
        out["verdicts"][name] = {
            "state": a.verdict_state,
            "statuses": [r.status for r in a.rows],
            "reasons": [r.reason for r in a.rows],
            "converted": [clean(r.value_in_guideline_unit) for r in a.rows],
            "uncertainties": list(a.uncertainties),
            "missing_essential": list(a.missing_essential),
            "verdict": a.verdict,
            "flags": [[f.level, f.code, f.message] for f in a.flags],
        }

    # The Depth Spine's guideline chart over units that are NOT the
    # guideline's own. The bundled sample reports everything in the guideline
    # unit, so a ratio computed from the raw value agrees there and the break
    # only shows on a converted one.
    from groundwater.depth_spine.view import _quality as _spine_quality

    out["spine_quality"] = [
        {
            "parameter": row["parameter"],
            "value": row["value"],
            "unit": row["unit"],
            "valueInGuidelineUnit": row["valueInGuidelineUnit"],
            "guidelineUnit": row["guidelineUnit"],
            "status": row["status"],
            "evaluable": row["evaluable"],
            "limitMax": row["limitMax"],
            "ratio": row["ratio"],
        }
        for row in _spine_quality(assess_sample(_wq(
            WaterQualityResult("Arsenic", 5.0, "ug/L"),
            WaterQualityResult("Electrical conductivity", 3.0, "mS/cm"),
            WaterQualityResult("Nitrate (as NO3)", 0.1, "g/L"),
            WaterQualityResult("Iron", 0.1, "wibbles"),
            WaterQualityResult("E. coli", 0.0, "CFU/100 mL"),
        )))["rows"]
    ]

    # The certification gate, over a project missing one thing at a time.
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

    # The QR encoder. Every module of every symbol, because a symbol that is
    # wrong in the data region still looks exactly like a QR symbol - and the
    # browser draws the one that gets printed and fixed to the headworks.
    from groundwater import qr

    _qr_payloads = [
        "SL-WAR-8FEEVKQ-T",
        ("BOREHOLE SL-WAR-8FEEVKQ-T\nDr. Timbo's (Western Area Rural)\n"
        "8.48310 N, 13.22940 W\n62.0 m deep, 1.85 m3/h"),
        "Kailahun - 10\u00b0 12' 03\" N",     # non-ASCII, so UTF-8 is exercised
    ]
    out["qr"] = [
        {
            "text": text, "ecc": ecc, "mask": mask,
            "version": _code.version, "size": _code.size,
            "chosen_mask": _code.mask,
            "penalty": qr._penalty(_code.modules),
            # one string per row keeps the reference file readable and diffable
            "rows": ["".join("1" if cell else "0" for cell in row)
                     for row in _code.modules],
        }
        for text in _qr_payloads
        for ecc in ("L", "M", "Q", "H")
        for mask in (None, 0, 5)
        for _code in [qr.encode(text, ecc=ecc, mask=mask)]
    ]
    out["qr_capacity"] = [
        {"version": v, "ecc": e, "bytes": qr._capacity_bytes(v, e)}
        for v in range(1, qr.MAX_VERSION + 1) for e in ("L", "M", "Q", "H")
    ]

    # The asset registry: identifiers, the merge, and what the event stream
    # says is true on a fixed day.
    from datetime import date as _date

    from groundwater import registry as _registry

    _sites = [
        SiteMetadata(district="Western Area Rural", easting=694912.0,
                     northing=938150.0, utm_zone=28),
        SiteMetadata(district="Western Area Rural", easting=694914.0,
                     northing=938147.0, utm_zone=28),
        SiteMetadata(district="Bo", easting=790500.0, northing=875300.0,
                     utm_zone=28),
        SiteMetadata(district="Kailahun", easting=280400.0, northing=925600.0,
                     utm_zone=29),
        SiteMetadata(district="Nowhere At All", easting=694912.0,
                     northing=938150.0, utm_zone=28),
    ]
    out["asset_ids"] = [
        {"district": s.district, "easting": s.easting, "northing": s.northing,
         "zone": s.utm_zone, "id": _registry.mint_asset_id(s)}
        for s in _sites
    ]
    _timbo_id = _registry.mint_asset_id(_sites[0])
    out["asset_id_parsing"] = [
        {"typed": t, "parsed": _registry.parse_asset_id(t),
         "ok": _registry.validate_asset_id(t)[0],
         "reason": _registry.validate_asset_id(t)[1]}
        for t in (_timbo_id, _timbo_id.lower(), _timbo_id.replace("0", "O"),
                  _timbo_id.replace("1", "L"), " " + _timbo_id + " ",
                  _timbo_id[:-1] + "Z", _timbo_id.replace("-", ""),
                  "SL-WAR-XXXXXXX-9", "not an identifier", "")
    ]
    _streams = [
        [{"when": "2020-01-10", "kind": "commissioned", "by": "M. Kolleh"},
         {"when": "2023-04-02", "kind": "failure", "note": "rising main parted"}],
        [{"when": "2023-04-02", "kind": "failure", "note": "rising main parted"},
         {"when": "2023-05-11", "kind": "repair", "note": "new seals",
          "by": "A. Bangura", "photo": "data:image/jpeg;base64,AAAA"},
         {"when": "not written down", "kind": "inspection"},
         {"when": "2099-01-01", "kind": "restored"}],
    ]
    out["asset_events"] = [
        e.as_dict() for e in _registry.merge_events(_timbo_id, *_streams)
    ]
    _registry_cases = {
        "silent": [],
        "commissioned": _streams[0][:1],
        "broken": _streams[0],
        "repaired": _streams[0] + [{"when": "2023-05-11", "kind": "restored"}],
        "sampled": _streams[0][:1] + [{"when": "2023-03-01", "kind": "water_sample"},
                                      {"when": "2024-05-20", "kind": "inspection"}],
        "decommissioned": _streams[0][:1] + [{"when": "2022-08-01",
                                              "kind": "decommissioned"}],
        "merged": _streams[0] + _streams[1],
    }
    _today = _date(2024, 6, 1)
    _assets = {}
    for _name, _events in _registry_cases.items():
        _assets[_name] = _registry.Asset(
            asset_id=_timbo_id, community="Dr. Timbo's",
            district="Western Area Rural", easting=694912.0, northing=938150.0,
            utm_zone=28, total_depth_m=62.0, safe_yield_m3_per_h=1.85,
            pump_type="India Mark II", installed_by="WiNGiN",
            events=[_registry.AssetEvent(**e) for e in _events],
        )
    out["asset_state"] = {
        name: _registry.asset_state(asset, _today).as_dict()
        for name, asset in _assets.items()
    }
    out["asset_placard"] = clean(_registry.placard_lines(
        _assets["commissioned"],
        _registry.asset_state(_assets["commissioned"], _today)))
    out["asset_qr_payload"] = _registry.qr_payload(_assets["commissioned"])
    out["registry_rows"] = _registry.registry_rows(list(_assets.values()), _today)
    out["registry_stats"] = clean(
        _registry.registry_stats(list(_assets.values()), _today))
    out["asset_months"] = [
        {"from": d, "months": m, "due": _registry._add_months(
            _date.fromisoformat(d), m).isoformat()}
        for d, m in (("2023-08-31", 6), ("2023-12-31", 2), ("2020-02-29", 12),
                     ("2023-01-31", 1), ("2023-03-30", 11), ("2024-02-29", 12))
    ]

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

    # Coverage as a planning figure: projection, freshness and the
    # dry-season band.
    from groundwater import planning as _planning
    from groundwater.waterpoints import WaterPoint as _WaterPoint

    def _wp(functional, year, months):
        return _WaterPoint(
            row_id="x", lat=8.0, lon=-13.0, functional=functional,
            status="", source="Borehole", technology="Hand Pump",
            install_year=None, adm2="", report_year=year,
            months_per_year=months)

    from groundwater.waterpoints import _months_per_year, _year_of

    out["wpdx_fields"] = [
        {"date": d, "year": _year_of(d),
         "months_text": m, "months": _months_per_year(m)}
        for d, m in (("2019-04-02T00:00:00", "12"), ("02/04/2019", "yes"),
                     ("2019", "6 months"), ("", ""), ("not a date", "seasonal"),
                     ("1899-01-01", "14"), ("survey 2024 round 2", "no"))
    ]
    out["growth_rate"] = _planning.intercensal_growth_rate()
    _planning_population = {
        "Bo": 575478.0, "Kono": 506100.0, "Pujehun": 346461.0,
        "Falaba": 202566.0, "Western Area Urban": 1055964.0,
    }
    _planning_points = {
        "Bo": [_wp(True, 2024, 12), _wp(True, 2010, None), _wp(False, 2024, 12)],
        "Kono": [_wp(True, None, None), _wp(True, 2003, 6)],
        "Pujehun": [_wp(False, 2020, None)],
        "Western Area Urban": [_wp(True, 2025, 12), _wp(True, 2025, None),
                               _wp(True, 2019, 4)],
    }
    out["planning"] = {}
    for _label, _year, _rate, _rates in (
        ("census", 2015, None, None),
        ("today", 2026, None, None),
        ("slow", 2026, 0.015, None),
        ("districts", 2026, None, {"Western Area Urban": 0.06, "Pujehun": 0.01}),
    ):
        _rows, _proj = _planning.planning_rows(
            _planning_population, _planning_points,
            as_of_year=_year, rate=_rate, rates=_rates)
        out["planning"][_label] = clean({
            "projection": _proj.as_dict(),
            "stats": _planning.planning_stats(_rows, _proj),
            "rows": [r.as_dict() for r in _rows],
        })

    # Procurement: planned against actual, and what that makes payable.
    from groundwater.procurement import (
        Contract as _Contract,
    )
    from groundwater.procurement import (
        ContractLine as _ContractLine,
    )
    from groundwater.procurement import (
        Measurement as _Measurement,
    )
    from groundwater.procurement import (
        Variation as _Variation,
    )
    from groundwater.procurement import certify as _certify
    from groundwater.procurement import contract_summary as _contract_summary

    def _proc_contract(**terms):
        return _Contract(
            ref="WSD/2024/017", contractor="WiNGiN", client="District Council",
            date="2024-02-01",
            lines=[
                _ContractLine("MOB", "Mobilisation", "sum", 1, 3000.0),
                _ContractLine("DRL-OB", "Drilling, overburden", "m", 20, 45.0),
                _ContractLine("DRL-RK", "Drilling, rock", "m", 25, 80.0),
                _ContractLine("CAS", "uPVC casing", "m", 45, 22.0),
            ],
            **terms)

    _proc_cases = {
        "clean": (_proc_contract(), [_Measurement("MOB", 1.0)], [], 1, 0.0),
        "overmeasured": (_proc_contract(),
                         [_Measurement("MOB", 1.0), _Measurement("DRL-RK", 42.0)],
                         [], 1, 0.0),
        "varied": (_proc_contract(),
                   [_Measurement("MOB", 1.0), _Measurement("DRL-RK", 42.0)],
                   [_Variation("VO-1", "2024-03-04", "DRL-RK", 17.0, None,
                               "deeper water", "M. Kolleh")], 2, 1500.0),
        "unsigned": (_proc_contract(), [_Measurement("GRAVEL", 12.0)],
                     [_Variation("VO-2", "2024-03-04", "CAS", 5.0)], 1, 0.0),
        "new_item": (_proc_contract(), [_Measurement("GRAVEL", 12.0)],
                     [_Variation("VO-3", "2024-03-04", "GRAVEL", 12.0, None,
                                 "gravel pack", "M. K.", "Gravel pack", "m3")],
                     1, 0.0),
        "advance": (_proc_contract(advance_percent=20.0, retention_percent=5.0),
                    [_Measurement("MOB", 1.0), _Measurement("DRL-OB", 20.0),
                     _Measurement("DRL-RK", 25.0), _Measurement("CAS", 45.0)],
                    [], 1, 0.0),
        "overpaid": (_proc_contract(retention_percent=0.0),
                     [_Measurement("MOB", 1.0)], [], 2, 5000.0),
        "negatives": (_proc_contract(), [_Measurement("CAS", -10.0)], [], 3, -5.0),
        # a rate-only variation is a variation; an omission beyond the line
        # authorises nothing; a duplicated code is valued once and named
        "repriced": (_proc_contract(),
                     [_Measurement("MOB", 1.0), _Measurement("CAS", 45.0)],
                     [_Variation("VO-4", "2024-03-04", "CAS", 0.0, 26.0,
                                 "supplier price", "Engineer")], 1, 0.0),
        "over_omitted": (_proc_contract(), [_Measurement("CAS", 10.0)],
                         [_Variation("VO-5", "2024-03-04", "CAS", -60.0, None,
                                     "redesign", "Engineer")], 1, 0.0),
        "duplicate": (_Contract(ref="DUP", lines=[
                          _ContractLine("CAS", "uPVC casing 6 in", "m", 10, 22.0),
                          _ContractLine("CAS", "uPVC casing 4 in", "m", 10, 22.0)]),
                      [_Measurement("CAS", 10.0)], [], 1, 0.0),
    }
    out["procurement"] = {}
    for _label, (_ct, _ms, _vs, _no, _prev) in _proc_cases.items():
        _cert = _certify(_ct, _ms, number=_no, date="2024-04-01",
                         variations=_vs, previously_certified_usd=_prev)
        out["procurement"][_label] = clean({
            "certificate": _cert.as_dict(),
            "summary_rows": _contract_summary(_ct, _cert),
        })

    # Rounding and %g, which the two languages get wrong in different ways.
    out["rounding"] = [
        {"value": v, "digits": d, "rounded": clean(round(v, d))}
        for v, d in ((0.15, 1), (14.05, 1), (2.675, 2), (0.5, 0), (1.5, 0),
                     (2.5, 0), (-0.15, 1), (2.34, 2), (2.345, 2), (0.125, 2),
                     (-2.5, 0), (45.05, 1), (150.5, 0))
    ]
    out["formatting"] = [
        {"value": v, "text": "%g" % v}
        for v in (1e6, 1e15, 999999.6, 1e5, 1e7, 1234567, 0.0001, 0.00001,
                  2.93, 0.0, 0.005, 1e-7)
    ]

    # The portfolio view, over summaries chosen to exercise every status class
    # and the zone-inference fallback.
    summaries = [
        {"community": "Rokel", "district": "Port Loko", "easting": 235000.0,
         "northing": 963000.0, "status": "sited"},
        {"community": "Dr. Timbo", "district": "Western Area Rural",
         "easting": 778000.0, "northing": 946000.0, "utm_zone": 28,
         "status": "Completed - successful", "total_depth_m": 45.0,
         "safe_yield_m3_per_h": 2.34, "water_verdict": "pass",
         "verdict_schema": 2, "cost_per_meter_usd": 133.0},
        {"community": "Kuntoloh", "district": "Western Area Rural",
         "status": "Completed - dry", "total_depth_m": 52.0,
         "water_verdict": "aesthetic", "cost_per_meter_usd": 151.0},
    ]
    out["portfolio"] = {
        "rows": clean(portfolio_rows(summaries)),
        "points": [[p["label"], clean(p["lat"]), clean(p["lon"]), p["status"]]
                   for p in portfolio_points(summaries)],
        "stats": clean(portfolio_stats(summaries)),
        "detail": [list(row) for row in site_detail(summaries[1])],
        "one_pager": site_one_pager(summaries[1]),
    }

    out["pdf_sheet"] = pdf_sheet_reference()
    out["pumping_cases"] = pumping_cases()
    return out


# ------------------------------------------------- pumping sheets at the edges

def _pumping_case_grids() -> dict[str, list[list]]:
    """The bundled pumping sheets with the cells rewritten that each
    hydraulics defect turned on: a recovery line that misses the origin, a
    level below the pump, a hole too shallow for the intake the test implies,
    hourly blocks read every few minutes, step times that restart, short
    steps inside the casing-storage period. Row 4 carries the borehole depth
    and row 5 the static level and pump setting in column 4 and 1; row 8 the
    step discharges; row 9 the block headings; readings start on row 11."""
    from groundwater.ingestion import common

    def grid_of(path):
        grid, _ = common.load_grid(path)
        return json.loads(json.dumps(grid, default=str))

    def copy(grid):
        return json.loads(json.dumps(grid))

    def clear_readings(grid):
        for row in grid[11:]:
            for c in range(15):
                row[c] = None

    timbo = grid_of(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    kuntolo = grid_of(DATA / "kuntolo" / "kuntolo_step_test.xlsx")
    swl = 9.44
    cases: dict[str, list[list]] = {}

    # the recovery on a clean line meeting t/t' = 1 at 20 m, beside fits that
    # are all disqualified; then with too few readings for any drawdown fit
    rejected = copy(timbo)
    for i, t_prime in enumerate([0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 45,
                                 50, 55, 60]):
        rejected[11 + i][13] = (42.26 if t_prime == 0 else round(
            swl + 20.0 + 9.0 * math.log10((30 + t_prime) / t_prime), 2))
    cases["rejected_recovery"] = rejected
    alone = copy(rejected)
    for row in alone[15:]:
        row[0] = row[1] = row[2] = None
    cases["every_fit_rejected"] = alone

    # the recovery line meeting t/t' = 1 below zero
    negative = copy(timbo)
    for i, t_prime in enumerate([0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 45,
                                 50, 55, 60]):
        negative[11 + i][13] = (42.26 if t_prime == 0 else round(
            swl - 8.0 + 20.0 * math.log10((30 + t_prime) / t_prime), 2))
    cases["negative_intercept"] = negative

    # the pump written at 15 m, 27 m above the deepest level recorded
    below_pump = copy(timbo)
    below_pump[5][4] = 15
    cases["level_below_pump"] = below_pump

    # a 45.5 m hole with the pump at 44 m
    shallow = copy(timbo)
    shallow[4][4] = 45.5
    shallow[5][4] = 44
    cases["shallow_hole"] = shallow

    # four hours in hourly blocks, hours two to four read every 5, 10 and 15
    # minutes and counted within the hour
    blocks = copy(timbo)
    clear_readings(blocks)
    for b, (start, times) in enumerate([
            (0, [0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 40, 50, 60]),
            (60, [5, 10, 15, 20, 25, 30, 40, 50, 60]),
            (120, [10, 20, 30, 40, 50, 60]), (180, [15, 30, 45, 60])]):
        for i, t in enumerate(times):
            blocks[11 + i][3 * b] = t
            blocks[11 + i][3 * b + 1] = round(
                swl + (0 if start + t == 0 else 3.0 * math.log10(start + t) + 5.0), 2)
    cases["blocks_by_heading"] = blocks

    # Kuntolo with its discharges, each step's time counted from its own start
    restart = copy(kuntolo)
    restart[8][2], restart[8][5], restart[8][8] = 1.5, 2.2, 3.0
    for row in restart[11:]:
        for col, offset in ((3, 60), (6, 120)):
            if isinstance(row[col], (int, float)):
                row[col] = row[col] - offset
    cases["step_restart"] = restart

    # three 50-minute steps, every one inside an 80-minute casing storage
    short = copy(kuntolo)
    short[2][4] = 50
    short[5][1] = 10.0
    short[8][2], short[8][5], short[8][8] = 1.0, 2.0, 3.0
    clear_readings(short)
    rates = [1.0, 2.0, 3.0]

    def drawdown(t):
        s = 0.0
        for i, q in enumerate(rates):
            if t > 50 * i:
                dq = q - (rates[i - 1] if i else 0.0)
                s += 2.303 * dq * 24 / (4 * math.pi * 2.5) * math.log10(
                    2.25 * 2.5 * ((t - 50 * i) / 1440) / (0.01 * 1e-3))
        q = rates[min(int((t - 1e-9) // 50), 2)]
        return s + 0.002 * (q * 24) ** 2 / 24

    for k in range(3):
        for i, t in enumerate([1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50]):
            short[11 + i][3 * k] = 50 * k + t
            short[11 + i][3 * k + 1] = round(10.0 + drawdown(50 * k + t), 2)
    cases["short_steps"] = short
    return cases


def pumping_cases() -> dict:
    """What Python makes of each edge sheet, with the sheet itself.

    The grid travels as a JSON string so the browser parses exactly the cells
    Python parsed; the rest is compared quantity by quantity, the prose word
    for word."""
    from groundwater.ingestion.pumping import _assemble

    out = {}
    for name, grid in _pumping_case_grids().items():
        test = _assemble(grid, f"{name}.xlsx")
        analysis = analyse_pumping_test(test)
        rec = analysis.yield_recommendation
        out[name] = {
            "grid": json.dumps(grid),
            "steps": [[s.step_number, clean(s.discharge_m3_per_h), len(s.time_min),
                       clean(float(np.min(s.time_min))), clean(float(np.max(s.time_min)))]
                      for s in test.steps],
            "duration": clean(test.pumping_duration_min),
            "source": analysis.transmissivity_source,
            "qualifies": analysis.adopted_fit()[2],
            "disqualified": sorted(analysis.disqualified),
            "invalid": sorted(analysis.invalid_fits),
            "T": clean(analysis.transmissivity_m2_per_day),
            "safe": clean(rec.safe_yield_m3_per_h),
            "range_text": rec.yield_range_text,
            "pump_depth": clean(rec.pump_installation_depth_m),
            "confidence": rec.confidence,
            "confidence_reasons": list(rec.confidence_reasons),
            "pending_reason": rec.pending_reason,
            "pump_depth_basis": rec.pump_depth_basis,
            "envelope_basis": rec.envelope_basis,
            "rec_pumping_time": clean(analysis.recovery.pumping_time_min)
                                if analysis.recovery else None,
            "step_numbers": [s["step"] for s in analysis.step_test.steps]
                            if analysis.step_test else None,
            "flags": flags(analysis.flags),
        }
    return out


# ------------------------------------------------- the unruled PDF field sheet

#: A typed VES sheet, placed with Tm/Tj and with no ruling line anywhere on
#: the page. Both readers find its table from word positions, so this is the
#: one fixture where the two have to agree byte for byte on the same input -
#: the bytes travel in the reference file and are decoded in the browser.
_PDF_ROWS = [[1, 1.5, 0.5, 210.4], [2, 2, 0.5, 233.1], [3, 3, 0.5, 268.0],
             [4, 4, 0.5, 291.7], [5, 6, 0.5, 302.5], [6, 8, 0.5, 288.2],
             [7, 10, 0.5, 264.9], [8, 15, 0.5, 198.3]]

_PDF_HEADER = [
    (60, 760, "SCHLUMBERGER ARRAY VES FIELD DATA"),
    (60, 735, "Community: Rokel"), (300, 735, "Client: Living Water International"),
    (60, 715, "District: Port Loko"), (300, 715, "Sounding Number: VES A-1"),
    (60, 695, "Date: 2023-05-14"), (300, 695, "Field Supervisor: M. Kolleh"),
    (60, 650, "No."), (110, 650, "AB/2 (m)"), (200, 650, "MN (m)"),
    (280, 650, "Apparent Resistivity (ohm-m)"),
]


def _typed_field_sheet_pdf() -> bytes:
    placed = list(_PDF_HEADER)
    for i, row in enumerate(_PDF_ROWS):
        y = 630 - i * 18
        for x, value in zip((60, 110, 200, 280), row, strict=True):
            placed.append((x, y, str(value)))

    ops = ["BT", "/F1 10 Tf"]
    for x, y, text in placed:
        escaped = str(text).replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")
        ops.append(f"1 0 0 1 {x} {y} Tm ({escaped}) Tj")
    ops.append("ET")
    # level 9 and no timestamp, so the same table always gives the same bytes
    content = zlib.compress("\n".join(ops).encode("latin-1"), 9)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"),
        b"<< /Length 6 0 R /Filter /FlateDecode >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        str(len(content)).encode(),
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def pdf_sheet_reference() -> dict:
    """What the Python reader makes of the sheet, plus the sheet itself."""
    from groundwater.extraction.pdf_text import extract_pdf_text

    pdf = _typed_field_sheet_pdf()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ves_sheet.pdf"
        path.write_bytes(pdf)
        document = extract_pdf_text(path)

    return {
        "b64": base64.b64encode(pdf).decode("ascii"),
        "kind": document.document_kind,
        "header": [[f.name, f.value] for f in document.header],
        "tables": [{"columns": list(t.columns), "rows": [list(r) for r in t.rows]}
                   for t in document.tables],
        "uncertain": len(document.uncertain_cells),
    }


# Loose enough to absorb a different BLAS build, tight enough that a real
# change in any reported quantity fails: 1e-6 relative is a millionth of a
# metre on a screen depth and a millionth of a percent on a fit error.
CHECK_RTOL = 1e-6


def drifted(fresh, committed, path=""):
    """Yield ``(path, fresh, committed)`` for every value that really differs."""
    if isinstance(fresh, dict) and isinstance(committed, dict):
        for key in sorted(set(fresh) | set(committed)):
            if key not in fresh or key not in committed:
                yield (f"{path}.{key}", fresh.get(key, "<missing>"),
                       committed.get(key, "<missing>"))
                continue
            yield from drifted(fresh[key], committed[key], f"{path}.{key}")
    elif isinstance(fresh, list) and isinstance(committed, list):
        if len(fresh) != len(committed):
            yield (f"{path}[]", f"{len(fresh)} items", f"{len(committed)} items")
            return
        for i, (a, b) in enumerate(zip(fresh, committed, strict=True)):
            yield from drifted(a, b, f"{path}[{i}]")
    elif isinstance(fresh, (int, float)) and isinstance(committed, (int, float)):
        if isinstance(fresh, bool) or isinstance(committed, bool):
            if fresh != committed:
                yield (path, fresh, committed)
        elif not math.isclose(fresh, committed, rel_tol=CHECK_RTOL, abs_tol=1e-12):
            yield (path, fresh, committed)
    elif fresh != committed:
        yield (path, fresh, committed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="compare the committed file against a fresh run instead of "
             "rewriting it; exit non-zero if anything really moved",
    )
    args = parser.parse_args()
    fresh = build()

    if not args.check:
        OUT.write_text(json.dumps(fresh, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {OUT}")
        return 0

    if not OUT.exists():
        print(f"{OUT} is missing; run this without --check to create it")
        return 1
    committed = json.loads(OUT.read_text(encoding="utf-8"))
    differences = list(drifted(fresh, committed))
    if not differences:
        print(f"{OUT} agrees with this toolkit to {CHECK_RTOL:g} relative")
        return 0
    print(f"{OUT} disagrees with this toolkit in {len(differences)} place(s):")
    for path, a, b in differences[:20]:
        print(f"  {path.lstrip('.')}: fresh {a!r} vs committed {b!r}")
    print("\nIf the change is intended, regenerate with:\n"
          "  python tests/webapp/make_reference.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
