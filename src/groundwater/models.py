"""Core data structures shared across the toolkit.

Every parser returns one of these objects and every analysis module
consumes them, so the raw-data-to-report chain stays traceable: each
object keeps a ``source`` path and parsers attach ``flags`` describing
anything that needs analyst attention (missing discharge, inconsistent
metadata, negative drawdown and so on).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .geo import UTMCoordinate, utm_to_geographic


# ---------------------------------------------------------------------------
# Flags raised during parsing and checking
# ---------------------------------------------------------------------------

@dataclass
class DataFlag:
    """A data quality or consistency issue that needs analyst review."""

    level: str  # "info" | "warning" | "error"
    code: str  # short machine readable code, e.g. "missing_discharge"
    message: str  # human readable explanation
    context: str = ""  # e.g. "VES 2", "step 3"

    def __str__(self) -> str:
        prefix = f"[{self.level.upper()}] {self.code}"
        ctx = f" ({self.context})" if self.context else ""
        return f"{prefix}{ctx}: {self.message}"


# ---------------------------------------------------------------------------
# Site metadata
# ---------------------------------------------------------------------------

@dataclass
class SiteMetadata:
    """Header block information shared by all field sheets."""

    client: str = ""
    project: str = ""
    community: str = ""
    chiefdom: str = ""
    district: str = ""
    country: str = "Sierra Leone"
    project_ref: str = ""
    easting: Optional[float] = None
    northing: Optional[float] = None
    utm_zone: Optional[int] = None
    elevation_m: Optional[float] = None
    date: str = ""
    supervisor: str = ""
    contractor: str = ""
    source: str = ""

    @property
    def utm(self) -> Optional[UTMCoordinate]:
        if self.easting is None or self.northing is None:
            return None
        zone = self.utm_zone or 28
        return UTMCoordinate(self.easting, self.northing, zone)

    @property
    def latlon(self) -> Optional[tuple[float, float]]:
        utm = self.utm
        if utm is None:
            return None
        return utm_to_geographic(utm.easting, utm.northing, utm.zone)

    def merged_with(self, other: "SiteMetadata") -> "SiteMetadata":
        """Fill blank fields from another metadata record.

        A field is "blank" only when it is None or an empty string. A genuine
        numeric zero - a sea-level elevation, or a zero UTM ordinate - counts
        as present and is never overwritten, so merging two records does not
        lose a real 0.0 datum.
        """
        merged = SiteMetadata(**self.__dict__)
        for key, value in other.__dict__.items():
            current = getattr(merged, key)
            if (current is None or current == "") and value not in (None, ""):
                setattr(merged, key, value)
        return merged


# ---------------------------------------------------------------------------
# VES
# ---------------------------------------------------------------------------

@dataclass
class VESSounding:
    """A single vertical electrical sounding.

    ``mn`` stores the full potential electrode spacing MN (not MN/2),
    matching the field sheets. Duplicate ``ab2`` values with different
    ``mn`` mark Schlumberger segment changes and are preserved.
    """

    site: SiteMetadata
    sounding_id: str
    ab2: np.ndarray  # AB/2 in metres
    mn: np.ndarray  # full MN spacing in metres
    rho_app: np.ndarray  # apparent resistivity, ohm-m
    array_type: str = "schlumberger"
    instrument: str = ""
    flags: list[DataFlag] = field(default_factory=list)
    source: str = ""

    def __post_init__(self) -> None:
        self.ab2 = np.asarray(self.ab2, dtype=float)
        self.mn = np.asarray(self.mn, dtype=float)
        self.rho_app = np.asarray(self.rho_app, dtype=float)

    @property
    def n_readings(self) -> int:
        return len(self.ab2)

    @property
    def label(self) -> str:
        return self.sounding_id or "VES"

    def segments(self) -> list[np.ndarray]:
        """Indices of readings grouped by MN spacing, in field order.

        A new segment starts at each change of MN spacing. A blank/NaN MN is
        treated as a continuation of the current segment (its spacing is
        unknown, carried forward from the last real value) rather than
        starting a new one, so a single missing MN cell does not inject a
        spurious one-point segment and an absent MN column does not split
        every reading into its own segment.
        """
        out: list[list[int]] = []
        last_mn: float | None = None
        for idx, mn in enumerate(self.mn):
            is_nan = mn != mn  # NaN is the only value not equal to itself
            new_segment = not out or (
                not is_nan and last_mn is not None and mn != last_mn
            )
            if new_segment:
                out.append([])
            out[-1].append(idx)
            if not is_nan:
                last_mn = mn
        return [np.array(g, dtype=int) for g in out]


@dataclass
class LayeredModel:
    """A 1D layered earth model (the IPI2Win style result).

    ``thicknesses`` has one entry fewer than ``resistivities``; the
    last layer is the half-space (its thickness is infinite).
    """

    resistivities: np.ndarray  # ohm-m, length n
    thicknesses: np.ndarray  # m, length n-1
    fit_error_percent: Optional[float] = None  # RMS misfit, like IPI2Win ERR
    method: str = ""  # "ipi2win-import" | "damped-lsq" | ...
    sounding_id: str = ""

    def __post_init__(self) -> None:
        self.resistivities = np.asarray(self.resistivities, dtype=float)
        self.thicknesses = np.asarray(self.thicknesses, dtype=float)
        if len(self.thicknesses) != len(self.resistivities) - 1:
            raise ValueError(
                "thicknesses must have exactly one entry fewer than resistivities"
            )

    @property
    def n_layers(self) -> int:
        return len(self.resistivities)

    @property
    def depths_top(self) -> np.ndarray:
        """Depth to the top of each layer (first entry 0)."""
        return np.concatenate([[0.0], np.cumsum(self.thicknesses)])

    @property
    def depths_bottom(self) -> np.ndarray:
        """Depth to the bottom of each layer (last entry inf)."""
        return np.concatenate([np.cumsum(self.thicknesses), [np.inf]])

    def as_table(self) -> list[dict]:
        """Rows in the IPI2Win layout: N, rho, h, z (depth to top)."""
        rows = []
        tops = self.depths_top
        for i in range(self.n_layers):
            h = self.thicknesses[i] if i < len(self.thicknesses) else None
            z = "0/0" if i == 0 else tops[i]
            rows.append(
                {
                    "N": i + 1,
                    "rho_ohm_m": float(self.resistivities[i]),
                    "h_m": None if h is None else float(h),
                    "z_m": z,
                }
            )
        return rows


# ---------------------------------------------------------------------------
# Pumping test
# ---------------------------------------------------------------------------

@dataclass
class PumpingStep:
    """One step of a step-drawdown or constant discharge test."""

    step_number: int
    time_min: np.ndarray  # minutes since the start of the whole test
    water_level_m: np.ndarray  # depth to water below datum
    discharge_m3_per_h: Optional[float] = None  # None when missing on sheet
    label: str = ""

    def __post_init__(self) -> None:
        self.time_min = np.asarray(self.time_min, dtype=float)
        self.water_level_m = np.asarray(self.water_level_m, dtype=float)


@dataclass
class PumpingTest:
    """A pumping test record built from the field sheet.

    The field sheets record an incremental "drawdown" column (change
    between successive readings). Parsers keep only time and water
    level; true drawdown below static is always recomputed here.
    """

    site: SiteMetadata
    borehole_ref: str = ""
    test_type: str = "step"  # "step" | "constant" | "constant+recovery"
    static_water_level_m: Optional[float] = None
    borehole_depth_m: Optional[float] = None
    pump_setting_m: Optional[float] = None
    step_length_min: Optional[float] = None
    steps: list[PumpingStep] = field(default_factory=list)
    recovery_time_min: Optional[np.ndarray] = None  # minutes since pump stop
    recovery_level_m: Optional[np.ndarray] = None
    pumping_duration_min: Optional[float] = None  # total pumping before recovery
    flags: list[DataFlag] = field(default_factory=list)
    source: str = ""

    @property
    def has_discharge(self) -> bool:
        return any(s.discharge_m3_per_h is not None for s in self.steps)

    def drawdown(self, step: PumpingStep) -> np.ndarray:
        """True drawdown below static water level, metres."""
        if self.static_water_level_m is None:
            raise ValueError("static water level is required to compute drawdown")
        return step.water_level_m - self.static_water_level_m

    def all_times_levels(self) -> tuple[np.ndarray, np.ndarray]:
        """Concatenated pumping phase time series."""
        t = np.concatenate([s.time_min for s in self.steps]) if self.steps else np.array([])
        wl = (
            np.concatenate([s.water_level_m for s in self.steps])
            if self.steps
            else np.array([])
        )
        order = np.argsort(t, kind="stable")
        return t[order], wl[order]

    def residual_drawdown(self) -> Optional[np.ndarray]:
        if self.recovery_level_m is None or self.static_water_level_m is None:
            return None
        return self.recovery_level_m - self.static_water_level_m


# ---------------------------------------------------------------------------
# Drilling log
# ---------------------------------------------------------------------------

@dataclass
class LithologyInterval:
    top_m: float
    bottom_m: float
    description: str = ""
    from_time: str = ""
    to_time: str = ""
    penetration_rate_m_per_min: Optional[float] = None
    bit_diameter_in: Optional[float] = None

    @property
    def thickness_m(self) -> float:
        return self.bottom_m - self.top_m


@dataclass
class DrillingLog:
    site: SiteMetadata
    borehole_ref: str = ""
    total_depth_m: Optional[float] = None
    drilling_method: str = ""
    intervals: list[LithologyInterval] = field(default_factory=list)
    water_strikes_m: list[float] = field(default_factory=list)
    grouting_depth_m: Optional[float] = None
    start_date: str = ""
    completion_date: str = ""
    status: str = ""  # e.g. "Successful"
    flags: list[DataFlag] = field(default_factory=list)
    source: str = ""


# ---------------------------------------------------------------------------
# Water quality
# ---------------------------------------------------------------------------

@dataclass
class WaterQualityResult:
    parameter: str
    value: Optional[float]
    unit: str = ""
    detection_limit: Optional[float] = None
    below_detection: bool = False
    method: str = ""


@dataclass
class WaterQualitySample:
    site: SiteMetadata
    sample_id: str = ""
    borehole_ref: str = ""
    sample_date: str = ""
    laboratory: str = ""
    results: list[WaterQualityResult] = field(default_factory=list)
    flags: list[DataFlag] = field(default_factory=list)
    source: str = ""

    def get(self, parameter: str) -> Optional[WaterQualityResult]:
        key = parameter.strip().lower()
        for r in self.results:
            if r.parameter.strip().lower() == key:
                return r
        return None
