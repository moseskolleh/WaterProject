"""The rising main material at design time (PLAN.md step 7.2).

The design used to say nothing about the rising main, and the bill of
quantities priced the galvanised iron one the handpump line carries whatever
the water. Now the design reads the water quality sample through the
toolkit's two existing rules - the corrosivity classification and the
handpump corrosion check's pH rule - and specifies a stainless steel rising
main, inspected more often, where the water is aggressive; the bill prices
the difference. With no sample it says the choice rests on no chemistry.
"""

from __future__ import annotations

import csv
import io
from dataclasses import replace

import pytest

from groundwater._resources import bundled_text
from groundwater.config import DesignRules
from groundwater.costing import CostingInputs, estimate_borehole_cost, inputs_from_design, load_rates
from groundwater.costing.distribution import _at_depth
from groundwater.costing.model import RISING_MAIN_BASES
from groundwater.design import design_borehole, rising_main_choice
from groundwater.design.materials import CHEMISTRY_STATES, PH_CORROSIVE_BELOW
from groundwater.models import DrillingLog, LithologyInterval, SiteMetadata, WaterQualityResult, WaterQualitySample
from groundwater.quality import assess_corrosivity, assess_sample
from groundwater.supervision import handpump_corrosion_check
from groundwater.text import phrase


def _sample(sample_id="WQ-7", when="2024-05-01", **params):
    results = [WaterQualityResult(parameter=name, value=value, unit=unit)
               for name, (value, unit) in params.items()]
    return WaterQualitySample(site=SiteMetadata(community="Test"), sample_id=sample_id,
                              sample_date=when, results=results)


# soft, low-pH basement water: aggressive by every index and by the pH
SOFT = dict(pH=(5.8, "pH units"), Calcium=(6.0, "mg/L"),
            Alkalinity=(15.0, "mg/L as CaCO3"), TDS=(60.0, "mg/L"))
# hard water near equilibrium, pH inside the range: not aggressive
HARD = dict(pH=(7.8, "pH units"), Calcium=(100.0, "mg/L"),
            Alkalinity=(250.0, "mg/L as CaCO3"), TDS=(500.0, "mg/L"))
# very hard water at pH 6.4: the indices do not count it aggressive, the
# handpump corrosion check's pH rule does
ACID_HARD = dict(pH=(6.4, "pH units"), Calcium=(200.0, "mg/L"),
                 Alkalinity=(500.0, "mg/L as CaCO3"), TDS=(1500.0, "mg/L"))


def _log():
    return DrillingLog(
        site=SiteMetadata(community="X"), total_depth_m=50.0,
        intervals=[LithologyInterval(0, 20, "laterite"),
                   LithologyInterval(20, 50, "fractured granite, water strike")],
        water_strikes_m=[32.0],
    )


# ------------------------------------------------------------ what the water says

def test_no_sample_keeps_the_standard_material_on_no_chemistry():
    rules = DesignRules()
    choice = rising_main_choice(None, rules)
    assert choice["chemistry"] == "none" and not choice["upgraded"]
    assert choice["material"] == rules.rising_main_material == "galvanised iron"
    # nothing shows the water is not aggressive, so it is inspected as if it were
    assert choice["inspection_months"] == rules.aggressive_rising_main_inspection_months
    assert choice["statement"].startswith(phrase("rising_main.no_sample"))
    assert "rests on no chemistry" in choice["statement"]
    assert choice["sample"] == "" and choice["lsi"] is None


def test_aggressive_water_specifies_stainless_and_quotes_the_sample():
    sample = _sample(**SOFT)
    assessment = assess_sample(sample)
    corr = assessment.corrosivity
    assert corr.is_aggressive  # the existing classification, not a second one
    choice = rising_main_choice(assessment)
    assert choice["chemistry"] == "aggressive" and choice["by_indices"] and choice["by_ph"]
    assert choice["upgraded"] and choice["material"] == "stainless steel"
    assert choice["standard"] == "galvanised iron"
    assert choice["inspection_months"] == 6
    assert (choice["lsi"], choice["rsi"], choice["aggressive_index"]) == (
        corr.lsi, corr.rsi, corr.aggressive_index)
    text = choice["statement"]
    assert "WQ-7 of 2024-05-01" in text
    assert f"Ryznar index {corr.rsi:.2f}" in text
    assert f"Langelier index {corr.lsi:.2f}" in text  # negative, so its own sign
    assert f"aggressive index {corr.aggressive_index:.2f}" in text
    assert "rated strongly corrosive" in text
    assert "stainless steel rising main in place of the galvanised iron one" in text
    assert "every 6 months, against 12" in text
    assert phrase("rising_main.alternative") in text


def test_a_bare_sample_reads_as_its_assessment():
    sample = _sample(**SOFT)
    assert rising_main_choice(sample) == rising_main_choice(assess_sample(sample))


