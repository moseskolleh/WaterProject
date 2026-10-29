"""Toolkit configuration: house style, analysis defaults and design rules.

All values can be overridden per project from a ``config.yaml`` placed
in the project folder, so client specific standards do not require code
changes.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

from ._resources import bundled_json

# The default of every setting below is in data/defaults.json, which the
# browser reads too (web/build_webapp_data.py emits it into gwt-data.js), so
# the two apps cannot start from different numbers. The fields, their types
# and the reasons for each value stay here.
_DEFAULTS = bundled_json("defaults.json")
_STYLE, _VES, _PUMPING, _DESIGN = (
    _DEFAULTS["style"], _DEFAULTS["ves"], _DEFAULTS["pumping"], _DEFAULTS["design"],
)
_RANGE = _DEFAULTS["ves_range"]
_ODDS = _DEFAULTS["odds"]
_LEDGER = _DEFAULTS["ledger"]
_COSTS = _DEFAULTS["cost_range"]
_TERRAIN = _DEFAULTS["terrain"]


# ---------------------------------------------------------------------------
# House style (figures and reports)
# ---------------------------------------------------------------------------

@dataclass
class HouseStyle:
    accent_color: str = _STYLE["accent_color"]  # muted blue used for headings and curves
    secondary_color: str = _STYLE["secondary_color"]  # burnt orange for model/overlay lines
    neutral_color: str = _STYLE["neutral_color"]
    background: str = _STYLE["background"]
    font_name: str = _STYLE["font_name"]
    base_font_size_pt: float = _STYLE["base_font_size_pt"]
    figure_dpi: int = _STYLE["figure_dpi"]
    figure_width_in: float = _STYLE["figure_width_in"]  # fits A4 with 2.5 cm margins
    organisation: str = _STYLE["organisation"]
    organisation_details: str = _STYLE["organisation_details"]
    logo_path: str = _STYLE["logo_path"]  # optional logo for report headers


# ---------------------------------------------------------------------------
# VES analysis defaults
# ---------------------------------------------------------------------------

@dataclass
class VESConfig:
    max_layers: int = _VES["max_layers"]
    min_layers: int = _VES["min_layers"]
    target_fit_percent: float = _VES["target_fit_percent"]  # accept the simplest model under this
    # ...but only while no richer model more than halves its misfit. A
    # two-layer model can sit just under the target while a three-layer one
    # fits the same curve an order of magnitude better and puts basement at
    # 65 m instead of 4 m - the difference between drilling into the aquifer
    # and stopping in the regolith.
    parsimony_max_error_ratio: float = _VES["parsimony_max_error_ratio"]
    damping: float = _VES["damping"]
    max_iterations: int = _VES["max_iterations"]
    # hydrogeological interpretation thresholds (ohm-m), crystalline basement
    fresh_basement_min_rho: float = _VES["fresh_basement_min_rho"]
    fractured_zone_rho: tuple = tuple(_VES["fractured_zone_rho"])  # likely water bearing when saturated
    clay_max_rho: float = _VES["clay_max_rho"]
    laterite_min_rho: float = _VES["laterite_min_rho"]  # dry laterite / duricrust near surface
    max_drilling_margin_m: float = _VES["max_drilling_margin_m"]  # added below deepest target zone
    round_drilling_depth_to_m: float = _VES["round_drilling_depth_to_m"]
    # Depth of investigation as a fraction of the largest current-electrode
    # half-spacing AB/2. A Schlumberger sounding resolves the ground to about
    # a half to a third of its largest AB/2 (Roy and Apparao 1971; Barker
    # 1989), not to the spacing itself. This one number sets how deep the
    # interpretation, every figure and the drilling-depth cap reach: an 80 m
    # spread used to put a "water zone" and a drilling depth at 80 m, which
    # was the array length and nothing the data had seen.
    depth_of_investigation_factor: float = _VES["depth_of_investigation_factor"]
    # When no candidate model reaches the target, the simplest model whose
    # misfit is within this ratio of the best fit is kept: extra layers must
    # earn their keep. It used to be an undocumented constant in the search.
    parsimony_fallback_ratio: float = _VES["parsimony_fallback_ratio"]
    # A misfit above the target is flagged as poor; above this it is
    # unreliable and the layer depths are indicative only. IPI2Win users
    # read ERR above about 10 percent as a poor fit and above 20 as one
    # that does not describe the curve.
    unreliable_fit_percent: float = _VES["unreliable_fit_percent"]
    # Confidence weights applied to a point's suitability when ranking. A
    # fit at the target keeps 1.0 and one at the unreliable level keeps the
    # floor; a conductive half-space whose base the sounding never reached
    # is discounted because its thickness is unknown, not measured.
    fit_confidence_floor: float = _VES["fit_confidence_floor"]
    unresolved_basement_confidence: float = _VES["unresolved_basement_confidence"]
    # Two points whose confidence-weighted suitabilities differ by less than
    # this are indistinguishable on geophysical grounds, and the report says
    # so instead of printing 1st and 2nd.
    ranking_tie_points: float = _VES["ranking_tie_points"]
    # The suitability score's weights on its four parts (siting/suitability.py),
    # adding to 1. They are a defensible default, not a calibrated model, and
    # they used to be hard-coded there; a calibration set (PLAN.md step 5.3)
    # that fits them puts its own in force here once a named person adopts
    # it. They have nothing to do with the inversion, so the cache key of a
    # saved inversion (ves/cache.py) leaves them out.
    suitability_weights: dict = field(default_factory=lambda: dict(_VES["suitability_weights"]))


# ---------------------------------------------------------------------------
# Pumping test defaults
# ---------------------------------------------------------------------------

@dataclass
class PumpingConfig:
    safety_factor: float = _PUMPING["safety_factor"]  # applied to long term yield, stated in reports
    design_period_days: float = _PUMPING["design_period_days"]  # projection horizon for safe yield
    available_drawdown_fraction: float = _PUMPING["available_drawdown_fraction"]  # usable share of available drawdown
    pump_clearance_above_screen_m: float = _PUMPING["pump_clearance_above_screen_m"]
    pump_submergence_min_m: float = _PUMPING["pump_submergence_min_m"]  # minimum water column above pump
    seasonal_allowance_m: float = _PUMPING["seasonal_allowance_m"]  # dry season decline allowance
    cooper_jacob_u_max: float = _PUMPING["cooper_jacob_u_max"]  # validity criterion for straight line fit
    cooper_jacob_min_r2: float = _PUMPING["cooper_jacob_min_r2"]  # the line has to explain the window
    # Where the pumped level has stopped growing (hydraulics.analysis
    # stabilised_tail): the readings of the last stabilised_span_log10 log
    # cycles move by less than a dipper reads, and their slope is under
    # stabilised_slope_ratio of the slope over the log cycle before them. A
    # Theis drawdown keeps its slope (a ratio near 1) and a recharge boundary
    # flattens it; a half is a choice between the two, not a standard, as is
    # judging the last half log cycle. A Cooper-Jacob window on such a tail
    # is not adopted.
    stabilised_span_log10: float = _PUMPING["stabilised_span_log10"]
    stabilised_slope_ratio: float = _PUMPING["stabilised_slope_ratio"]
    # Fits below this R squared are passed over when choosing which
    # transmissivity the yield rests on (recovery first, then Cooper-Jacob,
    # then Theis, which is a curve fit with no R squared and always eligible).
    min_fit_r_squared: float = _PUMPING["min_fit_r_squared"]
    # A test shorter than this is projected over several log cycles of time
    # to reach the design period, so its yield is flagged as indicative.
    min_constant_test_min: float = _PUMPING["min_constant_test_min"]  # pumped duration of a constant test
    min_step_length_min: float = _PUMPING["min_step_length_min"]  # length of each step in a step test
    # Casing storage. Early in a test the pump empties the water standing in
    # the casing before the aquifer supplies much of anything, and the
    # drawdown fits see the borehole emptying rather than the ground. Schafer
    # (1978) puts the end of that period at 0.6 (dc^2 - dp^2) / (Q/s) minutes
    # with the diameters in inches and Q/s in gpm/ft; the same rule in metres
    # and m3/h per m is the constant CASING_STORAGE_COEFFICIENT in
    # hydraulics.analysis. The diameters default to the design rules' casing
    # and a 1.25 inch riser; a sheet that records neither uses them.
    casing_diameter_in: float = _PUMPING["casing_diameter_in"]
    riser_diameter_in: float = _PUMPING["riser_diameter_in"]
    # A recovery line that does not pass near the origin is not a Theis
    # recovery line: theory has s' = 0 at t/t' = 1, and an intercept that is
    # a large fraction of the drawdown the recovery started from says the
    # residual drawdown is dominated by something the method does not model
    # (casing storage, a rising static level, a wrong pumping time). Such a
    # fit is reported, but not adopted for the yield.
    recovery_intercept_max_fraction: float = _PUMPING["recovery_intercept_max_fraction"]
    # A Theis fit whose storativity comes out above this is fitting the
    # casing, not the aquifer: no aquifer has a storage coefficient of 0.18,
    # and a single pumped well cannot resolve S anyway.
    max_plausible_storativity: float = _PUMPING["max_plausible_storativity"]
    # The spread of the adopted fit (hydraulics/spread.py): resamples in the
    # moving-block bootstrap of its residuals, and the seed of the generator
    # that draws them, fixed so a sheet gives the same band on every run and
    # in both apps. 400 resamples put the 10th and 90th percentiles within
    # about 0.015 in probability of where an endless run would. Measured on a
    # 24-reading test: 1.4 ms (Cooper-Jacob), 8 ms (Theis) and 0.76 s
    # (Papadopulos-Cooper) in the browser, 3.8 s for the last at a 4x CPU
    # slowdown, and 2.6 s for it in Python. The large-diameter fit is
    # adopted only where every other fit is disqualified.
    bootstrap_replicates: int = _PUMPING["bootstrap_replicates"]
    bootstrap_seed: int = _PUMPING["bootstrap_seed"]
    # The Bourdet derivative: neighbours at least this many log cycles apart
    # (Bourdet, Ayoub and Pirard's L; 0.2 smooths a dipper's centimetre
    # without flattening a regime half a cycle long), the
    # width in log cycles of the window its log-log slope is read over, and
    # the span a run of one slope class must cover to be named a regime.
    diagnostic_l_log10: float = _PUMPING["diagnostic_l_log10"]
    diagnostic_window_log10: float = _PUMPING["diagnostic_window_log10"]
    diagnostic_min_span_log10: float = _PUMPING["diagnostic_min_span_log10"]
    # The log-log slopes of the derivative that name a regime: about 1 for
    # casing storage, about 1/2 for linear flow along a fracture, about 0
    # for radial flow, and a clear fall for a recharge boundary or leakage.
    # These are judgements, set where a hydrogeologist reading the plot by
    # eye would draw them, and listed in the report so they can be argued.
    regime_unit_slope_min: float = _PUMPING["regime_unit_slope_min"]
    regime_unit_slope_max: float = _PUMPING["regime_unit_slope_max"]
    regime_half_slope_min: float = _PUMPING["regime_half_slope_min"]
    regime_half_slope_max: float = _PUMPING["regime_half_slope_max"]
    regime_flat_max: float = _PUMPING["regime_flat_max"]
    regime_falling_max: float = _PUMPING["regime_falling_max"]


# ---------------------------------------------------------------------------
# Borehole design rules (defaults follow common Sierra Leone practice and
# RWSN professional drilling guidance; adjust per client in config.yaml)
# ---------------------------------------------------------------------------

@dataclass
class DesignRules:
    borehole_diameter_in: float = _DESIGN["borehole_diameter_in"]  # drilled diameter
    casing_diameter_in: float = _DESIGN["casing_diameter_in"]  # uPVC production casing
    casing_material: str = _DESIGN["casing_material"]
    screen_slot_mm: float = _DESIGN["screen_slot_mm"]
    screen_length_default_m: float = _DESIGN["screen_length_default_m"]
    # Cement grout from the surface. This is the one number: the bundled
    # RWSN checklist's critical item ("sanitary seal in the top 6 m") and the
    # costing's cement quantity both follow it, so a supervisor applying the
    # toolkit's own checklist to the toolkit's own drawing no longer has to
    # answer No, and the BoQ no longer prices a 15 m seal the drawing did not
    # show.
    sanitary_seal_depth_m: float = _DESIGN["sanitary_seal_depth_m"]
    gravel_pack_above_top_screen_m: float = _DESIGN["gravel_pack_above_top_screen_m"]
    gravel_pack_material: str = _DESIGN["gravel_pack_material"]
    sump_length_m: float = _DESIGN["sump_length_m"]  # plain casing below the lowest screen
    stickup_m: float = _DESIGN["stickup_m"]  # casing stick-up above ground
    min_screen_below_swl_m: float = _DESIGN["min_screen_below_swl_m"]  # keep screens well below static level
    apron_note: str = _DESIGN["apron_note"]
    # A fracture zone the driller names with its depths ("fracture zone
    # 49-52 m") is screened with this much plain screen either side of it,
    # rather than the whole logged interval it was written on.
    fracture_zone_margin_m: float = _DESIGN["fracture_zone_margin_m"]


# ---------------------------------------------------------------------------
# The range of VES models (PLAN.md step 3.1)
#
# A section of its own rather than more VESConfig fields: the inversion cache
# key carries the whole VESConfig, and none of these changes what the
# inversion returns, so adding them there would have thrown away every saved
# inversion for nothing.
# ---------------------------------------------------------------------------

@dataclass
class VESRangeConfig:
    # The sampler's random numbers come from this seed, through a generator
    # both engines implement to the bit, so one sounding gives one range.
    seed: int = _RANGE["seed"]
    # Starting models drawn by Latin hypercube and polished by the same
    # Levenberg-Marquardt fit the inversion uses, beside the inversion's own.
    starts: int = _RANGE["starts"]
    # Metropolis-Hastings chains, each started from one of the best fits.
    chains: int = _RANGE["chains"]
    # Models kept over all the chains, after burn-in. Each costs one forward
    # call; bench/README.md says what that costs and why this number.
    samples: int = _RANGE["samples"]
    # Steps each chain takes and throws away first, while it finds its
    # step size; they cost a forward call each too.
    burn_in: int = _RANGE["burn_in"]
    # The error on every reading, in percent of the apparent resistivity,
    # before the measured disagreement at any MN overlap is added to it.
    # Provisional: the instrument's repeatability is about 1 percent; this
    # allows for electrode contact and small lateral changes as well.
    base_error_percent: float = _RANGE["base_error_percent"]
    # How many of the sampled models are drawn as the fan over the curve.
    fan_models: int = _RANGE["fan_models"]


# ---------------------------------------------------------------------------
# The chance of a working borehole (PLAN.md step 3.3, siting/odds.py)
# ---------------------------------------------------------------------------

@dataclass
class OddsConfig:
    # What "success" means: a yield of at least this at the dry-season water
    # level, the handpump design rate. 1 m3/h (0.28 L/s) is the minimum the
    # RWSN procurement guide accepts from a handpump borehole over its
    # pumping test (Adekile 2014, section 7.7.1), and the supervisors' guide
    # puts a handpump's demand at about 0.3 L/s (Adekile 2014). The priors in
    # success_prior.csv are worked out at this rate, so changing it moves
    # them too.
    success_yield_m3_per_h: float = _ODDS["success_yield_m3_per_h"]


# ---------------------------------------------------------------------------
# The ledger of predictions and outcomes (PLAN.md step 5.1, ledger.py)
# ---------------------------------------------------------------------------

@dataclass
class LedgerConfig:
    # A borehole is paired with the survey point nearest its logged position
    # when one lies this close. A handheld GPS reads to about 5 m, and a rig
    # is often set up some metres off the peg for access; a point farther
    # away than this is not taken to be the one drilled unless a person
    # says so, since a wrong pairing would mislead the calibration that
    # learns from the ledger. Provisional.
    pair_within_m: float = _LEDGER["pair_within_m"]
    # The calibration report (PLAN.md step 5.2, calibration.py) judges the
    # band and the odds only on at least this many boreholes drilled at
    # forecast points, and below it says there are too few and gives the
    # counts. With ten boreholes a calibrated P10 to P90 band holds between
    # six and ten of them at least nine times in ten, so fewer can hardly
    # tell a good band from a bad one. Provisional.
    min_boreholes: int = _LEDGER["min_boreholes"]
    # A hit rate is given for a geology unit, survey team or contractor only
    # on at least this many boreholes whose outcome is known; the plan's
    # contractor scorecards (step 6.3) never rank on fewer than five either.
    # Provisional.
    min_group: int = _LEDGER["min_group"]
    # The reliability diagram groups the forecast chances into this many
    # equal bins between 0 and 1: fifths, which a few dozen forecasts can
    # fill.
    reliability_bins: int = _LEDGER["reliability_bins"]
    # A calibration set (PLAN.md step 5.3, calibration_sets.py) fits a row
    # of the prior table, or a resistivity edge of a geology unit, only from
    # at least this many boreholes; below it the provisional value stays, as
    # a hit rate is given only on min_group. The fitted prior is a weighted
    # mean in which the provisional rate counts as its ten boreholes' worth,
    # so five boreholes move it a third of the way from the provisional
    # rate to theirs. Provisional.
    fit_min_boreholes: int = _LEDGER["fit_min_boreholes"]
    # The suitability score's weights are fitted only once at least this
    # many boreholes succeeded and this many failed, each with the score's
    # parts recorded: the fit ranks every pair of a success and a failure,
    # and with fewer of either a handful of holes decides it. Provisional.
    fit_weights_min_each: int = _LEDGER["fit_weights_min_each"]


# ---------------------------------------------------------------------------
# The cost as a distribution (PLAN.md step 3.4, costing/distribution.py)
# ---------------------------------------------------------------------------

@dataclass
class CostRangeConfig:
    # The draws come from this seed, through the generator the range of
    # models uses, which both engines implement to the bit, so one estimate
    # gives one distribution in either app.
    seed: int = _COSTS["seed"]
    # Boreholes (or programmes) sampled. bench/README.md says what that
    # costs and why this number.
    samples: int = _COSTS["samples"]


# ---------------------------------------------------------------------------
# Terrain analysis on an elevation model the operator supplies (PLAN.md step
# 4.1, mapping/elevation.py and the analysis built on it)
#
# A section of its own, and not in VESConfig: the inversion cache key carries
# the whole VESConfig, and none of these changes what an inversion returns.
# ---------------------------------------------------------------------------

@dataclass
class TerrainConfig:
    # Half the side of the square shown around the site. With the margin
    # below, the square analysed is about 0.96 million cells at 1
    # arc-second. Provisional until the terrain bench has timed it.
    analysis_radius_km: float = _TERRAIN["analysis_radius_km"]
    # How far beyond the square shown the analysis also reads, so that the
    # edge of the analysis does not bend the drainage lines. With no margin,
    # 5 to 13 percent of the unflagged stream cells in a 10 km window drained
    # the wrong area and up to 1,164 were missing; with 5 km, none were
    # missing or spurious. Provisional: it wants a hydrogeologist.
    analysis_buffer_km: float = _TERRAIN["analysis_buffer_km"]
    # One limit on the cells analysed, the margin included, in every
    # runtime, so that whether a window is refused does not depend on where
    # the engine ran. Lowered from 2,000,000 on 13 October 2026 by the rule
    # in bench/README.md: a whole press of "Analyse the terrain" in the
    # Streamlit app (the read, the analysis and the figures) took the server
    # to 679 to 729 MB on a first press at 2,000,000 cells and 747 to 779 MB
    # on a second, against Community Cloud's 690 MB, while at 1,500,000
    # every press measured stayed under it (535 to 669 MB). CPython analyses
    # the window at this cap in 2.0 s, under the rule's 6.0 s, and a press
    # in the browser takes 4.0 s with the engine worker. Provisional: it
    # wants the owner's confirmation.
    max_cells: int = _TERRAIN["max_cells"]
    # One limit on the blocks a read decodes, each a decode of its own: a
    # file cut into tiles of a cell or two costs a decode a cell, and two
    # million of them took over a minute and a gigabyte in CPython. A block
    # table longer than this is refused when the file is opened, so opening
    # one never builds a list of millions, and a window planned over more is
    # refused before a block is read. A Copernicus window at the cap meets a
    # few dozen blocks, and an .hgt set with missing tiles beside the sea
    # about 9,000 (each row of an .hgt is a strip of its own). Provisional,
    # as the cap on cells is.
    max_blocks: int = _TERRAIN["max_blocks"]
    # Ground at or below this, joined to the edge, is sea. Copernicus writes
    # sea and estuaries as exactly 0.0; 0.5 m would take in 26,352 land
    # cells around Freetown.
    sea_level_m: float = _TERRAIN["sea_level_m"]
    # A sea area that meets the land along a straight grid line this many
    # cells long is the 0 m fill of a joined or clipped file, not sea. Real
    # coasts on three Sierra Leone tiles reach 45 cells; a zero-filled gap
    # between tiles runs the window's full height. Provisional.
    sea_straight_edge_cells: int = _TERRAIN["sea_straight_edge_cells"]
    # Below any land surface: catches the -32767, -32768 and -3.4e38 that
    # elevation models write for a missing value.
    implausible_below_m: float = _TERRAIN["implausible_below_m"]
    implausible_above_m: float = _TERRAIN["implausible_above_m"]  # above any land surface
    # The upslope area at which a drainage line starts. Provisional: a value
    # within the 0.1 to 1 km2 commonly used for first-order channels, with
    # no source checked. It wants a hydrogeologist.
    drainage_area_km2: float = _TERRAIN["drainage_area_km2"]
    # Hollows raised by this much or more when filled are tinted as filled;
    # shallower filling shows through the cells routed across flats instead.
    # Provisional: it wants a hydrogeologist.
    fill_note_m: float = _TERRAIN["fill_note_m"]
    # A slope's tangent, about 0.06 degrees: the least slope the wetness
    # index divides by, and the slope below which curvature is not drawn.
    flat_tan_slope: float = _TERRAIN["flat_tan_slope"]
    # Curvature is worked out over about 3 cells at 1 arc-second, where the
    # noise (about 1.7e-4 per metre) sits well under signals near 6e-4 per
    # metre.
    curvature_spacing_m: float = _TERRAIN["curvature_spacing_m"]
    # The suns of the composite hillshade: gdaldem -multidirectional exactly.
    hillshade_azimuths_deg: tuple = tuple(_TERRAIN["hillshade_azimuths_deg"])
    # The suns of the one-direction panels, and of the layers lineament
    # work (PLAN.md step 4.2) starts from: the same strikes, all lit from
    # above, so that every strike is within 22.5 degrees of across one panel.
    hillshade_panel_azimuths_deg: tuple = tuple(_TERRAIN["hillshade_panel_azimuths_deg"])
    # GDAL's default height of the sun; lineament work may want a lower one.
    hillshade_altitude_deg: float = _TERRAIN["hillshade_altitude_deg"]
    # No vertical exaggeration, so that relief on the plains is drawn as it is.
    hillshade_z_factor: float = _TERRAIN["hillshade_z_factor"]
    # Lineament candidates (PLAN.md step 4.2, groundwater.mapping.lineaments).
    # Every value here is provisional and wants a geologist; each was chosen
    # on the Copernicus tile N08 W012 and on random terrain with straight
    # valleys planted in it, as the module says.
    # The heights are smoothed at about this scale before they are shaded:
    # 9 binomial passes at 1 arc-second. Unsmoothed, the canopy's texture
    # broke every edge into pieces of fewer than ten cells.
    lineament_smoothing_m: float = _TERRAIN["lineament_smoothing_m"]
    # The side of the square around each cell that its edge strength is
    # measured against, so that a valley across the plains counts as well as
    # one among the hills, where a single threshold kept only the hills.
    lineament_contrast_km: float = _TERRAIN["lineament_contrast_km"]
    # The share of the centreline cells of the square shown kept by their
    # strength against their surroundings.
    lineament_share: float = _TERRAIN["lineament_share"]
    # Ground that bends by less than this across a line is not a line, however
    # it compares with its surroundings: 0.1 per km is half a metre over 100 m
    # either side. On the tile 99 in 100 points along the candidates bent by
    # 0.49 per km or more and half the land by 0.83, while a plane rising 3 m
    # a cell gives 1e-6; without a floor, comparing a cell with its
    # surroundings drew ridges on a plane.
    lineament_min_curvature_per_km: float = _TERRAIN["lineament_min_curvature_per_km"]
    # Two neighbouring centreline cells belong to one line when their
    # directions differ by no more than this.
    lineament_turn_deg: float = _TERRAIN["lineament_turn_deg"]
    # A line is cut into straight pieces until no cell of a piece lies
    # further than this from it: three cells at 1 arc-second.
    lineament_straight_m: float = _TERRAIN["lineament_straight_m"]
    # The shortest straight piece kept before pieces are linked.
    lineament_piece_m: float = _TERRAIN["lineament_piece_m"]
    # The shortest candidate shown: about 20 cells at 1 arc-second, longer
    # than the texture of the model itself.
    lineament_min_length_m: float = _TERRAIN["lineament_min_length_m"]
    # Two pieces of one kind are linked into one candidate when their
    # directions differ by no more than this, neither end of the second lies
    # further than lineament_link_offset_m from the first's line, and the
    # gap between them along it is no more than lineament_link_gap_m.
    lineament_link_angle_deg: float = _TERRAIN["lineament_link_angle_deg"]
    lineament_link_offset_m: float = _TERRAIN["lineament_link_offset_m"]
    lineament_link_gap_m: float = _TERRAIN["lineament_link_gap_m"]
    # The survey plan (PLAN.md step 4.3), laid inside the service radius of
    # waterpoints.SERVICE_RADIUS_M. Every value is a provisional choice for a
    # hydrogeologist to confirm. The most profiling lines a plan lays, one
    # across each of the candidates nearest the site: two lines and their six
    # soundings are about a day for a crew with one resistivity meter.
    survey_lines: int = _TERRAIN["survey_lines"]
    # How long a line is, when the service radius leaves room for it: 200 m
    # either side of the candidate, so the profile reads the ground beside
    # the zone as well as the zone.
    survey_line_m: float = _TERRAIN["survey_line_m"]
    # The spacing of the profile's stations: a third of a cell at 1
    # arc-second, so a zone a cell wide is read at three stations.
    survey_station_m: float = _TERRAIN["survey_station_m"]
    # The flank soundings' distance either side of the crossing, along the
    # line: the candidate is placed from the terrain to within a cell or two
    # and the smoothing, about 65 m, so a zone that lies beside the crossing
    # still falls under a sounding.
    survey_flank_m: float = _TERRAIN["survey_flank_m"]
    # The furthest a sounding is moved along its line to clear a separation
    # ring: a sounding on a stream that crosses its line at right angles
    # moves just clear of the stream's 20 m. Under half of survey_flank_m,
    # so that soundings keep their order along the line.
    survey_move_m: float = _TERRAIN["survey_move_m"]
    # A line counts as crossing another candidate at right angles when the
    # two candidates' strikes differ by no more than this: at 20 degrees the
    # line runs across the second zone for about 6% more than its width.
    survey_cross_within_deg: float = _TERRAIN["survey_cross_within_deg"]
    # The depth each sounding is planned to see to, by the
    # depth-of-investigation rule: past the 35 m at which
    # success_evidence.yaml's deep weathered band begins, with 25 m more for
    # the fresh rock beneath to show on the curve.
    survey_target_depth_m: float = _TERRAIN["survey_target_depth_m"]


# ---------------------------------------------------------------------------
# Top level configuration
# ---------------------------------------------------------------------------

def _coerce_like(current, value, key: str):
    """``value`` as the type of the field it overrides.

    YAML hands back whatever was typed: a quoted "2.0" is a string, and a
    string safety factor multiplied a yield into a TypeError three pages
    later. Numbers are coerced; anything else is passed through as typed.
    """
    if isinstance(current, bool) or value is None or isinstance(value, bool):
        return value
    if isinstance(current, (int, float)) and isinstance(value, (int, float, str)):
        try:
            number = float(value)
        except ValueError as exc:
            raise ValueError(f"config: '{key}' must be a number, not {value!r}") from exc
        return int(number) if isinstance(current, int) and number == int(number) else number
    if isinstance(current, str) and not isinstance(value, str):
        return str(value)
    return value


@dataclass
class Config:
    style: HouseStyle = field(default_factory=HouseStyle)
    ves: VESConfig = field(default_factory=VESConfig)
    pumping: PumpingConfig = field(default_factory=PumpingConfig)
    design: DesignRules = field(default_factory=DesignRules)
    ves_range: VESRangeConfig = field(default_factory=VESRangeConfig)
    odds: OddsConfig = field(default_factory=OddsConfig)
    ledger: LedgerConfig = field(default_factory=LedgerConfig)
    cost_range: CostRangeConfig = field(default_factory=CostRangeConfig)
    terrain: TerrainConfig = field(default_factory=TerrainConfig)
    # The calibration set in force (PLAN.md step 5.3, calibration_sets.py),
    # as clean_set reads it, or None for the toolkit's provisional default.
    # Put one in force with calibration_sets.apply_set, which refuses a set
    # no named person has adopted, or name its file in config.yaml as
    # ``calibration: calibration.yaml``, beside the config file.
    calibration: dict | None = None

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        """Load configuration, overlaying a YAML file if provided.

        A top-level ``calibration`` names the calibration set to put in force,
        a file found beside the config file unless the path is absolute."""
        cfg = cls()
        if path is None:
            return cfg
        path = Path(path)
        if not path.exists():
            return cfg
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        for section_name, section in (
            ("style", cfg.style),
            ("ves", cfg.ves),
            ("pumping", cfg.pumping),
            ("design", cfg.design),
            ("ves_range", cfg.ves_range),
            ("odds", cfg.odds),
            ("ledger", cfg.ledger),
            ("cost_range", cfg.cost_range),
            ("terrain", cfg.terrain),
        ):
            overrides = data.get(section_name, {}) or {}
            for key, value in overrides.items():
                if not hasattr(section, key):
                    # a mis-keyed override (safety_factor under design:
                    # instead of pumping:) used to vanish without a word
                    warnings.warn(
                        f"{path.name}: unknown key '{key}' under '{section_name}' "
                        "is ignored; check the spelling and the section",
                        stacklevel=2,
                    )
                    continue
                setattr(section, key, _coerce_like(getattr(section, key), value, key))
        for key in data:
            if key not in ("style", "ves", "pumping", "design", "ves_range", "odds",
                           "ledger", "cost_range", "terrain", "calibration"):
                warnings.warn(
                    f"{path.name}: unknown section '{key}' is ignored "
                    "(expected style, ves, pumping, design, ves_range, odds, "
                    "ledger, cost_range, terrain or calibration)",
                    stacklevel=2,
                )
        named = data.get("calibration")
        if named:
            from .calibration_sets import apply_set, clean_set, read_set

            if isinstance(named, dict):
                # the set itself, as dump() writes a config with one in force
                cfg = apply_set(cfg, clean_set(named))
            else:
                where = Path(str(named))
                where = where if where.is_absolute() else path.parent / where
                cfg = apply_set(cfg, read_set(where.read_text(encoding="utf-8")))
        return cfg

    def dump(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(asdict(self), fh, sort_keys=False)


DEFAULT_CONFIG = Config()
