"""The range of VES models (PLAN.md step 3.1): the generator, the error
model, the sampler on the Rokel pair, the sentences it prints, and a
calibration on synthetic soundings whose layers are known."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from groundwater.config import Config
from groundwater.ingestion.ves import overlap_ratios, read_ves_workbook
from groundwater.models import SiteMetadata, VESSounding
from groundwater.ves.forward import forward_schlumberger
from groundwater.ves.inversion import inversion_readings, invert_sounding
from groundwater.ves.model_range import (
    Band,
    ModelRange,
    Stream,
    latin_hypercube,
    model_range_text,
    percentile,
    reading_errors,
    sample_model_range,
)

ROKEL = Path(__file__).resolve().parents[1] / "examples" / "data" / "rokel" / "rokel_ves.xlsx"


def short_config(**overrides) -> Config:
    """A run small enough for the quick loop; the defaults are timed in bench/."""
    config = Config()
    config.ves_range.samples = 400
    config.ves_range.burn_in = 200
    config.ves_range.starts = 3
    config.ves_range.chains = 2
    for key, value in overrides.items():
        setattr(config.ves_range, key, value)
    return config


@pytest.fixture(scope="module")
def rokel():
    soundings = read_ves_workbook(ROKEL)
    return [(s, invert_sounding(s)) for s in soundings]


# ------------------------------------------------------------------ numbers

def test_the_generator_is_xoshiro128_starstar():
    """The published sequence from the state (1, 2, 3, 4), and the seeded
    words gwt-core.js is held to through reference.json."""
    rng = Stream(1)
    rng._s = [1, 2, 3, 4]
    assert [rng.next_u32() for _ in range(6)] == [
        11520, 0, 5927040, 70819200, 2031721883, 1637235492]
    seeded = Stream(1, 0)
    assert [seeded.next_u32() for _ in range(4)] == [
        1292791899, 1284423797, 2013314966, 3703690653]


def test_streams_are_separate_and_reproducible():
    a = [Stream(5, 1).next_u32() for _ in range(3)]
    assert a == [Stream(5, 1).next_u32() for _ in range(3)]
    assert Stream(5, 1).next_u32() != Stream(5, 2).next_u32()


def test_the_step_is_symmetric_with_unit_variance():
    rng = Stream(3, 9)
    draws = np.array([rng.symmetric() for _ in range(40000)])
    assert abs(draws.mean()) < 0.02
    assert abs(draws.var() - 1.0) < 0.03
    assert np.abs(draws).max() <= 2.0 * math.sqrt(3.0)


def test_uniforms_stay_inside_the_open_interval():
    rng = Stream(0, 0)
    values = [rng.uniform() for _ in range(5000)]
    assert min(values) > 0.0 and max(values) < 1.0
    assert all(0 <= rng.below(7) < 7 for _ in range(2000))


def test_latin_hypercube_puts_one_point_in_each_slice_of_every_axis():
    points = latin_hypercube(Stream(1, 0), 8, [0.0, -2.0, 10.0], [1.0, 2.0, 11.0])
    for j, (lo, hi) in enumerate([(0.0, 1.0), (-2.0, 2.0), (10.0, 11.0)]):
        slices = sorted(int((p[j] - lo) / (hi - lo) * 8) for p in points)
        assert slices == list(range(8))


def test_percentile_interpolates_between_order_statistics():
    values = sorted([3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0])
    for q in (0.1, 0.5, 0.9):
        assert percentile(values, q) == pytest.approx(np.percentile(values, 100 * q))
    assert percentile([7.0], 0.9) == 7.0


# ------------------------------------------------------------- error model

def test_the_error_model_adds_the_measured_overlap_disagreement(rokel):
    sounding, _ = rokel[0]
    ab2, _rho, _ = inversion_readings(sounding)
    sigma, spacings = reading_errors(sounding, ab2, 3.0)
    ratios = dict(overlap_ratios(sounding.ab2, sounding.rho_app))
    assert spacings and set(spacings) == set(ratios)
    for value, s in zip(ab2, sigma, strict=True):
        if value in ratios:
            d = 0.5 * math.log(ratios[value])
            assert s == pytest.approx(math.sqrt(0.03 ** 2 + d ** 2))
        else:
            assert s == 0.03


# ------------------------------------------------------------------ sampler

def test_the_range_is_reproducible_and_leaves_the_best_fit_alone(rokel):
    sounding, inversion = rokel[0]
    rho = inversion.model.resistivities.copy()
    calc = inversion.rho_calc.copy()
    first = sample_model_range(sounding, inversion, short_config())
    again = sample_model_range(sounding, inversion, short_config())
    assert first == again
    assert np.array_equal(inversion.model.resistivities, rho)
    assert np.array_equal(inversion.rho_calc, calc)
    assert first.n_samples == 400 and len(first.accepted) == 2
    assert first.n_layers == inversion.model.n_layers
    assert len(first.start_points) == 3 and len(first.start_errors) == 3
    for band in [first.weathered_m, *first.resistivity, *first.interface_m]:
        assert band.p10 <= band.p50 <= band.p90
    assert first.chosen_error_percent == inversion.fit_error_percent
    assert first.best_error_percent <= first.chosen_error_percent + 1e-9


def test_a_different_seed_draws_a_different_range(rokel):
    sounding, inversion = rokel[1]
    one = sample_model_range(sounding, inversion, short_config())
    two = sample_model_range(sounding, inversion, short_config(seed=2))
    assert one.start_points != two.start_points
    assert one.weathered_m != two.weathered_m


def test_the_drilling_depth_is_read_from_p90_and_stops_at_the_depth_of_investigation(rokel):
    for sounding, inversion in rokel:
        r = sample_model_range(sounding, inversion, short_config())
        assert r.drilling_depth_m <= r.investigation_depth_m
        if r.drilling_depth_capped:
            assert r.drilling_depth_m == r.investigation_depth_m
        assert r.drilling_depth_m % 5.0 == 0.0 or r.drilling_depth_capped


def test_a_misfit_beyond_the_errors_widens_them(rokel):
    # Rokel B's best two-layer fit misses by 27 percent against 3 percent
    # errors, so the errors are widened to that misfit rather than the range
    # being drawn as if the model described the curve
    sounding, inversion = rokel[1]
    r = sample_model_range(sounding, inversion, short_config())
    assert r.error_scale > 5.0


def test_a_sounding_that_fits_its_errors_is_not_widened():
    ab2 = np.geomspace(1.0, 100.0, 18)
    rho_app = forward_schlumberger((np.array([300.0, 60.0, 5000.0]), np.array([2.0, 15.0])), ab2)
    sounding = VESSounding(site=SiteMetadata(), sounding_id="exact", ab2=ab2,
                           mn=np.full(len(ab2), np.nan), rho_app=rho_app)
    inversion = invert_sounding(sounding)
    r = sample_model_range(sounding, inversion, short_config())
    assert r.error_scale == 1.0
    assert r.basement_m is not None
    assert r.basement_m.p10 <= 17.0 <= r.basement_m.p90


# --------------------------------------------------------------------- text

def _range(**changes) -> ModelRange:
    base = dict(
        sounding_id="VES 1", n_layers=3, n_samples=4000, chains=4, starts=8, seed=1,
        base_error_percent=3.0, overlap_spacings=[], error_scale=1.0, acceptance=0.25,
        accepted=[250, 250, 250, 250], investigation_depth_m=50.0,
        basement_m=Band(22.3, 27.0, 34.2), basement_unresolved=0.3,
        weathered_m=Band(12.0, 15.0, 19.6), resistivity=[], interface_m=[],
        drilling_depth_m=35.0, drilling_depth_capped=False,
        chosen_error_percent=4.0, best_error_percent=4.0, ab2=[],
    )
    base.update(changes)
    return ModelRange(**base)


def test_the_report_sentence_is_in_the_plans_form():
    text = model_range_text(_range())
    assert text[0] == ("Basement between 22 and 34 m (P10 to P90); not resolved "
                       "in 30 percent of the models that fit.")
    assert text[1] == ("Water-bearing weathered zone 12 to 20 m thick (P10 to P90), "
                       "counted from 3 m down to the 50 m the sounding resolves.")
    assert text[2] == "Drilling depth from the P90 of the models that fit: about 35 m."
    assert text[-1].startswith("Basis: 4000 models of 3 layers sampled by "
                               "Metropolis-Hastings in 4 chains")
    assert text[-1].endswith("with an error of 3 percent on each reading. "
                             "The error model is provisional.")


def test_the_sentences_cover_every_case():
    always = model_range_text(_range(basement_unresolved=0.0))
    assert always[0].endswith("and resolved in every model that fits.")
    rare = model_range_text(_range(basement_unresolved=0.95))
    assert rare[0] == ("Basement not resolved in 95 percent of the models that fit, "
                       "within the 50 m the sounding resolves.")
    none = model_range_text(_range(basement_m=None, basement_unresolved=1.0))
    assert none[0].startswith("Basement not resolved in 100 percent")
    tiny = model_range_text(_range(basement_unresolved=0.002))
    assert "not resolved in under 1 percent" in tiny[0]
    dry = model_range_text(_range(weathered_m=Band(0.0, 0.0, 0.2)))
    assert dry[1] == "No water-bearing weathered zone in at least 90 percent of the models that fit."
    capped = model_range_text(_range(drilling_depth_m=50.0, drilling_depth_capped=True))
    assert capped[2] == ("Drilling depth from the P90 of the models that fit: at least "
                         "50 m, cut back to the 50 m the sounding resolves.")
    better = model_range_text(_range(best_error_percent=2.0))
    assert better[3].startswith("The wider search found a 3-layer model that fits to 2.0 percent")
    widened = model_range_text(_range(overlap_spacings=[10.0, 40.0], error_scale=2.5))
    assert widened[-1].endswith(
        "each reading, plus the measured disagreement at the MN overlaps at AB/2 10 and "
        "40 m; the errors were widened 2.5 times, to the misfit the best model reaches. "
        "The error model is provisional.")


@pytest.mark.slow
def test_the_report_prints_the_range_beside_the_best_fit(rokel, tmp_path):
    from docx import Document

    from groundwater.reporting import build_geophysical_report
    from groundwater.reporting.geophysical import GeophysicalReportInputs
    from groundwater.ves import interpret_model

    soundings = [s for s, _ in rokel]
    inversions = [r for _, r in rokel]
    interps = [interpret_model(s, r.model) for s, r in rokel]
    ranges = [sample_model_range(s, r, short_config()) for s, r in rokel]

    def text(path):
        return "\n".join(p.text for p in Document(str(path)).paragraphs)

    plain = text(build_geophysical_report(
        GeophysicalReportInputs(soundings=soundings, inversions=inversions,
                                interpretations=interps, figures_dir=tmp_path),
        tmp_path / "plain.docx"))
    ranged = text(build_geophysical_report(
        GeophysicalReportInputs(soundings=soundings, inversions=inversions,
                                interpretations=interps, figures_dir=tmp_path,
                                model_ranges=[None, ranges[1]]),
        tmp_path / "ranged.docx"))
    sentences = " ".join(model_range_text(ranges[1]))
    assert sentences in ranged and "Metropolis" not in plain
    assert " ".join(model_range_text(ranges[0])) not in ranged
    assert "The grey fan is 40 of the sampled models that fit." in ranged
    # the best fit's own words are all still there
    for line in plain.splitlines():
        if "fitted with" in line or "resolves a" in line:
            assert line in ranged


def test_the_table_rows_follow_the_sentences():
    from groundwater.ves.model_range import model_range_rows

    r = _range(resistivity=[Band(300.0, 450.0, 1234.5)], interface_m=[Band(1.5, 2.0, 2.65)])
    assert model_range_rows(r) == [
        ["Depth to basement (m)", "22.3", "27", "34.2"],
        ["Water-bearing weathered zone (m)", "12", "15", "19.6"],
        ["Resistivity of layer 1 (ohm-m)", "300", "450", "1,230"],
        ["Base of layer 1 (m)", "1.5", "2", "2.65"],
    ]
    # no basement row where the sentences quote no band for it
    rare = model_range_rows(_range(basement_unresolved=0.95))
    assert rare[0][0] == "Water-bearing weathered zone (m)"


def test_the_settings_load_from_a_project_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("ves_range:\n  samples: 1000\n  base_error_percent: '5'\n", encoding="utf-8")
    config = Config.load(path)
    assert config.ves_range.samples == 1000
    assert config.ves_range.base_error_percent == 5.0


# -------------------------------------------------------------- calibration

# The calibration's soundings: three layers over crystalline basement, as a
# weathered profile is - a resistive cover, a conductive weathered zone and
# basement of 3,000 to 10,000 ohm-m within the depth of investigation - read
# at 19 spacings out to AB/2 = 100 m with 3 percent noise, the error the
# range assumes. Each is inverted as the toolkit inverts any sounding, layer
# count search included, and its range sampled with the default settings.
CALIBRATION_SOUNDINGS = 40
CALIBRATION_NOISE = 0.03
#: The rate a P10 to P90 band should hold the truth at, and how far the
#: measured rate may stray from it. With 40 soundings the binomial standard
#: error of an 80 percent rate is 6 points, so 15 is about two and a half.
STATED_RATE = 0.8
RATE_TOLERANCE = 0.15


@pytest.mark.slow
def test_the_bands_hold_the_true_depths_at_the_stated_rate():
    """Synthetic soundings with known layers: the true depth to basement
    lies inside the P10 to P90 band in about 80 percent of them, and so does
    every true interface where the inversion found the true layer count.

    On 4 October 2026 this measured 33 of 40 for basement (82 percent) and
    60 of 70 interfaces (86 percent), with 35 of the 40 inverted to three
    layers; three of the seven basement misses are soundings inverted to
    two, whose range is conditional on a layer count the ground does not
    have. It takes about three minutes.
    """
    rng = np.random.default_rng(7)
    ab2 = np.array([1, 1.5, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 80, 100],
                   dtype=float)
    config = Config()
    basement_hits = interface_hits = interfaces = 0
    for k in range(CALIBRATION_SOUNDINGS):
        rho = np.exp([rng.uniform(math.log(100), math.log(1000)),
                      rng.uniform(math.log(30), math.log(300)),
                      rng.uniform(math.log(3000), math.log(10000))])
        h = np.array([rng.uniform(1, 5), rng.uniform(5, 30)])
        observed = forward_schlumberger((rho, h), ab2) * np.exp(
            rng.normal(0.0, CALIBRATION_NOISE, len(ab2)))
        sounding = VESSounding(site=SiteMetadata(), sounding_id=f"S{k}", ab2=ab2.copy(),
                               mn=np.full(len(ab2), np.nan), rho_app=observed)
        inversion = invert_sounding(sounding)
        r = sample_model_range(sounding, inversion, config)
        depth = float(h.sum())
        b = r.basement_m
        basement_hits += b is not None and b.p10 <= depth <= b.p90
        if inversion.model.n_layers == 3:
            for band, true in zip(r.interface_m, np.cumsum(h), strict=True):
                interfaces += 1
                interface_hits += band.p10 <= true <= band.p90
    basement_rate = basement_hits / CALIBRATION_SOUNDINGS
    interface_rate = interface_hits / interfaces
    print(f"\nbasement inside P10-P90: {basement_hits}/{CALIBRATION_SOUNDINGS} "
          f"({basement_rate:.0%}); interfaces: {interface_hits}/{interfaces} "
          f"({interface_rate:.0%})")
    assert abs(basement_rate - STATED_RATE) <= RATE_TOLERANCE
    assert abs(interface_rate - STATED_RATE) <= RATE_TOLERANCE
    assert interfaces >= 40  # most soundings inverted to the true layer count
