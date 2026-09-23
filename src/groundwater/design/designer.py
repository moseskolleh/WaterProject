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
from .lithology import is_clayey, read_fractures

# Lithology phrases that mark an interval as a screening target, and phrases
# that negate it. Matching is on whole words/phrases so a description like
# "dry, no water struck" is not screened just because it contains "water".
_AQUIFER_WORDS = {"fracture", "fractured", "fractures", "aquifer"}
_AQUIFER_PHRASES = ("water-bearing", "water bearing", "waterbearing",
                    "water strike", "water struck", "water inflow")
_NEGATION_PHRASES = ("no water", "not reached", "without water", "water table not")

#: The annular fill a design carries, decided by the annulus the hole and
#: casing leave: a filter pack needs 70 mm a side, anything can be placed
#: past 50 mm, and under that nothing can be poured without bridging.
ANNULUS_PACK_MIN_MM = 50.0
ANNULUS_FILTER_MIN_MM = 70.0

#: How construction was arrived at, printed under every drawing.
DESIGN_NOTE = (
    "Construction generated from the drilling log by the design rules. The "
    "log records no casing string, so this is a design, not an as-built record."
)
AS_BUILT_NOTE = (
    "As built: the screens are those recorded as installed on the drilling "
    "log; the rest of the string follows the design rules."
)


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
    # "gravel pack" (a filter pack, 70 mm or more a side), "formation
    # stabiliser" (placeable but too thin to filter) or "none" (an annulus
    # nothing can be poured into). The drawing, the summary and the bill of
    # quantities all read this; a 19 mm annulus used to carry a 2-4 mm pack
    # on every one of them.
    annular_fill: str = "gravel pack"
    annular_fill_material: str = ""
    annulus_mm: float = 0.0
    # True when the screens are the ones recorded as installed on the log
    as_built: bool = False
    construction_note: str = DESIGN_NOTE

    @property
    def screens(self) -> list[CasingSegment]:
        return [s for s in self.segments if s.kind == "screen"]

    @property
    def total_screen_length_m(self) -> float:
        return sum(s.length_m for s in self.screens)

    @property
    def annular_fill_label(self) -> str:
        """What the annulus below the seal holds, for a drawing or a table."""
        if self.annular_fill == "none":
            return (f"no gravel pack: the {self.annulus_mm:.0f} mm annulus is too "
                    "thin to place one")
        if self.annular_fill == "formation stabiliser":
            return (f"formation stabiliser ({self.annular_fill_material}); the "
                    f"{self.annulus_mm:.0f} mm annulus is too thin for a filter pack")
        return f"gravel pack ({self.annular_fill_material})"

    def summary_rows(self) -> list[tuple[str, str]]:
        # depths print as written (14.5, not 14): the table used to round
        # 14.5 m to "14" beside a drawing that said 14.5
        rows = [
            ("Total depth", f"{self.total_depth_m:g} m"),
            ("Drilled diameter", f'{self.borehole_diameter_in:g}"'),
            (
                "Casing",
                (f'{self.casing_diameter_in:g}" {self.casing_material}, stick-up '
                f"{self.stickup_m:g} m"),
            ),
            (
                "Screens" + (" (as installed)" if self.as_built else ""),
                "; ".join(f"{s.top_m:g}-{s.bottom_m:g} m" for s in self.screens)
                + f" (slot {self.screen_slot_mm:g} mm)",
            ),
            (
                "Annular fill",
                (f"{self.gravel_pack[0]:g}-{self.gravel_pack[1]:g} m: "
                 f"{self.annular_fill_label}"),
            ),
            # the fill can reach the seal, and "Backfill 20-20 m" was printed
            ("Backfill", f"{self.backfill[0]:g}-{self.backfill[1]:g} m"
             if self.backfill[1] > self.backfill[0] else "none"),
            (
                "Sanitary seal",
                f"{self.sanitary_seal[0]:g}-{self.sanitary_seal[1]:g} m cement grout",
            ),
        ]
        if self.static_water_level_m is not None:
            rows.append(("Static water level", f"{self.static_water_level_m:.2f} m"))
        if self.water_strikes_m:
            rows.append(
                ("Water strikes", ", ".join(f"{w:g} m" for w in self.water_strikes_m))
            )
        if self.pump_intake_m is not None:
            rows.append(("Recommended pump intake", f"{self.pump_intake_m:g} m"))
        return rows


