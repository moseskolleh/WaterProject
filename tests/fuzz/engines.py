"""Both engines over the same workbook, and what differs between them.

``python_summary`` reads a workbook with the Python package's own readers and
analyses; ``BrowserEngine`` hands the same bytes to ``gwt-core.js`` through
``engine.mjs``, a Node process kept open for the whole run; ``divergences``
compares the two with the comparison ``make_reference.py`` uses for the
committed reference values, at the tolerances ``parity.mjs`` holds each kind
of quantity to.

The summaries here and in ``page.js`` carry the same keys in the same order.
"""

from __future__ import annotations

import base64
import json
import math
import select
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "webapp"))

from make_reference import drifted  # noqa: E402

# What parity.mjs holds each kind of quantity to: what a sheet says to a
# millionth, a fitted result to 1e-4, an inverted model to 1e-3. Read values
# and flags come before any fit, so they are held at the tightest.
PARSE_TOL = 1e-6
ANALYSIS_TOL = 1e-4
INVERSION_TOL = 1e-3

# Long enough for the browser to start and for the slowest inversion.
ANSWER_TIMEOUT_S = 120


def num(value):
    """A number as the browser's JSON carries it: NaN and infinity are null."""
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    f = float(value)
    return None if not math.isfinite(f) else f


def nums(values):
    return None if values is None else [num(v) for v in np.asarray(values).tolist()]


def flag_rows(flags):
    return [[f.level, f.code, f.message, f.context or ""] for f in flags]


def site(s):
    return {
        "client": s.client or "", "project": s.project or "",
        "community": s.community or "", "chiefdom": s.chiefdom or "",
        "district": s.district or "", "project_ref": s.project_ref or "",
        "easting": num(s.easting), "northing": num(s.northing),
        "utm_zone": num(s.utm_zone), "elevation_m": num(s.elevation_m),
        "date": s.date or "", "supervisor": s.supervisor or "",
        "contractor": s.contractor or "",
    }


def failure(exc: BaseException) -> dict:
    return {"error": str(exc)}


# --------------------------------------------------------------- Python side

def _ves(path: Path, name: str, options: dict) -> dict:
    from groundwater.ingestion.ves import read_ves_workbook
    from groundwater.ves.inversion import invert_sounding

    skipped: list = []
    soundings = read_ves_workbook(path, skipped=skipped)
    out = {
        "skipped": flag_rows(skipped),
        "soundings": [{
            "id": s.sounding_id, "array": s.array_type, "instrument": s.instrument or "",
            "ab2": nums(s.ab2), "mn": nums(s.mn), "rho": nums(s.rho_app),
            "site": site(s.site), "flags": flag_rows(s.flags),
        } for s in soundings],
    }
    if options.get("invert"):
        inversions = []
        for s in soundings:
            try:
                r = invert_sounding(s)
                inversions.append({"rho": nums(r.model.resistivities),
                                   "h": nums(r.model.thicknesses),
                                   "err": num(r.fit_error_percent)})
            except Exception as exc:  # noqa: BLE001 - a crash is a divergence too
                inversions.append(failure(exc))
        out["inversions"] = inversions
    return out


