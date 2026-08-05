"""Build the Depth Spine view payload from the analysis objects.

The browser draws; this module decides. Every number the workspace shows is
computed here by the same functions the reports use, so the section, the rail
and the bill of quantities cannot drift from the .docx. The frontend owns only
the depth-to-pixel mapping and the pointer.

Pure and Streamlit-free, so the payload is unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ..config import Config
from ..costing.model import (
    CostEstimate,
    estimate_borehole_cost,
    inputs_from_design,
)
from ..design.designer import BoreholeDesign, design_borehole
from ..hydraulics.analysis import PumpingTestAnalysis
from ..models import DataFlag, DrillingLog, WaterQualitySample
from ..quality.assess import WaterQualityAssessment, assess_sample
from ..quality.standards import Limit


def _flag(flag: DataFlag) -> dict[str, str]:
    return {
        "level": flag.level,
        "code": flag.code,
        "message": flag.message,
        "context": flag.context,
    }


def _round(value: Optional[float], places: int = 2) -> Optional[float]:
    return None if value is None else round(float(value), places)


@dataclass
class SpineInputs:
    """Everything the workspace can draw, in whatever combination exists.

    Only the drilling log is required. A project with no pumping test still
    gets a section and a bill of quantities; the yield card says what is
    missing rather than inventing a number.
    """

    name: str
    log: DrillingLog
    analysis: Optional[PumpingTestAnalysis] = None
    #: A raw sample, assessed here.
    quality: Optional[WaterQualitySample] = None
    #: An assessment the caller already ran - preferred over ``quality``, so
    #: the workspace shows the same object the Water quality page does rather
    #: than a second run of the same computation.
    assessment: Optional[WaterQualityAssessment] = None
    config: Optional[Config] = None
    mobilisation_distance_km: float = 0.0


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------

def _section(log: DrillingLog, design: BoreholeDesign, analysis, config: Config) -> dict:
    """Everything indexed by depth, on one axis."""
    total_depth = design.total_depth_m
    # A little air below the hole so the total-depth line is not on the edge.
    domain = total_depth * 1.06

    lithology = [
        {
            "top": iv.top_m,
            "base": iv.bottom_m,
            "description": iv.description,
            "aquifer": _looks_like_aquifer(iv.description),
        }
        for iv in log.intervals
    ]

    levels: dict[str, Any] = {}
    swl = design.static_water_level_m
    if swl is not None:
        levels["restLevel"] = _round(swl)
    if analysis is not None:
        # The toolkit only calls a level "stabilised" when the last readings
        # agree within 5 cm. When they do not, the honest line to draw is the
        # deepest level reached, labelled as still falling — drawing it as a
        # stabilised pumping level would overstate what the test showed.
        levels["stabilised"] = analysis.stabilised_level_m is not None
        levels["maxDrawdown"] = _round(analysis.max_drawdown_m)
        if analysis.stabilised_level_m is not None:
            levels["pumpingLevel"] = _round(analysis.stabilised_level_m)
        elif swl is not None and analysis.max_drawdown_m is not None:
            levels["pumpingLevel"] = _round(swl + analysis.max_drawdown_m)
    if design.pump_intake_m is not None:
        levels["pumpIntake"] = _round(design.pump_intake_m, 1)

    return {
        "totalDepth": total_depth,
        "domain": domain,
        "lithology": lithology,
        "waterStrikes": list(design.water_strikes_m),
        "segments": [
            {"kind": s.kind, "top": s.top_m, "base": s.bottom_m} for s in design.segments
        ],
        "gravelPack": list(design.gravel_pack),
        "backfill": list(design.backfill),
        "sanitarySeal": list(design.sanitary_seal),
        "levels": levels,
        "boreDiameterIn": design.borehole_diameter_in,
        "casingDiameterIn": design.casing_diameter_in,
        "casingMaterial": design.casing_material,
        "slotMm": design.screen_slot_mm,
        "stickupM": design.stickup_m,
        "drillingMethod": log.drilling_method,
        # The handles may not move a screen outside this band.
        "screenLimits": {
            "top": 0.0,
            "base": total_depth - config.design.sump_length_m,
            "minLength": 0.5,
        },
    }


_AQUIFER_HINTS = ("fracture", "water", "aquifer")


def _looks_like_aquifer(description: str) -> bool:
    """Only for shading the log — screen placement uses designer._target_zones."""
    text = (description or "").lower()
    if any(neg in text for neg in ("no water", "not reached", "without water")):
        return False
    return any(hint in text for hint in _AQUIFER_HINTS)


# ---------------------------------------------------------------------------
# Design decisions
# ---------------------------------------------------------------------------

def _design_decisions(design: BoreholeDesign, analysis, config: Config) -> dict:
    rules = config.design
    screens = design.screens
    yield_block: dict[str, Any] = {"pending": "No pumping test loaded for this borehole."}

    if analysis is not None and analysis.yield_recommendation is not None:
        rec = analysis.yield_recommendation
        yield_block = {
            "pending": rec.pending_reason or "",
            "safeYieldM3PerH": _round(rec.safe_yield_m3_per_h),
            "lowM3PerH": _round(rec.safe_yield_low_m3_per_h),
            "highM3PerH": _round(rec.safe_yield_high_m3_per_h),
            "rangeText": rec.yield_range_text,
            "longTermM3PerH": _round(rec.long_term_yield_m3_per_h),
            "specificCapacity": _round(rec.specific_capacity_m3hr_per_m),
            "availableDrawdownM": _round(rec.available_drawdown_m),
            "usableDrawdownM": _round(rec.usable_drawdown_m),
            "pumpDepthM": _round(rec.pump_installation_depth_m, 1),
            "safetyFactor": rec.safety_factor,
            "designPeriodDays": rec.design_period_days,
            "basis": rec.basis,
            "envelopeBasis": rec.envelope_basis,
            "transmissivity": _round(analysis.transmissivity_m2_per_day, 2),
            "methods": _methods(analysis),
        }

    return {
        "yield": yield_block,
        "screens": [{"top": s.top_m, "base": s.bottom_m} for s in screens],
        "totalScreenM": _round(design.total_screen_length_m, 1),
        "screenShare": _round(
            design.total_screen_length_m / design.total_depth_m * 100, 1
        ),
        "slotMm": design.screen_slot_mm,
        "rules": {
            "sumpLengthM": rules.sump_length_m,
            "gravelAboveTopScreenM": rules.gravel_pack_above_top_screen_m,
            "sanitarySealDepthM": rules.sanitary_seal_depth_m,
            "minScreenBelowSwlM": rules.min_screen_below_swl_m,
            "submergenceMinM": config.pumping.pump_submergence_min_m,
            "seasonalAllowanceM": config.pumping.seasonal_allowance_m,
        },
        "basis": list(design.design_basis),
        "flags": [_flag(f) for f in design.flags]
        + ([_flag(f) for f in analysis.flags] if analysis is not None else []),
    }


def _methods(analysis: PumpingTestAnalysis) -> list[dict]:
    """Cross-method transmissivity, so agreement is visible rather than claimed."""
    out = []
    for label, result in (
        ("Cooper-Jacob", analysis.cooper_jacob),
        ("Theis", analysis.theis),
        ("Recovery", analysis.recovery),
    ):
        if result is None:
            continue
        out.append(
            {
                "label": label,
                "transmissivity": _round(result.transmissivity_m2_per_day, 2),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Water quality
# ---------------------------------------------------------------------------

def _binding_limit(row) -> tuple[Optional[Limit], str]:
    """The limit a row is judged against, and what kind of limit it is.

    The strictest applicable maximum binds. Which one it was matters in the
    report - a national limit exceeded is a compliance failure, an
    acceptability limit exceeded is a taste complaint - so the name travels
    with the number.
    """
    candidates = [
        ("WHO health", Limit.parse(row.who_health)),
        ("WHO acceptability", Limit.parse(row.who_aesthetic)),
        ("national", Limit.parse(row.sl_standard)),
    ]
    best: tuple[Optional[Limit], str] = (None, "")
    for name, limit in candidates:
        if limit is None:
            continue
        if limit.minimum is not None:  # a range, e.g. pH
            return limit, name
        if limit.maximum is None:
            continue
        if best[0] is None or limit.maximum < best[0].maximum:
            best = (limit, name)
    return best


def _quality(assessment: WaterQualityAssessment) -> dict:
    rows = []
    for r in assessment.rows:
        limit, limit_name = _binding_limit(r)
        # The chart plots every determinand as a multiple of its own limit, so
        # the ratio is computed here rather than by parsing limit strings in
        # the browser.
        ratio = None
        kind = "none"
        if limit is not None:
            kind = "range" if limit.minimum is not None else "max"
            # The limit is written in the guideline's unit, so the value has
            # to be on that scale too. Dividing the raw reported number by it
            # plotted a compliant ug/L result a thousand times over its line.
            if r.value_in_guideline_unit is not None and limit.maximum:
                ratio = float(r.value_in_guideline_unit) / float(limit.maximum)
        rows.append(
            {
                "parameter": r.parameter,
                "value": _round(r.value, 4),
                "unit": r.unit,
                "valueInGuidelineUnit": _round(r.value_in_guideline_unit, 4),
                "guidelineUnit": r.guideline_unit,
                "evaluable": r.evaluable,
                "reason": r.reason,
                "belowDetection": r.below_detection,
                "whoHealth": r.who_health,
                "whoAesthetic": r.who_aesthetic,
                "national": r.sl_standard,
                "status": r.status,
                "remark": r.remark,
                "limitKind": kind,
                "limitName": limit_name,
                "limitMax": _round(limit.maximum, 4) if limit else None,
                "limitMin": _round(limit.minimum, 4) if limit else None,
                "ratio": _round(ratio, 4),
            }
        )

    ionic = None
    if assessment.ionic is not None:
        ionic = {
            "cationsMeq": _round(assessment.ionic.sum_cations_meq, 3),
            "anionsMeq": _round(assessment.ionic.sum_anions_meq, 3),
            "errorPercent": _round(assessment.ionic.error_percent, 2),
            "cations": {k: _round(v, 4) for k, v in assessment.ionic.cations_meq.items()},
            "anions": {k: _round(v, 4) for k, v in assessment.ionic.anions_meq.items()},
            "usedAlkalinity": assessment.ionic.used_alkalinity_for_bicarbonate,
        }

    corrosivity = None
    if assessment.corrosivity is not None:
        c = assessment.corrosivity
        corrosivity = {
            "lsi": _round(c.lsi),
            "rsi": _round(c.rsi),
            "aggressiveIndex": _round(c.aggressive_index),
            "larsonSkold": _round(c.larson_skold),
            "classification": c.classification,
            "isAggressive": c.is_aggressive,
            "verdict": c.verdict,
            "materialsNote": c.materials_note,
            "assumptions": list(c.assumptions),
        }

    piper = _piper(assessment)

    wqi = None
    if assessment.wqi is not None:
        wqi = {
            "value": _round(assessment.wqi.value, 1),
            "rating": assessment.wqi.rating,
        }

    return {
        "sampleId": assessment.sample.sample_id,
        "sampleDate": assessment.sample.sample_date,
        "laboratory": assessment.sample.laboratory,
        "rows": rows,
        "verdict": assessment.verdict,
        "verdictState": assessment.verdict_state,
        "uncertainties": list(assessment.uncertainties),
        "healthExceedances": [r.parameter for r in assessment.health_exceedances],
        "nationalExceedances": [r.parameter for r in assessment.national_exceedances],
        "aestheticExceedances": [
            r.parameter for r in assessment.aesthetic_exceedances
        ],
        "indeterminate": [r.parameter for r in assessment.indeterminate_rows],
        "ionic": ionic,
        "piper": piper,
        "corrosivity": corrosivity,
        "wqi": wqi,
        "flags": [_flag(f) for f in assessment.flags],
    }


def _piper(assessment: WaterQualityAssessment) -> Optional[dict]:
    """Cation and anion percentages for the Piper and Stiff plots.

    Reuses the milliequivalents the ionic balance already worked out, so the
    diagrams and the balance check can never disagree.
    """
    if assessment.ionic is None:
        return None
    cations = assessment.ionic.cations_meq
    anions = assessment.ionic.anions_meq
    total_c = sum(cations.values())
    total_a = sum(anions.values())
    if total_c <= 0 or total_a <= 0:
        return None

    def c(key: str) -> float:
        return cations.get(key, 0.0)

    def a(key: str) -> float:
        return anions.get(key, 0.0)

    na_k = c("sodium") + c("potassium")
    return {
        "meq": {
            "ca": _round(c("calcium"), 4),
            "mg": _round(c("magnesium"), 4),
            "naK": _round(na_k, 4),
            "hco3": _round(a("bicarbonate"), 4),
            "cl": _round(a("chloride"), 4),
            "so4": _round(a("sulfate"), 4),
        },
        "percent": {
            "ca": _round(c("calcium") / total_c, 4),
            "mg": _round(c("magnesium") / total_c, 4),
            "naK": _round(na_k / total_c, 4),
            "hco3": _round(a("bicarbonate") / total_a, 4),
            "cl": _round(a("chloride") / total_a, 4),
            "so4": _round(a("sulfate") / total_a, 4),
        },
    }


# ---------------------------------------------------------------------------
# Costing
# ---------------------------------------------------------------------------

def _costing(estimate: CostEstimate) -> dict:
    items = [
        {
            "code": i.code,
            "stage": i.stage,
            "category": i.category,
            "item": i.item,
            "unit": i.unit,
            "quantity": _round(i.quantity, 3),
            "unitCost": _round(i.unit_cost_usd),
            "amount": _round(i.amount_usd),
            "note": i.note,
        }
        for i in estimate.items
    ]

    def _group(key: str) -> list[dict]:
        totals: dict[str, float] = {}
        for i in estimate.items:
            totals[getattr(i, key)] = totals.get(getattr(i, key), 0.0) + i.amount_usd
        direct = estimate.direct_cost_usd or 1.0
        return sorted(
            (
                {"label": k, "amount": _round(v), "share": _round(v / direct * 100, 1)}
                for k, v in totals.items()
            ),
            key=lambda row: row["amount"],
            reverse=True,
        )

    return {
        "items": items,
        "byStage": _group("stage"),
        "byCategory": _group("category"),
        "directCost": _round(estimate.direct_cost_usd),
        "overheads": _round(estimate.overheads_usd),
        "totalCost": _round(estimate.total_cost_usd),
        "margin": _round(estimate.margin_usd),
        "price": _round(estimate.price_usd),
        "vat": _round(estimate.vat_usd),
        "costPerMetre": _round(estimate.cost_per_meter_usd),
        "overheadsPercent": estimate.overheads_percent,
        "marginPercent": estimate.margin_percent,
        "contingencyPercent": estimate.contingency_percent,
        "vatPercent": estimate.vat_percent,
        "exchangeRate": estimate.exchange_rate_sle_per_usd,
        "assumptions": list(estimate.assumptions),
        "flags": [_flag(f) for f in estimate.flags],
        "quantityBasis": {
            "totalDepthM": estimate.inputs.total_depth_m,
            "casingM": _round(estimate.inputs.casing_m, 1),
            "screenM": _round(estimate.inputs.screen_m, 1),
            "gravelIntervalM": _round(estimate.inputs.gravel_interval_m, 1),
            "overburdenM": _round(estimate.inputs.overburden_m, 1),
        },
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_view(
    inputs: SpineInputs,
    screens_m: list[tuple[float, float]] | None = None,
) -> dict:
    """Derive the whole workspace from the analysis objects.

    ``screens_m`` is the analyst's screen placement from the section. Passing
    it re-runs the design and everything downstream of it - the annulus, the
    checks and the bill of quantities - so the drawing and the BoQ are always
    the same design.
    """
    config = inputs.config or Config()
    analysis = inputs.analysis
    swl = None
    pump_intake = None
    if analysis is not None:
        swl = analysis.test.static_water_level_m
        if analysis.yield_recommendation is not None:
            pump_intake = analysis.yield_recommendation.pump_installation_depth_m

    design = design_borehole(
        log=inputs.log,
        static_water_level_m=swl,
        pump_intake_m=pump_intake,
        rules=config.design,
        screens_m=screens_m,
    )

    estimate = estimate_borehole_cost(
        inputs_from_design(
            design, mobilisation_distance_km=inputs.mobilisation_distance_km
        )
    )

    site = inputs.log.site
    payload: dict[str, Any] = {
        "project": inputs.name,
        "site": {
            "community": site.community,
            "district": site.district,
            "chiefdom": site.chiefdom,
            "client": site.client,
            "boreholeRef": inputs.log.borehole_ref,
            "latlon": list(site.latlon) if site.latlon else None,
        },
        "section": _section(inputs.log, design, analysis, config),
        "design": _design_decisions(design, analysis, config),
        "costing": _costing(estimate),
        "quality": None,
        "edited": screens_m is not None,
    }

    assessment = inputs.assessment
    if assessment is None and inputs.quality is not None:
        assessment = assess_sample(inputs.quality)
    if assessment is not None:
        payload["quality"] = _quality(assessment)

    return payload
