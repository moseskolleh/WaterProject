# Contributing

Use a branch and a pull request. Keep raw observations, computed results,
assumptions and approval records distinct. Never add illustrative coordinates to
make an example pass a readiness gate: the report that comes out says nothing
about where the number came from, and a stamped cover is the honest result.

## Development and checks

`noxfile.py` holds the whole sequence below as sessions, and CI calls the
same sessions step by step, so `nox -s check` passing here means CI passes:

```bash
python -m pip install -e '.[dev,app,extract]'
npm install --no-save playwright@1.56.1 axe-core@4.10.3
npx playwright install chromium
nox -s check      # lint, types, tests, bundles, parity, fuzz, browser, depth_spine, js
nox -s build      # regenerate every generated file, in order
nox -s examples   # rerun the worked examples and rewrite their index
nox -s release    # wheel, sdist and example packs in dist/
```

The sessions run in the current environment rather than in virtualenvs of
their own: the install above is what they test, the matrix in CI installs
the same way on each Python version, and the browser suites need
Playwright from `node_modules` beside the checkout. axe-core, the
accessibility checker `tests/webapp/a11y.mjs` puts into every page, is
installed beside it, in the same command: a second `npm install --no-save`
removes what the first put there. Both are test tools, never shipped; the
browser session refuses any axe-core but the version CI pins
(`AXE_CORE_VERSION` in `.github/workflows/ci.yml`), since a newer one knows
more rules. `check` also needs npm,
for the Depth Spine: it runs `npm ci`, the TypeScript check, `oxlint` and
both Vite builds in `ui/depth-spine`, then fails if the result differs
from what is committed under `src/groundwater/depth_spine/`. Those
comparisons, like CI's, are against the git index, so stage a file you
regenerated before checking it. The same install serves `js`, which
type-checks and lints the browser app in `docs/js` with the TypeScript and
`oxlint` the Depth Spine pins; the app is served as it is written, with
nothing compiled, minified or rewritten (its three largest scripts are joined
from parts, as below, and that is all), and its types
are JSDoc comments it ignores. `gwt-core.js` is held to TypeScript's strict
mode and every function on `GWT.core` carries a type for each parameter;
the other scripts are checked loosely (`web/jscheck/` says what each level
means). The test run reports line coverage, with no threshold.

The tests that take ten seconds or more - the Streamlit AppTests, the
example regeneration and a few report builds - are marked `slow`, and a
new test as slow as that should be marked too. Pull request CI runs them
on Python 3.12 only; `nox -s tests -- -m "not slow"` is the quick loop
while working.

What the sessions run, in order:

```bash
# check: lint, types, tests
python -m ruff check .    # the ruff pinned in the dev extra
python -m pyright         # likewise pinned; basic mode, see pyproject.toml
# then the modules on its exclude list, on their own: each must still fail
python -m pytest -q --cov=groundwater --cov-report=term
# check: bundles - the bundled data must match the source tables
python web/build_boundary_review.py --check
python web/build_js.py --check    # the three large scripts are the join of their parts
python web/build_webapp_data.py
python web/build_offline.py
git diff --exit-code -- docs/js/gwt-core.js docs/js/gwt-app.js \
    docs/js/gwt-charts.js docs/js/gwt-data.js docs/js/gwt-geo.js \
    docs/js/gwt-samples.js docs/sw.js
# check: parity, browser
python tests/webapp/make_reference.py --check
node tests/webapp/parity.mjs
node tests/webapp/offline.mjs
node tests/webapp/review.mjs
node tests/webapp/smoke.mjs
node tests/webapp/copilot.mjs
node tests/webapp/fieldkit.mjs
node tests/webapp/a11y.mjs    # axe-core on every page; fails on serious or critical
# check: depth_spine
(cd ui/depth-spine && npm ci && npx tsc -b && npm run lint && npm run build:all)
git diff --exit-code -- src/groundwater/depth_spine/frontend \
    src/groundwater/depth_spine/static/workspace.html
git ls-files --others --exclude-standard \
    -- src/groundwater/depth_spine/frontend    # must print nothing
# check: js - the browser app's types and lint, with ui/depth-spine's tools
npm --prefix ui/depth-spine exec -- tsc -p web/jscheck/tsconfig.core.json
npm --prefix ui/depth-spine exec -- tsc -p web/jscheck/tsconfig.json
node web/jscheck/public-api.mjs
npm --prefix ui/depth-spine exec -- oxlint -c web/jscheck/oxlintrc.json \
    --deny-warnings docs/js

# build: every generated file, in dependency order
(cd ui/depth-spine && npm ci && npm run build:all)
python web/build_boundary_review.py
python web/build_js.py
python web/build_webapp_data.py
python web/build_demo.py
python web/build_offline.py
```

