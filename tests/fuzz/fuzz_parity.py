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
``rasters.py`` draws elevation models and their compressed blocks the same
way, and windows of heights for the terrain analysis, and the file both
engines are handed is then the block, the raster or the window's numbers
rather than a workbook.

A disagreement is written to ``tests/fuzz/regressions/`` and printed in the
log: on the nightly run shrunk by Hypothesis to the smallest sheet that still
shows it, on a pull request as drawn. Commit it with a note saying what it
was, and it is replayed on every run from then on.

An inversion on a knife edge is not a disagreement. Where one engine's own
answer moves when every reading moves by one ulp, at a place where the two
engines disagree, which of them ends where is the luck of the last bit;
``knife_edge`` says so, the case is printed and written to
``tests/fuzz/knife-edges/found/``, and the run goes on. A divergence that
neither engine's own answer moves at is still a failure. The ones committed
to ``tests/fuzz/knife-edges/`` are replayed to hold the check to its word.

The module is not named ``test_*`` so the ordinary pytest run, which has no
browser, does not collect it; ``nox -s fuzz`` names it explicitly.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
import zlib
from datetime import date
from pathlib import Path

import pytest
from hypothesis import HealthCheck, Phase, given, seed, settings

import rasters
import sheets
from engines import BrowserEngine, divergences, python_summary
from sheets import ves_case, workbook_bytes

HERE = Path(__file__).resolve().parent
REGRESSIONS = HERE / "regressions"
KNIFE_EDGES = HERE / "knife-edges"
# where a run writes the knife edges it finds; the replays read only the
# folder above, so one is kept by moving it up with a note
FOUND = KNIFE_EDGES / "found"

# Every generator, each seeded by its own name, so adding one draws nothing
# new for the others.
CASES = {**sheets.CASES, **rasters.CASES}

# What a case hands both engines: its sheets, or for the kinds in rasters.py
# its raster (a grid, for a kind that takes one). The regression files are
# written with the same key.
INPUTS = ("sheets", "raster", "grid")

# Cases per generator. A pull request runs the same few hundred every time,
# on any machine, and draws new ones when sheets.py or rasters.py, the
# Hypothesis version, a generator's name (its seed) or the number of cases
# changes, or a value a generator computes with the package, scipy or zlib:
# each VES reading comes from groundwater.ves.forward and each drawdown from
# scipy's exp1, and typed() draws once more for a reading that rounds to a
# whole number, so a change that carries one reading across a rounding draws
# every later case anew; and where a deflate case damages its stream is drawn
# within the stream zlib wrote, which another zlib build may write otherwise.
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
    the third agrees by luck and is replayed under these rules. A generated
    inversion that diverges anywhere else is put to ``knife_edge``, which
    asks the engines themselves whether the answer is one the last bit
    decides; these rules stay as they were.
    """
    return judge(*answers(engine, case, workdir), open_questions=open_questions)


def answers(engine: BrowserEngine, case: dict, workdir: Path) -> tuple:
    """``(browser, python, factors, settled)``: each engine's summary of
    ``case``, and apart from them what ``judge`` reads beside them.

    Judges, not answers: the Python model's own resolution, which the
    browser is not asked for, and whether each inversion converged, which
    no report prints. At a parameter bound one engine can stop for want of
    a better step while the other runs out its iterations, with models that
    agree to the tolerance.
    """
    data, suffix = case_file(case)
    path = workdir / f"case{suffix}"
    path.write_bytes(data)
    py = python_summary(case["kind"], path, str(path), case["options"])
    js = engine.summary(case["kind"], data, str(path), case["options"])
    factors = [inv.pop("h_factor", None) for inv in py.get("inversions") or []]
    settled = [[inv.pop("converged", None) for inv in side.get("inversions") or []
                if isinstance(inv, dict)] for side in (js, py)]
    return js, py, factors, settled


def judge(js: dict, py: dict, factors: list, settled: list,
          open_questions: bool = False) -> list:
    """Where ``js`` and ``py`` disagree, with ``compare``'s rules."""
    from groundwater.ves.interpret import POORLY_RESOLVED_FACTOR

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


# How knife_edge moves a sounding's readings: each one ulp up, each one down,
# and alternately one way and the other, starting either way.
NUDGES = ("up", "down", "up-down", "down-up")

