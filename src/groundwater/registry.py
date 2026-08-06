"""The borehole as an asset, not as a project.

A drilling project ends. The borehole does not: it is pumped every day for
twenty years by people who were not there when it was drilled, and the
question that matters after handover is not "what did the pumping test say"
but "is it working, when was it last looked at, and when was the water last
tested". The completion report cannot answer that, because it was written
once and never touched again.

So this module holds the other half. An asset has a stable identifier that
survives the project file, a position, and an append-only stream of events -
commissioned, inspected, sampled, broken down, repaired, abandoned. From
that stream it derives what is true today: whether the point is working,
how long it has been out, and what is now overdue.

Three things shape the design.

**Offline first.** Field updates are recorded on a phone at the wellhead
with no signal, often by two people who each write the visit down. Events
are therefore identified by their content rather than by a counter, so the
same visit recorded twice merges into one, and a merge is a set union that
needs no server to arbitrate it.

**Append-only.** A maintenance record that can be edited is a maintenance
record nobody can rely on. A mistake is corrected by recording the
correction, which leaves both in the history where an auditor can see them.

**Nothing is assumed working.** An asset with no events is ``unknown``, not
``functional``. A failure with no recorded repair stays a failure. The
common way an asset register becomes useless is that absence of bad news
gets read as good news, and after two years everything is green.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .geo import infer_zone_for_sierra_leone, utm_to_geographic

__all__ = [
    "Asset",
    "AssetEvent",
    "AssetState",
    "DISTRICT_CODES",
    "EVENT_KINDS",
    "FUNCTION_LABELS",
    "Schedule",
    "asset_from_project",
    "asset_state",
    "check_character",
    "event_id",
    "format_asset_id",
    "merge_events",
    "mint_asset_id",
    "parse_asset_id",
    "placard_lines",
    "qr_payload",
    "registry_rows",
    "registry_stats",
    "validate_asset_id",
]


# ---------------------------------------------------------------------------
# The identifier
# ---------------------------------------------------------------------------

#: Crockford's base 32: no I, L, O or U, so nothing in a code can be confused
#: with 1, 0 or V when it is read off a plate or repeated over a radio.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

#: What a reader who writes I, L, O or U anyway almost certainly meant.
_FOLD = {"I": "1", "L": "1", "O": "0", "U": "V"}

#: The check character is ISO 7064 MOD 37,36, whose alphabet is the full 36.
_CHECK_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: District codes. Written out rather than derived, for the same reason the
#: site statuses are: a rule that produces "BO" for Bo and "BOM" for Bombali
#: today produces a collision the first time a district is renamed, and a
#: collision here means two boreholes with one identifier.
DISTRICT_CODES = {
    "western area urban": "WAU",
    "western area rural": "WAR",
    "port loko": "PL",
    "kambia": "KAM",
    "karene": "KAR",
    "bombali": "BOM",
    "falaba": "FAL",
    "koinadugu": "KOI",
    "tonkolili": "TON",
    "kono": "KON",
    "kenema": "KEN",
    "kailahun": "KAI",
    "bo": "BO",
    "bonthe": "BON",
    "moyamba": "MOY",
    "pujehun": "PUJ",
}

#: A district nobody could match. Deliberately not a guess: an identifier
#: that says XX is one somebody can fix, and it still locates the borehole.
UNKNOWN_DISTRICT = "XX"

#: Positions are quantised to this before they go into the identifier.
POSITION_STEP_M = 10

_ID_RE = re.compile(r"^SL-([A-Z]{2,4})-([0-9A-Z]{7})-([0-9A-Z])$")


def check_character(body: str) -> str:
    """ISO 7064 MOD 37,36 over ``body``, ignoring separators.

    Chosen over a simpler weighted sum because it detects every single
    wrong character and every transposition of two adjacent ones - which
    between them are almost all the mistakes people make copying a code off
    a headworks plate into a phone.
    """
    product = 36
    for char in body.upper():
        value = _CHECK_ALPHABET.find(char)
        if value < 0:
            continue  # separators and spaces carry no value
        total = (product % 37) + value
        product = 2 * (total % 37 or 37)
    return _CHECK_ALPHABET[(37 - product % 37) % 36]


def _position_code(easting: float, northing: float, zone: int) -> str:
    """Seven characters holding the position to the nearest ten metres.

    Derived rather than allocated, because there is no server to allocate
    from: two teams standing at the same wellhead with no connection between
    them have to arrive at the same identifier.
    """
    east = int(round(float(easting) / POSITION_STEP_M))
    north = int(round(float(northing) / POSITION_STEP_M))
    if not 0 <= east < 1 << 17 or not 0 <= north < 1 << 17:
        raise ValueError(
            f"({easting}, {northing}) is not a position inside Sierra Leone; "
            "an identifier minted from it would not be findable"
        )
    value = ((1 if int(zone) == 29 else 0) << 34) | (east << 17) | north
    return "".join(_ALPHABET[(value >> shift) & 31]
                   for shift in range(30, -1, -5))


def _district_code(district: str) -> str:
    return DISTRICT_CODES.get(str(district or "").strip().lower(),
                              UNKNOWN_DISTRICT)


def format_asset_id(district_code: str, position_code: str) -> str:
    body = f"SL-{district_code}-{position_code}"
    return f"{body}-{check_character(body)}"


def mint_asset_id(site) -> str:
    """The identifier for a borehole at ``site``.

    Minted once, at commissioning, and carried from then on. A later GPS fix
    a few metres off the first one produces a different code, which is why
    the registry matches on the recorded identifier first and on proximity
    only as a fallback - the derivation is how the first identifier is made
    and how a lost one is reconstructed, not something to re-run each visit.
    """
    easting = getattr(site, "easting", None)
    northing = getattr(site, "northing", None)
    if easting is None or northing is None:
        raise ValueError(
            "a borehole with no recorded position cannot be given an "
            "identifier: there would be nothing to find it by"
        )
    zone = getattr(site, "utm_zone", None) or infer_zone_for_sierra_leone(
        float(easting))
    return format_asset_id(_district_code(getattr(site, "district", "")),
                           _position_code(easting, northing, zone))


def parse_asset_id(text: str) -> str | None:
    """Normalise a hand-entered identifier, or ``None`` if it is not one.

    Case, spacing and the four Crockford confusions (I and L for 1, O for 0,
    U for V) are forgiven in the position code, because they are reading
    mistakes rather than different codes. A failing check character is not
    forgiven: that is a wrong identifier, and a wrong identifier attaches a
    maintenance history to somebody else's borehole.
    """
    raw = re.sub(r"[\s_]+", "", str(text or "")).upper().replace("–", "-")
    if not raw:
        return None
    if not raw.startswith("SL-"):
        raw = "SL-" + raw
    parts = raw.split("-")
    if len(parts) != 4:
        return None
    _, district, code, given = parts
    code = "".join(_FOLD.get(c, c) for c in code)
    given = _FOLD.get(given, given)
    candidate = f"SL-{district}-{code}-{given}"
    if not _ID_RE.match(candidate):
        return None
    if check_character(f"SL-{district}-{code}") != given:
        return None
    return candidate


def validate_asset_id(text: str) -> tuple[bool, str]:
    """``(ok, reason)`` - the reason is written to be shown to the person typing."""
    raw = str(text or "").strip()
    if not raw:
        return False, "No identifier was entered."
    parsed = parse_asset_id(raw)
    if parsed:
        return True, ""
    tidy = re.sub(r"[\s_]+", "", raw.upper())
    if not tidy.startswith("SL-"):
        tidy = "SL-" + tidy
    parts = tidy.split("-")
    if len(parts) != 4:
        return False, ("An identifier looks like SL-WAR-8T4KQ2A-7: country, "
                       "district, position, check character.")
    _, district, code, given = parts
    code = "".join(_FOLD.get(c, c) for c in code)
    if not re.fullmatch(r"[0-9A-Z]{7}", code):
        return False, "The position part should be seven letters or digits."
    expected = check_character(f"SL-{district}-{code}")
    return False, (
        f"The check character does not match: this identifier should end in "
        f"{expected}, not {given}. Something in it has been mistyped.")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

#: kind -> (label, what it establishes about function, is it a service visit)
EVENT_KINDS = {
    "commissioned": ("Commissioned", "functional", False),
    "inspection": ("Sanitary inspection", None, True),
    "water_sample": ("Water sampled", None, False),
    "repair": ("Repair", "functional", True),
    "failure": ("Failure", "non_functional", True),
    "restored": ("Returned to service", "functional", True),
    "decommissioned": ("Decommissioned", "decommissioned", False),
    "note": ("Note", None, False),
}

FUNCTION_LABELS = {
    "functional": "Working",
    "non_functional": "Not working",
    "decommissioned": "Decommissioned",
    "unknown": "Not known",
}


def _hash32(text: str) -> int:
    """FNV-1a. Small, deterministic, and the same four lines in any language."""
    value = 0x811C9DC5
    for char in text:
        value = ((value ^ (ord(char) & 0xFF)) * 0x01000193) & 0xFFFFFFFF
    return value


def event_id(asset_id: str, when: str, kind: str, note: str = "",
             by: str = "") -> str:
    """A content-derived identifier, so recording a visit twice merges to one.

    Two people at the same wellhead writing down the same repair on the same
    day produce the same event, and a union of their phones has one entry
    rather than two. The cost is that two genuinely separate events with
    identical wording on the same day also collapse - which is the right way
    round: a duplicated record is a lie about how much maintenance happened.
    """
    digest = _hash32(f"{asset_id}|{when}|{kind}|{note.strip()}|{by.strip()}")
    tail = "".join(_ALPHABET[(digest >> shift) & 31] for shift in (15, 10, 5, 0))
    return f"{when}/{kind}/{tail}"


@dataclass
class AssetEvent:
    """One thing that happened to a borehole."""

    when: str                # ISO date; kept as written so a bad one is visible
    kind: str
    note: str = ""
    by: str = ""
    photo: str = ""          # a data URL or a path; opaque here
    event_id: str = ""

    def identified_for(self, asset_id: str) -> "AssetEvent":
        """A copy carrying its content-derived id."""
        return AssetEvent(
            when=self.when, kind=self.kind, note=self.note, by=self.by,
            photo=self.photo,
            event_id=self.event_id or event_id(asset_id, self.when, self.kind,
                                               self.note, self.by),
        )

    @property
    def label(self) -> str:
        return EVENT_KINDS.get(self.kind, ("Other", None, False))[0]

    @property
    def date(self) -> date | None:
        """The date, or ``None`` when it cannot be read.

        An event whose date is unreadable is kept - throwing away a
        maintenance record because of a typo is worse - but it can never
        establish when anything last happened.
        """
        try:
            return date.fromisoformat(str(self.when).strip())
        except (TypeError, ValueError):
            return None

    def as_dict(self) -> dict:
        return {"when": self.when, "kind": self.kind, "note": self.note,
                "by": self.by, "photo": self.photo, "event_id": self.event_id}


def _coerce_event(raw) -> AssetEvent | None:
    if isinstance(raw, AssetEvent):
        return raw
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()
    if kind not in EVENT_KINDS:
        kind = "note"
    return AssetEvent(
        when=str(raw.get("when") or "").strip(), kind=kind,
        note=str(raw.get("note") or ""), by=str(raw.get("by") or ""),
        photo=str(raw.get("photo") or ""),
        event_id=str(raw.get("event_id") or ""),
    )


def merge_events(asset_id: str, *streams) -> list[AssetEvent]:
    """Union of several event streams, in date order.

    This is the whole offline story. Two phones that have been out of touch
    for a fortnight each hold part of the history; merging them is a set
    union over content-derived identifiers, so it needs no clock agreement,
    no server and no conflict resolution. Merging is commutative and
    idempotent: order does not matter and doing it twice changes nothing.
    """
    merged: dict[str, AssetEvent] = {}
    for stream in streams:
        for raw in stream or []:
            event = _coerce_event(raw)
            if event is None:
                continue
            event = event.identified_for(asset_id)
            existing = merged.get(event.event_id)
            if existing is None:
                merged[event.event_id] = event
            elif not existing.photo and event.photo:
                # the only asymmetry: a phone that has the photograph wins,
                # because the alternative is losing it
                merged[event.event_id] = event
    return sorted(merged.values(),
                  key=lambda e: (e.when or "9999", e.kind, e.event_id))


# ---------------------------------------------------------------------------
# The asset
# ---------------------------------------------------------------------------

@dataclass
class Asset:
    """A borehole, as the people who maintain it see it."""

    asset_id: str
    community: str = ""
    district: str = ""
    chiefdom: str = ""
    easting: float | None = None
    northing: float | None = None
    utm_zone: int | None = None
    total_depth_m: float | None = None
    safe_yield_m3_per_h: float | None = None
    pump_type: str = ""
    installed_by: str = ""
    events: list[AssetEvent] = field(default_factory=list)

    @property
    def latlon(self) -> tuple[float, float] | None:
        if self.easting is None or self.northing is None:
            return None
        zone = self.utm_zone or infer_zone_for_sierra_leone(float(self.easting))
        try:
            return utm_to_geographic(float(self.easting), float(self.northing),
                                     int(zone))
        except Exception:  # noqa: BLE001 - a bad coordinate simply has no fix
            return None

    @property
    def label(self) -> str:
        place = self.community or "(unnamed site)"
        return f"{place} ({self.district})" if self.district else place

    def with_events(self, *streams) -> "Asset":
        """A copy carrying the merged union of this asset's events and more."""
        return Asset(**{**self.__dict__,
                        "events": merge_events(self.asset_id, self.events,
                                               *streams)})

    def as_dict(self) -> dict:
        payload = {k: v for k, v in self.__dict__.items() if k != "events"}
        payload["events"] = [e.identified_for(self.asset_id).as_dict()
                             for e in self.events]
        return payload


