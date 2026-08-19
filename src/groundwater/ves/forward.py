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

      rho_a(a) = 2 a * [F(a) - F(2a)]

The integrals are evaluated by direct quadrature on a hybrid
logarithmic + linear abscissa after subtracting the half space
asymptote (``T -> rho_1`` for large lambda), which makes the integrand
decay exponentially. This avoids relying on tabulated digital filter
coefficients and is validated against the analytic two layer image
series in the test suite (agreement better than 0.2 percent).
"""

from __future__ import annotations

import math

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
    T = np.full(lam.shape, rho[-1], dtype=float)
    for i in range(len(h) - 1, -1, -1):
        # T <- (T + rho_i tanh) / (1 + T tanh / rho_i), written a step at a
        # time so the recurrence allocates two arrays per layer instead of
        # eight. This is the innermost loop of the whole VES stage - an
        # inversion runs it a few hundred thousand times over arrays of a
        # few thousand abscissas - and the arithmetic is unchanged.
        th = lam * h[i]
        np.tanh(th, out=th)
        denom = T * th
        th *= rho[i]
        th += T
        denom /= rho[i]
        denom += 1.0
        th /= denom
        T = th
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

# The quadrature runs out to the largest tabulated Bessel zero. A sounding
# needs panels out to 9 * (AB/2) / h_min, so 1200 zeros (largest abscissa
# 3770.7) covers spacings up to about 419 times the thinnest layer. Beyond
# that the table is grown on demand: truncating the integral part-way
# through an oscillation of J1 leaves a large spurious residue - at AB/2 =
# 1000 m over a 0.5 m layer the model returned 574 ohm-m instead of 30.
# The inversion explores thin layers, so it can walk into that regime.
# Growth ceiling. 60000 zeros reach x = 188495, covering spacings up to about
# 20900 times the thinnest layer - far past anything a real sounding sees, and
# bounded so the browser build cannot be made to allocate without limit.
_MAX_ZEROS = 60_000

# Floor on the layer thickness used to size the decay scale. The inversion
# bounds thicknesses at 0.2 m; this only guards a hand-built degenerate model.
_MIN_DECAY_H = 0.02


def _build_tables(order: int, n_zeros: int = _N_ZEROS):
    zeros = jn_zeros(order, n_zeros)
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
        "panel_ends": zeros[1:],
    }


_TABLES = {0: _build_tables(0), 1: _build_tables(1)}


def _table_for(order: int, x_stop: float) -> dict:
    """Quadrature table for ``order`` reaching at least ``x_stop``.

    Grows (and caches) the table rather than truncating the integral, which
    silently returned resistivities an order of magnitude wrong.
    """
    table = _TABLES[order]
    if table["panel_ends"][-1] >= x_stop or len(table["panel_ends"]) + 1 >= _MAX_ZEROS:
        return table
    # zeros of J are spaced about pi apart, so this is the count that reaches
    # x_stop, with headroom so a sweep of spacings does not rebuild each time
    needed = min(int(x_stop / math.pi) + 32, _MAX_ZEROS)
    needed = min(max(needed, 2 * (len(table["panel_ends"]) + 1)), _MAX_ZEROS)
    table = _build_tables(order, needed)
    _TABLES[order] = table
    return table


# Largest integrand buffer a batch may allocate, in abscissas. A batch is
# evaluated in groups small enough to stay under it, so a sounding that walks
# the quadrature table out to its ceiling cannot make the browser build
# allocate hundreds of megabytes.
_BATCH_ABSCISSA_CAP = 2_000_000


def _hankel_integrals(g, order: int, x_decays: np.ndarray) -> np.ndarray:
    """Int_0^inf g_j(x) J_order(x) dx for a batch of decay scales.

    ``g(x, rows)`` returns the integrand of the members named by ``rows`` at
    the abscissas ``x``, as a ``(len(rows), len(x))`` array. Each member j
    decays like ``exp(-x / x_decays[j])`` at large x, so they need the
    quadrature carried to different distances.

    A sounding is a batch: one layered model sampled at every AB/2 the field
    team walked out to. Evaluated one member at a time, the resistivity
    transform is a separate pass each - and at these sizes, a few hundred to
    a few thousand abscissas, numpy spends longer entering and leaving its
    element loops than running them. So the members are evaluated together.

    Section 1 shares its abscissas across the whole batch. Section 2 does
    not, because members reach different distances, so it is walked in bands
    and each band is evaluated once for exactly the members that reach it.
    No member is integrated further than it would have been alone, and none
    pays for a member that reaches further.

    The sum is still taken one member at a time, over that member's own
    abscissas. Adding the members' contributions in a matrix product instead
    would reassociate the sum, and the inversion's numerical Jacobian takes
    differences over a 1e-4 step, so it turns a last-bit change in the
    forward model into a visible one in the fitted layer.
    """
    x_decays = np.asarray(x_decays, dtype=float)
    x_stop = 18.0 * np.maximum(x_decays, 1.0)
    t = _table_for(order, float(x_stop.max()))
    n_panels = np.searchsorted(t["panel_ends"], x_stop) + 1
    n_panels = np.clip(n_panels, 8, len(t["panel_ends"]))
    ends = n_panels * 10  # last section 2 abscissa each member integrates to

    s1_nodes, s1_wb = t["s1_nodes"], t["s1_wb"]
    s2_nodes, s2_wb = t["s2_nodes"], t["s2_wb"]
    acc = np.empty(len(x_decays), dtype=float)
    by_reach = np.argsort(ends, kind="stable")

    for group in _reach_groups(ends, by_reach):
        span = int(ends[group[-1]])  # the furthest reach in this group
        section1 = g(s1_nodes, group)
        section2 = np.empty((len(group), span), dtype=float)
        lo = 0
        for position, member in enumerate(group):
            hi = int(ends[member])
            if hi <= lo:
                continue  # another member reaches exactly this far
            reaching = group[position:]
            section2[position:, lo:hi] = g(s2_nodes[lo:hi], reaching)
            lo = hi
        for position, member in enumerate(group):
            k = int(ends[member])
            acc[member] = float(np.dot(section1[position], s1_wb)) + float(
                np.dot(section2[position, :k], s2_wb[:k])
            )
    return acc


def _reach_groups(ends: np.ndarray, by_reach: np.ndarray):
    """Members in reach order, split so no group's buffer exceeds the cap."""
    if not len(by_reach):
        return
    start = 0
    for position in range(1, len(by_reach)):
        # the buffer is sized by the group's furthest member, which in reach
        # order is whichever one is added last
        if (position - start + 1) * int(
            ends[by_reach[position]]
        ) > _BATCH_ABSCISSA_CAP:
            yield by_reach[start:position]
            start = position
    yield by_reach[start:]


