"""Water Quality Index and health Hazard Index tests."""

from groundwater.models import SiteMetadata, WaterQualityResult, WaterQualitySample
from groundwater.quality import assess_health_risk, assess_sample, compute_wqi


def _sample(**params):
    results = [
        WaterQualityResult(parameter=name, value=value, unit="mg/L")
        for name, value in params.items()
    ]
    return WaterQualitySample(site=SiteMetadata(community="Test"), results=results)


def test_wqi_low_for_clean_water():
    sample = _sample(**{
        "pH": 7.0, "TDS": 200.0, "Chloride": 20.0, "Sulfate": 15.0,
        "Nitrate (as NO3)": 5.0, "Iron": 0.05, "Fluoride": 0.3,
    })
    wqi = compute_wqi(sample)
    assert wqi is not None and wqi.n_parameters >= 3
    assert wqi.value < 100 and wqi.rating in ("Excellent", "Good")


def test_wqi_high_for_polluted_water():
    sample = _sample(**{
        "pH": 7.0, "TDS": 1500.0, "Chloride": 600.0, "Sulfate": 400.0,
        "Nitrate (as NO3)": 120.0, "Iron": 2.0, "Fluoride": 3.0,
    })
    wqi = compute_wqi(sample)
    assert wqi is not None and wqi.value > 100  # poor or worse


def test_health_risk_flags_arsenic():
    # arsenic well above the 0.01 guideline
    sample = _sample(**{"Arsenic": 0.05, "Fluoride": 0.5})
    hr = assess_health_risk(sample)
    assert hr is not None
    assert hr.hazard_index >= 1.0
    assert hr.cancer_risk is not None and hr.cancer_risk > 1e-4
    assert "arsenic" in hr.hazard_quotients
    assert any(f.code in ("hazard_index", "cancer_risk") for f in hr.flags)


def test_health_risk_acceptable_for_clean_water():
    sample = _sample(**{"Arsenic": 0.001, "Fluoride": 0.3, "Nitrate (as NO3)": 5.0})
    hr = assess_health_risk(sample)
    assert hr is not None and hr.hazard_index < 1.0
    assert "below 1" in hr.rating


def test_assess_sample_attaches_indices():
    sample = _sample(**{
        "pH": 7.2, "TDS": 300.0, "Chloride": 30.0, "Sulfate": 20.0,
        "Arsenic": 0.04, "Fluoride": 0.4,
    })
    assessment = assess_sample(sample)
    assert assessment.wqi is not None
    assert assessment.health_risk is not None and assessment.health_risk.hazard_index > 0
