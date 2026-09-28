"""The saved inversions a project file carries (PLAN.md step 1.6).

Reopening a saved survey must not invert it again, and a changed reading, a
changed setting, another engine or a damaged entry must. The Rokel survey is
inverted once for the module; every later "inversion" is counted and served
from that one, so the counts are what is tested and the suite stays quick.
"""

from __future__ import annotations

import dataclasses
import io

import numpy as np
import openpyxl
import pytest

import groundwater.recompute as recompute_module
import groundwater.ves.cache as cache_module
from groundwater.config import Config
from groundwater.project_io import deserialize_project, serialize_project
from groundwater.recompute import recompute_results
from groundwater.ves import invert_sounding
from groundwater.ves.cache import (
    cache_entry,
    cached_inversion,
    engine_version,
    inversion_key,
)

ROKEL = {"ves": {"sample": "rokel/rokel_ves.xlsx"}}


@pytest.fixture(scope="module")
def first_load(sample_data, tmp_path_factory):
    """The Rokel survey as a first load leaves it: inverted, and saved."""
    tmp = tmp_path_factory.mktemp("first")
    out = recompute_results(ROKEL, sample_root=sample_data, tmp_dir=tmp)
    session = {"src_ves": ROKEL["ves"], "q_1": 2.5,
               "inversion_cache": out["inversion_cache"]}
    return out, serialize_project(session, "0.3.0")


@pytest.fixture()
def counted(monkeypatch, first_load):
    """Count the inversions recompute asks for, answering from the first load."""
    soundings, results, _ = first_load[0]["ves_results"]
    answers = {s.sounding_id: r for s, r in zip(soundings, results, strict=True)}
    calls: list[str] = []

    def invert(sounding, config=None):
        calls.append(sounding.sounding_id)
        return answers[sounding.sounding_id]

    monkeypatch.setattr(recompute_module, "invert_sounding", invert)
    return calls


def _reopen(raw, sample_data, tmp_path, **kwargs):
    updates = deserialize_project(raw)
    return recompute_results(
        updates["sources"], sample_root=sample_data, tmp_dir=tmp_path,
        inversion_cache=updates.get("inversion_cache"), **kwargs,
    )


def _assert_same(a, b):
    """Two inversion results, equal to the last bit and in the same types."""
    for name in ("ab2", "rho_obs", "rho_calc", "rho_uncertainty_factor",
                 "h_uncertainty_factor"):
        assert np.array_equal(getattr(a, name), getattr(b, name)), name
    for name in ("fit_error_percent", "n_iterations", "converged", "trials", "shifts"):
        assert getattr(a, name) == getattr(b, name), name
        assert type(getattr(a, name)) is type(getattr(b, name)), name
    assert np.array_equal(a.model.resistivities, b.model.resistivities)
    assert np.array_equal(a.model.thicknesses, b.model.thicknesses)
    assert a.model.fit_error_percent == b.model.fit_error_percent
    assert a.model.method == b.model.method
    assert a.model.sounding_id == b.model.sounding_id
    assert np.array_equal(a.model.h_uncertainty_factor, b.model.h_uncertainty_factor)
    # one array, held by the model and the result, as the search returns it
    assert b.model.h_uncertainty_factor is b.h_uncertainty_factor


def test_a_saved_survey_carries_an_entry_per_sounding(first_load):
    out, raw = first_load
    soundings = out["ves_results"][0]
    assert len(out["inversion_cache"]) == len(soundings) == 2
    updates = deserialize_project(raw)
    assert updates["inversion_cache"] == out["inversion_cache"]
    # the file layout is unchanged otherwise: the same schema, one new key
    assert b"schema: 1\n" in raw


def test_reopening_a_saved_survey_inverts_nothing(first_load, counted, sample_data, tmp_path):
    out = _reopen(first_load[1], sample_data, tmp_path)
    assert counted == []
    assert out["recompute_diagnostics"]["issues"] == []
    for fresh, restored in zip(first_load[0]["ves_results"][1], out["ves_results"][1], strict=True):
        _assert_same(fresh, restored)
    first_ranks = [i.rank for i in first_load[0]["ves_results"][2]]
    assert [i.rank for i in out["ves_results"][2]] == first_ranks
    # and what it hands back to be saved is what it was given
    assert out["inversion_cache"] == first_load[0]["inversion_cache"]


