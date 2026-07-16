"""Drilling enterprise calculators from the RWSN costing guidance.

Implements the worked models in "Costing and Pricing: a Guide for
Water Well Drilling Enterprises" (RWSN 2014-12): rig depreciation on
the 10,000 working hour rule of thumb (Rowles 1995), per metre wear
costs of the drilling string and bits, the amortised loan repayment
used for equipment finance, and the rig cost per well sensitivity.

The guide's example figures (a 170,000 USD rig gives 17 USD/hour
depreciation; drag bit 1.67 USD/m; hammer bit 4.00 USD/m; overburden
running cost 2.42 USD/m and rock 7.42 USD/m) fall straight out of
these functions and are pinned by the test suite.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RigSpec:
    """A drilling rig for depreciation purposes.

    The default lifetime is the 10,000 working hour rule of thumb
    (about 1,000 hours per year over 10 years; at 8 hour days that is
    1,250 working days). Maintenance is taken as 5 percent of
    depreciation, following the guide's Table 3.
    """

    capital_cost_usd: float
    lifetime_hours: float = 10_000.0
    hours_per_day: float = 8.0
    maintenance_fraction: float = 0.05

    @property
    def depreciation_per_hour(self) -> float:
        return self.capital_cost_usd / self.lifetime_hours

    @property
    def depreciation_per_day(self) -> float:
        return self.depreciation_per_hour * self.hours_per_day

    @property
    def maintenance_per_hour(self) -> float:
        return self.depreciation_per_hour * self.maintenance_fraction

    @property
    def hourly_rate(self) -> float:
        """Depreciation plus maintenance, charged per working hour."""
        return self.depreciation_per_hour + self.maintenance_per_hour


@dataclass
class WearItem:
    """A consumable that wears out over drilled metres."""

    name: str
    lifetime_m: float
    replacement_cost_usd: float

    @property
    def cost_per_m(self) -> float:
        return self.replacement_cost_usd / self.lifetime_m


# The guide's Table 3 example wear items.
DRILL_STRING = WearItem("Drilling string", 20_000.0, 15_000.0)
DRAG_BIT = WearItem("Drag bit", 300.0, 500.0)
HAMMER = WearItem("Hammer", 3_000.0, 8_000.0)
HAMMER_BIT = WearItem("Hammer bit", 300.0, 1_200.0)


def running_cost_overburden_per_m(
    string: WearItem = DRILL_STRING, bit: WearItem = DRAG_BIT
) -> float:
    """Per metre wear cost drilling overburden (string plus drag bit)."""
    return string.cost_per_m + bit.cost_per_m


def running_cost_rock_per_m(
    string: WearItem = DRILL_STRING,
    hammer: WearItem = HAMMER,
    bit: WearItem = HAMMER_BIT,
) -> float:
    """Per metre wear cost in hard rock (string, hammer and hammer bit)."""
    return string.cost_per_m + hammer.cost_per_m + bit.cost_per_m


@dataclass
class LoanSummary:
    principal_usd: float
    annual_rate_percent: float
    years: float
    monthly_payment_usd: float
    total_paid_usd: float
    total_interest_usd: float


def loan_schedule(
    principal_usd: float, annual_rate_percent: float, years: float
) -> LoanSummary:
    """Amortised equipment loan (the Excel PMT formula).

    The guide advises planning to repay drilling equipment loans
    within 5 years even when the rig lasts 10, because longer loans
    are hard to find in sub-Saharan Africa and interest mounts.
    """
    months = int(round(years * 12))
    rate = annual_rate_percent / 100.0 / 12.0
    if rate == 0:
        payment = principal_usd / months
    else:
        payment = principal_usd * rate / (1.0 - (1.0 + rate) ** (-months))
    total = payment * months
    return LoanSummary(
        principal_usd=principal_usd,
        annual_rate_percent=annual_rate_percent,
        years=years,
        monthly_payment_usd=payment,
        total_paid_usd=total,
        total_interest_usd=total - principal_usd,
    )


def rig_cost_per_well(
    capital_cost_usd: float, depreciation_years: float, wells_per_year: float
) -> float:
    """Rig capital charged to each well at a given productivity.

    The guide's sensitivity: a 170,000 USD rig depreciated over 5
    years costs 3,400 USD per well at 10 wells/year but only 340 USD
    at 100 wells/year - utilisation drives competitiveness.
    """
    if depreciation_years <= 0 or wells_per_year <= 0:
        raise ValueError("depreciation years and wells per year must be positive")
    return capital_cost_usd / depreciation_years / wells_per_year
