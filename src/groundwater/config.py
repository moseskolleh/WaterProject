"""Toolkit configuration: house style, analysis defaults and design rules.

All values can be overridden per project from a ``config.yaml`` placed
in the project folder, so client specific standards do not require code
changes.
"""

from __future__ import annotations

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
                if hasattr(section, key):
                    setattr(section, key, value)
        return cfg

    def dump(self, path: str | Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(asdict(self), fh, sort_keys=False)


DEFAULT_CONFIG = Config()