def seal_depth_for(
    log: DrillingLog | None, rules: DesignRules, total_depth_m: float | None = None,
) -> float:
    """The cement seal: the recorded grout depth, never less than the rule.

    Dr Timbo's log records grouting to 20 m; the drawing showed a 6 m seal
    with a screen and a gravel pack inside the grouted interval.

    A grout recorded at or below the top of the sump cannot be what was
    placed: it leaves nowhere for a screen, and 70 m in a 60 m hole printed
    a "0-70 m" seal over "Annular fill 70-60 m". It is held at the top of
    the sump, and :func:`design_borehole` flags it as ``grout_too_deep``.
    """
    grout = float(getattr(log, "grouting_depth_m", None) or 0.0) if log else 0.0
    if total_depth_m is None and log is not None and log.total_depth_m:
        total_depth_m = float(log.total_depth_m)
    if total_depth_m is not None:
        grout = min(grout, max(total_depth_m - rules.sump_length_m, 0.0))
    return max(rules.sanitary_seal_depth_m, grout)


def logged_diameter_in(log: DrillingLog | None) -> float | None:
    """The drilled diameter the log records, from its diameter column.

    The deepest interval with a diameter is the production diameter; a
    hole reamed wider at the top is logged that way.
    """
    if log is None:
        return None
    with_diameter = [iv for iv in log.intervals if iv.bit_diameter_in]
    if not with_diameter:
        return None
    return float(max(with_diameter, key=lambda iv: iv.bottom_m).bit_diameter_in)


def _interval_at(log: DrillingLog | None, depth: float):
    if log is None:
        return None
    for interval in log.intervals:
        if interval.top_m <= depth < interval.bottom_m:
            return interval
    return None


@dataclass
class _Target:
    """One depth the log says is worth screening, and what became of it."""

    kind: str  # "strike", "zone" (a named fracture zone) or "interval"
    label: str  # "30 m", "49-52 m", "25-30 m"
    candidate: tuple[float, float]  # the screen asked for, before clipping
    clipped: tuple[float, float] | None = None
    # where the clip took the rest of it: "within the 20 m grouted interval"
    cut: list[str] = field(default_factory=list)

    @property
    def noun(self) -> str:
        return {"strike": "strike", "zone": "fracture zone"}.get(self.kind, "interval")


@dataclass
class _Targets:
    zones: list[tuple[float, float]]
    targets: list[_Target]
    # sentences that do not depend on what survives: a strike in clay or in
    # the grout, a clayey interval
    excluded: list[str]
    ves: list[str]


def _half_metres(zone: tuple[float, float]) -> tuple[float, float]:
    """A screen interval rounded inwards to the half metre, as every screen is."""
    return math.ceil(zone[0] * 2.0) / 2.0, math.floor(zone[1] * 2.0) / 2.0


