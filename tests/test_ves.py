import numpy as np
import pytest

from groundwater.models import LayeredModel, SiteMetadata, VESSounding
from groundwater.ves import classify_curve, interpret_model, invert_sounding
from groundwater.ves.arrays import geometric_factor
from groundwater.ves.forward import (
    forward_for_sounding,
    forward_schlumberger,
    forward_schlumberger_finite_mn,
    forward_schlumberger_models,
    forward_wenner,
    two_layer_schlumberger_series,
)
from groundwater.ves import forward, inversion
from groundwater.ves.interpret import drilling_preference_table
from groundwater.ves.inversion import (
    _forward_columns,
    _unpack,
    fit_error_percent,
)
from groundwater.ves.splice import splice_segments

AB2 = np.array([1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 50, 70, 80, 100], dtype=float)


def test_geometric_factor_schlumberger():
    # K = pi (L^2 - b^2) / (2b); L = 10, MN = 2 -> b = 1
    k = geometric_factor("schlumberger", ab2=10.0, mn=2.0)
    assert np.isclose(k, np.pi * (100 - 1) / 2.0)


def test_geometric_factor_wenner():
    assert np.isclose(geometric_factor("wenner", a=10.0), 2 * np.pi * 10.0)


def test_forward_half_space():
    rho = forward_schlumberger((np.array([500.0]), np.array([])), AB2)
    assert np.allclose(rho, 500.0, rtol=1e-9)


@pytest.mark.parametrize(
    "rho1,rho2,h",
    [(100, 2000, 5), (1000, 30, 8), (832, 36.7, 8.37), (50, 5000, 3), (2000, 20, 0.5)],
)
def test_forward_two_layer_vs_image_series(rho1, rho2, h):
    numeric = forward_schlumberger((np.array([rho1, rho2], float), np.array([h], float)), AB2)
    analytic = two_layer_schlumberger_series(rho1, rho2, h, AB2, n_terms=50000)
    assert np.max(np.abs(numeric - analytic) / analytic) < 5e-3


@pytest.mark.parametrize(
    "rho1,rho2,h,ab2_max",
    [(300, 30, 0.5, 1000), (1000, 10, 0.2, 1000), (100, 20, 0.05, 1000)],
)
def test_forward_stays_exact_when_the_spacing_dwarfs_the_layer(
    rho1, rho2, h, ab2_max
):
    """The quadrature runs out to the largest tabulated Bessel zero.

    A sounding needs panels out to 9 * (AB/2) / h_min, so the fixed 1200-zero
    table covered spacings only up to about 419 times the thinnest layer.
    Past that the integral was truncated part-way through an oscillation of
    J1, leaving a large spurious residue: 574 ohm-m instead of 30 at
    AB/2 = 1000 m over a 0.5 m layer. The inversion explores thin layers, so
    it can walk into that regime and fit against nonsense.
    """
    ab2 = np.array([1.0, 10.0, 100.0, 400.0, float(ab2_max)])
    numeric = forward_schlumberger(
        (np.array([rho1, rho2], float), np.array([h], float)), ab2
    )
    analytic = two_layer_schlumberger_series(rho1, rho2, h, ab2, n_terms=400000)
    assert np.max(np.abs(numeric - analytic) / analytic) < 5e-3


def test_forward_finite_mn_vs_image_series():
    rho1, rho2, h = 300.0, 30.0, 5.0
    k = (rho2 - rho1) / (rho2 + rho1)
    n = np.arange(1, 50001)

    def g(r):
        return 1.0 / r + 2.0 * np.sum(k**n / np.sqrt(r**2 + (2 * n * h) ** 2))

    for L, mn in [(20.0, 8.0), (40.0, 7.6), (80.0, 14.0)]:
        b = mn / 2.0
        expected = np.pi * (L**2 - b**2) / (2 * b) * (rho1 / np.pi) * (g(L - b) - g(L + b))
        numeric = forward_schlumberger_finite_mn(
            (np.array([rho1, rho2]), np.array([h])), np.array([L]), np.array([mn])
        )[0]
        assert abs(numeric - expected) / expected < 5e-3


