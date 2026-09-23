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


def test_a_national_exceedance_is_not_an_aesthetic_one(tmp_path):
    """It is a compliance failure, and it used to be counted as taste.

    The case is a national limit stricter than the WHO health guideline. No
    row in the bundled table is one: aluminium used to be, on a WHO health
    value of 0.9 mg/L that WHO does not set, so the case is built here
    rather than resting on a figure that should never have been in the
    table.
    """
    standards = tmp_path / "standards.csv"
    standards.write_text(
        "parameter,unit,who_health_gv,who_aesthetic,sl_standard,sl_source,category,note\n"
        "E. coli,CFU/100 mL,0,,0,provisional,microbiological,\n"
        "Arsenic,mg/L,0.01,,0.01,provisional,inorganic,\n"
        "Fluoride,mg/L,1.5,,1.5,provisional,inorganic,\n"
        "Nitrate (as NO3),mg/L,50,,50,provisional,inorganic,\n"
        "Manganese,mg/L,0.4,0.1,0.08,provisional,metal,national stricter\n",
        encoding="utf-8",
    )
    a = assess_sample(_sample(
        *_health_panel(),
        WaterQualityResult("Manganese", 0.2, "mg/L"),   # WHO 0.4, national 0.08
    ), standards_path=standards)
    assert a.verdict_state == "national_fail"
    assert [r.parameter for r in a.national_exceedances] == ["Manganese"]
    assert a.aesthetic_exceedances == []          # no longer folded in here
    assert [r.parameter for r in a.all_exceedances] == ["Manganese"]
    assert a.is_potable is False


def test_a_limit_who_sets_no_health_value_for_is_reported_as_provisional():
    """Aluminium had a WHO health guideline of 0.9 mg/L in the table.

    WHO sets none: 0.9 is a health-based value the guidelines derive and
    explicitly decline to adopt. A sample at 0.5 mg/L was therefore graded
    against a guideline that does not exist.
    """
    a = assess_sample(_sample(
        *_health_panel(),
        WaterQualityResult("Aluminium", 0.5, "mg/L"),
    ))
    assert not a.health_exceedances
    row = next(r for r in a.rows if r.parameter == "Aluminium")
    assert row.who_health == ""
    assert "provisional" in row.remark


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


def test_a_count_that_was_not_quantified_is_not_a_pass():
    """E. coli 0 with total coliforms TNTC used to be graded "Safe".

    The count read as "not measured", so the verdict rested on the one
    determinand that was clean and said nothing about the one that was not.
    """
    a = assess_sample(_sample(
        *_health_panel(),
        WaterQualityResult("Total coliforms", None, "CFU/100 mL", greater_than=0.0),
    ))
    assert a.verdict_state == "national_fail"
    assert [r.parameter for r in a.national_exceedances] == ["Total coliforms"]
    assert a.is_potable is False
    row = next(r for r in a.rows if r.parameter == "Total coliforms")
    assert "did not quantify" in row.remark or "not quantified" in row.remark


def test_a_faecal_indicator_that_was_not_quantified_is_a_health_failure():
    a = assess_sample(_sample(
        WaterQualityResult("E. coli", None, "CFU/100 mL", greater_than=0.0),
    ))
    row = next(r for r in a.rows if r.parameter == "E. coli")
    assert row.status == "exceeds_health"


def test_a_greater_than_inside_the_limit_is_an_open_question():
    """">20" is at least 20, not exactly 20, and the limit is 50.

    Read as exactly 20 it passed; the true value is somewhere above it, so
    the honest answer is that it cannot be shown to meet the limit.
    """
    a = assess_sample(_sample(
        *_health_panel(),
        WaterQualityResult("Sulfate", None, "mg/L", greater_than=100.0),
    ))
    row = next(r for r in a.rows if r.parameter == "Sulfate")
    assert row.status == "indeterminate"
    assert row.evaluable is False
    assert "more than 100" in row.remark


def test_a_balance_that_could_not_be_computed_says_which_ions_are_missing():
    """It was skipped in silence, which reads as an analysis that balanced.

    The charge balance is the one check that says whether a certificate's
    own numbers hang together. With a major ion missing the report simply
    had no charge-balance line and no flag either, so nothing told the
    reader that nobody could tell.
    """
    a = assess_sample(_sample(
        WaterQualityResult("pH", 7.2, "pH units"),
        WaterQualityResult("Calcium", 40.0, "mg/L"),
    ))
    assert a.ionic is None
    flag = next(f for f in a.flags if f.code == "ionic_balance_not_checked")
    assert "magnesium" in flag.message and "sulfate" in flag.message
    assert flag.level == "warning"


