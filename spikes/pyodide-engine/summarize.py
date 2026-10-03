"""Print the spike's numbers from a measure.mjs results file.

    python spikes/pyodide-engine/summarize.py [spikes/pyodide-engine/results.json]

Medians over the repetitions, with the range beside them, and the check that
the three engines - Pyodide, CPython and gwt-core.js - agree to the
tolerances tests/webapp/parity.mjs holds the two apps to, on the inversion
and on the interpretation, and with tests/webapp/reference.json.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFERENCE = HERE.parents[1] / "tests" / "webapp" / "reference.json"

# parity.mjs: the model's resistivities and thicknesses to 1e-3 relative, its
# misfit to 1e-4, the interpretation's confidence to 1e-6; the zones, depths,
# flags, fit quality and narrative word for word.
TOL = {"rho": 1e-3, "h": 1e-3, "err": 1e-4, "confidence": 1e-6}
EXACT = ["water_zones", "max_drilling_depth_m", "investigation_depth_m",
         "max_spacing_m", "basement_not_resolved", "fit_quality", "flags", "narrative"]


def norm(value):
    """Numbers as floats: reference.json writes a whole number as 40, where
    the engines answer 40.0, and the two are the same value."""
    if isinstance(value, list):
        return [norm(v) for v in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return value


def close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(b))


def rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1e-300)


def spread(values: list[float]) -> str:
    med = statistics.median(values)
    if len(values) == 1:
        return f"{med:,.0f}"
    return f"{med:,.0f} ({min(values):,.0f}-{max(values):,.0f})"


def agree(a: dict, b: dict) -> tuple[bool, list[str], float]:
    """Whether two answers agree to parity's tolerances; what differs; the
    largest relative difference in the model."""
    bad, worst = [], 0.0
    for key in ("rho", "h"):
        if len(a["model"][key]) != len(b["model"][key]):
            bad.append(f"{key}: layer count")
            continue
        for x, y in zip(a["model"][key], b["model"][key], strict=True):
            worst = max(worst, rel(x, y))
            if not close(x, y, TOL[key]):
                bad.append(f"{key}: {x} vs {y}")
    worst = max(worst, rel(a["model"]["err"], b["model"]["err"]))
    if not close(a["model"]["err"], b["model"]["err"], TOL["err"]):
        bad.append(f"err: {a['model']['err']} vs {b['model']['err']}")
    ia, ib = a["interpretation"], b["interpretation"]
    if not close(ia["confidence"], ib["confidence"], TOL["confidence"]):
        bad.append(f"confidence: {ia['confidence']} vs {ib['confidence']}")
    for key in EXACT:
        if json.dumps(norm(ia[key])) != json.dumps(norm(ib[key])):
            bad.append(f"{key}: {json.dumps(ia[key])[:80]} vs {json.dumps(ib[key])[:80]}")
    return not bad, bad, worst


def reference_answers() -> dict:
    ref = json.loads(REFERENCE.read_text(encoding="utf-8"))
    out = {}
    for k, interp in enumerate(ref["interpretations"]):
        entry = {"interpretation": interp}
        if k == 0:  # the reference holds the model of the first sounding only
            inv = ref["inversion"]
            entry["model"] = {"rho": inv["rho"], "h": inv["h"], "err": inv["err"]}
        out[interp["id"]] = entry
    return out


def agree_reference(a: dict, ref: dict) -> tuple[bool, list[str]]:
    if "model" in ref:
        ok, bad, _ = agree(a, ref)
        return ok, bad
    # no model in the reference for this sounding: the interpretation only
    shim = {"model": a["model"], "interpretation": ref["interpretation"]}
    ok, bad, _ = agree(a, shim)
    return ok, bad


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else HERE / "results.json"
    R = json.loads(path.read_text(encoding="utf-8"))
    reps = R["reps"]
    ids = R["soundings"]
    print(f"{path.name}: {len(reps)} repetitions on {R['machine']['cpus']} CPUs "
          f"({R['machine']['model']}), Chromium {R['machine']['chromium']}; "
          f"load average {R['machine']['loadavg_before'][0]:.2f} before, "
          f"{R['machine']['loadavg_after'][0]:.2f} after")

    # --- the download
    files = R["manifest"]["files"]
    raw = sum(f["bytes"] for f in files)
    gz = sum(c["gzip9"] for c in R["compressed"].values())
    br = sum(c["brotli11"] for c in R["compressed"].values())
    print(f"\nPrecache, the Pyodide engine: {len(files)} files, {raw:,} bytes stored "
          f"({raw / 1e6:.1f} MB, {raw / 2**20:.1f} MiB); sent gzip -9 {gz:,} "
          f"({gz / 1e6:.1f} MB), brotli 11 {br:,} ({br / 1e6:.1f} MB)")
    for f in sorted(files, key=lambda f: -f["bytes"]):
        c = R["compressed"][f["url"]]
        print(f"  {f['url']:<62} {f['bytes']:>12,} {c['brotli11']:>12,}")
    cached = [r["precache"]["cached"]["total"] for r in reps]
    fetched = [r["precache"]["fetched"] for r in reps]
    print(f"  service worker cache, with the bench page and the app's engine "
          f"scripts: {spread(cached)} bytes held, {spread(fetched)} fetched to fill it")
    if R["unexpected_requests"]:
        print(f"  requests the server could not answer: {R['unexpected_requests']}")

    # --- the starts
    print("\nStart, new Worker() to ready, ms (median, range):")
    for stage in ("cold", "reload", "restart"):
        for eng in ("js", "py"):
            print(f"  {stage:<8} {eng}: {spread([r[stage][eng]['start']['ms'] for r in reps])}")
    print("  where a Pyodide start goes, ms (median of every worker start):")
    starts = [r[s]["py"]["start"]["phases"] for r in reps for s in ("cold", "reload", "restart")]
    for key in starts[0]:
        print(f"    {key:<22} {spread([p[key] for p in starts])}")
    if all("restart_numpy_only" in r for r in reps):
        print("  restart, numpy alone and no scipy (cannot invert): "
              f"{spread([r['restart_numpy_only']['ms'] for r in reps])}")
    print("  on the page, unthrottled (warm), py: "
          f"{spread([r['page1x']['py']['start']['ms'] for r in reps])}")
    print("  on the page, CPU 4x (warm), py:       "
          f"{spread([r['page4x']['py']['start']['ms'] for r in reps])}")
    print("  on the page, CPU 4x (cold), py:       "
          f"{spread([c['py']['start']['ms'] for c in R['cold_page_4x']])}")

    # --- the inversions
    def times(runs, eng, which, k, field):
        out = []
        for run in runs:
            item = run[eng][which][k]
            out.append(item["result"]["ms"]["invert"] if field == "invert" else item["ran"])
        return out

    print("\nInversion of each sounding, ms (median, range); py/js is the ratio of medians.")
    print("  In the worker: js is the task's time in the worker; py 'invert' is")
    print("  invert_sounding alone, py 'task' adds interpret_model and the JSON both ways.")
    for which in ("first", "second"):
        label = "first in the session" if which == "first" else "again, Pyodide already up"
        print(f"  {label}:")
        for k, sid in enumerate(ids):
            runs = [r[s] for r in reps for s in ("cold", "reload", "restart")]
            js = times(runs, "js", which, k, "ran")
            py = times(runs, "py", which, k, "invert")
            task = times(runs, "py", which, k, "ran")
            print(f"    {sid}: js {spread(js)}  py invert {spread(py)}  py task {spread(task)}"
                  f"  py/js {statistics.median(py) / statistics.median(js):.2f}"
                  f" (task {statistics.median(task) / statistics.median(js):.2f})")
    for stage, title in (("page1x", "on the page, CPU 1x"), ("page4x", "on the page, CPU 4x")):
        print(f"  {title}:")
        for k, sid in enumerate(ids):
            js = [r[stage]["js"][w][k]["result"]["ms"]["invert"] for r in reps
                  for w in ("first", "second")]
            py = [r[stage]["py"][w][k]["result"]["ms"]["invert"] for r in reps
                  for w in ("first", "second")]
            print(f"    {sid}: js {spread(js)}  py {spread(py)}  "
                  f"py/js {statistics.median(py) / statistics.median(js):.2f}")
    print("  the JavaScript worker while the page is throttled 4x (were workers")
    print("  throttled, this would be about four times its unthrottled time):")
    for k, sid in enumerate(ids):
        under = [r["worker_under_page_4x"]["js"][w][k]["ran"] for r in reps
                 for w in ("first", "second")]
        free = [r[s]["js"][w][k]["ran"] for r in reps for s in ("cold", "reload", "restart")
                for w in ("first", "second")]
        print(f"    {sid}: {spread(under)} under 4x, {spread(free)} unthrottled")
    print("  native CPython, one BLAS thread (invert_sounding alone):")
    for k, sid in enumerate(ids):
        nat = [n[k + p * len(ids)]["ms"]["invert"] for n in R["native"] for p in (0, 1)]
        print(f"    {sid}: {spread(nat)}")
    print(f"  versions: pyodide {reps[0]['cold']['py']['start']['versions']}, "
          f"native {R['native_versions']}")

    # --- memory
    print("\nMemory, bytes (median, range), each engine alone in a fresh browser:")
    for eng in ("js", "py"):
        rows = [m for m in R["memory"] if m["engine"] == eng]
        print(f"  {eng}: renderer peak resident {spread([m['rendererPeakBytes'] for m in rows])}")
        if eng == "py":
            print(f"      WebAssembly heap {spread([m['wasmHeapBytes'] for m in rows])}")
        ua = rows[0]["uaMemory"]
        if ua and "unavailable" in ua:
            print(f"      measureUserAgentSpecificMemory: {ua['unavailable']}")

    # --- agreement
    print("\nAgreement, at parity.mjs's tolerances:")
    ref = reference_answers()
    pairs = []
    for r in reps:
        for s in ("cold", "reload", "restart"):
            pairs += [("pyodide (worker)", x["result"]) for w in ("first", "second")
                      for x in r[s]["py"][w]]
            pairs += [("gwt-core.js (worker)", x["result"]) for w in ("first", "second")
                      for x in r[s]["js"][w]]
        for s in ("page1x", "page4x"):
            pairs += [("pyodide (page)", x["result"]) for w in ("first", "second")
                      for x in r[s]["py"][w]]
            pairs += [("gwt-core.js (page)", x["result"]) for w in ("first", "second")
                      for x in r[s]["js"][w]]
    native = {a["id"]: a for a in R["native"][0]}
    summary: dict[str, list] = {}
    for who, answer in pairs:
        ok_n, bad_n, worst = agree(answer, native[answer["id"]])
        ok_r, bad_r = agree_reference(answer, ref[answer["id"]])
        row = summary.setdefault(who, [0, 0, 0, 0.0, set()])
        row[0] += 1
        row[1] += ok_n
        row[2] += ok_r
        row[3] = max(row[3], worst)
        row[4].update(bad_n + bad_r)
    for nat in R["native"]:
        for a in nat:
            ok_r, bad_r = agree_reference(a, ref[a["id"]])
            row = summary.setdefault("native CPython", [0, 0, 0, 0.0, set()])
            row[0] += 1
            row[1] += 1
            row[2] += ok_r
            row[4].update(bad_r)
    for who, (n, ok_n, ok_r, worst, bad) in summary.items():
        print(f"  {who:<22} {n:>3} answers: {ok_n} agree with native CPython "
              f"(largest model difference {worst:.1e} relative), "
              f"{ok_r} with reference.json")
        for b in sorted(bad)[:6]:
            print(f"      {b}")
    distinct = {json.dumps([a["model"]["rho"], a["model"]["h"]]) for who, a in pairs
                if who.startswith("pyodide")}
    print(f"  distinct Pyodide models across every run: {len(distinct)} "
          f"(one per sounding means the runs are bit-identical)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
