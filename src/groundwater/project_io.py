"""Serialize and restore the web app's saved project state.

Pure functions with no Streamlit dependency, so the project-file format is
unit-testable. The saved file captures the manual inputs that make up a
project (site details, costing assumptions and rate overrides, checklist
responses and remarks, and the WASH committee), the raw uploaded data files
(base64) or a bundled-sample reference under ``sources``, and the extra
recompute inputs (``q_*`` step discharges and ``design_swl``). On load the
analyses are rebuilt from the stored sources by ``groundwater.recompute``,
so results are restored without re-uploading.

The file may also carry ``evidence``: the photographs attached to
supervision checklist items, each with the provenance record made when it
was attached (:mod:`groundwater.photos`).

The file may also carry ``inversion_cache``: the VES inversions, keyed by
what they were computed from (:mod:`groundwater.ves.cache`), so reopening a
survey does not invert it again. It is a cache and nothing more. A file
without one loads exactly as before, a toolkit that predates it ignores
it, and an entry that no longer matches its sounding is not used.

The file may also carry ``procurement``: the contract awarded on the
Procurement page, its lines, what was measured against them and the
variation orders, as the Streamlit app's tables hold them; and ``works``:
what the project records of its contractor's work, for the Portfolio
page's contractor scorecards (:func:`groundwater.scorecards.works_record`),
which both apps write alike. Like the cache, each is a key a toolkit that
predates it ignores.
"""

from __future__ import annotations

import base64
import math

import yaml

from .ledger import clean_ledger
from .verification import clean_issue_records

# session-state key prefixes that hold saveable manual inputs. "q_" holds
# pumping-test step discharges and "design_" the borehole-design static water
# level, both needed to recompute the analyses from the saved data files.
PERSIST_PREFIXES = (
    "org_", "meta_", "chk_", "rmk_", "cost_", "fx_", "ho_", "wiz_", "q_", "design_", "proc_",
)

# Loading a project replaces the working state, so everything belonging to the
# outgoing project has to go first - not just the values the file restores.
# Missing one is silent and expensive: a file left in a file_uploader outlives
# the src_* entry it produced and is read again on the next render, putting the
# previous borehole's readings into the loaded project's reports.
RESET_ON_LOAD_PREFIXES = (
    "src_",      # stored data sources, replaced by the file's own
    "q_",        # pumping-test step discharges
    "chk_",      # supervision answers
    "rmk_",      # supervision remarks
    "chkw_",     # ...and the radios that display them
    "rmkw_",
    "upload_",   # file_uploader widgets, which outlive their src_ entry
    "sample_",   # bundled-sample pickers, likewise
    "dem_",      # the elevation model's uploader and the files it keeps
    "terrain_",  # its declared source, the terrain settings and figures
    "proc_",     # the outgoing project's contract, measurements and variations
)
# asset_record belongs to the outgoing borehole. Left behind, the incoming
# project would inherit somebody else's identifier and maintenance history.
# The saved inversions are the outgoing survey's; they would never match the
# incoming one's soundings, but they would be saved into its file.
# The supervision photographs are the outgoing borehole's evidence, and left
# behind they would vouch for the incoming one's seal.
# The maps are the outgoing site's: every figure on its Site maps page, the
# traverse they follow and the GeoLibre file built for it. The page shows them
# and offers their downloads from session state alone, so left behind they
# would pass as the incoming site's. The Portfolio page's GeoLibre file
# (geolibre_portfolio) is of the pooled sites rather than of one, and stays.
# An elevation model is not saved in a project, so left behind it would draw
# the incoming site's topographic map from tiles of somewhere else, credited
# as though they were its own. The ledger of predictions and outcomes is the
# outgoing survey's record; the incoming file brings its own.
RESET_ON_LOAD_KEYS = (
    "design_swl", "asset_record", "inversion_cache", "sup_evidence", "prediction_ledger",
    "issued_documents",
    "ledger_drilled_pick",
    "topo_path", "topo_source", "topo_report", "topo_inputs", "terrain_result", "profile_path",
    "map_paths", "subsurface_paths", "section_path", "pseudosection_path",
    "traverse", "geolibre_path", "geolibre_area", "geolibre_layers",
)


def stale_on_load(session) -> list[str]:
    """Session keys belonging to the outgoing project, to drop before a load."""
    return [
        key for key in list(session)
        if str(key).startswith(RESET_ON_LOAD_PREFIXES) or key in RESET_ON_LOAD_KEYS
    ]


