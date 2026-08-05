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


def test_any_positive_detection_limit_is_uninformative_for_e_coli():
    """Its guideline is zero, so "< 1 per 100 mL" cannot show compliance."""
    a = assess_sample(_sample(
        WaterQualityResult("E. coli", None, "CFU/100 mL",
                           detection_limit=1.0, below_detection=True),
    ))
    assert a.rows[0].status == "indeterminate"


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