def test_a_restored_inversion_is_the_one_the_search_returns(first_load):
    """No stand-in: the real search, and the entry rebuilt beside it."""
    soundings = first_load[0]["ves_results"][0]
    sounding = soundings[1]
    fresh = invert_sounding(sounding, Config().ves)
    key = inversion_key(sounding, Config().ves)
    _assert_same(fresh, cached_inversion(cache_entry(key, fresh), key, sounding))


def test_other_saved_inputs_keep_the_inversions(first_load, counted, sample_data, tmp_path):
    # a discharge typed on the pumping test page, and a pumping sheet added
    updates = deserialize_project(first_load[1])
    sources = dict(updates["sources"], pump={"sample": "kuntolo/kuntolo_step_test.xlsx"})
    out = recompute_results(
        sources, discharges={"1": 1.5, "2": 2.2, "3": 3.0},
        sample_root=sample_data, tmp_dir=tmp_path,
        inversion_cache=updates["inversion_cache"],
    )
    assert counted == []
    assert out["pump_analysis"].step_test is not None
    assert len(out["ves_results"][1]) == 2


def test_a_changed_reading_inverts_that_sounding_again(first_load, counted, sample_data,
                                                       tmp_path):
    book = openpyxl.load_workbook(sample_data / "rokel" / "rokel_ves.xlsx")
    sheet = book.worksheets[1]
    for row in sheet.iter_rows():
        if row[0].value == 1:
            row[3].value = str(float(row[3].value) * 1.05)
            break
    buffer = io.BytesIO()
    book.save(buffer)
    updates = deserialize_project(first_load[1])
    out = recompute_results(
        {"ves": {"name": "rokel_ves.xlsx", "bytes": buffer.getvalue()}},
        sample_root=sample_data, tmp_dir=tmp_path,
        inversion_cache=updates["inversion_cache"],
    )
    assert counted == [sheet.title]
    # the unchanged sounding is still found, and only today's two are kept
    assert len(out["inversion_cache"]) == 2
    assert set(out["inversion_cache"]) != set(updates["inversion_cache"])


def test_a_changed_setting_inverts_every_sounding(first_load, counted, sample_data, tmp_path):
    config = Config()
    config.ves = dataclasses.replace(config.ves, damping=0.021)
    _reopen(first_load[1], sample_data, tmp_path, config=config)
    assert counted == ["A (1)", "B (2)"]


def test_another_engine_finds_nothing(first_load, counted, monkeypatch, sample_data, tmp_path):
    # a new release, or the inversion's code changed without one
    monkeypatch.setattr(cache_module, "engine_version",
                        lambda: engine_version().replace("code ", "code 0"))
    _reopen(first_load[1], sample_data, tmp_path)
    assert counted == ["A (1)", "B (2)"]


def test_an_engine_that_cannot_be_named_caches_nothing(first_load, counted, monkeypatch,
                                                      sample_data, tmp_path):
    monkeypatch.setattr(cache_module, "engine_version", lambda: None)
    out = _reopen(first_load[1], sample_data, tmp_path)
    assert counted == ["A (1)", "B (2)"]
    assert out["inversion_cache"] == {}


def test_the_engine_is_named_by_its_code():
    name = engine_version()
    assert name.startswith("groundwater-python ")
    assert " numpy " in name and " scipy " in name and " code " in name


@pytest.mark.parametrize("damage", [
    "not a mapping", "no result", "result not a mapping", "digest changed",
    "reading edited", "edited and signed again", "layer count out of range",
    "a word for a number", "a bool for a count", "trials missing",
])
def test_a_damaged_entry_is_ignored(first_load, counted, sample_data, tmp_path, damage):
    raw = first_load[1]
    updates = deserialize_project(raw)
    key = sorted(updates["inversion_cache"])[0]
    entry = updates["inversion_cache"][key]
    record = entry["result"]
    if damage == "not a mapping":
        updates["inversion_cache"][key] = "junk"
    elif damage == "no result":
        del entry["result"]
    elif damage == "result not a mapping":
        entry["result"] = [1, 2, 3]
    elif damage == "digest changed":
        entry["digest"] = "0" * 64
    elif damage == "reading edited":
        record["resistivities"][0] *= 1.5
    else:
        if damage == "edited and signed again":
            record["resistivities"][0] *= 1.5
        elif damage == "layer count out of range":
            record["resistivities"] = [100.0] * 9
            record["thicknesses"] = [1.0] * 8
        elif damage == "a word for a number":
            record["resistivities"][0] = str(record["resistivities"][0])
        elif damage == "a bool for a count":
            record["n_iterations"] = True
        elif damage == "trials missing":
            record["trials"] = []
        # the digest a hand editor could work out: sound, and still not used
        entry["digest"] = cache_module._digest(key, record)
    out = recompute_results(
        updates["sources"], sample_root=sample_data, tmp_dir=tmp_path,
        inversion_cache=updates["inversion_cache"],
    )
    assert len(counted) == 1
    assert out["recompute_diagnostics"]["issues"] == []
    # the entry that was not used is replaced by a sound one
    assert out["inversion_cache"] == first_load[0]["inversion_cache"]


