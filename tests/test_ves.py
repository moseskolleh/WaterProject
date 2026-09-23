import numpy as np
import pytest

from groundwater.models import LayeredModel, SiteMetadata, VESSounding
from groundwater.ves import classify_curve, interpret_model, invert_sounding
from groundwater.ves.arrays import geometric_factor
from groundwater.ves.forward import (
    forward_for_sounding,
    forward_schlumberger,
    forward_schlumberger_finite_mn,
    forward_wenner,
    two_layer_schlumberger_series,
)
from groundwater.ves.interpret import drilling_preference_table
from groundwater.ves.inversion import fit_error_percent
from groundwater.ves.plots import plot_geoelectric_section
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
    """A conductive half-space is an open-ended zone, not an aquifer 72 m thick.

    Both report models end in a 35-37 ohm-m half-space below about 8-10 m.
    The sounding was expanded to AB/2 = 80 m, which resolves the ground to
    about 40 m: the zone runs from 8 m to at least 40 m, the thickness is a
    minimum, the drilling depth is a minimum, and the interpretation says so.
    It used to run to 80 m, the array length, and recommend drilling there.
    """
    model_a = LayeredModel(np.array([832.14, 2102.80, 36.71]), np.array([1.0, 7.37]),
                           sounding_id="A (1)")
    model_b = LayeredModel(np.array([1398.18, 703.0, 1912.4, 34.71]),
                           np.array([0.71, 0.87, 8.42]), sounding_id="B (2)")
    interp_a = interpret_model(rokel_ves_a, model_a)
    interp_b = interpret_model(rokel_ves_a, model_b)
    assert interp_a.max_spacing_m == 80
    assert interp_a.investigation_depth_m == 40  # half the largest AB/2
    assert interp_a.max_drilling_depth_m == 40  # capped at the depth of investigation
    assert interp_a.water_zones and interp_a.water_zones[0][1] == 40
    assert interp_a.basement_not_resolved
    assert any(f.code == "basement_not_resolved" for f in interp_a.flags)
    assert "at least 40 m" in interp_a.narrative
    assert "base is not resolved" in interp_a.narrative
    assert "fractured bedrock" not in interp_a.layers[-1].unit
    # neither transcribed model carries a misfit, so only the unresolved
    # basement discounts them, equally
    assert interp_a.confidence == interp_b.confidence == 0.85
    assert interp_a.fit_quality == "ok"

    rows = drilling_preference_table([interp_a, interp_b])
    ranks = {r["VES Point"]: r["Ranking"] for r in rows}
    # the two transcribed models score within the tie margin, so the table
    # does not rank them 1st and 2nd on a difference the ranking cannot see
    assert sorted(ranks.values()) == ["=1st", "=1st"]
    assert "Layer resistivity (ohm-m)" in rows[0]
    assert "Apparent Resistivity (Ohm-m)" not in rows[0]
    assert rows[0]["Possible Water Zones (m)"].endswith("+")
    assert rows[0]["Max Drilling Depth (m)"] == "at least 40 m"

    # near-ties are the analyst's call: preferred_order still sets the ranking
    rows = drilling_preference_table([interp_a, interp_b], preferred_order=["B (2)"])
    ranks = {r["VES Point"]: r["Ranking"] for r in rows}
    assert ranks["B (2)"] == "1st"