def _encode_source(source: dict) -> dict:
    """Encode an uploaded-file or bundled-sample source for the project file.

    A source can carry both: the browser inlines each bundled sample's bytes
    into its own state, so a demonstration project loaded there has the file
    content *and* the sample it came from. Both are kept, because the
    ``sample`` key is what tells the certification gate that this project
    describes a worked example rather than the site on its cover - dropping
    it on the way through a save would quietly launder a demonstration into
    a report that looks like real work.
    """
    if not isinstance(source, dict):
        return {}
    encoded: dict = {}
    if source.get("bytes") is not None:
        encoded = {
            "name": str(source.get("name") or "data"),
            "b64": base64.b64encode(bytes(source["bytes"])).decode("ascii"),
        }
    elif source.get("b64"):
        encoded = {
            "name": str(source.get("name") or "data"),
            "b64": str(source["b64"]),
        }
    if source.get("sample"):
        encoded["sample"] = str(source["sample"])
    return encoded


def _decode_source(stored: dict) -> dict | None:
    """Decode a stored source back to bytes or a bundled-sample reference.

    The ``sample`` marker rides along with the bytes when both were saved,
    so a demonstration project saved in the browser and reopened here is
    still recognisable as one.
    """
    if not isinstance(stored, dict):
        return None
    if stored.get("b64"):
        try:
            decoded = {
                "name": str(stored.get("name") or "data"),
                "bytes": base64.b64decode(stored["b64"]),
            }
        except Exception:  # noqa: BLE001 - a corrupt blob is simply dropped
            return None
        if stored.get("sample"):
            decoded["sample"] = str(stored["sample"])
        return decoded
    if stored.get("sample"):
        return {"sample": str(stored["sample"])}
    return None


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


PROJECT_FORMAT = "groundwater-toolkit-project"
#: 2 from PLAN.md step 5.1: the file carries the ledger of predictions and
#: outcomes. The schema was raised for it, where the saved inversions and the
#: supervision photographs came in as keys an older toolkit ignores, because
#: the ledger is a record rather than a cache: an older toolkit that loads a
#: file of schema 2 says it does not restore everything in it, rather than
#: dropping the record on its next save without a word.
#: 3 from PLAN.md step 8.1: the file carries the issue records of the
#: documents issued from it (``issued``), raised for the same reason - a
#: record an older toolkit dropped on its next save is a document nobody
#: can confirm was issued.
#: 4 when the ledger came to carry an identity of its own (``project_id``),
#: which each entry's id carries, so two projects whose points share a name
#: and a place are not pooled as one. Raised for the same reason again: an
#: older toolkit that dropped the identity on its next save would then look
#: the ledger's points up by the ids it knows, miss them, and record each
#: point a second time.
PROJECT_SCHEMA = 4


def _schema_1_to_2(payload: dict) -> dict:
    """Schema 1 had no ledger: a file of it loads with an empty one."""
    from .ledger import empty_ledger

    return dict(payload, schema=2, ledger=empty_ledger())


def _schema_2_to_3(payload: dict) -> dict:
    """Schema 2 had no issue records: a file of it loads with none."""
    return dict(payload, schema=3, issued=[])


def _schema_3_to_4(payload: dict) -> dict:
    """Schema 3's ledger had no identity. A file of it keeps its ledger as
    it is, with none: its entries keep the ids they were saved with, since
    nothing in the file tells copies of one project from two projects, and
    a ledger with entries never takes an identity later
    (:func:`groundwater.ledger.record_predictions`)."""
    return dict(payload, schema=4)


#: The step from each schema to the next, applied in turn on load.
_MIGRATIONS = {1: _schema_1_to_2, 2: _schema_2_to_3, 3: _schema_3_to_4}


def payload_schema(payload: dict) -> int:
    """The schema a project file was saved in. A file without one is of
    schema 1: the Python app's files before the schema was written, and the
    browser app's, which wrote ``version: 1`` until schema 2."""
    schema = payload.get("schema")
    if (isinstance(schema, bool) or not isinstance(schema, (int, float))
            or not math.isfinite(schema) or schema < 1):
        return 1
    return int(schema)


def migrate_payload(payload: dict) -> dict:
    """A project file's payload brought up to :data:`PROJECT_SCHEMA`, one
    schema at a time. A file of a newer schema than this toolkit knows is
    returned as it is, and the loader warns about it."""
    schema = payload_schema(payload)
    while schema < PROJECT_SCHEMA:
        payload = _MIGRATIONS[schema](payload)
        schema += 1
    return payload


