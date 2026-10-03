"""The check sequence from CONTRIBUTING.md, as commands rather than prose.

    nox -l                 list the sessions
    nox -s check           everything CI checks, in CI's order
    nox -s build           regenerate every generated file, in order
    nox -s parity          the numerical parity of the two engines
    nox -s fuzz            the two engines on generated field sheets
    nox -s types           Pyright on the package
    nox -s js              tsc and oxlint over the browser app in docs/js
    nox -s coverage        the tests, with a line coverage report
    nox -s examples        rerun the worked examples and their index
    nox -s release         the wheel, the sdist and the example packs in dist/

CI calls these same sessions (lint, types, tests or coverage, bundles,
parity, fuzz, browser, depth_spine, js) one step at a time, so a command changed
here changes in CI with it and "nox -s check passes" keeps meaning "CI
passes". The one thing CI adds is the Python version matrix: it runs the
tests session on four versions, the fast part on three of them and the
whole suite, under coverage, on 3.12.

Every session runs in the environment nox was started from rather than in
a virtualenv of its own. The flow CONTRIBUTING.md describes installs the
toolkit into the current environment with its extras, CI does the same on
each matrix version, and the browser suites need Playwright from the
node_modules beside the checkout; a nox-made virtualenv would install a
second copy of everything on every run and still have to reach outside
itself for node. So install first, once:

    python -m pip install -e '.[dev,app,extract]'
    npm install --no-save playwright@1.56.1
    npx playwright install chromium

Arguments after -- go to pytest in the tests session (for example
nox -s tests -- -m "not slow") and to ruff in the lint session.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

import nox

nox.options.default_venv_backend = "none"
nox.options.sessions = ["check"]

REPO = Path(__file__).resolve().parent
SPINE = REPO / "ui" / "depth-spine"

# What each Depth Spine build writes. Both are committed inside the package,
# because Streamlit Community Cloud has no npm and a wheel has to carry them.
SPINE_OUTPUT = [
    "src/groundwater/depth_spine/frontend",
    "src/groundwater/depth_spine/static/workspace.html",
]

# The bundles CI rebuilds and compares. build_offline.py is last because it
# hashes the whole app shell, gwt-data.js and the bundles beside it included.
BUNDLES = ["docs/js/gwt-data.js", "docs/js/gwt-geo.js", "docs/js/gwt-samples.js",
           "docs/sw.js"]

EXAMPLES = [
    "examples/run_rokel_geophysics.py",
    "examples/run_kuntolo_step_test.py",
    "examples/run_dr_timbo_completion.py",
]

BROWSER_SUITES = [
    "tests/webapp/offline.mjs",
    "tests/webapp/review.mjs",
    "tests/webapp/smoke.mjs",
    "tests/webapp/copilot.mjs",
    "tests/webapp/fieldkit.mjs",
]


def _python(session: nox.Session, *args: str, **kwargs) -> None:
    # The python on PATH, not the one running nox: nox installed with pipx
    # runs from an environment of its own that has no toolkit in it.
    session.run("python", *args, **kwargs)


def _need_playwright(session: nox.Session) -> None:
    # The suites import playwright from node_modules; without it every one of
    # them dies on the import with a stack trace that does not say what to do.
    if not (REPO / "node_modules" / "playwright").exists():
        session.error(
            "Playwright is not installed beside the checkout. Run:\n"
            "  npm install --no-save playwright@1.56.1\n"
            "  npx playwright install chromium"
        )


def _unchanged(session: nox.Session, paths: list[str], rebuild: str) -> None:
    """Fail if a fresh build differs from the committed files, as CI does.

    The untracked files are listed as well as the edited ones, because Vite
    names assets by content hash: a source change nobody rebuilt shows up as
    a new untracked asset and a deleted one, not only as an edit. The stat is
    printed rather than the diff because every one of these files is minified
    or generated, and a one-line change to them is a screenful of noise.

    Both compare the working tree against the index, so a file regenerated
    here and not yet staged counts as a difference: stage it, and the check
    holds it to what the commit will carry. git status would not do that: it
    also lists what is staged and not yet committed.
    """
    edited = session.run(
        "git", "--no-pager", "diff", "--stat", "--", *paths, silent=True,
    )
    untracked = session.run(
        "git", "ls-files", "--others", "--exclude-standard", "--", *paths,
        silent=True,
    )
    changed = (edited or "") + (untracked or "")
    if changed.strip():
        session.error(
            f"a fresh build differs from the committed files:\n{changed}"
            f"Regenerate them with:\n  {rebuild}\nand commit the result."
        )


def _pinned(session: nox.Session, tool: str, **kwargs) -> None:
    # Through python -m, so it is the copy the dev extra installed rather than
    # whichever one comes first on PATH, and held to that extra's pin: another
    # version can pass here and fail in CI.
    pin = re.search(rf'"{tool}==([^"]+)"', (REPO / "pyproject.toml").read_text())
    version = session.run("python", "-m", tool, "--version", silent=True, **kwargs)
    if pin and version.split()[-1] != pin.group(1):
        session.error(
            f"this is {version.strip()}, but CI runs {tool} {pin.group(1)}. Run:\n"
            f"  python -m pip install {tool}=={pin.group(1)}"
        )


def _lint(session: nox.Session, *args: str) -> None:
    _pinned(session, "ruff")
    _python(session, "-m", "ruff", "check", *args, ".")


# The pip package is a wrapper that fetches the pyright of its own version
# from npm on first use; this stops it printing that a newer one exists,
# which is not something a check run should be telling anyone.
PYRIGHT_ENV = {"PYRIGHT_PYTHON_IGNORE_WARNINGS": "1"}


def _types(session: nox.Session) -> None:
    _pinned(session, "pyright", env=PYRIGHT_ENV)
    _python(session, "-m", "pyright", env=PYRIGHT_ENV)
    _excluded_still_fail(session)


def _excluded_still_fail(session: nox.Session) -> None:
    # pyproject.toml's exclude is the list of modules that do not pass yet,
    # and it is meant only to get shorter. Pyright cannot say that a module
    # on it has started passing, so this asks: the excluded modules are
    # checked on their own, under the same settings without the exclude, and
    # one that reports no error has to come off the list in the change that
    # made it pass. A path that no longer exists has to come off too.
    text = (REPO / "pyproject.toml").read_text()
    section = text.split("[tool.pyright]", 1)[1].split("\n[", 1)[0]
    block = re.search(r"^exclude = \[(.*?)\]", section, re.S | re.M)
    excluded = re.findall(r'"([^"]+)"', block.group(1)) if block else []
    gone = [path for path in excluded if not (REPO / path).is_file()]
    if gone:
        session.error("no such module on pyright's exclude list in "
                      "pyproject.toml; take it off:\n  " + "\n  ".join(gone))
    if not excluded:
        return
    # typeCheckingMode, pythonVersion and the report* overrides: every
    # setting in the section that is a single quoted value
    settings = dict(re.findall(r'^(\w+) = "([^"]*)"', section, re.M))
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "pyrightconfig.json"
        config.write_text(json.dumps(settings))
        # Pyright exits 1 when it finds errors, which here is the expected
        # outcome; the JSON says which files they are in.
        report = session.run("python", "-m", "pyright", "--outputjson",
                             "-p", str(config), *excluded, silent=True,
                             success_codes=[0, 1], env=PYRIGHT_ENV)
    failing = {Path(d["file"]).resolve() for d in json.loads(report)["generalDiagnostics"]
               if d["severity"] == "error"}
    passing = [path for path in excluded if (REPO / path).resolve() not in failing]
    if passing:
        session.error("these modules pass pyright now; take them off the "
                      "exclude list in pyproject.toml:\n  " + "\n  ".join(passing))
    session.log(f"all {len(excluded)} modules on pyright's exclude list still fail")


# Line coverage of the package, printed after the tests. It is a report and
# not a gate: there is no threshold, so a change that adds an untested line
# is told so rather than failed.
COVERAGE = ["--cov=groundwater", "--cov-report=term"]


def _tests(session: nox.Session, *args: str) -> None:
    _python(session, "-m", "pytest", "-q", *args, env={"MPLBACKEND": "Agg"})


@nox.session
def lint(session: nox.Session) -> None:
    """Ruff, at the version pinned in the dev extra and in CI."""
    _lint(session, *session.posargs)


@nox.session
def types(session: nox.Session) -> None:
    """Pyright in basic mode, on the modules pyproject.toml does not exclude."""
    _types(session)


@nox.session
def tests(session: nox.Session) -> None:
    """The pytest suite. CI passes -m "not slow" or -m slow through posargs."""
    _tests(session, *session.posargs)


@nox.session
def coverage(session: nox.Session) -> None:
    """The pytest suite with a line coverage report, and no threshold."""
    _tests(session, *COVERAGE, *session.posargs)


@nox.session
def bundles(session: nox.Session) -> None:
    """The bundled browser data must match the source tables.

    The chiefdom layer is checked before the bundle is built from it, so a
    withheld boundary fragment that never made it back into the committed
    data is reported as itself rather than as a puzzling bundle diff.
    """
    _python(session, "web/build_boundary_review.py", "--check")
    _python(session, "web/build_webapp_data.py")
    _python(session, "web/build_offline.py")
    _unchanged(session, BUNDLES, "nox -s build")


@nox.session
def parity(session: nox.Session) -> None:
    """The browser engine held to the Python package's own numbers.

    --check compares within a tolerance rather than byte for byte: LAPACK is
    not bit reproducible across BLAS builds, so the last digit of a fitted
    transmissivity legitimately differs between machines.
    """
    _need_playwright(session)
    _python(session, "tests/webapp/make_reference.py", "--check")
    session.run("node", "tests/webapp/parity.mjs")


@nox.session
def fuzz(session: nox.Session) -> None:
    """The two engines against each other on generated field sheets.

    A few hundred cases, the same ones every run; FUZZ_PROFILE=nightly draws
    tens of thousands of new ones, and FUZZ_EXAMPLES sets the number per
    generator. Every counterexample committed under tests/fuzz/regressions
    is replayed first. The module is named by path because it is not a
    test_* file: the plain pytest run has no browser to give it.
    """
    _need_playwright(session)
    # -rP prints each generator's count of cases, which is otherwise captured
    _python(session, "-m", "pytest", "-q", "-rP", "-p", "no:cacheprovider",
            "tests/fuzz/fuzz_parity.py", *session.posargs, env={"MPLBACKEND": "Agg"})


@nox.session
def browser(session: nox.Session) -> None:
    """Drive the standalone app end to end in headless Chromium."""
    _need_playwright(session)
    for suite in BROWSER_SUITES:
        session.run("node", suite)


@nox.session
def depth_spine(session: nox.Session) -> None:
    """Type-check, lint and rebuild the Depth Spine; the build must match.

    Vite names the component's assets by content hash, so a source change
    that was never rebuilt shows up as a changed index.html and an untracked
    asset rather than as a diff in a file that already exists.
    """
    session.chdir(SPINE)
    session.run("npm", "ci", "--no-audit", "--no-fund")
    session.run("npx", "tsc", "-b")
    session.run("npm", "run", "lint")
    session.run("npm", "run", "build:all")
    session.chdir(REPO)
    _unchanged(session, SPINE_OUTPUT, "nox -s build")


@nox.session
def js(session: nox.Session) -> None:
    """Type-check and lint the browser app in docs/js, which has no build.

    The TypeScript and oxlint are ui/depth-spine's, at the versions its
    lockfile pins, rather than a second package.json pinning the same two
    tools again for Dependabot to move one at a time. Nothing here builds or
    rewrites docs/: the app is served as it is written, and the types are
    JSDoc comments it ignores. gwt-core.js is checked strictly, the other
    scripts loosely; web/jscheck/tsconfig*.json say what each level means.
    """
    session.chdir(SPINE)
    session.run("npm", "ci", "--no-audit", "--no-fund")
    session.chdir(REPO)
    spine = ["npm", "--prefix", str(SPINE), "exec", "--"]
    session.run(*spine, "tsc", "-p", "web/jscheck/tsconfig.core.json")
    session.run(*spine, "tsc", "-p", "web/jscheck/tsconfig.json")
    session.run("node", "web/jscheck/public-api.mjs")
    session.run(*spine, "oxlint", "-c", "web/jscheck/oxlintrc.json",
                "--deny-warnings", *session.posargs, "docs/js")


@nox.session
def check(session: nox.Session) -> None:
    """Everything CI checks, in CI's order. Stops at the first failure."""
    # Arguments after -- are not passed on: they would reach ruff and pytest
    # alike, and a check run with a narrowed suite is not the check CI runs.
    _lint(session)
    _types(session)
    _tests(session, *COVERAGE)
    for step in (bundles, parity, fuzz, browser, depth_spine, js):
        session.log(f"--- {step.__name__}")
        step(session)


