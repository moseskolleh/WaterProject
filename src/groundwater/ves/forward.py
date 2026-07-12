"""1D layered earth forward modelling for resistivity soundings.

The apparent resistivity over a stack of horizontal layers is obtained
from the resistivity transform ``T(lambda)`` (Koefoed recurrence) and
a Hankel transform:

* ideal Schlumberger (gradient array, MN -> 0)::

      rho_a(L) = L^2 * Int_0^inf T(lam) J1(lam L) lam dlam

* finite MN Schlumberger, from the surface potential
  ``F(r) = Int_0^inf T(lam) J0(lam r) dlam``::

      rho_a = (L^2 - b^2) / (2 b) * [F(L - b) - F(L + b)],  b = MN/2

* Wenner::

      rho_a(a) = 2 a * [F_hat(a) - F_hat(2a)],  F_hat(r) = r F(r) / 1

The integrals are evaluated by direct quadrature on a hybrid
logarithmic + linear abscissa after subtracting the half space
asymptote (``T -> rho_1`` for large lambda), which makes the integrand
decay exponentially. This avoids relying on tabulated digital filter
coefficients and is validated against the analytic two layer image
series in the test suite (agreement better than 0.2 percent).
"""

from __future__ import annotations

import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.special import j0, j1, jn_zeros

from ..models import LayeredModel, VESSounding

__all__ = [
    "resistivity_transform",
    "forward_schlumberger",
    "forward_schlumberger_finite_mn",
    "forward_wenner",
    "forward_for_sounding",
    "two_layer_schlumberger_series",
]


def resistivity_transform(
    lam: np.ndarray, resistivities: np.ndarray, thicknesses: np.ndarray
) -> np.ndarray:
    """Koefoed/Pekeris recurrence for the resistivity transform T(lambda).

    Stable downward recurrence starting from the half space:
    ``T_n = rho_n``;
    ``T_i = (T_{i+1} + rho_i tanh(lam h_i)) / (1 + T_{i+1} tanh(lam h_i) / rho_i)``.
    """
    lam = np.asarray(lam, dtype=float)
    rho = np.asarray(resistivities, dtype=float)
    h = np.asarray(thicknesses, dtype=float)
    T = np.full_like(lam, rho[-1])
    for i in range(len(h) - 1, -1, -1):
        th = np.tanh(lam * h[i])
        T = (T + rho[i] * th) / (1.0 + T * th / rho[i])
    return T


# ---------------------------------------------------------------------------
# Hankel integration machinery
#
# Integrals of the form Int_0^inf g(x) Jn(x) dx with g smooth and
# exponentially decaying are computed in two sections:
#
# * x in (0, z1), z1 the first zero of Jn: composite Gauss-Legendre on
#   log-subdivided panels. The resistivity transform varies over about
#   a decade of lambda, so sub-decade panels resolve it for any layer
#   thickness / spacing ratio.
# * x > z1: 10 point Gauss-Legendre panels between consecutive zeros
#   of Jn. Within a half period the integrand is smooth, so each panel
#   is near exact. The number of panels follows the exponential decay
#   scale of (T - rho1).
#
# Nodes and (weight x Bessel) products are precomputed once per order,
# so each integral is two vectorised evaluations of g.
# ---------------------------------------------------------------------------

_N_ZEROS = 1200


def _build_tables(order: int):
    zeros = jn_zeros(order, _N_ZEROS)
    bessel = j0 if order == 0 else j1

    # section 1: 14 log-spaced panels from 1e-6 to the first zero, GL-8
    nodes8, weights8 = leggauss(8)
    edges = np.geomspace(1e-6, zeros[0], 15)
    s1_nodes, s1_wb = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mid, half = 0.5 * (lo + hi), 0.5 * (hi - lo)
        x = mid + half * nodes8
        s1_nodes.append(x)
        s1_wb.append(half * weights8 * bessel(x))

    # section 2: GL-10 between consecutive zeros
    nodes10, weights10 = leggauss(10)
    s2_nodes, s2_wb = [], []
    lo = zeros[0]
    for hi in zeros[1:]:
        mid, half = 0.5 * (lo + hi), 0.5 * (hi - lo)
        x = mid + half * nodes10
        s2_nodes.append(x)
        s2_wb.append(half * weights10 * bessel(x))
        lo = hi
    return {
        "s1_nodes": np.concatenate(s1_nodes),
        "s1_wb": np.concatenate(s1_wb),
        "s2_nodes": np.concatenate(s2_nodes),
        "s2_wb": np.concatenate(s2_wb),
        "panel_ends": jn_zeros(order, _N_ZEROS)[1:],
    }


_TABLES = {0: _build_tables(0), 1: _build_tables(1)}


def _hankel_integral(g, order: int, x_decay: float) -> float:
    """Int_0^inf g(x) J_order(x) dx for smooth g decaying like
    exp(-x / x_decay) at large x."""
    t = _TABLES[order]
    acc = float(np.dot(g(t["s1_nodes"]), t["s1_wb"]))
    x_stop = 18.0 * max(x_decay, 1.0)
    n_panels = int(np.searchsorted(t["panel_ends"], x_stop)) + 1
    n_panels = min(max(n_panels, 8), len(t["panel_ends"]))
    k = n_panels * 10
    acc += float(np.dot(g(t["s2_nodes"][:k]), t["s2_wb"][:k]))
    return acc


