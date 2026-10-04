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
    # A late-time slope below what a dipper can resolve (2 cm per log cycle)
    # is reading noise or a level that has stabilised, and 2.303 Q / (4 pi
    # slope) turns it into a transmissivity of thousands of m2/day that no
    # basement borehole has. The fit is refused rather than reported.
    cooper_jacob_min_slope_m: float = _PUMPING["cooper_jacob_min_slope_m"]  # m per log cycle
    cooper_jacob_min_r2: float = _PUMPING["cooper_jacob_min_r2"]  # the line has to explain the window
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
    # (Bourdet, Ayoub and Pirard 1989 smooth with L of 0.1 to 0.5), the
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

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        """Load configuration, overlaying a YAML file if provided."""
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
            if key not in ("style", "ves", "pumping", "design"):
                warnings.warn(
                    f"{path.name}: unknown section '{key}' is ignored "
                    "(expected style, ves, pumping or design)",
                    stacklevel=2,
                )
        return cfg

    def dump(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(asdict(self), fh, sort_keys=False)


DEFAULT_CONFIG = Config()
