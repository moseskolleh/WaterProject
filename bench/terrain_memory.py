"""Measure the memory the terrain analysis takes at the cap on cells.

``bench/run.py`` times the analysis at the cap, but its output has no
field for memory, and a peak cannot be taken in the process that runs it:
``ru_maxrss`` only ever rises, and writing the synthetic tile alone holds
more than the analysis does. So this script writes the tile ``run.py``
writes in one fresh interpreter, then reads the widest window the cap
allows and analyses it in another, where nothing but a small warm-up has
run before, and prints one JSON document:

- ``increase_mb``: the peak resident set size once the analysis has
  returned (``ru_maxrss``) less the resident set size just before it,
  with the window already read and held. This is the analysis's own
  memory, the figure the cap's memory budget takes (bench/README.md,
  "The terrain analysis: why 2,000,000 cells");
- ``read_mb``: what reading the window added before that, the grid held;
- ``first_use_mb``: what a first analysis of a small window left behind.
  numpy, the reader and the analysis's module are imported before it, as
  an app has them before anyone analyses. It runs first, as ``run.py``'s
  warm-up call does, so that the modules the analysis imports on first
  use (parts of scipy) are counted here and not in ``increase_mb``. An
  app that has not loaded them yet pays them too;
- ``peak_set_by_analysis``: whether the analysis raised the peak. If it
  did not, something before it held more and ``increase_mb`` is not the
  analysis's;
- ``seconds``: the wall time of that one analysis, for orientation only;
  ``run.py``'s median is the time to quote;
- the window (radius shown, margin, cells analysed, the cap, the
  precision of the layers kept), the commit, the date and the machine,
  in the block ``run.py`` writes, taken before any of the work.

The interpreter that starts the other two stays small, loading neither
numpy nor the tile: Linux carries the peak resident set size of a process
into an interpreter it starts, so one started by a process that had held
the tile would begin with a peak above the analysis's.

MB here are 2**20 bytes, which is ``ps -o rss`` (in kilobytes) divided by
1024, so the figure adds directly to a resident set size taken with
``ps``. The resident set size just before the analysis is read from
``/proc/self/statm``, so this runs on Linux only.

Run from the repository root (about 15 s here, most of it writing the
tile):

    python bench/terrain_memory.py
    python bench/terrain_memory.py --out memory.json

``--write-tile PATH`` writes the synthetic tile alone, on any system, and
prints the run's header: ``bench/web.mjs`` times the browser app's
terrain card on the same tile with it.
"""

from __future__ import annotations

import argparse
import gc
import importlib
import importlib.util
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = "bench/terrain_memory.py"
STATM = Path("/proc/self/statm")
#: The radius shown of the warm-up window, in km: small, so that what it
#: leaves behind is the modules and not its arrays.
WARM_UP_RADIUS_KM = 1.0
#: What an app has imported before anyone analyses, numpy among them.
LOADED = ("groundwater.mapping.elevation", "groundwater.mapping.terrain_analysis")
METHOD = (f"a fresh interpreter: the window at the cap read, then analyse_terrain(precision='float32') "
          f"once, after a warm-up analysis of a {WARM_UP_RADIUS_KM:g} km window; increase_mb is "
          "ru_maxrss after the analysis minus the resident set size (/proc/self/statm) just before it; "
          "MB of 2**20 bytes")


def _bench():
    """bench/run.py, loaded from its file, for the synthetic tile, the
    window, the analysis call and the machine block, so that this measures
    what ``run.py`` times. Loading it imports neither numpy nor the package,
    and sets the BLAS threads before anything does."""
    spec = importlib.util.spec_from_file_location("bench_run", HERE / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module          # its dataclasses look themselves up here
    spec.loader.exec_module(module)
    return module


def _rss_mb() -> float:
    """The resident set size now, in MB."""
    return int(STATM.read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20


def _peak_mb() -> float:
    """The largest the resident set has been, in MB (Linux gives
    ``ru_maxrss`` in kilobytes)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def write_tile(path: Path) -> dict:
    """Write the synthetic DEFLATE tile to ``path``, and return the run's
    header, taken first so that its load average is the machine's before
    this script's work."""
    bench = _bench()
    header = bench.run_header({"precision": "float32", "warm_up_radius_km": WARM_UP_RADIUS_KM})
    bench._write_terrain_tile(path, "deflate", 1024)
    return header


def measure(path: Path) -> dict:
    """Read and analyse the window at the cap from the tile at ``path``, in
    this interpreter, which should have done nothing else."""
    bench = _bench()
    for name in LOADED:
        importlib.import_module(name)
    start = _rss_mb()

    cfg, small = bench._terrain_window(path, WARM_UP_RADIUS_KM)
    bench._analyse_window(cfg, small)
    del small
    gc.collect()
    warm = _rss_mb()

    radius = bench._terrain_cap_radius(path)
    cfg, read = bench._terrain_window(path, radius)
    gc.collect()
    before = _rss_mb()
    peak_before = _peak_mb()
    began = time.perf_counter()
    bench._analyse_window(cfg, read)         # ru_maxrss keeps its high point, the finished result held
    seconds = time.perf_counter() - began
    peak_after = _peak_mb()
    r0, r1, c0, c1 = read.shown
    return {
        "window": {"radius_km": radius, "margin_km": cfg.analysis_buffer_km,
                   "cells": int(read.grid.z.size), "cells_shown": (r1 - r0) * (c1 - c0),
                   "cap": cfg.max_cells, "precision": "float32"},
        "increase_mb": round(peak_after - before, 1),
        "read_mb": round(before - warm, 1),
        "first_use_mb": round(warm - start, 1),
        "rss_before_mb": round(before, 1),
        "peak_before_mb": round(peak_before, 1),
        "peak_after_mb": round(peak_after, 1),
        "peak_set_by_analysis": peak_after > peak_before,
        "seconds": round(seconds, 3),
    }


def _fresh(env: dict, step: str, path: Path) -> dict:
    """This script's ``step`` on ``path`` in a fresh interpreter, and the
    JSON it prints; its progress and any failure go to stderr as they come."""
    done = subprocess.run([sys.executable, str(Path(__file__).resolve()), step, str(path)],
                          env=env, check=True, stdout=subprocess.PIPE, text=True)
    return json.loads(done.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="also write the result as JSON here")
    # the two fresh interpreters' parts; the first is also how bench/web.mjs
    # writes the tile it times the browser app on
    parser.add_argument("--write-tile", type=Path, metavar="PATH",
                        help="only write the synthetic tile to PATH, and print the run's header")
    parser.add_argument("--measure", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.write_tile is not None:
        print(json.dumps(write_tile(args.write_tile)))
        return 0
    if not STATM.exists():
        raise SystemExit(f"{TOOL} reads the resident set size from {STATM}, so it runs on Linux only")
    if args.measure is not None:
        print(json.dumps(measure(args.measure)))
        return 0

    bench = _bench()
    env = bench._subprocess_env()
    with tempfile.TemporaryDirectory(prefix="gwt-bench-") as scratch:
        path = Path(scratch) / bench.TERRAIN_TILE
        print("writing the synthetic tile ...", file=sys.stderr)
        header = _fresh(env, "--write-tile", path)
        print("reading and analysing the window at the cap in a fresh interpreter ...", file=sys.stderr)
        measured = _fresh(env, "--measure", path)
    doc = {**header, "tool": TOOL, "date": date.today().isoformat(), "method": METHOD, **measured}
    text = json.dumps(doc, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"written to {args.out}", file=sys.stderr)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
