"""Borehole cost estimation following the RWSN costing methodology.

The structure follows the RWSN Borehole Costing Model (Heath, Carter
and Danert, Cost-Effective Boreholes Flagship) and the RWSN guide
"Costing and Pricing: a Guide for Water Well Drilling Enterprises":

- every cost line item carries a construction *stage* (mobilisation,
  drilling, casing, development, test pumping, water quality, wellhead)
  and a *resource category* (equipment, labour, consumables, fuel,
  vehicles), so the same items roll up along both axes;
- the model computes the actual *cost* of the borehole; the *price* is
  derived separately as cost plus overheads plus margin, keeping the
  contractor's cost and the client's price clearly apart;
- all amounts are stored in US dollars with a single exchange rate for
  display in the local currency, mirroring the reference-cell rule of
  the RWSN workbook.

Unit rates live in an editable CSV (``data/borehole_cost_items.csv``);
the bundled values are indicative and must be confirmed against local
Sierra Leone prices - no code change is needed to update them.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Optional

from ..models import DataFlag
from ..utils import fmt_num

# Canonical stage order for tables and charts (the six RWSN cost
# components, with development and test pumping kept separate and the
# water quality sampling shown in its own stage).
STAGES = (
    "Siting",
    "Mobilisation",
    "Drilling",
    "Casing",
    "Development",
    "Test pumping",
    "Water quality",
    "Wellhead",
)

# The five RWSN resource categories.
RESOURCE_CATEGORIES = ("equipment", "labour", "consumables", "fuel", "vehicles")

# Default exchange rate for display only (new Sierra Leonean leone per
# US dollar). Confirm against the current market rate.
DEFAULT_EXCHANGE_RATE_SLE_PER_USD = 23.0


# ---------------------------------------------------------------------------
# Rate catalogue
# ---------------------------------------------------------------------------

@dataclass
class RateItem:
    """One row of the unit rate catalogue."""

    code: str
    stage: str
    category: str
    item: str
    unit: str
    quantity_basis: str
    unit_cost_usd: float
    note: str = ""


def load_rates(path: str | Path | None = None) -> list[RateItem]:
    """Load the unit rate catalogue (bundled CSV unless a path is given)."""
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = (
            resources.files("groundwater") / "data" / "borehole_cost_items.csv"
        ).read_text(encoding="utf-8")
    rates: list[RateItem] = []
    for row in csv.DictReader(text.splitlines()):
        rates.append(
            RateItem(
                code=row["code"].strip(),
                stage=row["stage"].strip(),
                category=row["category"].strip().lower(),
                item=row["item"].strip(),
                unit=row["unit"].strip(),
                quantity_basis=row["quantity_basis"].strip(),
                unit_cost_usd=float(row["unit_cost_usd"]),
                note=(row.get("note") or "").strip(),
            )
        )
    return rates


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass
class CostingInputs:
    """Quantities that drive the bill of quantities.

    Only ``total_depth_m`` is required; every derived field falls back
    to a documented rule of thumb and the assumption is recorded on the
    estimate so nothing is hidden.
    """

    total_depth_m: float
    overburden_m: Optional[float] = None  # weathered zone drilled by rotary
    casing_m: Optional[float] = None  # plain casing length
    screen_m: Optional[float] = None  # screen length
    borehole_diameter_in: float = 6.5
    casing_diameter_in: float = 5.0
    gravel_interval_m: Optional[float] = None  # gravel packed annulus length
    cement_bags: Optional[float] = None  # sanitary seal and grout
    crew_days: Optional[float] = None  # days on site including moves
    development_hours: float = 6.0
    test_pumping_hours: float = 30.0  # step plus constant plus recovery
    mobilisation_distance_km: float = 0.0  # one way, base to site
    wq_samples: int = 1
    handpumps: int = 1  # set 0 when the pump is a separate contract

    def resolved(self) -> tuple["CostingInputs", list[str]]:
        """Fill missing fields from rules of thumb; return the assumptions."""
        r = CostingInputs(**self.__dict__)
        assumptions: list[str] = []
        if r.overburden_m is None:
            r.overburden_m = min(30.0, 0.5 * r.total_depth_m)
            assumptions.append(
                f"Overburden thickness assumed {fmt_num(r.overburden_m)} m "
                "(half the total depth, at most 30 m); supply the real "
                "split from the drilling log or the VES interpretation."
            )
        r.overburden_m = min(r.overburden_m, r.total_depth_m)
        if r.screen_m is None:
            r.screen_m = 9.0
            assumptions.append("Screen length assumed 9 m (design default).")
        if r.casing_m is None:
            r.casing_m = max(0.0, r.total_depth_m + 0.5 - r.screen_m)
            assumptions.append(
                f"Plain casing length taken as {fmt_num(r.casing_m)} m "
                "(total depth plus 0.5 m stick-up minus the screen length)."
            )
        if r.gravel_interval_m is None:
            r.gravel_interval_m = max(0.0, r.total_depth_m - 15.0)
            assumptions.append(
                f"Gravel packed interval assumed {fmt_num(r.gravel_interval_m)} m "
                "(from 15 m below ground to the bottom of the borehole)."
            )
        if r.cement_bags is None:
            seal_volume = annulus_volume_m3(
                r.borehole_diameter_in, r.casing_diameter_in, 15.0
            )
            r.cement_bags = max(4.0, math.ceil(seal_volume * 20.0))
            assumptions.append(
                f"Cement estimated at {fmt_num(r.cement_bags)} bags for the "
                "grout seal (about 20 bags per cubic metre of annulus)."
            )
        if r.crew_days is None:
            r.crew_days = math.ceil(r.total_depth_m / 25.0) + 4
            assumptions.append(
                f"Crew time assumed {fmt_num(r.crew_days)} days on site "
                "(drilling at 25 m per day plus four days for moving, "
                "set up, development, testing and completion)."
            )
        return r, assumptions

    @property
    def bedrock_m(self) -> float:
        over = self.overburden_m if self.overburden_m is not None else 0.0
        return max(0.0, self.total_depth_m - over)

    @property
    def gravel_pack_m3(self) -> float:
        interval = self.gravel_interval_m or 0.0
        return annulus_volume_m3(
            self.borehole_diameter_in, self.casing_diameter_in, interval, allowance=1.3
        )


def annulus_volume_m3(
    borehole_diameter_in: float,
    casing_diameter_in: float,
    interval_m: float,
    allowance: float = 1.0,
) -> float:
    """Volume of the borehole/casing annulus over an interval.

    ``allowance`` covers washout and placement losses (a 1.3 factor is
    common for gravel pack ordering).
    """
    to_m = 0.0254
    d_bore = borehole_diameter_in * to_m
    d_casing = casing_diameter_in * to_m
    area = math.pi / 4.0 * max(0.0, d_bore**2 - d_casing**2)
    return area * max(0.0, interval_m) * allowance


def inputs_from_design(design, *, mobilisation_distance_km: float = 0.0,
                       overburden_m: float | None = None) -> CostingInputs:
    """Pre-fill costing quantities from a :class:`BoreholeDesign`.

    Casing and screen lengths, diameters and the gravel packed interval
    come straight from the design so the bill of quantities always
    matches the drawing.
    """
    screen_m = design.total_screen_length_m
    casing_m = max(
        0.0,
        design.total_depth_m + design.stickup_m - screen_m,
    )
    gravel_top, gravel_bottom = design.gravel_pack
    return CostingInputs(
        total_depth_m=design.total_depth_m,
        overburden_m=overburden_m,
        casing_m=casing_m,
        screen_m=screen_m,
        borehole_diameter_in=design.borehole_diameter_in,
        casing_diameter_in=design.casing_diameter_in,
        gravel_interval_m=max(0.0, gravel_bottom - gravel_top),
        mobilisation_distance_km=mobilisation_distance_km,
    )


# ---------------------------------------------------------------------------
# Estimate
# ---------------------------------------------------------------------------

@dataclass
class CostLineItem:
    """One priced line of the bill of quantities."""

    code: str
    stage: str
    category: str
    item: str
    unit: str
    quantity: float
    unit_cost_usd: float
    note: str = ""

    @property
    def amount_usd(self) -> float:
        return self.quantity * self.unit_cost_usd


@dataclass
class CostEstimate:
    """A complete borehole cost estimate with both RWSN roll-ups."""

    items: list[CostLineItem]
    inputs: CostingInputs
    overheads_percent: float
    margin_percent: float
    contingency_percent: float
    exchange_rate_sle_per_usd: float
    vat_percent: float = 0.0
    assumptions: list[str] = field(default_factory=list)
    flags: list[DataFlag] = field(default_factory=list)

    # ---- roll-ups ------------------------------------------------------

    @property
    def direct_cost_usd(self) -> float:
        return sum(i.amount_usd for i in self.items)

    @property
    def overheads_usd(self) -> float:
        return self.direct_cost_usd * self.overheads_percent / 100.0

    @property
    def total_cost_usd(self) -> float:
        """The contractor's full cost (direct plus overheads)."""
        return self.direct_cost_usd + self.overheads_usd

    @property
    def margin_usd(self) -> float:
        return self.total_cost_usd * self.margin_percent / 100.0

    @property
    def price_usd(self) -> float:
        """A sustainable contract price: cost plus margin."""
        return self.total_cost_usd + self.margin_usd

    @property
    def cost_per_meter_usd(self) -> float:
        """Total cost per drilled metre, the sector's comparison figure."""
        depth = self.inputs.total_depth_m
        return self.total_cost_usd / depth if depth else 0.0

    @property
    def vat_usd(self) -> float:
        return self.price_usd * self.vat_percent / 100.0

    @property
    def price_with_vat_usd(self) -> float:
        return self.price_usd + self.vat_usd

    @property
    def contingency_usd(self) -> float:
        return self.price_with_vat_usd * self.contingency_percent / 100.0

    @property
    def budget_usd(self) -> float:
        """Client-side planning budget: price (with any VAT) plus contingency."""
        return self.price_with_vat_usd + self.contingency_usd

    def price_per_successful_well_usd(self, success_rate_percent: float) -> float:
        """Risk loaded price under a no water no pay contract.

        When the client only pays for successful boreholes, the price
        of each successful well must carry the cost of the expected
        failures: price / success rate.
        """
        if not 0 < success_rate_percent <= 100:
            raise ValueError("success rate must be in (0, 100]")
        return self.price_with_vat_usd / (success_rate_percent / 100.0)

    def in_local(self, usd: float) -> float:
        return usd * self.exchange_rate_sle_per_usd

    def by_stage(self) -> list[tuple[str, float]]:
        totals = {stage: 0.0 for stage in STAGES}
        for item in self.items:
            totals.setdefault(item.stage, 0.0)
            totals[item.stage] += item.amount_usd
        return [(s, v) for s, v in totals.items() if v > 0]

    def by_category(self) -> list[tuple[str, float]]:
        totals = {cat: 0.0 for cat in RESOURCE_CATEGORIES}
        for item in self.items:
            totals.setdefault(item.category, 0.0)
            totals[item.category] += item.amount_usd
        return [(c, v) for c, v in totals.items() if v > 0]

    def boq_rows(self) -> list[dict]:
        rows = []
        for item in sorted(
            self.items,
            key=lambda i: (STAGES.index(i.stage) if i.stage in STAGES else 99, i.code),
        ):
            rows.append(
                {
                    "Code": item.code,
                    "Stage": item.stage,
                    "Item": item.item,
                    "Unit": item.unit,
                    "Quantity": round(item.quantity, 2),
                    "Rate (USD)": round(item.unit_cost_usd, 2),
                    "Amount (USD)": round(item.amount_usd, 2),
                }
            )
        return rows

    def summary_rows(self) -> list[tuple[str, str, str]]:
        def pair(usd: float) -> tuple[str, str]:
            return (
                f"{usd:,.0f}",
                f"{self.in_local(usd):,.0f}",
            )

        rows = [
            ("Direct works cost", *pair(self.direct_cost_usd)),
            (f"Overheads ({self.overheads_percent:g}%)", *pair(self.overheads_usd)),
            ("Total cost", *pair(self.total_cost_usd)),
            ("Cost per metre drilled", *pair(self.cost_per_meter_usd)),
            (f"Margin ({self.margin_percent:g}%)", *pair(self.margin_usd)),
            ("Contract price", *pair(self.price_usd)),
        ]
        if self.vat_percent:
            rows += [
                (f"VAT/GST ({self.vat_percent:g}%)", *pair(self.vat_usd)),
                ("Price including VAT", *pair(self.price_with_vat_usd)),
            ]
        rows += [
            (
                f"Contingency ({self.contingency_percent:g}%)",
                *pair(self.contingency_usd),
            ),
            ("Planning budget", *pair(self.budget_usd)),
        ]
        return rows


