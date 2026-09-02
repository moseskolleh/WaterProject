"""The drinking-water verdict, and the cases where it must refuse to say "safe".

A verdict of "suitable for drinking" is something a village acts on. Every
test here names a way the assessment used to say it when it had no business
saying it - an empty sample, a determinand nobody could identify, a
detection limit that cannot see the guideline value, a health panel that was
never run.
"""

from __future__ import annotations

import pytest

from groundwater.models import (
    SiteMetadata,
    WaterQualityResult,
    WaterQualitySample,
)
from groundwater.quality import ESSENTIAL_HEALTH_PARAMETERS, assess_sample


def _sample(*results: WaterQualityResult) -> WaterQualitySample:
    return WaterQualitySample(site=SiteMetadata(community="Test"), results=list(results))


def _health_panel() -> list[WaterQualityResult]:
    """Clean results for the panel a "suitable" verdict requires."""
    return [
        WaterQualityResult("E. coli", 0.0, "CFU/100 mL"),
        WaterQualityResult("Arsenic", 0.001, "mg/L"),
        WaterQualityResult("Fluoride", 0.3, "mg/L"),
        WaterQualityResult("Nitrate (as NO3)", 5.0, "mg/L"),
    ]


def test_a_sample_with_no_results_is_not_suitable_for_drinking():
    """Silence is not a pass. This used to return the full "suitable" line."""
    a = assess_sample(_sample())
    assert a.verdict_state == "indeterminate"
    assert a.is_potable is None
    assert "suitable for drinking" not in a.verdict.replace(
        "cannot be declared suitable for drinking", "")
    assert any(f.code == "nothing_evaluable" for f in a.flags)


def test_a_sample_of_nothing_but_unmeasured_rows_is_not_suitable():
    a = assess_sample(_sample(
        WaterQualityResult("Arsenic", None, "mg/L"),
        WaterQualityResult("Iron", None, "mg/L"),
    ))
    assert a.verdict_state == "indeterminate"


def test_an_unknown_determinand_keeps_the_sample_out_of_a_pass():
    """A determinand the table has never heard of is an open question.

    It used to raise an info flag nothing read, and the sample still came
    back "suitable for drinking" - including for 900 mg/L of petroleum
    hydrocarbons.
    """
    a = assess_sample(_sample(
        *_health_panel(),
        WaterQualityResult("Total petroleum hydrocarbons", 900.0, "mg/L"),
    ))
    assert a.verdict_state == "indeterminate"
    assert [r.parameter for r in a.unknown_parameters] == [
        "Total petroleum hydrocarbons"]
    assert any("Total petroleum hydrocarbons" in u for u in a.uncertainties)
    assert any(f.code == "unknown_parameter" and f.level == "warning"
               for f in a.flags)


def test_a_parameter_with_no_limit_is_not_an_open_question():
    """Temperature is in the table and deliberately carries no limit.

    "We have no standard for this" and "we have never heard of this" used to
    share one status, so nothing could tell them apart.
    """
    a = assess_sample(_sample(
        *_health_panel(),
        WaterQualityResult("Temperature", 27.4, "deg C"),
    ))
    assert a.verdict_state == "pass"
    assert a.unknown_parameters == []


def test_a_detection_limit_above_the_guideline_proves_nothing():
    """"< 0.05 mg/L" for arsenic does not show the 0.01 guideline is met.

    It shows the method cannot see the guideline. This used to read as
    "below detection" and pass.
    """
    a = assess_sample(_sample(
        WaterQualityResult("Arsenic", None, "mg/L",
                           detection_limit=0.05, below_detection=True),
    ))
    row = a.rows[0]
    assert row.status == "indeterminate"
    assert row.reason == "detection_limit_above_guideline"
    assert "more sensitive method" in row.remark
    assert a.verdict_state == "indeterminate"


def test_a_detection_limit_under_the_guideline_does_prove_compliance():
    a = assess_sample(_sample(
        WaterQualityResult("Arsenic", None, "mg/L",
                           detection_limit=0.001, below_detection=True),
    ))
    assert a.rows[0].status == "below_detection"
    assert a.rows[0].evaluable


