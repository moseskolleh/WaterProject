"""Compare laboratory results against WHO and national standards.

The assessment is deliberately fail-closed. A drinking water verdict is a
statement someone acts on - a village drinks the water, a certificate is
issued - so this module says "suitable" only when it can show the work, and
says so plainly when it cannot:

* Values are converted onto the unit each guideline is written in before
  they are compared. An arsenic result of 5 ug/L is a fifth of the WHO
  guideline; compared as though it were 5 mg/L it is five hundred times
  over it, and the same arithmetic in the other direction certifies unsafe
  water as safe. A unit that cannot be read, or that measures something
  else, makes the row indeterminate rather than pass.
* A "below detection" result only proves compliance when the detection
  limit is at or under the limit it is being checked against. A laboratory
  reporting "< 0.05 mg/L" for arsenic has not shown the water meets the
  0.01 mg/L guideline; it has shown its method cannot see the guideline.
* A parameter the standards table does not know is an unresolved question,
  not an absence of one, and it keeps the sample out of "suitable".
* A sample with nothing evaluable in it - no results, or none that could be
  graded - is indeterminate. Silence is not a pass.
* Naming water suitable for drinking also needs the health panel to have
  been run at all: E. coli, arsenic, fluoride and nitrate
  (:data:`ESSENTIAL_HEALTH_PARAMETERS`). Without them the sample cannot
  speak to the risks that matter most in a rural Sierra Leone borehole.

One deliberate exception: a result carrying no unit at all is read in the
guideline's own unit, because that is the only reading under which the
number means anything, and an info flag records the assumption. A result
carrying the *wrong* unit is the dangerous case, and that one is caught.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..models import DataFlag, WaterQualitySample
from .corrosivity import CorrosivityAssessment, assess_corrosivity
from .indices import (
    HealthRiskAssessment,
    WaterQualityIndex,
    assess_health_risk,
    compute_wqi,
)
from .ionic import IonicBalanceResult, ionic_balance
from .standards import (
    StandardEntry,
    load_standards,
    normalise_parameter,
    to_standard_unit,
)

# status codes, ordered by severity for the summary
STATUS_ORDER = [
    "exceeds_health",
    "exceeds_national",
    "exceeds_aesthetic",
    "indeterminate",
    "within_limits",
    "below_detection",
    "no_guideline",
    "not_measured",
]

#: How each row status reads in a table. Kept here rather than in the report
#: writer so the app, the browser engine and the DOCX all print one wording -
#: a row the toolkit could not grade must never surface as a raw machine code
#: in a client-facing document.
STATUS_LABELS = {
    "within_limits": "Complies",
    "exceeds_health": "EXCEEDS HEALTH GUIDELINE",
    "exceeds_national": "Exceeds national/adopted limit",
    "exceeds_aesthetic": "Exceeds acceptability value",
    "indeterminate": "NOT EVALUABLE",
    "below_detection": "Below detection",
    "no_guideline": "No guideline value",
    "not_measured": "Not measured",
}

#: Verdict states, worst first. ``indeterminate`` sits above ``aesthetic``
#: because "usable for drinking" is a claim, and an open question defeats a
#: claim; it sits below the two failures because a demonstrated exceedance
#: is a finding, and uncertainty elsewhere does not soften it.
VERDICT_ORDER = ["health_fail", "national_fail", "indeterminate", "aesthetic", "pass"]

#: Short and long labels for each verdict state, shared by the app, the
#: portfolio table and the reports so one wording is used everywhere.
VERDICT_SHORT = {
    "health_fail": "Treat before use",
    "national_fail": "Fails national limit",
    "indeterminate": "Not proven safe",
    "aesthetic": "Aesthetic only",
    "pass": "Safe",
}
VERDICT_LONG = {
    "health_fail": "Treat before use",
    "national_fail": "Fails the national standard",
    "indeterminate": "Not proven safe - incomplete or unevaluable results",
    "aesthetic": "Aesthetic issues only",
    "pass": "Safe to drink",
}

#: One sentence per state, for report prose. Reports used to choose between
#: "requires treatment" and "suitable for drinking" on the health exceedances
#: alone, so a national breach or an unevaluable panel read as suitable.
SUITABILITY_SENTENCE = {
    "health_fail": "The water requires treatment before drinking.",
    "national_fail": (
        "The water meets the WHO health based guideline values but does not "
        "comply with the national standard; treatment is required before the "
        "supply is accepted."
    ),
    "indeterminate": (
        "The water has not been shown to be suitable for drinking: the results "
        "are incomplete or could not be evaluated."
    ),
    "aesthetic": (
        "The water is suitable for drinking on the parameters tested, with "
        "acceptability (taste, odour or staining) reservations."
    ),
    "pass": "The water is suitable for drinking on the parameters tested.",
}

#: The same, phrased to follow "Water safety: ".
SUITABILITY_PHRASE = {
    "health_fail": "treatment required before drinking.",
    "national_fail": "does not comply with the national standard; treatment required.",
    "indeterminate": "not established - results incomplete or unevaluable.",
    "aesthetic": "suitable on the parameters tested; acceptability reservations.",
    "pass": "suitable for drinking on the parameters tested.",
}

#: The health panel a verdict of "suitable for drinking" requires. E. coli is
#: the direct indicator of faecal contamination; arsenic and fluoride are the
#: geogenic risks that make otherwise clear, pleasant groundwater unsafe over
#: years; nitrate is the latrine and agricultural one. A sample missing any of
#: them cannot support the claim, however clean everything else looks.
ESSENTIAL_HEALTH_PARAMETERS = (
    "e. coli",
    "arsenic",
    "fluoride",
    "nitrate (as no3)",
)

#: Other table keys that answer the same health question: a laboratory that
#: reports nitrate as nitrogen has measured the nitrate.
ESSENTIAL_EQUIVALENTS = {
    "nitrate (as no3)": ("nitrate (as n)",),
}

#: Machine codes explaining why a row could not be graded.
INDETERMINATE_REASONS = {
    "unit_unreadable": "the reported unit could not be read",
    "unit_mismatch": "the reported unit measures something other than the guideline",
    "detection_limit_above_guideline": (
        "the detection limit is above the limit being checked"
    ),
    "detection_limit_unknown": "the detection limit was not reported",
    "unknown_parameter": "the parameter is not in the standards table",
    "unit_basis_conflict": (
        "the unit names a different chemical basis from the parameter"
    ),
}


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
    #: The unit the guideline values are written in.
    guideline_unit: str = ""
    #: The value actually compared, in ``guideline_unit``. ``None`` when the
    #: row could not be converted, which is never the same as zero.
    value_in_guideline_unit: Optional[float] = None
    #: As reported by the laboratory, in the reported unit.
    detection_limit: Optional[float] = None
    #: Whether the row could be graded against the limits that apply to it.
    evaluable: bool = True
    #: A code from :data:`INDETERMINATE_REASONS`, ``"unit_assumed"``, or "".
    reason: str = ""


@dataclass
class WaterQualityAssessment:
    sample: WaterQualitySample
    rows: list[ParameterAssessment]
    ionic: Optional[IonicBalanceResult]
    corrosivity: Optional[CorrosivityAssessment] = None
    wqi: Optional[WaterQualityIndex] = None
    health_risk: Optional[HealthRiskAssessment] = None
    flags: list[DataFlag] = field(default_factory=list)
    #: Parameters from :data:`ESSENTIAL_HEALTH_PARAMETERS` that the sample
    #: does not carry an evaluable result for.
    missing_essential: list[str] = field(default_factory=list)

    @property
    def health_exceedances(self) -> list[ParameterAssessment]:
        return [r for r in self.rows if r.status == "exceeds_health"]

    @property
    def aesthetic_exceedances(self) -> list[ParameterAssessment]:
        """Parameters over an acceptability limit only.

        National exceedances are deliberately *not* included. A national
        limit is law; folding it in here reported a compliance failure as a
        matter of taste and let a breached supply show a 100% pass rate.
        Use :attr:`all_exceedances` when every exceedance is wanted.
        """
        return [r for r in self.rows if r.status == "exceeds_aesthetic"]

    @property
    def national_exceedances(self) -> list[ParameterAssessment]:
        """Parameters over the national standard but inside the WHO health GV."""
        return [r for r in self.rows if r.status == "exceeds_national"]

    @property
    def all_exceedances(self) -> list[ParameterAssessment]:
        """Every exceedance, worst first: health, then national, then aesthetic."""
        return (
            self.health_exceedances
            + self.national_exceedances
            + self.aesthetic_exceedances
        )

    @property
    def indeterminate_rows(self) -> list[ParameterAssessment]:
        """Rows that were measured but could not be graded."""
        return [r for r in self.rows if r.status == "indeterminate"]

    @property
    def unknown_parameters(self) -> list[ParameterAssessment]:
        """Determinands the standards table does not recognise."""
        return [r for r in self.rows if r.reason == "unknown_parameter"]

    @property
    def evaluated_rows(self) -> list[ParameterAssessment]:
        """Rows that were actually graded against a limit."""
        return [
            r
            for r in self.rows
            if r.evaluable
            and r.status
            in (
                "exceeds_health",
                "exceeds_national",
                "exceeds_aesthetic",
                "within_limits",
                "below_detection",
            )
        ]

    @property
    def uncertainties(self) -> list[str]:
        """Every reason this sample cannot support a "suitable" verdict.

        Empty means nothing is unresolved; the verdict then rests only on
        what the limits say.
        """
        reasons: list[str] = []
        if not self.rows:
            reasons.append("the sample carries no laboratory results")
        elif not self.evaluated_rows:
            reasons.append(
                "no result in the sample could be graded against a guideline value"
            )
        for row in self.indeterminate_rows:
            why = INDETERMINATE_REASONS.get(row.reason, "it could not be evaluated")
            reasons.append(f"{row.parameter} could not be assessed: {why}")
        for row in self.unknown_parameters:
            reasons.append(
                f"{row.parameter} has no entry in the standards table, so it "
                "was not checked against any limit"
            )
        if self.missing_essential:
            reasons.append(
                "the health panel is incomplete: no evaluable result for "
                + ", ".join(self.missing_essential)
            )
        return reasons

    @property
    def verdict_state(self) -> str:
        """One of :data:`VERDICT_ORDER`, worst applicable first."""
        if self.health_exceedances:
            return "health_fail"
        if self.national_exceedances:
            return "national_fail"
        if self.uncertainties:
            return "indeterminate"
        if self.aesthetic_exceedances:
            return "aesthetic"
        return "pass"

    @property
    def is_potable(self) -> Optional[bool]:
        """``True`` safe, ``False`` not safe, ``None`` not established.

        ``None`` is the honest answer for an incomplete or unevaluable
        sample and must never be collapsed into ``True``.
        """
        state = self.verdict_state
        if state in ("health_fail", "national_fail"):
            return False
        if state == "indeterminate":
            return None
        return True

    @property
    def verdict(self) -> str:
        """One line suitability statement for reports."""
        state = self.verdict_state
        health = self.health_exceedances
        national = self.national_exceedances
        acceptability = self.aesthetic_exceedances

        if state == "health_fail":
            names = ", ".join(r.parameter for r in health)
            return (
                "The water does not meet the health based guideline value(s) "
                f"for: {names}. Treatment or an alternative source is required "
                "before the water is used for drinking."
            )
        if state == "national_fail":
            # A national limit can be stricter than, or exist without, a WHO
            # health value - it is a legal compliance failure, not a matter of
            # taste, so it must not be reported as merely aesthetic.
            names = ", ".join(r.parameter for r in national)
            extra = (
                " Acceptability limits are also exceeded for: "
                + ", ".join(r.parameter for r in acceptability)
                + "."
                if acceptability
                else ""
            )
            return (
                "The water meets the WHO health based guideline values, but "
                f"does not comply with the national standard limit(s) for: "
                f"{names}.{extra} Treatment is required before the supply can "
                "be accepted against the national standard; check whether the "
                "limit exceeded is a health or an acceptability limit."
            )
        if state == "indeterminate":
            reasons = "; ".join(self.uncertainties)
            extra = (
                " Acceptability limits are exceeded for: "
                + ", ".join(r.parameter for r in acceptability)
                + "."
                if acceptability
                else ""
            )
            return (
                "The water cannot be declared suitable for drinking on these "
                f"results: {reasons}.{extra} Resolve the outstanding "
                "parameters - re-sample, or ask the laboratory for the units "
                "and detection limits used - before the supply is signed off."
            )
        if state == "aesthetic":
            names = ", ".join(r.parameter for r in acceptability)
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


def _limit_maximums(entry: StandardEntry) -> list[float]:
    """Every upper limit that applies to a parameter, in the guideline unit."""
    out = []
    for limit in (entry.who_health, entry.sl_standard, entry.who_aesthetic):
        if limit is not None and limit.maximum is not None:
            out.append(limit.maximum)
    return out


#: Shared with the aggregate indices, so one conversion rule serves the row
#: comparison, the WQI, the hazard index, the ionic balance and corrosivity.
_convert_to_guideline_unit = to_standard_unit


def _assess_result(result, entry: Optional[StandardEntry]) -> ParameterAssessment:
    """Grade one laboratory result against its guideline entry."""
    who_h = str(entry.who_health) if entry and entry.who_health else ""
    who_a = str(entry.who_aesthetic) if entry and entry.who_aesthetic else ""
    sl = str(entry.sl_standard) if entry and entry.sl_standard else ""
    guideline_unit = entry.unit if entry else ""

    row = ParameterAssessment(
        parameter=result.parameter,
        value=result.value,
        unit=result.unit or guideline_unit,
        below_detection=result.below_detection,
        who_health=who_h,
        who_aesthetic=who_a,
        sl_standard=sl,
        status="not_measured",
        remark="no value reported",
        guideline_unit=guideline_unit,
        detection_limit=result.detection_limit,
    )

    if result.value is None and not result.below_detection:
        return row

    if entry is None:
        # An unrecognised determinand is an open question, not a clean bill.
        row.status = "no_guideline"
        row.reason = "unknown_parameter"
        row.evaluable = False
        row.remark = (
            "parameter not in the standards table, so it was not checked "
            "against any limit"
        )
        return row

    limits = _limit_maximums(entry)

    if result.below_detection and result.value is None:
        return _assess_below_detection(row, result, entry, limits)

    converted, reason = _convert_to_guideline_unit(
        float(result.value), result.unit, entry
    )
    if converted is None:
        row.status = "indeterminate"
        row.evaluable = False
        row.reason = reason
        row.remark = (
            f"reported in '{result.unit}' but the guideline is in "
            f"'{guideline_unit}': {INDETERMINATE_REASONS[reason]}. The value "
            "was not compared against any limit."
        )
        return row

    row.value_in_guideline_unit = converted
    row.reason = reason
    if reason == "unit_assumed":
        unit_note = f" (read as {guideline_unit}; the reported unit was '{result.unit}')" \
            if result.unit else f" (read as {guideline_unit}; no unit was reported)"
    elif converted != result.value:
        unit_note = (
            f" ({result.value:g} {result.unit} = {converted:g} {guideline_unit})"
        )
    else:
        unit_note = ""
    _grade(row, entry, converted, unit_note)
    return row


def _assess_below_detection(
    row: ParameterAssessment, result, entry: StandardEntry, limits: list[float]
) -> ParameterAssessment:
    """A "< X" result proves compliance only when X is under the limit."""
    if not limits:
        row.status = "below_detection"
        row.remark = (
            f"below detection limit ({result.detection_limit:g})"
            if result.detection_limit is not None
            else "below detection limit"
        )
        return row

    strictest = min(limits)
    microbiological = entry.category == "microbiological"
    if microbiological and result.detection_limit is None:
        # "Absent", "ND", "not detected": the count found nothing in the
        # sample, which for a guideline of "not detectable in any 100 mL
        # sample" is the guideline being met, not an unknown
        row.status = "below_detection"
        row.remark = (
            "reported not detected; the guideline is met provided the "
            "laboratory examined a 100 mL sample"
        )
        return row
    if result.detection_limit is None:
        row.status = "indeterminate"
        row.evaluable = False
        row.reason = "detection_limit_unknown"
        row.remark = (
            "reported below the detection limit, but the limit itself was not "
            f"reported, so compliance with {strictest:g} {entry.unit} cannot "
            "be shown. Ask the laboratory for the detection limit."
        )
        return row

    dl, reason = _convert_to_guideline_unit(
        float(result.detection_limit), result.unit, entry
    )
    if dl is None:
        row.status = "indeterminate"
        row.evaluable = False
        row.reason = reason
        row.remark = (
            f"reported below a detection limit of {result.detection_limit:g} "
            f"'{result.unit}', which cannot be compared with the guideline in "
            f"'{entry.unit}': {INDETERMINATE_REASONS[reason]}."
        )
        return row

    row.value_in_guideline_unit = None
    if microbiological and dl <= 1.0:
        # A membrane-filtration count cannot resolve below one colony per
        # volume filtered, so "<1 CFU/100 mL" is exactly what "not
        # detectable in any 100 mL sample" looks like on a certificate.
        # Refusing it as a detection limit above zero made the documented
        # way of transcribing a clean E. coli result "not proven safe".
        row.status = "below_detection"
        row.remark = (
            f"not detected in a 100 mL sample (reported as <{dl:g} {entry.unit})"
        )
        return row
    if dl > strictest:
        row.status = "indeterminate"
        row.evaluable = False
        row.reason = "detection_limit_above_guideline"
        row.remark = (
            f"below a detection limit of {dl:g} {entry.unit}, which is above "
            f"the limit of {strictest:g} {entry.unit}. The method cannot see "
            "the guideline value, so the result does not show compliance; "
            "re-test with a more sensitive method."
        )
        return row

    row.status = "below_detection"
    row.remark = (
        f"below detection limit ({dl:g} {entry.unit}), which is at or under "
        f"the limit of {strictest:g} {entry.unit}"
    )
    return row


def _grade(
    row: ParameterAssessment, entry: StandardEntry, value: float, unit_note: str
) -> None:
    """Apply the limit hierarchy to a converted value."""
    is_micro = (entry.category or "").strip().lower() == "microbiological"
    if entry.who_health and entry.who_health.exceeded_by(value):
        row.status = "exceeds_health"
        row.remark = (
            f"exceeds the WHO health based guideline ({entry.who_health})"
            f"{unit_note}"
        )
    elif is_micro and (
        (entry.sl_standard and entry.sl_standard.exceeded_by(value))
        or (entry.who_aesthetic and entry.who_aesthetic.exceeded_by(value))
    ):
        # A microbiological indicator (E. coli, total coliforms) is a health
        # concern, never an aesthetic one, even when its limit happens to be
        # carried in the national/acceptability column rather than the
        # WHO-health column. Treat any detection above the limit as a health
        # exceedance so the verdict never calls faecally-indicated water
        # "usable for drinking".
        row.status = "exceeds_health"
        limit = entry.sl_standard or entry.who_aesthetic
        row.remark = (
            f"microbiological indicator detected above the limit ({limit}); "
            f"a health (faecal contamination) concern, not aesthetic{unit_note}"
        )
    elif entry.sl_standard and entry.sl_standard.exceeded_by(value):
        if entry.who_health:
            # WHO sets a health value and the national limit is stricter:
            # failing it is a compliance failure, not a matter of taste, and
            # must not be reported as aesthetic.
            row.status = "exceeds_national"
            row.remark = (
                f"exceeds the national standard limit ({entry.sl_standard}), "
                f"which is stricter than the WHO health based guideline "
                f"({entry.who_health}){unit_note}"
            )
        else:
            # No WHO health value exists for this parameter, so the national
            # limit is an acceptability one (iron staining, chloride taste,
            # turbidity).
            row.status = "exceeds_aesthetic"
            row.remark = (
                f"exceeds the national acceptability limit "
                f"({entry.sl_standard}){unit_note}"
            )
    elif entry.who_aesthetic and entry.who_aesthetic.exceeded_by(value):
        row.status = "exceeds_aesthetic"
        row.remark = (
            f"exceeds the WHO acceptability value ({entry.who_aesthetic})"
            f"{unit_note}"
        )
    elif not (entry.who_health or entry.who_aesthetic or entry.sl_standard):
        row.status = "no_guideline"
        row.remark = entry.note or "no guideline value"
    else:
        row.status = "within_limits"
        row.remark = unit_note.strip() if unit_note else ""


def _missing_essential(rows: list[ParameterAssessment], table: dict) -> list[str]:
    """Essential health parameters with no evaluable result in the sample."""
    graded = {
        normalise_parameter(r.parameter)
        for r in rows
        if r.evaluable
        and r.status
        in (
            "exceeds_health",
            "exceeds_national",
            "exceeds_aesthetic",
            "within_limits",
            "below_detection",
        )
    }
    missing = []
    for key in ESSENTIAL_HEALTH_PARAMETERS:
        if key in graded or any(alt in graded for alt in ESSENTIAL_EQUIVALENTS.get(key, ())):
            continue
        entry = table.get(key)
        missing.append(entry.parameter if entry is not None else key)
    return missing


def assess_sample(
    sample: WaterQualitySample,
    standards_path: str | Path | None = None,
) -> WaterQualityAssessment:
    """Assess every result in a sample against the standards table."""
    table = load_standards(standards_path)
    rows: list[ParameterAssessment] = []
    flags: list[DataFlag] = list(sample.flags)

    for result in sample.results:
        entry = table.get(normalise_parameter(result.parameter))
        row = _assess_result(result, entry)
        rows.append(row)

        if row.reason == "unknown_parameter":
            flags.append(
                DataFlag(
                    "warning",
                    "unknown_parameter",
                    f"No guideline entry for '{result.parameter}'; it was not "
                    "checked against any limit and keeps the sample out of a "
                    "'suitable for drinking' verdict. Add it to the standards "
                    "CSV if a limit applies.",
                )
            )
        elif row.reason == "unit_assumed":
            flags.append(
                DataFlag(
                    "info",
                    "unit_not_reported",
                    f"'{result.parameter}' carries no usable unit"
                    + (f" ('{result.unit}')" if result.unit else "")
                    + f"; it was read as {row.guideline_unit}. Confirm against "
                    "the laboratory certificate.",
                )
            )
        elif row.reason == "unit_basis_assumed":
            flags.append(
                DataFlag(
                    "warning",
                    "unit_basis_assumed",
                    f"'{result.parameter}' is reported in '{result.unit}' but "
                    f"the guideline is written in '{row.guideline_unit}'. The "
                    "values were taken as the same basis; confirm with the "
                    "laboratory, since an 'as CaCO3' figure is about 2.5 times "
                    "the same concentration expressed as the element.",
                )
            )
        elif row.status == "indeterminate":
            flags.append(
                DataFlag(
                    "error",
                    f"indeterminate_{row.reason}",
                    f"'{result.parameter}' could not be assessed: {row.remark}",
                )
            )

    # WHO combined nitrate + nitrite rule: the sum of the ratio of each to
    # its own guideline value must not exceed 1. A sample can pass both
    # single-parameter checks yet fail this combined limit, so it is applied
    # only when neither ion is individually in exceedance (the individual
    # exceedance is already reported on its own row).
    combined = _nitrate_nitrite_index(rows, table)
    if combined is not None:
        ratio, no3, no2, gv3, gv2, bounded = combined
        if ratio > 1.0 and no3 <= gv3 and no2 <= gv2:
            # A bounded index is an upper bound, not a measurement: it says
            # the rule *may* be breached, which is a question rather than a
            # finding, so it is reported as indeterminate rather than as a
            # health exceedance the laboratory never demonstrated.
            rows.append(
                ParameterAssessment(
                    parameter="Nitrate + nitrite (combined)",
                    value=round(ratio, 2),
                    unit="ratio",
                    below_detection=False,
                    who_health="<= 1",
                    who_aesthetic="",
                    sl_standard="",
                    status="indeterminate" if bounded else "exceeds_health",
                    remark=(
                        f"An upper bound on the combined index "
                        f"({no3:g}/{gv3:g} + {no2:g}/{gv2:g} = {ratio:.2f}) "
                        "exceeds 1, taking the below-detection component at "
                        "its detection limit. The WHO combined nitrate and "
                        "nitrite limit cannot be shown to be met; ask the "
                        "laboratory for a lower detection limit."
                        if bounded else
                        f"The combined index ({no3:g}/{gv3:g} + {no2:g}/{gv2:g} "
                        f"= {ratio:.2f}) exceeds 1; the WHO combined nitrate and "
                        "nitrite limit is not met even though each is within its "
                        "own guideline value."
                    ),
                    guideline_unit="ratio",
                    value_in_guideline_unit=None if bounded else round(ratio, 2),
                    evaluable=not bounded,
                    reason="detection_limit_above_guideline" if bounded else "",
                )
            )
            flags.append(
                DataFlag(
                    "warning" if bounded else "warning",
                    "nitrate_nitrite_combined_unproven" if bounded
                    else "nitrate_nitrite_combined",
                    "The combined nitrate + nitrite index cannot be shown to "
                    "meet the WHO limit: one component is below detection and "
                    "its detection limit is high enough that the sum may "
                    "exceed 1."
                    if bounded else
                    "Combined nitrate + nitrite index exceeds 1 (WHO); treat as "
                    "a health exceedance.",
                )
            )

    missing_essential = _missing_essential(rows, table)
    if missing_essential:
        flags.append(
            DataFlag(
                "warning",
                "incomplete_health_panel",
                "No evaluable result for " + ", ".join(missing_essential) + ". "
                "The sample cannot show the water is safe to drink until the "
                "health panel is complete.",
            )
        )
    if not [r for r in rows if r.evaluable and r.status != "not_measured"]:
        flags.append(
            DataFlag(
                "error",
                "nothing_evaluable",
                "No result in this sample could be graded against a guideline "
                "value, so no suitability verdict can be given.",
            )
        )

    ionic = ionic_balance(sample)
    if ionic is not None and ionic.flag is not None:
        flags.append(ionic.flag)

    corrosivity = assess_corrosivity(sample)
    flags.extend(corrosivity.flags)

    wqi = compute_wqi(sample, standards_path)
    health_risk = assess_health_risk(sample)
    if health_risk is not None:
        flags.extend(health_risk.flags)

    return WaterQualityAssessment(
        sample=sample,
        rows=rows,
        ionic=ionic,
        corrosivity=corrosivity,
        wqi=wqi,
        health_risk=health_risk,
        flags=flags,
        missing_essential=missing_essential,
    )


def _nitrate_nitrite_index(rows: list[ParameterAssessment], table):
    """The WHO combined nitrate + nitrite index.

    Returns ``(ratio, no3, no2, gv3, gv2, bounded)`` where ``ratio`` is
    ``no3/gv3 + no2/gv2``, or ``None`` when a value or guideline is missing
    altogether. Both concentrations are the unit-converted ones, so a result
    reported in ug/L is not silently added as though it were mg/L.

    A component reported below detection is taken at its detection limit,
    and ``bounded`` says so. That reading is deliberately the pessimistic
    one: "< 3 mg/L nitrite" beside 49 mg/L nitrate cannot rule out a
    combined index of 1.98, and treating the unknown as zero turned a
    sample that might fail the rule into one that passed it silently.
    """

    def _value_and_gv(key):
        entry = table.get(key)
        gv = entry.who_health.maximum if entry and entry.who_health else None
        for row in rows:
            if normalise_parameter(row.parameter) != key:
                continue
            if row.value_in_guideline_unit is not None:
                return float(row.value_in_guideline_unit), gv, False
            if row.below_detection and entry is not None:
                dl, reason = to_standard_unit(
                    float(row.detection_limit), row.unit, entry
                ) if row.detection_limit is not None else (None, "")
                if dl is not None:
                    return float(dl), gv, True
                return None, gv, False
        return None, gv, False

    no3, gv3, b3 = _value_and_gv("nitrate (as no3)")
    no2, gv2, b2 = _value_and_gv("nitrite (as no2)")
    if no3 is None or no2 is None or not gv3 or not gv2:
        return None
    return no3 / gv3 + no2 / gv2, no3, no2, gv3, gv2, (b3 or b2)
