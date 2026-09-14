"""The worked examples, and the index that describes them.

An example is the first thing somebody reads, so an index that has
drifted from what the examples actually produce is worse than no index:
it advertises results nobody can reproduce. These checks hold the
committed index to the committed outputs, and hold the examples
themselves to the rule the project asks of every contributor.
"""

import importlib.util
import re
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "examples"


def _load_catalogue():
    spec = importlib.util.spec_from_file_location(
        "build_catalogue", EXAMPLES / "build_catalogue.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_catalogue_matches_the_published_examples():
    """examples/CATALOGUE.md must be what the examples on disk say.

    Every count in it comes back out of a workbook reader and every verdict
    off a report's own cover, so a stale index means a number somebody could
    quote that nothing produces.
    """
    catalogue = _load_catalogue()
    fresh = catalogue.render([catalogue.survey(case) for case in catalogue.CASES])
    assert catalogue.CATALOGUE.read_text(encoding="utf-8") == fresh, (
        "examples/CATALOGUE.md is stale; run: python examples/build_catalogue.py"
    )


def test_a_pack_holds_the_whole_case_and_is_reproducible(tmp_path):
    """One file that carries the inputs, the reports, the figures and the tables.

    Fixed timestamps, because a pack that differs from itself run to run
    cannot be compared, only rebuilt.
    """
    catalogue = _load_catalogue()
    catalogue.PACKS = tmp_path
    entry = catalogue.survey(catalogue.CASES[-1])   # the full drilling-to-handover case
    first = catalogue.pack(entry)
    names = zipfile.ZipFile(first).namelist()
    assert "project.yaml" in names
    assert any(n.startswith("data/") for n in names)
    assert any(n.endswith(".docx") for n in names)
    assert any(n.endswith(".png") for n in names)
    assert names == sorted(names), "a pack lists its members in a stable order"

    before = first.read_bytes()
    catalogue.pack(entry)
    assert first.read_bytes() == before, "the same case packed twice differs"


@pytest.mark.parametrize("script", sorted(EXAMPLES.glob("run_*.py")))
def test_no_example_invents_a_position_to_get_past_the_gate(script):
    """CONTRIBUTING asks contributors never to do this, so neither may we.

    The reports these scripts write are committed, and a committed report
    asserting a GPS fix nobody took is the exact failure the readiness gate
    exists to prevent - the document says nothing about where the number came
    from. An example whose sheets carry no position should publish a stamped
    report, which demonstrates the gate rather than hiding it.
    """
    source = script.read_text(encoding="utf-8")
    assignments = re.findall(r"site\.easting\s*,?[^=\n]*=\s*([0-9][0-9_.]*)", source)
    assert not assignments, (
        f"{script.name} assigns a site easting ({assignments}); an example must "
        "report what its sheets hold, stamp and all"
    )


def test_a_case_whose_sheets_carry_no_position_publishes_a_stamped_report():
    """And the published document proves it, not just the source."""
    catalogue = _load_catalogue()
    reports = sorted((EXAMPLES / "projects" / "dr_timbo" / "reports").glob("*.docx"))
    assert reports, "the Dr Timbo example has published no reports"
    for report in reports:
        assert catalogue.verdict(report) == "provisional", report.name
        assert "Site position" in catalogue.outstanding(report), report.name
