"""Recompute analysis objects from the data sources saved in a project.

The web app stores the raw uploaded data files (or a reference to a bundled
sample) in the project file, plus the few extra inputs an analysis needs
that are not in the file itself (pumping-test step discharges and the
borehole-design static water level). On load, this module rebuilds the
result objects so the reports can be regenerated without re-uploading.

Pure and Streamlit-free, so the round trip is unit-testable.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import Config
from .design import design_borehole
from .hydraulics import analyse_pumping_test
from .ingestion import (
    read_drilling_workbook,
    read_pumping_docx,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from .quality import assess_sample
from .ves import interpret_model, invert_sounding


def _materialize(source, sample_root, tmp_dir) -> Path | None:
    """Turn a saved source into a readable file path.

    Never raises: an I/O failure, a bad name or a sample reference outside
    the sample tree simply yields None, so a single bad source is skipped
    rather than crashing the load.
    """
    if not isinstance(source, dict):
        return None
    try:
        if source.get("bytes") is not None:
            # basename only, so a hand-edited project cannot write outside tmp_dir
            name = os.path.basename(str(source.get("name") or "data")) or "data"
            path = Path(tmp_dir) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes(source["bytes"]))
            return path
        if source.get("sample") and sample_root is not None:
            root = Path(sample_root).resolve()
            candidate = (root / str(source["sample"])).resolve()
            if candidate.is_relative_to(root) and candidate.exists():
                return candidate
    except OSError:
        return None
    return None


def recompute_results(
    sources: dict,
    discharges: dict | None = None,
    design_swl: float | None = None,
    config: Config | None = None,
    sample_root=None,
    tmp_dir=".",
) -> dict:
    """Rebuild the analysis objects a saved project needs.

    ``sources`` maps an upload key (``ves``/``wiz_ves``/``pump``/``wq``/``log``)
    to a source dict. Returns session updates keyed like the app's session
    state (``ves_results``, ``pump_analysis``, ``wq_assessment``,
    ``borehole_design``, ``drilling_log``); missing or unreadable sources are
    skipped rather than raised.
    """
    config = config or Config()
    discharges = discharges or {}
    out: dict = {}

    def _path(key):
        source = sources.get(key)
        return _materialize(source, sample_root, tmp_dir) if source else None

    # VES: the main tab wins over the guided-wizard upload
    ves_path = _path("ves") or _path("wiz_ves")
    if ves_path is not None:
        try:
            soundings = read_ves_workbook(ves_path)
            results = [invert_sounding(s, config.ves) for s in soundings]
            interps = [
                interpret_model(s, r.model, config.ves)
                for s, r in zip(soundings, results)
            ]
            out["ves_results"] = (soundings, results, interps)
        except Exception:  # noqa: BLE001 - a bad source just skips its result
            pass

    pump_path = _path("pump")
    if pump_path is not None:
        try:
            reader = (
                read_pumping_docx
                if pump_path.suffix.lower() == ".docx"
                else read_pumping_workbook
            )
            test = reader(pump_path)
            for step in test.steps:
                q = discharges.get(str(step.step_number))
                if q:
                    step.discharge_m3_per_h = float(q)
            out["pump_analysis"] = analyse_pumping_test(test, config.pumping)
        except Exception:  # noqa: BLE001
            pass

    wq_path = _path("wq")
    if wq_path is not None:
        try:
            out["wq_assessment"] = assess_sample(read_quality_workbook(wq_path))
        except Exception:  # noqa: BLE001
            pass

    log_path = _path("log")
    if log_path is not None:
        try:
            log = read_drilling_workbook(log_path)
            out["drilling_log"] = log
            out["borehole_design"] = design_borehole(
                log=log,
                static_water_level_m=design_swl or None,
                rules=config.design,
            )
        except Exception:  # noqa: BLE001
            pass

    return out
