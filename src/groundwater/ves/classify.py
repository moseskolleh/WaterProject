"""Sounding curve type classification (H, K, A, Q and combinations).

For three layers the classical types are

* H: rho1 > rho2 < rho3 (conductive middle layer)
* K: rho1 < rho2 > rho3 (resistive middle layer)
* A: rho1 < rho2 < rho3 (ascending)
* Q: rho1 > rho2 > rho3 (descending)

Models with more layers are classified by the sequence of overlapping
three layer triplets, giving the usual combined names such as HK, KH,
HKH or QQ.
"""

from __future__ import annotations

import numpy as np

from ..models import LayeredModel

__all__ = ["classify_curve", "describe_curve_type"]

_TRIPLET = {
    (1, 0): "K",  # up then down
    (0, 1): "H",  # down then up
    (1, 1): "A",  # up, up
    (0, 0): "Q",  # down, down
}


def classify_curve(model: LayeredModel) -> str:
    """Curve type letters for a layered model.

    Two layer models return "2-layer ascending" or "2-layer
    descending"; models with three or more layers return letter codes.
    """
    rho = np.asarray(model.resistivities, dtype=float)
    if len(rho) < 2:
        return "uniform"
    if len(rho) == 2:
        return "2-layer ascending" if rho[1] > rho[0] else "2-layer descending"
    letters = []
    for i in range(len(rho) - 2):
        up1 = 1 if rho[i + 1] > rho[i] else 0
        up2 = 1 if rho[i + 2] > rho[i + 1] else 0
        letters.append(_TRIPLET[(up1, up2)])
    return "".join(letters)


_DESCRIPTIONS = {
    "H": "a conductive layer between two more resistive layers, the classical "
    "signature of a saturated weathered zone above fresh basement",
    "K": "a resistive layer between two more conductive layers, often dry "
    "laterite or duricrust over a conductive saprolite",
    "A": "resistivity increasing with depth, typical of progressively less "
    "weathered rock towards fresh basement",
    "Q": "resistivity decreasing with depth, typical of deepening weathering "
    "or increasing saturation with depth",
}


def describe_curve_type(curve_type: str) -> str:
    """Short hydrogeological reading of a curve type for report text."""
    if curve_type.startswith("2-layer"):
        direction = "ascending" if "ascending" in curve_type else "descending"
        if direction == "descending":
            return (
                "a two layer response with resistivity decreasing at depth, "
                "consistent with weathered or fractured, possibly water bearing "
                "rock beneath a resistive surface layer"
            )
        return (
            "a two layer response with resistivity increasing at depth, "
            "consistent with more competent rock beneath the surface layer"
        )
    parts = [f"type {curve_type}"]
    seen = []
    for letter in curve_type:
        if letter in _DESCRIPTIONS and letter not in seen:
            seen.append(letter)
            parts.append(_DESCRIPTIONS[letter])
    return "; ".join(parts)