def test_a_poor_fit_is_flagged_and_discounts_the_ranking(rokel_ves_a):
    """The Rokel models never reach the 10 percent target; the report used to
    prefer B (2), fitted to 26.8 percent, over A (1) at 13.3 percent, on a
    2.7 ohm-m difference in half-space resistivity."""
    from groundwater.ves.interpret import fit_confidence, rank_interpretations

    assert fit_confidence(5.0) == 1.0
    assert fit_confidence(10.0) == 1.0
    assert abs(fit_confidence(15.0) - 0.75) < 1e-9
    assert fit_confidence(20.0) == 0.5
    assert fit_confidence(40.0) == 0.5

    good = LayeredModel(np.array([1100.0, 1600.0, 47.0]), np.array([1.0, 7.0]),
                        fit_error_percent=13.3, sounding_id="A (1)")
    bad = LayeredModel(np.array([1190.0, 50.0]), np.array([8.3]),
                       fit_error_percent=26.8, sounding_id="B (2)")
    interp_good = interpret_model(rokel_ves_a, good)
    interp_bad = interpret_model(rokel_ves_a, bad)
    assert interp_good.fit_quality == "poor"
    assert interp_bad.fit_quality == "unreliable"
    assert [f.code for f in interp_bad.flags][:1] == ["poor_fit"]
    assert "indicative only" in interp_bad.narrative
    assert "approximate" in interp_good.narrative
    assert interp_bad.confidence < interp_good.confidence < 1.0

    ranked = rank_interpretations([interp_bad, interp_good])
    assert [i.sounding_id for i in ranked] == ["A (1)", "B (2)"]


def test_the_drilling_depth_is_a_minimum_when_the_base_was_never_reached():
    from groundwater.ves.interpret import SiteInterpretation, drilling_depth_text

    resolved = SiteInterpretation(
        sounding_id="R", model=LayeredModel([1000.0, 50.0, 3000.0], [5.0, 20.0]),
        curve_type="H", layers=[], water_zones=[(5, 25)], depth_to_basement_m=25.0,
        aquifer_thickness_m=20.0, max_drilling_depth_m=35.0, investigation_depth_m=50.0,
        score=1.0,
    )
    assert drilling_depth_text(resolved) == "about 35 m"
    resolved.basement_not_resolved = True
    assert drilling_depth_text(resolved) == "at least 35 m"


def test_a_section_will_not_draw_a_sounding_it_was_not_given():
    """Positions and labels must match the models one for one.

    The workbook reader skips a sheet whose resistivity column was never
    labelled, so a survey typed up as three chainages can arrive here as two
    models. Zipped, that drew the section a sounding short - or, when the
    labels were the longer list, put every label against the wrong column -
    and the finished figure gave no sign of it.
    """
    models = [
        LayeredModel(np.array([500.0, 40.0]), np.array([6.0]), sounding_id="A"),
        LayeredModel(np.array([700.0, 55.0]), np.array([8.0]), sounding_id="B"),
    ]

    with pytest.raises(ValueError, match="2 soundings need 2 positions"):
        plot_geoelectric_section(models, positions=[0.0, 60.0, 120.0],
                                 labels=["A", "B"], depth_max=45.0)

    with pytest.raises(ValueError, match="2 soundings need 2 positions"):
        plot_geoelectric_section(models, positions=[0.0, 60.0],
                                 labels=["A", "B", "C"], depth_max=45.0)

    with pytest.raises(ValueError, match="at least one sounding"):
        plot_geoelectric_section([], depth_max=45.0)

    # the matched case still draws
    fig = plot_geoelectric_section(models, positions=[0.0, 60.0],
                                   labels=["A", "B"], depth_max=45.0)
    assert fig is not None


def test_the_layer_search_does_not_stop_at_a_good_enough_two_layer_fit():
    """A noise-free A-type curve over a 15 m aquifer above basement: the
    two-layer model fits to 4.7%, under the target, and the search used to
    stop there - reporting basement at 6 m instead of 19 m and no water
    zone at all. The richer model must at least be tried so the parsimony
    rule can see that it fits an order of magnitude better."""
    ab2 = np.array([1, 1.5, 2, 3, 4, 5, 7, 10, 15, 20, 30, 40, 50, 70, 100], float)
    rho_app = forward_schlumberger(
        (np.array([100.0, 400.0, 3000.0]), np.array([4.0, 15.0])), ab2
    )
    sounding = VESSounding(
        site=SiteMetadata(community="synthetic"), sounding_id="S1",
        ab2=ab2, mn=np.full_like(ab2, np.nan), rho_app=rho_app,
    )
    result = invert_sounding(sounding)
    assert result.model.n_layers == 3
    assert abs(float(np.sum(result.model.thicknesses)) - 19.0) / 19.0 < 0.25
    assert result.fit_error_percent < 1.0
    assert [n for n, _ in result.trials][:2] == [2, 3]