def test_forward_wenner_vs_series():
    rho1, rho2, h = 300.0, 30.0, 5.0
    k = (rho2 - rho1) / (rho2 + rho1)
    n = np.arange(1, 50001)
    for a in (1.0, 20.0, 60.0):
        expected = rho1 * (
            1 + 4 * np.sum(k**n * (1 / np.sqrt(1 + (2 * n * h / a) ** 2)
                                   - 1 / np.sqrt(4 + (2 * n * h / a) ** 2)))
        )
        numeric = forward_wenner((np.array([rho1, rho2]), np.array([h])), np.array([a]))[0]
        assert abs(numeric - expected) / expected < 5e-3


@pytest.mark.parametrize("label", ["Wenner", " WENNER ", "Wenner alpha"])
def test_array_type_is_matched_regardless_of_case(label):
    """A capitalised "Wenner" must not be inverted as Schlumberger.

    forward_for_sounding and the inversion match the array with a bare
    startswith("wenner"), so an un-normalised label silently selected the
    wrong forward model - apparent resistivities out by tens of percent
    with no warning.
    """
    model = (np.array([300.0, 60.0, 2000.0]), np.array([2.0, 15.0]))
    a = np.array([1.0, 3.0, 10.0, 30.0, 60.0])
    sounding = VESSounding(
        site=SiteMetadata(community="T", district="Bo"), sounding_id="S1",
        ab2=a, mn=a / 3, rho_app=np.full_like(a, 100.0), array_type=label,
    )
    assert sounding.array_type == label.strip().lower()
    assert np.allclose(forward_for_sounding(model, sounding),
                       forward_wenner(model, a))


def test_splice_modes(rokel_ves_a):
    ab2, rho, shifts = splice_segments(rokel_ves_a, mode="merge")
    assert np.all(np.diff(ab2) > 0)  # strictly increasing
    assert len(ab2) == 14  # 18 readings, 4 duplicates merged
    assert all(s == 1.0 for s in shifts)
    _, _, shifts_first = splice_segments(rokel_ves_a, mode="first")
    assert shifts_first[0] == 1.0 and len(shifts_first) == 5


def test_inversion_recovers_synthetic_model():
    truth = (np.array([800.0, 60.0]), np.array([6.0]))
    ab2 = np.geomspace(1, 80, 15)
    rho_app = forward_schlumberger(truth, ab2)
    sounding = VESSounding(
        site=SiteMetadata(), sounding_id="SYN",
        ab2=ab2, mn=np.full_like(ab2, np.nan), rho_app=rho_app,
    )
    result = invert_sounding(sounding)
    assert result.fit_error_percent < 2.0
    assert result.model.n_layers == 2
    assert abs(result.model.resistivities[0] - 800) / 800 < 0.15
    assert abs(result.model.thicknesses[0] - 6.0) / 6.0 < 0.2


@pytest.mark.parametrize(
    "rho,thicknesses",
    [
        ([300.0, 55.0, 4000.0], [5.0, 60.0]),            # deep basement
        ([250.0, 900.0, 45.0, 3000.0], [2.0, 6.0, 35.0]),  # thick regolith
        ([200.0, 1500.0, 60.0, 4000.0], [1.5, 5.0, 25.0]),  # KH curve
    ],
)
def test_a_simple_model_never_hides_a_far_better_one(rho, thicknesses):
    """Parsimony accepted the simplest model under the 10 percent target.

    A two-layer model can sit at 8.8 percent while a three-layer one fits the
    same curve to 0.0 percent - and puts basement at 65 m instead of 4 m.
    Drilling depth comes straight off that, so the simple model has to be
    rejected when a richer one more than halves the misfit.
    """
    ab2 = np.geomspace(1, 100, 20)
    rho_app = forward_schlumberger(
        (np.array(rho, float), np.array(thicknesses, float)), ab2
    )
    sounding = VESSounding(
        site=SiteMetadata(community="S", district="Bo"), sounding_id="X",
        ab2=ab2, mn=ab2 / 5, rho_app=rho_app,
    )
    result = invert_sounding(sounding)
    recovered = float(np.sum(result.model.thicknesses))
    assert result.fit_error_percent < 1.0
    assert abs(recovered - sum(thicknesses)) / sum(thicknesses) < 0.25


