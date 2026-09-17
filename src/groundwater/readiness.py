"""Whether a project's results are complete enough to certify.

A completion report is the document a borehole is handed over on. It gets
filed, invoiced against, and read years later by someone deciding whether
the village still has water. The toolkit will write one from whatever it
has - and it should, because an interim report is a real need - but it must
not let a document that rests on missing evidence look like one that does
not.

So every report carries its own provenance. This module answers one
question, over the results the project already holds: which of the things a
certifiable report needs are actually established? The answer is a list of
:class:`Requirement` records, each either met, unmet, not applicable, or
overridden by a named person with a stated reason. A report built from a
project that is not ready is stamped PROVISIONAL on its cover and carries
the list; a report built from one that is ready is not stamped at all.
Nothing is blocked, and nothing is quietly passed off as final.

**Completeness, not outcome.** A borehole whose water fails the arsenic
guideline is a perfectly certifiable borehole: the finding is the point of
the report. What is not certifiable is a borehole whose arsenic result
could not be read. The requirements here ask "do we know?", never "is the
answer the one we wanted?" - a gate that failed bad news would teach people
to leave the bad news out.

The signals are not re-derived. Every module in the toolkit already raises
:class:`~groundwater.models.DataFlag` for what it could not do, and the
water quality assessment already exposes its own uncertainties; this module
reads those. A requirement that invented its own check would drift from the
analysis it is supposed to describe.
"""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Optional

__all__ = [
    "Requirement",
    "Readiness",
    "REPORTS",
    "REQUIREMENTS",
    "SampleProvenance",
    "assess_readiness",
    "load_sample_provenance",
    "source_provenance",
]

#: Flag codes that mean a reading was refused, converted from an unreadable
#: unit, or otherwise could not be used. Raised by ingestion/pumping.py and
#: quality/assess.py; listed here so the gate and the parsers cannot drift.
_UNIT_BLOCKERS = (
    "time_unit_unknown",
    "discharge_unit_unknown",
    "discharge_ambiguous",
    "time_reading_unreadable",
)

#: Codes that say a value was assumed rather than read. Not blocking - the
#: assumption is stated in the report - but worth surfacing beside the gate.
_UNIT_ASSUMPTIONS = (
    "discharge_unit_assumed",
    "unit_not_reported",
    "unit_basis_assumed",
    "utm_zone_assumed",
    "test_type_inferred",
)


@dataclass(frozen=True)
class SampleProvenance:
    """What one bundled example file actually contains.

    ``kind`` is one of:

    ``transcribed``
        Copied verbatim off a real survey or completion document. Numbers
        read out of it are somebody's real measurements.
    ``reconstructed``
        Real measurements, but a column the original left blank has been
        filled in illustratively. Worth stating on the report; not a reason
        to withhold certification, because the measurements are real.
    ``synthetic``
        The readings were invented. Nothing was measured, and a report that
        quotes them is describing a sample that was never taken.
    """

    file: str
    kind: str
    note: str = ""

    @property
    def measured(self) -> bool:
        """Whether the readings in this file were taken from something real."""
        return self.kind != "synthetic"


@lru_cache(maxsize=4)
def load_sample_provenance(path: str | Path | None = None) -> dict[str, SampleProvenance]:
    """The bundled example files, keyed by basename.

    Keyed by basename rather than by the path each engine happens to use:
    the browser bundles ``dr_timbo/dr_timbo_water_quality.xlsx``, the
    Streamlit picker offers the same relative path, and
    ``examples/run_dr_timbo_completion.py`` opens it straight off disk. It
    is one file, and what it contains does not depend on which of those
    opened it.
    """
    try:
        if path is not None:
            text = Path(path).read_text(encoding="utf-8")
        else:
            text = (resources.files("groundwater") / "data" /
                    "sample_provenance.csv").read_text(encoding="utf-8")
    except (OSError, ModuleNotFoundError):
        # The record is packaged with the library, so this should not
        # happen - but losing it must not take the gate down with it. An
        # empty record means no file is *known* to be synthetic, and the
        # bundled-sample marker below still does its half of the job.
        return {}
    out: dict[str, SampleProvenance] = {}
    for row in csv.DictReader(io.StringIO(text)):
        name = os.path.basename((row.get("file") or "").strip())
        if not name:
            continue
        out[name.lower()] = SampleProvenance(
            file=(row.get("file") or "").strip(),
            kind=(row.get("provenance") or "").strip().lower(),
            note=(row.get("note") or "").strip(),
        )
    return out


