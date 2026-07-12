"""Electrode array geometric factors.

All spacings are in metres and resistances in ohm; apparent
resistivity is returned in ohm-m. ``mn`` is always the full potential
electrode spacing MN, matching the field sheets, not MN/2.
"""

from __future__ import annotations

import numpy as np


def geometric_factor(
    array_type: str,
    ab2: float | np.ndarray | None = None,
    mn: float | np.ndarray | None = None,
    a: float | np.ndarray | None = None,
    n: float | np.ndarray | None = None,
) -> np.ndarray:
    """Geometric factor K such that rho_a = K * (delta V / I).

    Parameters
    ----------
    array_type:
        "schlumberger", "wenner", "dipole-dipole" or "pole-pole".
    ab2:
        Half current electrode spacing AB/2 (Schlumberger).
    mn:
        Full potential electrode spacing MN (Schlumberger).
    a:
        Electrode spacing (Wenner) or dipole length (dipole-dipole,
        pole-pole).
    n:
        Dipole separation multiplier (dipole-dipole).

    For the Schlumberger array with finite MN the exact factor is
    ``K = pi (L^2 - b^2) / (2 b)`` with L = AB/2 and b = MN/2.
    """
    kind = array_type.strip().lower()
    if kind.startswith("schlum"):
        if ab2 is None or mn is None:
            raise ValueError("Schlumberger needs ab2 and mn")
        L = np.asarray(ab2, dtype=float)
        b = np.asarray(mn, dtype=float) / 2.0
        if np.any(b <= 0) or np.any(L <= b):
            raise ValueError("Require 0 < MN/2 < AB/2 for Schlumberger")
        return np.pi * (L**2 - b**2) / (2.0 * b)
    if kind.startswith("wenner"):
        if a is None:
            raise ValueError("Wenner needs the spacing a")
        return 2.0 * np.pi * np.asarray(a, dtype=float)
    if kind.startswith("dipole"):
        if a is None or n is None:
            raise ValueError("dipole-dipole needs a and n")
        a_arr = np.asarray(a, dtype=float)
        n_arr = np.asarray(n, dtype=float)
        return np.pi * n_arr * (n_arr + 1) * (n_arr + 2) * a_arr
    if kind.startswith("pole-pole") or kind.startswith("pole pole"):
        if a is None:
            raise ValueError("pole-pole needs the spacing a")
        return 2.0 * np.pi * np.asarray(a, dtype=float)
    raise ValueError(f"Unknown array type: {array_type}")


def apparent_resistivity(
    array_type: str,
    resistance_ohm: float | np.ndarray,
    **spacings,
) -> np.ndarray:
    """Apparent resistivity from measured resistance (delta V / I)."""
    K = geometric_factor(array_type, **spacings)
    return K * np.asarray(resistance_ohm, dtype=float)