# --- reading the array from the sheet (ROADMAP data-ingestion-11) -----------

def _ves_sheet(path, header_block, columns, rows):
    """Write a VES field sheet as CSV: a header block, then the data table."""
    lines = [",".join(str(cell) for cell in row) for row in header_block]
    lines.append("")
    lines.append(",".join(columns))
    lines += [",".join(str(value) for value in row) for row in rows]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_a_wenner_sheet_headed_ab_over_two_is_read_at_its_own_spacing(tmp_path):
    """A Wenner sounding headed AB/2 was inverted with AB/2 for the spacing a.

    The Wenner array is A M N B at one spacing a, so AB = 3a and the AB/2
    column of a Wenner sheet holds 1.5 a. Read as a, every reading sat at
    half again its true spacing: the curve shifted bodily along the depth
    axis, and since the array was never established from the sheet the
    Schlumberger kernel was often used on it as well.
    """
    from groundwater.ingestion.ves import read_ves_csv

    model = (np.array([300.0, 30.0, 900.0]), np.array([3.0, 12.0]))
    a = np.array([1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 20.0, 30.0])
    rho = forward_wenner(model, a)
    path = _ves_sheet(
        tmp_path / "wenner_ab2.csv",
        [["Community", "Rokel"], ["Sounding Number", "W 1"], ["Array", "Wenner"]],
        ["No.", "AB/2 (m)", "Apparent Resistivity (ohm-m)"],
        [[i + 1, 1.5 * spacing, value]
         for i, (spacing, value) in enumerate(zip(a, rho, strict=True))],
    )

    sounding = read_ves_csv(path)
    assert sounding.array_type == "wenner"
    assert np.allclose(sounding.ab2, a)  # a, not the tabulated 1.5 a
    # so the sounding reproduces the model it was synthesised from
    assert np.allclose(forward_for_sounding(model, sounding), rho)
    assert [f.code for f in sounding.flags] == ["wenner_spacing_from_ab2"]
    assert "two thirds" in sounding.flags[0].message


def test_a_column_headed_a_is_the_wenner_spacing_not_a_sheet_without_a_table(tmp_path):
    """A column headed "a" had no meaning to the reader at all.

    A Wenner sheet that tabulates its spacing the way Wenner sheets do was
    dropped whole, as a sheet with no data table, so the sounding never
    reached the report and the only trace was a skipped-sheet warning.
    """
    from groundwater.ingestion.ves import read_ves_csv

    a = [1.0, 2.0, 3.0, 5.0, 8.0]
    rho = [420.0, 400.0, 350.0, 190.0, 96.0]
    path = _ves_sheet(
        tmp_path / "wenner_a.csv",
        [["Community", "Rokel"], ["Sounding Number", "W 2"]],
        ["No.", "a (m)", "Apparent Resistivity (ohm-m)"],
        [[i + 1, s, r] for i, (s, r) in enumerate(zip(a, rho, strict=True))],
    )

    sounding = read_ves_csv(path)
    assert sounding.array_type == "wenner"
    assert list(sounding.ab2) == a  # the a column is the spacing as it stands
    assert list(sounding.rho_app) == rho
    assert [f.code for f in sounding.flags] == ["array_type_inferred"]


