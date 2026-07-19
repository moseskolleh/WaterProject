"""Reference citations and a glossary shared by the report builders.

The reports name methods, standards and datasets throughout (WHO
guidelines, RWSN cost guidance, Theis, Cooper-Jacob, the bundled map
sources). This module holds the full citations so a References section can
close each report, and a glossary of the abbreviations the reports use, so
they read as consultant-grade documents rather than naming sources that are
never fully cited.
"""

from __future__ import annotations

# full bibliography entries, keyed by a short id
CITATIONS: dict[str, str] = {
    "who": (
        "World Health Organization (2022). Guidelines for Drinking-water "
        "Quality, 4th edition incorporating the first and second addenda. "
        "Geneva: World Health Organization."
    ),
    "slsb": (
        "Sierra Leone Standards Bureau. Sierra Leone Standard for drinking "
        "water quality (SLS). Freetown: SLSB."
    ),
    "rwsn_cost": (
        "Rural Water Supply Network (2010). Code of Practice for Cost "
        "Effective Boreholes. St Gallen: RWSN."
    ),
    "rwsn_drilling": (
        "Rural Water Supply Network (2015). Professional Water Well Drilling: "
        "A UNICEF Guidance Note. St Gallen: RWSN / UNICEF."
    ),
    "theis": (
        "Theis, C.V. (1935). The relation between the lowering of the "
        "piezometric surface and the rate and duration of discharge of a well "
        "using groundwater storage. Transactions of the American Geophysical "
        "Union, 16, 519-524."
    ),
    "cooper_jacob": (
        "Cooper, H.H. and Jacob, C.E. (1946). A generalized graphical method "
        "for evaluating formation constants and summarizing well-field "
        "history. Transactions of the American Geophysical Union, 27, 526-534."
    ),
    "hantush": (
        "Hantush, M.S. (1964). Hydraulics of wells. In V.T. Chow (ed.), "
        "Advances in Hydroscience, 1, 281-442."
    ),
    "niwas_singhal": (
        "Niwas, S. and Singhal, D.C. (1981). Estimation of aquifer "
        "transmissivity from Dar-Zarrouk parameters in porous media. Journal "
        "of Hydrology, 50, 393-399."
    ),
    "langelier": (
        "Langelier, W.F. (1936). The analytical control of anti-corrosion "
        "water treatment. Journal of the American Water Works Association, 28, "
        "1500-1521."
    ),
    "geoboundaries": (
        "Runfola, D. et al. (2020). geoBoundaries: A global database of "
        "political administrative boundaries. PLoS ONE, 15(4). Licensed CC BY "
        "4.0."
    ),
    "bgs_atlas": (
        "MacDonald, A.M. et al. British Geological Survey, Africa Groundwater "
        "Atlas: Hydrogeology of Sierra Leone (OR/21/063). Licensed CC BY-SA "
        "4.0."
    ),
    "usgs_geology": (
        "United States Geological Survey (1997). Geologic Map of Africa, "
        "Open-File Report 97-470A. Public domain, 1:5,000,000."
    ),
    "salwaco_geology": (
        "Ministry of Water Resources and SALWACO (2017). Geology of Sierra "
        "Leone. Freetown."
    ),
}

# references relevant to each report type, in a sensible reading order
_REFERENCES_FOR = {
    "geophysical": [
        "salwaco_geology", "usgs_geology", "bgs_atlas", "geoboundaries",
        "niwas_singhal", "rwsn_drilling",
    ],
    "pumping": ["theis", "cooper_jacob", "hantush", "rwsn_drilling"],
    "quality": ["who", "slsb", "langelier"],
    "completion": ["rwsn_drilling", "rwsn_cost", "who", "slsb"],
    "handover": ["rwsn_drilling", "who", "slsb"],
    "cost": ["rwsn_cost", "rwsn_drilling"],
    "supervision": ["rwsn_drilling", "rwsn_cost"],
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