def _target_zones(
    log: DrillingLog | None,
    interpretation: SiteInterpretation | None,
    swl: float | None,
    total_depth: float,
    rules: DesignRules,
) -> _Targets:
    """Candidate aquifer intervals from strikes, lithology and VES.

    The basis sentences are written from the zones that survive clipping,
    not from the candidates: a strike above the static-level floor used to
    leave "screens positioned against the water strikes (8 m)" in the client
    document beside "no aquifer intervals identified", and blocked the VES
    fallback while contributing no screen. Each candidate is kept with what
    the clip did to it, so :func:`_placement_basis` can say why a zone the log
    names is screened only in part, or not at all.
    """
    seal = seal_depth_for(log, rules, total_depth)
    # nothing is screened inside the grouted interval, whatever the log says
    # is wet there: the grout is there to keep that water out
    swl_floor = (swl or 0.0) + rules.min_screen_below_swl_m
    floor = max(swl_floor, seal)
    sump_top = total_depth - rules.sump_length_m

    def clip_one(zone):
        top = math.ceil(max(zone[0], floor) * 2.0) / 2.0
        bottom = math.floor(min(zone[1], sump_top) * 2.0) / 2.0
        return (top, bottom) if bottom - top >= 1.0 else None

    def clip(candidates):
        return [c for c in (clip_one(zone) for zone in candidates) if c]

    def target(kind, label, first, candidate):
        cut = []
        if candidate[0] < floor:
            cut.append(
                f"within the {seal:g} m grouted interval" if seal >= swl_floor
                else f"shallower than {floor:g} m, {rules.min_screen_below_swl_m:g} m "
                "below the static water level"
            )
        if candidate[1] > sump_top:
            cut.append(
                f"below the {total_depth:g} m bottom of the hole" if first >= total_depth
                else f"below the top of the {rules.sump_length_m:g} m sump, at {sump_top:g} m"
            )
        return _Target(kind, label, candidate, clip_one(candidate), cut)

    targets: list[_Target] = []
    excluded: list[str] = []
    if log is not None:
        for strike in log.water_strikes_m:
            host = _interval_at(log, strike)
            reasons = []
            if host is not None and is_clayey(host.description):
                reasons.append(
                    f"it is in {host.description.lower()}, a seepage horizon that "
                    "is cased and grouted off rather than screened"
                )
            if strike < seal:
                reasons.append(f"it lies within the {seal:g} m grouted interval")
            if reasons:
                excluded.append(
                    f"the {strike:g} m strike is not screened: " + " and ".join(reasons)
                )
                continue
            targets.append(target("strike", f"{strike:g} m", strike,
                                  (max(strike - 1.0, 0.0), strike + 5.0)))
        for interval in log.intervals:
            text = interval.description.lower()
            if any(neg in text for neg in _NEGATION_PHRASES):
                continue  # e.g. "dry, no water struck" is not an aquifer
            words = set(re.findall(r"[a-z]+", text))
            hinted = (words & _AQUIFER_WORDS) or any(p in text for p in _AQUIFER_PHRASES)
            if not hinted:
                continue
            if is_clayey(interval.description):
                excluded.append(
                    f"the {interval.top_m:g}-{interval.bottom_m:g} m interval is not "
                    f"screened: {interval.description.lower()} is clayey ground"
                )
                continue
            # "fracture zone 49-52 m" on the 45-50 m row: the zone is the
            # target, with a margin, not the five metres it was logged on.
            # The screens used to cover one metre of that zone and none of
            # the next, which sat behind plain casing. A fracture phrase
            # whose depths cannot be read leaves the row a target as well,
            # rather than leaving it to plain casing.
            reading = read_fractures(interval.description, interval.top_m, interval.bottom_m)
            for top, bottom in reading.ranges:
                targets.append(target(
                    "zone", f"{top:g}-{bottom:g} m", top,
                    (top - rules.fracture_zone_margin_m,
                     bottom + rules.fracture_zone_margin_m),
                ))
            if reading.unread or not reading.ranges:
                targets.append(target(
                    "interval", f"{interval.top_m:g}-{interval.bottom_m:g} m",
                    interval.top_m, (interval.top_m, interval.bottom_m),
                ))
    # one target per thing the log names, however many rows name it
    seen: set[tuple[str, str]] = set()
    targets = [t for t in targets
               if not ((t.kind, t.label) in seen or seen.add((t.kind, t.label)))]
    clipped = [t.clipped for t in targets if t.clipped]
    ves: list[str] = []
    if not clipped and interpretation is not None and interpretation.water_zones:
        clipped = clip([(t, b) for t, b in interpretation.water_zones])
        if clipped:
            ves.append(
                "screens positioned against the low resistivity zones of the VES "
                "interpretation ("
                + ", ".join(f"{int(t)}-{int(b)} m" for t, b in interpretation.water_zones)
                + ")"
            )
    clipped.sort()
    merged: list[tuple[float, float]] = []
    for zone in clipped:
        if merged and zone[0] <= merged[-1][1] + 1.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], zone[1]))
        else:
            merged.append(zone)
    return _Targets(merged, targets, excluded, ves)


