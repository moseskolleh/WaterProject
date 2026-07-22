"""Regression tests for the code-review bug fixes.

Each test pins the corrected behaviour of a specific defect found in the
project review so it cannot silently regress. Tests are grouped by the
subsystem they exercise.
"""

from __future__ import annotations

import numpy as np
import pytest
from openpyxl import Workbook

from groundwater.models import (
    LayeredModel,
    SiteMetadata,
    WaterQualityResult,
    WaterQualitySample,
    VESSounding,
)
from groundwater.quality import (
    assess_corrosivity,
    assess_health_risk,
    assess_sample,
    compute_wqi,
)


def _quality_sample(*results: WaterQualityResult) -> WaterQualitySample:
    return WaterQualitySample(site=SiteMetadata(community="Test"), results=list(results))


# --- water quality: microbiological classification --------------------------

def test_total_coliform_is_a_health_exceedance_not_aesthetic():
    """Faecal-indicator bacteria must never be reported as a taste problem."""
    a = assess_sample(_quality_sample(
        WaterQualityResult("pH", 7.2),
        WaterQualityResult("Total coliforms", 40.0, unit="CFU/100mL"),
        WaterQualityResult("Chloride", 30.0),
        WaterQualityResult("TDS", 200.0),
    ))
    names = {r.parameter for r in a.health_exceedances}
    assert "Total coliforms" in names
    assert "Total coliforms" not in {r.parameter for r in a.aesthetic_exceedances}
    assert "usable for drinking" not in a.verdict
    assert "health based guideline" in a.verdict


def test_ecoli_still_health_exceedance():
    a = assess_sample(_quality_sample(WaterQualityResult("E. coli", 12.0, unit="CFU/100mL")))
    assert "E. coli" in {r.parameter for r in a.health_exceedances}


# --- water quality: below-detection handling --------------------------------

def _quality_workbook(tmp_path, rows):
    """Write a minimal quality sheet: a header line + a results table."""
    wb = Workbook()
    ws = wb.active
    ws.append(["Community:", "Test"])
    ws.append(["Sample ID:", "S1"])
    ws.append([])
    ws.append(["Parameter", "Unit", "Value", "Detection limit"])
    for row in rows:
        ws.append(row)
    path = tmp_path / "wq.xlsx"
    wb.save(path)
    return path


def test_below_detection_value_cleared_even_with_dl_column(tmp_path):
    """A '<X' value plus a filled detection-limit column must read as below
    detection, not as a real measurement equal to the limit."""
    from groundwater.ingestion import read_quality_workbook

    path = _quality_workbook(tmp_path, [
        ["Arsenic", "mg/L", "<0.01", "0.01"],   # marker AND explicit DL
        ["Lead", "mg/L", "<0.005", ""],           # marker only
    ])
    sample = read_quality_workbook(path)
    by_name = {r.parameter: r for r in sample.results}
    ars = by_name["Arsenic"]
    assert ars.below_detection is True
    assert ars.value is None
    assert ars.detection_limit == 0.01
    # and the assessment reports it as below-detection, not an exceedance
    a = assess_sample(sample)
    ars_row = next(r for r in a.rows if r.parameter == "Arsenic")
    assert ars_row.status == "below_detection"


# --- water quality: index sanity --------------------------------------------

def test_wqi_not_dominated_by_a_single_trace_toxicant():
    """A lone arsenic reading must not swamp the physico-chemical WQI."""
    params = dict(pH=7.0, Calcium=8.0, Magnesium=3.0, Sodium=12.0,
                  Chloride=15.0, Sulfate=6.0, TDS=90.0)
    clean = compute_wqi(_quality_sample(
        *[WaterQualityResult(k, v) for k, v in params.items()]))
    with_as = compute_wqi(_quality_sample(
        *[WaterQualityResult(k, v) for k, v in params.items()],
        WaterQualityResult("Arsenic", 0.02)))
    assert clean is not None and with_as is not None
    # adding one trace toxicant leaves the physico-chemical index unchanged
    assert with_as.value == clean.value
    assert clean.rating in ("Excellent", "Good")
    assert "Arsenic" not in {name for name, _ in with_as.top_contributors}