def _pumping(path: Path, name: str, options: dict) -> dict:
    from groundwater.hydraulics import analyse_pumping_test
    from groundwater.ingestion.pumping import read_pumping_workbook
    from groundwater.models import step_offsets_min

    try:
        test = read_pumping_workbook(path)
    except Exception as exc:  # noqa: BLE001
        return failure(exc)
    out = {
        "type": test.test_type, "swl": num(test.static_water_level_m),
        "depth": num(test.borehole_depth_m), "pump": num(test.pump_setting_m),
        "step_length": num(test.step_length_min), "ref": test.borehole_ref or "",
        "steps": [{"n": s.step_number, "q": num(s.discharge_m3_per_h),
                   "t": nums(s.time_min), "wl": nums(s.water_level_m),
                   "label": s.label} for s in test.steps],
        "rec_t": nums(test.recovery_time_min), "rec_wl": nums(test.recovery_level_m),
        "duration": num(test.pumping_duration_min),
        "offsets": [num(v) for v in step_offsets_min(test.steps)],
        "site": site(test.site), "flags": flag_rows(test.flags),
    }
    try:
        a = analyse_pumping_test(test)
        rec = a.yield_recommendation
        out["analysis"] = {
            "source": a.transmissivity_source,
            "qualifies": a.adopted_fit()[2],
            "disqualified": sorted(a.disqualified),
            "invalid": sorted(a.invalid_fits),
            "T": num(a.transmissivity_m2_per_day),
            "cj": num(a.cooper_jacob.transmissivity_m2_per_day) if a.cooper_jacob else None,
            "theis": num(a.theis.transmissivity_m2_per_day) if a.theis else None,
            "rec": num(a.recovery.transmissivity_m2_per_day) if a.recovery else None,
            "safe": num(rec.safe_yield_m3_per_h),
            "range_text": rec.yield_range_text,
            "pump_depth": num(rec.pump_installation_depth_m),
            "confidence": rec.confidence,
            "confidence_reasons": list(rec.confidence_reasons),
            "pending_reason": rec.pending_reason,
            "pump_depth_basis": rec.pump_depth_basis,
            "envelope_basis": rec.envelope_basis,
            "rec_pumping_time": num(a.recovery.pumping_time_min) if a.recovery else None,
            "step_numbers": [s["step"] for s in a.step_test.steps] if a.step_test else None,
            "B": num(a.step_test.aquifer_loss_B) if a.step_test else None,
            "C": num(a.step_test.well_loss_C) if a.step_test else None,
            "flags": flag_rows(a.flags),
        }
    except Exception as exc:  # noqa: BLE001
        out["analysis"] = failure(exc)
    return out


def _quality(path: Path, name: str, options: dict) -> dict:
    from groundwater.ingestion.waterquality import read_quality_workbook
    from groundwater.quality import assess_sample

    try:
        sample = read_quality_workbook(path)
    except Exception as exc:  # noqa: BLE001
        return failure(exc)
    out = {
        "id": sample.sample_id or "", "ref": sample.borehole_ref or "",
        "lab": sample.laboratory or "", "date": sample.sample_date or "",
        "results": [[r.parameter, num(r.value), r.unit or "", num(r.detection_limit),
                     bool(r.below_detection), num(r.greater_than),
                     bool(r.greater_than_inclusive), r.unreadable or ""]
                    for r in sample.results],
        "site": site(sample.site), "flags": flag_rows(sample.flags),
    }
    try:
        a = assess_sample(sample)
        out["assessment"] = {
            "verdict": a.verdict,
            "health": [r.parameter for r in a.health_exceedances],
            "national": [r.parameter for r in a.national_exceedances],
            "missing": list(a.missing_essential),
            "rows": [[r.parameter, r.status, num(r.value_in_guideline_unit),
                      r.guideline_unit or "", bool(r.evaluable), r.reason or ""]
                     for r in a.rows],
            "wqi": num(a.wqi.value) if a.wqi else None,
            "corros": a.corrosivity.classification if a.corrosivity else None,
            "ionic": num(a.ionic.error_percent) if a.ionic else None,
            "flags": flag_rows(a.flags),
        }
    except Exception as exc:  # noqa: BLE001
        out["assessment"] = failure(exc)
    return out


