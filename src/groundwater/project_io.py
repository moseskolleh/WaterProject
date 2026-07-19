"""Serialize and restore the web app's saved project state.

Pure functions with no Streamlit dependency, so the project-file format is
unit-testable. The saved file captures the manual inputs that make up a
project (site details, costing assumptions and rate overrides, checklist
responses and remarks, and the WASH committee). Analysis results are
recomputed from the re-uploaded data files rather than stored.
"""

from __future__ import annotations

import yaml

# session-state key prefixes that hold saveable manual inputs
PERSIST_PREFIXES = ("org_", "meta_", "chk_", "rmk_", "cost_", "fx_", "ho_", "wiz_")


def committee_records(data) -> list[dict]:
    """Normalise a committee table (list of rows or DataFrame) to plain dicts."""
    if hasattr(data, "to_dict"):  # a pandas DataFrame from st.data_editor
        data = data.to_dict("records")
    records = []
    for row in data or []:
        get = row.get if hasattr(row, "get") else (lambda k: None)
        records.append(
            {
                "Role": str(get("Role") or "").strip(),
                "Name": str(get("Name") or "").strip(),
                "Phone": str(get("Phone") or "").strip(),
            }
        )
    return records


def serialize_project(session: dict, version: str) -> bytes:
    """Serialise the saveable parts of a session-state mapping to YAML bytes."""
    state = {
        key: value
        for key, value in session.items()
        if key.startswith(PERSIST_PREFIXES)
        and isinstance(value, (str, int, float, bool))
    }
    committee = session.get("ho_committee_data")
    payload = {
        "groundwater_toolkit_project": version,
        "rates_overrides": session.get("rates_overrides", {}) or {},
        "committee": committee if isinstance(committee, list) else [],
        "state": state,
    }
    return yaml.safe_dump(payload, sort_keys=True).encode("utf-8")


def deserialize_project(raw: bytes) -> dict:
    """Parse a project file into a mapping of session-state updates.

    Raises ValueError if the bytes are not a valid project file. The returned
    dict may include ``rates_overrides`` (dict) and ``committee`` (list of
    dict rows) alongside the scalar input keys.
    """
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - surfaced as a load error
        raise ValueError("could not parse project file") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("state"), dict):
        raise ValueError("not a valid project file")

    updates: dict = {}
    for key, value in payload["state"].items():
        if key.startswith(PERSIST_PREFIXES) and isinstance(
            value, (str, int, float, bool)
        ):
            updates[key] = value

    overrides = payload.get("rates_overrides") or {}
    if isinstance(overrides, dict):
        updates["rates_overrides"] = {
            str(code): float(rate) for code, rate in overrides.items()
        }

    committee = payload.get("committee")
    if isinstance(committee, list) and committee:
        updates["committee"] = committee_records(committee)
    return updates