def test_nitrate_hazard_quotient_uses_nitrogen_basis():
    """Nitrate HQ must convert as-NO3 concentration to an as-N basis before
    dividing by the as-N reference dose (else it is ~4.4x too high)."""
    hr = assess_health_risk(_quality_sample(WaterQualityResult("Nitrate (as NO3)", 44.3)))
    assert hr is not None
    hq = hr.hazard_quotients["nitrate (as no3)"]
    # 44.3 as NO3 -> ~10 mg/L N; HQ = (10 * 2/70) / 1.6 ~= 0.18, well under the
    # ~0.79 the naive as-NO3 calculation would give.
    assert 0.15 < hq < 0.22


# --- water quality: corrosivity classification/flag consistency -------------

def test_corrosivity_label_matches_aggressive_flag():
    """When LSI/AI corroboration forces aggressive, the class label must not
    still read 'Balanced'/'Scale-forming'."""
    # soft, mildly acidic water: RSI lands near-balanced but LSI < -0.5
    corr = assess_corrosivity(_quality_sample(
        WaterQualityResult("pH", 6.6),
        WaterQualityResult("Calcium", 12.0),
        WaterQualityResult("Alkalinity", 40.0),
        WaterQualityResult("TDS", 120.0),
        WaterQualityResult("Temperature", 27.0),
    ))
    if corr.is_aggressive:
        assert corr.classification in ("Corrosive", "Strongly corrosive")
        assert "aggressive" in corr.verdict


# --- core: truthiness vs None -----------------------------------------------

def test_merged_with_keeps_real_zero_elevation():
    a = SiteMetadata(community="A", elevation_m=0.0)
    b = SiteMetadata(community="B", elevation_m=123.0)
    assert a.merged_with(b).elevation_m == 0.0  # a real 0 m is not "blank"
    # but a genuinely missing field is still filled
    c = SiteMetadata(community="C")
    assert c.merged_with(b).elevation_m == 123.0


def test_ves_segments_tolerate_blank_mn():
    """A blank (NaN) MN cell must not start a spurious one-point segment."""
    site = SiteMetadata(community="T")
    ab2 = np.array([1.5, 2.0, 3.0, 4.0, 6.0, 9.0])
    mn = np.array([0.5, 0.5, 0.5, np.nan, 5.0, 5.0])
    rho = np.array([100.0, 110.0, 120.0, 125.0, 130.0, 140.0])
    s = VESSounding(site=site, sounding_id="V1", ab2=ab2, mn=mn, rho_app=rho)
    segs = s.segments()
    assert len(segs) == 2  # the NaN folds into the running segment, not its own
    assert list(segs[0]) == [0, 1, 2, 3] and list(segs[1]) == [4, 5]
    # an entirely absent MN column collapses to one segment, not N of them
    s2 = VESSounding(site=site, sounding_id="V2", ab2=ab2, mn=np.full(6, np.nan),
                     rho_app=rho)
    assert len(s2.segments()) == 1


# --- portfolio: success rate cannot exceed 100% -----------------------------

def test_portfolio_success_rate_bounded():
    from groundwater.portfolio import portfolio_stats

    summaries = [
        {"status": "dry", "total_depth_m": 50},
        {"status": "successful, productive borehole"},   # no depth -> not drilled
        {"status": "successful"},                          # no depth -> not drilled
    ]
    stats = portfolio_stats(summaries)
    assert stats["n_drilled"] == 1
    assert stats["success_rate"] == 0.0  # the only drilled hole was dry
    assert stats["success_rate"] <= 100.0


# --- VES ingestion: blank spacer row must not truncate the table ------------

def test_ves_blank_spacer_row_does_not_truncate(tmp_path):
    from groundwater.ingestion.ves import read_ves_csv

    csv_text = (
        "No.,AB/2 (m),MN (m),rho (ohm-m)\n"
        "1,1.5,0.5,100\n"
        "2,2.0,0.5,110\n"
        "3,3.0,0.5,120\n"
        ",,,\n"              # blank spacer at the Schlumberger segment change
        "4,4.0,5,130\n"
        "5,6.0,5,140\n"
    )
    path = tmp_path / "ves.csv"
    path.write_text(csv_text)
    s = read_ves_csv(path)
    assert s is not None
    assert list(s.ab2) == [1.5, 2.0, 3.0, 4.0, 6.0]  # deep branch preserved
    # two consecutive blank rows still terminate the table
    csv_text2 = csv_text.replace(",,,\n4,4.0", ",,,\n,,,\n4,4.0")
    path2 = tmp_path / "ves2.csv"
    path2.write_text(csv_text2)
    s2 = read_ves_csv(path2)
    assert list(s2.ab2) == [1.5, 2.0, 3.0]