def forward_schlumberger(
    model: LayeredModel | tuple, ab2: np.ndarray
) -> np.ndarray:
    """Ideal (gradient) Schlumberger apparent resistivity at AB/2 values."""
    rho, h = _model_arrays(model)
    ab2 = np.atleast_1d(np.asarray(ab2, dtype=float))
    h_min = float(np.min(h)) if len(h) else 1.0
    out = np.empty_like(ab2)
    for i, L in enumerate(ab2):
        # substitute x = lambda L: rho_a = rho1 + Int (T(x/L) - rho1) J1(x) x dx
        # (the L^2 prefactor cancels against the 1/L^2 from the substitution)
        def g(x, L=L):
            return (resistivity_transform(x / L, rho, h) - rho[0]) * x

        # (T - rho1) decays like exp(-2 lambda h_min) = exp(-x / (L / (2 h_min)))
        out[i] = rho[0] + _hankel_integral(g, 1, L / (2.0 * max(h_min, 0.1)))
    return out


def _potential_integral(rho, h, r: float, h_min: float) -> float:
    """F(r) = Int T(lam) J0(lam r) dlam = (rho1 + Int (T - rho1) J0(x) dx) / r."""

    def g(x, r=r):
        return resistivity_transform(x / r, rho, h) - rho[0]

    return (rho[0] + _hankel_integral(g, 0, r / (2.0 * max(h_min, 0.1)))) / r


def forward_schlumberger_finite_mn(
    model: LayeredModel | tuple, ab2: np.ndarray, mn: np.ndarray
) -> np.ndarray:
    """Schlumberger apparent resistivity with finite MN spacing.

    Reproduces what the instrument actually measures at each
    (AB/2, MN) pair, including the small jumps at segment changes.
    """
    rho, h = _model_arrays(model)
    ab2 = np.atleast_1d(np.asarray(ab2, dtype=float))
    mn = np.atleast_1d(np.asarray(mn, dtype=float))
    h_min = float(np.min(h)) if len(h) else 1.0
    out = np.empty_like(ab2)
    for i, (L, m) in enumerate(zip(ab2, mn)):
        b = m / 2.0
        if not np.isfinite(b) or b <= 0 or b >= L:
            # fall back to the ideal gradient value
            out[i] = forward_schlumberger((rho, h), np.array([L]))[0]
            continue
        f_in = _potential_integral(rho, h, L - b, h_min)
        f_out = _potential_integral(rho, h, L + b, h_min)
        out[i] = (L**2 - b**2) / (2.0 * b) * (f_in - f_out)
    return out


def forward_wenner(model: LayeredModel | tuple, a: np.ndarray) -> np.ndarray:
    """Wenner apparent resistivity at spacings a."""
    rho, h = _model_arrays(model)
    a = np.atleast_1d(np.asarray(a, dtype=float))
    h_min = float(np.min(h)) if len(h) else 1.0
    out = np.empty_like(a)
    for i, s in enumerate(a):
        f1 = _potential_integral(rho, h, s, h_min)
        f2 = _potential_integral(rho, h, 2.0 * s, h_min)
        # rho_a = 2 pi a (V_M - V_N)/I; with A and B both contributing,
        # V_M - V_N = (I/pi) (F(a) - F(2a)), so rho_a = 2 a (F(a) - F(2a)).
        out[i] = 2.0 * s * (f1 - f2)
    return out


def forward_for_sounding(
    model: LayeredModel | tuple,
    sounding: VESSounding,
    finite_mn: bool = False,
) -> np.ndarray:
    """Model response at a sounding's abscissas."""
    if sounding.array_type.startswith("wenner"):
        return forward_wenner(model, sounding.ab2)
    if finite_mn and np.all(np.isfinite(sounding.mn)):
        return forward_schlumberger_finite_mn(model, sounding.ab2, sounding.mn)
    return forward_schlumberger(model, sounding.ab2)


def two_layer_schlumberger_series(
    rho1: float, rho2: float, h: float, ab2: np.ndarray, n_terms: int = 4000
) -> np.ndarray:
    """Analytic two layer ideal Schlumberger curve from image theory.

    ``rho_a(L) = rho1 [1 + 2 sum_n k^n L^3 / (L^2 + (2 n h)^2)^(3/2)]``
    with reflection coefficient k = (rho2 - rho1) / (rho2 + rho1).
    Used to validate the numerical Hankel evaluation.
    """
    ab2 = np.atleast_1d(np.asarray(ab2, dtype=float))
    k = (rho2 - rho1) / (rho2 + rho1)
    n = np.arange(1, n_terms + 1)[:, None]
    L = ab2[None, :]
    terms = (k**n) * L**3 / (L**2 + (2.0 * n * h) ** 2) ** 1.5
    return rho1 * (1.0 + 2.0 * np.sum(terms, axis=0))


def _model_arrays(model: LayeredModel | tuple) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(model, LayeredModel):
        return model.resistivities, model.thicknesses
    rho, h = model
    return np.asarray(rho, dtype=float), np.asarray(h, dtype=float)