def _drilling(path: Path, name: str, options: dict) -> dict:
    from groundwater.design import design_borehole
    from groundwater.ingestion.drilling import read_drilling_workbook

    try:
        log = read_drilling_workbook(path)
    except Exception as exc:  # noqa: BLE001
        return failure(exc)
    out = {
        "ref": log.borehole_ref or "", "total": num(log.total_depth_m),
        "method": log.drilling_method or "", "status": log.status or "",
        "strikes": nums(log.water_strikes_m), "grout": num(log.grouting_depth_m),
        "installed": [[num(a), num(b)] for a, b in log.installed_screens_m],
        "intervals": [[num(iv.top_m), num(iv.bottom_m), iv.description,
                       num(iv.penetration_rate_m_per_min), num(iv.bit_diameter_in),
                       iv.from_time or "", iv.to_time or ""]
                      for iv in log.intervals],
        "site": site(log.site), "flags": flag_rows(log.flags),
    }
    try:
        d = design_borehole(log=log, static_water_level_m=options.get("swl"),
                            pump_intake_m=options.get("pump"))
        out["design"] = {
            "rows": [[r[0], r[1]] for r in d.summary_rows()],
            "screens": [[num(s.top_m), num(s.bottom_m)] for s in d.screens],
            "basis": list(d.design_basis),
            "pump": num(d.pump_intake_m),
            "flags": flag_rows(d.flags),
        }
    except Exception as exc:  # noqa: BLE001
        out["design"] = failure(exc)
    return out


_KINDS = {"ves": _ves, "pumping": _pumping, "quality": _quality, "drilling": _drilling}


def python_summary(kind: str, path: Path, name: str, options: dict) -> dict:
    """What the Python package makes of the workbook at ``path``.

    ``name`` is the source the browser is told; the Python readers are given
    the path itself, which is what they print, so the two are the same string.
    """
    try:
        out = _KINDS[kind](path, name, options)
    except Exception as exc:  # noqa: BLE001
        out = failure(exc)
    # through JSON, as the browser's answer comes: tuples become lists and
    # the two sides are compared in the same shapes
    return json.loads(json.dumps(out))


# -------------------------------------------------------------- browser side

class BrowserEngine:
    """``engine.mjs`` held open: one request and one answer per line."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            ["node", str(REPO / "tests" / "fuzz" / "engine.mjs")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=REPO,
            bufsize=1,
        )
        ready = self._read()
        if not ready.get("ready"):
            raise RuntimeError(f"engine.mjs did not start: {ready}")
        self._next = 0

    def _read(self) -> dict:
        # Requests and answers alternate, so no answer is ever left waiting in
        # the pipe's buffer and select sees the next one arrive. A case the
        # browser never answers - a loop that does not end - fails the case
        # rather than holding the run until CI kills it.
        ready, _, _ = select.select([self.proc.stdout], [], [], ANSWER_TIMEOUT_S)
        if not ready:
            self.proc.kill()
            raise RuntimeError(f"engine.mjs gave no answer in {ANSWER_TIMEOUT_S} s")
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"engine.mjs exited with status {self.proc.wait()}")
        return json.loads(line)

    def summary(self, kind: str, data: bytes, name: str, options: dict) -> dict:
        self._next += 1
        request = {"id": self._next, "kind": kind, "name": name,
                   "b64": base64.b64encode(data).decode("ascii"), "options": options}
        self.proc.stdin.write(json.dumps(request) + "\n")
        self.proc.stdin.flush()
        answer = self._read()
        if answer.get("id") != self._next:
            raise RuntimeError(f"engine.mjs answered {answer.get('id')}, not {self._next}")
        if answer.get("errors"):
            # an error on the page is a fault even when the summary agrees
            return {"page_errors": answer["errors"], **answer["out"]}
        return answer["out"]

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ---------------------------------------------------------------- comparison

# The fitted quantities in each summary, held to the looser tolerances; every
# other value is what the sheet said, held to PARSE_TOL.
_LOOSER = {"analysis": ANALYSIS_TOL, "assessment": ANALYSIS_TOL,
           "design": ANALYSIS_TOL, "inversions": INVERSION_TOL}


def divergences(js: dict, py: dict) -> list[tuple[str, object, object]]:
    """Every ``(path, browser, python)`` that differs beyond its tolerance."""
    out = []
    keys = sorted(set(js) | set(py))
    for key in keys:
        if key not in js or key not in py:
            out.append((key, js.get(key, "<missing>"), py.get(key, "<missing>")))
            continue
        tol = _LOOSER.get(key, PARSE_TOL)
        out.extend(drifted(js[key], py[key], key, rtol=tol, atol=tol))
    return out