def _placement_basis(
    found: _Targets, screens: list[tuple[float, float]], rules: DesignRules,
) -> list[str]:
    """The basis sentences, written from the screens that are actually built.

    A zone clipped by the grout, the sump or the bottom of the hole, or
    trimmed away with the shallowest screens, used to stay in the basis as
    "screens positioned against the fracture zones the log names (16-18 m,
    49-52 m, 59-62 m), with 1 m of screen either side" beside a single
    48-53 m screen. Each target is now described by what covers it: in full,
    in part with the reason, or not at all with the reason.
    """
    margin = rules.fracture_zone_margin_m
    trim_reason = ("the screens were trimmed to 60 percent of the hole, keeping "
                   "the deepest sections")

    def covered(zone):
        pieces = [(max(zone[0], top), min(zone[1], bottom)) for top, bottom in screens
                  if min(zone[1], bottom) > max(zone[0], top)]
        if not pieces:
            return None
        return min(p[0] for p in pieces), max(p[1] for p in pieces)

    strikes, zones, intervals, partial, dropped = [], [], [], [], []
    for t in found.targets:
        cover = covered(t.clipped) if t.clipped else None
        trimmed = t.clipped is not None and cover != t.clipped
        why = []
        if t.cut and (cover is None or cover[0] > t.candidate[0] or cover[1] < t.candidate[1]):
            why.append(("it lies " if cover is None else "the rest of it lies ")
                       + " and ".join(t.cut))
        if trimmed:
            why.append(trim_reason)
        if cover is None:
            if why:
                dropped.append(f"the {t.label} {t.noun} is not screened: " + "; ".join(why))
            continue
        if t.kind == "strike":
            strikes.append(t.label)
        elif t.kind == "interval":
            intervals.append(t.label)
        elif cover == _half_metres(t.candidate):
            zones.append(t.label)
        else:
            partial.append(
                f"the {t.label} fracture zone is screened at {cover[0]:g}-{cover[1]:g} m, "
                f"not with {margin:g} m of screen either side: "
                + "; ".join(why or ["the screen is rounded to the half metre"])
            )
    basis = []
    if strikes:
        basis.append(
            "screens positioned against the water strikes recorded in the "
            "drilling log (" + ", ".join(strikes) + ")"
        )
    if zones:
        basis.append(
            "screens positioned against the fracture zones the log names ("
            + ", ".join(zones) + f"), with {margin:g} m of screen either side"
        )
    if intervals:
        basis.append(
            "screens positioned against the fractured or water-bearing intervals "
            "logged at " + ", ".join(intervals)
        )
    return basis + partial + found.excluded + dropped + found.ves


