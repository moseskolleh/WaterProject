"""Damped least squares (Levenberg-Marquardt) 1D inversion of VES data.

Parameters are the logarithms of layer resistivities and thicknesses,
the misfit is measured on the logarithm of apparent resistivity, and a
Marquardt damping term stabilises the ill posed steps, which is the
classical ridge regression approach used by IPI2Win and similar tools.
The reported fit error matches the IPI2Win ERR quantity::

    ERR % = sqrt( mean( ((rho_calc - rho_obs) / rho_obs)^2 ) ) * 100

``invert_sounding`` searches over the number of layers (2 to
``max_layers``, and never more than the readings can determine: see
:func:`most_layers`) from several deterministic starting models and
returns the simplest model that reaches the target fit, with all trial
results attached for review.

A fit is labelled converged only where a stated test finds it at a
minimum within the bounds (:func:`_stationary`); where it is not, the
result still says why the iterations stopped (``stopped``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import VESConfig
from ..models import LayeredModel, VESSounding
from ..text import phrase
from .forward import (
    forward_schlumberger,
    forward_schlumberger_models,
    forward_wenner,
)
from .splice import splice_segments

__all__ = [
    "STOPS",
    "InversionResult",
    "invert_model",
    "invert_sounding",
    "inversion_readings",
    "most_layers",
    "restore_inversion",
]

_RHO_BOUNDS = (0.5, 200000.0)
_H_BOUNDS = (0.2, 300.0)

#: Why the iterations of a fit stopped, as ``InversionResult.stopped`` says:
#: the misfit fell below 1e-10 (the readings are fitted exactly), the damped
#: step search found no step that lowers the misfit, or the fit ran its
#: ``max_iterations`` with every step improving.
STOPS = ("exact fit", "no improving step", "iteration cap")

#: The converged label's test: a fit has converged where the Gauss-Newton
#: step from it, over the parameters free to move within the bounds, would
#: lower the sum of squared log residuals by no more than this share of
#: it. "No improving step" is not that: the damped step search gives up on
#: a narrow curved valley as readily as at its floor. Of 158 fits that
#: stopped that way on 40 synthetic soundings (two starts at 2, 3 and 4
#: layers each), 8 could still be lowered by more than 0.1 percentage
#: points by a bounded trust-region polish on the same forward model, and
#: 31 of the 82 that ran out of iterations were already at a minimum. The
#: share is a choice, not a standard. On the same fits, with the forward
#: model's cut set right, this test calls 162 converged, and the polish
#: lowers none of them by more than 0.06 percent of its misfit (6 by more
#: than 0.001 points, all two-layer fits at 59 to 213 percent); of the 78
#: it does not, 33 are at a minimum, so it errs towards "not converged" in
#: an equivalence valley.
STATIONARY_DECREASE = 1e-6

#: The ridge on the unit diagonal of the scaled normal equations in that
#: test, so a direction the readings cannot see at all (an exact
#: equivalence) cannot make the system singular. A numerical guard, far
#: below any resolution the readings have.
_STATIONARY_RIDGE = 1e-12

#: The largest uncertainty factor reported, which reads as not resolved.
UNRESOLVED_FACTOR = 10.0


@dataclass
class InversionResult:
    model: LayeredModel
    ab2: np.ndarray
    rho_obs: np.ndarray
    rho_calc: np.ndarray
    fit_error_percent: float
    n_iterations: int
    # True only where the fit passed the stationarity test (_stationary)
    converged: bool
    # why the iterations stopped, one of STOPS ("" on a hand-built result)
    stopped: str = ""
    trials: list = field(default_factory=list)  # (n_layers, err) for auto search
    shifts: list = field(default_factory=list)  # splice diagnostics
    # linearised 1-sigma multiplicative uncertainty per parameter, so a
    # resistivity rho is constrained to rho x/ factor. Larger factors mark
    # the equivalence/suppression that makes resistivity models non-unique.
    rho_uncertainty_factor: np.ndarray | None = None
    h_uncertainty_factor: np.ndarray | None = None


def _forward(rho, h, ab2, array_type: str):
    if array_type.startswith("wenner"):
        return forward_wenner((rho, h), ab2)
    return forward_schlumberger((rho, h), ab2)


def _forward_columns(thetas, n_layers: int, ab2, array_type: str) -> np.ndarray:
    """log(response) for each row of ``thetas``, as columns of one array.

    Schlumberger soundings go through the batched forward model; anything
    else is walked one row at a time. Either way each column is what
    ``residuals`` would have produced for that row on its own.
    """
    if not array_type.startswith("wenner"):
        rho = np.exp(thetas[:, :n_layers])
        h = np.exp(thetas[:, n_layers:])
        calc = forward_schlumberger_models(rho, h, ab2)
    else:
        calc = np.stack([
            forward_wenner(_unpack(t, n_layers), ab2) for t in thetas
        ])
    return np.log(np.maximum(calc, 1e-9)).T


JACOBIAN_STEP = 1e-4


def _jacobian(theta, res, log_obs, n_layers: int, ab2, array_type: str):
    """Forward-difference Jacobian in log space, one column per parameter.

    Returned C-ordered, which is not incidental: the caller forms
    ``J.T @ J``, and that dispatches on memory layout. The columns arrive
    here from a transpose, so leaving the result F-ordered sends the
    product down a different path through BLAS, and it rounds differently.
    Over sixty iterations that is a different fitted layer, not a different
    last bit.
    """
    perturbed = theta[None, :] + np.eye(len(theta)) * JACOBIAN_STEP
    columns = _forward_columns(perturbed, n_layers, ab2, array_type)
    return np.ascontiguousarray(
        (columns - log_obs[:, None] - res[:, None]) / JACOBIAN_STEP
    )


def fit_error_percent(rho_obs: np.ndarray, rho_calc: np.ndarray) -> float:
    rel = (rho_calc - rho_obs) / rho_obs
    return float(np.sqrt(np.mean(rel**2)) * 100.0)


def _pack(rho, h):
    return np.concatenate([np.log(rho), np.log(h)]) if len(h) else np.log(rho)


def _unpack(theta, n_layers):
    rho = np.exp(theta[:n_layers])
    h = np.exp(theta[n_layers:])
    return rho, h


def _bounds(n_params: int, n_layers: int) -> tuple[np.ndarray, np.ndarray]:
    """The lower and upper bounds of the log parameters."""
    lo = np.concatenate(
        [np.full(n_layers, np.log(_RHO_BOUNDS[0])), np.full(n_params - n_layers, np.log(_H_BOUNDS[0]))]
    )
    hi = np.concatenate(
        [np.full(n_layers, np.log(_RHO_BOUNDS[1])), np.full(n_params - n_layers, np.log(_H_BOUNDS[1]))]
    )
    return lo, hi


def _clip(theta, n_layers):
    lo, hi = _bounds(len(theta), n_layers)
    return np.clip(theta, lo, hi)


def _stationary(theta, JtJ, g, cost: float, n_layers: int) -> bool:
    """Whether a fit stopped at ``theta`` is at a minimum within the bounds.

    ``JtJ`` and ``g = J'r`` are from the Jacobian at ``theta`` and ``cost``
    is ``r'r`` there. A parameter at a bound that the gradient pushes
    outward is held; over the others the Gauss-Newton step would lower the
    cost by ``g' (J'J)^-1 g``. The fit is at a minimum when that is at most
    ``STATIONARY_DECREASE`` of the cost, or when the cost is below 1e-10.

    The normal equations are scaled to a unit diagonal before the ridge is
    added, so the test reads the same whatever the units of the parameters.
    The browser engine takes the same steps (``stationary`` in gwt-core.js).
    """
    if cost < 1e-10:
        return True
    lo, hi = _bounds(len(theta), n_layers)
    held = ((theta <= lo) & (g > 0)) | ((theta >= hi) & (g < 0))
    free = np.flatnonzero(~held)
    if not free.size:
        return True
    A = JtJ[np.ix_(free, free)]
    scale = np.sqrt(np.diag(A))
    scale[scale == 0.0] = 1.0
    A = A / np.outer(scale, scale) + _STATIONARY_RIDGE * np.eye(free.size)
    b = g[free] / scale
    try:
        step = np.linalg.solve(A, b)
    except np.linalg.LinAlgError:
        return False
    return float(b @ step) <= STATIONARY_DECREASE * cost


def invert_model(
    ab2: np.ndarray,
    rho_app: np.ndarray,
    rho0: np.ndarray,
    h0: np.ndarray,
    array_type: str = "schlumberger",
    damping: float = 0.02,
    max_iterations: int = 60,
) -> tuple[LayeredModel, np.ndarray, float, int, bool, str]:
    """Levenberg-Marquardt refinement from one starting model.

    Returns ``(model, calc, err, iterations, converged, stopped)``.
    ``iterations`` counts the iterations run, at most ``max_iterations``;
    ``stopped`` is one of :data:`STOPS`; and ``converged`` is whether the
    model passes :func:`_stationary`, which the stop alone does not say.
    """
    n_layers = len(rho0)
    theta = _clip(_pack(np.asarray(rho0, float), np.asarray(h0, float)), n_layers)
    log_obs = np.log(rho_app)

    def residuals(t):
        rho, h = _unpack(t, n_layers)
        calc = _forward(rho, h, ab2, array_type)
        calc = np.maximum(calc, 1e-9)
        return np.log(calc) - log_obs, calc

    res, calc = residuals(theta)
    cost = float(res @ res)
    lam = damping
    iterations = 0
    stopped = "iteration cap"
    JtJ = g = None
    for iterations in range(1, max_iterations + 1):  # noqa: B007 - returned below
        # numerical Jacobian in log space. The columns are the same sounding
        # against one model per parameter, each with a single parameter
        # nudged, so they are taken in one pass over the quadrature rather
        # than one pass each - the same arithmetic, on arrays large enough
        # for numpy to be doing work rather than dispatching.
        J = _jacobian(theta, res, log_obs, n_layers, ab2, array_type)

        JtJ = J.T @ J
        g = J.T @ res
        improved = False
        for _ in range(12):
            try:
                delta = np.linalg.solve(
                    JtJ + lam * np.diag(np.maximum(np.diag(JtJ), 1e-8)), -g
                )
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            trial = _clip(theta + delta, n_layers)
            r_trial, c_trial = residuals(trial)
            cost_trial = float(r_trial @ r_trial)
            if cost_trial < cost:
                theta, res, calc, cost = trial, r_trial, c_trial, cost_trial
                lam = max(lam / 3.0, 1e-7)
                improved = True
                break
            lam *= 10
            if lam > 1e8:
                break
        if not improved:
            stopped = "no improving step"  # theta is where J was taken
            break
        if cost < 1e-10:
            stopped = "exact fit"
            break

    # The label, read off the returned point and nothing else, so it moves
    # no fitted number. Only after a step that improved has theta moved
    # since the last Jacobian.
    if stopped == "iteration cap" and cost >= 1e-10:
        J = _jacobian(theta, res, log_obs, n_layers, ab2, array_type)
        JtJ, g = J.T @ J, J.T @ res
    converged = stopped == "exact fit" or _stationary(theta, JtJ, g, cost, n_layers)

    rho, h = _unpack(theta, n_layers)
    err = fit_error_percent(rho_app, calc)
    model = LayeredModel(rho, h, fit_error_percent=err, method="damped-lsq")
    return model, calc, err, iterations, converged, stopped


def _starting_models(ab2: np.ndarray, rho: np.ndarray, n_layers: int) -> list:
    """Deterministic starting models from the smoothed field curve.

    Thicknesses grow logarithmically over the depth range covered by
    the spacings (depth of investigation taken as AB/2 / 2); starting
    resistivities are read off the smoothed curve at the corresponding
    spacings. Two depth-scale variants bracket the depth of investigation.
    """
    log_rho = np.log(rho)
    starts = []
    for depth_factor in (0.35, 0.7):
        z_top = max(ab2[0] * depth_factor, 0.5)
        z_bot = max(ab2[-1] * depth_factor, z_top * 4)
        # An n-layer model has n-1 interfaces, and they must span the whole
        # investigated range. Spacing n points and then dropping the last
        # put the deepest starting interface at the second geomspace point:
        # 6 m for a sounding that reaches 56 m, so the search began with
        # basement far too shallow and had to climb out of it.
        interfaces = np.geomspace(z_top, z_bot, max(n_layers - 1, 1))
        h0 = np.maximum(np.diff(np.concatenate([[0.0], interfaces])), 0.3)
        # one starting resistivity per layer, read off the smoothed curve at
        # the spacing that senses each layer's mid-depth
        tops = np.concatenate([[0.0], interfaces])
        mids = np.concatenate([
            0.5 * (tops[:-1] + tops[1:]),      # the finite layers
            [interfaces[-1] * 1.5],            # the half space below
        ])
        rho0 = []
        for z in mids[:n_layers]:
            L = np.clip(2.0 * z, ab2[0], ab2[-1])
            rho0.append(np.exp(np.interp(np.log(L), np.log(ab2), log_rho)))
        starts.append((np.array(rho0), h0))
    return starts


def inversion_readings(
    sounding: VESSounding, splice: bool = True
) -> tuple[np.ndarray, np.ndarray, list[float]]:
    """The readings the inversion fits: ``(ab2, rho_app, shifts)``.

    Spliced where the array has segments, sorted by spacing, and only the
    readings with a finite, positive spacing and apparent resistivity. The
    interpretation reads its depth of investigation from the same readings,
    so a last reading recorded as 0 cannot lend it a depth the model never
    saw. A spacing of 0 (a formula over a blank cell, a placeholder row) has
    no place on the curve: its logarithm sent the starting models to -inf,
    which numpy recovered from and the browser did not, so the two engines
    fitted different models.
    """
    if splice and not sounding.array_type.startswith("wenner"):
        ab2, rho_app, shifts = splice_segments(sounding)
    else:
        order = np.argsort(sounding.ab2, kind="stable")
        ab2, rho_app, shifts = sounding.ab2[order], sounding.rho_app[order], [1.0]
    keep = np.isfinite(rho_app) & (rho_app > 0) & np.isfinite(ab2) & (ab2 > 0)
    return ab2[keep], rho_app[keep], shifts


def most_layers(n_spacings: int) -> int:
    """The most layers a model fitted to ``n_spacings`` distinct spacings
    may have.

    An n-layer model has 2n - 1 parameters. With as many parameters as
    spacings it can pass through every reading: the misfit is then about 0
    whatever the earth, the parsimony rule rejects every simpler model as
    more than twice as bad, and the uncertainty factors, from a residual
    variance of about 0, read as perfectly resolved. Four readings of an
    800 / 40 / 2000 ohm-m earth were fitted with a 9.8 ohm-m clay below
    3.5 m at confidence 1.0. So a model keeps at least one degree of
    freedom: 2n - 1 <= m - 1, n <= m // 2. That is the least the misfit
    needs to say anything about the readings' error, and a choice: two
    would refuse three layers to soundings of six and seven spacings.
    """
    return int(n_spacings) // 2


def _too_many_layers(n: int, n_spacings: int) -> str:
    return phrase("ves.too_many_layers", layers=n, parameters=2 * n - 1, needed=2 * n, spacings=n_spacings)


def invert_sounding(
    sounding: VESSounding,
    config: VESConfig | None = None,
    n_layers: int | None = None,
    initial_model: LayeredModel | None = None,
    splice: bool = True,
) -> InversionResult:
    """Invert a sounding to a layered model.

    With ``n_layers=None`` the layer count is searched from
    ``config.min_layers`` to ``config.max_layers`` and the simplest
    model whose fit reaches ``config.target_fit_percent`` is kept (or
    the best fitting model if none reaches it). Passing
    ``initial_model`` (for example an imported IPI2Win model) refines
    that model instead. The search stops at :func:`most_layers` of the
    sounding's spacings; asked for more layers than that, by ``n_layers``
    or ``initial_model``, it raises ``ValueError`` rather than fit a model
    the readings cannot determine.
    """
    config = config or VESConfig()
    ab2, rho_app, shifts = inversion_readings(sounding, splice)
    # Spacings, not readings: a Wenner sheet is not spliced, so one read
    # twice at each of two spacings passed a count of four and had a
    # two-layer model's three parameters fitted to two points of the curve,
    # where a family of models fits equally well and each engine picked a
    # different one.
    n_spacings = len(np.unique(ab2))
    if n_spacings < 4:
        raise ValueError("Not enough readings to invert")
    most = most_layers(n_spacings)
    asked = (
        len(initial_model.resistivities) if initial_model is not None
        else n_layers if n_layers is not None
        else config.min_layers
    )
    if asked > most:
        raise ValueError(_too_many_layers(asked, n_spacings))

    candidates: list[tuple[LayeredModel, np.ndarray, float, int, bool, str]] = []
    trials: list[tuple[int, float]] = []

    if initial_model is not None:
        result = invert_model(
            ab2,
            rho_app,
            initial_model.resistivities,
            initial_model.thicknesses,
            sounding.array_type,
            config.damping,
            config.max_iterations,
        )
        candidates.append(result)
        trials.append((result[0].n_layers, result[2]))
    else:
        layer_range = (
            [n_layers]
            if n_layers is not None
            else list(range(config.min_layers, min(config.max_layers, most) + 1))
        )
        for n in layer_range:
            best_for_n = None
            for rho0, h0 in _starting_models(ab2, rho_app, n):
                result = invert_model(
                    ab2, rho_app, rho0, h0,
                    sounding.array_type, config.damping, config.max_iterations,
                )
                if best_for_n is None or result[2] < best_for_n[2]:
                    best_for_n = result
            candidates.append(best_for_n)
            trials.append((n, best_for_n[2]))
            if n_layers is None:
                # stop adding layers once the target is comfortably reached
                # or when the extra layer no longer helps materially - but the
                # diminishing-returns test only applies once an adequate fit is
                # already in hand, so a small n-1 -> n gain (equivalence /
                # suppression) cannot abandon the search while the fit is still
                # far above target.
                # "Comfortably" means the noise floor the accept rule below
                # uses (a tenth of the target), not half of it: at half, a
                # 4.7% two-layer fit ended the search before the three-layer
                # model that fitted a 15 m aquifer over basement exactly was
                # ever tried, and the parsimony rule never saw it.
                if best_for_n[2] <= config.target_fit_percent / 10.0:
                    break
                if (
                    len(trials) >= 2
                    and trials[-1][1] > 0.9 * trials[-2][1]
                    and best_for_n[2] <= config.target_fit_percent
                ):
                    break

    # Parsimony: the simplest model reaching the target; otherwise the
    # simplest model whose fit is within config.parsimony_fallback_ratio of
    # the best fit (extra layers must earn their keep), otherwise the
    # overall best. A model chosen by the fallback has not reached the
    # target, and the interpretation flags that: neither Rokel sounding
    # reaches it, and the choice between their candidates was being made by
    # a constant nobody could see.
    #
    # "Reaching the target" is not enough on its own. A two-layer model can
    # sit just under the target while a three-layer one fits the same curve
    # an order of magnitude better and puts basement at 65 m instead of 4 m -
    # the difference between drilling into the aquifer and stopping in the
    # regolith. So a simple model is only accepted while no available model
    # more than halves its misfit.
    best_err = min(c[2] for c in candidates)
    chosen = None
    for cand in candidates:
        if cand[2] <= config.target_fit_percent and (
            cand[2] <= config.parsimony_max_error_ratio * max(best_err, 1e-9)
            or cand[2] <= config.target_fit_percent / 10.0
        ):
            chosen = cand
            break
    if chosen is None:
        for cand in candidates:
            if cand[2] <= config.parsimony_fallback_ratio * best_err:
                chosen = cand
                break
    if chosen is None:
        chosen = min(candidates, key=lambda c: c[2])

    return _result(sounding, ab2, rho_app, shifts, chosen, trials)


def _result(sounding, ab2, rho_app, shifts, chosen, trials) -> InversionResult:
    """The result of a search, from the candidate it chose.

    Shared by :func:`invert_sounding` and :func:`restore_inversion`, so a
    result rebuilt from a saved model is put together by the same code as
    the one the search returned.
    """
    model, calc, err, iterations, converged, stopped = chosen
    model.sounding_id = sounding.sounding_id
    rho_factor, h_factor = _parameter_uncertainty(
        ab2, rho_app, model, sounding.array_type
    )
    model.h_uncertainty_factor = h_factor
    return InversionResult(
        model=model,
        ab2=ab2,
        rho_obs=rho_app,
        rho_calc=calc,
        fit_error_percent=err,
        n_iterations=iterations,
        converged=converged,
        stopped=stopped,
        trials=trials,
        shifts=shifts,
        rho_uncertainty_factor=rho_factor,
        h_uncertainty_factor=h_factor,
    )


def restore_inversion(
    sounding: VESSounding,
    resistivities,
    thicknesses,
    n_iterations: int,
    converged: bool,
    stopped: str,
    trials: list,
) -> InversionResult:
    """Rebuild what :func:`invert_sounding` returned from the model it chose.

    Only what the search alone can say is taken as given: the model, how
    many iterations it took, whether it converged and why it stopped, and
    the layer counts it tried. Everything else - the readings fitted, the
    model's response, the misfit and the uncertainty factors - is worked
    out again from the sounding, the same way and in the same order as the
    search does it, so it comes out to the last bit. A response or a misfit
    read back from a file would be one more thing a damaged file could get
    wrong.
    """
    ab2, rho_app, shifts = inversion_readings(sounding)
    rho = np.asarray(resistivities, dtype=float)
    h = np.asarray(thicknesses, dtype=float)
    calc = np.maximum(_forward(rho, h, ab2, sounding.array_type), 1e-9)
    err = fit_error_percent(rho_app, calc)
    model = LayeredModel(rho, h, fit_error_percent=err, method="damped-lsq")
    chosen = (model, calc, err, int(n_iterations), bool(converged), str(stopped))
    return _result(sounding, ab2, rho_app, shifts, chosen, list(trials))


def _parameter_uncertainty(ab2, rho_app, model, array_type):
    """Linearised 1-sigma multiplicative uncertainty per model parameter.

    Reuses the log-space Jacobian the inversion is built on: the model
    covariance is sigma^2 (J'J)^-1 with sigma^2 the variance of the log
    residuals, and because the parameters are logarithms, exp(sigma_i)
    gives the multiplicative factor on each resistivity and thickness.
    Returns ``(rho_factor, h_factor)``; factors near 1 are well resolved,
    large factors mark equivalence. With no more readings than parameters
    there is no residual variance to scale by, and every factor is
    ``UNRESOLVED_FACTOR``: such a model passes through the readings
    whatever the earth. The search never fits one (:func:`most_layers`).
    """
    rho = np.asarray(model.resistivities, float)
    h = np.asarray(model.thicknesses, float)
    n_layers = len(rho)
    theta = _pack(rho, h)
    log_obs = np.log(rho_app)

    def residuals(t):
        r, hh = _unpack(t, n_layers)
        calc = np.maximum(_forward(r, hh, ab2, array_type), 1e-9)
        return np.log(calc) - log_obs

    res = residuals(theta)
    m, p = len(ab2), len(theta)
    if m <= p:
        return np.full(n_layers, UNRESOLVED_FACTOR), np.full(p - n_layers, UNRESOLVED_FACTOR)
    # the same Jacobian the iterations take, built the same way
    J = _jacobian(theta, res, log_obs, n_layers, ab2, array_type)

    sigma2 = float(res @ res) / (m - p)
    JtJ = J.T @ J
    try:
        cov = sigma2 * np.linalg.inv(JtJ)
    except np.linalg.LinAlgError:
        cov = sigma2 * np.linalg.pinv(JtJ)
    std = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    # cap the reported factor so a wildly unconstrained parameter does not
    # print an absurd number; anything above ~10x is "not resolved"
    # clip in log space: exp() of an unconstrained parameter's std overflowed
    # and warned on every poorly resolved sounding before the minimum applied
    factors = np.exp(np.minimum(std, np.log(UNRESOLVED_FACTOR)))
    return factors[:n_layers], factors[n_layers:]
