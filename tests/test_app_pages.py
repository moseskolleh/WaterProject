"""The Streamlit app runs only the page on screen (PLAN.md step 1.1).

Every page used to run on every rerun and was then hidden, which kept
three things true for free: a widget kept its value because it was drawn
every time, a result that follows from another (the design from the
pumping test) was re-derived whichever page was on screen, and a file in
an uploader stayed there. These tests hold the app to all three now that
only one page runs, and check the rules in ``app/state.py`` that keep them.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def _app_sources():
    return sorted(APP.rglob("*.py"))


def _key_prefix(node) -> str | None:
    """A widget key as written: the string, or an f-string's fixed start."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        head = node.values[0] if node.values else None
        if isinstance(head, ast.Constant):
            return head.value
        return ""
    return None


def _calls(tree, names):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in names:
                yield name, node


def _key_of(name, call):
    for kw in call.keywords:
        if kw.arg == "key":
            return _key_prefix(kw.value)
    if name == "kept_upload" and len(call.args) >= 2:
        return _key_prefix(call.args[1])
    return None


def test_no_button_uploader_or_editor_key_is_carried():
    """Streamlit refuses a value set on a button, an uploader or a data
    editor, so a carried key that matched one would take its page down."""
    import state

    refused = {"button", "file_uploader", "kept_upload", "data_editor",
               "download_button", "form_submit_button", "depth_spine"}
    seen = []
    for path in _app_sources():
        for name, call in _calls(ast.parse(path.read_text()), refused):
            key = _key_of(name, call)
            if key is None:
                continue
            seen.append(key)
            # an f-string's fixed start is tested with a sample suffix
            assert not state.carried(key) and not state.carried(key + "x"), (
                f"{path.name}: {name} key {key!r} matches a carried key")
    assert "run_cost" in seen and "upload_" in seen and "ho_committee" in seen


def test_a_fragment_holds_no_saved_input():
    """A fragment reruns without the sidebar, so its Save project button
    would carry a stale value of any input the project file saves."""
    from groundwater.project_io import PERSIST_PREFIXES

    widgets = {"number_input", "text_input", "text_area", "selectbox", "radio",
               "checkbox", "toggle", "slider", "select_slider", "multiselect",
               "date_input", "data_editor"}
    fragments = 0
    for path in _app_sources():
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.FunctionDef):
                continue
            decorated = any(
                (isinstance(d, ast.Attribute) and d.attr == "fragment")
                or (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "fragment")
                for d in node.decorator_list)
            if not decorated:
                continue
            fragments += 1
            for name, call in _calls(node, widgets):
                key = _key_of(name, call)
                assert key is not None, f"{path.name}:{node.name} has an unkeyed {name}"
                assert not key.startswith(PERSIST_PREFIXES), (
                    f"{path.name}:{node.name}: {key!r} is saved in the project file")
    assert fragments >= 4


def test_no_button_is_saved_in_the_project_file():
    """A button holds False between clicks, so one keyed with a saved prefix
    went into the project file, and Streamlit refuses a button's value set
    through session state: loading that file took the page down."""
    from groundwater.project_io import PERSIST_PREFIXES

    import shared

    buttons = set()
    for path in _app_sources():
        for name, call in _calls(ast.parse(path.read_text()),
                                 {"button", "download_button", "form_submit_button"}):
            key = _key_of(name, call)
            if key is not None and key.startswith(PERSIST_PREFIXES):
                buttons.add(key)
    assert buttons, "the guided start's buttons are keyed wiz_"
    assert buttons == set(shared.UNSAVED_BUTTONS)


slow = pytest.mark.slow
streamlit = pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from conftest import goto  # noqa: E402

APP_FILE = str(APP / "streamlit_app.py")


@slow
def test_inputs_survive_a_visit_to_another_page(sample_data):
    """Typed on one page, still there after another page has been open, and
    so still in the project file saved from there."""
    at = AppTest.from_file(APP_FILE, default_timeout=600)
    at.run()
    goto(at, "Costing & BoQ")
    at.number_input(key="cost_distance").set_value(240.0)
    at.run()
    goto(at, "Handover")
    at.text_input(key="ho_pump_type").set_value("India Mark II")
    at.run()
    goto(at, "Supervision")
    at.number_input(key="fx_dev").set_value(80.0)
    at.run()
    goto(at, "Pumping test")
    at.selectbox(key="sample_pump").select("kuntolo/kuntolo_step_test.xlsx")
    at.run()
    at.number_input(key="q_2").set_value(3.5)
    at.run()

    goto(at, "Overview")
    at.run()  # and a rerun there, the run after which a widget's value goes
    # in session state, which is what the project file is written from
    for key, value in (("cost_distance", 240.0), ("ho_pump_type", "India Mark II"),
                       ("fx_dev", 80.0), ("q_2", 3.5)):
        assert at.session_state[key] == value, key

    # back on each page, the widget shows what was typed
    goto(at, "Costing & BoQ")
    assert at.number_input(key="cost_distance").value == 240.0
    goto(at, "Pumping test")
    assert at.selectbox(key="sample_pump").value == "kuntolo/kuntolo_step_test.xlsx"
    assert at.number_input(key="q_2").value == 3.5
    steps = at.session_state["pump_analysis"].test.steps
    assert steps[1].discharge_m3_per_h == 3.5