def test_a_wenner_resistance_sheet_uses_the_wenner_geometric_factor(tmp_path):
    """A sheet that records V/I needs K to become a resistivity, and the
    reader knew only the Schlumberger factor, which needs an MN spacing a
    Wenner sheet does not carry: K stayed unknown and every row was dropped.
    The Wenner factor is 2 pi a and needs nothing but the spacing."""
    from groundwater.ingestion.ves import read_ves_csv

    a = [1.0, 2.0, 5.0, 10.0]
    resistance = [66.8, 31.8, 11.1, 3.05]
    path = _ves_sheet(
        tmp_path / "wenner_resistance.csv",
        [["Sounding Number", "W 3"], ["Array", "Wenner alpha"]],
        ["No.", "a (m)", "R (ohm)"],
        [[i + 1, s, r] for i, (s, r) in enumerate(zip(a, resistance, strict=True))],
    )

    sounding = read_ves_csv(path)
    assert sounding.array_type == "wenner"
    assert sounding.n_readings == 4
    expected = [float(geometric_factor("wenner", a=s)) * r
                for s, r in zip(a, resistance, strict=True)]
    assert np.allclose(sounding.rho_app, expected)
    assert [f.code for f in sounding.flags] == ["rho_computed_from_resistance"]


def test_an_unnamed_array_is_recorded_as_assumed_not_chosen_in_silence(tmp_path):
    """Schlumberger was the default for every sheet, whatever the sheet said
    or failed to say. A sheet that names no array and carries no MN column
    settles nothing, and a Wenner sounding inverted as Schlumberger is wrong
    by tens of percent, so the assumption now goes on the record."""
    from groundwater.ingestion.ves import read_ves_csv

    rows = [[1, 1.0, 420.0], [2, 2.0, 400.0], [3, 5.0, 190.0], [4, 10.0, 96.0]]
    path = _ves_sheet(
        tmp_path / "silent.csv", [["Sounding Number", "S 1"]],
        ["No.", "AB/2 (m)", "Apparent Resistivity (ohm-m)"], rows,
    )
    sounding = read_ves_csv(path)
    assert sounding.array_type == "schlumberger"
    assert [f.code for f in sounding.flags] == ["array_type_assumed"]
    assert sounding.flags[0].level == "warning"
    assert "Schlumberger was assumed" in sounding.flags[0].message

    # an MN column is the Schlumberger construct, and settles it: the sheets
    # the toolkit has always read are not now flagged for saying nothing
    with_mn = _ves_sheet(
        tmp_path / "schlumberger.csv", [["Sounding Number", "S 2"]],
        ["No.", "AB/2 (m)", "MN (m)", "Apparent Resistivity (ohm-m)"],
        [[i + 1, ab2, 0.5, rho] for i, (_n, ab2, rho) in enumerate(rows)],
    )
    assert read_ves_csv(with_mn).flags == []


def test_a_sheet_that_contradicts_itself_about_the_array_is_not_guessed_at(tmp_path):
    """The header block says Schlumberger and the table heads its spacing
    column "a", the Wenner spacing. The two readings of that one column
    differ by half again, so the reader keeps the default and says what it
    assumed rather than picking the array it likes."""
    from groundwater.ingestion.ves import read_ves_csv

    path = _ves_sheet(
        tmp_path / "conflict.csv",
        [["Sounding Number", "S 3"], ["Array", "Schlumberger"]],
        ["No.", "a (m)", "Apparent Resistivity (ohm-m)"],
        [[1, 1.0, 420.0], [2, 2.0, 400.0], [3, 5.0, 190.0], [4, 10.0, 96.0]],
    )

    sounding = read_ves_csv(path)
    assert sounding.array_type == "schlumberger"
    assert list(sounding.ab2) == [1.0, 2.0, 5.0, 10.0]  # taken as AB/2, unconverted
    assert [f.code for f in sounding.flags] == ["array_type_conflict"]
    assert sounding.flags[0].level == "warning"