@nox.session
def build(session: nox.Session) -> None:
    """Regenerate every generated file, in the order each depends on the last.

    The Depth Spine goes first because build_demo.py inlines the package,
    and the package carries the Depth Spine build. build_offline.py goes
    last because it hashes the shell everything before it wrote into.
    tests/webapp/reference.json is not here: it moves only when numbers are
    meant to, so regenerate it by hand with tests/webapp/make_reference.py.
    """
    session.chdir(SPINE)
    session.run("npm", "ci", "--no-audit", "--no-fund")
    session.run("npm", "run", "build:all")
    session.chdir(REPO)
    _python(session, "web/build_boundary_review.py")
    _python(session, "web/build_webapp_data.py")
    _python(session, "web/build_demo.py")
    _python(session, "web/build_offline.py")


@nox.session
def examples(session: nox.Session) -> None:
    """Rerun the worked examples, then rewrite and verify their index."""
    for script in EXAMPLES:
        _python(session, script)
    _python(session, "examples/build_catalogue.py")
    _python(session, "examples/build_catalogue.py", "--check")


@nox.session
def release(session: nox.Session) -> None:
    """The wheel, the sdist and one pack per worked example, in dist/.

    dist/ is emptied first so nothing from an earlier build rides along with
    this one. The index is checked before the packs are made: a release
    whose examples have drifted from their committed outputs is not one to
    publish.
    """
    dist = REPO / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    # setuptools stages into build/ and only refreshes files it thinks are
    # newer, so a stale staging tree can put a deleted file into the wheel.
    shutil.rmtree(REPO / "build", ignore_errors=True)
    _python(session, "-m", "build", "--outdir", str(dist), str(REPO))
    _python(session, "examples/build_catalogue.py", "--check")
    _python(session, "examples/build_catalogue.py")
    for pack in sorted((REPO / "examples" / "packs").glob("*.zip")):
        shutil.copy2(pack, dist / pack.name)
    session.log("dist/: " + ", ".join(sorted(p.name for p in dist.iterdir())))