def source_provenance(source: Any) -> SampleProvenance | None:
    """The provenance record for one loaded source, if it is a bundled file.

    ``source`` is a source dict as both apps hold them: ``{"name": ...}``
    for an upload, ``{"sample": <relative path>}`` for a bundled pick, and
    in the browser both at once. Either key is matched against the record
    by basename, so a file is recognised however it was loaded.

    Matching on the name means a user file that happens to share a bundled
    file's name is taken for the bundled one. That is deliberate: the cost
    is a report stamped provisional that need not have been, which an
    analyst can see and override, and the alternative error is a report
    that quotes invented water quality results without saying so.
    """
    if not isinstance(source, dict):
        return None
    known = load_sample_provenance()
    for key in ("sample", "name"):
        value = source.get(key)
        if not value:
            continue
        found = known.get(os.path.basename(str(value)).lower())
        if found is not None:
            return found
    return None


@dataclass(frozen=True)
class Requirement:
    """One thing a certifiable report needs, and whether it is established."""

    key: str
    title: str
    #: "met" | "unmet" | "not_applicable" | "overridden"
    state: str
    #: What was found, in a sentence an analyst can act on.
    detail: str
    #: Who overrode it and why, when ``state`` is "overridden".
    override_reason: str = ""
    override_by: str = ""

    @property
    def satisfied(self) -> bool:
        """Whether this requirement stops holding the report back.

        An override satisfies it for the purpose of issuing the document and
        is recorded in the document; it does not make the evidence exist.
        """
        return self.state in ("met", "not_applicable", "overridden")


@dataclass
class Readiness:
    """The readiness of one project for one kind of report."""

    report: str
    requirements: list[Requirement] = field(default_factory=list)
    #: Assumptions the analysis made that the reader should see. Never
    #: blocking; a stated assumption is not a missing result.
    assumptions: list[str] = field(default_factory=list)

    @property
    def unmet(self) -> list[Requirement]:
        return [r for r in self.requirements if r.state == "unmet"]

    @property
    def overridden(self) -> list[Requirement]:
        return [r for r in self.requirements if r.state == "overridden"]

    @property
    def state(self) -> str:
        """``"ready"``, ``"ready_with_overrides"`` or ``"not_ready"``."""
        if self.unmet:
            return "not_ready"
        return "ready_with_overrides" if self.overridden else "ready"

    @property
    def is_certifiable(self) -> bool:
        """Whether the document may be issued without a PROVISIONAL stamp.

        An override is deliberately *not* certifiable. Overriding says "issue
        it anyway, on my authority", which is a legitimate thing to need and
        a different thing from the evidence being there.
        """
        return self.state == "ready"

    @property
    def summary(self) -> str:
        """One line for a cover stamp or a status chip."""
        if self.state == "ready":
            return "All certification requirements are met."
        if self.state == "ready_with_overrides":
            names = ", ".join(r.title for r in self.overridden)
            return f"Issued on override: {names}."
        names = ", ".join(r.title for r in self.unmet)
        return f"Not ready to certify - outstanding: {names}."

    def as_dict(self) -> dict:
        """JSON- and YAML-safe, so it round-trips in a saved project."""
        return {
            "report": self.report,
            "state": self.state,
            "requirements": [
                {
                    "key": r.key, "title": r.title, "state": r.state,
                    "detail": r.detail, "override_reason": r.override_reason,
                    "override_by": r.override_by,
                }
                for r in self.requirements
            ],
            "assumptions": list(self.assumptions),
        }


# ---------------------------------------------------------------------------
# The requirements themselves
# ---------------------------------------------------------------------------

