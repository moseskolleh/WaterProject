# Contributing

Use a branch and a pull request. Keep raw observations, computed results,
assumptions and approval records distinct. Never add illustrative coordinates to
make an example pass a readiness gate: the report that comes out says nothing
about where the number came from, and a stamped cover is the honest result.

## Development and checks

```bash
python -m pip install -e '.[dev,app,extract]'
python -m pytest -q
ruff check .
python tests/webapp/make_reference.py --check
python web/build_boundary_review.py --check
python web/build_webapp_data.py
python web/build_demo.py
python web/build_offline.py
npm install --no-save playwright@1.56.1
npx playwright install chromium
node tests/webapp/parity.mjs
node tests/webapp/offline.mjs
node tests/webapp/review.mjs
node tests/webapp/smoke.mjs
```

Regenerate the browser bundles in that order after Python or data changes.
`build_offline.py` goes last: it hashes the whole app shell, `gwt-data.js`
included, so running it before the bundle it is meant to describe produces a
release identifier for a shell that no longer exists. Both `build_offline.py`
and `build_boundary_review.py` take `--check`, which is what CI uses.

A release is all of its files or none of them. A precache that cannot complete
fails the install and leaves the device on the release it already had; an open
tab finishes on the release it started with, so close every app tab and reopen
to pick up a waiting update.

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

The district polygons in `sl_admin_geoboundaries.geojson` are the pre-2017
fourteen: Karene and Falaba have none. A point is still placed in one of the
sixteen current districts through the chiefdom polygons and
`sl_chiefdom_district.csv`. Do not try to derive sixteen district polygons by
dissolving the chiefdoms - the rings are simplified independently, so
neighbouring chiefdoms no longer share vertices and their common boundary does
not cancel; CHANGELOG.md records the measurements. A correct dissolve needs a
geometric union over the raw geoBoundaries download, which is not committed.

## Examples and reports

```bash
python examples/run_rokel_geophysics.py
python examples/run_kuntolo_step_test.py
python examples/run_dr_timbo_completion.py
python examples/build_catalogue.py
python examples/build_catalogue.py --check
```

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