def asset_from_dict(payload: dict) -> Asset | None:
    """Rebuild an asset from a saved project file, or ``None`` if it is not one."""
    if not isinstance(payload, dict):
        return None
    asset_id = parse_asset_id(payload.get("asset_id"))
    if not asset_id:
        return None
    known = {f for f in Asset.__dataclass_fields__ if f != "events"}
    fields = {k: v for k, v in payload.items() if k in known}
    fields["asset_id"] = asset_id
    asset = Asset(**fields)
    asset.events = merge_events(asset_id, payload.get("events") or [])
    return asset


def asset_from_project(state: dict) -> Asset | None:
    """Draft an asset from an assembled project, or ``None`` without a position.

    Nothing is invented: the commissioning event is not written here, because
    a borehole is commissioned by somebody deciding it is, on a day, and that
    decision is a record with a name on it rather than a side effect of
    opening a page.
    """
    site = _project_site(state)
    if site is None:
        return None
    try:
        asset_id = mint_asset_id(site)
    except ValueError:
        return None
    log = state.get("drilling_log")
    analysis = state.get("pump_analysis")
    depth = getattr(log, "total_depth_m", None) if log is not None else None
    recommendation = getattr(analysis, "yield_recommendation", None)
    return Asset(
        asset_id=asset_id,
        community=getattr(site, "community", "") or "",
        district=getattr(site, "district", "") or "",
        chiefdom=getattr(site, "chiefdom", "") or "",
        easting=getattr(site, "easting", None),
        northing=getattr(site, "northing", None),
        utm_zone=getattr(site, "utm_zone", None),
        total_depth_m=depth,
        safe_yield_m3_per_h=getattr(recommendation, "safe_yield_m3_per_h", None),
        installed_by=getattr(site, "contractor", "") or "",
    )


