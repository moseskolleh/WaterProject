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

A disagreement is written to ``tests/fuzz/regressions/`` and printed in the
log: on the nightly run shrunk by Hypothesis to the smallest sheet that still
shows it, on a pull request as drawn. Commit it with a note saying what it
was, and it is replayed on every run from then on.

The module is not named ``test_*`` so the ordinary pytest run, which has no
browser, does not collect it; ``nox -s fuzz`` names it explicitly.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import zlib
from datetime import date
from pathlib import Path

import pytest
from hypothesis import HealthCheck, Phase, given, seed, settings

from engines import BrowserEngine, divergences, python_summary
from sheets import CASES, ves_case, workbook_bytes

HERE = Path(__file__).resolve().parent
REGRESSIONS = HERE / "regressions"

# Cases per generator. A pull request runs the same few hundred every time,
# on any machine, and draws new ones when sheets.py, the Hypothesis version,
# a generator's name (its seed) or the number of cases changes, or a value
# sheets.py computes with the package or scipy: each VES reading comes from
# groundwater.ves.forward and each drawdown from scipy's exp1, and typed()
# draws once more for a reading that rounds to a whole number, so a change
# that carries one reading across a rounding draws every later case anew.
# The nightly run draws new ones each night. Inversions cost about a second
# each in Python, so they get a small share of either budget.
PROFILES = {
    "pr": {"cases": 150, "inversions": 10, "fixed": True},
    "nightly": {"cases": 6000, "inversions": 300, "fixed": False},
}
PROFILE = PROFILES[os.environ.get("FUZZ_PROFILE", "pr")]
CASES_PER_KIND = int(os.environ.get("FUZZ_EXAMPLES", PROFILE["cases"]))
INVERSIONS = int(os.environ.get("FUZZ_INVERSIONS", PROFILE["inversions"]))

if PROFILE["fixed"]:
    # Hypothesis also draws, now and then, a literal it found in any module it
    # takes for local code, which is every module under src/. One constant
    # added anywhere in the package would then draw a pull request a new
    # sample, and a red build would be the luck of that draw. The fixed
    # sample is drawn without them; the nightly run keeps them, since probing
    # the package's own thresholds is what they are for. This reaches into
    # Hypothesis's internals, one more reason its version is pinned, and a
    # release that moves them stops the run here rather than re-rolling it:
    # one that renames them, or one that keeps the name but reads the pool
    # some other way, which the provider's own view of it shows.
    from hypothesis.internal.conjecture import providers
    from hypothesis.internal.constants_ast import Constants

    _MOVED = ("Hypothesis no longer keeps the pool of local constants where "
              "fuzz_parity.py empties it; see PROFILES")
    if not (callable(getattr(providers, "_get_local_constants", None))
            and hasattr(providers, "CONSTANTS_CACHE")):
        raise RuntimeError(_MOVED)
    _NO_CONSTANTS = Constants()
    providers._get_local_constants = lambda: _NO_CONSTANTS
    providers.CONSTANTS_CACHE.cache.clear()
    if getattr(providers.HypothesisProvider(None), "_local_constants", None) is not _NO_CONSTANTS:
        raise RuntimeError(_MOVED)


