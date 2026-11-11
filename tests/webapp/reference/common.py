"""What the sections of the reference share: where the files are, the
shapes values are written in, and the tolerances ``--check`` compares within.

``REPO`` and ``OUT`` are worked out from this file's own place, one folder
below ``tests/webapp``, so ``OUT`` is still ``tests/webapp/reference.json``
and the fixtures the sections read are still ``OUT.parent / "fixtures"``.
``drifted`` is also the walk ``tests/fuzz/engines.py`` compares the two
engines with, and ``range_tolerated`` and ``pc_tolerated`` are held by
``tests/test_ves_range.py`` and ``tests/test_pumping_spread.py``; all three
reach them through ``make_reference.py``, which names them again.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np


# This file is tests/webapp/reference/common.py, so the repository is three
# folders up and reference.json one, beside make_reference.py.
REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "examples" / "data"
OUT = Path(__file__).resolve().parents[1] / "reference.json"


def clean(value):
    """JSON-safe: NaN becomes null, numpy scalars become plain floats."""
    # bool before the numeric branches: bool is a subclass of int, and a
    # stabilised flag written out as 0 compares unequal to the browser's false.
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) else f
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.ndarray):
        return [clean(v) for v in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    # Dicts have to recurse too. Without this a mapping passed through here
    # came back untouched, so a tuple inside one stayed a tuple - identical
    # in the written JSON, but --check compares the fresh value against the
    # parsed file, and ("a", "b") != ["a", "b"]. That reads as 107 places
    # where the browser disagrees with the toolkit when nothing disagrees
    # at all, and a numpy scalar in the same position would survive too.
    if isinstance(value, dict):
        return {key: clean(v) for key, v in value.items()}
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


def _ns(value):
    """A dict as the attributes Python's decision numbers read, all the way
    down; lists element by element."""
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_ns(v) for v in value]
    return value


# --check holds the range to the tolerances parity.mjs holds the browser to,
# not to CHECK_RTOL. Its chains start from Levenberg-Marquardt fits, which a
# different BLAS build, or OpenBLAS with more threads, rounds differently;
# on a flat equivalence valley that moves a polished start by a few parts in
# a million, and every sample of the chain started there moves with it. One
# thread against four on this machine moved the short runs by 2e-6. Only the
# sampler's runs are loosened: the generator's words, its steps, the Latin
# hypercube and the hand-built sentence cases involve no fit, so they are
# held to CHECK_RTOL like every other entry.
RANGE_RTOL = {".ves_range.default": 2e-2, ".ves_range.short": 1e-4,
              ".ves_range.synthetic": 1e-4,
              # the depth the costing reads off those short runs
              ".cost_range.spreads": 1e-4}


def range_tolerated(path: str, fresh, committed) -> bool:
    """Whether a difference --check found is inside the range's tolerance."""
    for prefix, rtol in RANGE_RTOL.items():
        if path.startswith(prefix + ".") or path.startswith(prefix + "["):
            return (isinstance(fresh, (int, float)) and isinstance(committed, (int, float))
                    and not isinstance(fresh, bool)
                    and math.isclose(fresh, committed, rel_tol=rtol, abs_tol=1e-12))
    return False


# The Papadopulos-Cooper fit's own numbers on a sheet it fits badly sit on a
# valley floor flat to within the Stehfest inversion's rounding, so another
# BLAS build or scipy stops the optimiser a few parts in a hundred thousand
# away (3e-5 relative, Python on the CI runner against this machine). --check
# holds them to the 1e-3 relative parity.mjs holds the browser to; where the
# fit is adopted it is held to CHECK_RTOL, as is everything resting on it.
PC_RTOL = 1e-3
_PC_PATH = re.compile(r"^\.pumping_spread\.cases\.([^.]+)\.pc\[\d+\]$")


def pc_tolerated(path: str, fresh, committed, reference: dict) -> bool:
    """Whether a difference --check found is a badly fitting large-diameter
    fit's own number, inside parity's tolerance for it."""
    match = _PC_PATH.match(path)
    if not match:
        return False
    case = reference.get("pumping_spread", {}).get("cases", {}).get(match.group(1)) or {}
    if case.get("source") == "papadopulos_cooper":
        return False
    return (isinstance(fresh, (int, float)) and isinstance(committed, (int, float))
            and not isinstance(fresh, bool)
            and math.isclose(fresh, committed, rel_tol=PC_RTOL, abs_tol=1e-12))


# Loose enough to absorb a different BLAS build, tight enough that a real
# change in any reported quantity fails: 1e-6 relative is a millionth of a
# metre on a screen depth and a millionth of a percent on a fit error.
CHECK_RTOL = 1e-6


def drifted(fresh, committed, path="", rtol=CHECK_RTOL, atol=1e-12):
    """Yield ``(path, fresh, committed)`` for every value that really differs.

    The defaults are for --check, the toolkit against its own committed
    values. tests/fuzz compares the two engines with the same walk at the
    tolerances parity.mjs holds each kind of quantity to.
    """
    if isinstance(fresh, dict) and isinstance(committed, dict):
        for key in sorted(set(fresh) | set(committed)):
            if key not in fresh or key not in committed:
                yield (f"{path}.{key}", fresh.get(key, "<missing>"),
                       committed.get(key, "<missing>"))
                continue
            yield from drifted(fresh[key], committed[key], f"{path}.{key}", rtol, atol)
    elif isinstance(fresh, list) and isinstance(committed, list):
        if len(fresh) != len(committed):
            yield (f"{path}[]", f"{len(fresh)} items", f"{len(committed)} items")
            return
        for i, (a, b) in enumerate(zip(fresh, committed, strict=True)):
            yield from drifted(a, b, f"{path}[{i}]", rtol, atol)
    elif isinstance(fresh, (int, float)) and isinstance(committed, (int, float)):
        if isinstance(fresh, bool) or isinstance(committed, bool):
            if fresh != committed:
                yield (path, fresh, committed)
        elif not math.isclose(fresh, committed, rel_tol=rtol, abs_tol=atol):
            yield (path, fresh, committed)
    elif fresh != committed:
        yield (path, fresh, committed)