def _project_site(state: dict):
    """The site metadata, merged across the sheets that carry any of it."""
    candidates = [state.get("site")]
    log = state.get("drilling_log")
    if log is not None:
        candidates.append(getattr(log, "site", None))
    analysis = state.get("pump_analysis")
    if analysis is not None:
        candidates.append(getattr(getattr(analysis, "test", None), "site", None))
    assessment = state.get("wq_assessment")
    if assessment is not None:
        candidates.append(getattr(getattr(assessment, "sample", None), "site",
                                  None))
    merged = None
    for site in candidates:
        if site is None:
            continue
        if merged is None:
            merged = site
            continue
        try:
            merged = merged.merged_with(site)
        except AttributeError:  # noqa: PERF203 - a plain object is fine as-is
            continue
    if merged is None:
        return None
    return merged if getattr(merged, "easting", None) is not None else None


# ---------------------------------------------------------------------------
# What is true today
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Schedule:
    """How often a working point should be visited.

    These are defaults, not a standard. Surveillance intervals for rural
    point sources are set by the programme and by the district, and vary
    with how many people drink from the point and what the last result said;
    a six-monthly sanitary inspection and an annual water sample is a common
    baseline to start from and to argue with. Change them here and every
    due-date in the registry moves with them.
    """

    inspection_months: int = 6
    water_sample_months: int = 12
    #: How long past due before an item stops being "due" and starts being
    #: "overdue". A visit is a journey, not a diary entry.
    grace_days: int = 30