def test_not_detected_in_100_ml_is_the_e_coli_guideline_being_met():
    """A membrane-filtration count cannot resolve below one colony per volume
    filtered, so "<1 CFU/100 mL" - the documented way to transcribe a clean
    certificate - is exactly "not detectable in any 100 mL sample". A limit
    of 10 (a 10 mL volume) still cannot show it."""
    clean = assess_sample(_sample(
        WaterQualityResult("E. coli", None, "CFU/100 mL",
                           detection_limit=1.0, below_detection=True),
    ))
    assert clean.rows[0].status == "below_detection" and clean.rows[0].evaluable
    assert "100 mL" in clean.rows[0].remark
    absent = assess_sample(_sample(
        WaterQualityResult("E. coli", None, "CFU/100 mL", below_detection=True),
    ))
    assert absent.rows[0].status == "below_detection"
    coarse = assess_sample(_sample(
        WaterQualityResult("E. coli", None, "CFU/100 mL",
                           detection_limit=10.0, below_detection=True),
    ))
    assert coarse.rows[0].status == "indeterminate"
    # a chemical determinand with no stated limit is still an open question
    chem = assess_sample(_sample(
        WaterQualityResult("Arsenic", None, "mg/L", below_detection=True),
    ))
    assert chem.rows[0].status == "indeterminate"
    assert chem.rows[0].reason == "detection_limit_unknown"


def test_a_detection_limit_is_converted_before_it_is_compared():
    """5 ug/L is under the 0.01 mg/L arsenic guideline; 5 mg/L is not."""
    under = assess_sample(_sample(
        WaterQualityResult("Arsenic", None, "ug/L",
                           detection_limit=5.0, below_detection=True),
    ))
    assert under.rows[0].status == "below_detection"
    over = assess_sample(_sample(
        WaterQualityResult("Arsenic", None, "mg/L",
                           detection_limit=5.0, below_detection=True),
    ))
    assert over.rows[0].status == "indeterminate"


def test_the_health_panel_has_to_have_been_run():
    """Clean water on four parameters is not a tested borehole."""
    a = assess_sample(_sample(
        WaterQualityResult("pH", 7.2, "pH units"),
        WaterQualityResult("Iron", 0.05, "mg/L"),
    ))
    assert a.verdict_state == "indeterminate"
    assert set(ESSENTIAL_HEALTH_PARAMETERS) == {"e. coli", "arsenic", "fluoride",
                                                "nitrate (as no3)"}
    assert a.missing_essential == ["E. coli", "Arsenic", "Fluoride",
                                   "Nitrate (as NO3)"]
    assert any(f.code == "incomplete_health_panel" for f in a.flags)


def test_a_complete_clean_panel_does_pass():
    """Fail-closed must not mean fail-always."""
    a = assess_sample(_sample(*_health_panel(),
                              WaterQualityResult("pH", 7.2, "pH units")))
    assert a.verdict_state == "pass"
    assert a.is_potable is True
    assert a.uncertainties == []
    assert "suitable for drinking" in a.verdict


def test_a_national_exceedance_is_not_an_aesthetic_one():
    """It is a legal compliance failure, and it used to be counted as taste."""
    a = assess_sample(_sample(
        *_health_panel(),
        WaterQualityResult("Aluminium", 0.5, "mg/L"),   # WHO 0.9, national 0.2
    ))
    assert a.verdict_state == "national_fail"
    assert [r.parameter for r in a.national_exceedances] == ["Aluminium"]
    assert a.aesthetic_exceedances == []          # no longer folded in here
    assert [r.parameter for r in a.all_exceedances] == ["Aluminium"]
    assert a.is_potable is False


def test_a_health_exceedance_outranks_an_open_question():
    """Uncertainty elsewhere does not soften a demonstrated exceedance."""
    a = assess_sample(_sample(
        WaterQualityResult("Arsenic", 0.5, "mg/L"),
        WaterQualityResult("Iron", 0.1, "wibbles"),
    ))
    assert a.verdict_state == "health_fail"
    assert a.is_potable is False


def test_an_open_question_outranks_an_aesthetic_exceedance():
    """"Usable for drinking" is a claim, and an open question defeats it."""
    a = assess_sample(_sample(
        *_health_panel(),
        WaterQualityResult("Iron", 0.5, "mg/L"),        # aesthetic only
        WaterQualityResult("Manganese", 0.02, "wibbles"),
    ))
    assert a.verdict_state == "indeterminate"
    # the aesthetic finding is still reported, just not as the verdict
    assert "Acceptability limits are exceeded for: Iron" in a.verdict


def test_the_verdict_says_what_has_to_be_resolved():
    a = assess_sample(_sample(
        WaterQualityResult("Arsenic", None, "mg/L",
                           detection_limit=0.05, below_detection=True),
    ))
    assert "detection limit is above the limit" in a.verdict
    assert "health panel is incomplete" in a.verdict


def test_a_status_never_reaches_a_report_as_a_raw_code():
    from groundwater.quality import STATUS_LABELS
    from groundwater.quality.assess import STATUS_ORDER

    for status in STATUS_ORDER:
        assert status in STATUS_LABELS, status
        assert STATUS_LABELS[status] != status


@pytest.mark.parametrize("state", ["health_fail", "national_fail",
                                   "indeterminate", "aesthetic", "pass"])
