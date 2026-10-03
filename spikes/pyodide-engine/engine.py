"""The VES page's computation, as the Pyodide worker runs it.

This file is the whole interface between the browser and the package in
the spike (PLAN.md step 1.10). The page reads the workbook in JavaScript,
as the app does today, and sends each sounding as the browser engine holds
it (``sounding_id``, ``array_type``, ``ab2``, ``mn``, ``rho_app``, ``site``,
``flags``). This builds the package's own ``VESSounding`` from that, runs
``invert_sounding`` and ``interpret_model`` on it, and answers in JSON with
the fields tests/webapp/parity.mjs compares.

The same file runs under CPython, so the native numbers the driver quotes
come from the same code path the worker takes:

    PYTHONPATH=src python spikes/pyodide-engine/engine.py SOUNDINGS.json
"""

from __future__ import annotations

import dataclasses
import json
import math
import sys
import time
from pathlib import Path

from groundwater.config import VESConfig
from groundwater.models import DataFlag, SiteMetadata, VESSounding
from groundwater.ves.interpret import interpret_model
from groundwater.ves.inversion import invert_sounding

_SITE_FIELDS = {f.name for f in dataclasses.fields(SiteMetadata)}
_VES_FIELDS = {f.name: f for f in dataclasses.fields(VESConfig)}


def _number(value) -> float:
    # JSON has no NaN: a blank MN reaches here as null
    return math.nan if value is None else float(value)


def _flag(flag) -> DataFlag:
    if isinstance(flag, dict):
        return DataFlag(flag.get("level", ""), flag.get("code", ""),
                        flag.get("message", ""), flag.get("context", ""))
    return DataFlag(*flag)


def sounding_from(js: dict) -> VESSounding:
    """The package's sounding, from the browser engine's object."""
    site = {k: v for k, v in (js.get("site") or {}).items() if k in _SITE_FIELDS}
    return VESSounding(
        site=SiteMetadata(**site),
        sounding_id=js.get("sounding_id", ""),
        ab2=[_number(v) for v in js["ab2"]],
        mn=[_number(v) for v in js.get("mn") or [None] * len(js["ab2"])],
        rho_app=[_number(v) for v in js["rho_app"]],
        array_type=js.get("array_type") or "schlumberger",
        flags=[_flag(f) for f in js.get("flags") or []],
        source=js.get("source", ""),
    )


def ves_config(config: dict | None) -> VESConfig:
    """VESConfig from the browser's configuration object, or the default."""
    if not config or "ves" not in config:
        return VESConfig()
    values = {}
    for key, value in config["ves"].items():
        if key in _VES_FIELDS:
            values[key] = tuple(value) if isinstance(value, list) else value
    return VESConfig(**values)


def _floats(values) -> list:
    return [None if v is None else float(v) for v in values]


def run(js_sounding: dict, config: dict | None = None) -> dict:
    """Invert one sounding and interpret its model, timing each."""
    sounding = sounding_from(js_sounding)
    cfg = ves_config(config)
    t0 = time.perf_counter()
    result = invert_sounding(sounding, cfg)
    t1 = time.perf_counter()
    interp = interpret_model(sounding, result.model, cfg)
    t2 = time.perf_counter()
    model = result.model
    return {
        "id": sounding.sounding_id,
        "model": {
            "rho": _floats(model.resistivities),
            "h": _floats(model.thicknesses),
            "err": float(result.fit_error_percent),
            "iterations": int(result.n_iterations),
            "converged": bool(result.converged),
            "trials": [[int(n), float(e)] for n, e in result.trials],
        },
        "interpretation": {
            "water_zones": [[float(t), float(b)] for t, b in interp.water_zones],
            "max_drilling_depth_m": float(interp.max_drilling_depth_m),
            "investigation_depth_m": float(interp.investigation_depth_m),
            "max_spacing_m": (None if interp.max_spacing_m is None
                              else float(interp.max_spacing_m)),
            "basement_not_resolved": bool(interp.basement_not_resolved),
            "confidence": float(interp.confidence),
            "fit_quality": interp.fit_quality,
            "flags": [[f.level, f.code, f.message] for f in interp.flags],
            "narrative": interp.narrative,
        },
        "ms": {"invert": (t1 - t0) * 1000.0, "interpret": (t2 - t1) * 1000.0},
    }


def run_json(request: str) -> str:
    """The worker's entry point: one request in JSON, one answer in JSON."""
    payload = json.loads(request)
    return json.dumps(run(payload["sounding"], payload.get("config")))


def main(argv: list[str]) -> int:
    # Native timing for the record: each sounding twice, so the first call
    # (imports settled, caches cold) and a warm one are both on file.
    soundings = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    config = json.loads(Path(argv[2]).read_text(encoding="utf-8")) if len(argv) > 2 else None
    out = []
    for passno in (1, 2):
        for s in soundings:
            answer = run(s, config)
            answer["pass"] = passno
            out.append(answer)
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