def test_water_that_is_not_aggressive_keeps_galvanised_at_the_usual_interval():
    sample = _sample(**HARD)
    assert not assess_corrosivity(sample).is_aggressive
    choice = rising_main_choice(sample)
    assert choice["chemistry"] == "not_aggressive" and not choice["upgraded"]
    assert choice["material"] == "galvanised iron"
    assert choice["inspection_months"] == 12
    assert "is not aggressive" in choice["statement"]
    assert "its pH of 7.8 is not below 6.5" in choice["statement"]
    assert "Langelier index +" in choice["statement"]


def test_a_ph_below_the_corrosion_check_limit_is_aggressive_on_its_own():
    sample = _sample(**ACID_HARD)
    corr = assess_corrosivity(sample)
    assert not corr.is_aggressive  # the indices alone would keep galvanised
    assert not handpump_corrosion_check(6.4).passed  # the existing pH rule
    choice = rising_main_choice(sample)
    assert choice["chemistry"] == "aggressive"
    assert choice["by_ph"] and not choice["by_indices"]
    assert choice["upgraded"] and choice["inspection_months"] == 6
    assert "has a pH of 6.4, below the 6.5" in choice["statement"]
    assert "do not count it aggressive on their own" in choice["statement"]
    assert PH_CORROSIVE_BELOW == 6.5


def test_a_low_ph_with_no_indices_is_still_aggressive():
    choice = rising_main_choice(_sample(pH=(6.0, "pH units")))
    assert choice["chemistry"] == "aggressive" and choice["upgraded"]
    assert choice["lsi"] is None and choice["classification"] == ""
    assert phrase("rising_main.ph_low_no_indices") in choice["statement"]


def test_a_sample_without_the_indices_rests_on_no_corrosivity_index():
    choice = rising_main_choice(_sample(pH=(7.0, "pH units")))
    assert choice["chemistry"] == "incomplete" and not choice["upgraded"]
    assert choice["inspection_months"] == 6
    assert "rests on no corrosivity index" in choice["statement"]
    assert "as in aggressive water" in choice["statement"]


def test_the_ph_rounding_never_puts_a_low_ph_on_the_limit():
    choice = rising_main_choice(_sample(pH=(6.46, "pH units")))
    assert "a pH of 6.46, below the 6.5" in choice["statement"]


@pytest.mark.parametrize("ident, when, named", [
    ("WQ-7", "2024-05-01", "The water sample WQ-7 of 2024-05-01 "),
    ("WQ-7", "", "The water sample WQ-7, which records no date, "),
    ("", "20th May, 2018", "The water sample of 20th May, 2018 "),
    ("  ", "", "The water sample with neither an identifier nor a date "),
])
def test_the_sample_is_named_by_its_identifier_and_date(ident, when, named):
    choice = rising_main_choice(_sample(sample_id=ident, when=when, **SOFT))
    assert choice["statement"].startswith(named)


def test_the_states_are_the_four_named():
    seen = {rising_main_choice(q)["chemistry"] for q in (
        None, _sample(**SOFT), _sample(**HARD), _sample(pH=(7.0, "pH units")))}
    assert seen == set(CHEMISTRY_STATES)


# ------------------------------------------------------------- the design rules

def test_the_materials_and_intervals_are_settings():
    rules = DesignRules()
    assert rules.aggressive_rising_main_material == "stainless steel"
    assert rules.rising_main_inspection_months == 12
    assert rules.aggressive_rising_main_inspection_months == 6
    other = replace(rules, aggressive_rising_main_material="uPVC",
                    rising_main_inspection_months=24, aggressive_rising_main_inspection_months=3)
    choice = rising_main_choice(_sample(**SOFT), other)
    assert choice["material"] == "uPVC" and choice["inspection_months"] == 3
    assert "against 24" in choice["statement"]


def test_rules_that_name_the_same_material_keep_it_and_say_so():
    rules = replace(DesignRules(), aggressive_rising_main_material=" Galvanised iron ")
    choice = rising_main_choice(_sample(**SOFT), rules)
    assert choice["chemistry"] == "aggressive" and not choice["upgraded"]
    assert choice["material"] == "galvanised iron"
    assert "name galvanised iron for aggressive water as well" in choice["statement"]


# ------------------------------------------------------------------ the design

def test_the_design_carries_the_choice_and_nothing_else_moves():
    plain = design_borehole(log=_log(), pump_intake_m=35.0)
    chosen = design_borehole(log=_log(), pump_intake_m=35.0, quality=assess_sample(_sample(**SOFT)))
    assert plain.rising_main["chemistry"] == "none"
    assert chosen.rising_main["upgraded"]
    # the drawing, the summary and the flags are the design's as before
    assert chosen.summary_rows() == plain.summary_rows()
    assert [f.code for f in chosen.flags] == [f.code for f in plain.flags]
    assert chosen.design_basis == plain.design_basis


def test_analyst_screens_carry_the_choice_too():
    design = design_borehole(log=_log(), screens_m=[(30.0, 45.0)], quality=_sample(**SOFT))
    assert design.rising_main["material"] == "stainless steel"


# --------------------------------------------------------- the bill of quantities

def _bill(design, **changes):
    inputs = inputs_from_design(design, mobilisation_distance_km=50.0)
    for key, value in changes.items():
        setattr(inputs, key, value)
    return estimate_borehole_cost(inputs)


