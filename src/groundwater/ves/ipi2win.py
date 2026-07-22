"""Import layered models from IPI2Win output tables.

IPI2Win reports models as a table with columns N, rho, h and z, where
z is the depth to the top of the layer, the first z prints as ``0/0``
and the half space row has no thickness. The overall fit is reported
as ``ERR = <percent>``. Interpretations already made in IPI2Win can be
transcribed into a small Excel/CSV table and reused directly.

Expected layout (one worksheet per sounding, or one CSV per sounding):

    Sounding Number: 1        (optional header row(s))
    ERR (%): 21.5             (optional)
    N | rho | h | z
    1 | 832.14 | 1    | 0/0
    2 | 2102.8 | 7.37 | 1
    3 | 36.71  |      | 8.37
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import numpy as np

from ..models import LayeredModel
from ..utils import clean_text, parse_number

# "ERR" / "Error" as a whole word, so it does not fire on unrelated words that
# merely contain the letters e-r-r (Terrain, Errol, ...).
_ERR_RE = re.compile(r"\berr(?:or)?\b", re.IGNORECASE)

__all__ = ["read_ipi2win_models", "model_from_rows"]


def _find_table(grid: list[list]) -> tuple[int, dict] | None:
    for r, row in enumerate(grid):
        texts = [clean_text(c).lower().rstrip(".") for c in row]
        cols: dict[str, int] = {}
        for c, t in enumerate(texts):
            base = t.replace("(m)", "").replace("(ohm-m)", "").strip()
            if base in ("n", "no", "layer"):
                cols["n"] = c
            elif base in ("rho", "p", "resistivity") or "rho" in base or "resist" in base:
                cols.setdefault("rho", c)
            elif base in ("h", "thickness") or base.startswith("h "):
                cols.setdefault("h", c)
            elif base in ("z", "depth") or base.startswith("z "):
                cols.setdefault("z", c)
        if "rho" in cols and ("h" in cols or "z" in cols):
            return r, cols
    return None


def _find_err(grid: list[list]) -> float | None:
    for row in grid:
        for cell in row:
            text = clean_text(cell)
            if not text or not _ERR_RE.search(text):
                continue
            # Prefer the value after a '=' or ':' delimiter ("ERR = 3.5%"); a
            # label cell that merely mentions error but has no number is
            # skipped rather than yielding a bogus fit error.
            tail = re.split(r"[=:]", text)[-1] if re.search(r"[=:]", text) else text
            value = parse_number(tail)
            if value is not None:
                return value
    return None


def model_from_rows(
    rows: list[dict], err: float | None = None, sounding_id: str = ""
) -> LayeredModel:
    """Build a LayeredModel from row dicts with rho / h / z entries."""
    rho = [r["rho"] for r in rows]
    h = [r.get("h") for r in rows]
    z = [r.get("z") for r in rows]
    thicknesses: list[float] = []
    for i in range(len(rho) - 1):
        if h[i] is not None:
            thicknesses.append(float(h[i]))
        elif z[i + 1] is not None and z[i] is not None:
            thicknesses.append(float(z[i + 1]) - float(z[i]))
        elif z[i + 1] is not None and i == 0:
            thicknesses.append(float(z[i + 1]))
        else:
            raise ValueError("Cannot determine layer thicknesses from the table")
    return LayeredModel(
        np.asarray(rho, float),
        np.asarray(thicknesses, float),
        fit_error_percent=err,
        method="ipi2win-import",
        sounding_id=sounding_id,
    )


def _model_from_grid(grid: list[list], sounding_id: str) -> LayeredModel | None:
    located = _find_table(grid)
    if located is None:
        return None
    header_row, cols = located
    rows = []
    for row in grid[header_row + 1 :]:
        def cell(key):
            c = cols.get(key)
            return row[c] if c is not None and c < len(row) else None

        rho = parse_number(cell("rho"))
        if rho is None:
            if rows:
                break
            continue
        z_raw = clean_text(cell("z"))
        z = 0.0 if z_raw.startswith("0/0") else parse_number(cell("z"))
        rows.append({"rho": rho, "h": parse_number(cell("h")), "z": z})
    if not rows:
        return None
    err = _find_err(grid)
    return model_from_rows(rows, err=err, sounding_id=sounding_id)


def read_ipi2win_models(path: str | Path) -> dict[str, LayeredModel]:
    """Read IPI2Win model tables from an Excel workbook or CSV file.

    Returns a mapping of sounding id (worksheet title or a "Sounding
    Number" header value, else the file stem) to the layered model.
    """
    from ..ingestion import common

    path = Path(path)
    models: dict[str, LayeredModel] = {}
    if path.suffix.lower() == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as fh:
            grid = [[c if c != "" else None for c in row] for row in csv.reader(fh)]
        fields = common.extract_header_fields(grid)
        sounding_id = str(fields.get("sounding_id", "") or path.stem)
        model = _model_from_grid(grid, sounding_id)
        if model is not None:
            models[sounding_id] = model
        return models

    for name in common.sheet_names(path):
        grid, title = common.load_grid(path, sheet=name)
        fields = common.extract_header_fields(grid)
        sounding_id = str(fields.get("sounding_id", "") or title)
        model = _model_from_grid(grid, sounding_id)
        if model is not None:
            models[sounding_id] = model
    return models
