"""Project save/load round-trip, including the WASH committee."""

import pytest

from groundwater.project_io import (
    committee_records,
    deserialize_project,
    serialize_project,
)


def test_scalar_inputs_round_trip():
    session = {
        "meta_community": "Rokel",
        "meta_easting": 694667.0,
        "cost_depth": 50,
        "chk_1": True,
        "not_saved": "ignored",  # no persist prefix
        "ho_committee": object(),  # data_editor delta: not serialisable, skipped
    }
    updates = deserialize_project(serialize_project(session, "0.2.0"))
    assert updates["meta_community"] == "Rokel"
    assert updates["meta_easting"] == 694667.0
    assert updates["cost_depth"] == 50
    assert updates["chk_1"] is True
    assert "not_saved" not in updates
    assert "ho_committee" not in updates  # the delta object was dropped safely


def test_committee_survives_save_and_load():
    committee = [
        {"Role": "Chair", "Name": "Aminata Kamara", "Phone": "076111222"},
        {"Role": "Treasurer", "Name": "Mohamed Sesay", "Phone": "088333444"},
    ]
    session = {"meta_community": "Rokel", "ho_committee_data": committee}
    updates = deserialize_project(serialize_project(session, "0.2.0"))
    assert updates["committee"] == committee  # names no longer vanish on reload


def test_rates_overrides_round_trip():
    session = {"meta_community": "X"}
    session["rates_overrides"] = {"DRILL": 130.5}
    updates = deserialize_project(serialize_project(session, "0.2.0"))
    assert updates["rates_overrides"] == {"DRILL": 130.5}


def test_committee_records_normalises_and_strips():
    rows = [{"Role": " Chair ", "Name": "A", "Phone": None}, {"Role": "", "Name": ""}]
    recs = committee_records(rows)
    assert recs[0] == {"Role": "Chair", "Name": "A", "Phone": ""}
    assert recs[1] == {"Role": "", "Name": "", "Phone": ""}


def test_sources_round_trip():
    session = {
        "meta_community": "Rokel",
        "src_ves": {"sample": "rokel/rokel_ves.xlsx"},
        "src_pump": {"name": "test.xlsx", "bytes": b"\x00\x01binary\xff"},
        "q_1": 2.5,          # a pumping discharge, now persisted
        "design_swl": 9.44,  # borehole design static water level
    }
    updates = deserialize_project(serialize_project(session, "0.2.0"))
    assert updates["sources"]["ves"] == {"sample": "rokel/rokel_ves.xlsx"}
    assert updates["sources"]["pump"]["bytes"] == b"\x00\x01binary\xff"
    assert updates["sources"]["pump"]["name"] == "test.xlsx"
    # the extra inputs the recompute needs survive as scalars
    assert updates["q_1"] == 2.5
    assert updates["design_swl"] == 9.44


def test_bad_file_raises():
    with pytest.raises(ValueError):
        deserialize_project(b"not: [valid, project")
    with pytest.raises(ValueError):
        deserialize_project(b"just_a_string")
