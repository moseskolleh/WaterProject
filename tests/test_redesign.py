"""Tests for the project-workspace redesign: sidebar navigation and the
Overview dashboard.

The redesign replaced the flat tab bar with grouped sidebar navigation
(one radio per lifecycle group). The pages all rendered on every run and
only their visibility changed with the selection, until PLAN.md step 1.1
made the selection pick the one page that runs. These tests pin down the
navigation contract: a single active page, group radios kept mutually
exclusive, the Overview quick actions moving the selection, and no page
running while another is on screen.
"""

from pathlib import Path

import pytest

# Every test here drives the real app script through AppTest.
pytestmark = pytest.mark.slow


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

    from conftest import goto

    at = AppTest.from_file(str(app_file), default_timeout=600)
    at.session_state["nav"] = "Geophysics (VES)"
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
    goto(at, "Pumping test")
    at.selectbox(key="sample_pump").select("dr_timbo/dr_timbo_constant_test.xlsx")
    at.run()
    assert at.session_state["artifacts"]
    goto(at, "Overview")
    assert any("Deliverables" in str(s.value) for s in at.subheader)


def test_every_page_offers_the_next_lifecycle_step():
    """Only the Overview had navigation. Every other page dead-ended, so after
    reading the recommended drilling depth there was no route to Costing."""
    from pathlib import Path

    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    from conftest import goto

    app_file = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
    at = AppTest.from_file(app_file, default_timeout=600)
    at.run()
    assert not at.exception
    labels = set()
    for page in ("Geophysics (VES)", "Pumping test", "Costing & BoQ", "Supervision"):
        goto(at, page)
        labels |= {b.label for b in at.button if b.key and b.key.startswith("next_")}
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


def test_only_the_page_on_screen_runs(sample_data, monkeypatch):
    """PLAN.md step 1.1: every page used to run on every rerun and was then
    hidden, so one click on the costing page re-parsed four workbooks and
    redrew a dozen figures. Each page's function is wrapped to record that
    it ran; opening each page in turn, with every sample loaded, runs that
    page and no other."""
    import importlib

    from conftest import goto

    at = AppTest.from_file(APP, default_timeout=600)
    at.run()
    for page, key, sample in (
            ("Geophysics (VES)", "sample_ves", "rokel/rokel_ves.xlsx"),
            ("Pumping test", "sample_pump", "dr_timbo/dr_timbo_constant_test.xlsx"),
            ("Water quality", "sample_wq", "dr_timbo/dr_timbo_water_quality.xlsx"),
            ("Borehole design", "sample_log", "dr_timbo/dr_timbo_drilling_log.xlsx")):
        goto(at, page)
        at.selectbox(key=key).select(sample)
        at.run()
    assert not at.exception, at.exception

    # the app has put its folder on the path, so its views import here as
    # they do in the app
    views = importlib.import_module("views")
    ran: list[str] = []

    def recording(title, render):
        def page():
            ran.append(title)
            render()
        return page

    for title, _, name in views.MODULES:
        module = importlib.import_module(f"views.{name}")
        monkeypatch.setattr(module, "render", recording(title, module.render))

    titles = [title for title, _, _ in views.MODULES]
    assert titles, "no pages registered"
    for title in titles:
        ran.clear()
        at.session_state["nav"] = title
        at.run()
        assert not at.exception, (title, at.exception)
        at.run()  # and a rerun on the page, as a click there makes
        assert not at.exception, (title, at.exception)
        assert ran == [title, title], (title, ran)


def test_every_listed_page_has_a_view():
    """The sidebar lists every page, and every page it lists can be opened."""
    import sys

    app_dir = str(Path(APP).parent)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    import shared
    import views

    listed = [page for _, pages in shared.NAV_GROUPS for page in pages]
    assert sorted(listed) == sorted(title for title, _, _ in views.MODULES)
    for _, url, render in views.page_functions():
        assert callable(render) and url


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