def test_an_array_the_reader_cannot_place_is_named_in_the_flag(tmp_path):
    """"Dipole-dipole" in the array field was read straight into array_type,
    where every downstream startswith("wenner") test failed and the sounding
    was inverted as Schlumberger without a word. The toolkit models two
    arrays; a sheet naming a third has to say so on the face of the report."""
    from groundwater.ingestion.ves import read_ves_csv

    path = _ves_sheet(
        tmp_path / "dipole.csv",
        [["Sounding Number", "S 4"], ["Array", "Dipole-dipole"]],
        ["No.", "AB/2 (m)", "MN (m)", "Apparent Resistivity (ohm-m)"],
        [[1, 1.0, 0.5, 420.0], [2, 2.0, 0.5, 400.0],
         [3, 5.0, 0.5, 190.0], [4, 10.0, 0.5, 96.0]],
    )

    sounding = read_ves_csv(path)
    assert sounding.array_type == "schlumberger"
    assert [f.code for f in sounding.flags] == ["array_type_unrecognised"]
    assert "Dipole-dipole" in sounding.flags[0].message


# --- the interpretation stops where the sounding stops seeing ---------------

def _synthetic_interp(sid, rho, h, err=5.0, ab2=(1, 2, 5, 10, 20, 40, 80), rho_app=None,
                      h_factor=None):
    ab2 = np.array(ab2, dtype=float)
    model = LayeredModel(np.array(rho, float), np.array(h, float),
                         fit_error_percent=err, sounding_id=sid)
    if h_factor is not None:
        model.h_uncertainty_factor = np.array(h_factor, float)
    sounding = VESSounding(
        site=SiteMetadata(), sounding_id=sid, ab2=ab2, mn=np.full_like(ab2, np.nan),
        rho_app=np.array(rho_app if rho_app is not None else [100.0] * len(ab2), float),
    )
    return interpret_model(sounding, model)


def test_nothing_below_the_depth_of_investigation_is_reported_as_resolved():
    """A sounding to AB/2 80 m sees about 40 m. A weathered zone the model
    carries from 5 m to 65 m used to be reported as "5 m to 65 m", with
    basement at 65 m and "drill about 40 m": the zone and the basement came
    from the model's extrapolation, and only the drilling depth was cut back,
    silently. A zone wholly below the depth of investigation was reported as
    a zone, with a depth to bedrock, and ranked as a good target."""
    from groundwater.siting import assess_siting
    from groundwater.ves.interpret import drilling_depth_text

    past = _synthetic_interp("past", [1000, 100, 5000], [5, 60])
    assert past.investigation_depth_m == 40
    assert past.water_zones == [(5, 40)]
    assert past.basement_not_resolved and past.drilling_depth_capped
    assert past.depth_to_basement_m is None
    assert drilling_depth_text(past) == "at least 40 m"
    assert "5 m to at least 40 m" in past.narrative
    assert "depth to bedrock is not resolved within the depth of investigation" in past.narrative
    flag = next(f for f in past.flags if f.code == "basement_not_resolved")
    assert "the model puts its base at 65 m" in flag.message
    assert "half-space" not in flag.message

    below = _synthetic_interp("below", [1000, 1500, 100, 5000], [10, 40, 20],
                              ab2=(1, 2, 5, 10, 20, 40, 60))
    assert below.investigation_depth_m == 30
    assert below.water_zones == [] and below.depth_to_basement_m is None
    assert ("The water-bearing layer from 50 m lies below the 30 m the sounding "
            "resolves, so it is not counted as a water zone.") in below.narrative
    assert assess_siting([below])[0].suitability < 35

    # a zone resolved inside the depth of investigation, whose margin is not
    margin = _synthetic_interp("margin", [1000, 100, 5000], [5, 33])
    assert margin.water_zones == [(5, 38)] and margin.depth_to_basement_m == 38
    assert not margin.basement_not_resolved and margin.drilling_depth_capped
    assert drilling_depth_text(margin) == "at least 40 m"


def test_the_depth_of_investigation_comes_from_the_readings_that_were_fitted():
    """A last reading recorded as 0 is dropped by the inversion, and the
    depth of investigation used to count it anyway: 40 m from a sounding
    whose deepest fitted reading was AB/2 40 m."""
    interp = _synthetic_interp("zero", [1000, 100], [8],
                               rho_app=[300, 250, 200, 150, 120, 110, 0])
    assert interp.max_spacing_m == 40
    assert interp.investigation_depth_m == 20
    assert interp.water_zones == [(8, 20)]