def test_a_malformed_cache_in_the_file_is_ignored(first_load, counted, sample_data, tmp_path):
    raw = first_load[1].replace(b"inversion_cache:", b"inversion_cache: [1, 2]\nold_cache:")
    updates = deserialize_project(raw)
    assert "inversion_cache" not in updates
    _reopen(raw, sample_data, tmp_path)
    assert counted == ["A (1)", "B (2)"]


def test_a_file_without_soundings_saves_no_cache():
    raw = serialize_project({"meta_community": "Njala", "inversion_cache": {}}, "0.3.0")
    assert b"inversion_cache" not in raw
    assert "inversion_cache" not in deserialize_project(raw)


def test_the_command_line_reopens_a_saved_survey_without_inverting(
        first_load, counted, sample_data, tmp_path, capsys):
    from groundwater.cli import main

    project = tmp_path / "rokel.yaml"
    project.write_bytes(first_load[1])
    code = main(["recompute", str(project), "--sample-root", str(sample_data),
                 "--tmp-dir", str(tmp_path)])
    assert code == 0, capsys.readouterr().out
    assert counted == []


def _sounding(**changes):
    from groundwater.models import SiteMetadata, VESSounding

    fields = dict(site=SiteMetadata(), sounding_id="V1",
                  ab2=[1.0, 2.0, 3.0, 5.0, 8.0], mn=[0.5, 0.5, 0.5, 2.0, 2.0],
                  rho_app=[100.0, 90.0, 80.0, 70.0, 60.0])
    fields.update(changes)
    return VESSounding(**fields)


@pytest.mark.parametrize("change", [
    {"sounding_id": "V2"},
    {"array_type": "wenner"},
    {"ab2": [1.0, 2.0, 3.0, 5.0, 8.5]},
    # MN is read only by the splice, and a changed one moves where the
    # segments join
    {"mn": [0.5, 0.5, 2.0, 2.0, 2.0]},
    {"mn": [0.5, 0.5, 0.5, float("nan"), 2.0]},
    {"rho_app": [100.0, 90.0, 80.0, 70.0, 61.0]},
    # the same numbers split differently between the arrays
    {"ab2": [1.0, 2.0, 3.0, 5.0], "mn": [8.0, 0.5, 0.5, 0.5, 2.0, 2.0]},
])
def test_every_input_of_the_inversion_is_in_the_key(change):
    assert inversion_key(_sounding(**change)) != inversion_key(_sounding())


@pytest.mark.parametrize("field", [
    f.name for f in dataclasses.fields(Config().ves)
])
def test_every_setting_is_in_the_key(field):
    config = Config().ves
    value = getattr(config, field)
    other = (value[0] * 1.5, value[1]) if isinstance(value, tuple) else value * 2 + 1
    changed = dataclasses.replace(config, **{field: other})
    assert inversion_key(_sounding(), changed) != inversion_key(_sounding(), config)


def test_a_sounding_the_cache_cannot_key_is_inverted_not_lost(
        first_load, counted, sample_data, tmp_path):
    # a setting the canonical encoding cannot write: the key is None, the
    # cache is off for the run, and every sounding is still inverted
    config = Config()
    config.ves = dataclasses.replace(config.ves, damping=np.float32(0.02))
    out = _reopen(first_load[1], sample_data, tmp_path, config=config)
    assert counted == ["A (1)", "B (2)"]
    assert len(out["ves_results"][1]) == 2
    assert out["inversion_cache"] == {}
    assert out["recompute_diagnostics"]["issues"] == []
