"""Sample data for the Depth Spine workspace — Dr Timbo BH-01.

Mirrors the analysis the frontend bundles, so the Streamlit harness can vary
the inputs and watch the derived decisions, the diagrams and the bill of
quantities move.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

BOREHOLE: dict[str, Any] = {
    "id": "dr-timbo-bh-01",
    "name": "Dr Timbo BH-01",
    "locality": "Tonkolili",
    "terrain": "crystalline basement",
    "ves": [
        {"top": 0, "base": 1.5, "rho": 140},
        {"top": 1.5, "base": 9, "rho": 45},
        {"top": 9, "base": 24, "rho": 38},
        {"top": 24, "base": 41, "rho": 320, "aquifer": True},
        {"top": 41, "base": None, "rho": 2600},
    ],
    "lithology": [
        {"top": 0, "base": 1.5, "name": "Lateritic topsoil", "fill": "topsoil"},
        {"top": 1.5, "base": 9, "name": "Clayey sand", "fill": "clayey-sand"},
        {
            "top": 9,
            "base": 24,
            "name": "Sandy clay saprolite",
            "note": "weathered zone",
            "fill": "saprolite",
        },
        {
            "top": 24,
            "base": 41,
            "name": "Fractured granite",
            "note": "target aquifer",
            "fill": "fractured",
            "aquifer": True,
        },
        {"top": 41, "base": None, "name": "Fresh granite", "fill": "fresh"},
    ],
    "waterStrikes": [26.5, 33.0, 38.5],
    "construction": {
        "boreDiameter": 165,
        "casingDiameter": 125,
        "casingMaterial": "uPVC",
        "screenTop": 28,
        "screenBase": 40,
        "sanitarySealBase": 6,
        "totalDepth": 45,
        "screen": {"slotWidth": 1.0, "slotLength": 50, "rows": 6, "pitch": 16},
    },
    "hydraulics": {
        "restLevel": 8.2,
        "pumpingLevel": 14.3,
        "testRate": 1.03,
        "testDuration": 360,
        "drawdownPerLogCycle": 1.36,
        "safetyFactor": 0.7,
    },
    "field": {
        "sandContent": 2,
        "sandContentLimit": 5,
        "verticality": 0.4,
        "verticalityLimit": 1.0,
    },
}


ANALYSIS: dict[str, Any] = {
    "boreholeId": "dr-timbo-bh-01",
    "sampledOn": "18 March 2026",
    "laboratory": "SLARI Water Laboratory, Freetown",
    "transitHours": 26,
    "temperatureC": 28,
    "preserved": True,
    "determinands": [
        {"id": "ecoli", "label": "E. coli", "unit": "cfu/100 mL", "value": 0, "who": 0, "basis": "microbiological"},
        {"id": "tcoliform", "label": "Total coliforms", "unit": "cfu/100 mL", "value": 0, "who": 0, "basis": "microbiological"},
        {"id": "arsenic", "label": "Arsenic", "unit": "mg/L", "value": 0.002, "who": 0.01, "basis": "health"},
        {"id": "fluoride", "label": "Fluoride", "unit": "mg/L", "value": 0.35, "who": 1.5, "basis": "health"},
        {"id": "nitrate", "label": "Nitrate as NO₃", "unit": "mg/L", "value": 4.2, "who": 50, "basis": "health"},
        {"id": "manganese", "label": "Manganese", "unit": "mg/L", "value": 0.08, "who": 0.08, "basis": "health"},
        {"id": "iron", "label": "Iron", "unit": "mg/L", "value": 0.4, "who": 0.3, "basis": "acceptability"},
        {"id": "turbidity", "label": "Turbidity", "unit": "NTU", "value": 1.8, "who": 5, "basis": "acceptability"},
        {"id": "tds", "label": "Total dissolved solids", "unit": "mg/L", "value": 137, "who": 1000, "basis": "acceptability"},
        {"id": "chloride", "label": "Chloride", "unit": "mg/L", "value": 18, "who": 250, "basis": "acceptability"},
        {"id": "sulphate", "label": "Sulphate", "unit": "mg/L", "value": 11, "who": 250, "basis": "acceptability"},
        {"id": "hardness", "label": "Hardness as CaCO₃", "unit": "mg/L", "value": 70, "who": 500, "basis": "acceptability"},
        {"id": "ph", "label": "pH", "unit": "", "value": 6.4, "who": 8.5, "whoMin": 6.5, "basis": "acceptability"},
        {"id": "ec", "label": "Conductivity", "unit": "µS/cm", "value": 210, "who": None, "basis": "acceptability", "informational": True},
    ],
    "ions": {"ca": 18, "mg": 6.2, "na": 9.5, "k": 2.4, "hco3": 73, "cl": 18, "so4": 11, "no3": 4.2},
}


def borehole() -> dict[str, Any]:
    """A fresh, mutable copy of the sample borehole."""
    return deepcopy(BOREHOLE)


def analysis() -> dict[str, Any]:
    """A fresh, mutable copy of the sample water quality analysis."""
    return deepcopy(ANALYSIS)


def set_determinand(sample: dict[str, Any], determinand_id: str, value: float) -> None:
    """Set one determinand's measured value in place."""
    for d in sample["determinands"]:
        if d["id"] == determinand_id:
            d["value"] = value
            return
    raise KeyError(determinand_id)