def test_a_complete_analysis_still_balances_without_the_new_flag():
    a = assess_sample(_sample(
        WaterQualityResult("Calcium", 40.0, "mg/L"),
        WaterQualityResult("Magnesium", 10.0, "mg/L"),
        WaterQualityResult("Sodium", 20.0, "mg/L"),
        WaterQualityResult("Chloride", 30.0, "mg/L"),
        WaterQualityResult("Sulfate", 15.0, "mg/L"),
        WaterQualityResult("Bicarbonate", 150.0, "mg/L"),
    ))
    assert a.ionic is not None
    assert not [f for f in a.flags if f.code == "ionic_balance_not_checked"]


def test_a_detection_of_a_determinand_the_table_does_not_know_is_not_a_pass():
    """"Salmonella: Present" was read as not measured, raised no flag, and
    left the sample "suitable for drinking"; the same organism with a count
    was "not proven safe". Salmonella is now graded by name (below); any
    other detection of something the table does not know stays open."""
    a = assess_sample(_sample(
        *_health_panel(),
        WaterQualityResult("Iron bacteria", None, "per 100 mL", greater_than=0.0),
        WaterQualityResult("Faecal streptococci", None, "CFU/100 mL",
                           greater_than=50.0),
    ))
    for row in a.rows[4:]:
        assert row.status == "no_guideline" and row.reason == "unknown_parameter"
        assert not row.evaluable
    assert a.rows[4].remark.startswith("detected, count not quantified")
    assert a.rows[5].remark.startswith("more than 50")
    assert [f.code for f in a.flags].count("unknown_parameter") == 2
    assert a.verdict_state == "indeterminate"
    assert "suitable for drinking on the basis" not in a.verdict


def test_a_faecal_pathogen_is_graded_by_its_name_not_its_unit():
    """"Salmonella: Present" was an unknown determinand, so the verdict asked
    for units and detection limits to be confirmed while the laboratory had
    reported Salmonella in the water. The only thing that could have told
    it was microbiological was the unit, and grading every CFU count as a
    pathogen would fail a sample on a heterotrophic plate count, which WHO
    does not treat as a health parameter."""
    from groundwater.quality.standards import faecal_pathogen
    from groundwater.reporting.quality import quality_recommendations

    def graded(result):
        a = assess_sample(_sample(*_health_panel(), result))
        return a, a.rows[-1]

    for result in (
        WaterQualityResult("Salmonella", None, "per 100 mL", greater_than=0.0),
        WaterQualityResult("Shigella spp.", 3.0, "CFU/100 mL"),
        WaterQualityResult("Giardia cysts", None, "per 10 L", greater_than=50.0),
        WaterQualityResult("Vibrio cholerae O1", 1.0, ""),
    ):
        a, row = graded(result)
        assert (row.status, row.evaluable, row.reason) == ("exceeds_health", True, "")
        assert row.remark.endswith("a health concern, whatever the count")
        assert a.verdict_state == "health_fail"
        assert "a sanitary inspection to find where the contamination enters" in (
            " ".join(quality_recommendations(a)))
    a, row = graded(WaterQualityResult("Salmonella", None, "per 100 mL",
                                       greater_than=0.0))
    assert row.remark.startswith("detected, count not quantified: a faecal pathogen")
    assert a.verdict.startswith(
        "The water does not meet the health based guideline value for: Salmonella.")

    # nothing found is the requirement met, and does not hold the sample open
    for result, status in (
        (WaterQualityResult("Salmonella", 0.0, "CFU/100 mL"), "within_limits"),
        (WaterQualityResult("Salmonella", None, "", below_detection=True),
         "below_detection"),
        (WaterQualityResult("Cryptosporidium oocysts", None, "oocysts/10 L",
                            detection_limit=1.0, below_detection=True),
         "below_detection"),
    ):
        a, row = graded(result)
        assert (row.status, row.evaluable) == (status, True)
        assert a.verdict_state == "pass"
    # but a method that cannot see one organism cannot show there are none
    a, row = graded(WaterQualityResult("Cryptosporidium oocysts", None, "oocysts/10 L",
                                       detection_limit=10.0, below_detection=True))
    assert (row.status, row.evaluable) == ("indeterminate", False)
    assert row.remark.startswith(
        "reported below a detection limit of 10 oocysts/10 L, which cannot show")
    assert a.verdict_state == "indeterminate"

    # a plate count names no organism, and stays an open question, not a failure
    a, row = graded(WaterQualityResult("Heterotrophic plate count", 250.0, "CFU/mL"))
    assert (row.status, row.reason) == ("no_guideline", "unknown_parameter")
    assert a.verdict_state == "indeterminate"
    assert [faecal_pathogen(n) for n in (
        "E. coli", "Total coliforms", "Heterotrophic plate count", "Iron bacteria",
        "Hepatitis antibodies", "Faecal streptococci")] == [""] * 6
    assert [faecal_pathogen(n) for n in (
        "Salmonella typhi", "S. Typhi", "Hepatitis A virus", "Enteroviruses",
        "E. coli O157:H7", "V. cholerae")] == [
        "salmonella", "s. typhi", "hepatitis a", "enterovirus", "e. coli o157",
        "v. cholerae"]


