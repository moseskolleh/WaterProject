"""The field kit: printed sheets and quick cards for a crew with no device.

PLAN.md step 2.5. The co-pilots of steps 2.1 and 2.2 run on a phone, and
many crews do not carry one that can. This module works out what goes on
paper for them, in a form both engines build the same way (``fieldKit`` in
``docs/js/gwt-core.js`` is its port, held to it by the parity suite):

- a **pumping test sheet for each borehole**, pre-filled with the site and
  the borehole identifier, the reading schedule in the Time column and the
  casing-storage time the pump must outlast. Its tables have the columns of
  the standard pumping test workbook (``ingestion.templates``), so a filled
  sheet is typed into the template the readers take, cell for cell
  (PLAN.md rule 6);
- three **quick cards** to laminate: the pumping schedule, the VES
  spacings, and the chlorine doses for disinfecting a borehole.

The schedules are the co-pilots' own. They are written once, in
``data/field.yaml``, which the co-pilots, this module and the browser's
port all read. The casing-storage time is the engine's
:func:`~groundwater.hydraulics.analysis.casing_storage_min` at the same
cautious transmissivity the pumping co-pilot offers before pumping, and
the doses are :func:`~groundwater.supervision.field_checks.disinfection_dose`.

The sheet code
--------------

Each sheet carries a QR code, so that a photographed sheet can be matched
to its project when it is read back (step 10.1). The code is one line of
text, four fields separated by ``|``::

    GWT-FK/1|pumping|<project>|<borehole>

1. ``GWT-FK/1``: the format and its version. A reader takes only versions
   it knows, and a later version may add fields after the fourth.
2. The sheet: ``pumping`` is the pumping test sheet, the one sheet the kit
   prints today.
3. The project: its reference if one is set, else its name (in the
   Streamlit app, which has no reference field, its name). Empty when the
   project has neither; the sheet then says it cannot be matched.
4. The borehole identifier, as the sheet's "Borehole Ref. No." prints it.

In the project and borehole fields, each run of spaces, tabs and line
breaks becomes one space and the ends are trimmed of it (of nothing else:
a byte-order mark or a Unicode space is kept, as it is everywhere inside
the field); then ``%`` is written
``%25`` and ``|`` is written ``%7C``, so no field can contain the
separator. Nothing else is escaped: the text is UTF-8, as the QR symbol's
byte mode carries it. The symbol is printed at error-correction level H,
like the headworks plate, and the code is also printed under it, so a
symbol that will not scan can be typed in. At level H, version 10 holds
122 bytes; a code longer than that is refused rather than cut short.
"""

from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass
from typing import Any, TypeGuard

import yaml

from ._resources import bundled_text
from .config import Config, PumpingConfig, VESConfig
from .hydraulics.analysis import casing_storage_min
from .ingestion.templates import (
    PUMPING_COLUMNS,
    PUMPING_DISCHARGE_LABEL,
    PUMPING_HEADER,
    RECOVERY_COLUMNS,
)
from .models import SiteMetadata
from .reporting.citations import references_for
from .supervision.field_checks import disinfection_dose
from .text import phrase, render_text
from .ves.interpret import depth_of_investigation

__all__ = [
    "PAYLOAD_FORMAT",
    "PayloadFields",
    "airlift_yield",
    "cautious_storage",
    "field_kit_content",
    "field_kit_payload",
    "field_schedules",
    "parse_field_kit_payload",
    "project_identifier",
    "reading_minutes",
    "ves_survey_plan",
]

#: The sheet code's format and version, its first field.
PAYLOAD_FORMAT = "GWT-FK/1"

#: The one sheet the kit prints, named in the code's second field.
PUMPING_SHEET = "pumping"

# The whitespace a field's runs collapse over, and the only whitespace a
# field or a code is trimmed of: written out rather than \s, str.strip() or
# String.trim(), which Python and JavaScript read as different sets (a
# byte-order mark, U+0085 and U+001C to U+001F), and gave the two engines
# different codes for the same name.
_SPACE = re.compile(r"[ \t\n\r\f\v]+")
_SPACE_CHARS = " \t\n\r\f\v"
_ESCAPED = re.compile(r"%(25|7C)")


@functools.lru_cache(maxsize=1)
def field_schedules() -> dict:
    """``data/field.yaml``: the schedules and field rules, shared.

    Parsed once and held; treat it as read-only.
    """
    return yaml.safe_load(bundled_text("field.yaml"))