def design_borehole(
    log: DrillingLog | None = None,
    interpretation: SiteInterpretation | None = None,
    static_water_level_m: float | None = None,
    pump_intake_m: float | None = None,
    rules: DesignRules | None = None,
    total_depth_m: float | None = None,
    screens_m: list[tuple[float, float]] | None = None,
    pump_intake_floor_m: float | None = None,
) -> BoreholeDesign:
    """Produce a construction design from the drilling log and/or VES model.

    ``screens_m`` overrides the automatic screen placement with intervals the
    analyst has chosen. The rest of the string - plain casing, sump, gravel
    pack, backfill and seal - is still assembled by the same rules, and the
    same checks still run, so an analyst-placed screen is validated exactly
    like a generated one rather than being taken on trust.

    ``pump_intake_floor_m`` is the shallowest depth the pumping test supports
    for the intake (see :func:`pump_intake_floor`). An intake that falls in a
    screen is moved up into plain casing only as far as that; without it, it
    is moved down or not at all.
    """
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

    as_built = False
    if not screens_m and log is not None and log.installed_screens_m:
        # the sheet records the screens the crew set: those are the screens,
        # and the drawing is an as-built record rather than a design
        screens_m = list(log.installed_screens_m)
        as_built = True
    if screens_m:
        screens, basis = _analyst_screens(screens_m, total_depth_m, rules, flags,
                                          as_built=as_built)
        if as_built:
            # the record as the crew wrote it: where the drawing has had to
            # differ from it, a screen_clipped warning says how
            basis = [
                "screens as installed, recorded on the drilling log ("
                + ", ".join(f"{float(t):g}-{float(b):g} m" for t, b in sorted(screens_m))
                + ")"
            ]
        return _assemble(
            screens=screens,
            basis=basis,
            flags=flags,
            total_depth_m=total_depth_m,
            swl=swl,
            pump_intake_m=pump_intake_m,
            pump_intake_floor_m=pump_intake_floor_m,
            rules=rules,
            log=log,
            as_built=as_built,
        )

    found = _target_zones(log, interpretation, swl, total_depth_m, rules)

    # screens: cover the zones, at least the default screen length overall
    screens: list[tuple[float, float]] = []
    for top, bottom in found.zones:
        screens.append((top, bottom))
    fallback: list[str] = []
    if not screens:
        # fall back: screen the bottom third of the hole below the SWL margin
        swl_floor = (swl or 0.0) + rules.min_screen_below_swl_m
        seal = seal_depth_for(log, rules, total_depth_m)
        floor = max(swl_floor, seal)
        sump_top = max(total_depth_m - rules.sump_length_m, 0.0)
        bottom = sump_top
        # rounded to 0.5 m like every other screen top, so the summary does
        # not read "27-38 m" over a segment that carries 26.666...
        top = math.ceil(max(total_depth_m * 2.0 / 3.0, floor) * 2.0) / 2.0
        if bottom - top < 3.0:
            top = max(bottom - rules.screen_length_default_m, floor)
        if bottom - top < 1.0:
            # The static water level margin, or the recorded grout, plus the
            # sump leave no room for a valid screen. Clamp to a positive
            # interval just above the sump so the geometry stays valid (no
            # negative-length screen, no casing past the hole bottom) and
            # flag it loudly for manual review rather than emitting garbage.
            # The message names whichever of the two is in the way: a grout
            # recorded below the hole was blamed on the static water level.
            top = max(min(bottom - rules.screen_length_default_m, bottom - 1.0), 0.0)
            cause = (
                f"The {seal:g} m grouted interval" if seal >= swl_floor
                else f"Static water level plus the {rules.min_screen_below_swl_m:g} m "
                "minimum screen depth"
            )
            flags.append(
                DataFlag(
                    "error",
                    "hole_too_shallow",
                    f"{cause} leaves no room for a screen above the sump "
                    f"in this {total_depth_m:g} m hole. Screen placement is a best "
                    "effort only - deepen the hole or revise the design manually.",
                )
            )
        screens = [(top, bottom)]
        # the targets the log names and the design could not screen are
        # listed above this sentence, so it does not say there were none
        fallback.append(
            ("none of the aquifer intervals identified from the data can be screened"
             if found.targets or found.excluded
             else "no aquifer intervals identified from the data")
            + "; screens default to the lower third of the hole"
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

    return _assemble(
        screens=screens,
        basis=_placement_basis(found, screens, rules) + fallback,
        flags=flags,
        total_depth_m=total_depth_m,
        swl=swl,
        pump_intake_m=pump_intake_m,
        pump_intake_floor_m=pump_intake_floor_m,
        rules=rules,
        log=log,
    )


def pump_intake_floor(recommendation, submergence_m: float) -> float | None:
    """The shallowest pump intake the pumping test supports.

    That is the deepest level the test drew the water to, with the
    submergence margin under it: the floor the yield recommendation itself
    never sets the intake above. ``None`` when the test gives no level.
    """
    deepest = getattr(recommendation, "deepest_pumping_level_m", None)
    if deepest is None:
        return None
    return float(deepest) + float(submergence_m)


def _analyst_screens(
    screens_m: list[tuple[float, float]],
    total_depth_m: float,
    rules: DesignRules,
    flags: list[DataFlag],
    as_built: bool = False,
) -> tuple[list[tuple[float, float]], list[str]]:
    """Clean up analyst-supplied screen intervals without silently moving them.

    Intervals are ordered, clipped to the hole above the sump and merged where
    they touch. Anything the clipping actually changed is flagged rather than
    absorbed, because a screen that has quietly moved is worse than one that
    was refused.

    Screens recorded as installed are a record, not a choice: two that meet
    stay two, and a clip is a warning that reaches the client documents. It
    used to be an info flag, so "48-54; 54-60 m" in a 60 m hole was printed
    "Screens (as installed) 48-58 m" without a word.
    """
    sump_top = total_depth_m - rules.sump_length_m
    cleaned: list[tuple[float, float]] = []
    for top, bottom in sorted((float(t), float(b)) for t, b in screens_m):
        clipped_top = max(0.0, min(top, sump_top))
        clipped_bottom = max(clipped_top, min(bottom, sump_top))
        if clipped_bottom - clipped_top < 0.5:
            flags.append(
                DataFlag(
                    "warning",
                    "screen_dropped",
                    f"A screen interval at {top:g}-{bottom:g} m does not fit above "
                    f"the {rules.sump_length_m:g} m sump and was dropped.",
                )
            )
            continue
        if (clipped_top, clipped_bottom) != (top, bottom):
            if as_built:
                flags.append(
                    DataFlag(
                        "warning",
                        "screen_clipped",
                        f"The screen recorded as installed at {top:g}-{bottom:g} m "
                        f"runs below the top of the {rules.sump_length_m:g} m sump "
                        f"the design rules place at {sump_top:g} m in this "
                        f"{total_depth_m:g} m hole; it is drawn as "
                        f"{clipped_top:g}-{clipped_bottom:g} m. Check the record "
                        "against the hole.",
                    )
                )
            else:
                flags.append(
                    DataFlag(
                        "info",
                        "screen_clipped",
                        f"Screen {top:g}-{bottom:g} m was clipped to "
                        f"{clipped_top:g}-{clipped_bottom:g} m to stay inside the hole "
                        "and above the sump.",
                    )
                )
        if cleaned and (clipped_top < cleaned[-1][1]
                        or (clipped_top == cleaned[-1][1] and not as_built)):
            cleaned[-1] = (cleaned[-1][0], max(cleaned[-1][1], clipped_bottom))
        else:
            cleaned.append((clipped_top, clipped_bottom))

    if not cleaned:
        raise ValueError("no usable screen interval was supplied")

    basis = [
        "screen intervals set by the analyst on the borehole section ("
        + ", ".join(f"{t:g}-{b:g} m" for t, b in cleaned)
        + ")"
    ]
    return cleaned, basis


def _assemble(
    *,
    screens: list[tuple[float, float]],
    basis: list[str],
    flags: list[DataFlag],
    total_depth_m: float,
    swl: float | None,
    pump_intake_m: float | None,
    rules: DesignRules,
    log: DrillingLog | None,
    as_built: bool = False,
    pump_intake_floor_m: float | None = None,
) -> BoreholeDesign:
    """Build the casing string and annulus around a set of screen intervals."""
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
    seal_depth = seal_depth_for(log, rules, total_depth_m)
    grout = float(getattr(log, "grouting_depth_m", None) or 0.0) if log else 0.0
    if grout > 0 and grout >= sump_top:
        flags.append(
            DataFlag(
                "error",
                "grout_too_deep",
                f"The drilling log records grouting to {grout:g} m, at or below the "
                f"top of the sump at {sump_top:g} m in this {total_depth_m:g} m hole, "
                "which leaves nowhere below the grout for a screen. The seal is "
                f"drawn to {seal_depth:g} m; check the grouting depth on the log.",
            )
        )
    # A screen inside the grout is sealed off from the water it is there to
    # take. The design never places one there; a screen recorded as
    # installed, or placed by the analyst, can say otherwise, and 15-20 m of
    # an as-built screen inside a 20 m grout used to go unmentioned.
    for top, bottom in screens:
        if top < seal_depth:
            sealed = min(bottom, seal_depth) - top
            flags.append(
                DataFlag(
                    "warning",
                    "screen_in_grout",
                    (f"The screen recorded as installed at {top:g}-{bottom:g} m"
                     if as_built else f"The screen at {top:g}-{bottom:g} m")
                    + f" runs inside the {seal_depth:g} m grouted interval, which "
                    f"seals {sealed:g} m of it off"
                    + ("; the record of the grout or of the screen needs checking."
                       if as_built else "."),
                )
            )
    gravel_top = max(top_screen - rules.gravel_pack_above_top_screen_m, seal_depth)
    gravel = (gravel_top, total_depth_m)
    seal = (0.0, seal_depth)
    backfill = (seal_depth, gravel_top)

    # the drilled diameter is what the log says was drilled, not the rule's
    # default; the rule applies when the log records none
    bore_in = logged_diameter_in(log) or rules.borehole_diameter_in
    diameter_source = " as logged" if logged_diameter_in(log) else ""

    # The same annulus rule the field checks apply (50 mm per side to place
    # gravel, 70 mm for it to filter). It used to raise a flag that reached
    # no document while the drawing, the summary and the bill of quantities
    # carried a 2-4 mm pack that cannot be poured through 19 mm. The fill
    # now follows the annulus, and every document follows the fill.
    annulus_mm = (bore_in - rules.casing_diameter_in) * 25.4 / 2.0
    if annulus_mm < ANNULUS_PACK_MIN_MM:
        fill, material = "none", ""
        flags.append(
            DataFlag(
                "warning",
                "thin_annulus",
                f"A {rules.casing_diameter_in:g} inch casing in a "
                f"{bore_in:g} inch hole leaves {annulus_mm:.0f} mm "
                f"of annulus per side, under the {ANNULUS_PACK_MIN_MM:g} mm needed "
                "to place gravel without bridging "
                f"({ANNULUS_FILTER_MIN_MM:g} mm for a true filter pack), so no "
                "gravel pack is drawn or priced and the screen slot must suit "
                "the formation; use a larger bit or smaller casing to fit one.",
            )
        )
    elif annulus_mm < ANNULUS_FILTER_MIN_MM:
        fill, material = "formation stabiliser", rules.gravel_pack_material
        flags.append(
            DataFlag(
                "info",
                "thin_annulus",
                f"The {annulus_mm:.0f} mm annulus meets the {ANNULUS_PACK_MIN_MM:g} mm "
                f"placement minimum but is under {ANNULUS_FILTER_MIN_MM:g} mm, so "
                "the annular fill acts as a formation stabiliser rather than a "
                "filter pack.",
            )
        )
    else:
        fill, material = "gravel pack", rules.gravel_pack_material

    if fill == "none":
        fill_sentence = (
            f"no gravel pack: the {annulus_mm:.0f} mm annulus between the "
            f"{rules.casing_diameter_in:g} inch casing and the {bore_in:g} inch hole "
            "is too thin to place one, so the annulus below the seal is left to "
            "the formation"
        )
    else:
        fill_sentence = (
            f"{fill} ({material}) from {gravel[0]:g} m to the bottom, "
            f"{rules.gravel_pack_above_top_screen_m:g} m above the top screen"
        )
    if grout > seal_depth:
        # held at the top of the sump: not what the log records
        seal_sentence = (
            f"cement grout from surface to {seal_depth:g} m, the top of the sump, "
            f"where the drilling log records {grout:g} m (see the design notes), "
            "with " + rules.apron_note
        )
    elif seal_depth > rules.sanitary_seal_depth_m:
        seal_sentence = (
            f"cement grout from surface to {seal_depth:g} m as recorded on the "
            f"drilling log (the rule's minimum is {rules.sanitary_seal_depth_m:g} m), "
            "with " + rules.apron_note
        )
    else:
        seal_sentence = (
            f"cement sanitary seal from surface to {seal_depth:g} m with "
            + rules.apron_note
        )
    basis.extend(
        [
            (f"{rules.casing_diameter_in:g} inch {rules.casing_material} casing in a "
            f"{bore_in:g} inch hole{diameter_source}"),
            fill_sentence,
            seal_sentence,
            (f"screens kept at least {rules.min_screen_below_swl_m:g} m below the "
            "static water level"),
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

    # A pump intake inside a screen is moved into plain casing, downwards
    # where the string allows it (deeper is more submergence) and upwards
    # otherwise, by the same clearance the pumping rules use. The yield
    # recommendation cannot know where the screens are; the design can.
    held = ""
    if pump_intake_m is not None:
        hit = next(((t, b) for t, b in screens if t <= pump_intake_m <= b), None)
        if hit is not None:
            clearance = 1.0
            below = hit[1] + clearance
            above = hit[0] - clearance
            plain_below = below <= sump_top and not any(
                t <= below <= b for t, b in screens
            )
            plain_above = above > 0 and (swl is None or above > swl) and not any(
                t <= above <= b for t, b in screens
            )
            # Moving the intake up spends drawdown the yield was worked out
            # on. It goes up only as far as the deepest level the pumping
            # test reached plus the submergence margin, the floor the yield
            # itself holds to: a 40-68 m screen used to lift a 52 m intake to
            # 39 m, above the 42.3 m the test had drawn the water to, which
            # is the intake hydraulics-4 took out of the yield. Without that
            # floor there is nothing to check a shallower setting against.
            if plain_above and not plain_below:
                if pump_intake_floor_m is None:
                    held = (f"the plain casing above it, at {above:g} m, cannot be "
                            "checked against the level the pumping test reached")
                elif above < pump_intake_floor_m:
                    held = (f"the plain casing above it, at {above:g} m, is shallower "
                            f"than the {pump_intake_floor_m:g} m the pumping test "
                            "supports (the deepest level it reached with the "
                            "submergence margin)")
                if held:
                    plain_above = False
            moved = below if plain_below else (above if plain_above else None)
            if moved is not None:
                flags.append(
                    DataFlag(
                        "info",
                        "pump_intake_moved",
                        f"The pump intake of {pump_intake_m:g} m from the yield "
                        f"recommendation sits inside the {hit[0]:g}-{hit[1]:g} m "
                        f"screen; it is set at {moved:g} m, {clearance:g} m "
                        + ("below" if moved > pump_intake_m else "above")
                        + " that screen in plain casing, so the inflow is not "
                        "drawn across the pump.",
                    )
                )
                basis.append(
                    f"pump intake at {moved:g} m, in plain casing {clearance:g} m "
                    + ("below" if moved > pump_intake_m else "above")
                    + f" the {hit[0]:g}-{hit[1]:g} m screen rather than the "
                    f"{pump_intake_m:g} m the yield recommendation asked for"
                )
                pump_intake_m = moved
    # a pump intake is written straight through from the caller; it used to
    # be accepted below the hole bottom, inside a screen or above the water
    if pump_intake_m is not None:
        if pump_intake_m > sump_top:
            flags.append(
                DataFlag(
                    "error",
                    "pump_intake_below_hole",
                    f"The pump intake at {pump_intake_m:g} m is below the top of the "
                    f"sump at {sump_top:g} m in a {total_depth_m:g} m hole; it cannot "
                    "be set there.",
                )
            )
        elif held:
            flags.append(
                DataFlag(
                    "warning",
                    "pump_intake_in_screen",
                    f"The pump intake at {pump_intake_m:g} m sits inside a screened "
                    "interval and is kept there: there is no plain casing below "
                    f"that screen above the sump, and {held}. Set the screens so "
                    "there is plain casing at a depth the test supports, or accept "
                    "the inflow drawn across the pump.",
                )
            )
        elif any(top <= pump_intake_m <= bottom for top, bottom in screens):
            flags.append(
                DataFlag(
                    "warning",
                    "pump_intake_in_screen",
                    f"The pump intake at {pump_intake_m:g} m sits inside a screened "
                    "interval; set it in plain casing above or below the screen so "
                    "the inflow is not drawn across the pump.",
                )
            )
        if swl is not None and pump_intake_m <= swl:
            flags.append(
                DataFlag(
                    "error",
                    "pump_intake_above_swl",
                    f"The pump intake at {pump_intake_m:g} m is at or above the static "
                    f"water level of {swl:g} m; the pump would run dry.",
                )
            )

    return BoreholeDesign(
        total_depth_m=total_depth_m,
        borehole_diameter_in=bore_in,
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
        annular_fill=fill,
        annular_fill_material=material,
        annulus_mm=annulus_mm,
        as_built=as_built,
        construction_note=AS_BUILT_NOTE if as_built else DESIGN_NOTE,
    )
