"""When in the year the test was run, and what the borehole will do later.

A pumping test measures one day. The borehole has to supply a village on
the worst day, and in Sierra Leone those are months apart: a single wet
season from about June to October recharges the aquifer, the water table
peaks around the end of it, and it falls through the dry season to an
annual low in April or May. A test run in August sits on a static level the
borehole will not see again until the following August.

The toolkit already reserved a fixed allowance for that decline before
computing the usable drawdown. A fixed allowance is right for exactly one
month of the year. Applied to a test run in April it takes two metres of
drawdown that has already been spent, and understates a yield the borehole
has demonstrably got; applied to a test run in September it is the whole
story and may not be enough. So this module puts the test in the year and
computes the decline still to come, then reports the yield under named
scenarios instead of one number resting on a hidden assumption.

**What is assumed, and what is measured.** The shape of the year - which
months are high and which are low - is well established for a single-wet-
season climate and is stated here as a table anyone can read and argue
with. The *size* of the annual range is not: it varies with the aquifer,
the catchment and the year, and a single test cannot measure it. It is
therefore a parameter, defaulting to the configured allowance, and every
scenario says which range it used and where that came from.

**The month has to be known.** A date written 10/05/2018 is 10 May under
one convention and 5 October under the other - opposite ends of the year,
and opposite answers. An ambiguous date is treated as no date at all: the
season is unknown, the full range is reserved because that is the
conservative reading, and the report says why rather than quietly picking
one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Optional

from .config import PumpingConfig

__all__ = [
    "MONTH_NAMES",
    "SCENARIOS",
    "SEASONAL_POSITION",
    "SeasonalScenario",
    "SeasonalYield",
    "month_of",
    "season_of",
    "seasonal_yield",
]

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]

#: Where the water table sits in the annual cycle, by month: 0.0 at the
#: annual high, 1.0 at the annual low. A single wet season from June to
#: October fills the aquifer; levels peak at the end of it and recede
#: through the dry season to a low in April and May, just before the rains
#: return. The shape is the standard one for this climate; the size of the
#: swing is not stated here, because that is a property of the aquifer and
#: is carried separately.
SEASONAL_POSITION = {
    1: 0.35,   # January - two months into the recession
    2: 0.55,
    3: 0.75,
    4: 0.95,   # April - the low, or within a few weeks of it
    5: 1.00,   # May - the driest the borehole will be
    6: 0.80,   # the rains have started but the table lags them
    7: 0.45,
    8: 0.15,
    9: 0.00,   # September - fully recovered
    10: 0.05,  # October - the rains end, the recession has barely begun
    11: 0.15,
    12: 0.25,
}

#: Which part of the year a month belongs to, for plain-language reporting.
_SEASON_OF_MONTH = {
    1: "dry season", 2: "dry season", 3: "late dry season",
    4: "late dry season", 5: "late dry season", 6: "early wet season",
    7: "wet season", 8: "wet season", 9: "wet season",
    10: "late wet season", 11: "early dry season", 12: "dry season",
}

#: The scenarios a design is judged against. ``factor`` multiplies the
#: annual range: 0 is the level on the day of the test, 1 is the normal
#: annual low, and the drought case allows for the low being deeper in a
#: run of poor years than in an average one.
SCENARIOS = {
    "as_tested": (
        "As tested", 0.0,
        ("The level on the day of the test. Not a design figure: unless the "
        "test was run at the end of the dry season the borehole will be "
        "lower than this for part of every year."),
    ),
    "dry_season": (
        "End of dry season", 1.0,
        ("The normal annual low, which the borehole reaches every year. This "
        "is the figure a design should be sized on."),
    ),
    "drought": (
        "Drought year", 1.5,
        ("A low deeper than a normal year's, for a run of poor rains. The "
        "pump has to still be under water here, or the village loses the "
        "borehole in exactly the year it is needed most."),
    ),
}


def month_of(text) -> tuple[int | None, str]:
    """``(month, why)`` for a date as written on a field sheet.

    ``month`` is ``None`` whenever the answer would be a guess, and ``why``
    says what stopped it - the wording goes into the report, because the
    fix is somebody writing the date less ambiguously next time.
    """
    raw = str(text or "").strip()
    if not raw:
        return None, "No date is recorded for the test."

    # A month written by name settles it wherever it sits in the text. Only
    # the first word used to be looked at, so "Wed 25/04/2018" and
    # "Date: 14/09/2018" - both perfectly clear - were reported as naming
    # no month at all.
    words = re.findall(r"[A-Za-z]{3,}", raw)
    for word in words:
        head = word.lower()[:3]
        for index, month in enumerate(MONTH_NAMES, start=1):
            if month.lower().startswith(head):
                return index, ""

    parts = [int(p) for p in re.findall(r"\d+", raw)]
    if len(parts) < 3:
        if words:
            return None, f"The date {raw!r} does not name a month."
        return None, f"The date {raw!r} is not a full date."

    # An ISO date is unambiguous: a four-digit year can only be the year.
    if parts[0] > 31:
        month = parts[1]
        return (month, "") if 1 <= month <= 12 else (
            None, f"The date {raw!r} has no month in it.")

    first, second = parts[0], parts[1]
    if first > 12 and 1 <= second <= 12:
        return second, ""                      # 25/04/2018 - only one reading
    if second > 12 and 1 <= first <= 12:
        return first, ""                       # 04/25/2018 - likewise
    if 1 <= first <= 12 and 1 <= second <= 12:
        return None, (
            f"The date {raw!r} could be read either way round: "
            f"{MONTH_NAMES[second - 1]} or {MONTH_NAMES[first - 1]}. Those are "
            "different ends of the year and give different answers, so the "
            "season is treated as unknown. Record the month by name, or pick "
            "it below.")
    return None, f"The date {raw!r} has no month in it."


def season_of(month: int | None) -> str:
    """Plain language for a month, or "unknown" when there is no month."""
    if not month or month not in _SEASON_OF_MONTH:
        return "unknown"
    return _SEASON_OF_MONTH[month]


def _decline_to_come(month: int | None, annual_range_m: float,
                     factor: float) -> float:
    """Metres the water table still has to fall from the tested level.

    With no month the whole range is reserved. That is the conservative
    reading and it is what the toolkit did before this module existed - the
    difference is that now it is a stated fallback rather than the only
    behaviour.
    """
    if month is None:
        position = 0.0
    else:
        position = SEASONAL_POSITION.get(month, 0.0)
    # never negative: a test at the annual low needs no further allowance,
    # and a scenario shallower than the tested level is not a scenario
    return max(annual_range_m * (factor - position), 0.0)


@dataclass(frozen=True)
class SeasonalScenario:
    key: str
    title: str
    decline_m: float
    static_water_level_m: Optional[float]
    available_drawdown_m: Optional[float]
    safe_yield_m3_per_h: Optional[float]
    pump_installation_depth_m: Optional[float]
    note: str

    def as_dict(self) -> dict:
        return {
            "key": self.key, "title": self.title,
            "decline_m": self.decline_m,
            "static_water_level_m": self.static_water_level_m,
            "available_drawdown_m": self.available_drawdown_m,
            "safe_yield_m3_per_h": self.safe_yield_m3_per_h,
            "pump_installation_depth_m": self.pump_installation_depth_m,
            "note": self.note,
        }


@dataclass
class SeasonalYield:
    """The yield under each scenario, and what a design should be sized on."""

    month: Optional[int]
    season: str
    month_note: str
    annual_range_m: float
    range_source: str
    scenarios: list[SeasonalScenario]
    pending_reason: str = ""

    def scenario(self, key: str) -> Optional[SeasonalScenario]:
        for item in self.scenarios:
            if item.key == key:
                return item
        return None

    @property
    def is_established(self) -> bool:
        design = self.scenario("dry_season")
        return design is not None and design.safe_yield_m3_per_h is not None

    @property
    def design_yield_m3_per_h(self) -> Optional[float]:
        """What to size on: the normal annual low, not the day of the test."""
        design = self.scenario("dry_season")
        return design.safe_yield_m3_per_h if design else None

    @property
    def pump_installation_depth_m(self) -> Optional[float]:
        """Deep enough for the worst scenario, because the pump is fitted once."""
        depths = [s.pump_installation_depth_m for s in self.scenarios
                  if s.pump_installation_depth_m is not None]
        return max(depths) if depths else None

    @property
    def dry_season_loss_percent(self) -> Optional[float]:
        """How much of the tested yield the dry season takes away."""
        tested = self.scenario("as_tested")
        design = self.scenario("dry_season")
        if not tested or not design:
            return None
        if not tested.safe_yield_m3_per_h:
            return None
        if design.safe_yield_m3_per_h is None:
            # the dry season takes all of it: the pump is dry at the annual low
            return 100.0
        return (1.0 - design.safe_yield_m3_per_h
                / tested.safe_yield_m3_per_h) * 100.0

    @property
    def summary(self) -> str:
        if self.pending_reason:
            return self.pending_reason
        tested = self.scenario("as_tested")
        design = self.scenario("dry_season")
        drought = self.scenario("drought")
        if design is None:
            return "The seasonal yield could not be established."
        if design.safe_yield_m3_per_h is None:
            # Not "could not be established": it was, and the answer is that
            # the pump runs dry before the annual low is reached.
            text = ("No yield at the end of the dry season: the pump would be "
                    "dry at the dry-season low")
            if tested and tested.safe_yield_m3_per_h is not None:
                text += (f" (the test itself gave "
                         f"{tested.safe_yield_m3_per_h:.2g} m3/h)")
        else:
            text = (f"Sized on the end of the dry season: "
                    f"{design.safe_yield_m3_per_h:.2g} m3/h")
            if drought and drought.safe_yield_m3_per_h is not None:
                text += (f", falling to {drought.safe_yield_m3_per_h:.2g} m3/h "
                         "in a drought year")
            elif drought is not None:
                # a clause that used to be dropped, which read as if a
                # drought year cost nothing
                text += ", and the pump would be dry in a drought year"
        if self.month:
            text += (f". The test was run in {MONTH_NAMES[self.month - 1]}, "
                     f"the {self.season}")
        return text + "."

    def as_dict(self) -> dict:
        return {
            "month": self.month, "season": self.season,
            "month_note": self.month_note,
            "annual_range_m": self.annual_range_m,
            "range_source": self.range_source,
            "pending_reason": self.pending_reason,
            "design_yield_m3_per_h": self.design_yield_m3_per_h,
            "pump_installation_depth_m": self.pump_installation_depth_m,
            "dry_season_loss_percent": self.dry_season_loss_percent,
            "summary": self.summary,
            "scenarios": [s.as_dict() for s in self.scenarios],
        }


def seasonal_yield(analysis, config: PumpingConfig | None = None, *,
                   month: int | None = None,
                   annual_range_m: float | None = None) -> SeasonalYield:
    """Re-run the yield recommendation at each scenario's water level.

    ``month`` overrides whatever the field sheet says - a supervisor who
    knows when the test was run should be able to say so. ``annual_range_m``
    overrides the configured allowance, for a programme that has measured
    the swing in its own boreholes rather than assuming one.
    """
    from .hydraulics.analysis import recommend_yield

    config = config or PumpingConfig()
    test = getattr(analysis, "test", None)
    recommendation = getattr(analysis, "yield_recommendation", None)

    if month is not None:
        found_month, note = (month if 1 <= int(month) <= 12 else None), ""
        if found_month is None:
            note = f"{month!r} is not a month."
    else:
        found_month, note = month_of(
            getattr(getattr(test, "site", None), "date", "") if test else "")

    if annual_range_m is not None and annual_range_m >= 0:
        band, source = float(annual_range_m), "measured for this programme"
    else:
        band, source = float(config.seasonal_allowance_m), (
            "the configured dry-season allowance, not a measurement")

    blank = SeasonalYield(month=found_month, season=season_of(found_month),
                          month_note=note, annual_range_m=band,
                          range_source=source, scenarios=[])
    if test is None or recommendation is None:
        blank.pending_reason = (
            "No pumping test has been analysed, so there is nothing to project "
            "through the year.")
        return blank
    if recommendation.safe_yield_m3_per_h is None:
        blank.pending_reason = (
            recommendation.pending_reason
            or "The yield recommendation is pending, so it cannot be projected "
               "through the year.")
        return blank

    transmissivity = getattr(analysis, "transmissivity_m2_per_day", None)
    if transmissivity is None:
        blank.pending_reason = (
            "No transmissivity was fitted, so the seasonal projection has "
            "nothing to run on.")
        return blank

    scenarios = []
    for key, (title, factor, why) in SCENARIOS.items():
        decline = _decline_to_come(found_month, band, factor)
        # The scenario is the same borehole with its static level lowered:
        # everything downstream - available drawdown, usable fraction, the
        # projection and the pump depth - follows from that one change, so
        # the recommendation is re-run rather than scaled.
        lowered = replace(test, static_water_level_m=test.static_water_level_m
                          + decline)
        trial = recommend_yield(
            lowered, transmissivity, getattr(analysis, "step_test", None),
            replace(config, seasonal_allowance_m=0.0),
        )
        note_text = why
        if key == "as_tested" and found_month:
            note_text += (
                f" The test was run in {MONTH_NAMES[found_month - 1]}, "
                f"the {season_of(found_month)}.")
        if key != "as_tested" and decline == 0.0 and found_month:
            note_text += (
                f" No further decline is reserved: a test run in "
                f"{MONTH_NAMES[found_month - 1]} is already at or below this "
                "level.")
        if trial.safe_yield_m3_per_h is None:
            # the pump would be dry at this level; the table cell is blank,
            # so the note has to carry the reason
            note_text += (
                " No yield at this level: "
                + (trial.pending_reason
                   or "the projection leaves no usable drawdown") + ".")
        scenarios.append(SeasonalScenario(
            key=key, title=title, decline_m=decline,
            static_water_level_m=lowered.static_water_level_m,
            available_drawdown_m=trial.available_drawdown_m,
            safe_yield_m3_per_h=trial.safe_yield_m3_per_h,
            pump_installation_depth_m=trial.pump_installation_depth_m,
            note=note_text,
        ))

    return SeasonalYield(
        month=found_month, season=season_of(found_month), month_note=note,
        annual_range_m=band, range_source=source, scenarios=scenarios,
    )
