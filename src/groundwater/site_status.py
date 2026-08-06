"""What a borehole's recorded status actually means.

Field sheets carry the status as free text - "Successful", "Completed -
Dry", "Incomplete, rig broke down", "Unproductive" - and the portfolio has
to turn that into one of a few classes to colour a map and compute a
success rate. Substring matching cannot do it: "complete" is inside
"incomplete", "productive" is inside "unproductive", and "sit" is inside
"visited". Every one of those read as a producing borehole, so a programme
that had drilled a run of dry holes reported them as successes and painted
them green on the national map.

So the mapping is explicit. Known phrasings are listed; the rest are
matched by word-boundary rules ordered so that a negation is always seen
before the word it negates; and anything still unrecognised lands in
:attr:`SiteStatus.OTHER` rather than being guessed at. Failing to classify
is visible and harmless. Classifying a dry hole as a success is neither.
"""

from __future__ import annotations

import re
from enum import Enum


class SiteStatus(str, Enum):
    """The portfolio classes. ``str`` mixin, so ``== "successful"`` works."""

    SUCCESSFUL = "successful"
    DRY = "dry"
    SITED = "sited"
    IN_PROGRESS = "in_progress"
    OTHER = "other"


# The lookup tables are keyed by the wire strings rather than by members.
# Enum hashes by member name, not by value, so a member-keyed dict cannot
# also be indexed with the plain string that a saved project file carries -
# and the callers that do exactly that (mapping/regional.py, the Streamlit
# chip) would raise a KeyError at render time.

#: Map colours: red for a problem, green for a producing hole, grey for a
#: status nobody could read - grey so it reads as missing data rather than
#: as an outcome.
STATUS_COLORS = {
    "successful": "#2E7D5B",
    "dry": "#B23A2E",
    "sited": "#17527E",
    "in_progress": "#C1772A",
    "other": "#6B7785",
}

STATUS_LABELS = {
    "successful": "Successful",
    "dry": "Dry / failed",
    "sited": "Sited (not drilled)",
    "in_progress": "In progress",
    "other": "Status not recognised",
}

#: Exact phrasings seen on real sheets and in saved projects, normalised.
#: An entry here beats every rule below, so a known wording can never be
#: caught by a rule meant for something else.
LEGACY_STATUS_MAP = {
    "successful": SiteStatus.SUCCESSFUL,
    "success": SiteStatus.SUCCESSFUL,
    "completed": SiteStatus.SUCCESSFUL,
    "complete": SiteStatus.SUCCESSFUL,
    "productive": SiteStatus.SUCCESSFUL,
    "equipped": SiteStatus.SUCCESSFUL,
    "commissioned": SiteStatus.SUCCESSFUL,
    "handed over": SiteStatus.SUCCESSFUL,
    "dry": SiteStatus.DRY,
    "dry hole": SiteStatus.DRY,
    "failed": SiteStatus.DRY,
    "failure": SiteStatus.DRY,
    "unsuccessful": SiteStatus.DRY,
    "not successful": SiteStatus.DRY,
    "unproductive": SiteStatus.DRY,
    "non productive": SiteStatus.DRY,
    "abandoned": SiteStatus.DRY,
    "no water": SiteStatus.DRY,
    "completed dry": SiteStatus.DRY,
    "sited": SiteStatus.SITED,
    "siting": SiteStatus.SITED,
    "surveyed": SiteStatus.SITED,
    "not drilled": SiteStatus.SITED,
    "incomplete": SiteStatus.IN_PROGRESS,
    "not completed": SiteStatus.IN_PROGRESS,
    "uncompleted": SiteStatus.IN_PROGRESS,
    "in progress": SiteStatus.IN_PROGRESS,
    "ongoing": SiteStatus.IN_PROGRESS,
    "drilling": SiteStatus.IN_PROGRESS,
    "pending": SiteStatus.IN_PROGRESS,
    "on hold": SiteStatus.IN_PROGRESS,
}

