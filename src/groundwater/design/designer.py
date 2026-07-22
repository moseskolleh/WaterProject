"""Generate a borehole construction design from the available data.

Inputs are whatever exists at design time: the drilling log (lithology
intervals, water strikes, total depth), the VES interpretation (water
zones, recommended depth) when the hole is still to be drilled, the
static water level and the pumping test results when available.

The rules follow common Sierra Leone practice and RWSN professional
drilling guidance and live in :class:`~groundwater.config.DesignRules`
so they can be adjusted per client without touching code:

* plain casing from surface, screens set against the aquifer zones,
* screens kept below static water level by a configurable margin,
* a sump of plain casing below the lowest screen,
* gravel pack from the bottom to a margin above the top screen,
* backfill above the gravel pack up to the sanitary seal,
* cement sanitary seal from surface,
* casing stick-up above ground.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ..config import DesignRules
from ..models import DataFlag, DrillingLog
from ..ves.interpret import SiteInterpretation

# Lithology phrases that mark an interval as a screening target, and phrases
# that negate it. Matching is on whole words/phrases so a description like
# "dry, no water struck" is not screened just because it contains "water".
_AQUIFER_WORDS = {"fracture", "fractured", "fractures", "aquifer"}
_AQUIFER_PHRASES = ("water-bearing", "water bearing", "waterbearing",
                    "water strike", "water struck", "water inflow")
_NEGATION_PHRASES = ("no water", "not reached", "without water", "water table not")


@dataclass
class CasingSegment:
    top_m: float
    bottom_m: float
    kind: str  # "plain" | "screen" | "sump"

    @property
    def length_m(self) -> float:
        return self.bottom_m - self.top_m


@dataclass
class BoreholeDesign:
    total_depth_m: float
    borehole_diameter_in: float
    casing_diameter_in: float
    casing_material: str
    segments: list[CasingSegment]
    gravel_pack: tuple[float, float]
    backfill: tuple[float, float]
    sanitary_seal: tuple[float, float]
    stickup_m: float
    screen_slot_mm: float
    water_strikes_m: list[float] = field(default_factory=list)
    static_water_level_m: float | None = None
    pump_intake_m: float | None = None
    design_basis: list[str] = field(default_factory=list)
    flags: list[DataFlag] = field(default_factory=list)

    @property
    def screens(self) -> list[CasingSegment]:
        return [s for s in self.segments if s.kind == "screen"]

    @property
    def total_screen_length_m(self) -> float:
        return sum(s.length_m for s in self.screens)

    def summary_rows(self) -> list[tuple[str, str]]:
        rows = [
            ("Total depth", f"{self.total_depth_m:.0f} m"),
            ("Drilled diameter", f'{self.borehole_diameter_in:g}"'),
            (
                "Casing",
                f'{self.casing_diameter_in:g}" {self.casing_material}, stick-up '
                f"{self.stickup_m:.1f} m",
            ),
            (
                "Screens",
                "; ".join(f"{s.top_m:.0f}-{s.bottom_m:.0f} m" for s in self.screens)
                + f" (slot {self.screen_slot_mm:g} mm)",
            ),
            ("Gravel pack", f"{self.gravel_pack[0]:.0f}-{self.gravel_pack[1]:.0f} m"),
            ("Backfill", f"{self.backfill[0]:.0f}-{self.backfill[1]:.0f} m"),
            (
                "Sanitary seal",
                f"{self.sanitary_seal[0]:.0f}-{self.sanitary_seal[1]:.0f} m cement grout",
            ),
        ]
        if self.static_water_level_m is not None:
            rows.append(("Static water level", f"{self.static_water_level_m:.2f} m"))
        if self.water_strikes_m:
            rows.append(
                ("Water strikes", ", ".join(f"{w:g} m" for w in self.water_strikes_m))
            )
        if self.pump_intake_m is not None:
            rows.append(("Recommended pump intake", f"{self.pump_intake_m:.0f} m"))
        return rows


def _target_zones(
    log: DrillingLog | None,
    interpretation: SiteInterpretation | None,
    swl: float | None,
    total_depth: float,
    rules: DesignRules,
) -> tuple[list[tuple[float, float]], list[str]]:
    """Candidate aquifer intervals from strikes, lithology and VES."""
    basis = []
    zones: list[tuple[float, float]] = []
    if log is not None and log.water_strikes_m:
        for strike in log.water_strikes_m:
            zones.append((max(strike - 1.0, 0.0), strike + 5.0))
        basis.append(
            "screens positioned against the water strikes recorded in the "
            "drilling log (" + ", ".join(f"{w:g} m" for w in log.water_strikes_m) + ")"
        )
    if log is not None:
        for interval in log.intervals:
            text = interval.description.lower()
            if any(neg in text for neg in _NEGATION_PHRASES):
                continue  # e.g. "dry, no water struck" is not an aquifer
            words = set(re.findall(r"[a-z]+", text))
            if (words & _AQUIFER_WORDS) or any(p in text for p in _AQUIFER_PHRASES):
                zones.append((interval.top_m, interval.bottom_m))
    if not zones and interpretation is not None and interpretation.water_zones:
        zones = [(t, b) for t, b in interpretation.water_zones]
        basis.append(
            "screens positioned against the low resistivity zones of the VES "
            "interpretation ("
            + ", ".join(f"{int(t)}-{int(b)} m" for t, b in interpretation.water_zones)
            + ")"
        )
    # clip to the hole, keep below the static level margin, round to 0.5 m
    floor = (swl or 0.0) + rules.min_screen_below_swl_m
    clipped = []
    for top, bottom in zones:
        top = math.ceil(max(top, floor) * 2.0) / 2.0
        bottom = math.floor(min(bottom, total_depth - rules.sump_length_m) * 2.0) / 2.0
        if bottom - top >= 1.0:
            clipped.append((top, bottom))
    clipped.sort()
    merged: list[tuple[float, float]] = []
    for zone in clipped:
        if merged and zone[0] <= merged[-1][1] + 1.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], zone[1]))
        else:
            merged.append(zone)
    return merged, basis


def design_borehole(
    log: DrillingLog | None = None,
    interpretation: SiteInterpretation | None = None,
    static_water_level_m: float | None = None,
    pump_intake_m: float | None = None,
    rules: DesignRules | None = None,
    total_depth_m: float | None = None,
) -> BoreholeDesign:
    """Produce a construction design from the drilling log and/or VES model."""
    rules = rules or DesignRules()
    flags: list[DataFlag] = []

    if total_depth_m is None:
        if log is not None and log.total_depth_m:
            total_depth_m = float(log.total_depth_m)
        elif interpretation is not None:
            total_depth_m = float(interpretation.max_drilling_depth_m)
        else:
            raise ValueError("total depth is needed (drilling log or VES interpretation)")

    swl = static_water_level_m
    zones, basis = _target_zones(log, interpretation, swl, total_depth_m, rules)

    # screens: cover the zones, at least the default screen length overall
    screens: list[tuple[float, float]] = []
    for top, bottom in zones:
        screens.append((top, bottom))
    if not screens:
        # fall back: screen the bottom third of the hole below the SWL margin
        floor = (swl or 0.0) + rules.min_screen_below_swl_m
        sump_top = max(total_depth_m - rules.sump_length_m, 0.0)
        bottom = sump_top
        top = max(total_depth_m * 2.0 / 3.0, floor)
        if bottom - top < 3.0:
            top = max(bottom - rules.screen_length_default_m, floor)
        if bottom - top < 1.0:
            # The static water level margin plus the sump leave no room for a
            # valid screen: the hole is too shallow for this SWL. Clamp to a
            # positive interval just above the sump so the geometry stays valid
            # (no negative-length screen, no casing past the hole bottom) and
            # flag it loudly for manual review rather than emitting garbage.
            top = max(min(bottom - rules.screen_length_default_m, bottom - 1.0), 0.0)
            flags.append(
                DataFlag(
                    "error",
                    "hole_too_shallow",
                    f"Static water level plus the {rules.min_screen_below_swl_m:g} m "
                    f"minimum screen depth leaves no room for a screen above the sump "
                    f"in this {total_depth_m:g} m hole. Screen placement is a best "
                    "effort only - deepen the hole or revise the design manually.",
                )
            )
        screens = [(top, bottom)]
        basis.append(
            "no aquifer intervals identified from the data; screens default to "
            "the lower third of the hole"
        )
        flags.append(
            DataFlag(
                "warning",
                "default_screens",
                "Screen placement fell back to the lower third of the hole; "
                "review against the drilling observations.",
            )
        )

    # trim overall screen length to a sensible share of the hole
    total_screen = sum(b - t for t, b in screens)
    if total_screen > 0.6 * total_depth_m:
        # keep the deepest sections, which sit in the main fractured zone
        keep: list[tuple[float, float]] = []
        budget = 0.6 * total_depth_m
        for top, bottom in reversed(screens):
            length = bottom - top
            if budget <= 0:
                break
            if length > budget:
                top = bottom - budget
                length = budget
            keep.append((top, bottom))
            budget -= length
        screens = sorted(keep)
        flags.append(
            DataFlag(
                "info",
                "screen_trimmed",
                "Total screen length was trimmed to 60 percent of the hole, "
                "keeping the deepest aquifer sections.",
            )
        )

    # assemble the casing string from surface down
    segments: list[CasingSegment] = []
    cursor = 0.0
    sump_top = total_depth_m - rules.sump_length_m
    for top, bottom in screens:
        if top > cursor:
            segments.append(CasingSegment(cursor, top, "plain"))
        segments.append(CasingSegment(top, bottom, "screen"))
        cursor = bottom
    if cursor < sump_top:
        segments.append(CasingSegment(cursor, sump_top, "plain"))
    segments.append(CasingSegment(sump_top, total_depth_m, "sump"))

    top_screen = screens[0][0]
    gravel_top = max(top_screen - rules.gravel_pack_above_top_screen_m, rules.sanitary_seal_depth_m)
    gravel = (gravel_top, total_depth_m)
    seal = (0.0, rules.sanitary_seal_depth_m)
    backfill = (rules.sanitary_seal_depth_m, gravel_top)

    basis.extend(
        [
            f"{rules.casing_diameter_in:g} inch {rules.casing_material} casing in a "
            f"{rules.borehole_diameter_in:g} inch hole",
            f"gravel pack ({rules.gravel_pack_material}) from {gravel[0]:.0f} m to "
            f"the bottom, {rules.gravel_pack_above_top_screen_m:g} m above the top screen",
            f"cement sanitary seal from surface to {rules.sanitary_seal_depth_m:g} m "
            "with " + rules.apron_note,
            f"screens kept at least {rules.min_screen_below_swl_m:g} m below the "
            "static water level",
        ]
    )

    if swl is not None and top_screen < swl:
        flags.append(
            DataFlag(
                "warning",
                "screen_above_swl",
                "The top screen is above the static water level; check the design.",
            )
        )

    return BoreholeDesign(
        total_depth_m=total_depth_m,
        borehole_diameter_in=rules.borehole_diameter_in,
        casing_diameter_in=rules.casing_diameter_in,
        casing_material=rules.casing_material,
        segments=segments,
        gravel_pack=gravel,
        backfill=backfill,
        sanitary_seal=seal,
        stickup_m=rules.stickup_m,
        screen_slot_mm=rules.screen_slot_mm,
        water_strikes_m=list(log.water_strikes_m) if log else [],
        static_water_level_m=swl,
        pump_intake_m=pump_intake_m,
        design_basis=basis,
        flags=flags,
    )
