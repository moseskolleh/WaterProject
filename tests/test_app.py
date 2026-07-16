"""End to end tests of the Streamlit app using the bundled samples.

These drive the same flow a demo visitor uses: pick a bundled sample,
run the analysis, build the report. AppTest executes the real app
script, so every tab's code path runs.
"""

from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


@pytest.fixture(scope="module")
def app(sample_data):
    at = AppTest.from_file(APP, default_timeout=600)
    at.run()
    assert not at.exception, at.exception
    return at


def test_app_renders(app):
    assert app.title[0].value == "Groundwater Investigation Toolkit"
    # bundled samples offered in every data tab
    for key in ("sample_ves", "sample_pump", "sample_wq", "sample_log"):
        assert app.selectbox(key=key) is not None


def test_ves_flow_with_sample(app):
    app.selectbox(key="sample_ves").select("rokel/rokel_ves.xlsx")
    app.run()
    assert not app.exception
    # the Port Loko copy-over error in the sample is surfaced as a warning
    warnings = " ".join(str(w.value) for w in app.warning)
    assert "Port Loko" in warnings

    app.button(key="run_ves").click()
    app.run()
    assert not app.exception
    assert "ves_results" in app.session_state
    soundings, results, interps = app.session_state["ves_results"]
    assert len(results) == 2 and results[0].fit_error_percent < 21.5

    app.button(key="build_geo_report").click()
    app.run()
    assert not app.exception


def test_pumping_flow_with_sample(app):
    app.selectbox(key="sample_pump").select("dr_timbo/dr_timbo_constant_test.xlsx")
    app.run()
    assert not app.exception
    analysis = app.session_state["pump_analysis"]
    assert analysis.transmissivity_m2_per_day is not None
    app.button(key="build_pump_report").click()
    app.run()
    assert not app.exception


def test_pending_pumping_sample(app):
    app.selectbox(key="sample_pump").select("kuntolo/kuntolo_step_test.xlsx")
    app.run()
    assert not app.exception
    analysis = app.session_state["pump_analysis"]
    assert analysis.transmissivity_m2_per_day is None  # discharge pending


def test_quality_flow_with_sample(app):
    app.selectbox(key="sample_wq").select("dr_timbo/dr_timbo_water_quality.xlsx")
    app.run()
    assert not app.exception
    errors = " ".join(str(e.value) for e in app.error)
    assert "Manganese" in errors  # health exceedance verdict
    app.button(key="build_wq_report").click()
    app.run()
    assert not app.exception


def test_design_flow_with_sample(app):
    app.selectbox(key="sample_log").select("dr_timbo/dr_timbo_drilling_log.xlsx")
    app.run()
    assert not app.exception


def test_costing_flow(app):
    app.button(key="run_cost").click()
    app.run()
    assert not app.exception
    estimate = app.session_state["cost_estimate"]
    assert estimate.direct_cost_usd > 0
    assert estimate.items
    app.button(key="build_cost_report").click()
    app.run()
    assert not app.exception


def test_supervision_flow(app):
    from groundwater.supervision import load_checklists

    first = load_checklists()[0]
    app.radio(key=f"chk_{first.item_id}").set_value("Yes")
    app.run()
    assert not app.exception
    app.button(key="build_sup_report").click()
    app.run()
    assert not app.exception


def test_templates_tab(app):
    app.button(key="gen_templates").click()
    app.run()
    assert not app.exception