@dataclass(frozen=True)
class DueItem:
    key: str
    title: str
    due_on: date | None
    state: str          # "due" | "overdue" | "unknown"
    detail: str

    def as_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "state": self.state,
                "due_on": self.due_on.isoformat() if self.due_on else None,
                "detail": self.detail}


@dataclass(frozen=True)
class AssetState:
    """What the event stream says about the borehole now."""

    function: str
    since: date | None
    detail: str
    last_inspection: date | None
    last_sample: date | None
    commissioned: date | None
    days_out_of_service: int | None
    due: tuple[DueItem, ...]
    undated_events: int

    @property
    def label(self) -> str:
        return FUNCTION_LABELS.get(self.function, "Not known")

    @property
    def is_working(self) -> bool:
        """True only when something says so. ``unknown`` is not a yes."""
        return self.function == "functional"

    @property
    def overdue(self) -> tuple[DueItem, ...]:
        return tuple(item for item in self.due if item.state == "overdue")

    def as_dict(self) -> dict:
        return {
            "function": self.function, "label": self.label,
            "since": self.since.isoformat() if self.since else None,
            "detail": self.detail,
            "last_inspection": self.last_inspection.isoformat()
            if self.last_inspection else None,
            "last_sample": self.last_sample.isoformat()
            if self.last_sample else None,
            "commissioned": self.commissioned.isoformat()
            if self.commissioned else None,
            "days_out_of_service": self.days_out_of_service,
            "due": [item.as_dict() for item in self.due],
            "undated_events": self.undated_events,
        }