def test_every_state_has_every_label(state):
    from groundwater.quality import (
        VERDICT_LONG,
        VERDICT_ORDER,
        VERDICT_SHORT,
    )
    from groundwater.quality.assess import SUITABILITY_PHRASE, SUITABILITY_SENTENCE

    assert state in VERDICT_ORDER
    for table in (VERDICT_SHORT, VERDICT_LONG, SUITABILITY_SENTENCE,
                  SUITABILITY_PHRASE):
        assert table[state]


def test_a_below_detection_nitrite_cannot_hide_a_combined_rule_breach():
    """The WHO rule is nitrate/50 + nitrite/3 <= 1.

    Taking an unknown component as zero passed a sample whose upper bound is
    1.98 - "< 3 mg/L nitrite" beside 49 mg/L nitrate cannot rule the rule
    out, so the honest answer is that it has not been shown to be met.
    """
    a = assess_sample(_sample(
        WaterQualityResult("E. coli", 0.0, "CFU/100 mL"),
        WaterQualityResult("Arsenic", 0.001, "mg/L"),
        WaterQualityResult("Fluoride", 0.3, "mg/L"),
        WaterQualityResult("Nitrate (as NO3)", 49.0, "mg/L"),
        WaterQualityResult("Nitrite (as NO2)", None, "mg/L",
                           detection_limit=3.0, below_detection=True),
    ))
    combined = [r for r in a.rows if "combined" in r.parameter]
    assert combined and combined[0].status == "indeterminate"
    assert "upper bound" in combined[0].remark
    assert a.verdict_state == "indeterminate"
    assert any(f.code == "nitrate_nitrite_combined_unproven" for f in a.flags)


def test_a_low_detection_limit_still_lets_the_sample_pass():
    """Fail-closed must not mean fail-always: 49/50 + 0.01/3 is under 1."""
    a = assess_sample(_sample(
        *_health_panel()[:3],
        WaterQualityResult("Nitrate (as NO3)", 49.0, "mg/L"),
        WaterQualityResult("Nitrite (as NO2)", None, "mg/L",
                           detection_limit=0.01, below_detection=True),
    ))
    assert a.verdict_state == "pass"


def test_a_measured_pair_still_reports_a_real_combined_exceedance():
    a = assess_sample(_sample(
        *_health_panel()[:3],
        WaterQualityResult("Nitrate (as NO3)", 45.0, "mg/L"),
        WaterQualityResult("Nitrite (as NO2)", 1.0, "mg/L"),
    ))
    combined = [r for r in a.rows if "combined" in r.parameter]
    assert combined and combined[0].status == "exceeds_health"
    assert a.verdict_state == "health_fail"


def test_nitrate_reported_as_nitrogen_is_refused_not_graded_at_face_value():
    """10 mg/L as N is 44 mg/L as NO3 - a different water against a 50 limit.

    The unit names one basis and the parameter names another, so there is no
    reading under which the number can be compared.
    """
    a = assess_sample(_sample(
        WaterQualityResult("Nitrate (as NO3)", 10.0, "mg/L as N")))
    assert a.rows[0].status == "indeterminate"
    assert a.rows[0].reason == "unit_basis_conflict"
    # the matching basis converts normally
    ok = assess_sample(_sample(
        WaterQualityResult("Nitrate (as NO3)", 10.0, "mg/L as NO3")))
    assert ok.rows[0].value_in_guideline_unit == 10.0
    # and a parameter whose name states no basis still accepts one, with a flag
    hardness = assess_sample(_sample(
        WaterQualityResult("Total hardness", 58.0, "mg/L")))
    assert hardness.rows[0].reason == "unit_basis_assumed"


def test_the_report_does_not_clear_an_indeterminate_supply():
    """"No treatment is required" is a clearance the results did not give."""
    from groundwater.reporting.quality import _executive_summary

    a = assess_sample(_sample(WaterQualityResult("Iron", 0.1, "wibbles")))
    paragraphs, key = _executive_summary(a)
    assert "NOT been shown to be safe" in " ".join(key)
    assert "suitable for drinking" not in paragraphs[0].replace(
        "do not establish that the water is suitable for drinking", "")


def test_a_parameter_name_survives_the_report_sentence():
    """str.capitalize() lower-cased everything after the first character."""
    from groundwater.reporting.quality import _executive_summary

    a = assess_sample(_sample(
        WaterQualityResult("Total petroleum hydrocarbons", 900.0, "mg/L"),
        WaterQualityResult("E. coli", 3.0, "wibbles"),
    ))
    paragraph = _executive_summary(a)[0][0]
    text = " ".join(_executive_summary(a)[1])
    # both appear after the first character of a joined sentence, which is
    # exactly where capitalize() used to lower-case them
    assert "Total petroleum hydrocarbons" in text and "E. coli" in text
    assert "E. coli" in paragraph