def _plain_scalar(value):
    """A numpy scalar as the Python number it is; yaml.safe_dump refuses
    numpy types, and np.float64 passes an isinstance(float) check."""
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (str, bytes)):
        try:
            return item()
        except (TypeError, ValueError):
            return value
    return value


def serialize_project(session: dict, version: str) -> bytes:
    """Serialise the saveable parts of a session-state mapping to YAML bytes."""
    state = {}
    for key, value in session.items():
        if not key.startswith(PERSIST_PREFIXES):
            continue
        plain = _plain_scalar(value)
        if isinstance(plain, (str, int, float, bool)):
            state[key] = plain
    committee = session.get("ho_committee_data")
    sources = {}
    for key, value in session.items():
        if key.startswith("src_") and isinstance(value, dict):
            encoded = _encode_source(value)
            if encoded:
                sources[key[len("src_"):]] = encoded
    summary = session.get("project_summary")
    asset = session.get("asset_record")
    payload = {
        "groundwater_toolkit_project": version,
        # the file's own schema number, independent of the toolkit version,
        # so a later layout can be migrated on load and a newer file warned
        # about instead of half-read
        "format": PROJECT_FORMAT,
        "schema": PROJECT_SCHEMA,
        "rates_overrides": session.get("rates_overrides", {}) or {},
        "committee": committee if isinstance(committee, list) else [],
        "sources": sources,
        # a small headline summary so a portfolio can be built from many
        # project files without recomputing each one
        "summary": summary if isinstance(summary, dict) else {},
        # the asset record: identifier and maintenance history. It rides in
        # the project file because that is what gets mailed between offices
        # and carried into the field, and an event stream that only exists
        # in one browser's storage is one bad phone away from gone.
        "asset": asset if isinstance(asset, dict) else {},
        # the survey's predictions beside what the borehole found (PLAN.md
        # step 5.1), written even when empty so the schema it belongs to
        # always shows it
        "ledger": clean_ledger(session.get("prediction_ledger")),
        # the issue record of every document issued from the project
        # (PLAN.md step 8.1), likewise
        "issued": clean_issue_records(session.get("issued_documents")),
        "state": state,
    }
    cache = _inversion_cache(session.get("inversion_cache"))
    if cache:
        # Only when there is something in it, so a project with no soundings
        # saves the same file it always did. It is a new top-level key rather
        # than a new schema: an older toolkit reads the file and ignores it.
        payload["inversion_cache"] = cache
    evidence = _evidence(session.get("sup_evidence"))
    if evidence:
        # likewise only when there is some, and as a key an older toolkit
        # ignores rather than a new schema
        payload["evidence"] = evidence
    procurement = _procurement(session.get("proc_contract_lines"), session.get("proc_measured"),
                               session.get("proc_variations"))
    if procurement:
        payload["procurement"] = procurement
    from .scorecards import clean_works

    works = clean_works(session.get("works_record"))
    if works is not None:
        payload["works"] = works
    return yaml.safe_dump(payload, sort_keys=True).encode("utf-8")


def _rows(value) -> list[dict]:
    """A table's rows as plain mappings of text, numbers, yes or no, and
    blanks. A data editor's rows hand back numpy numbers and NaN for an empty
    cell, which a project file cannot carry; a cell of any other kind, and a
    row that is not a mapping, are left out."""
    if hasattr(value, "to_dict"):  # a pandas DataFrame from st.data_editor
        value = value.to_dict("records")
    out = []
    for row in value if isinstance(value, list) else []:
        if not isinstance(row, dict):
            continue
        clean: dict = {}
        for key, cell in row.items():
            cell = _plain_scalar(cell)
            if not isinstance(key, str):
                continue
            if cell is None or isinstance(cell, (str, bool)):
                clean[key] = cell
            elif isinstance(cell, (int, float)):
                clean[key] = cell if math.isfinite(cell) else None
        out.append(clean)
    return out


def _procurement(lines, measured, variations) -> dict:
    """The contract awarded on the Procurement page as the Streamlit app
    keeps it (``proc_contract_lines``, ``proc_measured`` and
    ``proc_variations``): its lines, what was measured and the variation
    orders, or {} where none was awarded. A file's block is cleaned the same
    way on the way in as a session's on the way out."""
    clean = _rows(lines)
    if not clean:
        return {}
    return {"lines": clean, "measured": _rows(measured), "variations": _rows(variations)}


