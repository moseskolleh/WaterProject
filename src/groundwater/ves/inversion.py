"""Damped least squares (Levenberg-Marquardt) 1D inversion of VES data.

Parameters are the logarithms of layer resistivities and thicknesses,
the misfit is measured on the logarithm of apparent resistivity, and a
Marquardt damping term stabilises the ill posed steps, which is the
classical ridge regression approach used by IPI2Win and similar tools.
The reported fit error matches the IPI2Win ERR quantity::

    ERR % = sqrt( mean( ((rho_calc - rho_obs) / rho_obs)^2 ) ) * 100

``invert_sounding`` searches over the number of layers (2 to
``max_layers``) from several deterministic starting models and returns
the simplest model that reaches the target fit, with all trial results
attached for review.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import VESConfig
from ..models import LayeredModel, VESSounding
from .forward import forward_schlumberger, forward_wenner
from .splice import splice_segments

__all__ = ["InversionResult", "invert_model", "invert_sounding"]

_RHO_BOUNDS = (0.5, 200000.0)
_H_BOUNDS = (0.2, 300.0)


@dataclass
class InversionResult:
    model: LayeredModel
    ab2: np.ndarray
    rho_obs: np.ndarray
    rho_calc: np.ndarray
    fit_error_percent: float
    n_iterations: int
    converged: bool
    trials: list = field(default_factory=list)  # (n_layers, err) for auto search
    shifts: list = field(default_factory=list)  # splice diagnostics


def _forward(rho, h, ab2, array_type: str):
    if array_type.startswith("wenner"):
        return forward_wenner((rho, h), ab2)
    return forward_schlumberger((rho, h), ab2)


def fit_error_percent(rho_obs: np.ndarray, rho_calc: np.ndarray) -> float:
    rel = (rho_calc - rho_obs) / rho_obs
    return float(np.sqrt(np.mean(rel**2)) * 100.0)


def _pack(rho, h):
    return np.concatenate([np.log(rho), np.log(h)]) if len(h) else np.log(rho)


def _unpack(theta, n_layers):
    rho = np.exp(theta[:n_layers])
    h = np.exp(theta[n_layers:])
    return rho, h


def _clip(theta, n_layers):
    lo = np.concatenate(
        [np.full(n_layers, np.log(_RHO_BOUNDS[0])), np.full(len(theta) - n_layers, np.log(_H_BOUNDS[0]))]
    )
    hi = np.concatenate(
        [np.full(n_layers, np.log(_RHO_BOUNDS[1])), np.full(len(theta) - n_layers, np.log(_H_BOUNDS[1]))]
    )
    return np.clip(theta, lo, hi)


def invert_model(
    ab2: np.ndarray,
    rho_app: np.ndarray,
    rho0: np.ndarray,
    h0: np.ndarray,
    array_type: str = "schlumberger",
    damping: float = 0.02,
    max_iterations: int = 60,
) -> tuple[LayeredModel, np.ndarray, float, int, bool]:
    """Levenberg-Marquardt refinement from one starting model."""
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
    converged = False
    for iterations in range(1, max_iterations + 1):
        # numerical Jacobian in log space
        J = np.empty((len(ab2), len(theta)))
        step = 1e-4
        for j in range(len(theta)):
            tp = theta.copy()
            tp[j] += step
            rp, _ = residuals(tp)
            J[:, j] = (rp - res) / step

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
            converged = True
            break
        if cost < 1e-10:
            converged = True
            break

    rho, h = _unpack(theta, n_layers)
    err = fit_error_percent(rho_app, calc)
    model = LayeredModel(rho, h, fit_error_percent=err, method="damped-lsq")
    return model, calc, err, iterations, converged


def _starting_models(ab2: np.ndarray, rho: np.ndarray, n_layers: int) -> list:
    """Deterministic starting models from the smoothed field curve.

    Thicknesses grow logarithmically over the depth range covered by
    the spacings (depth of investigation taken as AB/2 / 2); starting
    resistivities are read off the smoothed curve at the corresponding
    spacings. Three variants bracket the depth scale.
    """
    log_rho = np.log(rho)
    starts = []
    for depth_factor in (0.35, 0.7):
        z_top = max(ab2[0] * depth_factor, 0.5)
        z_bot = max(ab2[-1] * depth_factor, z_top * 4)
        bounds = np.geomspace(z_top, z_bot, n_layers)
        h0 = np.diff(np.concatenate([[0.0], bounds[:-1]]))
        h0 = np.maximum(h0, 0.3)
        rho0 = []
        for z in bounds:
            L = np.clip(2.0 * z, ab2[0], ab2[-1])
            rho0.append(np.exp(np.interp(np.log(L), np.log(ab2), log_rho)))
        starts.append((np.array(rho0), h0))
    return starts


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
    that model instead.
    """
    config = config or VESConfig()
    if splice and not sounding.array_type.startswith("wenner"):
        ab2, rho_app, shifts = splice_segments(sounding)
    else:
        order = np.argsort(sounding.ab2, kind="stable")
        ab2, rho_app, shifts = sounding.ab2[order], sounding.rho_app[order], [1.0]

    keep = np.isfinite(rho_app) & (rho_app > 0)
    ab2, rho_app = ab2[keep], rho_app[keep]
    if len(ab2) < 4:
        raise ValueError("Not enough readings to invert")

    candidates: list[tuple[LayeredModel, np.ndarray, float, int, bool]] = []
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
            else list(range(config.min_layers, config.max_layers + 1))
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
                # or when the extra layer no longer helps materially
                if best_for_n[2] <= config.target_fit_percent / 2:
                    break
                if len(trials) >= 2 and trials[-1][1] > 0.9 * trials[-2][1]:
                    break

    # Parsimony: the simplest model reaching the target; otherwise the
    # simplest model whose fit is within 15 percent of the best fit
    # (extra layers must earn their keep), otherwise the overall best.
    chosen = None
    for cand in candidates:
        if cand[2] <= config.target_fit_percent:
            chosen = cand
            break
    if chosen is None:
        best_err = min(c[2] for c in candidates)
        for cand in candidates:
            if cand[2] <= 1.15 * best_err:
                chosen = cand
                break
    if chosen is None:
        chosen = min(candidates, key=lambda c: c[2])

    model, calc, err, iterations, converged = chosen
    model.sounding_id = sounding.sounding_id
    return InversionResult(
        model=model,
        ab2=ab2,
        rho_obs=rho_app,
        rho_calc=calc,
        fit_error_percent=err,
        n_iterations=iterations,
        converged=converged,
        trials=trials,
        shifts=shifts,
    )
