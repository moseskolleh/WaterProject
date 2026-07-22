"""Corrosivity and scaling indices, and a materials recommendation.

Soft, low-alkalinity, low-pH water from crystalline basement aquifers is
chemically aggressive and corrodes galvanised iron and mild-steel rising
mains and pump parts, which is a leading cause of premature handpump
failure across West Africa. The water can be aggressive even when the pH
is inside the 6.5 to 8.5 acceptability range, so a pH check alone is not
enough.

This module computes the classical indices from parameters the toolkit
already parses (pH, calcium, alkalinity, TDS or EC, temperature) and
turns them into a plain-language verdict and a rising-main / pump material
recommendation:

* Langelier Saturation Index (LSI)  - CaCO3 saturation; < 0 is corrosive.
* Ryznar Stability Index (RSI)      - practical corrosion/scaling scale.
* Aggressive Index (AI)             - AWWA index for asbestos-cement, a
                                      useful aggressiveness check.
* Larson-Skold Index                - chloride/sulfate attack on steel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ..models import DataFlag, WaterQualitySample
from .standards import normalise_parameter

# milli-equivalents per mg for the Larson-Skold ratio
_MEQ = {
    "chloride": 1 / 35.453,
    "sulfate": 2 / 96.06,
    "bicarbonate": 1 / 61.017,
    "carbonate": 2 / 60.009,
}


@dataclass
class CorrosivityAssessment:
    lsi: Optional[float] = None
    rsi: Optional[float] = None
    aggressive_index: Optional[float] = None
    larson_skold: Optional[float] = None
    classification: str = "Insufficient data"
    is_aggressive: bool = False
    verdict: str = ""
    materials_note: str = ""
    assumptions: list[str] = field(default_factory=list)
    flags: list[DataFlag] = field(default_factory=list)


def _value(sample: WaterQualitySample, key: str) -> Optional[float]:
    for result in sample.results:
        if normalise_parameter(result.parameter) == key:
            if result.value is not None:
                return float(result.value)
            return 0.0 if result.below_detection else None
    return None


def _classify_rsi(rsi: float) -> tuple[str, bool]:
    """Map a Ryznar index to a class and an is-aggressive flag."""
    if rsi < 6.0:
        return "Scale-forming", False
    if rsi <= 7.0:
        return "Balanced (near CaCO3 equilibrium)", False
    if rsi <= 8.0:
        return "Corrosive", True
    return "Strongly corrosive", True


def assess_corrosivity(sample: WaterQualitySample) -> CorrosivityAssessment:
    """Assess corrosivity/scaling from a water quality sample.

    Returns an assessment with whichever indices the available data
    supports. When pH, calcium and alkalinity are all present the
    saturation indices are computed; the Larson-Skold ratio additionally
    needs chloride and sulfate.
    """
    assessment = CorrosivityAssessment()
    assumptions = assessment.assumptions

    ph = _value(sample, "ph")
    calcium = _value(sample, "calcium")
    alkalinity = _value(sample, "alkalinity")
    tds = _value(sample, "tds")
    ec = _value(sample, "electrical conductivity")
    temp = _value(sample, "temperature")

    # TDS: measured, else estimated from EC, else a soft-water default
    if tds is None or tds <= 0:
        if ec and ec > 0:
            tds = 0.64 * ec
            assumptions.append(
                f"TDS estimated as 0.64 x EC = {tds:.0f} mg/L (TDS not reported)."
            )
        else:
            tds = 250.0
            assumptions.append("TDS assumed 250 mg/L (neither TDS nor EC reported).")
    if temp is None or temp <= 0:
        temp = 25.0
        assumptions.append("Temperature assumed 25 C (not reported).")

    if ph is None or calcium is None or alkalinity is None or calcium <= 0 or alkalinity <= 0:
        assessment.verdict = (
            "Corrosivity could not be assessed: pH, calcium and alkalinity are "
            "all required. Supply them to obtain a materials recommendation."
        )
        return assessment

    # calcium hardness as CaCO3 (Ca mg/L x 100.09/40.08)
    ca_hardness = calcium * 2.497

    # Langelier: pHs = (9.3 + A + B) - (C + D)
    a = (math.log10(tds) - 1.0) / 10.0
    b = -13.12 * math.log10(temp + 273.15) + 34.55
    c = math.log10(ca_hardness) - 0.4
    d = math.log10(alkalinity)
    ph_s = (9.3 + a + b) - (c + d)
    lsi = ph - ph_s
    rsi = 2 * ph_s - ph
    ai = ph + math.log10(alkalinity * ca_hardness)

    assessment.lsi = round(lsi, 2)
    assessment.rsi = round(rsi, 2)
    assessment.aggressive_index = round(ai, 2)

    # Larson-Skold (optional): (Cl + SO4) / (HCO3 + CO3) in meq/L
    chloride = _value(sample, "chloride")
    sulfate = _value(sample, "sulfate")
    bicarbonate = _value(sample, "bicarbonate")
    carbonate = _value(sample, "carbonate")
    if bicarbonate is None:
        # alkalinity (as CaCO3) -> bicarbonate equivalent meq/L
        hco3_meq = alkalinity / 50.04
    else:
        hco3_meq = bicarbonate * _MEQ["bicarbonate"]
    co3_meq = (carbonate or 0.0) * _MEQ["carbonate"]
    if chloride is not None and sulfate is not None and (hco3_meq + co3_meq) > 0:
        ls = (chloride * _MEQ["chloride"] + sulfate * _MEQ["sulfate"]) / (
            hco3_meq + co3_meq
        )
        assessment.larson_skold = round(ls, 2)

    classification, aggressive = _classify_rsi(rsi)
    # corroborate with LSI and AI
    if lsi < -0.5:
        aggressive = True
    if assessment.aggressive_index is not None and assessment.aggressive_index < 10:
        aggressive = True
    # Keep the class label consistent with the flag and verdict: when the
    # LSI/AI corroboration promotes borderline water to aggressive, the RSI
    # class ("Balanced", "Scale-forming") must not still say otherwise, else
    # a report shows a "Balanced" label beside an "aggressive" verdict.
    if aggressive and classification not in ("Corrosive", "Strongly corrosive"):
        classification = "Corrosive"
    assessment.classification = classification
    assessment.is_aggressive = aggressive

    if aggressive:
        assessment.verdict = (
            f"The water is chemically aggressive (Ryznar index {rsi:.1f}, "
            f"Langelier index {lsi:+.1f}). It will corrode metal fittings, and "
            "it can be aggressive even though the pH is within the acceptability "
            "range, which is typical of soft basement groundwater."
        )
        assessment.materials_note = (
            "Specify uPVC or stainless steel (grade 304 or 316) for the rising "
            "main and pump components, and avoid galvanised iron and mild steel, "
            "which corrode rapidly in this water and are a leading cause of "
            "premature handpump failure. Inspect the rising main and pump rods "
            "for corrosion at each service."
        )
        if assessment.larson_skold is not None and assessment.larson_skold > 0.8:
            assessment.materials_note += (
                f" The Larson-Skold ratio ({assessment.larson_skold:.1f}) is "
                "elevated, so chloride and sulfate add to the attack on steel."
            )
        assessment.flags.append(
            DataFlag(
                "warning",
                "aggressive_water",
                "Water is chemically aggressive; specify uPVC or stainless rising "
                "main and pump components.",
            )
        )
    elif classification == "Scale-forming":
        assessment.verdict = (
            f"The water tends to deposit calcium carbonate scale (Ryznar index "
            f"{rsi:.1f}, Langelier index {lsi:+.1f})."
        )
        assessment.materials_note = (
            "Monitor the screen and pump for encrustation and de-scale as needed; "
            "corrosion of metal parts is a lesser concern."
        )
    else:
        assessment.verdict = (
            f"The water is close to calcium carbonate equilibrium (Ryznar index "
            f"{rsi:.1f}, Langelier index {lsi:+.1f}); neither strong corrosion nor "
            "scaling is expected."
        )
        assessment.materials_note = (
            "Standard materials are acceptable; inspect fittings for corrosion "
            "during routine maintenance."
        )
    return assessment