# --------------------------------------------------------------- the schedule

def reading_minutes(until_min: float) -> list[float]:
    """The scheduled reading minutes up to and including ``until_min``.

    The log-spaced list, then every ``late_every_min`` after its last
    minute: the pumping co-pilot's ``nextSlot`` laid out as a column.
    """
    pumping = field_schedules()["pumping"]
    schedule = pumping["schedule_min"]
    out = [m for m in schedule if m <= until_min + 1e-9]
    late = schedule[-1] + pumping["late_every_min"]
    while late <= until_min + 1e-9:
        out.append(late)
        late += pumping["late_every_min"]
    return out


def _first_reading_at_or_after(minutes: float) -> float:
    """The scheduled minute a test of ``minutes`` reads last."""
    pumping = field_schedules()["pumping"]
    for m in pumping["schedule_min"]:
        if m >= minutes - 1e-9:
            return m
    last, every = pumping["schedule_min"][-1], pumping["late_every_min"]
    return last + every * math.ceil((minutes - last) / every - 1e-9)


def cautious_storage(config: PumpingConfig | None = None) -> dict:
    """Schafer's casing-storage time at the cautious transmissivity range.

    The pumping co-pilot's figure before pumping: each end of the range
    turned into a specific capacity by Logan's factor and handed to
    :func:`casing_storage_min`. ``low_t_min`` is the time at the low end of
    the range, the longer one, and the one the advice rests on. None where
    the casing leaves no annulus to store water in.
    """
    config = config or PumpingConfig()
    pumping = field_schedules()["pumping"]
    t_low, t_high = pumping["cautious_t_m2_per_day"]
    logan = pumping["logan_factor"]

    def storage(t: float) -> float | None:
        return casing_storage_min(t / (logan * 24), config)

    return {
        "casing_in": config.casing_diameter_in, "riser_in": config.riser_diameter_in,
        "t_low": t_low, "t_high": t_high,
        "low_t_min": storage(t_low), "high_t_min": storage(t_high),
    }


def ves_survey_plan(target_m: float, config: VESConfig | None = None) -> dict:
    """The AB/2 series and the MN changes that reach ``target_m``.

    The VES co-pilot's proposal (step 2.2), which reads it from here in the
    browser. The largest AB/2 is the first spacing in the series at which
    the depth of investigation reaches the target. MN starts at the widest
    spacing a ``min_ab_per_mn`` share of the first AB allows and is widened
    when AB passes ``max_ab_per_mn`` times it; at each change the last AB/2
    is read again with the new MN, so the two segments overlap at one
    spacing. ``capped`` says the longest spacing in the series still falls
    short of the target.
    """
    config = config or VESConfig()
    ves = field_schedules()["ves"]
    series_all = ves["ab2_series_m"]
    mn_series = ves["mn_series_m"]

    # the engine's own rule decides, not target / factor: a factor that is
    # not a power of two divides with a rounding error
    def reaches(ab2: float) -> bool:
        return depth_of_investigation(ab2, config) >= target_m

    capped = not reaches(series_all[-1])
    series: list[float] = []
    for ab2 in series_all:
        series.append(ab2)
        if reaches(ab2):
            break

    def widest(ab2: float) -> float:
        best = None
        for mn in mn_series:
            if mn * ves["min_ab_per_mn"] <= 2 * ab2:
                best = mn
        return mn_series[0] if best is None else best

    steps: list[dict] = []
    mn = widest(series[0])
    for k, ab2 in enumerate(series):
        if k > 0 and 2 * ab2 > ves["max_ab_per_mn"] * mn:
            wider = widest(series[k - 1])
            if wider > mn:
                mn = wider
                steps.append({"ab2": series[k - 1], "mn": mn})
        steps.append({"ab2": ab2, "mn": mn})
    max_ab2 = series[-1]
    return {
        "target_m": target_m, "factor": config.depth_of_investigation_factor,
        "max_ab2": max_ab2, "investigation_m": depth_of_investigation(max_ab2, config),
        "line_m": 2 * max_ab2, "capped": capped, "steps": steps,
    }


# ------------------------------------------------------------ airlift yield

#: Standard gravity, m/s2, in the V-notch equation.
_GRAVITY = 9.80665


def _positive(value: float | None) -> TypeGuard[float]:
    return value is not None and math.isfinite(value) and value > 0