def _settings(examples: int):
    # The fixed sample is not shrunk: shrinking stops on a five-minute clock,
    # so where it stops depends on the machine, and a pull request should
    # write the case it drew, the same on every run. The nightly run shrinks.
    phases = ((Phase.explicit, Phase.generate) if PROFILE["fixed"]
              else settings.default.phases)
    return settings(
        max_examples=examples, deadline=None, derandomize=PROFILE["fixed"],
        database=None, print_blob=True, phases=phases,
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


def compare(engine: BrowserEngine, case: dict, workdir: Path,
            open_questions: bool = False) -> list:
    """Every place the two engines disagree on ``case``.

    ``open_questions`` leaves out the fitted numbers of two kinds of model,
    which can turn on the last bits of either engine's arithmetic:

    * the models of an inversion neither engine converged. This rule was
      written for regressions/ves-unconverged-inversion.json, which turned
      out to be the browser's Bessel tables and now agrees to 1e-10; no
      recorded case still needs it. It is kept as it was until the owner
      decides whether an unconverged model should be held to agreeing.
    * a model with a boundary the Python inversion itself calls poorly
      resolved, its thickness uncertain by a factor of POORLY_RESOLVED_FACTOR
      or more, which the reports already say. Such a model is one of a
      family that fits about equally well, and where a search settles on it
      can move by more than parity's 1e-3: perturbing Python's forward model
      by 1e-15 moves its own answer for
      regressions/ves-poorly-resolved-boundary.json by 1.2e-3.

    Whether each engine inverted at all, and to how many layers, is still
    compared. The open cases these rules were written for (an unconverged
    inversion, equivalent models, a poorly resolved boundary) stopped
    diverging once the browser's Bessel tables and its interp were put
    right. The first two were port defects and are now held to agreeing;
    the third agrees by luck and is replayed under these rules. What parity
    should mean for a knife-edge model is for the owner to decide; until
    then the rules stay as they were.
    """
    from groundwater.ves.interpret import POORLY_RESOLVED_FACTOR

    data = workbook_bytes(case["sheets"])
    path = workdir / "case.xlsx"
    path.write_bytes(data)
    py = python_summary(case["kind"], path, str(path), case["options"])
    js = engine.summary(case["kind"], data, str(path), case["options"])
    # Judges here, not answers: the Python model's own resolution, which
    # the browser is not asked for, and whether each inversion converged,
    # which no report prints. At a parameter bound one engine can stop for
    # want of a better step while the other runs out its iterations, with
    # models that agree to the tolerance.
    factors = [inv.pop("h_factor", None) for inv in py.get("inversions") or []]
    settled = [[inv.pop("converged", None) for inv in side.get("inversions") or []
                if isinstance(inv, dict)] for side in (js, py)]
    found = divergences(js, py)
    if open_questions:
        skipped = set()
        for i, (a, b) in enumerate(zip(*settled, strict=False)):
            if a is False and b is False:
                skipped |= {f"inversions[{i}].{key}" for key in ("rho", "h", "err")}
            if any(f is not None and f >= POORLY_RESOLVED_FACTOR
                   for f in factors[i] or []):
                skipped |= {f"inversions[{i}].{key}" for key in ("rho", "h", "err")}
        # "rho[]" is a different number of layers, which is still compared
        found = [d for d in found if d[0].endswith("[]") or (
            d[0] not in skipped and d[0].rsplit("[", 1)[0] not in skipped)]
    return found


def report(found: list) -> str:
    lines = [f"the engines disagree in {len(found)} place(s):"]
    for where, js, py in found[:12]:
        lines.append(f"  {where}\n    browser {json.dumps(js)[:400]}\n"
                     f"    python  {json.dumps(py)[:400]}")
    return "\n".join(lines)


def save_regression(case: dict, found: list) -> Path:
    """Write a counterexample where the next run replays it: shrunk on the
    nightly run, as drawn on a pull request."""
    where = found[0][0]
    slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"\[\d+\]", "", where).lower()).strip("-")
    body = json.dumps({"kind": case["kind"], "sheets": case["sheets"],
                       "options": case["options"]}, sort_keys=True)
    digest = hashlib.sha1(body.encode()).hexdigest()[:8]
    REGRESSIONS.mkdir(exist_ok=True)
    path = REGRESSIONS / f"{case['kind']}-{slug[:40]}-{digest}.json"
    path.write_text(regression_text({
        "note": "Found by the fuzz suite on " + date.today().isoformat()
                + ". Say here what diverged and which engine was put right.",
        "first_divergence": [where, found[0][1], found[0][2]],
        **json.loads(body),
    }), encoding="utf-8")
    return path