def forward_schlumberger(
    model: LayeredModel | tuple, ab2: np.ndarray
) -> np.ndarray:
    """Ideal (gradient) Schlumberger apparent resistivity at AB/2 values."""
    rho, h = _model_arrays(model)
    ab2 = np.atleast_1d(np.asarray(ab2, dtype=float))
    h_min = float(h[0]) if len(h) else 1.0
    # substitute x = lambda L: rho_a = rho1 + Int (T(x/L) - rho1) J1(x) x dx
    # (the L^2 prefactor cancels against the 1/L^2 from the substitution)
    def g(x, rows):
        lam = x[None, :] / ab2[rows][:, None]
        integrand = resistivity_transform(lam, rho, h)
        integrand -= rho[0]
        integrand *= x[None, :]
        return integrand

    # (T - rho1) decays like exp(-2 lambda h_min) = exp(-x / (L / (2 h_min)))
    decay = ab2 / (2.0 * max(h_min, _MIN_DECAY_H))
    return rho[0] + _hankel_integrals(g, 1, decay)


def _potential_integrals(rho, h, r: np.ndarray, h_min: float) -> np.ndarray:
    """F(r) = Int T(lam) J0(lam r) dlam, for every radius in ``r`` at once.

    ``F(r) = (rho1 + Int (T - rho1) J0(x) dx) / r``.
    """
    r = np.atleast_1d(np.asarray(r, dtype=float))

    def g(x, rows):
        lam = x[None, :] / r[rows][:, None]
        integrand = resistivity_transform(lam, rho, h)
        integrand -= rho[0]
        return integrand

    decay = r / (2.0 * max(h_min, _MIN_DECAY_H))
    return (rho[0] + _hankel_integrals(g, 0, decay)) / r


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
    h_min = float(h[0]) if len(h) else 1.0
    out = np.empty_like(ab2)

    b = mn / 2.0
    usable = np.isfinite(b) & (b > 0) & (b < ab2)
    if not np.all(usable):
        # an MN that cannot be used falls back to the ideal gradient value
        idx = np.nonzero(~usable)[0]
        out[idx] = forward_schlumberger((rho, h), ab2[idx])
    if np.any(usable):
        idx = np.nonzero(usable)[0]
        L, half = ab2[idx], b[idx]
        # the inner and outer potential radii of every reading at once
        f = _potential_integrals(
            rho, h, np.concatenate([L - half, L + half]), h_min
        )
        n = len(idx)
        out[idx] = (L**2 - half**2) / (2.0 * half) * (f[:n] - f[n:])
    return out


def forward_wenner(model: LayeredModel | tuple, a: np.ndarray) -> np.ndarray:
    """Wenner apparent resistivity at spacings a."""
    rho, h = _model_arrays(model)
    a = np.atleast_1d(np.asarray(a, dtype=float))
    h_min = float(h[0]) if len(h) else 1.0
    # both radii of every spacing in one quadrature pass
    f = _potential_integrals(rho, h, np.concatenate([a, 2.0 * a]), h_min)
    n = len(a)
    # rho_a = 2 pi a (V_M - V_N)/I; with A and B both contributing,
    # V_M - V_N = (I/pi) (F(a) - F(2a)), so rho_a = 2 a (F(a) - F(2a)).
    return 2.0 * a * (f[:n] - f[n:])


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
