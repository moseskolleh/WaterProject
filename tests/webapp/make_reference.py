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
from groundwater.design import design_borehole
from groundwater.hydraulics import analyse_pumping_test
from groundwater.ingestion import (
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from groundwater.models import (
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
from groundwater.ves.interpret import interpret_model
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
    }

    assessed = assess_sample(sample)
    out["assessed"] = {
        "verdict": assessed.verdict,
        "health": [r.parameter for r in assessed.health_exceedances],
        "wqi": clean(assessed.wqi.value) if assessed.wqi else None,
        "corros": assessed.corrosivity.classification,
        "ionic": clean(assessed.ionic.error_percent) if assessed.ionic else None,
    }

    design = design_borehole(log=log, static_water_level_m=test.static_water_level_m)
    out["design"] = {
        "depth": clean(design.total_depth_m),
        "screens": [[clean(s.top_m), clean(s.bottom_m)] for s in design.screens],
        "gravel": clean(list(design.gravel_pack)),
        "screen_len": clean(design.total_screen_length_m),
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
        for s, inv in zip(soundings, rokel_inversions)
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
        "national_fail": _wq(*_panel, WaterQualityResult("Aluminium", 0.5, "mg/L")),
        "health_fail": _wq(*_panel, WaterQualityResult("Arsenic", 0.5, "mg/L")),
        "micrograms": _wq(*_panel, WaterQualityResult("Lead", 5.0, "ug/L")),
        "bad_unit": _wq(*_panel, WaterQualityResult("Iron", 0.1, "wibbles")),
        "shallow_dl": _wq(*_panel, WaterQualityResult(
            "Cadmium", None, "mg/L", detection_limit=0.05, below_detection=True)),
        "unknown_parameter": _wq(
            *_panel, WaterQualityResult("Glyphosate", 0.4, "mg/L")),
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
            }
            for report in ("completion", "handover", "quality", "pumping")
        }

    # The QR encoder. Every module of every symbol, because a symbol that is
    # wrong in the data region still looks exactly like a QR symbol - and the
    # browser draws the one that gets printed and fixed to the headworks.
    from groundwater import qr

    _qr_payloads = [
        "SL-WAR-8FEEVKQ-T",
        "BOREHOLE SL-WAR-8FEEVKQ-T\nDr. Timbo's (Western Area Rural)\n"
        "8.48310 N, 13.22940 W\n62.0 m deep, 1.85 m3/h",
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
    out["asset_placard"] = _registry.placard_lines(
        _assets["commissioned"], _registry.asset_state(_assets["commissioned"], _today))
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
        for x, value in zip((60, 110, 200, 280), row):
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
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
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
        for i, (a, b) in enumerate(zip(fresh, committed)):
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
