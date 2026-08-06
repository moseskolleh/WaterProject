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

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

__all__ = [
    "Requirement",
    "Readiness",
    "REPORTS",
    "REQUIREMENTS",
    "assess_readiness",
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


#: Every requirement, in the order a reader should see them: the borehole
#: first, then what was measured in it, then what it produced.
REQUIREMENTS: dict[str, tuple[str, Any]] = {
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
    "no_errors": ("No fatal data problems", _no_errors),
}

#: What each report has to be able to stand behind. A pumping report makes
#: no claim about water quality, so an unassessed sample does not hold it
#: back; a handover report tells a village the water is safe to drink, so it
#: needs everything.
REPORTS: dict[str, tuple[str, ...]] = {
    "completion": (
        "site_located", "borehole_logged", "readings_usable",
        "pumping_measured", "yield_established", "water_quality_panel",
        "water_quality_evaluable", "design_derived", "no_errors",
    ),
    "handover": (
        "site_located", "borehole_logged", "pumping_measured",
        "yield_established", "water_quality_panel", "water_quality_evaluable",
        "no_errors",
    ),
    "quality": (
        "site_located", "water_quality_panel", "water_quality_evaluable",
        "no_errors",
    ),
    "pumping": (
        "site_located", "readings_usable", "pumping_measured",
        "yield_established", "no_errors",
    ),
    "geophysical": ("site_located",),
    "costing": ("site_located", "borehole_logged", "design_derived"),
    "supervision": ("site_located",),
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
    return Readiness(report=report, requirements=requirements,
                     assumptions=assumptions)