def _flags(*objects) -> list:
    """Every DataFlag carried by the objects given, skipping the absent."""
    out = []
    for obj in objects:
        if obj is None:
            continue
        out.extend(getattr(obj, "flags", None) or [])
    return out


def _has(flags: Iterable, codes: Iterable[str]) -> list:
    wanted = set(codes)
    return [f for f in flags if getattr(f, "code", "") in wanted]


def _project_site(state: dict):
    """The site, merged across whatever the project holds.

    Field crews write the position on one sheet and not the others, so a
    project can be perfectly well located while the drilling log's own header
    block is blank. ``SiteMetadata.merged_with`` fills blanks without
    overwriting anything, which is the same rule the app's header uses.
    """
    site = state.get("site")
    for obj in (state.get("drilling_log"), state.get("wq_assessment"),
                state.get("borehole_design")):
        other = getattr(obj, "site", None) or getattr(
            getattr(obj, "sample", None), "site", None)
        if other is not None:
            site = other if site is None else site.merged_with(other)
    analysis = state.get("pump_analysis")
    if analysis is not None:
        site = analysis.test.site if site is None else site.merged_with(
            analysis.test.site)
    return site


def _site_located(state: dict) -> tuple[str, str]:
    site = _project_site(state)
    if site is None or site.easting is None or site.northing is None:
        return "unmet", (
            "No GPS position is recorded on any sheet in this project. A "
            "borehole that cannot be found again on the ground cannot be "
            "certified, revisited or maintained."
        )
    from .ingestion.checks import check_site_consistency

    errors = [f for f in check_site_consistency(site) if f.level == "error"]
    if errors:
        return "unmet", errors[0].message
    return "met", f"Position recorded: {site.utm}."


def _borehole_logged(state: dict) -> tuple[str, str]:
    log = state.get("drilling_log")
    if log is None:
        return "unmet", "No drilling log has been loaded."
    if not log.total_depth_m:
        return "unmet", "The drilling log records no total depth."
    if not log.intervals:
        return "unmet", "The drilling log records no lithology."
    return "met", (
        f"Logged to {log.total_depth_m:.0f} m with {len(log.intervals)} "
        "lithological interval(s)."
    )


def _pumping_measured(state: dict) -> tuple[str, str]:
    analysis = state.get("pump_analysis")
    if analysis is None:
        return "unmet", "No pumping test has been analysed."
    test = analysis.test
    if test.static_water_level_m is None:
        return "unmet", (
            "The static water level is missing, so no drawdown can be "
            "computed from the test."
        )
    if not test.has_discharge:
        return "unmet", (
            "No discharge is recorded for the test, so transmissivity and "
            "yield stay pending."
        )
    missing = [s.step_number for s in test.steps if s.discharge_m3_per_h is None]
    if missing:
        return "unmet", (
            "Discharge is missing for step(s) "
            + ", ".join(str(n) for n in missing) + "."
        )
    return "met", (
        f"{len(test.steps)} step(s) with discharge, static water level "
        f"{test.static_water_level_m:.2f} m."
    )


def _readings_usable(state: dict) -> tuple[str, str]:
    """No reading was refused for a unit the toolkit could not read."""
    flags = _flags(state.get("pump_analysis"), state.get("drilling_log"))
    analysis = state.get("pump_analysis")
    if analysis is not None:
        flags += analysis.test.flags or []
    refused = _has(flags, _UNIT_BLOCKERS)
    if refused:
        return "unmet", "; ".join(f.message for f in refused)
    return "met", "Every reading carried a unit the toolkit could read."


def _yield_established(state: dict) -> tuple[str, str]:
    analysis = state.get("pump_analysis")
    if analysis is None or analysis.yield_recommendation is None:
        return "unmet", "No yield recommendation has been derived."
    rec = analysis.yield_recommendation
    if rec.pending_reason:
        return "unmet", rec.pending_reason
    if rec.safe_yield_m3_per_h is None:
        return "unmet", "The safe yield could not be derived from this test."
    # A yield the analysis itself calls indicative is not established. The
    # gate used to certify a 30-minute test inside its casing storage on
    # the strength of the number alone.
    if getattr(rec, "is_indicative", False):
        return "unmet", (
            f"The safe yield of {rec.yield_range_text} is indicative, not "
            "established: " + "; ".join(rec.confidence_reasons) + "."
        )
    return "met", f"Safe yield {rec.yield_range_text}."