def airlift_yield(method: str, *, volume_l: float | None = None,
                  timings_s: list[float] | None = None, head_mm: float | None = None,
                  reason: str = "") -> dict:
    """The airlift yield of a water strike, in litres per second.

    The drilling log co-pilot's estimate (step 2.3), which reads it from here
    in the browser (``C.airliftYield``). ``method`` is how it was measured:

    - ``"bucket"``: a container of ``volume_l`` litres timed filling, once
      or more (``timings_s``); the yield is the volume over the mean time;
    - ``"vnotch"``: the head over a V-notch plate on the discharge, in mm,
      read by the Kindsvater-Shen equation with the angle and coefficient in
      ``data/field.yaml``;
    - ``"none"``: not measured, for the ``reason`` given.

    Returns ``{"method", "q_l_per_s", "basis", "flags"}``: the yield (None
    when not measured), the sentence the sheets print for how it was got,
    and ``{"code", "message"}`` for a reading outside the range the method
    holds for. An estimate during drilling, not a pumping test: the air
    lifts the water and the well has not been developed. A reading that
    cannot give a yield (no volume, a time of zero, no reason) raises
    ``ValueError``.
    """
    flags: list[dict] = []
    if method == "bucket":
        times = [float(t) for t in (timings_s or [])]
        # each reading a finite number above zero: min() let a NaN timing
        # through to a NaN yield, which the browser refused, and an infinite
        # time gave a yield of zero
        if (not _positive(volume_l) or not times
                or not all(_positive(t) for t in times)):
            raise ValueError("a timed container needs its volume and at least one "
                             "time, each more than zero")
        mean = sum(times) / len(times)
        q = float(volume_l) / mean
        basis = phrase("drilling_copilot.airlift_bucket",
                       volume=float(volume_l), mean=mean, n=len(times))
    elif method == "vnotch":
        if not _positive(head_mm):
            raise ValueError("a V-notch reading needs the head over the notch, "
                             "more than zero")
        drilling = field_schedules()["drilling"]
        angle = drilling["vnotch_angle_deg"]
        ce = drilling["vnotch_discharge_coefficient"]
        low, high = drilling["vnotch_head_range_mm"]
        h = float(head_mm) / 1000.0
        q = (ce * 8.0 / 15.0 * math.sqrt(2.0 * _GRAVITY)
             * math.tan(math.radians(angle / 2.0)) * h ** 2.5 * 1000.0)
        basis = phrase("drilling_copilot.airlift_vnotch", angle=angle,
                       head=float(head_mm), ce=ce, half=angle / 2.0)
        if not low <= head_mm <= high:
            flags.append({"code": "vnotch_head_outside", "message": phrase(
                "drilling_copilot.vnotch_outside", head=float(head_mm), low=low, high=high)})
    elif method == "none":
        text = _SPACE.sub(" ", str(reason or "")).strip(_SPACE_CHARS)
        if not text:
            raise ValueError("an airlift not measured needs the reason")
        return {"method": "none", "q_l_per_s": None,
                "basis": phrase("drilling_copilot.airlift_not_measured", reason=text),
                "flags": flags}
    else:
        raise ValueError(f"unknown airlift method {method!r}")
    return {"method": method, "q_l_per_s": q, "basis": basis, "flags": flags}


# ------------------------------------------------------------- the sheet code

def _clean_field(text: Any) -> str:
    return _SPACE.sub(" ", "" if text is None else str(text)).strip(" ")


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("|", "%7C")


def _unescape(text: str) -> str:
    return _ESCAPED.sub(lambda m: "%" if m.group(1) == "25" else "|", text)


def field_kit_payload(project: str, borehole: str, sheet: str = PUMPING_SHEET) -> str:
    """The text a sheet's QR code carries (the format is in the module notes)."""
    return "|".join((PAYLOAD_FORMAT, sheet, _escape(_clean_field(project)),
                     _escape(_clean_field(borehole))))


@dataclass(frozen=True)
class PayloadFields:
    """What a sheet code says."""

    format: str
    sheet: str
    project: str
    borehole: str


def parse_field_kit_payload(text: str) -> PayloadFields | None:
    """The fields of a sheet code, or None for text that is not one.

    Only version 1 is read; a code of a later version is not guessed at.
    """
    parts = str(text).strip(_SPACE_CHARS).split("|")
    if len(parts) != 4 or parts[0] != PAYLOAD_FORMAT or not parts[1]:
        return None
    return PayloadFields(parts[0], parts[1], _unescape(parts[2]), _unescape(parts[3]))


