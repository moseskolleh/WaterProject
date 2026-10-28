"""The VES forward model and inversion, held to what an audit of them found.

Each test names what was wrong. The forward model's are measured against
references that share none of its quadrature: the two-layer image series,
and Gauss-Legendre on every half-period of the Bessel function carried 80
decay lengths of the thinnest layer out, far past the engine's cut.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest
from numpy.polynomial.legendre import leggauss
from scipy.special import j1, jn_zeros

from groundwater.config import VESConfig
from groundwater.models import LayeredModel, SiteMetadata, VESSounding
from groundwater.ves import forward, inversion
from groundwater.ves.cache import _digest, cache_entry, cached_inversion, inversion_key
from groundwater.ves.forward import (
    forward_schlumberger,
    forward_schlumberger_finite_mn,
    forward_wenner,
    resistivity_transform,
    two_layer_schlumberger_series,
)
from groundwater.ves.inversion import (
    STOPS,
    UNRESOLVED_FACTOR,
    _parameter_uncertainty,
    _stationary,
    invert_model,
    invert_sounding,
    inversion_readings,
    most_layers,
)


def _sounding(ab2, rho, mn=None, sounding_id="T"):
    ab2 = np.asarray(ab2, dtype=float)
    return VESSounding(
        site=SiteMetadata(), sounding_id=sounding_id, ab2=ab2,
        mn=np.full(ab2.size, np.nan) if mn is None else np.asarray(mn, dtype=float),
        rho_app=np.asarray(rho, dtype=float),
    )


def _reference_schlumberger(rho, h, ab2, decays=80.0):
    """Gauss-Legendre (24 points) on 300 log panels below the first zero of
    J1 and on every half-period after it, out to ``decays`` decay lengths of
    the thinnest layer."""
    rho, h = np.asarray(rho, float), np.asarray(h, float)
    nodes, weights = leggauss(24)
    out = []
    for L in np.atleast_1d(ab2):
        x_end = max(decays * L / (2.0 * h.min()), 200.0)
        zeros = jn_zeros(1, int(x_end / np.pi) + 5)
        edges = np.concatenate([np.geomspace(1e-12, zeros[0], 301), zeros[1:]])
        lo, hi = edges[:-1, None], edges[1:, None]
        x = (0.5 * (lo + hi) + 0.5 * (hi - lo) * nodes).ravel()
        w = (0.5 * (hi - lo) * weights).ravel()
        g = (resistivity_transform(x / L, rho, h) - rho[0]) * x * j1(x) * w
        out.append(rho[0] + float(np.sum(g[::-1])))
    return np.array(out)


def _wenner_image_series(rho1, rho2, h, a, n_terms=1_000_000):
    """rho_a = rho1 [1 + 4 sum k^n (1 / sqrt(1 + u^2) - 1 / sqrt(4 + u^2))],
    u = 2 n h / a: the two-layer Wenner curve from image theory."""
    k = (rho2 - rho1) / (rho2 + rho1)
    n = np.arange(1, n_terms + 1, dtype=float)[:, None]
    u = 2.0 * n * h / np.asarray(a, float)[None, :]
    terms = k**n * (1.0 / np.sqrt(1.0 + u**2) - 1.0 / np.sqrt(4.0 + u**2))
    return rho1 * (1.0 + 4.0 * np.sum(terms, axis=0))


# ------------------------------------------------------------------ forward


def test_a_resistive_top_layer_is_integrated_well_below_the_reading_error():
    """The cut at 18 decay lengths left 5 to 7e-8 x (rho1 / rho_a) x
    sqrt(AB/2 / h1): 150,000 ohm-m over 10 ohm-m under a 0.5 m top layer was
    2.7 percent out at AB/2 = 300 m. The cut now reaches as far as the
    contrast needs."""
    L = np.array([10.0, 100.0, 300.0])
    exact = two_layer_schlumberger_series(150000.0, 10.0, 0.5, L, n_terms=1_000_000)
    model = (np.array([150000.0, 10.0]), np.array([0.5]))
    assert np.max(np.abs(forward_schlumberger(model, L) / exact - 1.0)) < 1e-7


@pytest.mark.parametrize("rho,h", [
    ([5000.0, 10.0, 10.0], [0.5, 15.0]),           # the worst of the audit's 576
    ([150000.0, 100.0, 10.0], [0.5, 15.0]),
    ([300.0, 50.0, 5000.0, 2000.0], [5.0, 3.0, 0.5]),  # thin and resistive at depth
    ([10.0, 150000.0, 10.0], [3.0, 0.5]),
])
def test_the_forward_model_holds_to_a_reference_without_a_cut(rho, h):
    """The cut follows the top layer, whose thickness alone sets how fast the
    integrand decays; a thin layer deeper down no longer moves it. The
    reference integrates 80 decay lengths of the thinnest layer whatever its
    depth, so it is not built on that argument."""
    ab2 = np.array([1.0, 5.0, 30.0, 100.0, 300.0])
    numeric = forward_schlumberger((np.array(rho), np.array(h)), ab2)
    assert np.max(np.abs(numeric / _reference_schlumberger(rho, h, ab2) - 1.0)) < 1e-7


def test_the_forward_model_has_no_steps_for_the_jacobian_to_read():
    """Where the cut crossed a Bessel zero, rho_a stepped. Over 100
    Jacobian-sized steps of h1 (5000 over 10 ohm-m, h1 = 0.5 m, AB/2 300 m),
    17 forward-difference slopes were +-17.7 where the true slope is 0.00002.
    And a deep thin layer, which set the old cut, no longer steps it: with
    0.5 m of 300 ohm-m at 3.55 m, under 0.55 m of 5000 ohm-m and 3 m of 10,
    the slopes against that layer's thickness spread over 0.10 in 100 steps
    (AB/2 300 m), where they now vary by 4e-5."""
    L = np.array([300.0])
    hs = 0.5 * np.exp(np.arange(100) * inversion.JACOBIAN_STEP)
    values = [forward_schlumberger(([5000.0, 10.0], [h]), L)[0] for h in hs]
    slopes = np.diff(np.log(values)) / inversion.JACOBIAN_STEP
    assert np.max(np.abs(slopes)) < 0.01

    h3 = 0.5 * np.exp(np.arange(100) * inversion.JACOBIAN_STEP)
    values = [forward_schlumberger(([5000.0, 10.0, 300.0, 2000.0], [0.55, 3.0, h]),
                                   L)[0] for h in h3]
    slopes = np.diff(np.log(values)) / inversion.JACOBIAN_STEP
    assert np.max(slopes) - np.min(slopes) < 1e-3


def test_the_potential_integral_starts_at_zero():
    """Section 1 of the J0 integral began at x = 1e-6 and left out about
    (rho_n - rho1) x 1e-6 of it, which a Wenner reading, a difference of two
    potentials, carries whole: 5e-4 relative for 5000 over 10 ohm-m at
    a = 100 m."""
    a = np.array([10.0, 100.0])
    exact = _wenner_image_series(5000.0, 10.0, 2.0, a)
    numeric = forward_wenner((np.array([5000.0, 10.0]), np.array([2.0])), a)
    assert np.max(np.abs(numeric / exact - 1.0)) < 1e-6

    rho1, rho2, h = 5000.0, 10.0, 0.5
    k = (rho2 - rho1) / (rho2 + rho1)
    n = np.arange(1, 1_000_001, dtype=float)

    def potential(r):  # F(r) of a two-layer earth, by image theory
        return rho1 * (1.0 / r + 2.0 * np.sum(k**n / np.sqrt(r**2 + (2.0 * n * h) ** 2)))

    L, b = 20.0, 1.0
    exact = (L**2 - b**2) / (2.0 * b) * (potential(L - b) - potential(L + b))
    numeric = forward_schlumberger_finite_mn(
        (np.array([rho1, rho2]), np.array([h])), np.array([L]), np.array([2.0 * b]))
    assert abs(numeric[0] / exact - 1.0) < 1e-6


@pytest.mark.parametrize("h1", [60.0, 300.0])
def test_the_potential_integral_holds_under_a_thick_conductive_cover(h1):
    """Below x = r / (rho_n S), S = h1 / rho1, the potential integrand is the
    whole rho_n - rho1, and the tables took (0, 1e-6) as one Gauss-Legendre
    panel. At the corner of the inversion's bounds, 0.5 ohm-m on 200,000
    ohm-m, that point is 8e-9 for a 1 m radius under 300 m of cover: Wenner
    was 1.1e-3 out at a = 1 m, and finite MN (MN 0.4 m) 1.1e-3 at AB/2 = 1 m
    (6.0e-4 and 3.5e-4 at a = 0.5 m and AB/2 = 1 m under 60 m). The J0 panels
    now run down to 1e-14, and both are within 3e-10."""
    rho1, rho2 = 0.5, 200000.0
    model = (np.array([rho1, rho2]), np.array([h1]))
    a = np.array([0.5, 1.0, 3.0, 10.0])
    exact = _wenner_image_series(rho1, rho2, h1, a)
    assert np.max(np.abs(forward_wenner(model, a) / exact - 1.0)) < 1e-8

    k = (rho2 - rho1) / (rho2 + rho1)
    n = np.arange(1, 1_000_001, dtype=float)

    def potential(r):  # F(r) of a two-layer earth, by image theory
        return rho1 * (1.0 / r + 2.0 * np.sum(k**n / np.sqrt(r**2 + (2.0 * n * h1) ** 2)))

    L, b = np.array([1.0, 2.0, 4.0]), 0.2
    exact = np.array([(x**2 - b**2) / (2.0 * b) * (potential(x - b) - potential(x + b))
                      for x in L])
    numeric = forward_schlumberger_finite_mn(model, L, np.full(L.size, 2.0 * b))
    assert np.max(np.abs(numeric / exact - 1.0)) < 1e-8


def test_the_potential_table_reaches_below_every_cover_the_inversion_can_fit():
    """The J0 table's panels stop at forward._J0_FLOOR, which is exact only
    while x = r / (rho_n S) stays above it. Held here with room to spare -
    ten layers at the inversion's bounds and a 1 mm radius - so that
    widening the bounds cannot quietly leave the floor too high."""
    rho_lo, rho_hi = inversion._RHO_BOUNDS
    cover = 9 * inversion._H_BOUNDS[1] / rho_lo  # S over the basement, siemens
    assert 1e-3 / (rho_hi * cover) > 10.0 * forward._J0_FLOOR


def test_the_cut_never_falls_short_of_eighteen_decay_lengths():
    assert forward._cut(1000.0, 1.0) >= 18.0 * 1000.0
    assert forward._cut(0.01, 1.0) >= 18.0  # a decay under 1 is taken as 1
    # more contrast, further out; a deeper thin layer changes nothing
    near = forward._cuts(np.array([100.0]), np.array([100.0, 10.0]), np.array([1.0]))
    far = forward._cuts(np.array([100.0]), np.array([100000.0, 10.0]), np.array([1.0]))
    assert far[0] > near[0]
    deep = forward._cuts(np.array([100.0]), np.array([100.0, 10.0, 50.0]), np.array([1.0, 0.2]))
    assert deep[0] == near[0]


# --------------------------------------------------------- how many layers


def _few(n_readings):
    ab2 = np.array([1.5, 3.0, 6.0, 10.0, 20.0, 40.0, 80.0])[:n_readings]
    true = (np.array([800.0, 40.0, 2000.0]), np.array([3.0, 15.0]))
    noise = np.array([1.02, 0.97, 1.03, 0.98, 1.01, 0.99, 1.02])[:n_readings]
    return _sounding(ab2, forward_schlumberger(true, ab2) * noise, sounding_id="F")


@pytest.mark.parametrize("n_readings", [4, 5])
def test_a_short_sounding_is_not_fitted_with_a_parameter_per_reading(n_readings):
    """Four readings were fitted with a three-layer model's five parameters:
    0.00003 percent, which the parsimony rule then preferred to the two-layer
    model's 2.1 percent, with every uncertainty factor 1.0 and confidence 1.0,
    and a 9.8 ohm-m clay below 3.5 m in an 800 / 40 / 2000 ohm-m earth. A
    model now keeps at least one degree of freedom."""
    result = invert_sounding(_few(n_readings))
    assert result.model.n_layers == 2
    assert [n for n, _err in result.trials] == [2]
    assert result.fit_error_percent > 1.0
    factors = np.concatenate([result.rho_uncertainty_factor, result.h_uncertainty_factor])
    assert np.any(factors > 1.01)


def test_six_readings_may_carry_three_layers():
    assert [most_layers(m) for m in (4, 5, 6, 7, 8, 30)] == [2, 2, 3, 3, 4, 15]
    trials = invert_sounding(_few(6)).trials
    assert max(n for n, _err in trials) <= 3


def test_more_layers_than_the_readings_determine_is_refused():
    sounding = _few(5)
    with pytest.raises(ValueError, match="Too few spacings for a 3-layer model"):
        invert_sounding(sounding, n_layers=3)
    start = LayeredModel(np.array([800.0, 40.0, 2000.0]), np.array([3.0, 15.0]))
    with pytest.raises(ValueError, match="its 5 parameters need at least 6 spacings"):
        invert_sounding(sounding, initial_model=start)
    with pytest.raises(ValueError, match="Too few spacings"):
        invert_sounding(sounding, VESConfig(min_layers=3))
    assert invert_sounding(sounding, n_layers=2).model.n_layers == 2


def test_a_model_with_no_degree_of_freedom_is_not_resolved():
    """The residual variance was divided by max(m - p, 1), so an exact fit
    with as many parameters as readings read as perfectly resolved."""
    sounding = _few(5)
    model = LayeredModel(np.array([800.0, 40.0, 2000.0]), np.array([3.0, 15.0]))
    rho_factor, h_factor = _parameter_uncertainty(
        sounding.ab2, sounding.rho_app, model, "schlumberger")
    assert list(rho_factor) == [UNRESOLVED_FACTOR] * 3
    assert list(h_factor) == [UNRESOLVED_FACTOR] * 2


def test_a_saved_model_the_search_would_not_have_tried_is_not_used():
    sounding = _few(5)
    config = VESConfig()
    key = inversion_key(sounding, config)
    fresh = invert_sounding(sounding, config)
    entry = cache_entry(key, fresh)
    assert cached_inversion(entry, key, sounding, config) is not None
    # a three-layer model, with the misfit it really has, and signed
    rho, h = [800.0, 40.0, 2000.0], [3.0, 15.0]
    restored = inversion.restore_inversion(
        sounding, rho, h, 10, True, "no improving step", [(3, 0.0)])
    record = dict(entry["result"], resistivities=rho, thicknesses=h,
                  trials=[[2, fresh.fit_error_percent], [3, restored.fit_error_percent]])
    forged = dict(entry, result=record, digest=_digest(key, record))
    assert cached_inversion(forged, key, sounding, config) is None


# ---------------------------------------------------------- the iterations


def test_the_iterations_are_counted_up_to_the_cap_and_no_further():
    """The browser counted max_iterations + 1 when a fit ran out, which its
    own cache then refused on every reload; Python counts as range() does."""
    sounding = _few(7)
    (rho0, h0), _other = inversion._starting_models(sounding.ab2, sounding.rho_app, 2)
    for cap in (0, 1, 3):
        *_rest, iterations, converged, stopped = invert_model(
            sounding.ab2, sounding.rho_app, rho0, h0, max_iterations=cap)
        assert iterations == cap
        assert stopped == "iteration cap"
        assert converged is False


def test_converged_means_a_minimum_by_the_stated_test():
    """'No improving step' was reported as converged, and running out of
    iterations as not, whether or not the point was a minimum. The label is
    now the stationarity test alone."""
    J = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    theta = np.log(np.array([100.0, 50.0, 3.0]))[:2]  # two resistivities, inside
    off_range = np.array([1.0, 1.0, -1.0])  # orthogonal to J's columns
    assert _stationary(theta, J.T @ J, J.T @ off_range, float(off_range @ off_range), 2)
    toward = off_range + J @ np.array([0.1, 0.0])
    assert not _stationary(theta, J.T @ J, J.T @ toward, float(toward @ toward), 2)
    # a pull on the first resistivity alone: a minimum only where that
    # resistivity is held at its lower bound, the descent pushing it below
    pull = off_range + J @ np.array([0.2, -0.1])
    g = J.T @ pull
    assert g[0] > 0 and abs(g[1]) < 1e-15
    assert not _stationary(theta, J.T @ J, g, float(pull @ pull), 2)
    held = np.array([np.log(inversion._RHO_BOUNDS[0]), theta[1]])
    assert _stationary(held, J.T @ J, g, float(pull @ pull), 2)


def test_each_way_a_fit_stops_is_told_apart():
    ab2 = np.array([1, 1.5, 2, 3, 5, 7, 10, 15, 20, 30, 50, 70, 100.0])
    data = forward_schlumberger((np.array([300.0, 40.0, 2000.0]), np.array([2.0, 12.0])), ab2)
    (rho0, h0), _other = inversion._starting_models(ab2, data, 3)
    *_rest, converged, stopped = invert_model(ab2, data, rho0, h0)
    assert (converged, stopped) == (True, "exact fit")
    *_rest, converged, stopped = invert_model(ab2, data, rho0, h0, max_iterations=2)
    assert (converged, stopped) == (False, "iteration cap")
    assert set(STOPS) == {"exact fit", "no improving step", "iteration cap"}


def test_a_rokel_fit_stops_with_no_improving_step_at_a_minimum(rokel_ves_a):
    result = invert_sounding(rokel_ves_a)
    assert result.stopped == "no improving step"
    assert result.converged is True


# ------------------------------------------------------- a spacing of zero


def test_a_reading_at_a_spacing_of_zero_is_left_out_and_flagged(tmp_path):
    """A row with AB/2 = 0, which a formula over a blank cell leaves, was kept:
    its logarithm, -inf, went into the starting models, numpy's interp
    recovered from it and the browser's did not, and the two engines fitted
    a 3-layer model at 12.9 percent and a NaN top layer at 100 percent."""
    from groundwater.ingestion.ves import read_ves_csv

    ab2 = [1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 30.0, 50.0]
    rho = list(forward_schlumberger((np.array([400.0, 60.0, 1500.0]), np.array([2.0, 10.0])),
                                    np.array(ab2)))
    clean = invert_sounding(_sounding(ab2, rho))
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no log of 0, no division by it
        zero = _sounding([0.0] + ab2, [1150.0] + rho)
        assert list(inversion_readings(zero)[0]) == ab2
        result = invert_sounding(zero)
    assert np.array_equal(result.model.resistivities, clean.model.resistivities)
    assert result.fit_error_percent == clean.fit_error_percent

    lines = ["Sounding Number,Z 1", "", "AB/2 (m),MN (m),Apparent Resistivity (ohm-m)",
             "0,0.4,1150"] + [f"{a},0.4,{r}" for a, r in zip(ab2, rho, strict=True)]
    path = tmp_path / "zero.csv"
    path.write_text("\n".join(lines) + "\n")
    sounding = read_ves_csv(path)
    flags = {f.code: f for f in sounding.flags}
    assert flags["nonpositive_spacing"].level == "warning"
    assert flags["nonpositive_spacing"].message == (
        "A spacing must be positive; 1 reading at a spacing of 0 or less is left "
        "out of the inversion.")

    # the sentence is the catalogue's (ves.yaml), and takes its plural there
    lines.insert(3, "-1,0.4,1150")
    path.write_text("\n".join(lines) + "\n")
    flags = {f.code: f for f in read_ves_csv(path).flags}
    assert flags["nonpositive_spacing"].message == (
        "A spacing must be positive; 2 readings at a spacing of 0 or less are left "
        "out of the inversion.")
