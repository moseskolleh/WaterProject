"""Field acceptance checks and calculators for drilling supervision.

Each function encodes a numeric standard from RWSN/UNICEF "Supervising
Water Well Drilling" so the supervisor can check acceptance criteria
on site: sand content, verticality, screen open area, the handpump
specific capacity rule and the WHO chlorine disinfection dose.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class FieldCheck:
    """The outcome of one field acceptance check."""

    name: str
    passed: Optional[bool]  # None when the check is informational
    measured: str
    limit: str
    message: str

    @property
    def status(self) -> str:
        if self.passed is None:
            return "info"
        return "pass" if self.passed else "fail"


def sand_content_check(samples_cm3: list[float], sample_volume_l: float = 20.0) -> FieldCheck:
    """Sand content at the end of the pumping test.

    Three 20 litre samples are collected; the settled sand in each must
    not exceed 0.2 cubic centimetres (10 parts per million by volume).
    """
    limit_cm3 = sample_volume_l * 1000.0 * 10e-6  # 10 ppm by volume, in cm3
    worst = max(samples_cm3) if samples_cm3 else 0.0
    passed = bool(samples_cm3) and worst <= limit_cm3
    return FieldCheck(
        name="Sand content",
        passed=passed if samples_cm3 else None,
        measured=f"{worst:g} cm3 worst of {len(samples_cm3)} sample(s)",
        limit=f"{limit_cm3:g} cm3 per {sample_volume_l:g} L sample (10 ppm by volume)",
        message=(
            "Sand content acceptable."
            if passed
            else "Excessive sand: check drilling technique, gravel pack and "
            "development; a replacement borehole may be at the driller's cost."
        ),
    )


def verticality_check(
    deviation_mm: float, depth_m: float, casing_inner_diameter_mm: float
) -> FieldCheck:
    """Plumb test: deviation must not exceed two thirds of the casing
    inner diameter per 30 m of depth."""
    allowed_mm = (2.0 / 3.0) * casing_inner_diameter_mm * (depth_m / 30.0)
    passed = deviation_mm <= allowed_mm
    return FieldCheck(
        name="Verticality (plumb test)",
        passed=passed,
        measured=f"{deviation_mm:g} mm over {depth_m:g} m",
        limit=f"{allowed_mm:.0f} mm (two thirds of {casing_inner_diameter_mm:g} mm ID per 30 m)",
        message=(
            "Borehole is acceptably straight and vertical."
            if passed
            else "Deviation exceeds the limit; the driller re-drills at own cost."
        ),
    )


def screen_open_area_check(
    design_yield_l_per_s: float, screen_open_area_m2: float
) -> FieldCheck:
    """Screen entrance velocity rule: open area A >= Q/30 (A in m2, Q in
    L/s) keeps the entrance velocity below 0.03 m/s."""
    required = design_yield_l_per_s / 30.0
    passed = screen_open_area_m2 >= required
    return FieldCheck(
        name="Screen open area",
        passed=passed,
        measured=f"{screen_open_area_m2:g} m2",
        limit=f">= {required:.3f} m2 for Q = {design_yield_l_per_s:g} L/s",
        message=(
            "Entrance velocity within 0.03 m/s."
            if passed
            else "Open area too small: turbulent inflow, encrustation and a "
            "shortened screen life are likely; use more or larger screen."
        ),
    )


def specific_capacity_check(
    discharge_m3_per_h: float, drawdown_m: float
) -> FieldCheck:
    """Handpump adequacy rule of thumb: a specific capacity around
    1 m3/h per metre of drawdown suggests the borehole suits a handpump."""
    if drawdown_m <= 0:
        return FieldCheck(
            name="Specific capacity",
            passed=None,
            measured="n/a",
            limit=">= 1 m3/h per m for a handpump",
            message="Drawdown must be positive to compute specific capacity.",
        )
    sc = discharge_m3_per_h / drawdown_m
    passed = sc >= 1.0
    return FieldCheck(
        name="Specific capacity",
        passed=passed,
        measured=f"{sc:.2f} m3/h per m",
        limit=">= 1 m3/h per m for a handpump",
        message=(
            "Adequate for a handpump (about 1 m drawdown at 1 m3/h)."
            if passed
            else "Below the handpump rule of thumb; review the test data and "
            "the pump setting before acceptance."
        ),
    )


def pack_aquifer_ratio_check(d50_pack_mm: float, d50_aquifer_mm: float) -> FieldCheck:
    """Filter pack sizing: pack D50 / aquifer D50 should be 4 to 6."""
    if d50_aquifer_mm <= 0:
        return FieldCheck(
            name="Pack aquifer ratio",
            passed=None,
            measured="n/a",
            limit="4 to 6",
            message="Aquifer D50 must be positive.",
        )
    ratio = d50_pack_mm / d50_aquifer_mm
    passed = 4.0 <= ratio <= 6.0
    return FieldCheck(
        name="Pack aquifer ratio",
        passed=passed,
        measured=f"{ratio:.1f}",
        limit="4 to 6 (D50 pack / D50 aquifer)",
        message=(
            "Filter pack correctly sized for the formation."
            if passed
            else "Pack aquifer ratio outside 4 to 6: risk of sand pumping "
            "(too coarse) or a choked screen (too fine)."
        ),
    )


def annular_space_check(
    borehole_diameter_in: float, casing_od_mm: float
) -> FieldCheck:
    """Annular space rule: at least 50 mm all round for placement, and a
    gravel pack needs at least 70 mm to work as a filter (thinner is
    only a formation stabiliser)."""
    borehole_mm = borehole_diameter_in * 25.4
    annulus_mm = (borehole_mm - casing_od_mm) / 2.0
    passed = annulus_mm >= 50.0
    if annulus_mm >= 70.0:
        note = "Full gravel pack possible."
    elif passed:
        note = (
            "Meets the 50 mm placement minimum, but under 70 mm the annular "
            "fill acts as a formation stabiliser rather than a filter pack."
        )
    else:
        note = (
            "Annulus below the 50 mm minimum: gravel is likely to bridge "
            "during placement; use a larger bit or smaller casing."
        )
    return FieldCheck(
        name="Annular space",
        passed=passed,
        measured=f"{annulus_mm:.0f} mm",
        limit=">= 50 mm (70 mm for a true gravel pack)",
        message=note,
    )


def handpump_corrosion_check(ph: float) -> FieldCheck:
    """Handpump corrosion risk rule (RWSN Stop the Rot).

    Below pH 6.5 galvanised iron riser pipes and rods corrode rapidly
    (failures within 3 months to 2 years), shedding iron and possibly
    heavy metals into the supply; corrosion resistant components
    (stainless steel 304/316 or uPVC risers) must be used instead.
    """
    at_risk = ph < 6.5
    return FieldCheck(
        name="Handpump corrosion risk",
        passed=not at_risk,
        measured=f"pH {ph:g}",
        limit=">= 6.5 for galvanised iron components",
        message=(
            "Corrosion risk low; standard components acceptable."
            if not at_risk
            else "Corrosive water: specify stainless steel (grade 304/316) "
            "or uPVC riser pipes and rods; galvanised iron can fail within "
            "months and taint the water with iron."
        ),
    )


@dataclass
class DisinfectionDose:
    """Chlorine quantities for shock disinfection at 20 mg/L (WHO)."""

    well_volume_l: float
    solution_02pct_l: float  # litres of 0.2 percent chlorine solution
    hth_grams: float  # grams of 65 percent HTH powder for that solution
    contact_hours: float = 4.0

    def summary(self) -> str:
        return (
            f"Well volume about {self.well_volume_l:,.0f} L: add "
            f"{self.solution_02pct_l:,.1f} L of 0.2% chlorine solution "
            f"(about {self.hth_grams:,.0f} g of 65% HTH in that much water) "
            f"and wait at least {self.contact_hours:g} hours before pumping."
        )


def disinfection_dose(
    water_column_m: float, casing_inner_diameter_mm: float
) -> DisinfectionDose:
    """WHO shock dose: 1 L of 0.2 percent solution per 100 L of well
    volume gives 20 mg/L; do not pump for at least 4 hours."""
    radius_m = casing_inner_diameter_mm / 2000.0
    volume_l = math.pi * radius_m**2 * max(0.0, water_column_m) * 1000.0
    solution_l = volume_l / 100.0
    # 0.2 percent solution = 2 g chlorine per litre; 65 percent HTH
    # carries 0.65 g available chlorine per gram of powder.
    hth_grams = solution_l * 2.0 / 0.65
    return DisinfectionDose(
        well_volume_l=volume_l,
        solution_02pct_l=solution_l,
        hth_grams=hth_grams,
    )