def _quantity(basis: str, inputs: CostingInputs) -> Optional[float]:
    """Quantity for a rate item, or None when the basis is unknown."""
    table = {
        "lump_sum": 1.0,
        "per_km_round_trip": 2.0 * inputs.mobilisation_distance_km,
        "per_crew_day": inputs.crew_days or 0.0,
        "per_m_drilled": inputs.total_depth_m,
        "per_m_overburden": inputs.overburden_m or 0.0,
        "per_m_bedrock": inputs.bedrock_m,
        "per_m_casing": inputs.casing_m or 0.0,
        "per_m_screen": inputs.screen_m or 0.0,
        "per_m3_gravel": inputs.gravel_pack_m3,
        "per_bag_cement": inputs.cement_bags or 0.0,
        "per_hour_development": inputs.development_hours,
        "per_hour_test": inputs.test_pumping_hours,
        "per_sample": float(inputs.wq_samples),
        "per_handpump": float(inputs.handpumps),
    }
    return table.get(basis)


def estimate_borehole_cost(
    inputs: CostingInputs,
    rates: list[RateItem] | None = None,
    *,
    overheads_percent: float = 15.0,
    margin_percent: float = 20.0,
    contingency_percent: float = 10.0,
    vat_percent: float = 0.0,
    exchange_rate_sle_per_usd: float = DEFAULT_EXCHANGE_RATE_SLE_PER_USD,
) -> CostEstimate:
    """Build the bill of quantities and roll it up to a cost and a price.

    Percentage defaults follow the RWSN costing and pricing guidance
    for drilling enterprises: overheads on top of direct works cost,
    then a margin that keeps the business viable; the contingency is a
    client-side planning allowance, shown separately so the contract
    price stays honest.
    """
    if inputs.total_depth_m <= 0:
        raise ValueError("total depth must be positive")
    resolved, assumptions = inputs.resolved()
    rates = rates if rates is not None else load_rates()
    items: list[CostLineItem] = []
    flags: list[DataFlag] = []
    for rate in rates:
        quantity = _quantity(rate.quantity_basis, resolved)
        if quantity is None:
            flags.append(
                DataFlag(
                    "warning",
                    "unknown_quantity_basis",
                    f"Rate {rate.code} uses unknown quantity basis "
                    f"'{rate.quantity_basis}' and was skipped.",
                    context=rate.code,
                )
            )
            continue
        if quantity <= 0:
            continue
        items.append(
            CostLineItem(
                code=rate.code,
                stage=rate.stage,
                category=rate.category,
                item=rate.item,
                unit=rate.unit,
                quantity=quantity,
                unit_cost_usd=rate.unit_cost_usd,
                note=rate.note,
            )
        )
    if resolved.mobilisation_distance_km <= 0:
        flags.append(
            DataFlag(
                "info",
                "no_mobilisation_distance",
                "Mobilisation distance is zero; transport costs are not "
                "included. Enter the one way distance from the "
                "contractor's base to the site.",
            )
        )
    return CostEstimate(
        items=items,
        inputs=resolved,
        overheads_percent=overheads_percent,
        margin_percent=margin_percent,
        contingency_percent=contingency_percent,
        vat_percent=vat_percent,
        exchange_rate_sle_per_usd=exchange_rate_sle_per_usd,
        assumptions=assumptions,
        flags=flags,
    )