def regression_text(case: dict) -> str:
    """A regression file a reviewer can read: one sheet row to a line."""
    def one(value):
        return json.dumps(value, ensure_ascii=False)

    lines = ["{"]
    for key in ("note", "open", "as_generated", "first_divergence", "kind", "options"):
        if key in case:
            lines.append(f" {one(key)}: {one(case[key])},")
    lines.append(' "sheets": [')
    for i, sheet in enumerate(case["sheets"]):
        lines.append(f'  {{"name": {one(sheet["name"])}, "rows": [')
        lines.append(",\n".join(f"   {one(row)}" for row in sheet["rows"]))
        lines.append("  ]}" + ("," if i + 1 < len(case["sheets"]) else ""))
    lines.append(" ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _regressions():
    return sorted(REGRESSIONS.glob("*.json"))


@pytest.mark.parametrize("path", _regressions(), ids=lambda p: p.stem)
def test_regression(path, engine, workdir):
    """Every counterexample found so far, replayed on every run.

    A case carrying ``"open"`` is a divergence that is a question of method
    rather than a bug, recorded with the question and not yet answered. It
    is held to diverging still, at the path it was found at, so the day one
    engine changes its answer the case says so rather than passing quietly.

    A case carrying ``"as_generated"`` is compared as test_inversions_agree
    compares a generated inversion, with ``open_questions``, which leaves out
    every fitted number of a model with a poorly resolved boundary. On such
    a sheet the boundary turns on the last bits of the arithmetic, so holding
    the engines to agreeing on it, or to diverging, would be luck either way.
    The key says what is left out, and whose decision it waits on.
    """
    case = json.loads(path.read_text(encoding="utf-8"))
    found = compare(engine, case, workdir, open_questions=bool(case.get("as_generated")))
    if case.get("open"):
        where = case["first_divergence"][0]
        assert any(path_ == where for path_, _, _ in found), (
            f"this open case no longer diverges at {where}; answer the question "
            f"in its 'open' note and remove the key:\n{report(found)}")
        pytest.xfail(case["open"])
    assert not found, report(found)


def _fuzz(engine, workdir, name: str, strategy, examples: int, **options) -> None:
    last: dict = {"agreed": 0}

    @given(strategy)
    @_settings(examples)
    def agree(case):
        found = compare(engine, case, workdir, **options)
        last["agreed"] += not found
        if found:
            # Hypothesis replays the case it reports last, so this ends holding it
            last["case"], last["found"] = case, found
            raise AssertionError(report(found))

    if PROFILE["fixed"]:
        # derandomize alone seeds from a hash of agree's source, so a line
        # added to agree would draw new cases; a seed named for the generator
        # does not move
        agree = seed(zlib.crc32(name.encode()))(agree)

    try:
        agree()
        # nox -s fuzz passes -rP, so this reaches the log of every run
        print(f"{last['agreed']} generated cases, the engines agreeing on each")
    except AssertionError:
        if "case" in last:
            saved = save_regression(last["case"], last["found"])
            print(f"\ncounterexample written to {saved.relative_to(HERE.parents[1])}, "
                  f"which reads:\n{saved.read_text(encoding='utf-8')}")
        raise


@pytest.mark.parametrize("kind", sorted(CASES))
def test_engines_agree(kind, engine, workdir):
    _fuzz(engine, workdir, kind, CASES[kind](), CASES_PER_KIND)


def test_inversions_agree(engine, workdir):
    """The inversion of generated soundings, at parity.mjs's model tolerance.

    Soundings that read one resistivity at every spacing are left out
    (``ves_sheet`` gives them a gentle drift). What a layered inversion
    should report for a uniform half-space is an open question, awaiting
    the owner's decision: a one-layer model, which interpretation, design
    and the reports would all have to accept; two layers with the boundary
    marked unresolved; or a refusal. Today both engines fit two layers of
    the one resistivity with the boundary wherever each search left it.
    Perturbing Python's forward model by 1e-15 moves its own boundary by
    more than parity's 1e-3, and with a thickness factor of 1.0001 the
    model is not one ``open_questions`` leaves out, so whether the engines
    agree on it is luck. The sheet that recorded the question,
    regressions/ves-uniform-half-space-boundary.json (in the tree at
    74b123d), is retired from the replays for that reason until the owner
    decides.

    The models ``compare`` leaves out with ``open_questions`` are left out
    here too; see ``compare``. On a pull request the ten soundings are the
    same on every run until one of the things PROFILES lists changes, the
    Python forward model among them, when ten new ones are drawn. A new
    sample can land on a knife-edge model those rules do not cover, which
    is still a question for the owner; replaying the saved case on main
    tells such a case from a change that broke parity.
    """
    strategy = ves_case(varied=True).map(
        lambda case: {**case, "sheets": case["sheets"][:1], "options": {"invert": True}})
    _fuzz(engine, workdir, "inversions", strategy, INVERSIONS, open_questions=True)