Regenerate the browser bundles in that order after Python or data changes.
The Depth Spine goes first because `build_demo.py` inlines the Python
package, and the package carries the Depth Spine build; any change under
`src/` or `app/` changes `docs/wasm/index.html`, which the test suite holds
to a fresh build. `build_js.py` goes before `build_webapp_data.py`, which
hashes `gwt-core.js` into `gwt-data.js` as the engine's digest.
`build_offline.py` goes last: it hashes the whole app
shell, `gwt-data.js` and its bundles included, so running it before the bundle it is meant
to describe produces a release identifier for a shell that no longer
exists. `build_js.py`, `build_offline.py` and `build_boundary_review.py` take
`--check`. `tests/webapp/reference.json` is not in `build`: it moves only
when numbers are meant to, so run `python tests/webapp/make_reference.py`
by hand when they are.

Three scripts of the browser app are too long to read, or to review a change
in, as one file each: `gwt-core.js` is forty thousand lines, `gwt-app.js` ten
thousand and `gwt-charts.js` seven thousand. Each is one closure whose
sections call each other by bare name, so it cannot become several scripts,
but it can be written as several files. Its parts are in `web/src/<name>/`,
one for each banner section - a Python module's port in the engine, a page in
the app, a family of figures in the charts - named `NNN-name.js`, and
`python web/build_js.py` joins them in the order of their numbers into
`docs/js/<name>.js`. Edit the part, run it, and commit the part and the joined
file together. `docs/js` is still what Pages serves and what every test, `tsc`
and `oxlint` read, so they report lines of the joined file;
`python web/build_js.py --where docs/js/gwt-core.js:12345` gives the part and
the line in it. An edit made to one of the three in `docs/js` is overwritten
by the next join, and before that `nox -s bundles` and
`tests/test_web_build.py` fail on it, naming the line and the part it belongs
in. The join is a concatenation: nothing is added between two parts and
nothing is transformed or minified, so the browser still runs exactly
the text a person wrote. Every other script in `docs/js` is edited where it
is. The numbers go up in tens so that a new part can take one between its
neighbours'; nothing else may sit in a parts folder.

A release is all of its files or none of them. A precache that cannot complete
fails the install and leaves the device on the release it already had; an open
tab finishes on the release it started with, so close every app tab and reopen
to pick up a waiting update.

Nothing but `install` may write to the versioned cache. Serving a precached
file and quietly revalidating it back into that cache is what makes a
half-uploaded deploy become the app a file at a time, under the old release's
identifier, with no install having succeeded - which is the exact failure the
`addAll` is there to refuse. Anything in scope the release does not carry goes
in the separate runtime cache instead.

## Two engines, one answer

`src/groundwater/` and `docs/js/gwt-core.js` compute the same results, and
`tests/webapp/parity.mjs` holds them to each other against
`tests/webapp/reference.json`. It covers prose the two engines both write, not
only numbers: the handover works list is compared bullet for bullet, because
that list is what an interim payment is argued from and four of its seven
bullets once differed - a quantity surveyor reading one document got the screen
run, one reading the other got the casing size, and neither got the seal.

So a sentence both engines write is not worded twice: it is kept once, in
`src/groundwater/data/text/*.yaml`, and both engines read it. The water
quality recommendations are in `quality.yaml`, the handover works list in
`handover.yaml` and the works the reports cite in `references.yaml` (where
an id ending in `_web` is the browser's wording of a work the Python reports
cite in other words: settling each pair changes one app's reports, so it is
a change of its own). The package reads an entry
with `groundwater.text.phrase("quality.treat_health", parameters=...)`; the
browser reads the same files, which `web/build_webapp_data.py` emits into
`gwt-data.js`, with `C.phrase('quality.treat_health', {parameters: ...})`.
The two renderers are one grammar, written out in `groundwater/text.py`:
`{name}` takes a string, a number always names its format (`{depth:num}` as
`fmt_num` writes it, `{d:g}`, `{mm:.0f}`), `{n:plural:limit|limits}` agrees
with a count, and anything else - a missing value, a spare one, a bare
number, a lone brace - is an error rather than a sentence with a hole in it.
An entry that is a mapping rather than a string is a table, looked up by a
value from the data (`phrase_table` / `C.phraseTable`).

To add a sentence: put it in the file for its report under a lower-case key,
call it from both engines by its quoted id, run
`python web/build_webapp_data.py`, then `python tests/webapp/make_reference.py`
and the parity suite. `tests/test_text.py` fails if an entry is read by only
one engine, if the bundle carries another catalogue, or if either engine
still spells out a catalogued sentence for itself. Only the top-level files
are read, so the Krio catalogue step 9.2 needs can sit beside them in a
folder of its own, under the same ids. A sentence not yet in the catalogue is
still worded once in each engine, and the same in both.

The configuration defaults are kept the same way, in
`src/groundwater/data/defaults.json`: `config.py` builds every field's
default from it and keeps the reason for each value beside the field, and the
browser's `C.defaultConfig()` is a copy of the same file out of `gwt-data.js`.
Change a default there, regenerate the bundle, and both apps move together. A
new setting is a field in `config.py` and a key in the file;
`tests/test_text.py` holds the two to the same names and types. Neither the
defaults nor the sentences are part of the engine digest in `gwt-data.js`:
the inversion cache key already carries the whole VES configuration, and a
reworded sentence is not a different inversion.

