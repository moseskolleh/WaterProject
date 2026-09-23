"""The worked examples, and the index that describes them.

An example is the first thing somebody reads, so an index that has
drifted from what the examples actually produce is worse than no index:
it advertises results nobody can reproduce. These checks hold the
committed index to the committed outputs, and hold the examples
themselves to the rule the project asks of every contributor.
"""

import difflib
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


def _run_example(script: Path, out_root: Path) -> None:
    spec = importlib.util.spec_from_file_location(script.stem, script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main(out_root=out_root)


def _generated(root: Path) -> set[str]:
    """Every file a case's folder holds, relative to it, apart from raw/."""
    return {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).parts[0] != "raw"
    }


@pytest.mark.parametrize("case", [c["key"] for c in _load_catalogue().CASES])
def test_the_committed_outputs_are_what_the_current_code_writes(case, tmp_path):
    """The example folders hold what the scripts write today, no more, no less.

    Twenty-one figures once sat in these folders that no script had written
    for months - maps keyed to a district centroid the boundary layer had
    since moved, drawings under a file name a builder had stopped using -
    beside the current ones, with nothing in either name to say which the
    committed report embeds. The scripts now clear their folders before
    they run; this check holds the committed set of file names to the set a
    fresh run produces, so an output nobody regenerated shows up as a diff
    rather than as a second map somebody quotes. Names, not bytes: the
    catalogue check and CONTRIBUTING's reproducibility rule cover content.
    """
    catalogue = _load_catalogue()
    entry = next(c for c in catalogue.CASES if c["key"] == case)
    _run_example(EXAMPLES / entry["script"], tmp_path)
    fresh = _generated(tmp_path / case)
    committed = _generated(EXAMPLES / "projects" / case)
    assert fresh == committed, (
        f"examples/projects/{case} does not match a fresh run of {entry['script']}: "
        f"only committed {sorted(committed - fresh)}; only fresh {sorted(fresh - committed)}. "
        f"Run: python examples/{entry['script']} && python examples/build_catalogue.py"
    )
    # The names alone let a whole release of report changes through: the
    # committed reports went on saying "handpump failure", quoting a WHO
    # turbidity value WHO does not set and judging districts by the deleted
    # boxes, because nothing compared what they said. The words are
    # deterministic where a rasterised figure's bytes are not, so the text
    # of every report is held to a fresh run.
    for name in sorted(n for n in fresh if n.endswith(".docx")):
        now = _report_text(tmp_path / case / name)
        then = _report_text(EXAMPLES / "projects" / case / name)
        changed = [
            line for line in difflib.unified_diff(then, now, lineterm="", n=0)
            if line[:1] in "+-" and line[:3] not in ("+++", "---")
        ]
        assert not changed, (
            f"examples/projects/{case}/{name} is not what the current code writes:\n"
            + "\n".join(changed[:12])
            + f"\nRun: python examples/{entry['script']} && python examples/build_catalogue.py"
        )


def _report_text(path: Path) -> list[str]:
    """The paragraphs of a report, table cells included, as the reader sees them."""
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    return [
        "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", paragraph))
        for paragraph in re.findall(r"<w:p[\s>].*?</w:p>", xml, flags=re.S)
    ]
