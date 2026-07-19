"""Compare laboratory results against WHO and national standards."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models import DataFlag, WaterQualitySample
from .corrosivity import CorrosivityAssessment, assess_corrosivity
from .ionic import IonicBalanceResult, ionic_balance
from .standards import StandardEntry, load_standards, normalise_parameter

# status codes, ordered by severity for the summary
STATUS_ORDER = [
    "exceeds_health",
    "exceeds_national",
    "exceeds_aesthetic",
    "within_limits",
    "below_detection",
    "no_guideline",
    "not_measured",
]


@dataclass
class ParameterAssessment:
    parameter: str
    value: Optional[float]
    unit: str
    below_detection: bool
    who_health: str
    who_aesthetic: str
    sl_standard: str
    status: str
    remark: str


@dataclass
class WaterQualityAssessment:
    sample: WaterQualitySample
    rows: list[ParameterAssessment]
    ionic: Optional[IonicBalanceResult]
    corrosivity: Optional[CorrosivityAssessment] = None
    flags: list[DataFlag] = field(default_factory=list)

    @property
    def health_exceedances(self) -> list[ParameterAssessment]:
        return [r for r in self.rows if r.status == "exceeds_health"]

    @property
    def aesthetic_exceedances(self) -> list[ParameterAssessment]:
        return [r for r in self.rows if r.status in ("exceeds_aesthetic", "exceeds_national")]

    @property
    def verdict(self) -> str:
        """One line suitability statement for reports."""
        health = self.health_exceedances
        aesthetic = self.aesthetic_exceedances
        if health:
            names = ", ".join(r.parameter for r in health)
            return (
                "The water does not meet the health based guideline value(s) "
                f"for: {names}. Treatment or an alternative source is required "
                "before the water is used for drinking."
            )
        if aesthetic:
            names = ", ".join(r.parameter for r in aesthetic)
            return (
                "The water meets all health based guideline values. "
                f"Acceptability (aesthetic) limits are exceeded for: {names}. "
                "The water is usable for drinking, although taste, odour or "
                "staining complaints may arise; simple treatment is advisable."
            )
        return (
            "All measured parameters comply with the WHO guideline values and "
            "the national standard limits applied. The water is suitable for "
            "drinking on the basis of the parameters tested."
        )


def assess_sample(
    sample: WaterQualitySample,
    standards_path: str | Path | None = None,
) -> WaterQualityAssessment:
    """Assess every result in a sample against the standards table."""
    table = load_standards(standards_path)
    rows: list[ParameterAssessment] = []
    flags: list[DataFlag] = list(sample.flags)

    for result in sample.results:
        key = normalise_parameter(result.parameter)
        entry: StandardEntry | None = table.get(key)
        who_h = str(entry.who_health) if entry and entry.who_health else ""
        who_a = str(entry.who_aesthetic) if entry and entry.who_aesthetic else ""
        sl = str(entry.sl_standard) if entry and entry.sl_standard else ""

        if result.value is None and not result.below_detection:
            status, remark = "not_measured", "no value reported"
        elif result.below_detection and result.value is None:
            status, remark = "below_detection", (
                f"below detection limit ({result.detection_limit:g})"
                if result.detection_limit is not None
                else "below detection limit"
            )
        elif entry is None:
            status, remark = "no_guideline", "parameter not in the standards table"
            flags.append(
                DataFlag(
                    "info",
                    "unknown_parameter",
                    f"No guideline entry for '{result.parameter}'; add it to the "
                    "standards CSV if a limit applies.",
                )
            )
        else:
            value = float(result.value)
            if entry.who_health and entry.who_health.exceeded_by(value):
                status = "exceeds_health"
                remark = f"exceeds the WHO health based guideline ({entry.who_health})"
            elif entry.sl_standard and entry.sl_standard.exceeded_by(value):
                status = "exceeds_national"
                remark = f"exceeds the national standard limit ({entry.sl_standard})"
            elif entry.who_aesthetic and entry.who_aesthetic.exceeded_by(value):
                status = "exceeds_aesthetic"
                remark = f"exceeds the WHO acceptability value ({entry.who_aesthetic})"
            elif not (entry.who_health or entry.who_aesthetic or entry.sl_standard):
                status, remark = "no_guideline", entry.note or "no guideline value"
            else:
                status, remark = "within_limits", ""

        rows.append(
            ParameterAssessment(
                parameter=result.parameter,
                value=result.value,
                unit=result.unit or (entry.unit if entry else ""),
                below_detection=result.below_detection,
                who_health=who_h,
                who_aesthetic=who_a,
                sl_standard=sl,
                status=status,
                remark=remark,
            )
        )

    # WHO combined nitrate + nitrite rule: the sum of the ratio of each to
    # its own guideline value must not exceed 1. A sample can pass both
    # single-parameter checks yet fail this combined limit, so it is applied
    # only when neither ion is individually in exceedance (the individual
    # exceedance is already reported on its own row).
    combined = _nitrate_nitrite_index(sample, table)
    if combined is not None:
        ratio, no3, no2, gv3, gv2 = combined
        if ratio > 1.0 and no3 <= gv3 and no2 <= gv2:
            rows.append(
                ParameterAssessment(
                    parameter="Nitrate + nitrite (combined)",
                    value=round(ratio, 2),
                    unit="ratio",
                    below_detection=False,
                    who_health="<= 1",
                    who_aesthetic="",
                    sl_standard="",
                    status="exceeds_health",
                    remark=(
                        f"The combined index ({no3:g}/{gv3:g} + {no2:g}/{gv2:g} "
                        f"= {ratio:.2f}) exceeds 1; the WHO combined nitrate and "
                        "nitrite limit is not met even though each is within its "
                        "own guideline value."
                    ),
                )
            )
            flags.append(
                DataFlag(
                    "warning",
                    "nitrate_nitrite_combined",
                    "Combined nitrate + nitrite index exceeds 1 (WHO); treat as "
                    "a health exceedance.",
                )
            )

    ionic = ionic_balance(sample)
    if ionic is not None and ionic.flag is not None:
        flags.append(ionic.flag)

    corrosivity = assess_corrosivity(sample)
    flags.extend(corrosivity.flags)

    assessment = WaterQualityAssessment(
        sample=sample, rows=rows, ionic=ionic, corrosivity=corrosivity, flags=flags
    )
    return assessment


def _nitrate_nitrite_index(sample, table):
    """The WHO combined nitrate + nitrite index, if both are measured.

    Returns ``(ratio, no3, no2, gv3, gv2)`` where ``ratio`` is
    ``no3/gv3 + no2/gv2``, or ``None`` when either value or guideline is
    missing.
    """

    def _value_and_gv(key):
        entry = table.get(key)
        gv = entry.who_health.maximum if entry and entry.who_health else None
        for result in sample.results:
            if (
                normalise_parameter(result.parameter) == key
                and result.value is not None
            ):
                return float(result.value), gv
        return None, gv

    no3, gv3 = _value_and_gv("nitrate (as no3)")
    no2, gv2 = _value_and_gv("nitrite (as no2)")
    if no3 is None or no2 is None or not gv3 or not gv2:
        return None
    return no3 / gv3 + no2 / gv2, no3, no2, gv3, gv2
