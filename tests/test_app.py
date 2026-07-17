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


def test_programme_flow(app):
    app.button(key="run_programme").click()
    app.run()
    assert not app.exception
    programme, gantt_path = app.session_state["programme_estimate"]
    assert programme.n_attempted >= programme.n_successful
    assert gantt_path.exists()


def test_handover_flow(app):
    app.button(key="build_handover").click()
    app.run()
    assert not app.exception


def test_maps_flow(app):
    app.button(key="run_maps").click()
    app.run()
    assert not app.exception
    paths = app.session_state["map_paths"]
    assert len(paths) >= 2 and all(p.exists() for p in paths)


def test_project_state_tracked(app):
    """The state the project file persists is maintained by the app."""
    assert "rates_overrides" in app.session_state
    assert app.session_state["rates_overrides"], "working rates not tracked"


def test_guided_wizard_flow(app):
    """Walk the wizard: site details -> siting -> costing -> done."""
    # step 0 gate: needs community and district from the sidebar
    app.text_input(key="meta_community").set_value("Kuntolo")
    app.selectbox(key="meta_district").select("Bombali")
    app.run()
    assert not app.exception
    app.button(key="wiz_next").click()
    app.run()
    assert app.session_state["wiz_step"] == 1

    # step 1: run the siting analysis on the bundled sample
    app.selectbox(key="sample_wiz_ves").select("rokel/rokel_ves.xlsx")
    app.run()
    app.button(key="wiz_run_ves").click()
    app.run()
    assert not app.exception
    assert "ves_results" in app.session_state
    # the fresh result must unlock Next in the same rerun (review fix)
    next_button = app.button(key="wiz_next")
    assert not getattr(next_button, "disabled", next_button.proto.disabled)
    app.button(key="wiz_next").click()
    app.run()
    assert app.session_state["wiz_step"] == 2

    # step 2: costing prefilled from the siting result
    app.button(key="wiz_cost_run").click()
    app.run()
    assert not app.exception
    assert app.session_state["cost_estimate"].direct_cost_usd > 0
    app.button(key="wiz_next").click()
    app.run()
    assert app.session_state["wiz_step"] == 3


def test_wizard_unlocks_after_first_ves_run(sample_data):
    """Regression: the first siting run must enable Next immediately.

    Uses a fresh app instance (no prior VES results) to reproduce the
    reported state: reaching step 1 cold and running the analysis once.
    """
    at = AppTest.from_file(APP, default_timeout=600)
    at.run()
    at.text_input(key="meta_community").set_value("Kuntolo")
    at.selectbox(key="meta_district").select("Bombali")
    at.run()
    at.button(key="wiz_next").click()
    at.run()
    at.selectbox(key="sample_wiz_ves").select("rokel/rokel_ves.xlsx")
    at.run()
    at.button(key="wiz_run_ves").click()
    at.run()
    assert not at.exception
    next_button = at.button(key="wiz_next")
    assert not getattr(next_button, "disabled", next_button.proto.disabled)


def test_wizard_grace_survives_until_costing_step(sample_data):
    """Regression: a project loaded on a step other than costing must
    keep its restored wizard costing values when the costing step is
    finally visited, even though the load rerun has long passed."""
    at = AppTest.from_file(APP, default_timeout=600)
    # state as the project loader would leave it: saved at the final
    # step with a siting-derived signature that the fresh session
    # cannot reproduce, plus the wizard grace marker
    at.session_state["wiz_step"] = 3
    at.session_state["wiz_cost_depth"] = 85.0
    at.session_state["wiz_cost_over"] = 12.0
    at.session_state["wiz_prefill_sig"] = "72.0:24.0"
    at.session_state["_wiz_load_grace"] = True
    at.run()  # the load rerun: costing block does not execute
    assert not at.exception
    at.session_state["wiz_step"] = 2  # user navigates back to costing
    at.run()
    assert not at.exception
    assert at.session_state["wiz_cost_depth"] == 85.0
    assert at.session_state["wiz_cost_over"] == 12.0
    # grace is consumed: a genuine source change afterwards resets
    assert "_wiz_load_grace" not in at.session_state


def test_wizard_grace_cleared_by_siting_change(sample_data):
    """Regression: a siting change made after loading a project must
    invalidate the load grace, so costing follows the new depth
    instead of the stale loaded values."""
    at = AppTest.from_file(APP, default_timeout=600)
    at.session_state["wiz_step"] = 1
    at.session_state["wiz_cost_depth"] = 85.0
    at.session_state["wiz_cost_over"] = 12.0
    at.session_state["wiz_prefill_sig"] = "72.0:24.0"
    at.session_state["_wiz_load_grace"] = True
    at.run()
    assert not at.exception
    # the user changes the planned depth on the siting step
    at.number_input(key="wiz_manual_depth").set_value(95.0)
    at.run()
    assert "_wiz_load_grace" not in at.session_state
    at.session_state["wiz_step"] = 2
    at.run()
    assert not at.exception
    # costing adopted the new siting depth, not the stale loaded value
    assert at.session_state["wiz_cost_depth"] == 95.0


def test_templates_tab(app):
    app.button(key="gen_templates").click()
    app.run()
    assert not app.exception