def test_the_spine_plots_the_converted_value_against_its_limit():
    """The limit is in the guideline unit, so the value has to be too."""
    from groundwater.depth_spine.view import _quality

    micro = _quality(assess_sample(_sample(
        WaterQualityResult("Arsenic", 5.0, "ug/L"))))
    row = micro["rows"][0]
    assert row["valueInGuidelineUnit"] == 0.005
    assert row["ratio"] == 0.5          # 0.005 of a 0.01 mg/L guideline
    # an ungraded row has no ratio at all rather than a misleading one
    bad = _quality(assess_sample(_sample(
        WaterQualityResult("Arsenic", 5.0, "wibbles"))))
    assert bad["rows"][0]["ratio"] is None
    assert bad["rows"][0]["evaluable"] is False


@pytest.mark.parametrize("written,key", [
    ("Iron (Fe)", "iron"), ("Total iron", "iron"), ("Total alkalinity", "alkalinity"),
    ("Alkalinity (as CaCO3)", "alkalinity"), ("Calcium (Ca)", "calcium"),
    ("Manganese (Mn)", "manganese"), ("Conductivity (EC)", "electrical conductivity"),
    ("Nitrate (NO3)", "nitrate (as no3)"), ("Sulphate (SO4)", "sulfate"),
    ("Bicarbonate (HCO3)", "bicarbonate"), ("Turbidity (NTU)", "turbidity"),
    ("Temperature (°C)", "temperature"), ("pH value", "ph"),
    ("Thermotolerant coliforms", "e. coli"), ("Faecal coliform", "e. coli"),
    ("Colour", "colour"), ("Color", "colour"), ("Phosphate", "phosphate"),
    ("Free chlorine", "free chlorine"), ("Residual chlorine", "free chlorine"),
    ("Silica", "silica"), ("Total suspended solids", "total suspended solids"),
    ("Nitrate-N", "nitrate (as n)"), ("Nitrate (as N)", "nitrate (as n)"),
    ("Chromium (total)", "chromium (total)"), ("E.Coli", "e. coli"),
])
def test_certificate_spellings_resolve_to_the_table(written, key):
    from groundwater.quality.standards import load_standards, normalise_parameter

    assert normalise_parameter(written) == key
    assert key in load_standards(), key


def test_a_routine_certificate_is_not_refused_for_its_spellings():
    """The assessment is fail-closed, so an unknown name made the whole
    sample "not proven safe"; a clean panel written the way a laboratory
    writes it now passes."""
    a = assess_sample(_sample(
        WaterQualityResult("pH value", 7.1, "pH units"),
        WaterQualityResult("Turbidity (NTU)", 1.0, "NTU"),
        WaterQualityResult("Iron (Fe)", 0.1, "mg/L"),
        WaterQualityResult("Nitrate-N", 2.0, "mg/L"),
        WaterQualityResult("Fluoride", 0.3, "mg/L"),
        WaterQualityResult("Arsenic", 0.002, "mg/L"),
        WaterQualityResult("Total alkalinity", 46.0, "mg/L as CaCO3"),
        WaterQualityResult("Colour", 5.0, "TCU"),
        WaterQualityResult("Silica", 12.0, "mg/L"),
        WaterQualityResult("E. coli", None, "CFU/100 mL", below_detection=True),
        WaterQualityResult("Total coliforms", None, "CFU/100 mL",
                           detection_limit=1.0, below_detection=True),
    ))
    assert a.verdict_state == "pass", [(r.parameter, r.status, r.reason) for r in a.rows]
    nitrate_n = next(r for r in a.rows if r.parameter == "Nitrate-N")
    assert nitrate_n.status == "within_limits"
    high = assess_sample(_sample(WaterQualityResult("Nitrate-N", 12.0, "mg/L")))
    assert next(r for r in high.rows if r.parameter == "Nitrate-N").status == "exceeds_health"


def test_missing_sulfate_is_an_incomplete_analysis_not_an_unreliable_one():
    from groundwater.quality.ionic import ionic_balance

    def ions(**extra):
        results = [
            WaterQualityResult("Calcium", 20.0, "mg/L"), WaterQualityResult("Magnesium", 5.0, "mg/L"),
            WaterQualityResult("Sodium", 10.0, "mg/L"), WaterQualityResult("Potassium", 2.0, "mg/L"),
            WaterQualityResult("Chloride", 15.0, "mg/L"), WaterQualityResult("Bicarbonate", 60.0, "mg/L"),
        ] + [WaterQualityResult(k, v, "mg/L") for k, v in extra.items()]
        return _sample(*results)

    assert ionic_balance(ions()) is None
    with_sulfate = ionic_balance(ions(Sulfate=20.0))
    assert with_sulfate is not None and abs(with_sulfate.error_percent) < 5
