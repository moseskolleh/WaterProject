"""Inversions saved in a project file, so a survey is not inverted twice.

An inversion is fully determined by the readings, the VES configuration
and the code that runs it, and it is the one slow step in reopening a
project. So each result is saved beside the project's data under a key:
the SHA-256 of a canonical encoding of everything the inversion reads (the
sounding's name, array type, AB/2, MN and apparent resistivities), the
whole :class:`~groundwater.config.VESConfig`, and the engine that ran it.

The saved results are a cache, never a source of truth. A loader may use
one and may always throw it away and invert again. Nothing is trusted
because it is there:

- the key is worked out afresh from the sounding in hand, so a changed
  reading, a changed setting or a different engine looks for a different
  key and finds nothing;
- an entry carries a digest of its own content under its key, so a damaged
  or hand-edited entry is ignored rather than read. That catches accident
  and casual editing, not a forger: there is no secret to sign with in a
  file anybody can open, and whoever can rewrite an entry can as easily
  rewrite the readings it was made from;
- only what the search alone can say is stored: the chosen model, its
  iteration count, whether it converged and the layer counts it tried. The
  fitted readings, the model's response, the misfit and the uncertainty
  factors are worked out again from the sounding on the way in
  (:func:`~groundwater.ves.inversion.restore_inversion`), and the misfit
  has to be the one the search recorded for that layer count.

The engine is named by the package version, the numpy and scipy versions
(the forward model's Bessel functions and the solver's rounding come from
them) and a digest of the source of the modules that compute an inversion.
The digest is there because the version moves only at a release, and a fix
to the inversion between two releases must not be answered with a result
the old code computed.

The browser keeps a cache of its own, keyed the same way but under its own
engine name. The two engines agree to a tolerance, not to the bit, so a
result the Python engine computed is not what the browser would compute,
and each only ever finds its own entries.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from functools import lru_cache
from importlib import resources

from ..config import VESConfig
from ..models import VESSounding
from .inversion import InversionResult, restore_inversion

__all__ = [
    "CACHE_FORMAT",
    "ENGINE",
    "cache_entry",
    "cached_inversion",
    "engine_version",
    "inversion_key",
]

#: The engine's name in the key; the browser's is "gwt-core".
ENGINE = "groundwater-python"

#: The layout of a key and an entry. A change to either is a new number, so
#: an entry in the old layout is simply never found.
CACHE_FORMAT = 1

#: The modules whose code decides what an inversion returns, relative to the
#: package. The configuration's values are in the key already.
_ENGINE_SOURCES = (
    "ves/inversion.py",
    "ves/forward.py",
    "ves/splice.py",
    "models.py",
)


@lru_cache(maxsize=1)
def engine_version() -> str | None:
    """What computed an inversion here, or None if it cannot be told.

    Without its source to read, a change to the inversion could not be
    told from its absence, so nothing is cached at all rather than risk
    handing back an old answer.
    """
    try:
        import numpy
        import scipy

        from .. import __version__

        root = resources.files("groundwater")
        code = hashlib.sha256()
        for name in _ENGINE_SOURCES:
            # line endings normalised, so a Windows checkout of the same
            # code is the same engine
            text = root.joinpath(name).read_bytes().replace(b"\r\n", b"\n")
            code.update(name.encode() + b"\0" + text + b"\0")
    except Exception:  # noqa: BLE001 - no engine version means no cache
        return None
    return (
        f"{ENGINE} {__version__} numpy {numpy.__version__} "
        f"scipy {scipy.__version__} code {code.hexdigest()[:16]}"
    )


def _canonical(value) -> str:
    # sorted keys and no spaces; a float is written by repr, the shortest
    # text that reads back to the same number, so equal inputs give equal
    # text. A blank MN is NaN, and is written as NaN.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=True)


def _floats(values) -> list[float]:
    return [float(v) for v in values]


def inversion_key(sounding: VESSounding, config: VESConfig | None = None) -> str | None:
    """The cache key of ``invert_sounding(sounding, config)``, or None.

    None when the engine cannot be named, which turns the cache off.
    """
    engine = engine_version()
    if engine is None:
        return None
    payload = {
        "cache": CACHE_FORMAT,
        "engine": engine,
        "sounding": {
            "id": str(sounding.sounding_id),
            "array_type": str(sounding.array_type),
            "ab2": _floats(sounding.ab2),
            "mn": _floats(sounding.mn),
            "rho_app": _floats(sounding.rho_app),
        },
        "config": asdict(config or VESConfig()),
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _digest(key: str, record: dict) -> str:
    text = key + "\n" + _canonical(record)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_entry(key: str, result: InversionResult) -> dict | None:
    """What to save for one inversion under ``key``, or None if it will not keep.

    Plain lists, numbers and strings, so it goes into YAML and comes back
    unchanged.
    """
    record = {
        "resistivities": _floats(result.model.resistivities),
        "thicknesses": _floats(result.model.thicknesses),
        "n_iterations": int(result.n_iterations),
        "converged": bool(result.converged),
        "trials": [[int(n), float(err)] for n, err in result.trials],
    }
    numbers = record["resistivities"] + record["thicknesses"] + [
        err for _, err in record["trials"]
    ]
    if not all(math.isfinite(x) for x in numbers):
        return None
    return {
        # for whoever opens the file; neither is read back
        "sounding": str(result.model.sounding_id),
        "engine": engine_version(),
        "result": record,
        "digest": _digest(key, record),
    }


def _is_number(value) -> bool:
    # a bool is an int to Python, and "12" is not a number however it reads
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _positive_list(value, length=None) -> bool:
    return (
        isinstance(value, list)
        and (length is None or len(value) == length)
        and all(_is_number(x) and math.isfinite(x) and x > 0 for x in value)
    )


def cached_inversion(
    entry, key: str | None, sounding: VESSounding, config: VESConfig | None = None
) -> InversionResult | None:
    """The saved inversion of ``sounding``, or None to invert it afresh.

    ``key`` is :func:`inversion_key` of this sounding and configuration.
    Anything short of a well-formed entry whose digest matches under this
    key, and whose model reproduces the misfit the search recorded for it,
    is None: the caller inverts again and the entry is replaced.
    """
    if key is None or not isinstance(entry, dict):
        return None
    config = config or VESConfig()
    record = entry.get("result")
    if not isinstance(record, dict) or not isinstance(entry.get("digest"), str):
        return None
    try:
        if entry["digest"] != _digest(key, record):
            return None
    except (TypeError, ValueError):  # a value JSON cannot hold
        return None
    rho, h = record.get("resistivities"), record.get("thicknesses")
    trials = record.get("trials")
    iterations, converged = record.get("n_iterations"), record.get("converged")
    if not (
        _positive_list(rho)
        and config.min_layers <= len(rho) <= config.max_layers
        and _positive_list(h, len(rho) - 1)
        and isinstance(iterations, int) and not isinstance(iterations, bool)
        and 0 <= iterations <= config.max_iterations
        and isinstance(converged, bool)
        and isinstance(trials, list) and trials
    ):
        return None
    for trial in trials:
        if not (
            isinstance(trial, list) and len(trial) == 2
            and isinstance(trial[0], int) and not isinstance(trial[0], bool)
            and config.min_layers <= trial[0] <= config.max_layers
            and _is_number(trial[1]) and math.isfinite(trial[1])
        ):
            return None
    try:
        result = restore_inversion(
            sounding, rho, h, iterations, converged,
            [(n, float(err)) for n, err in trials],
        )
    except Exception:  # noqa: BLE001 - an entry that will not rebuild is a miss
        return None
    # the model has to fit the readings as well as the search said it did
    recorded = [err for n, err in result.trials if n == result.model.n_layers]
    if not recorded or not math.isclose(
        recorded[0], result.fit_error_percent, rel_tol=1e-12, abs_tol=1e-12
    ):
        return None
    return result