def _evidence(value) -> dict:
    """The supervision photographs, ``{item id: photograph}``, or {}.

    A photograph is its file name, type and base64 bytes, and the provenance
    record :func:`groundwater.photos.photo_provenance` made when it was
    attached. One without a record keeps none: nothing is filled in for it.
    """
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, photo in value.items():
        if not isinstance(key, str) or not isinstance(photo, dict):
            continue
        b64 = photo.get("b64")
        if not isinstance(b64, str) or not b64:
            continue
        provenance = photo.get("provenance")
        out[key] = {
            "name": str(photo.get("name") or "photo"),
            "mime": str(photo.get("mime") or "image/jpeg"),
            "b64": b64,
            "provenance": provenance if isinstance(provenance, dict) else None,
        }
    return out


def _inversion_cache(value) -> dict:
    """The saved inversions, as ``{key: entry}``, or {} for anything else.

    Only the shape is checked here. Whether an entry is sound, and whether
    it is for the sounding in hand, is decided when it is used
    (:func:`groundwater.ves.cache.cached_inversion`).
    """
    if not isinstance(value, dict):
        return {}
    return {
        key: entry for key, entry in value.items()
        if isinstance(key, str) and isinstance(entry, dict)
    }


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
    try:
        return _updates_from_payload(payload)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - a hand-edited file is a message, not a traceback
        raise ValueError(f"could not read project file: {exc}") from exc


def _updates_from_payload(payload: dict) -> dict:
    updates: dict = {}
    warnings: list[str] = []
    schema = payload_schema(payload)
    if schema > PROJECT_SCHEMA:
        warnings.append(
            f"This file was saved in project format {schema}; this "
            f"toolkit reads format {PROJECT_SCHEMA}. Inputs it does not "
            "recognise are not restored."
        )
    payload = migrate_payload(payload)
    for key, value in payload["state"].items():
        # a hand-edited file can carry an integer key, which has no
        # startswith(); str() keeps the check honest instead of crashing it
        if str(key).startswith(PERSIST_PREFIXES) and isinstance(
            value, (str, int, float, bool)
        ):
            updates[str(key)] = value
    # supervision answers saved before the checklist CSV carried stable ids
    # are keyed by position; carry them onto the questions they answered
    from .supervision.checklists import migrate_response_keys

    updates = migrate_response_keys(updates)
    if warnings:
        updates["warnings"] = warnings

    overrides = payload.get("rates_overrides") or {}
    if isinstance(overrides, dict):
        # a hand-edited file can carry nulls, lists or words where a rate
        # belongs; skip those rather than raise, so one bad rate does not
        # cost the user the whole project file
        clean: dict[str, float] = {}
        for code, rate in overrides.items():
            try:
                value = float(rate)
            except (TypeError, ValueError):
                continue
            if math.isfinite(value):
                clean[str(code)] = value
        updates["rates_overrides"] = clean

    committee = payload.get("committee")
    if isinstance(committee, list) and committee:
        updates["committee"] = committee_records(committee)

    sources = payload.get("sources")
    if isinstance(sources, dict):
        decoded = {}
        for key, stored in sources.items():
            source = _decode_source(stored)
            if source is not None:
                decoded[str(key)] = source
        if decoded:
            updates["sources"] = decoded

    summary = payload.get("summary")
    if isinstance(summary, dict) and summary:
        updates["summary"] = summary

    cache = _inversion_cache(payload.get("inversion_cache"))
    if cache:
        updates["inversion_cache"] = cache

    evidence = _evidence(payload.get("evidence"))
    if evidence:
        updates["evidence"] = evidence

    held = payload.get("procurement")
    procurement = _procurement(held.get("lines"), held.get("measured"), held.get("variations")) \
        if isinstance(held, dict) else {}
    if procurement:
        updates["procurement"] = procurement

    from .scorecards import clean_works

    works = clean_works(payload.get("works"))
    if works is not None:
        updates["works"] = works

    # always, so a loaded project never keeps the outgoing one's ledger; a
    # hand-edited entry is dropped or blanked, not raised
    updates["prediction_ledger"] = clean_ledger(payload.get("ledger"))
    # likewise its issue records; one that is not one is dropped
    updates["issued_documents"] = clean_issue_records(payload.get("issued"))

    asset = payload.get("asset")
    if isinstance(asset, dict) and asset.get("asset_id"):
        # Rebuilt through the registry so a file whose identifier has been
        # damaged is dropped rather than loaded: a maintenance history under
        # the wrong identifier is worse than no history at all.
        from .registry import asset_from_dict

        record = asset_from_dict(asset)
        if record is not None:
            updates["asset"] = record.as_dict()
    return updates