@slow
def test_an_uploaded_file_waits_for_its_page(sample_data):
    """Streamlit forgets an uploader's file when its page is not drawn; the
    upload is kept, so coming back does not mean uploading it again."""
    csv_text = (
        "lat_deg,lon_deg,status_clean,water_source_clean\n"
        "8.8817,-12.0442,Functional,Borehole\n"
        "8.8820,-12.0450,Non-Functional,Borehole\n"
    )
    at = AppTest.from_file(APP_FILE, default_timeout=600)
    at.session_state["nav"] = "Coverage gap"
    at.run()
    at.file_uploader(key="cov_csv").set_value([("wpdx.csv", csv_text.encode(), "text/csv")])
    at.run()
    assert not at.exception, at.exception

    def ranking():
        return next((t.value for t in at.dataframe if "District" in t.value.columns
                     and "Rank" in t.value.columns), None)

    assert ranking() is not None
    goto(at, "Overview")
    at.run()
    goto(at, "Coverage gap")
    for _ in range(2):  # on coming back, and on every rerun there after
        back = ranking()
        assert back is not None and len(back) == 16
        assert dict(zip(back["District"], back["Functional"], strict=True))["Bombali"] == 1
        assert any("uploaded earlier" in str(c.value) for c in at.caption)
        at.run()
    # Remove does what clearing the uploader did
    at.button(key="cov_csv_forget").click()
    at.run()
    assert ranking() is None
    at.run()
    assert ranking() is None
    # the join is cached on the export's content, not in this session
    assert "_cov_join_memo" not in at.session_state


@slow
def test_the_design_follows_a_pumping_test_loaded_after_it(sample_data):
    """The design page re-derived the design from the pumping test on every
    run, whichever page was on screen. A test loaded after the drilling log
    still reaches the design, and the costing, without a visit to the design
    page."""
    at = AppTest.from_file(APP_FILE, default_timeout=600)
    at.session_state["nav"] = "Borehole design"
    at.run()
    at.selectbox(key="sample_log").select("dr_timbo/dr_timbo_drilling_log.xlsx")
    at.run()
    assert at.session_state["borehole_design"].pump_intake_m is None

    goto(at, "Pumping test")
    at.selectbox(key="sample_pump").select("dr_timbo/dr_timbo_constant_test.xlsx")
    at.run()
    at.number_input(key="seasonal_range").set_value(8.0)
    at.run()
    goto(at, "Costing & BoQ")

    analysis = at.session_state["pump_analysis"]
    design = at.session_state["borehole_design"]
    level = analysis.test.static_water_level_m
    assert design.static_water_level_m == pytest.approx(level, abs=0.01)
    assert at.session_state["design_swl"] == pytest.approx(level, abs=0.01)
    assert design.pump_intake_m is not None
    assert design.pump_intake_m > analysis.yield_recommendation.pump_installation_depth_m

    # and it is the design the design page draws when it is opened
    goto(at, "Borehole design")
    assert at.session_state["borehole_design"].pump_intake_m == pytest.approx(
        design.pump_intake_m)


@slow
def test_a_project_saved_on_the_guided_start_loads_there(sample_data):
    """Files saved before the buttons were left out carry wiz_next: false.
    Loading one with the guided start on screen raised Streamlit's refusal
    of a button value set through session state; it is now left out."""
    import groundwater
    from groundwater.project_io import serialize_project

    at = AppTest.from_file(APP_FILE, default_timeout=600)
    at.session_state["nav"] = "Guided start"
    at.run()
    at.text_input(key="meta_community").set_value("Kuntolo")
    at.run()
    # what Save project wrote from this page before: the inputs, and the
    # button's False with them
    assert at.session_state["wiz_next"] is False
    saved = serialize_project({"meta_community": "Kuntolo", "wiz_step": 0,
                               "wiz_next": at.session_state["wiz_next"]},
                              groundwater.__version__)
    assert b"wiz_next: false" in saved

    at.file_uploader(key="project_upload").set_value(
        ("kuntolo_project.yaml", saved, "application/x-yaml"))
    at.run()
    at.button(key="project_load").click()
    at.run()
    assert not at.exception, at.exception
    assert any("Project loaded" in str(s.value) for s in at.success)
    assert at.session_state["meta_community"] == "Kuntolo"
