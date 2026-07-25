"""Tests for the project-workspace redesign: sidebar navigation and the
Overview dashboard.

The redesign replaced the flat tab bar with grouped sidebar navigation
(one radio per lifecycle group) over pages that all render on every run;
only visibility changes with the selection. These tests pin down the
navigation contract: a single active page, group radios kept mutually
exclusive, and the Overview quick actions moving the selection.
"""

from pathlib import Path

import pytest


def test_built_reports_stay_downloadable_and_the_app_loads_offline():
    """A build button is true for one rerun, so its download button vanished
    the moment the user touched anything else and the report had to be rebuilt.
    Built files are now remembered and listed under Deliverables.

    Also checks the stylesheet carries no render-blocking webfont @import:
    everything else in the toolkit works offline, and a CSS @import made the
    whole page wait on fonts.googleapis.com over a bad link.
    """
    from pathlib import Path

    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app_file = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"
    assert "@import url(" not in app_file.read_text()

    at = AppTest.from_file(str(app_file), default_timeout=600)
    at.run()
    at.selectbox(key="sample_ves").select("rokel/rokel_ves.xlsx")
    at.run()
    at.button(key="run_ves").click()
    at.run()
    at.button(key="build_geo_report").click()
    at.run()
    assert not at.exception
    assert at.session_state["artifacts"], "the built report must be remembered"

    # navigate away: the download used to disappear here
    at.selectbox(key="sample_pump").select("dr_timbo/dr_timbo_constant_test.xlsx")
    at.run()
    assert at.session_state["artifacts"]
    assert any("Deliverables" in str(s.value) for s in at.subheader)


def test_every_page_offers_the_next_lifecycle_step():
    """Only the Overview had navigation. Every other page dead-ended, so after
    reading the recommended drilling depth there was no route to Costing."""
    from pathlib import Path

    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    app_file = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
    at = AppTest.from_file(app_file, default_timeout=600)
    at.run()
    assert not at.exception
    labels = {b.label for b in at.button if b.key and b.key.startswith("next_")}
    assert {
        "Cost this borehole →", "Start supervision →",
        "Assess water quality →", "Build the handover →",
    } <= labels

streamlit = pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


@pytest.fixture(scope="module")
def at(sample_data):
    at = AppTest.from_file(APP, default_timeout=600)
    at.run()
    assert not at.exception, at.exception
    return at


def test_overview_is_the_default_page(sample_data):
    # a fresh instance: the shared module fixture may have been navigated
    # away from the default by another test
    at = AppTest.from_file(APP, default_timeout=600)
    at.run()
    assert not at.exception
    assert at.session_state["nav"] == "Overview"
    assert at.radio(key="nav_project").value == "Overview"
    # the other groups carry no selection
    for group in ("nav_investigation", "nav_testing", "nav_delivery",
                  "nav_area_analysis"):
        assert at.radio(key=group).value is None


def test_group_radio_switches_the_active_page(at):
    at.radio(key="nav_testing").set_value("Pumping test")
    at.run()
    assert not at.exception
    assert at.session_state["nav"] == "Pumping test"
    # the previously selected group resets, keeping one active page
    assert at.radio(key="nav_project").value is None
    assert at.radio(key="nav_testing").value == "Pumping test"

    at.radio(key="nav_delivery").set_value("Costing & BoQ")
    at.run()
    assert at.session_state["nav"] == "Costing & BoQ"
    assert at.radio(key="nav_testing").value is None


def test_every_page_still_renders_each_run(at):
    """Hidden pages keep rendering (widgets from all pages coexist)."""
    for key in ("sample_ves", "sample_pump", "sample_wq", "sample_log"):
        assert at.selectbox(key=key) is not None
    assert any(b.key == "run_cost" for b in at.button)
    assert any(b.key == "gen_templates" for b in at.button)


def test_overview_quick_actions_navigate(sample_data):
    at = AppTest.from_file(APP, default_timeout=600)
    at.run()
    assert not at.exception
    # empty project: the getting-started actions are offered
    at.button(key="ov_go_guide").click()
    at.run()
    assert not at.exception
    assert at.session_state["nav"] == "Guided start"
    assert at.radio(key="nav_project").value == "Guided start"


def test_overview_dashboard_after_analyses(sample_data):
    """With recomputed analyses, the dashboard reflects the lifecycle."""
    at = AppTest.from_file(APP, default_timeout=600)
    at.run()
    at.session_state["src_ves"] = {"sample": "rokel/rokel_ves.xlsx"}
    at.session_state["src_pump"] = {
        "sample": "dr_timbo/dr_timbo_constant_test.xlsx"}
    at.session_state["src_log"] = {
        "sample": "dr_timbo/dr_timbo_drilling_log.xlsx"}
    at.session_state["_recompute_pending"] = True
    at.run()
    assert not at.exception
    assert "ves_results" in at.session_state
    assert "pump_analysis" in at.session_state
    # the overview markdown includes the lifecycle stepper and cards
    rendered = " ".join(str(m.value) for m in at.markdown)
    assert "gw-steps" in rendered
    assert "Pumping test" in rendered