# --- VES: IPI2WIN fit-error parsing -----------------------------------------

def test_ipi2win_find_err_ignores_unrelated_words():
    from groundwater.ves.ipi2win import _find_err

    assert _find_err([["Terrain slope: 8 deg"]]) is None
    assert _find_err([["Field supervisor: Errol 5"]]) is None
    assert _find_err([["ERR = 3.5%"]]) == 3.5
    assert _find_err([["ERR (%): 21.5"]]) == 21.5


# --- VES: recommended drilling depth never exceeds the investigated depth ----

def test_max_drilling_depth_within_investigation():
    from groundwater.ves import interpret_model

    model = LayeredModel(np.array([300.0, 40.0]), np.array([6.0]))
    interp = interpret_model(None, model)
    assert interp.max_drilling_depth_m <= interp.investigation_depth_m


# --- design: geometry stays valid, dry intervals are not screened -----------

def test_dry_interval_not_screened():
    from groundwater.design import design_borehole
    from groundwater.models import DrillingLog, LithologyInterval

    log = DrillingLog(
        site=SiteMetadata(community="T"),
        total_depth_m=40.0,
        water_strikes_m=[],
        intervals=[
            LithologyInterval(0.0, 6.0, "laterite"),
            LithologyInterval(6.0, 30.0, "hard granite, dry, no water struck"),
            LithologyInterval(30.0, 40.0, "fractured granite, water-bearing"),
        ],
    )
    design = design_borehole(log=log, static_water_level_m=8.0)
    # the explicitly-dry interval must not be a screen target; the fractured
    # water-bearing interval must be
    assert any(s.top_m >= 30.0 - 1e-9 for s in design.segments if s.kind == "screen")
    assert not any(
        6.0 <= s.top_m < 30.0 and s.kind == "screen" for s in design.segments
    )


def test_shallow_hole_deep_swl_produces_valid_geometry():
    """A SWL too deep for the hole must not yield a negative-length screen or
    casing past the hole bottom - the geometry must stay valid and be flagged."""
    from groundwater.design import design_borehole
    from groundwater.models import DrillingLog

    log = DrillingLog(site=SiteMetadata(community="T"), total_depth_m=18.0,
                      water_strikes_m=[])
    design = design_borehole(log=log, static_water_level_m=14.0)
    for seg in design.segments:
        assert seg.bottom_m > seg.top_m           # no negative-length segment
        assert 0.0 <= seg.top_m <= design.total_depth_m + 1e-9
        assert seg.bottom_m <= design.total_depth_m + 1e-9
    assert design.total_screen_length_m > 0.0
    assert any(f.code == "hole_too_shallow" for f in design.flags)


# --- app: a loaded project with a non-string UTM zone must not brick it ------

def test_app_survives_integer_meta_zone():
    """A project file storing meta_zone as an int (e.g. 29) must not raise on
    every sidebar rerun."""
    from pathlib import Path

    streamlit = pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app_path = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
    at = AppTest.from_file(app_path, default_timeout=600)
    at.session_state["meta_zone"] = 29  # int, as an older/hand-edited file might store
    at.run()
    assert not at.exception


# --- robustness one-liners --------------------------------------------------

def test_loan_schedule_rejects_zero_term():
    from groundwater.costing.enterprise import loan_schedule

    with pytest.raises(ValueError):
        loan_schedule(10000, 5, 0)
    # a normal loan still works
    summ = loan_schedule(10000, 10, 5)
    assert summ.monthly_payment_usd > 0


def test_site_location_map_empty_points_clear_error(tmp_path):
    from groundwater.mapping import site_location_map

    with pytest.raises(ValueError):
        site_location_map([], zone=28, path=tmp_path / "x.png")


def test_coordinate_flag_uses_west_hemisphere():
    """Sierra Leone longitudes are negative and must read 'W', not 'E'."""
    from groundwater.ingestion.checks import _fmt_latlon

    text = _fmt_latlon(8.5859, -12.4562)
    assert text == "8.5859 N, 12.4562 W"
