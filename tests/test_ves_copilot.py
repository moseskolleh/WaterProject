"""The VES co-pilot's workbook, read by the Python parser (PLAN.md step 2.2).

The co-pilot is a page of the browser app (docs/js/gwt-ves-copilot.js), and
rule 6 of the plan is that a field tool writes the template the readers
already take. So the page's own code is run here, in Node, beside the
support and engine scripts it uses: the Rokel soundings are played back
into it reading by reading, it writes its workbook with the app's own
.xlsx writer, and ``read_ves_workbook`` reads that file as it reads any
VES template. tests/webapp/smoke.mjs plays the same readings through the
page in Chromium and reads the workbook with the browser's parser.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from groundwater.geo import geographic_to_utm
from groundwater.ingestion.ves import read_ves_workbook

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "docs" / "js"
ROKEL = REPO / "examples" / "data" / "rokel" / "rokel_ves.xlsx"

_PLAYBACK = r"""
import { readFileSync, writeFileSync } from 'node:fs';
import vm from 'node:vm';
const [dir, input, output] = process.argv.slice(2);
// what the .xlsx writer needs of a browser, which Node also has
const sandbox = { console, TextEncoder, TextDecoder, Blob, Response,
  CompressionStream, DecompressionStream };
sandbox.window = sandbox;
vm.createContext(sandbox);
for (const f of ['support.js', 'gwt-data.js', 'gwt-core.js', 'gwt-ves-copilot.js']) {
  vm.runInContext(readFileSync(dir + '/' + f, 'utf8'), sandbox, { filename: f });
}
const V = sandbox.GWT.vesCopilot, S = sandbox.GWT.support;
const job = JSON.parse(readFileSync(input, 'utf8'));
const out = { soundings: [], proposals: {} };
for (const s of job.soundings) {
  const session = V.blankSession(new Date(job.start));
  session.sounding_id = s.id;
  session.instrument = s.instrument;
  session.gps = { lat: 8.6, lon: -12.9, accuracy_m: 6, at: job.start };
  session.plan = s.readings.map((r) => ({ ab2: r[0], mn: r[1] }));
  s.readings.forEach((r, i) => {
    session.readings.push({ ab2: r[0], mn: r[1], v_mV: null, i_mA: null, rho: r[2],
      at: new Date(Date.parse(job.start) + 120000 * (i + 1)).toISOString() });
  });
  const bytes = await S.writeXlsx(V.workbookSheets(session, job.site));
  const path = output + '/' + s.file;
  writeFileSync(path, bytes);
  out.soundings.push({ id: s.id, path, review: V.review(session) });
}
for (const depth of job.depths) out.proposals[depth] = V.propose(depth);
writeFileSync(output + '/result.json', JSON.stringify(out));
"""


def _playback(tmp_path: Path) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; run `node --version` to check")
    soundings = [
        # the second with no instrument named: the reader must find nothing
        # there, not the device GPS cell further along the sheet
        {"id": s.sounding_id, "file": f"copilot_{k}.xlsx",
         "instrument": "Syscal Junior" if k == 0 else "",
         "readings": [[float(a), float(m), float(r)]
                      for a, m, r in zip(s.ab2, s.mn, s.rho_app, strict=True)]}
        for k, s in enumerate(read_ves_workbook(ROKEL))
    ]
    job = {
        "start": "2026-10-03T08:00:00Z",
        "site": {"client": "Living Water International", "community": "Rokel",
                 "project": "Co-pilot playback", "district": "Port Loko",
                 "chiefdom": "", "supervisor": "M. Kamara"},
        "soundings": soundings, "depths": [20, 50, 60, 120],
    }
    script = tmp_path / "playback.mjs"
    script.write_text(_PLAYBACK, encoding="utf-8")
    (tmp_path / "job.json").write_text(json.dumps(job), encoding="utf-8")
    subprocess.run([node, str(script), str(JS), str(tmp_path / "job.json"), str(tmp_path)],
                   check=True, timeout=300)
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    result["original"] = soundings
    return result


@pytest.fixture(scope="module")
def playback(tmp_path_factory):
    return _playback(tmp_path_factory.mktemp("copilot"))


def test_the_copilot_workbook_reads_back_through_the_python_parser(playback):
    """Every reading comes back as it was taken, with the header the
    co-pilot wrote: the sounding, the site, and the GPS fix as UTM."""
    for original, written in zip(playback["original"], playback["soundings"], strict=True):
        skipped = []
        (sounding,) = read_ves_workbook(written["path"], skipped)
        assert not skipped
        readings = np.array(original["readings"])
        assert sounding.sounding_id == original["id"]
        assert sounding.array_type == "schlumberger"
        np.testing.assert_array_equal(sounding.ab2, readings[:, 0])
        np.testing.assert_array_equal(sounding.mn, readings[:, 1])
        np.testing.assert_array_equal(sounding.rho_app, readings[:, 2])
        assert sounding.instrument == original["instrument"]
        assert sounding.site.community == "Rokel"
        assert sounding.site.client == "Living Water International"
        assert sounding.site.district == "Port Loko"
        assert sounding.site.supervisor == "M. Kamara"
        assert sounding.site.date == "2026-10-03"
        # the device's fix, 8.6 N 12.9 W, written as UTM 28N to the decimetre
        utm = geographic_to_utm(8.6, -12.9)
        assert sounding.site.utm_zone == utm.zone == 28
        assert sounding.site.easting == pytest.approx(utm.easting, abs=0.05)
        assert sounding.site.northing == pytest.approx(utm.northing, abs=0.05)
        # the engine's own office-side warning is still there in the file
        codes = {f.code for f in sounding.flags}
        assert "segment_overlap_discrepancy" in codes


def test_every_rokel_overlap_that_disagrees_said_remeasure_at_the_peg(playback):
    """PLAN.md step 2.2's done-when: the overlaps that disagree by 45 to 98
    percent would each have raised "re-measure now" at the peg, and those
    that agree would not."""
    raised = []
    for original, written in zip(playback["original"], playback["soundings"], strict=True):
        for reading, checks in zip(original["readings"], written["review"], strict=True):
            overlap = [c for c in checks if c["code"] == "overlap_discrepancy"]
            if overlap:
                assert overlap[0]["level"] == "remeasure"
                assert overlap[0]["message"].startswith("Re-measure now")
                raised.append((original["id"], reading[0]))
    assert raised == [("A (1)", 10.0), ("A (1)", 40.0),
                      ("B (2)", 10.0), ("B (2)", 40.0), ("B (2)", 70.0)]


def test_the_proposal_follows_the_depth_of_investigation_rule(playback):
    """The line is long enough for the target by the engines' one rule
    (0.5 of the largest AB/2), and no longer than the next spacing."""
    for depth, proposal in playback["proposals"].items():
        steps = proposal["steps"]
        assert proposal["max_ab2"] * 0.5 >= float(depth)
        assert steps[-1]["ab2"] == proposal["max_ab2"]
        # the spacing before the last would not have reached the target
        distinct = sorted({s["ab2"] for s in steps})
        assert len(distinct) < 2 or distinct[-2] * 0.5 < float(depth)
        for step in steps:
            assert step["mn"] * 5 <= 2 * step["ab2"]
        # every MN change repeats the AB/2 it changes at
        for before, after in zip(steps, steps[1:], strict=False):
            if after["mn"] != before["mn"]:
                assert after["ab2"] == before["ab2"]