# Ordered rules, first match wins. The order is load-bearing: every rule
# that recognises a negation ("unproductive", "not completed") must be
# tried before the rule that would match the word being negated.
_RULES: list[tuple[re.Pattern, SiteStatus]] = [
    # 1. Outright failure.
    (
        re.compile(
            r"\b(dry|no\s+water|water\s+not\s+struck|failed|failure|"
            r"unsuccessful|not\s+successful|abandon\w*|collapsed|backfilled|"
            r"plugged|caved)\b"
        ),
        SiteStatus.DRY,
    ),
    # 2. Failure written as a negated success. THIS is the bug: "unproductive"
    #    contains "productive" and used to be read as a producing borehole.
    (
        re.compile(
            r"\b(un|non|not)[\s-]*(productive|producing)\b"
            r"|\b(low|poor|insufficient|inadequate|marginal|nil)\s+"
            r"(yield|productivity|production)\b"
            r"|\bproductivity\s+(low|poor)\b"
        ),
        SiteStatus.DRY,
    ),
    # 3. Unfinished written as a negated completion. "incomplete" contains
    #    "complete" and used to be read as a finished, producing hole.
    (
        re.compile(
            r"\b(in|un)complet\w*\b|\bnot\s+complet\w*\b"
            r"|\b(partially|part|partly)\s+complet\w*\b"
        ),
        SiteStatus.IN_PROGRESS,
    ),
    # 4. Unfinished, said plainly.
    (
        re.compile(
            r"\b(in\s+progress|ongoing|under\s+(construction|way|test\w*)|"
            r"drilling|pending|awaiting|suspended|on\s+hold|deferred|"
            r"standing\s+by|rework)\b"
        ),
        SiteStatus.IN_PROGRESS,
    ),
    # 5. Sited but not drilled. Word-anchored, so "visited" and "deposit" no
    #    longer count as a siting. ("not sited" is refused before the rules
    #    run - written as a plain check rather than a lookbehind so the same
    #    expression compiles in both this engine and the browser one.)
    (
        re.compile(
            r"\bsit(e|ed|ing)\b"
            r"|\b(surveyed|survey\s+complete|geophysics\s+complete|"
            r"recommended\s+for\s+drilling|to\s+be\s+drilled|not\s+drilled)\b"
        ),
        SiteStatus.SITED,
    ),
    # 6. Success, last, so every negation above has already had its turn.
    (
        re.compile(
            r"\bsuccess(ful)?\b|\bcomplet(e|ed)\b|\bproductive\b"
            r"|\b(equipped|commissioned|handed\s+over|operational|functional)\b"
        ),
        SiteStatus.SUCCESSFUL,
    ),
]

_SEPARATORS = re.compile(r"[_/\\|,;()\[\].–—-]+")


def normalise_status(raw: str) -> str:
    """Fold punctuation and spacing so "Completed - Dry" == "completed dry"."""
    text = _SEPARATORS.sub(" ", str(raw or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def coerce_status(value) -> SiteStatus:
    """Turn a stored wire value back into a member, unrecognised -> OTHER."""
    if isinstance(value, SiteStatus):
        return value
    try:
        return SiteStatus(str(value or "").strip().lower())
    except ValueError:
        return SiteStatus.OTHER


def status_label(value) -> str:
    """Display label for a member or its wire value."""
    return STATUS_LABELS[coerce_status(value).value]


def status_color(value) -> str:
    """Map colour for a member or its wire value."""
    return STATUS_COLORS[coerce_status(value).value]


def classify_text(raw: str) -> SiteStatus | None:
    """Classify a free-text status, or ``None`` when it is not recognised.

    ``None`` rather than a guess: an unreadable status is data to fix, and
    the caller decides what to show for it.
    """
    key = normalise_status(raw)
    if not key:
        return None
    exact = LEGACY_STATUS_MAP.get(key)
    if exact is not None:
        return exact
    if re.search(r"\bnot\s+sited\b", key):
        return None  # a negation, not a siting
    for pattern, status in _RULES:
        if pattern.search(key):
            return status
    return None