def _water_quality_evaluable(state: dict) -> tuple[str, str]:
    """Every determinand in the sample was graded against a limit.

    Deliberately not "the verdict state is not indeterminate". A health
    exceedance outranks uncertainty in the *verdict* - and rightly, since a
    demonstrated failure is a finding - but it does not make an unreadable
    arsenic result readable. Certifying is about the evidence, so the rows
    are checked, not the headline.
    """
    assessment = state.get("wq_assessment")
    if assessment is None:
        return "unmet", "No water quality results have been assessed."
    ungraded = assessment.indeterminate_rows + assessment.unknown_parameters
    if ungraded:
        return "unmet", (
            "Not graded against any limit: "
            + ", ".join(dict.fromkeys(r.parameter for r in ungraded))
            + "."
        )
    if not assessment.evaluated_rows:
        return "unmet", "No result in the sample could be graded."
    return "met", (
        f"{len(assessment.evaluated_rows)} determinand(s) graded; verdict "
        f"{assessment.verdict_state}."
    )


def _water_quality_panel(state: dict) -> tuple[str, str]:
    assessment = state.get("wq_assessment")
    if assessment is None:
        return "unmet", "No water quality results have been assessed."
    if assessment.missing_essential:
        return "unmet", (
            "No evaluable result for "
            + ", ".join(assessment.missing_essential) + "."
        )
    return "met", "The health panel was run and every result was evaluable."


def _design_derived(state: dict) -> tuple[str, str]:
    design = state.get("borehole_design")
    if design is None:
        return "unmet", "No borehole design has been derived."
    errors = [f for f in (design.flags or []) if f.level == "error"]
    if errors:
        return "unmet", errors[0].message
    if not design.screens:
        return "unmet", "The design places no screen."
    return "met", (
        f"{design.total_screen_length_m:.1f} m of screen in "
        f"{len(design.screens)} run(s)."
    )


def _no_errors(state: dict) -> tuple[str, str]:
    """Nothing anywhere raised an error-level flag.

    A catch-all, deliberately last: a module that learns to report a new
    fatal condition is covered by the gate the day it does, without this
    file having to be edited.
    """
    analysis = state.get("pump_analysis")
    sources = [
        state.get("drilling_log"), analysis, state.get("wq_assessment"),
        state.get("borehole_design"), state.get("cost_estimate"),
    ]
    if analysis is not None:
        sources.append(analysis.test)
    errors = [f for f in _flags(*sources) if f.level == "error"]
    if errors:
        return "unmet", "; ".join(dict.fromkeys(f.message for f in errors))
    return "met", "No module reported a fatal problem with the data."


def _cost_basis(state: dict) -> tuple[str, str]:
    """A cost estimate exists and is built on a stated depth.

    An estimate is a pre-construction document by its own words, so it is
    not held to a drilling log and an as-built design: demanding those
    stamped every budget PROVISIONAL at exactly the time a budget is needed.
    """
    estimate = state.get("cost_estimate")
    if estimate is None:
        return "unmet", "No cost estimate has been computed."
    depth = getattr(getattr(estimate, "inputs", None), "total_depth_m", None)
    if not depth:
        return "unmet", "The cost estimate has no total depth to price against."
    return "met", f"Estimate priced for a {depth:.0f} m borehole."