def _add_months(start: date, months: int) -> date:
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    # clamp rather than roll over: six months from 31 August is 28 February,
    # not 3 March, and a due date that drifts forward is one that gets missed
    day = min(start.day, [31, 29 if year % 4 == 0 and (year % 100 or not
                                                       year % 400) else 28,
                          31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def asset_state(asset: Asset, today: date | None = None,
                schedule: Schedule | None = None) -> AssetState:
    """Reduce the event stream to the borehole's condition on ``today``."""
    today = today or date.today()
    schedule = schedule or Schedule()
    events = merge_events(asset.asset_id, asset.events)
    dated = [(e.date, e) for e in events if e.date is not None]
    dated.sort(key=lambda pair: (pair[0], pair[1].kind, pair[1].event_id))
    undated = sum(1 for e in events if e.date is None)

    function, since, detail = "unknown", None, (
        "Nothing has been recorded against this borehole, so whether it is "
        "working is not known.")
    commissioned = last_inspection = last_sample = None
    for when, event in dated:
        if when > today:
            continue  # a record dated in the future settles nothing yet
        establishes = EVENT_KINDS.get(event.kind, ("", None, False))[1]
        if establishes:
            function, since = establishes, when
            detail = f"{event.label} recorded on {when.isoformat()}"
            if event.by:
                detail += f" by {event.by}"
        if event.kind == "commissioned" and commissioned is None:
            commissioned = when
        if event.kind == "inspection":
            last_inspection = when
        if event.kind == "water_sample":
            last_sample = when

    out_for = ((today - since).days
               if function == "non_functional" and since else None)
    if undated and function == "unknown":
        detail = (f"{undated} record(s) carry a date nobody can read, so "
                  "nothing can be established from them.")

    due: list[DueItem] = []
    if function != "decommissioned":
        due.append(_due_item(
            "inspection", "Sanitary inspection", last_inspection, commissioned,
            schedule.inspection_months, schedule.grace_days, today,
            "A sanitary inspection is what catches a cracked apron or a "
            "latrine dug uphill before the water shows it."))
        due.append(_due_item(
            "water_sample", "Water quality sample", last_sample, commissioned,
            schedule.water_sample_months, schedule.grace_days, today,
            "Water that was safe at handover is not evidence that it is safe "
            "now: the aquifer, the headworks and the catchment all change."))
    return AssetState(
        function=function, since=since, detail=detail,
        last_inspection=last_inspection, last_sample=last_sample,
        commissioned=commissioned, days_out_of_service=out_for,
        due=tuple(item for item in due if item is not None),
        undated_events=undated,
    )


def _due_item(key: str, title: str, last: date | None, commissioned: date | None,
              months: int, grace_days: int, today: date, why: str) -> DueItem:
    anchor = last or commissioned
    if anchor is None:
        return DueItem(key, title, None, "unknown",
                       f"No {title.lower()} has been recorded, and there is no "
                       f"commissioning date to count from. {why}")
    due_on = _add_months(anchor, months)
    if today > due_on + timedelta(days=grace_days):
        overdue_by = (today - due_on).days
        never = "" if last else "has never been done; it "
        return DueItem(key, title, due_on, "overdue",
                       f"{title} {never}has been due since "
                       f"{due_on.isoformat()}, {overdue_by} days ago. {why}")
    if today > due_on:
        return DueItem(key, title, due_on, "due",
                       f"{title} fell due on {due_on.isoformat()}.")
    return DueItem(key, title, due_on, "scheduled",
                   f"Next {title.lower()} due {due_on.isoformat()}.")


# ---------------------------------------------------------------------------
# What goes on the borehole itself
# ---------------------------------------------------------------------------

def qr_payload(asset: Asset) -> str:
    """The text the QR code carries.

    Plain text rather than a link. A link is only useful where there is a
    network, and the whole reason this symbol is on the headworks is that
    there is not one - a technician who scans it should see the identifier,
    the place and the position on the screen immediately, with nothing to
    load and nothing to install.
    """
    lines = [f"BOREHOLE {asset.asset_id}", asset.label]
    latlon = asset.latlon
    if latlon is not None:
        lat, lon = latlon
        lines.append(f"{abs(lat):.5f} {'N' if lat >= 0 else 'S'}, "
                     f"{abs(lon):.5f} {'E' if lon >= 0 else 'W'}")
    facts = []
    if asset.total_depth_m:
        facts.append(f"{float(asset.total_depth_m):.1f} m deep")
    if asset.safe_yield_m3_per_h:
        facts.append(f"{float(asset.safe_yield_m3_per_h):.2f} m3/h")
    if asset.pump_type:
        facts.append(asset.pump_type)
    if facts:
        lines.append(", ".join(facts))
    return "\n".join(lines)


def placard_lines(asset: Asset, state: AssetState | None = None) -> list[tuple[str, str]]:
    """Field-value rows for the plate that gets fixed to the headworks."""
    rows = [("Identifier", asset.asset_id), ("Community", asset.community or "-")]
    if asset.district:
        rows.append(("District", asset.district))
    latlon = asset.latlon
    if latlon is not None:
        rows.append(("Position", f"{latlon[0]:.5f} N, {abs(latlon[1]):.5f} W"))
    if asset.total_depth_m:
        rows.append(("Depth", f"{float(asset.total_depth_m):.1f} m"))
    if asset.safe_yield_m3_per_h:
        rows.append(("Safe yield", f"{float(asset.safe_yield_m3_per_h):.2f} m3/h"))
    if asset.pump_type:
        rows.append(("Pump", asset.pump_type))
    if asset.installed_by:
        rows.append(("Installed by", asset.installed_by))
    if state is not None:
        if state.commissioned:
            rows.append(("Commissioned", state.commissioned.isoformat()))
        rows.append(("Status", state.label))
    return rows


# ---------------------------------------------------------------------------
# Many of them
# ---------------------------------------------------------------------------

def registry_rows(assets, today: date | None = None,
                  schedule: Schedule | None = None) -> list[dict]:
    """One formatted row per asset, for the registry table."""
    today = today or date.today()
    rows = []
    for asset in assets:
        state = asset_state(asset, today, schedule)
        overdue = state.overdue
        rows.append({
            "Identifier": asset.asset_id,
            "Community": asset.community or "(unnamed)",
            "District": asset.district or "",
            "Status": state.label,
            "Since": state.since.isoformat() if state.since else "",
            "Last inspected": state.last_inspection.isoformat()
            if state.last_inspection else "",
            "Last sampled": state.last_sample.isoformat()
            if state.last_sample else "",
            "Overdue": ", ".join(item.title for item in overdue),
            "Events": len(asset.events),
        })
    return rows


def registry_stats(assets, today: date | None = None,
                   schedule: Schedule | None = None) -> dict:
    """Headline counts.

    ``n_unknown`` is reported beside the working and broken counts and never
    folded into either. A register where most points are unknown looks very
    like one where most points are working, unless the number is on the
    page next to them.
    """
    today = today or date.today()
    assets = list(assets)
    counts = {key: 0 for key in FUNCTION_LABELS}
    overdue_by_key: dict[str, int] = {}
    out_days = []
    for asset in assets:
        state = asset_state(asset, today, schedule)
        counts[state.function] = counts.get(state.function, 0) + 1
        if state.days_out_of_service is not None:
            out_days.append(state.days_out_of_service)
        for item in state.overdue:
            overdue_by_key[item.key] = overdue_by_key.get(item.key, 0) + 1
    known = counts["functional"] + counts["non_functional"]
    return {
        "n_assets": len(assets),
        "n_functional": counts["functional"],
        "n_non_functional": counts["non_functional"],
        "n_decommissioned": counts["decommissioned"],
        "n_unknown": counts["unknown"],
        # over the points whose condition is actually known, and None when
        # none of them are - a functionality rate computed over silence is
        # the number that makes these registers untrustworthy
        "functionality_rate": (counts["functional"] / known * 100.0)
        if known else None,
        "n_overdue_inspection": overdue_by_key.get("inspection", 0),
        "n_overdue_sample": overdue_by_key.get("water_sample", 0),
        "mean_days_out_of_service": (sum(out_days) / len(out_days))
        if out_days else None,
    }
