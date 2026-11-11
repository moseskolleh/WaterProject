"""The Depth Spine's payload: the "spine" and "spine_costed" entries of
``reference.json``.
"""

from __future__ import annotations

from groundwater.costing import load_rates
from groundwater.depth_spine.view import build_view, SpineCosting, SpineInputs

from .common import clean


def fill_spine(out: dict, log, analysis, assessed) -> None:
    """Fill "spine" and "spine_costed": the Depth Spine's payload for Dr Timbo,
    from the log, the pumping analysis and the assessed sample build() has
    already read and written out under their own keys.

    It fills ``out`` in place, where build() calls it: build.py says why."""
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
        # the rock each row is logged as, and the bands the drawing draws
        "lithology": [[clean(u["top"]), clean(u["base"]), u["aquifer"], u["class"]]
                      for u in spine["section"]["lithology"]],
        "bands": [[clean(b["top"]), clean(b["base"]), b["class"], b["colour"]]
                  for b in spine["section"]["bands"]],
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

    # The spine priced with the Costing page's settings rather than its
    # defaults. The Streamlit spine could not be given them, so the price
    # signed there was the catalogue's; the settings travel with the answer
    # so the browser prices with the very same ones.
    _rates = load_rates()
    _edited_rate = (_rates[0].code, round(_rates[0].unit_cost_usd * 1.5, 2))
    spine_settings = {
        "mobilisation_km": 120.0, "rate": list(_edited_rate),
        "overheads": 25.0, "margin": 10.0, "contingency": 5.0, "vat": 15.0,
        "exchange": 25.0, "overburden": 12.0, "wq_samples": 2, "handpumps": 0,
        "development_hours": 8.0, "test_pumping_hours": 36.0,
    }
    spine_costed = build_view(SpineInputs(
        name="Dr Timbo", log=log, analysis=analysis, assessment=assessed,
        mobilisation_distance_km=spine_settings["mobilisation_km"],
        costing=SpineCosting(
            rates=[r.with_likely(_edited_rate[1]) if r.code == _edited_rate[0] else r
                   for r in _rates],
            overheads_percent=spine_settings["overheads"],
            margin_percent=spine_settings["margin"],
            contingency_percent=spine_settings["contingency"],
            vat_percent=spine_settings["vat"],
            exchange_rate_sle_per_usd=spine_settings["exchange"],
            overburden_m=spine_settings["overburden"],
            wq_samples=spine_settings["wq_samples"],
            handpumps=spine_settings["handpumps"],
            development_hours=spine_settings["development_hours"],
            test_pumping_hours=spine_settings["test_pumping_hours"],
        ),
    ))
    out["spine_costed"] = {
        "settings": spine_settings,
        "money": {key: clean(spine_costed["costing"][key])
                  for key in ("directCost", "overheads", "totalCost", "margin",
                              "price", "vat", "costPerMetre", "overheadsPercent",
                              "marginPercent", "contingencyPercent", "vatPercent",
                              "exchangeRate")},
        "quantity_basis": {k: clean(v) for k, v
                           in spine_costed["costing"]["quantityBasis"].items()},
        "items": [[i["code"], clean(i["quantity"]), clean(i["unitCost"]),
                   clean(i["amount"])] for i in spine_costed["costing"]["items"]],
    }
