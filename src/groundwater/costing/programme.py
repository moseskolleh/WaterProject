"""Multi-borehole programme cost estimate.

Follows the procurement guide's contract packaging logic: mobilise the
rig once for the package, move it between nearby sites, and let the
successful wells carry the cost of the expected dry holes. A dry
attempt only incurs the siting, set up and drilling stages; casing,
development, testing and wellhead work happen on successful wells.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import (
    CostEstimate,
    CostingInputs,
    RateItem,
    estimate_borehole_cost,
    load_rates,
)

# Stages a dry (abandoned) attempt still pays for.
_DRY_STAGES = ("Siting", "Mobilisation", "Drilling")


@dataclass
class ProgrammeEstimate:
    """Roll-up for a package of boreholes drilled with one rig."""

    n_successful: int
    n_attempted: int
    success_rate_percent: float
    well_estimate: CostEstimate  # one successful well, transport excluded
    dry_attempt_cost_usd: float
    transport_cost_usd: float
    overheads_percent: float
    margin_percent: float
    contingency_percent: float
    vat_percent: float
    exchange_rate_sle_per_usd: float
    assumptions: list[str] = field(default_factory=list)

    @property
    def direct_cost_usd(self) -> float:
        wells = self.n_successful * self.well_estimate.direct_cost_usd
        dry = (self.n_attempted - self.n_successful) * self.dry_attempt_cost_usd
        return wells + dry + self.transport_cost_usd

    @property
    def total_cost_usd(self) -> float:
        return self.direct_cost_usd * (1 + self.overheads_percent / 100.0)

    @property
    def price_usd(self) -> float:
        return self.total_cost_usd * (1 + self.margin_percent / 100.0)

    @property
    def price_with_vat_usd(self) -> float:
        return self.price_usd * (1 + self.vat_percent / 100.0)

    @property
    def budget_usd(self) -> float:
        return self.price_with_vat_usd * (1 + self.contingency_percent / 100.0)

    @property
    def price_per_successful_well_usd(self) -> float:
        return self.price_with_vat_usd / self.n_successful

    def in_local(self, usd: float) -> float:
        return usd * self.exchange_rate_sle_per_usd

    def summary_rows(self) -> list[tuple[str, str, str]]:
        def pair(usd: float) -> tuple[str, str]:
            return f"{usd:,.0f}", f"{self.in_local(usd):,.0f}"

        rows = [
            (f"Successful boreholes required", f"{self.n_successful}", ""),
            (
                f"Attempts planned ({self.success_rate_percent:g}% success)",
                f"{self.n_attempted}", "",
            ),
            ("Direct works cost", *pair(self.direct_cost_usd)),
            ("- of which transport and moves", *pair(self.transport_cost_usd)),
            (
                "- of which dry attempts",
                *pair((self.n_attempted - self.n_successful) * self.dry_attempt_cost_usd),
            ),
            (f"Total cost (overheads {self.overheads_percent:g}%)",
             *pair(self.total_cost_usd)),
            (f"Contract price (margin {self.margin_percent:g}%)",
             *pair(self.price_usd)),
        ]
        if self.vat_percent:
            rows.append((f"Price including VAT ({self.vat_percent:g}%)",
                         *pair(self.price_with_vat_usd)))
        rows += [
            ("Price per successful borehole", *pair(self.price_per_successful_well_usd)),
            (f"Planning budget (contingency {self.contingency_percent:g}%)",
             *pair(self.budget_usd)),
        ]
        return rows


def estimate_programme_cost(
    per_well: CostingInputs,
    n_boreholes: int,
    *,
    rates: list[RateItem] | None = None,
    inter_site_distance_km: float = 15.0,
    success_rate_percent: float = 100.0,
    overheads_percent: float = 15.0,
    margin_percent: float = 20.0,
    contingency_percent: float = 10.0,
    vat_percent: float = 0.0,
    exchange_rate_sle_per_usd: float | None = None,
) -> ProgrammeEstimate:
    """Cost a package of boreholes sharing one mobilisation.

    ``per_well.mobilisation_distance_km`` is the one way distance from
    the contractor's base to the package area; transport is charged
    once for the package plus one inter-site move per additional
    attempt, at the catalogue's per kilometre rate.
    """
    if n_boreholes < 1:
        raise ValueError("a programme needs at least one borehole")
    if not 0 < success_rate_percent <= 100:
        raise ValueError("success rate must be in (0, 100]")
    rates = rates if rates is not None else load_rates()
    n_attempted = math.ceil(n_boreholes / (success_rate_percent / 100.0))

    # one successful well, without base transport (charged at package level)
    well_inputs = CostingInputs(**{**per_well.__dict__, "mobilisation_distance_km": 0.0})
    kwargs = dict(
        overheads_percent=overheads_percent,
        margin_percent=margin_percent,
        contingency_percent=contingency_percent,
        vat_percent=vat_percent,
    )
    if exchange_rate_sle_per_usd is not None:
        kwargs["exchange_rate_sle_per_usd"] = exchange_rate_sle_per_usd
    well = estimate_borehole_cost(well_inputs, rates, **kwargs)

    dry_cost = sum(v for s, v in well.by_stage() if s in _DRY_STAGES)

    km_rates = [r for r in rates if r.quantity_basis == "per_km_round_trip"]
    km_rate = sum(r.unit_cost_usd for r in km_rates)
    transport_km = 2.0 * per_well.mobilisation_distance_km \
        + max(0, n_attempted - 1) * inter_site_distance_km
    transport = km_rate * transport_km

    assumptions = list(well.assumptions)
    assumptions.append(
        f"One rig mobilised once for the package "
        f"({per_well.mobilisation_distance_km:g} km each way) with "
        f"{max(0, n_attempted - 1)} inter-site moves of "
        f"{inter_site_distance_km:g} km on average."
    )
    if n_attempted > n_boreholes:
        assumptions.append(
            f"{n_attempted - n_boreholes} dry attempt(s) expected at "
            f"{success_rate_percent:g}% siting success; a dry attempt "
            "pays for siting, set up and drilling only, costed at the "
            "full crew time (a conservative allowance)."
        )
    return ProgrammeEstimate(
        n_successful=n_boreholes,
        n_attempted=n_attempted,
        success_rate_percent=success_rate_percent,
        well_estimate=well,
        dry_attempt_cost_usd=dry_cost,
        transport_cost_usd=transport,
        overheads_percent=overheads_percent,
        margin_percent=margin_percent,
        contingency_percent=contingency_percent,
        vat_percent=vat_percent,
        exchange_rate_sle_per_usd=well.exchange_rate_sle_per_usd,
        assumptions=assumptions,
    )