def test_a_national_failure_does_not_claim_health_values_it_never_showed():
    """Arsenic "<0.05" could not be graded and there was no fluoride or
    nitrate, yet a total coliform count made the verdict "meets the WHO
    health based guideline values" in the verdict, the summary and the
    completion and handover sentences."""
    from groundwater.quality.assess import SUITABILITY_SENTENCE, suitability_sentence
    from groundwater.reporting.quality import _executive_summary

    a = assess_sample(_sample(
        WaterQualityResult("E. coli", 0.0, "CFU/100 mL"),
        WaterQualityResult("Arsenic", None, "mg/L", detection_limit=0.05,
                           below_detection=True),
        WaterQualityResult("Total coliforms", 12.0, "CFU/100 mL"),
    ))
    assert a.verdict_state == "national_fail" and a.uncertainties
    assert "meets the WHO" not in a.verdict
    assert "has not been shown to meet the WHO health based guideline values" in a.verdict
    assert "Arsenic could not be assessed" in a.verdict
    assert "meets the WHO" not in suitability_sentence(a)
    paragraphs, key = _executive_summary(a)
    assert "meet the WHO" not in paragraphs[0].replace("not been shown to meet the WHO", "")
    assert "All WHO health based guideline values are met." not in key
    # with nothing unresolved the claim is made, and made true
    clean = assess_sample(_sample(
        *_health_panel(), WaterQualityResult("Total coliforms", 12.0, "CFU/100 mL")))
    assert clean.uncertainties == []
    assert clean.verdict.startswith("The water meets the WHO health based guideline values")
    assert suitability_sentence(clean) == SUITABILITY_SENTENCE["national_fail"]
    assert "All WHO health based guideline values are met." in _executive_summary(clean)[1]


def test_the_completion_and_handover_summaries_name_what_is_unresolved():
    """The summary sentence said only that the WHO values had not been shown
    to be met, or that the results were incomplete, and named nothing: the
    arsenic result nobody could grade and the missing fluoride were in the
    quality section and nowhere in the summary."""
    from groundwater.models import DrillingLog, SiteMetadata
    from groundwater.quality.assess import suitability_sentence
    from groundwater.reporting import completion, handover

    arsenic = WaterQualityResult("Arsenic", None, "mg/L", detection_limit=0.05,
                                 below_detection=True)
    failing = assess_sample(_sample(
        WaterQualityResult("E. coli", 0.0, "CFU/100 mL"), arsenic,
        WaterQualityResult("Total coliforms", 12.0, "CFU/100 mL"),
    ))
    open_only = assess_sample(_sample(
        WaterQualityResult("E. coli", 0.0, "CFU/100 mL"), arsenic,
    ))
    assert failing.verdict_state == "national_fail"
    assert open_only.verdict_state == "indeterminate"

    site = SiteMetadata(community="Mabang")
    log = DrillingLog(site=site, total_depth_m=60.0)
    for a in (failing, open_only):
        sentence = suitability_sentence(a)
        assert "Arsenic could not be assessed: the detection limit is above" in sentence
        assert "no evaluable result for Arsenic, Fluoride, Nitrate (as NO3)" in sentence
        assert sentence.endswith(".") and ".." not in sentence
        for paragraphs in (
            completion._executive_summary(
                completion.CompletionReportInputs(log=log, quality=a))[0],
            handover._executive_summary(
                handover.HandoverReportInputs(site=site, log=log, quality=a))[0],
        ):
            assert "Arsenic could not be assessed" in paragraphs[0]
            assert "Fluoride" in paragraphs[0]
    assert suitability_sentence(failing).startswith(
        "The water does not comply with the national standard, and it has not "
        "been shown to meet the WHO health based guideline values: Arsenic")
    assert suitability_sentence(open_only).startswith(
        "The water has not been shown to be suitable for drinking: Arsenic")


