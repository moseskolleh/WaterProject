"""A range of VES models, not one (PLAN.md step 3.1).

One Levenberg-Marquardt fit is one member of a family of models that fit a
sounding about equally well: equivalence lets a thin conductive layer trade
thickness for resistivity, and a basement the spread never reached can sit
anywhere below it. The best fit is kept as it is, and this samples the
family beside it:

1. more starting models, drawn by Latin hypercube over the range of
   resistivities and depths the readings span, each polished by the same
   Levenberg-Marquardt fit the inversion uses, at the inversion's layer
   count;
2. an error on every reading: a base percentage, plus half the measured
   disagreement (as a log ratio) at each MN overlap, which is the error of
   the geometric mean the splice fits there. Where even the best model
   misses the readings by more than those errors allow, they are widened
   until it does not (the Birge ratio), so that a curve no layered model
   describes gives a wide range rather than a confident narrow one;
3. a random-walk Metropolis-Hastings sampler over the logarithms of the
   resistivities and thicknesses, with a flat prior inside the inversion's
   own bounds, run in several chains, each started from one of the best
   fits. The step is shaped by the linearised covariance at the best fit,
   so a chain walks along an equivalence ridge rather than across it, and
   its size is tuned during burn-in;
4. what each kept model says, read by the interpretation's own rules: the
   depth to basement (or that there is none within the depth of
   investigation), the water-bearing weathered zone, the drilling depth and
   each layer's resistivity and depth. Their P10, P50 and P90 are the range.

The range is conditional on the inversion's layer count: the sampler does
not add or remove layers.

It is not saved with a project, as inversions are (``ves/cache.py``). A
saved inversion is checked on the way back in by fitting its model to the
readings again and comparing the misfit the search recorded; a saved range
has no check short of sampling it again, and a cache that must be taken on
trust is what that module was written not to be. The range is seeded, so
sampling it again gives the same answer, and it is asked for with a button
rather than paid for on every reopening.

Both engines run this, and ``gwt-core.js`` is held to it by
``tests/webapp/parity.mjs``. Every random number comes from one 32-bit
generator (xoshiro128**, seeded by splitmix32) written the same way in
both, and the random-walk step is a sum of four uniforms rather than a
Gaussian, because a Gaussian needs a logarithm and the two engines' ``log``
differ in the last bit for about one value in fifteen. Any symmetric step is
a valid Metropolis-Hastings proposal. So the two engines draw the same
starting models and the same steps; what still differs is the forward
model's last bits, which moves an accept decision only when a uniform lands
within about 1e-9 of the acceptance probability.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..config import Config, VESConfig
from ..ingestion.ves import overlap_ratios
from ..models import VESSounding
from ..text import phrase
from ..utils import and_join, fmt_num
from .interpret import _unit_label, depth_of_investigation
from .inversion import (
    _H_BOUNDS,
    _RHO_BOUNDS,
    InversionResult,
    _forward,
    _jacobian,
    _pack,
    fit_error_percent,
    invert_model,
    inversion_readings,
)

__all__ = [
    "MIN_RESOLVED_SHARE",
    "Band",
    "ModelRange",
    "Stream",
    "latin_hypercube",
    "model_range_caption",
    "model_range_rows",
    "model_range_table_caption",
    "model_range_text",
    "percentile",
    "quoted_basement_band",
    "reading_errors",
    "sample_model_range",
]

# ------------------------------------------------------------ random numbers

_MASK = 0xFFFFFFFF
_GOLDEN = 0x9E3779B9
_SQRT3 = math.sqrt(3.0)


def _rotl(x: int, k: int) -> int:
    return ((x << k) | (x >> (32 - k))) & _MASK


class Stream:
    """xoshiro128** on 32-bit words, seeded by splitmix32.

    ``stream`` separates the generator a purpose uses from the others: the
    Latin hypercube draws from stream 0 and chain c from stream c + 1, so a
    chain's numbers do not depend on how many any other part drew.
    ``gwt-core.js`` has the same generator, word for word.
    """

    def __init__(self, seed: int, stream: int = 0):
        x = ((int(seed) & _MASK) * _GOLDEN + int(stream)) & _MASK
        state = []
        for _ in range(4):
            x = (x + _GOLDEN) & _MASK
            z = x
            z = ((z ^ (z >> 16)) * 0x85EBCA6B) & _MASK
            z = ((z ^ (z >> 13)) * 0xC2B2AE35) & _MASK
            state.append(z ^ (z >> 16))
        if not any(state):
            state[0] = 1  # the one state xoshiro cannot leave
        self._s = state

    def next_u32(self) -> int:
        s0, s1, s2, s3 = self._s
        result = (_rotl((s1 * 5) & _MASK, 7) * 9) & _MASK
        t = (s1 << 9) & _MASK
        s2 ^= s0
        s3 ^= s1
        s1 ^= s2
        s0 ^= s3
        s2 ^= t
        s3 = _rotl(s3, 11)
        self._s = [s0, s1, s2, s3]
        return result

    def uniform(self) -> float:
        """A uniform number in (0, 1), exactly representable in both engines."""
        return (self.next_u32() + 0.5) / 4294967296.0

    def below(self, n: int) -> int:
        """A whole number from 0 to n - 1, in integer arithmetic."""
        return (self.next_u32() * n) >> 32

    def symmetric(self) -> float:
        """Zero mean and unit variance: four uniforms summed and scaled.

        The Irwin-Hall sum stands in for a Gaussian. It needs no logarithm, so
        both engines draw it to the bit, and it is symmetric, which is all a
        Metropolis-Hastings step asks of it.
        """
        total = self.uniform() + self.uniform()
        total += self.uniform()
        total += self.uniform()
        return (total - 2.0) * _SQRT3


def latin_hypercube(rng: Stream, n_points: int, lo: list[float], hi: list[float]) -> list[list[float]]:
    """``n_points`` points in the box ``lo``-``hi``, one in each of
    ``n_points`` equal slices of every axis: a shuffled slice per point and
    axis (Fisher-Yates), and a uniform position inside it."""
    p = len(lo)
    points = [[0.0] * p for _ in range(n_points)]
    for j in range(p):
        perm = list(range(n_points))
        for i in range(n_points - 1, 0, -1):
            k = rng.below(i + 1)
            perm[i], perm[k] = perm[k], perm[i]
        for k in range(n_points):
            u = (perm[k] + rng.uniform()) / n_points
            points[k][j] = lo[j] + (hi[j] - lo[j]) * u
    return points


# ------------------------------------------------------------------ results

@dataclass
class Band:
    """P10, P50 and P90 of one quantity over the models that fit."""

    p10: float
    p50: float
    p90: float


def percentile(sorted_values: list[float], q: float) -> float:
    """Linear interpolation between order statistics (numpy's default rule),
    written out so both engines do the same arithmetic."""
    pos = q * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    if lo + 1 >= len(sorted_values):
        return float(sorted_values[-1])
    frac = pos - lo
    a, b = sorted_values[lo], sorted_values[lo + 1]
    return float(a + (b - a) * frac)


def _band(values: list[float]) -> Band:
    ordered = sorted(values)
    return Band(*(percentile(ordered, q) for q in (0.1, 0.5, 0.9)))


@dataclass
class ModelRange:
    sounding_id: str
    n_layers: int
    #: models kept over all the chains, and the chains they came from
    n_samples: int
    chains: int
    #: Latin hypercube starts polished, beside the inversion's own model
    starts: int
    seed: int
    base_error_percent: float
    #: AB/2 of each fitted reading whose error carries an MN overlap
    overlap_spacings: list[float]
    #: the factor the errors were widened by (1 when they were not)
    error_scale: float
    #: share of the kept steps accepted, over all the chains
    acceptance: float
    #: kept steps accepted, chain by chain
    accepted: list[int]
    investigation_depth_m: float
    #: depth to basement over the models that have one within the depth of
    #: investigation; None when none of them has
    basement_m: Band | None
    #: share of the models with no basement within the depth of investigation
    basement_unresolved: float
    weathered_m: Band
    resistivity: list[Band]
    #: depth of the base of each layer above the half-space
    interface_m: list[Band]
    #: the drilling depth read from the P90 model depth, rounded up and cut
    #: back to the depth of investigation as the interpretation's is
    drilling_depth_m: float
    drilling_depth_capped: bool
    #: the inversion's misfit, and the best the wider search reached
    chosen_error_percent: float
    best_error_percent: float
    ab2: list[float]
    #: a thinned set of the kept models, and their responses at ``ab2``
    fan: list[tuple[list[float], list[float]]] = field(default_factory=list)
    fan_curves: list[list[float]] = field(default_factory=list)
    #: what parity compares: the hypercube points in log space and the
    #: misfit of each polished start
    start_points: list[list[float]] = field(default_factory=list)
    start_errors: list[float] = field(default_factory=list)
    #: the depth each kept model would be drilled to, cut back to the depth
    #: of investigation but not yet rounded, at every twentieth of the way
    #: from its least to its greatest: what the cost distribution draws the
    #: depth from (PLAN.md step 3.4)
    drilling_depth_quantiles_m: list[float] = field(default_factory=list)


# ---------------------------------------------------------------- the model

def reading_errors(
    sounding: VESSounding, ab2: np.ndarray, base_error_percent: float
) -> tuple[np.ndarray, list[float]]:
    """The error of each fitted reading as a log standard deviation.

    The base percentage, plus half the log ratio of the readings at an MN
    overlap where there is one, added in quadrature as two independent
    errors are: the two readings there scatter by about that much about
    their geometric mean, which is what the splice fits.
    Returns the errors and the spacings that carry an overlap.

    A Wenner sheet has no MN to change, and a spacing read twice on one is
    two readings the fit sees apart, so their scatter is in the misfit
    already: only a Schlumberger overlap adds to the error.
    """
    base = base_error_percent / 100.0
    at = ({} if sounding.array_type.startswith("wenner")
          else dict(overlap_ratios(sounding.ab2, sounding.rho_app)))
    sigma = np.empty(len(ab2))
    spacings = []
    for i, value in enumerate(ab2):
        ratio = at.get(float(value))
        if ratio is None:
            sigma[i] = base
            continue
        d = 0.5 * math.log(ratio)
        sigma[i] = math.sqrt(base * base + d * d)
        spacings.append(float(value))
    return sigma, spacings


def _summary(theta: list[float], n: int, investigation: float, ves: VESConfig):
    """What one model says, by the interpretation's rules (interpret_model):
    ``(basement, weathered, deepest, interfaces, rho)``.

    The zones are not rounded here, as the interpretation rounds them for
    print, so a percentile is of the model and not of its rounding.
    """
    rho = [math.exp(v) for v in theta[:n]]
    tops = [0.0]
    for v in theta[n:]:
        tops.append(tops[-1] + math.exp(v))
    weathered = 0.0
    deepest = None
    basement = None
    for i in range(n):
        top = tops[i]
        bottom = tops[i + 1] if i + 1 < n else math.inf
        if _unit_label(rho[i], i == 0, i == n - 1, ves)[1]:
            z_top = max(top, 3.0)  # the top few metres are vadose
            if z_top < investigation:
                z_bottom = min(bottom, investigation)
                if z_bottom - z_top >= 1.0:
                    weathered += z_bottom - z_top
                    deepest = z_bottom
        if basement is None and rho[i] >= ves.fresh_basement_min_rho and top > 0:
            basement = top
    if basement is None and rho[-1] >= ves.fractured_zone_rho[1]:
        basement = tops[n - 1]
    if basement is not None and basement > investigation:
        basement = None
    deepest = investigation if deepest is None else deepest + ves.max_drilling_margin_m
    return basement, weathered, deepest, tops[1:], rho


def _chi2(calc, log_obs, sigma) -> float:
    r = (np.log(np.maximum(calc, 1e-9)) - log_obs) / sigma
    return float(r @ r)


def _cholesky_inverse_t(H: list[list[float]]) -> list[list[float]]:
    """``M`` with ``M M' = H^-1``: the inverse of the transpose of H's
    Cholesky factor. Plain loops, in the order gwt-core.js runs them."""
    p = len(H)
    L = [[0.0] * p for _ in range(p)]
    for j in range(p):
        s = H[j][j]
        for k in range(j):
            s -= L[j][k] * L[j][k]
        L[j][j] = math.sqrt(max(s, 1e-300))
        for i in range(j + 1, p):
            s = H[i][j]
            for k in range(j):
                s -= L[i][k] * L[j][k]
            L[i][j] = s / L[j][j]
    # back substitution against U = L', one column of the identity at a time
    M = [[0.0] * p for _ in range(p)]
    for c in range(p):
        for i in range(p - 1, -1, -1):
            s = 1.0 if i == c else 0.0
            for k in range(i + 1, p):
                s -= L[k][i] * M[k][c]
            M[i][c] = s / L[i][i]
    return M


#: The drilling depth is kept at this many equal steps of probability, for the
#: cost distribution to draw from; twenty steps of 5 percent follow the
#: models' spread closely, and a range kept in a project stays small.
DEPTH_QUANTILES = 20

_WINDOW = 50  # burn-in steps between two adjustments of the step size


def sample_model_range(
    sounding: VESSounding,
    inversion: InversionResult,
    config: Config | None = None,
    on_progress=None,
) -> ModelRange:
    """The range of models that fit ``sounding`` about as well as ``inversion``.

    ``on_progress(fraction, label)``, when given, is told how far the work
    has got; it reads nothing back.
    """
    config = config or Config()
    ves, opts = config.ves, config.ves_range
    array_type = sounding.array_type
    ab2, rho_app, _shifts = inversion_readings(sounding)
    log_obs = np.log(rho_app)
    n = inversion.model.n_layers
    p = 2 * n - 1
    m = len(ab2)
    investigation = depth_of_investigation(float(np.max(ab2)), ves)
    sigma, overlap_spacings = reading_errors(sounding, ab2, opts.base_error_percent)

    n_starts = max(int(opts.starts), 0)
    n_chains = max(int(opts.chains), 1)
    n_samples = max(int(opts.samples), n_chains)
    burn_in = max(int(opts.burn_in), 0)
    lm_weight = 250  # about the forward calls one polish takes
    total_work = n_starts * lm_weight + n_chains * burn_in + n_samples
    done = 0

    def progress(label):
        if on_progress is not None:
            on_progress(min(done / total_work, 1.0), label)

    # ---- the hard bounds (the inversion's) and the hypercube's box -------
    hard_lo = [math.log(_RHO_BOUNDS[0])] * n + [math.log(_H_BOUNDS[0])] * (n - 1)
    hard_hi = [math.log(_RHO_BOUNDS[1])] * n + [math.log(_H_BOUNDS[1])] * (n - 1)
    rho_lo = math.log(max(_RHO_BOUNDS[0], float(np.min(rho_app)) / 10.0))
    rho_hi = math.log(min(_RHO_BOUNDS[1], float(np.max(rho_app)) * 10.0))
    # the depth scales the inversion's own two starting models use
    h_lo = math.log(max(_H_BOUNDS[0], 0.35 * float(ab2[0])))
    h_hi = math.log(min(_H_BOUNDS[1], 0.7 * float(ab2[-1])))
    box_lo = [rho_lo] * n + [h_lo] * (n - 1)
    box_hi = [rho_hi] * n + [h_hi] * (n - 1)

    # ---- the candidates: the inversion's model and the polished starts ---
    chosen = inversion.model
    candidates = [(
        [float(v) for v in _pack(chosen.resistivities, chosen.thicknesses)],
        np.asarray(inversion.rho_calc, dtype=float),
    )]
    start_points = latin_hypercube(Stream(opts.seed, 0), n_starts, box_lo, box_hi)
    start_errors = []
    for k, point in enumerate(start_points):
        progress(f"starting model {k + 1} of {n_starts}")
        model, calc, err, _it, _conv = invert_model(
            ab2, rho_app, np.exp(point[:n]), np.exp(point[n:]),
            array_type, ves.damping, ves.max_iterations,
        )
        candidates.append((
            [float(v) for v in _pack(model.resistivities, model.thicknesses)],
            np.asarray(calc, dtype=float),
        ))
        start_errors.append(float(err))
        done += lm_weight

    chi2 = [_chi2(calc, log_obs, sigma) for _theta, calc in candidates]
    # Ranked on the misfit to six figures, the earlier first on a tie. Two
    # starts that polish to one minimum differ only in the last digits, and
    # differently in each engine, so ranking on those let the two engines
    # start a chain from different copies of the same model. The inversion's
    # own model comes first, so it wins such a tie.
    rank = [float(f"{c:.6g}") for c in chi2]
    best = min(range(len(candidates)), key=lambda i: (rank[i], i))
    dof = max(m - p, 1)
    widen = chi2[best] / dof
    scale = math.sqrt(widen) if widen > 1.0 else 1.0
    sigma_eff = sigma * scale
    chi2_scaled = [c / (scale * scale) for c in chi2]

    # chains start from the best fits that a sample of the posterior could
    # plausibly be: within p + 3 sqrt(2p) of the best in chi-squared, which
    # is where a p-parameter model's samples lie. One further off would
    # hold a chain in a minimum the data do not support.
    limit = chi2_scaled[best] + p + 3.0 * math.sqrt(2.0 * p)
    order = sorted(range(len(candidates)), key=lambda i: (rank[i], i))
    distinct: list[int] = []
    for i in order:
        if chi2_scaled[i] > limit:
            break
        if all(max(abs(a - b) for a, b in zip(candidates[i][0], candidates[k][0], strict=True))
               >= 0.01 for k in distinct):
            distinct.append(i)

    # ---- the step: shaped by the linearised covariance at the best fit ---
    theta_best = candidates[best][0]
    calc_best = candidates[best][1]
    res_best = np.log(np.maximum(calc_best, 1e-9)) - log_obs
    J = _jacobian(np.asarray(theta_best), res_best, log_obs, n, ab2, array_type)
    H = [[0.0] * p for _ in range(p)]
    for a in range(p):
        for b in range(p):
            s = 0.0
            for i in range(m):
                s += (J[i, a] / sigma_eff[i]) * (J[i, b] / sigma_eff[i])
            H[a][b] = s
        # the flat prior's own spread keeps a direction the data do not
        # constrain from asking for an infinite step
        width = hard_hi[a] - hard_lo[a]
        H[a][a] += 12.0 / (width * width)
    M = _cholesky_inverse_t(H)

    def evaluate(theta):
        rho = np.exp(theta[:n])
        h = np.exp(theta[n:])
        calc = np.maximum(_forward(rho, h, ab2, array_type), 1e-9)
        r = (np.log(calc) - log_obs) / sigma_eff
        return calc, -0.5 * float(r @ r)

    # ---- the chains ------------------------------------------------------
    kept: list[tuple] = []  # (theta, calc, summary) of each kept step
    accepted = []
    for c in range(n_chains):
        rng = Stream(opts.seed, c + 1)
        theta = list(candidates[distinct[c % len(distinct)]][0])
        calc, ll = evaluate(np.asarray(theta))
        summary = _summary(theta, n, investigation, ves)
        step = 2.38 / math.sqrt(p)
        keep = n_samples // n_chains + (1 if c < n_samples % n_chains else 0)
        window = 0
        hits = 0
        for k in range(burn_in + keep):
            z = [rng.symmetric() for _ in range(p)]
            u = rng.uniform()
            proposal = []
            inside = True
            for j in range(p):
                s = 0.0
                for q in range(j, p):
                    s += M[j][q] * z[q]
                v = theta[j] + step * s
                if v < hard_lo[j] or v > hard_hi[j]:
                    inside = False
                proposal.append(v)
            moved = False
            if inside:
                calc_p, ll_p = evaluate(np.asarray(proposal))
                d = ll_p - ll
                if d >= 0.0 or u < math.exp(d):
                    theta, calc, ll = proposal, calc_p, ll_p
                    summary = _summary(theta, n, investigation, ves)
                    moved = True
            if k < burn_in:
                window += moved
                if (k + 1) % _WINDOW == 0:
                    rate = window / _WINDOW
                    if rate < 0.15:
                        step *= 0.7
                    elif rate > 0.35:
                        step *= 1.4
                    window = 0
            else:
                hits += moved
                kept.append((theta, calc, summary))
            done += 1
            if done % 200 == 0:
                progress(f"chain {c + 1} of {n_chains}")
        accepted.append(hits)

    # ---- what the kept models say ---------------------------------------
    total = len(kept)
    basements = [s[0] for _t, _c, s in kept if s[0] is not None]
    deepest = sorted(s[2] for _t, _c, s in kept)
    p90 = percentile(deepest, 0.9)
    capped = p90 > investigation
    step_m = ves.round_drilling_depth_to_m
    drill = math.ceil(min(p90, investigation) / step_m) * step_m
    drill = min(drill, investigation)
    reach = [min(d, investigation) for d in deepest]  # still in order
    fan_count = min(max(int(opts.fan_models), 0), total)
    fan_at = [(k * total) // fan_count for k in range(fan_count)]
    progress("done")
    return ModelRange(
        sounding_id=sounding.sounding_id,
        n_layers=n,
        n_samples=total,
        chains=n_chains,
        starts=n_starts,
        seed=int(opts.seed),
        base_error_percent=float(opts.base_error_percent),
        overlap_spacings=overlap_spacings,
        error_scale=scale,
        acceptance=sum(accepted) / total,
        accepted=accepted,
        investigation_depth_m=investigation,
        basement_m=_band(basements) if basements else None,
        basement_unresolved=1.0 - len(basements) / total,
        weathered_m=_band([s[1] for _t, _c, s in kept]),
        resistivity=[_band([s[4][i] for _t, _c, s in kept]) for i in range(n)],
        interface_m=[_band([s[3][i] for _t, _c, s in kept]) for i in range(n - 1)],
        drilling_depth_m=float(drill),
        drilling_depth_capped=capped,
        chosen_error_percent=float(inversion.fit_error_percent),
        best_error_percent=float(min(
            fit_error_percent(rho_app, calc) for _theta, calc in candidates)),
        ab2=[float(v) for v in ab2],
        fan=[([math.exp(v) for v in kept[k][0][:n]],
              [math.exp(v) for v in kept[k][0][n:]]) for k in fan_at],
        fan_curves=[[float(v) for v in kept[k][1]] for k in fan_at],
        start_points=start_points,
        start_errors=start_errors,
        drilling_depth_quantiles_m=[percentile(reach, k / DEPTH_QUANTILES)
                                    for k in range(DEPTH_QUANTILES + 1)],
    )


# -------------------------------------------------------------------- prose

#: A depth range for basement is quoted only when at least this share of the
#: models that fit find one: a band read off the last few percent says more
#: about the sampler than about the ground.
MIN_RESOLVED_SHARE = 0.1


def quoted_basement_band(r: ModelRange) -> Band | None:
    """The depth range for basement the sentences, the table and the
    examples' CSV quote, or None where they quote none: at least
    ``MIN_RESOLVED_SHARE`` of the models must find basement. Compared on
    the unresolved share, as stored: 400 of 4,000 is exactly a tenth, but
    1 - (1 - 0.1) is a last bit under 0.1, and the band was dropped at the
    very share the rule says to quote it."""
    if r.basement_m is None or r.basement_unresolved > 1.0 - MIN_RESOLVED_SHARE:
        return None
    return r.basement_m


def _share(fraction: float) -> str:
    """A share as a whole percentage, never "0" or "100" for one that is not."""
    percent = 100.0 * fraction
    if 0.0 < percent < 0.5:
        return "under 1"
    if 99.5 <= percent < 100.0:
        return "over 99"
    return f"{percent:.0f}"


def model_range_text(r: ModelRange) -> list[str]:
    """The range in sentences: basement, the weathered zone, the drilling
    depth, any better fit the wider search found, and the basis."""
    doi = r.investigation_depth_m
    out = []
    basement = quoted_basement_band(r)
    if basement is None:
        out.append(phrase("ves_range.basement_unresolved",
                          share=_share(r.basement_unresolved), doi=doi))
    elif r.basement_unresolved == 0.0:
        out.append(phrase("ves_range.basement_always",
                          p10=basement.p10, p90=basement.p90))
    else:
        out.append(phrase("ves_range.basement", p10=basement.p10,
                          p90=basement.p90, share=_share(r.basement_unresolved)))
    if r.weathered_m.p90 < 0.5:
        out.append(phrase("ves_range.weathered_none"))
    else:
        out.append(phrase("ves_range.weathered", p10=r.weathered_m.p10,
                          p90=r.weathered_m.p90, doi=doi))
    if r.drilling_depth_capped:
        out.append(phrase("ves_range.drilling_capped", depth=r.drilling_depth_m, doi=doi))
    else:
        out.append(phrase("ves_range.drilling", depth=r.drilling_depth_m))
    # a better fit is worth a sentence only when it is better by more than
    # the search's own noise: a tenth of the misfit
    if r.best_error_percent < 0.9 * r.chosen_error_percent:
        out.append(phrase("ves_range.better_fit", layers=r.n_layers,
                          err=r.best_error_percent, chosen=r.chosen_error_percent))
    overlap = ""
    if r.overlap_spacings:
        overlap = phrase("ves_range.basis_overlap", count=len(r.overlap_spacings),
                         spacings=and_join([fmt_num(v) for v in r.overlap_spacings]))
    widened = ""
    if r.error_scale > 1.0:
        widened = phrase("ves_range.basis_widened", factor=r.error_scale)
    out.append(phrase(
        "ves_range.basis", samples=r.n_samples, layers=r.n_layers, chains=r.chains,
        fits=r.starts + 1, starts=r.starts, base=r.base_error_percent,
        overlap=overlap, widened=widened,
    ))
    return out


def model_range_rows(r: ModelRange) -> list[list[str]]:
    """The range as table rows - a label, then P10, P50 and P90 - for depth
    to basement (where the sentences quote a band for it), the weathered
    zone, each layer's resistivity and the base of each layer."""
    def row(label: str, band: Band) -> list[str]:
        return [label, fmt_num(band.p10), fmt_num(band.p50), fmt_num(band.p90)]

    out = []
    basement = quoted_basement_band(r)
    if basement is not None:
        out.append(row(phrase("ves_range.row_basement"), basement))
    out.append(row(phrase("ves_range.row_weathered"), r.weathered_m))
    out += [row(phrase("ves_range.row_resistivity", layer=i + 1), band)
            for i, band in enumerate(r.resistivity)]
    out += [row(phrase("ves_range.row_interface", layer=i + 1), band)
            for i, band in enumerate(r.interface_m)]
    return out


def model_range_table_caption(r: ModelRange) -> str:
    return phrase("ves_range.table_caption", sid=r.sounding_id)


def model_range_caption(r: ModelRange) -> str:
    """The sentence a figure with the fan adds to its caption."""
    return phrase("ves_range.caption", count=len(r.fan))
