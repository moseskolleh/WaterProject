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


# ---------------------------------------------------------------------------
# House style (figures and reports)
# ---------------------------------------------------------------------------

@dataclass
class HouseStyle:
    accent_color: str = "#1F5C8B"  # muted blue used for headings and curves
    secondary_color: str = "#C15A2A"  # burnt orange for model/overlay lines
    neutral_color: str = "#4D4D4D"
    background: str = "#FFFFFF"
    font_name: str = "Calibri"
    base_font_size_pt: float = 11.0
    figure_dpi: int = 200
    figure_width_in: float = 6.3  # fits A4 with 2.5 cm margins
    organisation: str = ""
    organisation_details: str = ""
    logo_path: str = ""  # optional logo for report headers


# ---------------------------------------------------------------------------
# VES analysis defaults
# ---------------------------------------------------------------------------

@dataclass
class VESConfig:
    max_layers: int = 4
    min_layers: int = 2
    target_fit_percent: float = 10.0  # accept the simplest model under this
    # ...but only while no richer model more than halves its misfit. A
    # two-layer model can sit just under the target while a three-layer one
    # fits the same curve an order of magnitude better and puts basement at
    # 65 m instead of 4 m - the difference between drilling into the aquifer
    # and stopping in the regolith.
    parsimony_max_error_ratio: float = 2.0
    damping: float = 0.02
    max_iterations: int = 60
    # hydrogeological interpretation thresholds (ohm-m), crystalline basement
    fresh_basement_min_rho: float = 3000.0
    fractured_zone_rho: tuple = (20.0, 800.0)  # likely water bearing when saturated
    clay_max_rho: float = 20.0
    laterite_min_rho: float = 800.0  # dry laterite / duricrust near surface
    max_drilling_margin_m: float = 10.0  # added below deepest target zone
    round_drilling_depth_to_m: float = 5.0


# ---------------------------------------------------------------------------
# Pumping test defaults
# ---------------------------------------------------------------------------

@dataclass
class PumpingConfig:
    safety_factor: float = 1.5  # applied to long term yield, stated in reports
    design_period_days: float = 365.0  # projection horizon for safe yield
    available_drawdown_fraction: float = 0.7  # usable share of available drawdown
    pump_clearance_above_screen_m: float = 1.0
    pump_submergence_min_m: float = 3.0  # minimum water column above pump
    seasonal_allowance_m: float = 2.0  # dry season decline allowance
    cooper_jacob_u_max: float = 0.05  # validity criterion for straight line fit
    # A late-time slope below what a dipper can resolve (2 cm per log cycle)
    # is reading noise or a level that has stabilised, and 2.303 Q / (4 pi
    # slope) turns it into a transmissivity of thousands of m2/day that no
    # basement borehole has. The fit is refused rather than reported.
    cooper_jacob_min_slope_m: float = 0.02  # m per log cycle
    cooper_jacob_min_r2: float = 0.8  # the line has to explain the window
    # Fits below this R squared are passed over when choosing which
    # transmissivity the yield rests on (recovery first, then Cooper-Jacob,
    # then Theis, which is a curve fit with no R squared and always eligible).
    min_fit_r_squared: float = 0.8
    # A test shorter than this is projected over several log cycles of time
    # to reach the design period, so its yield is flagged as indicative.
    min_constant_test_min: float = 240.0  # pumped duration of a constant test
    min_step_length_min: float = 60.0  # length of each step in a step test


# ---------------------------------------------------------------------------
# Borehole design rules (defaults follow common Sierra Leone practice and
# RWSN professional drilling guidance; adjust per client in config.yaml)
# ---------------------------------------------------------------------------

@dataclass
class DesignRules:
    borehole_diameter_in: float = 6.5  # drilled diameter
    casing_diameter_in: float = 5.0  # uPVC production casing
    casing_material: str = "uPVC"
    screen_slot_mm: float = 0.75
    screen_length_default_m: float = 9.0
    sanitary_seal_depth_m: float = 3.0  # cement grout from surface
    grout_min_depth_m: float = 15.0  # backfill/seal above gravel pack
    gravel_pack_above_top_screen_m: float = 2.0
    gravel_pack_material: str = "well sorted siliceous gravel, 2-4 mm"
    sump_length_m: float = 2.0  # plain casing below the lowest screen
    stickup_m: float = 0.5  # casing stick-up above ground
    min_screen_below_swl_m: float = 5.0  # keep screens well below static level
    apron_note: str = "concrete apron with drainage channel and soakaway"


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
    def load(cls, path: str | Path | None = None) -> "Config":
        """Load configuration, overlaying a YAML file if provided."""
        cfg = cls()
        if path is None:
            return cfg
        path = Path(path)
        if not path.exists():
            return cfg
        with open(path, "r", encoding="utf-8") as fh:
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
