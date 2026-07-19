import numpy as np
import pytest

from groundwater.models import LayeredModel, SiteMetadata, VESSounding
from groundwater.ves import classify_curve, interpret_model, invert_sounding
from groundwater.ves.arrays import geometric_factor
from groundwater.ves.forward import (
    forward_schlumberger,
    forward_schlumberger_finite_mn,
    forward_wenner,
    two_layer_schlumberger_series,
)
from groundwater.ves.interpret import drilling_preference_table
from groundwater.ves.inversion import fit_error_percent
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
