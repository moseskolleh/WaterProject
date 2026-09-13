# Contributing

Use a branch and a pull request. Keep raw observations, computed results,
assumptions and approval records distinct. Never add illustrative coordinates to
make an example pass a readiness gate.

## Development and checks

```bash
python -m pip install -e '.[dev,app,extract]'
python -m pytest -q
ruff check .
python tests/webapp/make_reference.py --check
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

Regenerate both browser bundles after Python/data changes. Generate `sw.js` last:
its release identifier hashes the complete app shell. A failed precache must keep
the previous release. Existing open tabs finish using their current release;
close all app tabs and reopen to activate a waiting update.

## Data corrections

Give the source URL, release date, licence, affected identifiers and a small
reproduction. Preserve superseded observations in the inventory audit. Do not
assign uncertain geometry by proximity alone. `boundary_review.geojson` retains
the detached Maforki fragment pending authoritative chiefdom ownership.

The sixteen display districts are reconstructed from chiefdoms and the current
crosswalk. `web/build_current_districts.py` requires Shapely and records topology
repairs. The original fourteen-district file remains available for provenance.
These display polygons are not a newly verified legal boundary dataset.

## Examples and reports

```bash
python examples/run_rokel_geophysics.py
python examples/run_kuntolo_step_test.py
python examples/run_dr_timbo_completion.py
python examples/build_catalogue.py --previews
```

PDF previews require LibreOffice (`soffice`/`libreoffice`, or `GWT_SOFFICE`).
Review page breaks, maps, captions, units, incomplete evidence and source labels.
Commit catalogue inputs, expected results and published packs together.