def _field_data(state: dict) -> tuple[str, str]:
    """The report describes this borehole, not a worked example.

    The toolkit ships example datasets and offers them from a picker, which
    is the right thing to do: nobody should have to have drilled a borehole
    to find out what the software does. But the documents it writes from
    them are indistinguishable from the ones it writes from real work - the
    same letterhead, the same tables, the same signature block - and they
    leave the machine that made them as .docx files that get forwarded,
    filed and read years later by somebody who was not there when they were
    generated.

    So the fact travels with the document. Two different things make a
    project fail this, and they are not equally serious:

    * a source whose readings were **invented**. The Dr Timbo water quality
      workbook is the one in the bundle: no sample was ever taken, and the
      determinand values exist to exercise the assessment. A quality report
      drawn from it states arsenic and coliform results for a sample that
      does not exist.
    * a source **picked from the sample list**, whoever it was transcribed
      from. The Rokel soundings are a real 2015 survey, faithfully copied,
      and the numbers in them are sound - but a report an evaluator
      produces by clicking "load a sample" is a survey of Rokel, not of the
      site they are evaluating, and it should not be issuable as one.

      This one turns on the ``sample`` marker rather than on the file,
      because it is a fact about the session and not about the data. A
      script that opens the same workbook to publish the worked example
      itself is reporting Rokel as Rokel, and is not caught.

    Both are stated rather than blocked, like every other requirement here.
    An override is available and is recorded on the cover, which is the
    right escape hatch for the one case that needs it: someone
    deliberately publishing the worked example itself.
    """
    sources = state.get("sources") or {}
    if not isinstance(sources, dict):
        return "met", "No input is a bundled example file."

    invented, bundled = [], []
    for source in sources.values():
        record = source_provenance(source)
        if record is None:
            continue
        name = os.path.basename(record.file)
        if not record.measured:
            # True of the file however it was opened: nothing was sampled.
            invented.append(name)
        elif isinstance(source, dict) and source.get("sample"):
            # Only when it was *picked from the sample list*. The marker is
            # set by the two apps' pickers and by nothing else, which is the
            # distinction that matters: the Rokel soundings are a real survey,
            # so examples/run_rokel_geophysics.py publishing them under the
            # Rokel name is reporting exactly what it says it is. The same
            # file pulled into somebody else's project is not.
            bundled.append(name)

    if invented:
        return "unmet", (
            "Readings that were never measured are in this project: "
            + ", ".join(sorted(dict.fromkeys(invented)))
            + ". The values in "
            + ("that file were" if len(set(invented)) == 1 else "those files were")
            + " invented to demonstrate the toolkit, so no result derived "
            "from them describes anything that was sampled."
        )
    if bundled:
        return "unmet", (
            "This project is built on the bundled example data ("
            + ", ".join(sorted(dict.fromkeys(bundled)))
            + "), which was recorded at another site. The analysis is of "
            "that example, not of the borehole named on this report."
        )
    return "met", "No input is a bundled example file."


#: Every requirement, in the order a reader should see them: the borehole
#: first, then what was measured in it, then what it produced.
REQUIREMENTS: dict[str, tuple[str, Any]] = {
    # First, because it qualifies every other answer below it: a met
    # requirement established from invented readings is still invented.
    "field_data": ("Field data", _field_data),
    "site_located": ("Site position", _site_located),
    "borehole_logged": ("Drilling log", _borehole_logged),
    # Negative checks: vacuously met when there is nothing to have gone wrong
    # with, which is harmless because the positive requirements beside them
    # (a log, a test, a sample) already catch absence.
    "readings_usable": ("Readable units", _readings_usable),
    "pumping_measured": ("Pumping test measured", _pumping_measured),
    "yield_established": ("Yield established", _yield_established),
    "water_quality_panel": ("Water quality panel", _water_quality_panel),
    "water_quality_evaluable": ("Water quality evaluable", _water_quality_evaluable),
    "design_derived": ("Borehole design", _design_derived),
    "cost_basis": ("Cost estimate", _cost_basis),
    "no_errors": ("No fatal data problems", _no_errors),
}

