"""Drilling supervision checklists as data.

The checklist content follows RWSN/UNICEF "Supervising Water Well
Drilling: a Guide for Supervisors" (Adekile), whose Annex B checklists
cover the nine step borehole construction workflow, and the WASH
funders infrastructure checklists for boreholes and handpumps. Items
live in an editable CSV (``data/supervision_checklists.csv``) so a
project can adapt them without code changes.

Critical items are the ones whose failure should stop acceptance of
the works (safety, records, acceptance criteria and sign offs).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from ..models import DataFlag

# Ordered stages of the supervision workflow, keyed as in the CSV.
STAGE_TITLES: tuple[tuple[str, str], ...] = (
    ("procurement", "Procurement and contract"),
    ("pre_contract", "Pre-contract inspection"),
    ("siting", "Siting"),
    ("mobilisation", "Mobilisation"),
    ("drilling", "Drilling"),
    ("design", "Design and installation"),
    ("development", "Development and completion"),
    ("demobilisation", "Demobilisation"),
    ("handover", "Documentation and handover"),
    ("post_construction", "Post-construction monitoring"),
)

STAGE_ORDER = tuple(key for key, _ in STAGE_TITLES)

RESPONSE_STATES = ("pending", "yes", "no", "na")


@dataclass
class ChecklistItem:
    """One supervision checklist requirement."""

    item_id: str  # stable id, e.g. "drilling-03"
    checklist: str  # stage key, e.g. "drilling"
    section: str  # grouping within the stage, e.g. "Safety"
    text: str
    critical: bool = False
    guidance: str = ""


def stage_title(key: str) -> str:
    for stage_key, title in STAGE_TITLES:
        if stage_key == key:
            return title
    return key.replace("_", " ").capitalize()


def load_checklists(path: str | Path | None = None) -> list[ChecklistItem]:
    """Load the checklist items (bundled CSV unless a path is given)."""
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = (
            resources.files("groundwater") / "data" / "supervision_checklists.csv"
        ).read_text(encoding="utf-8")
    items: list[ChecklistItem] = []
    counters: dict[str, int] = {}
    for row in csv.DictReader(text.splitlines()):
        checklist = row["checklist"].strip()
        counters[checklist] = counters.get(checklist, 0) + 1
        items.append(
            ChecklistItem(
                item_id=f"{checklist}-{counters[checklist]:02d}",
                checklist=checklist,
                section=row["section"].strip(),
                text=row["item"].strip(),
                critical=(row.get("critical") or "").strip().lower() == "yes",
                guidance=(row.get("guidance") or "").strip(),
            )
        )
    return items


@dataclass
class ChecklistResponse:
    """The supervisor's answer to one checklist item."""

    item_id: str
    status: str = "pending"  # pending | yes | no | na
    remark: str = ""


@dataclass
class StageProgress:
    stage: str
    title: str
    total: int
    answered: int
    passed: int
    failed: int
    critical_failed: int
    critical_open: int

    @property
    def complete(self) -> bool:
        return self.answered == self.total

    @property
    def percent(self) -> float:
        return 100.0 * self.answered / self.total if self.total else 0.0


@dataclass
class ChecklistAssessment:
    """Roll-up of the responses across all stages."""

    stages: list[StageProgress]
    flags: list[DataFlag] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(s.total for s in self.stages)

    @property
    def answered(self) -> int:
        return sum(s.answered for s in self.stages)

    @property
    def percent(self) -> float:
        return 100.0 * self.answered / self.total if self.total else 0.0

    @property
    def critical_failures(self) -> int:
        return sum(s.critical_failed for s in self.stages)

    @property
    def verdict(self) -> str:
        if self.critical_failures:
            return (
                f"{self.critical_failures} critical item(s) failed; the works "
                "should not be accepted until they are resolved."
            )
        open_critical = sum(s.critical_open for s in self.stages)
        if open_critical:
            return (
                f"{open_critical} critical item(s) still open; complete them "
                "before sign off."
            )
        if self.answered < self.total:
            return "No critical failures; routine items remain open."
        return "All checklist items answered with no critical failures."


def evaluate_checklist(
    items: list[ChecklistItem],
    responses: dict[str, ChecklistResponse] | list[ChecklistResponse],
) -> ChecklistAssessment:
    """Score responses against the checklist and flag critical failures."""
    if not isinstance(responses, dict):
        responses = {r.item_id: r for r in responses}
    stages: list[StageProgress] = []
    flags: list[DataFlag] = []
    stage_keys = [k for k in STAGE_ORDER if any(i.checklist == k for i in items)]
    stage_keys += sorted({i.checklist for i in items} - set(stage_keys))
    for key in stage_keys:
        stage_items = [i for i in items if i.checklist == key]
        answered = passed = failed = critical_failed = critical_open = 0
        for item in stage_items:
            response = responses.get(item.item_id)
            status = response.status if response else "pending"
            if status not in RESPONSE_STATES:
                status = "pending"
            if status != "pending":
                answered += 1
            if status in ("yes", "na"):
                passed += 1
            elif status == "no":
                failed += 1
                if item.critical:
                    critical_failed += 1
                    flags.append(
                        DataFlag(
                            "error",
                            "critical_item_failed",
                            item.text,
                            context=stage_title(key),
                        )
                    )
            elif item.critical:
                critical_open += 1
        stages.append(
            StageProgress(
                stage=key,
                title=stage_title(key),
                total=len(stage_items),
                answered=answered,
                passed=passed,
                failed=failed,
                critical_failed=critical_failed,
                critical_open=critical_open,
            )
        )
    return ChecklistAssessment(stages=stages, flags=flags)


@dataclass
class SeparationDistance:
    structure: str
    min_distance_m: float
    note: str = ""


def load_separation_distances(
    path: str | Path | None = None,
) -> list[SeparationDistance]:
    """Minimum borehole separation distances (FGN/NWRI 2010, via RWSN)."""
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = (
            resources.files("groundwater") / "data" / "site_separation_distances.csv"
        ).read_text(encoding="utf-8")
    return [
        SeparationDistance(
            structure=row["structure"].strip(),
            min_distance_m=float(row["min_distance_m"]),
            note=(row.get("note") or "").strip(),
        )
        for row in csv.DictReader(text.splitlines())
    ]