def test_starting_interfaces_span_the_investigated_depth():
    """An n-layer model has n-1 interfaces. Spacing n depths and dropping the
    last left the deepest starting interface at the second point - 6 m for a
    sounding reaching 56 m - so every search began with basement far too
    shallow."""
    from groundwater.ves.inversion import _starting_models

    ab2 = np.array([1.0, 2, 3, 5, 10, 20, 40, 80])
    for n_layers in (3, 4, 5):
        for _, h0 in _starting_models(ab2, np.full_like(ab2, 100.0), n_layers):
            assert len(h0) == n_layers - 1
            # the deepest interface reaches the investigated depth scale
            assert np.sum(h0) >= 0.3 * ab2[-1]


def test_inversion_reports_parameter_uncertainty():
    truth = (np.array([800.0, 60.0]), np.array([6.0]))
    ab2 = np.geomspace(1, 80, 15)
    sounding = VESSounding(
        site=SiteMetadata(), sounding_id="SYN",
        ab2=ab2, mn=np.full_like(ab2, np.nan),
        rho_app=forward_schlumberger(truth, ab2),
    )
    result = invert_sounding(sounding)
    rf = result.rho_uncertainty_factor
    hf = result.h_uncertainty_factor
    assert rf is not None and hf is not None
    assert rf.shape == (2,) and hf.shape == (1,)
    # multiplicative 1-sigma factors are >= 1, finite, and capped at 10
    assert np.all(np.isfinite(rf)) and np.all(np.isfinite(hf))
    assert np.all(rf >= 1.0) and np.all(hf >= 1.0)
    assert np.all(rf <= 10.0) and np.all(hf <= 10.0)
    # a clean two-layer synthetic resolves the first-layer resistivity well
    assert rf[0] < 1.5


def test_inversion_rokel_beats_report_fit(rokel_ves_a):
    result = invert_sounding(rokel_ves_a)
    # the report's IPI2Win model shows ERR = 21.5; ours should be comparable
    assert result.fit_error_percent < 21.5
    ipi = LayeredModel(np.array([832.14, 2102.80, 36.71]), np.array([1.0, 7.37]))
    calc = forward_schlumberger(ipi, result.ab2)
    assert fit_error_percent(result.rho_obs, calc) > result.fit_error_percent


def test_classify_types():
    assert classify_curve(LayeredModel([100, 10, 1000], [2, 5])) == "H"
    assert classify_curve(LayeredModel([10, 100, 5], [2, 5])) == "K"
    assert classify_curve(LayeredModel([10, 100, 1000], [2, 5])) == "A"
    assert classify_curve(LayeredModel([1000, 100, 10], [2, 5])) == "Q"
    assert classify_curve(LayeredModel([100, 10, 1000, 5], [2, 5, 10])) == "HK"
    assert classify_curve(LayeredModel([500, 50], [5])) == "2-layer descending"


def test_interpretation_and_preference(rokel_ves_a):
    # interpret both report models: B should rank first, as in the report
    model_a = LayeredModel(np.array([832.14, 2102.80, 36.71]), np.array([1.0, 7.37]),
                           sounding_id="A (1)")
    model_b = LayeredModel(np.array([1398.18, 703.0, 1912.4, 34.71]),
                           np.array([0.71, 0.87, 8.42]), sounding_id="B (2)")
    interp_a = interpret_model(rokel_ves_a, model_a)
    interp_b = interpret_model(rokel_ves_a, model_b)
    assert interp_a.max_drilling_depth_m == 80  # capped at max AB/2
    assert interp_a.water_zones and interp_a.water_zones[0][1] == 80
    # both sites carry thick water zones; scores land within a few percent
    assert abs(interp_a.score - interp_b.score) / interp_a.score < 0.2

    rows = drilling_preference_table([interp_a, interp_b])
    ranks = {r["VES Point"]: r["Ranking"] for r in rows}
    assert sorted(ranks.values()) == ["1st", "2nd"]

    # near-ties are the analyst's call: the report preferred B, so the
    # explicit order reproduces the published ranking
    rows = drilling_preference_table([interp_a, interp_b], preferred_order=["B (2)"])
    ranks = {r["VES Point"]: r["Ranking"] for r in rows}
    assert ranks["B (2)"] == "1st" and ranks["A (1)"] == "2nd"