def project_identifier(site: SiteMetadata) -> str:
    """The project as a sheet code names it: its reference, else its name."""
    return _clean_field(site.project_ref) or _clean_field(site.project)


# ------------------------------------------------------------------- the kit

def _g(value: float) -> str:
    return render_text("{v:g}", {"v": value})


def _block_of(minute: float) -> int:
    # the co-pilot's hourly blocks: a reading belongs to the block whose
    # heading starts at or before it
    return 0 if minute < 61 else 1 if minute < 121 else 2 if minute < 181 else 3


def _pumping_blocks(minutes: list[float], planned: float) -> list[dict]:
    last = max(240, math.ceil(planned))
    headings = ["Constant discharge 0-60 min", "Constant discharge 61-120 min",
                "Constant discharge 121-180 min", f"Constant discharge 181-{last} min"]
    groups: list[list[float]] = [[], [], [], []]
    for m in minutes:
        groups[_block_of(m)].append(m)
    return [{"caption": headings[i], "header": list(PUMPING_COLUMNS),
             "rows": [[_g(m), "", ""] for m in group]}
            for i, group in enumerate(groups) if group]


def _sheet(site: SiteMetadata, project: str, borehole: str, plan: dict,
           notes: list[str]) -> dict:
    payload = field_kit_payload(project, borehole)
    values = {
        "Community": site.community, "Client": site.client,
        "Test conducted by": site.supervisor, "Borehole Ref. No.": borehole,
        "Test type (step or constant)": "constant", "District": site.district,
    }
    header = [[label, _clean_field(values.get(label, ""))]
              for _, label, _ in PUMPING_HEADER]
    minutes = reading_minutes(plan["planned_min"])
    return {
        "borehole": borehole,
        "payload": payload,
        "title": phrase("field_kit.sheet_title", borehole=borehole),
        "code": phrase("field_kit.sheet_code", payload=payload),
        "warning": "" if project else phrase("field_kit.no_project"),
        "header": header,
        "notes": notes,
        "discharge_note": phrase("field_kit.discharge"),
        "discharge": {
            "caption": PUMPING_DISCHARGE_LABEL,
            "header": [f"Step {i} Q" for i in range(1, 5)],
            "rows": [["", "", "", ""]],
        },
        "bucket": {
            "caption": "Bucket timings",
            "header": ["Step", "Bucket (L)", "Timing 1 (s)", "Timing 2 (s)",
                       "Timing 3 (s)", "Q (m3/h)"],
            "rows": [[f"Step {i}", "", "", "", "", ""] for i in range(1, 5)],
        },
        "transcribe": phrase("field_kit.transcribe"),
        "blocks": _pumping_blocks(minutes, plan["planned_min"]),
        "recovery": {"caption": "Recovery", "header": list(RECOVERY_COLUMNS),
                     "rows": [[_g(m), "", ""] for m in minutes]},
    }


def _plan(config: PumpingConfig) -> dict:
    storage = cautious_storage(config)
    low = storage["low_t_min"]
    constant = max(config.min_constant_test_min, low or 0.0)
    return {
        "storage": storage,
        "constant_min": constant,
        "first_step_min": max(config.min_step_length_min, low or 0.0),
        "step_min": config.min_step_length_min,
        "planned_min": _first_reading_at_or_after(constant),
    }


def _pumping_notes(plan: dict, config: PumpingConfig) -> dict[str, str]:
    """The sheet's sentences, by name, in the order the sheet prints them."""
    storage = plan["storage"]
    pumping = field_schedules()["pumping"]
    notes = {}
    if storage["low_t_min"] is not None and storage["high_t_min"] is not None:
        notes["storage"] = phrase(
            "field_kit.storage", casing=storage["casing_in"], riser=storage["riser_in"],
            low=storage["low_t_min"], t_low=storage["t_low"],
            high=storage["high_t_min"], t_high=storage["t_high"])
        notes["stop_constant"] = phrase(
            "field_kit.stop_constant", minutes=plan["constant_min"],
            min_test=config.min_constant_test_min)
    else:
        # a riser as wide as the casing leaves nothing to store
        notes["stop_constant"] = phrase("field_kit.stop_constant_no_storage",
                                        minutes=plan["constant_min"])
    notes["stop_step"] = phrase("field_kit.stop_step", step=plan["step_min"],
                                first=plan["first_step_min"])
    notes["storage_measured"] = phrase("field_kit.storage_measured")
    notes["schedule"] = phrase("field_kit.schedule", last=pumping["schedule_min"][-1],
                               every=pumping["late_every_min"])
    notes["recovery"] = phrase("field_kit.recovery")
    return notes


