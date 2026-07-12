"""Ionic balance check for major ion analyses.

The charge balance error is ``100 x (sum cations - sum anions) /
(sum cations + sum anions)`` in meq/L. Errors within 5 percent are
normal laboratory practice; 5 to 10 percent is flagged for review and
more than 10 percent indicates an unreliable analysis or a missing
major ion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import DataFlag, WaterQualitySample
from .standards import normalise_parameter

# meq per mg: charge / molar mass
_CATIONS = {
    "calcium": 2 / 40.078,
    "magnesium": 2 / 24.305,
    "sodium": 1 / 22.990,
    "potassium": 1 / 39.098,
    "iron": 2 / 55.845,  # ferrous, minor
    "manganese": 2 / 54.938,  # minor
}
_ANIONS = {
    "chloride": 1 / 35.453,
    "sulfate": 2 / 96.06,
    "bicarbonate": 1 / 61.017,
    "carbonate": 2 / 60.009,
    "nitrate (as no3)": 1 / 62.004,
    "fluoride": 1 / 18.998,
}

# the four majors on each side that make a balance meaningful
_REQUIRED_CATIONS = ("calcium", "magnesium", "sodium")
_REQUIRED_ANIONS = ("chloride", "bicarbonate")


@dataclass
class IonicBalanceResult:
    sum_cations_meq: float
    sum_anions_meq: float
    error_percent: float
    cations_meq: dict
    anions_meq: dict
    used_alkalinity_for_bicarbonate: bool
    flag: Optional[DataFlag]


def _value(sample: WaterQualitySample, key: str) -> Optional[float]:
    for result in sample.results:
        if normalise_parameter(result.parameter) == key:
            return result.value if result.value is not None else (
                0.0 if result.below_detection else None
            )
    return None


def ionic_balance(sample: WaterQualitySample) -> Optional[IonicBalanceResult]:
    """Compute the charge balance; returns None when the major ions are
    not sufficiently covered by the analysis."""
    cations: dict[str, float] = {}
    anions: dict[str, float] = {}

    for key, factor in _CATIONS.items():
        value = _value(sample, key)
        if value is not None:
            cations[key] = value * factor

    used_alk = False
    for key, factor in _ANIONS.items():
        value = _value(sample, key)
        if value is not None:
            anions[key] = value * factor
    if "bicarbonate" not in anions:
        alk = _value(sample, "alkalinity")
        if alk is not None:
            # alkalinity as CaCO3 -> bicarbonate equivalent: meq = mg/L / 50.04
            anions["bicarbonate"] = alk / 50.04
            used_alk = True

    if not all(k in cations for k in _REQUIRED_CATIONS) or not all(
        k in anions for k in _REQUIRED_ANIONS
    ):
        return None

    total_cat = sum(cations.values())
    total_an = sum(anions.values())
    if total_cat + total_an <= 0:
        return None
    error = 100.0 * (total_cat - total_an) / (total_cat + total_an)

    flag = None
    if abs(error) > 10:
        flag = DataFlag(
            "error",
            "ionic_balance",
            f"Charge balance error {error:+.1f}% exceeds 10%; the analysis is "
            "unreliable or a major ion is missing.",
        )
    elif abs(error) > 5:
        flag = DataFlag(
            "warning",
            "ionic_balance",
            f"Charge balance error {error:+.1f}% is between 5% and 10%; review "
            "the laboratory analysis.",
        )
    return IonicBalanceResult(
        sum_cations_meq=total_cat,
        sum_anions_meq=total_an,
        error_percent=error,
        cations_meq=cations,
        anions_meq=anions,
        used_alkalinity_for_bicarbonate=used_alk,
        flag=flag,
    )