# the number in a reading typed as text: "078.7", "1,5", "80m", " 261.1 "
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def nudged(case: dict, nudge: str) -> dict | None:
    """``case`` with every reading of every sounding moved one ulp, as
    ``nudge`` says, or None for a case with no readings to move.

    A reading is the cell in the last column of the table under the header
    row that starts "No.", as ``ves_sheet`` writes it. One typed as text
    stays text, spelt as it was, with only its number moved.
    """
    out = copy.deepcopy(case)
    moved = 0
    for sheet in out.get("sheets") or []:
        rows = sheet["rows"]
        head = next((i for i, row in enumerate(rows)
                     if row and str(row[0]).strip() == "No."), None)
        if head is None:
            continue
        column = max(k for k, cell in enumerate(rows[head]) if cell is not None)
        for row in rows[head + 1:]:
            # a reading's row is numbered; a spacer or a note is not
            if (column >= len(row) or isinstance(row[0], bool)
                    or not isinstance(row[0], (int, float))):
                continue
            cell = row[column]
            if isinstance(cell, str):
                match = _NUMBER.search(cell)
                if match is None:
                    continue
                value = float(match.group().replace(",", "."))
            elif isinstance(cell, (int, float)) and not isinstance(cell, bool):
                match = None
                value = float(cell)
            else:
                continue
            if not math.isfinite(value):
                continue
            up = {"up": True, "down": False, "up-down": moved % 2 == 0,
                  "down-up": moved % 2 == 1}[nudge]
            value = math.nextafter(value, math.inf if up else -math.inf)
            if match is None:
                row[column] = value
            else:
                text = repr(value)
                if "," in match.group():
                    text = text.replace(".", ",")
                row[column] = cell[:match.start()] + text + cell[match.end():]
            moved += 1
    return out if moved else None


def knife_edge(engine: BrowserEngine, case: dict, workdir: Path, found: list,
               js: dict, py: dict) -> str | None:
    """Why the divergence ``found`` between ``js`` and ``py`` on an
    inversion of ``case`` is a knife edge, or None if it is not one.

    It is one when, with every reading moved by one ulp in one of the ways
    NUDGES lists, either engine's own answer moves by more than parity's
    tolerance at a place the two disagree. An answer the last bit of the
    readings moves is not one either engine can be held to, by the other
    or by itself (the two in knife-edges/ say how far one moved). The place
    must be one of those in ``found``: a poorly resolved boundary that
    moves says nothing about a layer count the engines disagree on. A
    disagreement neither engine moves at, as the browser's old Bessel
    tables and interp edge gave (see the regressions named for them), is
    still a divergence.
    """
    where = {path for path, _, _ in found}
    for nudge in NUDGES:
        moved = nudged(case, nudge)
        if moved is None:
            return None
        js_moved, py_moved, _, _ = answers(engine, moved, workdir)
        for side, before, after in (("the browser", js, js_moved), ("Python", py, py_moved)):
            moves = [d for d in divergences({"inversions": after.get("inversions")},
                                            {"inversions": before.get("inversions")})
                     if d[0] in where]
            if moves:
                path, now, then = moves[0]
                return (f"{side}'s own {path} moves from {json.dumps(then)} to "
                        f"{json.dumps(now)} with every reading one ulp {nudge}")
    return None


def case_file(case: dict) -> tuple[bytes, str]:
    """The file both engines read for ``case``, and its suffix: the workbook
    of a field sheet, or for a kind in rasters.py what that kind is handed."""
    if case["kind"] in rasters.FILES:
        return rasters.FILES[case["kind"]](case)
    return workbook_bytes(case["sheets"]), ".xlsx"


def report(found: list) -> str:
    lines = [f"the engines disagree in {len(found)} place(s):"]
    for where, js, py in found[:12]:
        lines.append(f"  {where}\n    browser {json.dumps(js)[:400]}\n"
                     f"    python  {json.dumps(py)[:400]}")
    return "\n".join(lines)


def save_regression(case: dict, found: list) -> Path:
    """Write a counterexample where the next run replays it: shrunk on the
    nightly run, as drawn on a pull request."""
    return _save(REGRESSIONS, case, found, "Found by the fuzz suite on "
                 + date.today().isoformat()
                 + ". Say here what diverged and which engine was put right.")


def save_knife_edge(case: dict, found: list, reason: str) -> Path:
    """Write a knife edge to FOUND, which no run replays."""
    return _save(FOUND, case, found, "Found by the fuzz suite on "
                 + date.today().isoformat() + ", on a knife edge: " + reason
                 + ". Say here what the engines were choosing between, and move it "
                 "up a folder to keep it.")


def _save(folder: Path, case: dict, found: list, note: str) -> Path:
    where = found[0][0]
    slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"\[\d+\]", "", where).lower()).strip("-")
    body = json.dumps({key: case[key] for key in ("kind", *INPUTS, "options") if key in case},
                      sort_keys=True)
    digest = hashlib.sha1(body.encode()).hexdigest()[:8]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{case['kind']}-{slug[:40]}-{digest}.json"
    path.write_text(regression_text({
        "note": note,
        "first_divergence": [where, found[0][1], found[0][2]],
        **json.loads(body),
    }), encoding="utf-8")
    return path