def _pumping_card(notes: dict[str, str]) -> dict:
    pumping = field_schedules()["pumping"]
    schedule = [_g(m) for m in pumping["schedule_min"]]
    # seven to a row, so the card stays one card
    rows = [(schedule[i:i + 7] + [""] * 7)[:7] for i in range(0, len(schedule), 7)]
    return {
        "key": "pumping",
        "title": phrase("field_kit.card_pumping_title"),
        "lines": [phrase("field_kit.card_pumping_schedule",
                         every=pumping["late_every_min"]), notes["recovery"]],
        "tables": [{"caption": "Reading minutes", "header": [], "rows": rows}],
        # the sheet's own advice, less the sentences about its Time column
        "notes": [text for key, text in notes.items()
                  if key not in ("schedule", "recovery")],
    }


def _ves_card(config: VESConfig) -> dict:
    ves = field_schedules()["ves"]
    plan = ves_survey_plan(depth_of_investigation(ves["ab2_series_m"][-1], config), config)
    rows = [[str(k + 1), _g(s["ab2"]), _g(s["mn"]),
             _g(depth_of_investigation(s["ab2"], config))]
            for k, s in enumerate(plan["steps"])]
    return {
        "key": "ves",
        "title": phrase("field_kit.card_ves_title"),
        "lines": [phrase("field_kit.card_ves_rule", factor=plan["factor"]),
                  phrase("field_kit.card_ves_mn", min_ratio=ves["min_ab_per_mn"],
                         max_ratio=ves["max_ab_per_mn"])],
        "tables": [{"caption": "Schlumberger spacings",
                    "header": ["No.", "AB/2 (m)", "MN (m)", "Depth reached (m)"],
                    "rows": rows}],
        "notes": [],
    }


def _dose_card() -> dict:
    grid = field_schedules()["disinfection_card"]
    header = ["Water column (m)"]
    for d in grid["casing_id_mm"]:
        header += [f"{_g(d)} mm: L", f"{_g(d)} mm: g"]
    rows = []
    hours = grams_per_litre = None
    for column in grid["water_column_m"]:
        row = [_g(column)]
        for d in grid["casing_id_mm"]:
            dose = disinfection_dose(column, d)
            hours = dose.contact_hours
            grams_per_litre = dose.hth_grams / dose.solution_02pct_l
            row += [render_text("{v:.1f}", {"v": dose.solution_02pct_l}),
                    render_text("{v:.0f}", {"v": dose.hth_grams})]
        rows.append(row)
    return {
        "key": "disinfection",
        "title": phrase("field_kit.card_dose_title"),
        "lines": [phrase("field_kit.card_dose_rule", hours=hours),
                  phrase("field_kit.card_dose_solution", grams=grams_per_litre),
                  phrase("field_kit.card_dose_volume")],
        "tables": [{"caption": phrase("field_kit.card_dose_table"), "header": header,
                    "rows": rows}],
        "notes": [phrase("field_kit.card_dose_basis")],
    }


def field_kit_content(site: SiteMetadata, boreholes: list[str],
                      config: Config | None = None) -> dict:
    """Everything the field kit prints, as plain data.

    One pumping test sheet for each borehole named (blank names dropped,
    repeats printed once) and the three quick cards. Both engines return
    the same structure, which the two document writers lay out.
    """
    config = config or Config()
    project = project_identifier(site)
    names: list[str] = []
    for name in boreholes:
        cleaned = _clean_field(name)
        if cleaned and cleaned not in names:
            names.append(cleaned)
    plan = _plan(config.pumping)
    notes = _pumping_notes(plan, config.pumping)
    return {
        "format": PAYLOAD_FORMAT,
        "project": project,
        "title": phrase("field_kit.title", name=project or _clean_field(site.community)
                        or "unnamed project"),
        "storage": plan["storage"],
        "constant_min": plan["constant_min"],
        "first_step_min": plan["first_step_min"],
        "planned_min": plan["planned_min"],
        "sheets": [_sheet(site, project, name, plan, list(notes.values()))
                   for name in names],
        "cards": [_pumping_card(notes), _ves_card(config.ves), _dose_card()],
        "references": references_for("field_kit"),
    }
