"""Aggregate water quality index and health-risk scoring.

Two summary numbers a district water office can use to rank many
boreholes and prioritise treatment or rehabilitation:

* Water Quality Index (WQI) - a weighted-arithmetic 0-based index over the
  physico-chemical parameters, with the usual rating classes (Excellent to
  Unsuitable). One number per borehole for comparison.

* Health Hazard Index (HI) - the sum of hazard quotients (chronic daily
  intake over the oral reference dose) for the toxicants that matter for
  long-term ingestion (arsenic, fluoride, nitrate, manganese, lead,
  uranium and others), plus a lifetime carcinogenic risk for arsenic. HI
  below 1 is generally acceptable; at or above 1 there is a potential
  non-carcinogenic health concern.

Both are computed from the values and guideline limits the toolkit already
carries, and both degrade gracefully when parameters are missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..models import DataFlag, WaterQualitySample
from .standards import Limit, StandardEntry, load_standards, normalise_parameter

# adult chronic exposure (WHO/EPA default)
_INTAKE_L_PER_DAY = 2.0
_BODY_WEIGHT_KG = 70.0

# oral reference doses, mg/kg/day (EPA IRIS / WHO), for the toxicants that
# drive long-term ingestion risk in this setting
_RFD = {
    "arsenic": 3.0e-4,
    "fluoride": 0.06,
    "nitrate (as no3)": 1.6,
    "nitrite (as no2)": 0.1,
    "manganese": 0.14,
    "lead": 3.5e-3,
    "cadmium": 5.0e-4,
    "chromium (total)": 3.0e-3,
    "uranium": 3.0e-3,
    "nickel": 0.02,
    "copper": 0.04,
    "zinc": 0.3,
    "barium": 0.2,
    "selenium": 5.0e-3,
    "antimony": 4.0e-4,
}
# oral cancer slope factors, (mg/kg/day)^-1
_CANCER_SLOPE = {"arsenic": 1.5}

# The EPA IRIS reference doses for nitrate (1.6) and nitrite (0.1) are
# expressed as nitrogen (NO3-N / NO2-N), but the toolkit records nitrate and
# nitrite as the whole ion (as NO3 / as NO2). Convert the measured "as ion"
# concentration to a nitrogen basis before dividing by the RfD, else the
# hazard quotient is overstated by the mass ratio (NO3/N = 62/14 = 4.43,
# NO2/N = 46/14 = 3.29).
_AS_NITROGEN_FACTOR = {
    "nitrate (as no3)": 62.004 / 14.007,
    "nitrite (as no2)": 46.005 / 14.007,
}


@dataclass
class WaterQualityIndex:
    value: float
    rating: str
    n_parameters: int
    top_contributors: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class HealthRiskAssessment:
    hazard_index: float
    hazard_quotients: dict  # parameter -> HQ
    cancer_risk: Optional[float]  # lifetime, arsenic
    rating: str
    flags: list[DataFlag] = field(default_factory=list)


def _measured(sample: WaterQualitySample) -> dict[str, float]:
    values: dict[str, float] = {}
    for result in sample.results:
        if result.value is not None:
            values[normalise_parameter(result.parameter)] = float(result.value)
    return values


def _wqi_limit(entry: StandardEntry) -> Optional[Limit]:
    for limit in (entry.who_health, entry.who_aesthetic, entry.sl_standard):
        if limit is not None:
            return limit
    return None


def _wqi_rating(value: float) -> str:
    if value <= 50:
        return "Excellent"
    if value <= 100:
        return "Good"
    if value <= 200:
        return "Poor"
    if value <= 300:
        return "Very poor"
    return "Unsuitable for drinking"


def compute_wqi(sample: WaterQualitySample, standards_path=None) -> Optional[WaterQualityIndex]:
    """Weighted-arithmetic Water Quality Index over physico-chemical data.

    Returns None when fewer than three usable parameters are available.
    """
    table = load_standards(standards_path)
    values = _measured(sample)
    weight_sum = 0.0
    weighted_q = 0.0
    contributors: list[tuple[str, float]] = []
    n = 0
    for key, value in values.items():
        entry = table.get(key)
        if entry is None or entry.category == "microbiological":
            continue
        if key in _RFD:
            # Health-based trace toxicants (arsenic, lead, fluoride, nitrate,
            # ...) have tiny standards, so 1/s weighting and the value/s
            # sub-index let a single one dominate and drown out the general
            # chemistry this index is meant to summarise. They are reported
            # through the separate Hazard Index instead; excluding them keeps
            # the WQI a physico-chemical/acceptability measure as documented.
            continue
        limit = _wqi_limit(entry)
        if limit is None or not limit.maximum or limit.maximum <= 0:
            continue
        s_i = limit.maximum
        if key == "ph":
            ideal = 7.0
            denom = s_i - ideal
            q_i = 100.0 * abs(value - ideal) / denom if denom else 0.0
        else:
            q_i = 100.0 * value / s_i
        w_i = 1.0 / s_i
        weight_sum += w_i
        weighted_q += w_i * q_i
        contributors.append((entry.parameter, w_i * q_i))
        n += 1
    if n < 3 or weight_sum <= 0:
        return None
    wqi = weighted_q / weight_sum
    contributors.sort(key=lambda kv: kv[1], reverse=True)
    return WaterQualityIndex(
        value=round(wqi, 1),
        rating=_wqi_rating(wqi),
        n_parameters=n,
        top_contributors=[(name, round(c / weight_sum, 1)) for name, c in contributors[:3]],
    )


def assess_health_risk(sample: WaterQualitySample) -> Optional[HealthRiskAssessment]:
    """Non-carcinogenic Hazard Index and arsenic carcinogenic risk.

    Returns None when none of the scored toxicants were measured.
    """
    values = _measured(sample)
    hq: dict[str, float] = {}
    intake_factor = _INTAKE_L_PER_DAY / _BODY_WEIGHT_KG
    for key, rfd in _RFD.items():
        if key in values and rfd > 0:
            conc = values[key]
            factor = _AS_NITROGEN_FACTOR.get(key)
            if factor:
                conc = conc / factor  # the RfD is expressed as nitrogen
            cdi = conc * intake_factor  # mg/kg/day
            hq[key] = cdi / rfd
    if not hq:
        return None
    hazard_index = sum(hq.values())
    cancer_risk = None
    if "arsenic" in values:
        cdi_as = values["arsenic"] * intake_factor
        cancer_risk = cdi_as * _CANCER_SLOPE["arsenic"]

    flags: list[DataFlag] = []
    if hazard_index >= 1.0:
        worst = max(hq, key=hq.get)
        flags.append(
            DataFlag(
                "warning",
                "hazard_index",
                f"Non-carcinogenic Hazard Index {hazard_index:.1f} is at or above "
                f"1 (dominated by {worst}); chronic ingestion poses a potential "
                "health concern.",
            )
        )
    if cancer_risk is not None and cancer_risk > 1e-4:
        flags.append(
            DataFlag(
                "warning",
                "cancer_risk",
                f"Estimated lifetime arsenic cancer risk {cancer_risk:.1e} exceeds "
                "the 1e-4 screening level.",
            )
        )

    if hazard_index < 1.0:
        rating = "Acceptable (Hazard Index below 1)"
    elif hazard_index < 4.0:
        rating = "Elevated (Hazard Index at or above 1)"
    else:
        rating = "High (Hazard Index at or above 4)"

    return HealthRiskAssessment(
        hazard_index=round(hazard_index, 2),
        hazard_quotients={k: round(v, 2) for k, v in sorted(hq.items(), key=lambda kv: kv[1], reverse=True)},
        cancer_risk=cancer_risk,
        rating=rating,
        flags=flags,
    )