Document-level assertions - what reaches the `.docx` a user downloads - belong
in `tests/webapp/review.mjs`, not in parity.

## The changelog

`CHANGELOG.md` is an index and `changelog/` holds the text: one file per
version, and `changelog/unreleased.md` for what has not been released. Write
an entry at the top of `changelog/unreleased.md` under a `### ` heading, then
add that heading, character for character, as the first bullet under
"Unreleased" in `CHANGELOG.md`. The heading is the only summary the index
gives and the only line of the entry a release's notes carry, so make it a
sentence a reader can use without the text. Below it, say what changed and
why in plain declarative sentences, with the exact names and numbers.
`tests/test_changelog.py` fails if the bullets and the headings differ, in
wording or in order.

To cut a release, rename `changelog/unreleased.md` to
`changelog/<version>.md`, change its title and the sentence under it to name
the version, rename the "Unreleased" section and its link in `CHANGELOG.md`
to match, and start a new `changelog/unreleased.md` under a new "Unreleased"
section. The release workflow refuses a tag whose `changelog/<version>.md`
does not exist, or whose section does not begin with the link to that file.
The notes it publishes are the section's list of headings and a link to the
file at the tag, because GitHub refuses a release body over 125,000
characters and one version's text has run to 357,000.

## Data corrections

Give the source URL, release date, licence, affected identifiers and a small
reproduction. Record the new checksum in `data_provenance.yaml`; the test suite
compares it, so a dataset quietly replaced with a different vintage shows up as
a mismatch rather than as numbers that changed for no reason.

Do not assign uncertain geometry by proximity alone.
`web/build_boundary_review.py` withholds chiefdom geometry that cannot place a
borehole - a piece of a chiefdom sitting an implausible distance from the rest
of it - and writes it to `src/groundwater/data/boundary_review.geojson` with
the measurements behind the decision and the chiefdom it probably belongs to.
It proposes; it does not reassign. `boundary_review.geojson` currently holds
the detached Maforki fragment, which shares a boundary with Mafindor in Kono.
Confirming that against a gazetteer, and moving it, is a data correction
somebody with a source should make.

`coverage_service_classes.csv` is the fixed scale both engines colour the
coverage map by. It is a display convention, not a dataset: where the breaks
fall is a judgement whichever way it is made, so each row carries the basis it
rests on. The two lowest are the Sphere handbook's figures for a tapstand and a
handpump, and the table says in the file that no copy of that standard is
committed here - read them as a stated basis, not as a standard this project
holds. Change the breaks and both engines follow; regenerate the bundle
afterwards so the browser sees the same table.

`sample_provenance.csv` says what each bundled example file actually holds:
`transcribed` verbatim from a real document, `reconstructed` (real
measurements with a column the original left blank filled in illustratively),
or `synthetic` (the readings were invented). The certification gate reads it,
so adding a sample file means adding its row - an unlisted file is treated as
the analyst's own work and its reports come out unmarked. Be strict about
`synthetic`: it is the class that keeps a report from stating results for a
sample nobody took. Regenerate the bundle afterwards so the browser sees the
same table.

The district polygons in `sl_admin_geoboundaries.geojson` are the pre-2017
fourteen: Karene and Falaba have none. A point is still placed in one of the
sixteen current districts through the chiefdom polygons and
`sl_chiefdom_district.csv`. Do not try to derive sixteen district polygons by
dissolving the chiefdoms - the rings are simplified independently, so
neighbouring chiefdoms no longer share vertices and their common boundary does
not cancel; `changelog/0.3.0.md` records the measurements, under "A note on
the sixteen districts". A correct dissolve needs a
geometric union over the raw geoBoundaries download, which is not committed.

## Examples and reports

```bash
python examples/run_rokel_geophysics.py
python examples/run_kuntolo_step_test.py
python examples/run_dr_timbo_completion.py
python examples/build_catalogue.py
python examples/build_catalogue.py --check
```

`nox -s examples` runs those five in that order.

`build_catalogue.py` writes `examples/CATALOGUE.md` from the files themselves -
counts out of the workbook readers, verdicts off each report's own cover - and
packs each case into `examples/packs/`. The packs are built rather than
committed; the index is committed and `--check` keeps it honest, so regenerate
it in the same change as any example output.

`--previews` also renders each report to PDF, which is the quickest way to
review page breaks, maps, captions and units. It needs LibreOffice
(`soffice`/`libreoffice`, or the path in `GWT_SOFFICE`) and is skipped with a
reason where there is none. Nothing depends on its output.

Commit an example's inputs and its regenerated outputs together. Report
contents are byte-reproducible, so a stale committed report shows up as a diff
rather than as a surprise later.