def regression_text(case: dict) -> str:
    """A regression file a reviewer can read: one sheet row to a line, or
    for a raster or a grid one member to a line, and one row of any table
    in it."""
    def one(value):
        return json.dumps(value, ensure_ascii=False)

    lines = ["{"]
    for key in ("note", "open", "as_generated", "first_divergence", "kind", "options"):
        if key in case:
            lines.append(f" {one(key)}: {one(case[key])},")
    if "sheets" in case:
        lines.append(' "sheets": [')
        for i, sheet in enumerate(case["sheets"]):
            lines.append(f'  {{"name": {one(sheet["name"])}, "rows": [')
            lines.append(",\n".join(f"   {one(row)}" for row in sheet["rows"]))
            lines.append("  ]}" + ("," if i + 1 < len(case["sheets"]) else ""))
        lines.append(" ]")
    else:
        key = next(k for k in INPUTS if k in case)
        members = []
        for name, value in case[key].items():
            if isinstance(value, list) and value and all(isinstance(row, list) for row in value):
                rows = ",\n".join(f"   {one(row)}" for row in value)
                members.append(f"  {one(name)}: [\n{rows}\n  ]")
            else:
                members.append(f"  {one(name)}: {one(value)}")
        lines.append(f" {one(key)}: {{")
        lines.append(",\n".join(members))
        lines.append(" }")
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


@pytest.mark.parametrize("path", sorted(KNIFE_EDGES.glob("*.json")), ids=lambda p: p.stem)
def test_knife_edge(path, engine, workdir):
    """Every generated inversion kept as a knife edge, judged again as
    test_inversions_agree judges one.

    The engines may agree on it today or not: on a knife edge either is the
    luck of the last bit. While they disagree, ``knife_edge`` must still
    find one of their own answers moving where they do. The day it finds
    none, the disagreement is a divergence like any other, and this fails
    with it.
    """
    case = json.loads(path.read_text(encoding="utf-8"))
    js, py, factors, settled = answers(engine, case, workdir)
    found = judge(js, py, factors, settled, open_questions=True)
    if found:
        assert knife_edge(engine, case, workdir, found, js, py), (
            "no longer a knife edge: neither engine's own answer moves where "
            "they disagree when the readings move one ulp\n" + report(found))


def _fuzz(engine, workdir, name: str, strategy, examples: int,
          knife_edges: bool = False, **options) -> None:
    """``knife_edges``: a divergence on which ``knife_edge`` finds one
    engine's own answer moving is printed, kept in FOUND and passed."""
    last: dict = {"agreed": 0, "edges": {}}

    @given(strategy)
    @_settings(examples)
    def agree(case):
        js, py, factors, settled = answers(engine, case, workdir)
        found = judge(js, py, factors, settled, **options)
        if found and knife_edges:
            reason = knife_edge(engine, case, workdir, found, js, py)
            if reason:
                last["edges"][json.dumps(case, sort_keys=True)] = (case, found, reason)
                return
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
        edges = len(last["edges"])
        print(f"{last['agreed']} generated cases, the engines agreeing on each"
              + (f"; {edges} more on a knife edge" if edges else ""))
    except AssertionError:
        if "case" in last:
            saved = save_regression(last["case"], last["found"])
            print(f"\ncounterexample written to {saved.relative_to(HERE.parents[1])}, "
                  f"which reads:\n{saved.read_text(encoding='utf-8')}")
        raise
    finally:
        # a run that fails keeps the knife edges it passed on its way too
        for case, found, reason in last["edges"].values():
            saved = save_knife_edge(case, found, reason)
            print(f"\na knife edge, not a divergence: {reason}. "
                  f"{report(found)}\nwritten to {saved.relative_to(HERE.parents[1])}, "
                  f"which reads:\n{saved.read_text(encoding='utf-8')}")


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
    The sheet that recorded the question,
    regressions/ves-uniform-half-space-boundary.json (in the tree at
    74b123d), stays retired from the replays; the engines agree on it
    today, which is luck.

    The models ``compare`` leaves out with ``open_questions`` are left out
    here too; see ``compare``. A divergence on any other model is put to
    ``knife_edge``: where one engine's own answer moves when the readings
    move by one ulp, the case is a knife edge, printed and kept in FOUND,
    and does not fail the run. The two the nightly run found first are in
    knife-edges/: a layer count that a one-ulp change to Python's
    quadrature weights flips from four to three, and a top layer the data
    do not determine, which the browser's search left at 18,763 ohm-m and
    10,507 when one starting value moved by an ulp. What parity should
    hold a knife edge to otherwise is left as it was: nothing.

    On a pull request the ten soundings are the same on every run until one
    of the things PROFILES lists changes, the Python forward model among
    them, when ten new ones are drawn.
    """
    strategy = ves_case(varied=True).map(
        lambda case: {**case, "sheets": case["sheets"][:1], "options": {"invert": True}})
    _fuzz(engine, workdir, "inversions", strategy, INVERSIONS, knife_edges=True,
          open_questions=True)
