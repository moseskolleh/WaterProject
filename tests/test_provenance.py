"""The bundled datasets are what the provenance record says they are.

`data_provenance.yaml` records where each committed dataset came from, under
what terms, and its SHA-256. The checksum is the part a test can enforce: a
dataset quietly replaced with a different vintage, or an edit that never made
it back to the build script, otherwise shows up only as numbers that changed
for no reason anybody can trace.

The licence fields cannot be verified by a test - that is human work - but
the record has to at least be complete and internally consistent, and every
file it claims to cover has to exist.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
RECORD = REPO / "data_provenance.yaml"


@pytest.fixture(scope="module")
def provenance() -> dict:
    return yaml.safe_load(RECORD.read_text(encoding="utf-8"))


def test_the_licence_file_exists_and_names_its_own_scope():
    """MIT declared in pyproject with no LICENSE beside it is not a grant.

    And a blanket "this repository is MIT" would be wrong anyway: the BGS
    hydrogeology layer is CC BY-SA 4.0 and ShareAlike propagates into the two
    published web bundles that embed it.
    """
    text = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "GeomentAqua" in text
    assert "WITHOUT WARRANTY OF ANY KIND" in text
    assert "CC BY-SA 4.0" in text, "the scope note has to name the copyleft data"
    assert "THIRD_PARTY_NOTICES.md" in text


def test_every_recorded_file_exists_with_the_recorded_checksum(provenance):
    checked = 0
    for dataset in provenance["datasets"]:
        for entry in dataset.get("files") or []:
            path = REPO / entry["path"]
            assert path.is_file(), f"{dataset['id']}: {entry['path']} is missing"
            raw = path.read_bytes()
            assert len(raw) == entry["bytes"], entry["path"]
            assert hashlib.sha256(raw).hexdigest() == entry["sha256"], (
                f"{entry['path']} has changed since the provenance record was "
                "written. If the change is intended, regenerate the record; if "
                "it is not, find out who replaced the dataset."
            )
            checked += 1
    assert checked >= 9, "the record should cover every committed dataset"


def test_every_dataset_states_its_licence_and_its_evidence(provenance):
    """"unverified" is a legitimate answer; silence is not."""
    for dataset in provenance["datasets"]:
        for key in ("id", "name", "source", "licence", "licence_evidence",
                    "attribution", "changes_made"):
            assert dataset.get(key), f"{dataset.get('id')} is missing {key}"


def test_the_copyleft_dataset_is_marked_share_alike(provenance):
    """The one obligation that propagates into the published site."""
    bgs = next(d for d in provenance["datasets"] if d["id"] == "bgs_hydrogeology")
    assert bgs["licence"] == "CC-BY-SA-4.0"
    assert bgs["share_alike"] is True
    assert "docs/js/gwt-data.js" in bgs["embedded_in"]
    assert "docs/wasm/index.html" in bgs["embedded_in"]


def test_the_committed_geojson_still_declares_its_own_licence():
    """The derived file carries the licence in its own payload.

    That declaration is what tells a downstream user of the published bundle
    that ShareAlike applies to it, so it must survive every rebuild.
    """
    import json

    path = REPO / "src" / "groundwater" / "data" / "sl_hydrogeology_bgs.geojson"
    payload = json.loads(path.read_text(encoding="utf-8"))
    text = json.dumps(payload)
    assert "CC BY-SA 4.0" in text
    assert "British Geological Survey" in text or "BGS" in text


def test_the_reference_documents_are_listed_with_an_honest_status(provenance):
    """No redistribution grant has been established for eight of the nine."""
    documents = provenance["documents"]
    assert len(documents) >= 9
    for entry in documents:
        assert (REPO / entry["path"]).is_file(), entry["path"]
        assert entry.get("licence"), entry["path"]
    unverified = [d for d in documents if d["licence"] == "unverified"]
    assert unverified, "the honest status has not been recorded"


def test_the_notices_file_covers_every_recorded_dataset(provenance):
    notices = (REPO / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for dataset in provenance["datasets"]:
        # the headline name, not the id, is what a reader looks for
        head = dataset["name"].split(" - ")[0].strip()
        assert head in notices, f"{dataset['id']} is not described in the notices"
