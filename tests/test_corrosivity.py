"""Corrosivity index and materials-advice tests."""

from groundwater.models import SiteMetadata, WaterQualityResult, WaterQualitySample
from groundwater.quality import assess_corrosivity, assess_sample


def _sample(**params):
    results = [
        WaterQualityResult(parameter=name, value=value, unit=unit)
        for name, (value, unit) in params.items()
    ]
    return WaterQualitySample(site=SiteMetadata(community="Test"), results=results)


def test_soft_basement_water_is_aggressive():
    # soft, low-pH, low-alkalinity water typical of crystalline basement
    sample = _sample(
        pH=(5.8, "pH units"),
        Calcium=(6.0, "mg/L"),
        Alkalinity=(15.0, "mg/L as CaCO3"),
        TDS=(60.0, "mg/L"),
        Temperature=(27.0, "deg C"),
    )
    corr = assess_corrosivity(sample)
    assert corr.is_aggressive
    assert corr.lsi is not None and corr.lsi < 0  # undersaturated -> corrosive
    assert corr.rsi is not None and corr.rsi > 8  # strongly corrosive
    assert "uPVC" in corr.materials_note and "galvanised" in corr.materials_note
    assert corr.classification in ("Corrosive", "Strongly corrosive")


def test_hard_water_is_scale_forming():
    sample = _sample(
        pH=(8.2, "pH units"),
        Calcium=(120.0, "mg/L"),
        Alkalinity=(300.0, "mg/L as CaCO3"),
        TDS=(600.0, "mg/L"),
        Temperature=(25.0, "deg C"),
    )
    corr = assess_corrosivity(sample)
    assert not corr.is_aggressive
    assert corr.lsi is not None and corr.lsi > 0  # supersaturated -> scaling
    assert corr.classification == "Scale-forming"


def test_missing_inputs_reported_not_crashed():
    sample = _sample(pH=(6.5, "pH units"))  # no calcium or alkalinity
    corr = assess_corrosivity(sample)
    assert corr.classification == "Insufficient data"
    assert corr.lsi is None
    assert "required" in corr.verdict


def test_ec_used_when_tds_absent():
    sample = _sample(
        pH=(6.0, "pH units"),
        Calcium=(8.0, "mg/L"),
        Alkalinity=(20.0, "mg/L as CaCO3"),
        **{"Electrical conductivity": (120.0, "uS/cm")},
    )
    corr = assess_corrosivity(sample)
    assert corr.lsi is not None  # computed despite no TDS
    assert any("EC" in a for a in corr.assumptions)


def test_assess_sample_attaches_corrosivity_and_flag():
    sample = _sample(
        pH=(5.6, "pH units"),
        Calcium=(5.0, "mg/L"),
        Alkalinity=(12.0, "mg/L as CaCO3"),
        TDS=(50.0, "mg/L"),
    )
    assessment = assess_sample(sample)
    assert assessment.corrosivity is not None and assessment.corrosivity.is_aggressive
    assert any(f.code == "aggressive_water" for f in assessment.flags)