def test_two_soundings_with_one_id_are_ranked_on_their_own_weights():
    """A copied sheet with an unchanged Sounding Number gave both soundings
    the weight of the last one, so a point with no water zone could come
    first while the suitability table ranked the other."""
    from groundwater.siting import assess_siting
    from groundwater.ves.interpret import rank_interpretations

    weak = _synthetic_interp("VES 1", [300, 1500], [30])
    strong = _synthetic_interp("VES 1", [1000, 100, 5000], [5, 20])
    ranked = rank_interpretations([weak, strong])
    assert ranked[0] is strong and strong.rank == 1 and weak.rank == 2
    suit = assess_siting([weak, strong])
    assert suit[0].rationale == assess_siting([strong])[0].rationale
    rows = drilling_preference_table([weak, strong])
    assert [r["Possible Water Zones (m)"] for r in rows] == ["5-25", "none resolved"]


def test_a_poorly_resolved_boundary_is_not_read_as_a_resolved_layer(rokel_ves_a):
    """"The data at A (1) resolves a 3 layer subsurface" stood a paragraph
    after the report said its first boundary was known only to x/ 3.7."""
    soft = _synthetic_interp("A (1)", [1100, 1600, 47], [1.0, 7.0], h_factor=[3.7, 1.4])
    assert soft.narrative.startswith(
        "The data at A (1) are fitted with a 3 layer model (")
    assert ("though the boundary at 1 m is poorly resolved, so the layer count is "
            "uncertain.") in soft.narrative
    assert "resolves a 3 layer subsurface" not in soft.narrative
    firm = _synthetic_interp("A (1)", [1100, 1600, 47], [1.0, 7.0], h_factor=[1.2, 1.4])
    assert firm.narrative.startswith("The data at A (1) resolves a 3 layer subsurface")

    # the inversion hands its thickness uncertainty on with the model
    result = invert_sounding(rokel_ves_a)
    assert np.array_equal(result.model.h_uncertainty_factor, result.h_uncertainty_factor)


def test_a_sheet_named_wenner_that_carries_schlumberger_marks_is_warned_about(tmp_path):
    """A Schlumberger sheet with only its array field changed to "Wenner" was
    read as Wenner, every spacing divided by 1.5, with nothing but
    information notes: its MN column and the AB/2 repeated at each MN change
    are things a Wenner array cannot have."""
    from groundwater.ingestion.ves import read_ves_csv

    rows = [[1, 1.5, 1.0, 300.0], [2, 3.0, 1.0, 280.0], [3, 6.0, 1.0, 200.0],
            [4, 6.0, 4.0, 190.0], [5, 15.0, 4.0, 120.0], [6, 30.0, 4.0, 90.0]]
    path = _ves_sheet(
        tmp_path / "relabelled.csv",
        [["Sounding Number", "W 5"], ["Array", "Wenner"]],
        ["No.", "AB/2 (m)", "MN (m)", "Apparent Resistivity (ohm-m)"], rows,
    )
    sounding = read_ves_csv(path)
    assert sounding.array_type == "wenner"
    flag = next(f for f in sounding.flags if f.code == "array_type_wenner_contradicted")
    assert flag.level == "warning"
    assert "its MN column holds spacings other than a and it repeats 1 spacing" in flag.message

    # a Wenner sheet that tabulates MN keeps it equal to a, and is not flagged
    honest = _ves_sheet(
        tmp_path / "wenner_mn.csv",
        [["Sounding Number", "W 6"], ["Array", "Wenner"]],
        ["No.", "AB/2 (m)", "MN (m)", "Apparent Resistivity (ohm-m)"],
        [[1, 1.5, 1.0, 300.0], [2, 3.0, 2.0, 280.0], [3, 7.5, 5.0, 200.0],
         [4, 15.0, 10.0, 120.0]],
    )
    assert "array_type_wenner_contradicted" not in [f.code for f in read_ves_csv(honest).flags]
