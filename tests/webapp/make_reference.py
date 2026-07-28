"""Produce the reference values the browser app is checked against.

Runs the Python toolkit over the bundled sample workbooks and writes
``tests/webapp/reference.json``. ``tests/webapp/parity.mjs`` then runs the
same inputs through the JavaScript engine in headless Chromium and
compares the two, so the standalone web app cannot silently drift away
from the package it was ported from.

    python tests/webapp/make_reference.py            # regenerate the file
    python tests/webapp/make_reference.py --check    # verify it, don't rewrite
    node tests/webapp/parity.mjs

The committed file is checked in so ``parity.mjs`` runs without a Python
environment, and ``--check`` is what CI uses to keep it honest.

``--check`` compares within a tolerance rather than byte for byte. The
inversion and the Theis fit go through LAPACK, which is not bit
reproducible across BLAS builds: the same input gives 1.4021310045105808
on one machine and 1.4021310045105801 on another. Those last digits carry
no information about the toolkit, so requiring them to match would make CI
fail on a runner upgrade while a genuine change of a millimetre in a
screen depth slipped through. The tolerance is tight enough that any real
change in behaviour still fails.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from groundwater.design import design_borehole
from groundwater.hydraulics import analyse_pumping_test
from groundwater.ingestion import (
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from groundwater.quality import assess_sample
from groundwater.ves.inversion import invert_sounding

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "examples" / "data"
OUT = Path(__file__).resolve().parent / "reference.json"


def clean(value):
    """JSON-safe: NaN becomes null, numpy scalars become plain floats."""
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) else f
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.ndarray):
        return [clean(v) for v in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def site_dict(site):
    return {
        "client": site.client, "project": site.project,
        "community": site.community, "chiefdom": site.chiefdom,
        "district": site.district, "project_ref": site.project_ref,
        "easting": clean(site.easting), "northing": clean(site.northing),
        "elevation_m": clean(site.elevation_m), "supervisor": site.supervisor,
        "contractor": site.contractor,
    }


def flags(items):
    return [[f.level, f.code, f.message] for f in items]


def build() -> dict:
    out: dict = {}

    soundings = read_ves_workbook(DATA / "rokel" / "rokel_ves.xlsx")
    out["ves"] = [
        {
            "id": s.sounding_id, "array": s.array_type,
            "ab2": clean(s.ab2), "mn": clean(s.mn), "rho": clean(s.rho_app),
            "site": site_dict(s.site), "flags": flags(s.flags),
        }
        for s in soundings
    ]

    log = read_drilling_workbook(DATA / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    out["drilling"] = {
        "ref": log.borehole_ref, "total": clean(log.total_depth_m),
        "strikes": clean(log.water_strikes_m),
        "intervals": [[clean(i.top_m), clean(i.bottom_m), i.description]
                      for i in log.intervals],
        "site": site_dict(log.site), "flags": flags(log.flags),
    }

    sample = read_quality_workbook(DATA / "dr_timbo" / "dr_timbo_water_quality.xlsx")
    out["quality"] = {
        "id": sample.sample_id, "ref": sample.borehole_ref,
        "lab": sample.laboratory,
        "results": [[r.parameter, clean(r.value), r.unit, r.below_detection,
                     clean(r.detection_limit)] for r in sample.results],
        "flags": flags(sample.flags),
    }

    test = read_pumping_workbook(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    out["pumping"] = {
        "type": test.test_type, "swl": clean(test.static_water_level_m),
        "depth": clean(test.borehole_depth_m), "pump": clean(test.pump_setting_m),
        "steps": [{"n": s.step_number, "q": clean(s.discharge_m3_per_h),
                   "t": clean(s.time_min), "wl": clean(s.water_level_m),
                   "label": s.label} for s in test.steps],
        "rec_t": clean(test.recovery_time_min),
        "rec_wl": clean(test.recovery_level_m),
        "duration": clean(test.pumping_duration_min),
        "flags": flags(test.flags),
    }

    step_test = read_pumping_workbook(DATA / "kuntolo" / "kuntolo_step_test.xlsx")
    out["step"] = {
        "type": step_test.test_type, "swl": clean(step_test.static_water_level_m),
        "nsteps": len(step_test.steps),
        "steps": [{"n": s.step_number, "q": clean(s.discharge_m3_per_h),
                   "npoints": len(s.time_min), "tmax": clean(float(s.time_min.max()))}
                  for s in step_test.steps],
        "flags": flags(step_test.flags),
    }

    analysis = analyse_pumping_test(test)
    rec = analysis.yield_recommendation
    out["analysis"] = {
        "T": clean(analysis.transmissivity_m2_per_day),
        "cj": clean(analysis.cooper_jacob.transmissivity_m2_per_day)
              if analysis.cooper_jacob else None,
        "rec": clean(analysis.recovery.transmissivity_m2_per_day)
               if analysis.recovery else None,
        "theis": clean(analysis.theis.transmissivity_m2_per_day)
                 if analysis.theis else None,
        "safe": clean(rec.safe_yield_m3_per_h),
        "low": clean(rec.safe_yield_low_m3_per_h),
        "high": clean(rec.safe_yield_high_m3_per_h),
        "pump_depth": clean(rec.pump_installation_depth_m),
        "range_text": rec.yield_range_text,
        "flags": [[f.level, f.code] for f in analysis.flags],
    }

    assessed = assess_sample(sample)
    out["assessed"] = {
        "verdict": assessed.verdict,
        "health": [r.parameter for r in assessed.health_exceedances],
        "wqi": clean(assessed.wqi.value) if assessed.wqi else None,
        "corros": assessed.corrosivity.classification,
        "ionic": clean(assessed.ionic.error_percent) if assessed.ionic else None,
    }

    design = design_borehole(log=log, static_water_level_m=test.static_water_level_m)
    out["design"] = {
        "depth": clean(design.total_depth_m),
        "screens": [[clean(s.top_m), clean(s.bottom_m)] for s in design.screens],
        "gravel": clean(list(design.gravel_pack)),
        "screen_len": clean(design.total_screen_length_m),
    }

    inverted = invert_sounding(soundings[0])
    out["inversion"] = {
        "rho": clean(inverted.model.resistivities),
        "h": clean(inverted.model.thicknesses),
        "err": clean(inverted.fit_error_percent),
    }
    return out


# Loose enough to absorb a different BLAS build, tight enough that a real
# change in any reported quantity fails: 1e-6 relative is a millionth of a
# metre on a screen depth and a millionth of a percent on a fit error.
CHECK_RTOL = 1e-6


def drifted(fresh, committed, path=""):
    """Yield ``(path, fresh, committed)`` for every value that really differs."""
    if isinstance(fresh, dict) and isinstance(committed, dict):
        for key in sorted(set(fresh) | set(committed)):
            if key not in fresh or key not in committed:
                yield (f"{path}.{key}", fresh.get(key, "<missing>"),
                       committed.get(key, "<missing>"))
                continue
            yield from drifted(fresh[key], committed[key], f"{path}.{key}")
    elif isinstance(fresh, list) and isinstance(committed, list):
        if len(fresh) != len(committed):
            yield (f"{path}[]", f"{len(fresh)} items", f"{len(committed)} items")
            return
        for i, (a, b) in enumerate(zip(fresh, committed)):
            yield from drifted(a, b, f"{path}[{i}]")
    elif isinstance(fresh, (int, float)) and isinstance(committed, (int, float)):
        if isinstance(fresh, bool) or isinstance(committed, bool):
            if fresh != committed:
                yield (path, fresh, committed)
        elif not math.isclose(fresh, committed, rel_tol=CHECK_RTOL, abs_tol=1e-12):
            yield (path, fresh, committed)
    elif fresh != committed:
        yield (path, fresh, committed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="compare the committed file against a fresh run instead of "
             "rewriting it; exit non-zero if anything really moved",
    )
    args = parser.parse_args()
    fresh = build()

    if not args.check:
        OUT.write_text(json.dumps(fresh, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {OUT}")
        return 0

    if not OUT.exists():
        print(f"{OUT} is missing; run this without --check to create it")
        return 1
    committed = json.loads(OUT.read_text(encoding="utf-8"))
    differences = list(drifted(fresh, committed))
    if not differences:
        print(f"{OUT} agrees with this toolkit to {CHECK_RTOL:g} relative")
        return 0
    print(f"{OUT} disagrees with this toolkit in {len(differences)} place(s):")
    for path, a, b in differences[:20]:
        print(f"  {path.lstrip('.')}: fresh {a!r} vs committed {b!r}")
    print("\nIf the change is intended, regenerate with:\n"
          "  python tests/webapp/make_reference.py")
    return 1


if __name__ == "__main__":
    sys.exit(main())