def test_the_combined_nitrate_rule_reads_either_basis():
    """10 and 0.8 mg/L as N is an index of 1.76, and the rule was skipped
    because only the "as NO3" and "as NO2" rows were looked for."""
    def combined(*results):
        a = assess_sample(_sample(*_health_panel()[:3], *results))
        rows = [r for r in a.rows if "combined" in r.parameter]
        return (rows[0].status, rows[0].value) if rows else None

    assert combined(WaterQualityResult("Nitrate (as N)", 10.0, "mg/L"),
                    WaterQualityResult("Nitrite (as N)", 0.8, "mg/L")) == (
        "exceeds_health", 1.76)
    assert combined(WaterQualityResult("Nitrate (as NO3)", 45.0, "mg/L"),
                    WaterQualityResult("Nitrite (as N)", 0.5, "mg/L")) == (
        "exceeds_health", 1.45)
    assert combined(WaterQualityResult("Nitrate-N", 10.0, "mg/L"),
                    WaterQualityResult("Nitrite", 1.5, "mg/L")) == (
        "exceeds_health", 1.38)
    assert combined(WaterQualityResult("Nitrate (as NO3)", 45.0, "mg/L"),
                    WaterQualityResult("Nitrite (as NO2)", 1.5, "mg/L")) == (
        "exceeds_health", 1.4)
    assert combined(WaterQualityResult("Nitrate (as N)", 5.0, "mg/L"),
                    WaterQualityResult("Nitrite (as N)", 0.1, "mg/L")) is None


def test_a_lower_bound_is_graded_as_a_measured_value_would_be():
    """A bound was compared as written and met every limit with the coliform
    wording: lead ">5 ug/L" (0.005 mg/L) failed the health guideline while a
    measured 7 ug/L complied, iron ">1.0" was a national failure put down
    to wellhead ingress where a measured 1.5 was an acceptability one, and
    ">=50" nitrate exceeded a limit of 50 it may equal."""
    def row(result, panel=None):
        a = assess_sample(_sample(*(panel or _health_panel()), result))
        return next(r for r in a.rows if r.parameter == result.parameter), a

    lead, _ = row(WaterQualityResult("Lead", None, "ug/L", greater_than=5.0))
    assert lead.status == "indeterminate"
    assert "(5 ug/L = 0.005 mg/L)" in lead.remark
    lead, _ = row(WaterQualityResult("Lead", None, "ug/L", greater_than=20.0))
    assert lead.status == "exceeds_health"
    iron, a = row(WaterQualityResult("Iron", None, "mg/L", greater_than=1.0))
    measured, _ = row(WaterQualityResult("Iron", 1.5, "mg/L"))
    assert iron.status == measured.status == "exceeds_aesthetic"
    assert "wellhead" not in iron.remark and a.verdict_state == "aesthetic"
    tds, _ = row(WaterQualityResult("TDS", None, "mg/L", greater_than=1000.0))
    assert tds.status == "exceeds_aesthetic"
    panel = _health_panel()[:3]
    at_least, _ = row(WaterQualityResult("Nitrate (as NO3)", None, "mg/L",
                                         greater_than=50.0,
                                         greater_than_inclusive=True), panel)
    assert at_least.status == "indeterminate" and "at least 50" in at_least.remark
    more_than, _ = row(WaterQualityResult("Nitrate (as NO3)", None, "mg/L",
                                          greater_than=50.0), panel)
    assert more_than.status == "exceeds_health"
    # over the acceptability value and under the health guideline: the
    # exceedance stands, and the guideline it cannot rule out is said
    copper, a = row(WaterQualityResult("Copper", None, "mg/L", greater_than=1.5))
    assert copper.status == "exceeds_aesthetic"
    assert copper.reason == "stricter_limit_unresolved"
    assert "WHO health based guideline (2) is not known" in copper.remark
    assert a.verdict_state == "indeterminate"
    assert any("Copper was not quantified" in u for u in a.uncertainties)
    assert any(f.code == "stricter_limit_unresolved" for f in a.flags)


