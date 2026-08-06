"""Recompute analysis objects from the data sources saved in a project.

The web app stores the raw uploaded data files (or a reference to a bundled
sample) in the project file, plus the few extra inputs an analysis needs
that are not in the file itself (pumping-test step discharges and the
borehole-design static water level). On load, this module rebuilds the
result objects so the reports can be regenerated without re-uploading.

A rebuild that fails is *reported*, not swallowed. It used to be: four bare
``except Exception: pass`` blocks turned a failed rebuild into an absent
dictionary key, and every consumer reads an absent key as "the user never
supplied that data". So a project whose water-quality workbook no longer
parsed came back looking like a borehole nobody had ever sampled - the
overview showed the stage as not started, the portfolio summary carried no
verdict, and the handover report was written without a water-quality
section. Nothing anywhere said a file had failed to load.

Failures are still contained - one bad source must not cost the other three
- but each one now produces a :class:`RecomputeIssue` naming what failed,
which file it was, and what to do about it.

Pure and Streamlit-free, so the round trip is unit-testable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
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
from .ves.interpret import rank_interpretations

_log = logging.getLogger(__name__)

#: The session key each upload key produces. An issue names it even when the
#: file could not be opened at all: the key really is absent, and a banner
#: that cannot say which result is missing can never be cleared when the
#: analyst supplies it by hand.
SOURCE_RESULTS = {
    "ves": "ves_results",
    "wiz_ves": "ves_results",
    "pump": "pump_analysis",
    "wq": "wq_assessment",
    "log": "drilling_log",
}

#: What each upload key is called in front of a user.
SOURCE_LABELS = {
    "ves": "Geophysics (VES)",
    "wiz_ves": "Geophysics (VES)",
    "pump": "Pumping test",
    "wq": "Water quality",
    "log": "Drilling log",
}

#: Why a source did not produce its result.
ISSUE_CODES = {
    "bad_payload": "the saved file content could not be read",
    "unreadable_file": "the saved file could not be written to disk",
    "missing_sample": "the bundled sample it refers to is no longer present",
    "outside_sample_root": "it refers to a file outside the sample directory",
    "parse_error": "the workbook could not be parsed",
    "analysis_error": "the data parsed but the analysis failed",
    "sounding_failed": "one sounding could not be inverted",
    "recompute_crashed": "the rebuild itself failed",
}


@dataclass(frozen=True)
class RecomputeIssue:
    """One saved source that did not produce its result."""

    source: str      # upload key: "ves" | "wiz_ves" | "pump" | "wq" | "log"
    result: str      # the session key now absent, "" for a partial failure
    label: str       # what the user calls it: "Water quality"
    level: str       # "error" (no result at all) | "warning" (partial result)
    code: str        # a key of ISSUE_CODES
    message: str     # one plain, actionable sentence
    context: str = ""   # the file name or sample path the user recognises
    detail: str = ""    # "ValueError: ...", truncated

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _issue(source, result, code, message, context="", exc=None, level="error"):
    detail = ""
    if exc is not None:
        detail = f"{type(exc).__name__}: {exc}"[:300]
    return RecomputeIssue(
        source=source,
        result=result,
        label=SOURCE_LABELS.get(source, source),
        level=level,
        code=code,
        message=message,
        context=context,
        detail=detail,
    )


def _source_name(source) -> str:
    if not isinstance(source, dict):
        return ""
    return str(source.get("name") or source.get("sample") or "")


def _materialize(source, sample_root, tmp_dir) -> tuple[Path | None, str]:
    """Turn a saved source into a readable file path.

    Never raises. Returns ``(path, "")`` on success or ``(None, code)`` with
    a code from :data:`ISSUE_CODES`, so the caller can say which of several
    quite different failures happened rather than reporting them all as an
    absent file.
    """
    if not isinstance(source, dict):
        return None, "bad_payload"
    if source.get("bytes") is not None:
        try:
            # basename only, so a hand-edited project cannot write outside tmp_dir
            name = os.path.basename(str(source.get("name") or "data")) or "data"
            path = Path(tmp_dir) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes(source["bytes"]))
            return path, ""
        except OSError:
            return None, "unreadable_file"
        except (TypeError, ValueError):
            # a str or out-of-range payload from a hand-edited project file;
            # this used to escape the function entirely and abort the whole load
            return None, "bad_payload"
    if source.get("sample") and sample_root is not None:
        try:
            root = Path(sample_root).resolve()
            candidate = (root / str(source["sample"])).resolve()
        except OSError:
            return None, "unreadable_file"
        if not candidate.is_relative_to(root):
            return None, "outside_sample_root"
        if not candidate.exists():
            return None, "missing_sample"
        return candidate, ""
    return None, "bad_payload"


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
    ``borehole_design``, ``drilling_log``), plus ``recompute_diagnostics``
    - always present - carrying ``{"ok": [...], "issues": [...]}``. A source
    that fails is skipped and recorded; it never aborts the others.
    """
    config = config or Config()
    discharges = discharges or {}
    out: dict = {}
    issues: list[RecomputeIssue] = []
    ok: list[str] = []

    def _path(key) -> Path | None:
        """Resolve one source, recording why if it cannot be resolved."""
        source = sources.get(key)
        if not source:
            return None
        path, code = _materialize(source, sample_root, tmp_dir)
        if path is None:
            issues.append(_issue(
                key, SOURCE_RESULTS.get(key, ""), code,
                f"{SOURCE_LABELS.get(key, key)}: the saved file could not be "
                f"opened because {ISSUE_CODES[code]}. Upload it again.",
                context=_source_name(source),
            ))
        return path

    # VES: the main tab wins over the guided-wizard upload
    ves_key = "ves" if sources.get("ves") else "wiz_ves"
    ves_path = _path("ves") or _path("wiz_ves")
    if ves_path is not None:
        try:
            soundings = read_ves_workbook(ves_path)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            _log.exception("VES workbook could not be parsed")
            soundings = None
            issues.append(_issue(
                ves_key, "ves_results", "parse_error",
                "The geophysics workbook could not be read, so the soundings "
                "were not restored. Open it and check the layout, or upload it "
                "again.",
                context=ves_path.name, exc=exc,
            ))
        if soundings:
            kept, results, interps = [], [], []
            # Per sounding, so one bad curve costs one curve rather than the
            # whole survey.
            for sounding in soundings:
                try:
                    result = invert_sounding(sounding, config.ves)
                    interps.append(interpret_model(sounding, result.model, config.ves))
                    results.append(result)
                    kept.append(sounding)
                except Exception as exc:  # noqa: BLE001
                    _log.exception("sounding %s could not be inverted", sounding.label)
                    issues.append(_issue(
                        ves_key, "", "sounding_failed",
                        f"Sounding {sounding.label} could not be inverted and "
                        "was left out; the other soundings were restored.",
                        context=sounding.label, exc=exc, level="warning",
                    ))
            if kept:
                # rank now: the dashboard reads interp.rank, and an unranked
                # set leaves every rank None so "best" silently becomes
                # "first parsed"
                rank_interpretations(interps)
                out["ves_results"] = (kept, results, interps)
                ok.append(ves_key)
            else:
                issues.append(_issue(
                    ves_key, "ves_results", "analysis_error",
                    "No sounding in the geophysics workbook could be inverted, "
                    "so there are no VES results to show.",
                    context=ves_path.name,
                ))

    pump_path = _path("pump")
    if pump_path is not None:
        try:
            reader = (
                read_pumping_docx
                if pump_path.suffix.lower() == ".docx"
                else read_pumping_workbook
            )
            test = reader(pump_path)
        except Exception as exc:  # noqa: BLE001
            _log.exception("pumping test could not be parsed")
            test = None
            issues.append(_issue(
                "pump", "pump_analysis", "parse_error",
                "The pumping test sheet could not be read, so the drawdown and "
                "yield results were not restored.",
                context=pump_path.name, exc=exc,
            ))
        if test is not None:
            try:
                for step in test.steps:
                    q = discharges.get(str(step.step_number))
                    if q:
                        step.discharge_m3_per_h = float(q)
                out["pump_analysis"] = analyse_pumping_test(test, config.pumping)
                ok.append("pump")
            except Exception as exc:  # noqa: BLE001
                _log.exception("pumping test could not be analysed")
                issues.append(_issue(
                    "pump", "pump_analysis", "analysis_error",
                    "The pumping test sheet was read but the analysis failed, "
                    "so there is no transmissivity or yield recommendation.",
                    context=pump_path.name, exc=exc,
                ))

    wq_path = _path("wq")
    if wq_path is not None:
        try:
            sample = read_quality_workbook(wq_path)
        except Exception as exc:  # noqa: BLE001
            _log.exception("water quality workbook could not be parsed")
            sample = None
            issues.append(_issue(
                "wq", "wq_assessment", "parse_error",
                "The water quality workbook could not be read, so no "
                "suitability verdict was restored. Do not treat the absence of "
                "a verdict as a pass.",
                context=wq_path.name, exc=exc,
            ))
        if sample is not None:
            try:
                out["wq_assessment"] = assess_sample(sample)
                ok.append("wq")
            except Exception as exc:  # noqa: BLE001
                _log.exception("water quality sample could not be assessed")
                issues.append(_issue(
                    "wq", "wq_assessment", "analysis_error",
                    "The laboratory results were read but could not be assessed "
                    "against the standards, so there is no verdict. Do not "
                    "treat the absence of a verdict as a pass.",
                    context=wq_path.name, exc=exc,
                ))

    log_path = _path("log")
    if log_path is not None:
        try:
            log = read_drilling_workbook(log_path)
        except Exception as exc:  # noqa: BLE001
            _log.exception("drilling log could not be parsed")
            log = None
            issues.append(_issue(
                "log", "drilling_log", "parse_error",
                "The drilling log could not be read, so the lithology and the "
                "borehole design were not restored.",
                context=log_path.name, exc=exc,
            ))
        if log is not None:
            out["drilling_log"] = log
            ok.append("log")
            try:
                out["borehole_design"] = design_borehole(
                    log=log,
                    static_water_level_m=design_swl or None,
                    rules=config.design,
                )
            except Exception as exc:  # noqa: BLE001
                _log.exception("borehole design could not be derived")
                issues.append(_issue(
                    "log", "borehole_design", "analysis_error",
                    "The drilling log was read but the borehole design could "
                    "not be derived from it, so the screen layout and the bill "
                    "of quantities are missing.",
                    context=log_path.name, exc=exc, level="warning",
                ))

    # Always present, so loading a second project clears the first one's
    # banner rather than leaving a stale one on screen.
    out["recompute_diagnostics"] = {
        "ok": ok,
        "issues": [issue.as_dict() for issue in issues],
    }
    return out
