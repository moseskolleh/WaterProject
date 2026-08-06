"""Project save/load round-trip, including the WASH committee."""

import pytest

from groundwater.project_io import (
    committee_records,
    deserialize_project,
    serialize_project,
    stale_on_load,
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


@pytest.mark.parametrize(
    "bad", ["null", "[1, 2]", "abc", "'.nan'", ".inf"]
)
def test_unusable_rate_overrides_are_skipped_not_raised(bad):
    """A hand-edited rate must not cost the user the whole project file.

    ``float(None)`` raises TypeError, which the app's load handler does not
    catch - the user got a red traceback instead of the analyses.
    """
    raw = (
        b"groundwater_toolkit_project: '0.2.0'\n"
        b"state: {meta_community: Rokel}\n"
        b"rates_overrides:\n  DRILL: 130.5\n  BAD: " + bad.encode() + b"\n"
    )
    updates = deserialize_project(raw)
    assert updates["rates_overrides"] == {"DRILL": 130.5}
    assert updates["meta_community"] == "Rokel"


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


def test_summary_round_trip():
    session = {
        "meta_community": "Rokel",
        "project_summary": {
            "community": "Rokel", "district": "Port Loko",
            "status": "Successful", "safe_yield_m3_per_h": 2.4,
        },
    }
    updates = deserialize_project(serialize_project(session, "0.2.0"))
    assert updates["summary"]["community"] == "Rokel"
    assert updates["summary"]["safe_yield_m3_per_h"] == 2.4


def test_loading_clears_the_outgoing_project_including_the_uploaders():
    """A file left in a file_uploader outlives the src_ entry it produced.

    choose_input reads the uploader on the very next render and rewrites
    src_*, so the previous borehole's workbook silently replaced the loaded
    project's data - and then went into its reports and its next save.
    """
    session = {
        # the outgoing project
        "src_pump": {"sample": "dr_timbo/dr_timbo_constant_test.xlsx"},
        "upload_pump": object(),   # the widget behind it
        "sample_ves": "rokel/rokel_ves.xlsx",
        "q_1": 2.5,
        "design_swl": 9.44,
        "chk_procurement-01": "Yes",
        "chkw_procurement-01": "Yes",
        "rmk_procurement-01": "late",
        "rmkw_procurement-01": "late",
        # settings that belong to the user, not the project
        "org_name": "GeomentAqua",
        "meta_community": "Rokel",
        "nav": "Supervision",
    }
    stale = set(stale_on_load(session))
    assert "upload_pump" in stale and "sample_ves" in stale
    assert {"src_pump", "q_1", "design_swl"} <= stale
    assert {"chk_procurement-01", "chkw_procurement-01"} <= stale
    assert {"rmk_procurement-01", "rmkw_procurement-01"} <= stale
    # the loaded file supplies these itself; the branding and nav are not the
    # project's to clear
    assert not ({"org_name", "nav"} & stale)


def test_bad_file_raises():
    with pytest.raises(ValueError):
        deserialize_project(b"not: [valid, project")
    with pytest.raises(ValueError):
        deserialize_project(b"just_a_string")


def test_the_asset_record_survives_the_round_trip():
    """The maintenance history is what a project file is worth after handover."""
    from groundwater.registry import Asset, AssetEvent, mint_asset_id
    from groundwater.models import SiteMetadata

    site = SiteMetadata(district="Bo", easting=790500.0, northing=875300.0,
                        utm_zone=28)
    asset = Asset(asset_id=mint_asset_id(site), community="Njala",
                  district="Bo", easting=790500.0, northing=875300.0,
                  utm_zone=28,
                  events=[AssetEvent("2020-01-10", "commissioned", by="M. K."),
                          AssetEvent("2023-04-02", "failure", "pump seized")])
    raw = serialize_project({"meta_community": "Njala",
                             "asset_record": asset.as_dict()}, "test")
    updates = deserialize_project(raw)
    assert updates["asset"]["asset_id"] == asset.asset_id
    assert len(updates["asset"]["events"]) == 2
    assert updates["asset"]["events"][1]["note"] == "pump seized"


def test_a_project_file_with_a_damaged_identifier_drops_the_asset():
    """A history under the wrong identifier is worse than no history."""
    raw = serialize_project(
        {"meta_community": "Njala",
         "asset_record": {"asset_id": "SL-WAR-XXXXXXX-9",
                          "events": [{"when": "2020-01-10",
                                      "kind": "commissioned"}]}},
        "test")
    assert "asset" not in deserialize_project(raw)


def test_loading_a_project_does_not_inherit_the_previous_borehole():
    """Its identifier and maintenance history belong to the outgoing project."""
    assert "asset_record" in stale_on_load({"asset_record": {"asset_id": "x"},
                                            "meta_community": "keep me"})