def test_a_confirmed_national_limit_is_not_called_provisional(tmp_path):
    """Every acceptability remark said "which is provisional", and the
    summary called a provisional limit a legal requirement, whatever table
    was in use."""
    from groundwater.reporting.quality import _executive_summary

    standards = tmp_path / "standards.csv"
    standards.write_text(
        "parameter,unit,who_health_gv,who_aesthetic,sl_standard,sl_source,category,note\n"
        "E. coli,CFU/100 mL,0,,0,SLSB 2021,microbiological,\n"
        "Arsenic,mg/L,0.01,,0.01,SLSB 2021,metal,\n"
        "Fluoride,mg/L,1.5,,1.5,SLSB 2021,inorganic,\n"
        "Nitrate (as NO3),mg/L,50,,50,SLSB 2021,inorganic,\n"
        "Iron,mg/L,,0.3,0.3,SLSB 2021,metal,\n"
        "Total coliforms,CFU/100 mL,,0,0,SLSB 2021,microbiological,\n",
        encoding="utf-8",
    )
    iron = WaterQualityResult("Iron", 1.2, "mg/L")
    confirmed = assess_sample(_sample(*_health_panel(), iron), standards_path=standards)
    assert confirmed.rows[-1].status == "exceeds_aesthetic"
    assert "provisional" not in confirmed.rows[-1].remark
    assert not confirmed.rows[-1].sl_provisional
    bundled = assess_sample(_sample(*_health_panel(), iron))
    assert "which is provisional" in bundled.rows[-1].remark
    assert bundled.rows[-1].sl_provisional

    coliforms = WaterQualityResult("Total coliforms", 5.0, "CFU/100 mL")
    legal = assess_sample(_sample(*_health_panel(), coliforms), standards_path=standards)
    assert "legal requirement" in _executive_summary(legal)[0][0]
    paragraph = _executive_summary(assess_sample(_sample(*_health_panel(), coliforms)))[0][0]
    assert "legal requirement" not in paragraph
    assert "provisional" in paragraph and "compliance finding" in paragraph


def test_the_recommendations_follow_the_table_name_and_the_direction():
    """Advice was matched by substring on the name as written: lead and
    "Faecal coliforms" got "No treatment is required" under "Treat before
    use", "Sulphate" got the low-pH advice for containing "ph", and so did a
    pH of 9.2."""
    from groundwater.reporting.quality import quality_recommendations

    def advice(*results):
        return quality_recommendations(assess_sample(_sample(*_health_panel(), *results)))

    lead = advice(WaterQualityResult("Lead", 0.05, "mg/L"))
    assert not any("No treatment is required" in t for t in lead)
    assert any(t.startswith("Treat or replace the source") and "Lead" in t for t in lead)
    faecal = advice(WaterQualityResult("Faecal coliforms", 5.0, "CFU/100 mL"))
    assert any("E. coli detection calls for shock chlorination" in t for t in faecal)
    assert not any("No treatment is required" in t for t in faecal)
    sulphate = advice(WaterQualityResult("Sulphate", 400.0, "mg/L"))
    assert not any("pH" in t for t in sulphate)
    high = advice(WaterQualityResult("pH", 9.2, "pH units"))
    assert any("pH above the acceptability range" in t for t in high)
    assert not any("Low pH" in t for t in high)
    assert any("Low pH" in t for t in advice(WaterQualityResult("pH", 5.9, "pH units")))
    clean = advice(WaterQualityResult("pH", 7.2, "pH units"))
    assert any("No treatment is required" in t for t in clean)


def test_a_result_that_was_not_quantified_prints_as_what_was_reported():
    """The report tables printed only the value, so TNTC and ">50" reached
    the client as "n/a"."""
    from groundwater.quality.assess import unquantified_text

    a = assess_sample(_sample(
        *_health_panel()[:3],
        WaterQualityResult("Nitrate (as NO3)", None, "mg/L", greater_than=50.0),
        WaterQualityResult("Total coliforms", None, "CFU/100 mL", greater_than=0.0),
        WaterQualityResult("Iron", None, "mg/L", greater_than=1.0,
                           greater_than_inclusive=True),
    ))
    assert [unquantified_text(r) for r in a.rows] == [
        "", "", "", ">50", "detected", "≥1"]
