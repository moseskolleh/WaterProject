"""Reference citations and a glossary shared by the report builders.

The reports name methods, standards and datasets throughout (WHO
guidelines, RWSN cost guidance, Theis, Cooper-Jacob, the bundled map
sources). This module chooses the full citations a References section
closes each report with, and holds a glossary of the abbreviations the reports use, so
they read as consultant-grade documents rather than naming sources that are
never fully cited.
"""

from __future__ import annotations

from ..text import phrase_table

#: Full bibliography entries, keyed by a short id. They are in
#: data/text/references.yaml, which the browser's reports read too.
CITATIONS: dict[str, str] = phrase_table("references.citations")

# references relevant to each report type, in a sensible reading order
_REFERENCES_FOR = {
    "geophysical": [
        "salwaco_geology", "usgs_geology", "bgs_atlas", "bgs_guide",
        "geoboundaries",
        "niwas_singhal", "rwsn_drilling",
    ],
    "pumping": ["theis", "cooper_jacob", "hantush", "papadopulos_cooper",
                "stehfest", "bourdet", "renard_diagnostic", "kunsch",
                "hall_horowitz_jing", "rwsn_drilling"],
    "quality": ["who", "slsb", "langelier"],
    "completion": ["rwsn_drilling", "rwsn_code_of_practice", "who", "slsb"],
    "handover": ["rwsn_drilling", "who", "slsb"],
    "cost": ["rwsn_code_of_practice", "rwsn_drilling"],
    "supervision": ["rwsn_drilling", "rwsn_code_of_practice"],
    # the dose card: the supervision guide the checklist item follows, and
    # WHO, which the dose calculator names
    "field_kit": ["rwsn_supervision", "who"],
}


def references_for(kind: str) -> list[str]:
    """Full bibliography entries for a report type."""
    return [CITATIONS[key] for key in _REFERENCES_FOR.get(kind, []) if key in CITATIONS]


# glossary of abbreviations and terms used across the reports
GLOSSARY: list[tuple[str, str]] = [
    ("VES", "Vertical electrical sounding, a resistivity depth survey"),
    ("AB/2", "Half the current-electrode spacing in a Schlumberger array"),
    ("ohm-m", "Ohm-metre, the unit of electrical resistivity"),
    ("ERR", "Root-mean-square misfit of the fitted layered model (percent)"),
    ("S (Dar-Zarrouk)", "Longitudinal conductance, sum of thickness/resistivity (siemens)"),
    ("T (Dar-Zarrouk)", "Transverse resistance, sum of thickness x resistivity (ohm m2)"),
    ("SWL", "Static water level, the rest water level before pumping"),
    ("DWL", "Dynamic water level, the water level during pumping"),
    ("T (transmissivity)", "Aquifer transmissivity (m2/day)"),
    ("S (storativity)", "Aquifer storage coefficient (dimensionless)"),
    ("m3/h", "Cubic metres per hour, a discharge or yield rate"),
    ("LSI / RSI", "Langelier and Ryznar indices of water corrosivity and scaling"),
    ("WQI", "Water Quality Index, an aggregate 0-based quality score"),
    ("HI", "Health Hazard Index, the sum of chronic hazard quotients"),
    ("uPVC", "Unplasticised polyvinyl chloride, the casing and screen material"),
    ("GPS / UTM", "Satellite positioning and the Universal Transverse Mercator grid"),
    ("WASH", "Water, sanitation and hygiene"),
    ("RWSN", "Rural Water Supply Network"),
    ("SALWACO", "Sierra Leone Water Company"),
    ("WHO", "World Health Organization"),
    ("SLSB", "Sierra Leone Standards Bureau"),
]
