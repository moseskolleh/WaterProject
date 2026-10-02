"""The two engines against each other on generated field sheets.

    nox -s fuzz                                  # what a pull request runs
    FUZZ_PROFILE=nightly nox -s fuzz             # what the nightly job runs
    FUZZ_EXAMPLES=2000 nox -s fuzz               # any number, here

Parity on the three sample projects says nothing about a fourth kind of
sheet. Here Hypothesis draws VES soundings, pumping tests, laboratory sheets
and drilling logs (``sheets.py``), writes each as a real .xlsx, reads it with
the Python package and hands the same bytes to ``gwt-core.js`` in headless
Chromium (``engines.py``, ``engine.mjs``); the two answers are compared with
``make_reference.py``'s comparison at the tolerances ``parity.mjs`` uses.

A disagreement is shrunk by Hypothesis to the smallest sheet that still shows
it and written to ``tests/fuzz/regressions/``. Commit it with a note saying
what it was, and it is replayed on every run from then on.

The module is not named ``test_*`` so the ordinary pytest run, which has no
browser, does not collect it; ``nox -s fuzz`` names it explicitly.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings

from engines import BrowserEngine, divergences, python_summary
from sheets import CASES, ves_case, workbook_bytes

HERE = Path(__file__).resolve().parent
REGRESSIONS = HERE / "regressions"

# Cases per generator. A pull request runs the same few hundred every time
# (derandomized, so a red build is never luck); the nightly run draws new
# ones each night. Inversions cost about a second each in Python, so they get
# a small share of either budget.
PROFILES = {
    "pr": {"cases": 150, "inversions": 10, "derandomize": True},
    "nightly": {"cases": 6000, "inversions": 300, "derandomize": False},
}
PROFILE = PROFILES[os.environ.get("FUZZ_PROFILE", "pr")]
CASES_PER_KIND = int(os.environ.get("FUZZ_EXAMPLES", PROFILE["cases"]))
INVERSIONS = int(os.environ.get("FUZZ_INVERSIONS", PROFILE["inversions"]))


def _settings(examples: int):
    return settings(
        max_examples=examples, deadline=None, derandomize=PROFILE["derandomize"],
        database=None, print_blob=True,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large,
                               HealthCheck.large_base_example],
    )


@pytest.fixture(scope="module")
def engine():
    browser = BrowserEngine()
    yield browser
    browser.close()


@pytest.fixture(scope="module")
def workdir():
    with tempfile.TemporaryDirectory(prefix="gwt-fuzz-") as folder:
        yield Path(folder)


def compare(engine: BrowserEngine, case: dict, workdir: Path) -> list:
    """Every place the two engines disagree on ``case``."""
    data = workbook_bytes(case["sheets"])
    path = workdir / "case.xlsx"
    path.write_bytes(data)
    py = python_summary(case["kind"], path, str(path), case["options"])
    js = engine.summary(case["kind"], data, str(path), case["options"])
    return divergences(js, py)


def report(found: list) -> str:
    lines = [f"the engines disagree in {len(found)} place(s):"]
    for where, js, py in found[:12]:
        lines.append(f"  {where}\n    browser {json.dumps(js)[:400]}\n"
                     f"    python  {json.dumps(py)[:400]}")
    return "\n".join(lines)


def save_regression(case: dict, found: list) -> Path:
    """Write a shrunk counterexample where the next run replays it."""
    where = found[0][0]
    slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"\[\d+\]", "", where).lower()).strip("-")
    body = json.dumps({"kind": case["kind"], "sheets": case["sheets"],
                       "options": case["options"]}, sort_keys=True)
    digest = hashlib.sha1(body.encode()).hexdigest()[:8]
    REGRESSIONS.mkdir(exist_ok=True)
    path = REGRESSIONS / f"{case['kind']}-{slug[:40]}-{digest}.json"
    path.write_text(json.dumps({
        "note": "Found by the fuzz suite on " + date.today().isoformat()
                + ". Say here what diverged and which engine was put right.",
        "first_divergence": [where, found[0][1], found[0][2]],
        **json.loads(body),
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _regressions():
    return sorted(REGRESSIONS.glob("*.json"))


@pytest.mark.parametrize("path", _regressions(), ids=lambda p: p.stem)
def test_regression(path, engine, workdir):
    """Every counterexample found so far, replayed on every run."""
    case = json.loads(path.read_text(encoding="utf-8"))
    found = compare(engine, case, workdir)
    assert not found, report(found)


def _fuzz(engine, workdir, strategy, examples: int) -> None:
    last: dict = {}

    @given(strategy)
    @_settings(examples)
    def agree(case):
        found = compare(engine, case, workdir)
        if found:
            # Hypothesis replays the shrunk case last, so this ends holding it
            last["case"], last["found"] = case, found
            raise AssertionError(report(found))

    try:
        agree()
    except AssertionError:
        if "case" in last:
            saved = save_regression(last["case"], last["found"])
            print(f"\nshrunk counterexample written to {saved.relative_to(HERE.parents[1])}")
        raise


@pytest.mark.parametrize("kind", sorted(CASES))
def test_engines_agree(kind, engine, workdir):
    _fuzz(engine, workdir, CASES[kind](), CASES_PER_KIND)


def test_inversions_agree(engine, workdir):
    """The inversion of generated soundings, at parity.mjs's model tolerance."""
    strategy = ves_case().map(lambda case: {**case, "sheets": case["sheets"][:1],
                                            "options": {"invert": True}})
    _fuzz(engine, workdir, strategy, INVERSIONS)
