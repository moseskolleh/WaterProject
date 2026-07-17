"""Price sensitivity: re-estimate with one input moved at a time.

The output feeds a tornado chart, the standard way to show a client
which assumptions actually move the contract price and which are
noise.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .model import CostingInputs, RateItem, estimate_borehole_cost


@dataclass
class SensitivityEntry:
    label: str
    low_price_usd: float
    high_price_usd: float

    @property
    def span_usd(self) -> float:
        return abs(self.high_price_usd - self.low_price_usd)


def price_sensitivity(
    inputs: CostingInputs,
    rates: list[RateItem] | None = None,
    **kwargs,
) -> tuple[float, list[SensitivityEntry]]:
    """(base price, entries) with one driver varied per entry.

    Varies depth +-20%, mobilisation distance +-50%, overburden +-50%
    (when stated), and the margin and overheads percentages +-5 points.
    ``kwargs`` are passed through to ``estimate_borehole_cost`` and
    must hold the same percentages the base estimate used. Derived
    quantities (casing, gravel, crew days) follow each variation
    through the usual rules of thumb.
    """

    def price(varied: CostingInputs, **overrides) -> float:
        merged = {**kwargs, **overrides}
        return estimate_borehole_cost(varied, rates, **merged).price_usd

    base_price = price(inputs)
    entries: list[SensitivityEntry] = []

    depth = float(inputs.total_depth_m)
    entries.append(SensitivityEntry(
        "Total depth ±20%",
        price(replace(inputs, total_depth_m=0.8 * depth)),
        price(replace(inputs, total_depth_m=1.2 * depth)),
    ))

    distance = float(inputs.mobilisation_distance_km or 0.0)
    if distance > 0:
        entries.append(SensitivityEntry(
            "Mobilisation distance ±50%",
            price(replace(inputs, mobilisation_distance_km=0.5 * distance)),
            price(replace(inputs, mobilisation_distance_km=1.5 * distance)),
        ))

    if inputs.overburden_m:
        over = float(inputs.overburden_m)
        entries.append(SensitivityEntry(
            "Overburden ±50%",
            price(replace(inputs, overburden_m=0.5 * over)),
            price(replace(inputs, overburden_m=1.5 * over)),
        ))

    margin = float(kwargs.get("margin_percent", 20.0))
    entries.append(SensitivityEntry(
        "Margin ±5 points",
        price(inputs, margin_percent=max(0.0, margin - 5.0)),
        price(inputs, margin_percent=margin + 5.0),
    ))

    overheads = float(kwargs.get("overheads_percent", 15.0))
    entries.append(SensitivityEntry(
        "Overheads ±5 points",
        price(inputs, overheads_percent=max(0.0, overheads - 5.0)),
        price(inputs, overheads_percent=overheads + 5.0),
    ))

    entries.sort(key=lambda e: e.span_usd, reverse=True)
    return base_price, entries