@pytest.mark.parametrize("ab2_max", [80.0, 300.0, 1000.0])
def test_a_batch_of_models_answers_exactly_as_one_at_a_time(ab2_max):
    """The batched forward model is the same numbers, not merely close.

    The inversion's Jacobian takes differences over a 1e-4 step, so a
    last-bit difference here is a different fitted layer sixty iterations
    later, not a rounding detail. ``ab2_max`` walks the batch across the
    reach threshold where it stops batching and evaluates one at a time.
    """
    rng = np.random.default_rng(19)
    ab2 = np.geomspace(1.0, ab2_max, 15)
    for n_layers in (1, 2, 3, 4):
        rho = np.exp(rng.uniform(np.log(5), np.log(9000), size=(6, n_layers)))
        # 0.2 m is the inversion's own thickness floor, and the reach it
        # implies is what the batch has to decide about
        h = np.exp(rng.uniform(np.log(0.2), np.log(80), size=(6, n_layers - 1)))
        batched = forward_schlumberger_models(rho, h, ab2)
        for k in range(len(rho)):
            alone = forward_schlumberger((rho[k], h[k]), ab2)
            assert np.array_equal(alone, batched[k])


def test_the_batched_jacobian_matches_a_column_by_column_one(rokel_ves_a):
    """The Jacobian must not depend on how its columns were assembled.

    Including the memory layout. The columns arrive from a transpose, and
    ``J.T @ J`` in the solver dispatches on layout: an F-ordered J takes a
    different path through BLAS and rounds differently, which twenty
    iterations later is a different fitted layer rather than a different
    last bit. The values alone do not catch that, so the layout is asserted
    on the array the inversion actually builds.
    """
    ab2 = rokel_ves_a.ab2
    n_layers = 3
    theta = np.log(np.array([1105.0, 1638.0, 47.3, 1.02, 7.08]))
    log_obs = np.log(rokel_ves_a.rho_app)
    res = np.log(
        np.maximum(forward_schlumberger(_unpack(theta, n_layers), ab2), 1e-9)
    ) - log_obs
    step = inversion.JACOBIAN_STEP

    reference = np.empty((len(ab2), len(theta)))
    for j in range(len(theta)):
        nudged = theta.copy()
        nudged[j] += step
        calc = forward_schlumberger(_unpack(nudged, n_layers), ab2)
        reference[:, j] = (np.log(np.maximum(calc, 1e-9)) - log_obs - res) / step

    built = inversion._jacobian(
        theta, res, log_obs, n_layers, ab2, "schlumberger"
    )
    assert np.array_equal(reference, built)
    assert built.flags.c_contiguous


def test_batching_does_not_move_the_inversion(rokel_ves_a, monkeypatch):
    """The fitted model must be the same whether or not the batch was taken.

    Deliberately a comparison and not a pinned number. LAPACK is not bit
    reproducible across BLAS builds - the same reason the browser build's
    parity check compares within a tolerance rather than byte for byte - so
    the last digits of a fitted layer legitimately differ between machines
    and no absolute value holds everywhere. What holds on every machine is
    that batching changes nothing on that machine.
    """
    batched = invert_sounding(rokel_ves_a)
    monkeypatch.setattr(forward, "_batchable", lambda *args, **kwargs: False)
    one_at_a_time = invert_sounding(rokel_ves_a)

    assert np.array_equal(
        batched.model.resistivities, one_at_a_time.model.resistivities
    )
    assert np.array_equal(
        batched.model.thicknesses, one_at_a_time.model.thicknesses
    )
    assert np.array_equal(batched.rho_calc, one_at_a_time.rho_calc)
    assert batched.fit_error_percent == one_at_a_time.fit_error_percent
    assert batched.n_iterations == one_at_a_time.n_iterations


def test_the_rokel_fit_stays_the_model_the_samples_were_built_from(rokel_ves_a):
    """A loose pin on the fitted layers, to catch a change of substance.

    The tolerance is deliberate: cross-BLAS variation moves these by about
    1e-8, so anything tighter fails on somebody else's machine, and the
    kind of mistake worth catching here - a different layer count, a layer
    an order of magnitude out - is nowhere near that small.
    """
    result = invert_sounding(rokel_ves_a)
    assert result.fit_error_percent == pytest.approx(13.3468506, rel=1e-6)
    assert list(result.model.resistivities) == pytest.approx(
        [1105.5107779, 1637.7603910, 47.2797656], rel=1e-6
    )