def test_the_bill_prices_the_stainless_main_over_the_pump_intake():
    design = design_borehole(log=_log(), pump_intake_m=35.0, quality=_sample(**SOFT))
    inputs = inputs_from_design(design)
    assert inputs.rising_main_material == "stainless steel" and inputs.rising_main_m == 35.0
    estimate = _bill(design)
    line = next(i for i in estimate.items if i.code == "RSM1")
    rate = next(r for r in load_rates() if r.code == "RSM1")
    assert line.quantity == 35.0 and line.unit_cost_usd == rate.unit_cost_usd
    assert line.stage == "Wellhead"
    assert not [f for f in estimate.flags if f.code == "rising_main_unpriced"]
    plain = _bill(design_borehole(log=_log(), pump_intake_m=35.0))
    assert estimate.direct_cost_usd == pytest.approx(plain.direct_cost_usd + 35.0 * rate.unit_cost_usd)


def test_water_that_is_not_aggressive_adds_nothing_to_the_bill():
    design = design_borehole(log=_log(), pump_intake_m=35.0, quality=_sample(**HARD))
    assert inputs_from_design(design).rising_main_material == ""
    estimate = _bill(design)
    assert all(i.code != "RSM1" for i in estimate.items)
    assert not any("Rising main" in a for a in estimate.assumptions)


def test_with_no_intake_the_main_is_priced_to_the_whole_depth_and_says_so():
    design = design_borehole(log=_log(), quality=_sample(**SOFT))
    assert design.pump_intake_m is None
    estimate = _bill(design)
    line = next(i for i in estimate.items if i.code == "RSM1")
    assert line.quantity == 50.0
    assert phrase("rising_main.length_assumed", depth=50.0) in estimate.assumptions


def test_no_handpump_in_the_contract_prices_no_rising_main():
    design = design_borehole(log=_log(), pump_intake_m=35.0, quality=_sample(**SOFT))
    estimate = _bill(design, handpumps=0)
    assert all(i.code not in ("RSM1", "PMP1") for i in estimate.items)
    assert not estimate.flags or all(f.code != "rising_main_unpriced" for f in estimate.flags)
    assert not any("Rising main" in a for a in estimate.assumptions)


def test_a_material_the_catalogue_cannot_price_is_flagged_not_hidden():
    rules = replace(DesignRules(), aggressive_rising_main_material="uPVC")
    design = design_borehole(log=_log(), pump_intake_m=35.0, rules=rules, quality=_sample(**SOFT))
    estimate = _bill(design)
    assert all(i.code != "RSM1" for i in estimate.items)
    flag = next(f for f in estimate.flags if f.code == "rising_main_unpriced")
    assert flag.level == "warning"
    assert flag.message == phrase("rising_main.unpriced", material="uPVC")
    # a catalogue of one's own without the stainless row is flagged too
    design = design_borehole(log=_log(), pump_intake_m=35.0, quality=_sample(**SOFT))
    rates = [r for r in load_rates() if r.code != "RSM1"]
    estimate = estimate_borehole_cost(inputs_from_design(design), rates)
    assert any(f.code == "rising_main_unpriced" for f in estimate.flags)


def test_a_manual_estimate_can_carry_the_material():
    estimate = estimate_borehole_cost(CostingInputs(total_depth_m=60.0,
                                                    rising_main_material="Stainless steel"))
    line = next(i for i in estimate.items if i.code == "RSM1")
    assert line.quantity == 60.0
    plain = estimate_borehole_cost(CostingInputs(total_depth_m=60.0))
    assert all(i.code != "RSM1" for i in plain.items)


def test_the_cost_distribution_moves_an_assumed_length_with_the_depth():
    given = CostingInputs(total_depth_m=60.0, rising_main_material="stainless steel")
    base, _ = given.resolved()
    assert base.rising_main_m == 60.0
    assert _at_depth(given, base, 75.0).rising_main_m == 75.0
    fixed = CostingInputs(total_depth_m=60.0, rising_main_material="stainless steel",
                          rising_main_m=40.0)
    fixed_base, _ = fixed.resolved()
    assert _at_depth(fixed, fixed_base, 75.0).rising_main_m == 40.0
    plain = CostingInputs(total_depth_m=60.0)
    plain_base, _ = plain.resolved()
    assert _at_depth(plain, plain_base, 75.0).rising_main_m is None


def test_the_catalogue_row_is_a_placeholder_that_says_so():
    rows = list(csv.DictReader(io.StringIO(bundled_text("borehole_cost_items.csv"))))
    row = next(r for r in rows if r["code"] == "RSM1")
    assert row["quantity_basis"] == RISING_MAIN_BASES["stainless steel"]
    assert row["stage"] == "Wellhead" and row["unit"] == "m"
    assert "Placeholder" in row["note"] and "no quotation" in row["note"]
    # every material the bill can price has a row in the bundled catalogue
    bases = {r["quantity_basis"] for r in rows}
    assert set(RISING_MAIN_BASES.values()) <= bases