#: What each report has to be able to stand behind. A pumping report makes
#: no claim about water quality, so an unassessed sample does not hold it
#: back; a handover report tells a village the water is safe to drink, so it
#: needs everything.
REPORTS: dict[str, tuple[str, ...]] = {
    "completion": (
        "field_data",
        "site_located", "borehole_logged", "readings_usable",
        "pumping_measured", "yield_established", "water_quality_panel",
        "water_quality_evaluable", "design_derived", "no_errors",
    ),
    "handover": (
        "field_data",
        "site_located", "borehole_logged", "pumping_measured",
        "yield_established", "water_quality_panel", "water_quality_evaluable",
        "no_errors",
    ),
    "quality": (
        "field_data",
        "site_located", "water_quality_panel", "water_quality_evaluable",
        "no_errors",
    ),
    "pumping": (
        "field_data",
        "site_located", "readings_usable", "pumping_measured",
        "yield_established", "no_errors",
    ),
    "geophysical": ("field_data", "site_located"),
    # An estimate is priced before anything is drilled, so it is judged on
    # its own inputs, not on a log and an as-built design it cannot have.
    "costing": ("field_data", "site_located", "cost_basis", "no_errors"),
    "supervision": ("field_data", "site_located"),
    # The asset documents and the payment certificate. Without an entry each
    # of these fell back to the completion set, so a plate for the headworks
    # was stamped PROVISIONAL for want of a water quality panel - which a
    # plate makes no claim about. What a plate does claim is that the
    # identifier on it leads back to this borehole, and that identifier is
    # minted from the position, so the position is the requirement.
    "placard": ("field_data", "site_located"),
    "asset": ("field_data", "site_located"),
    # A certificate is a claim that work was done at a place and is worth
    # paying for. It makes no claim about the water.
    "procurement": ("field_data", "site_located", "no_errors"),
}


def assess_readiness(
    state: dict,
    report: str = "completion",
    overrides: Optional[dict] = None,
) -> Readiness:
    """Judge one project against what one kind of report has to stand behind.

    ``state`` is keyed as the app's session is - ``site``, ``drilling_log``,
    ``pump_analysis``, ``wq_assessment``, ``borehole_design``,
    ``cost_estimate`` - so the app can pass its session straight in and a
    test can pass a dict.

    ``overrides`` maps a requirement key to ``{"reason": ..., "by": ...}``
    (a bare string is taken as the reason). An override is recorded on the
    requirement and reproduced on the report, and never makes the project
    certifiable - only issuable.
    """
    overrides = overrides or {}
    keys = REPORTS.get(report, REPORTS["completion"])
    requirements: list[Requirement] = []

    for key in keys:
        title, check = REQUIREMENTS[key]
        try:
            found, detail = check(state)
        except Exception as exc:  # noqa: BLE001 - a broken check is not a pass
            found, detail = "unmet", (
                f"The {title.lower()} check could not run: "
                f"{type(exc).__name__}: {exc}"
            )
        override = overrides.get(key)
        if found == "unmet" and override:
            reason = override.get("reason", "") if isinstance(override, dict) else str(override)
            by = override.get("by", "") if isinstance(override, dict) else ""
            requirements.append(Requirement(
                key=key, title=title, state="overridden", detail=detail,
                override_reason=reason, override_by=by,
            ))
            continue
        requirements.append(
            Requirement(key=key, title=title, state=found, detail=detail)
        )

    try:
        analysis = state.get("pump_analysis")
        sources = [
            state.get("drilling_log"), analysis, state.get("wq_assessment"),
            state.get("borehole_design"),
        ]
        if analysis is not None:
            sources.append(analysis.test)
        assumptions = list(dict.fromkeys(
            f.message for f in _has(_flags(*sources), _UNIT_ASSUMPTIONS)
        ))
    except Exception:  # noqa: BLE001 - a malformed object costs the list, not the gate
        assumptions = []

    # A bundled file whose measurements are real but whose blank columns were
    # filled in illustratively. Not blocking - the readings are somebody's
    # real readings - but the reader should know which column is which.
    try:
        for source in (state.get("sources") or {}).values():
            record = source_provenance(source)
            if record is not None and record.kind == "reconstructed":
                assumptions.append(
                    f"{os.path.basename(record.file)}: {record.note}")
        assumptions = list(dict.fromkeys(assumptions))
    except Exception:  # noqa: BLE001 - as above
        pass

    return Readiness(report=report, requirements=requirements,
                     assumptions=assumptions)
