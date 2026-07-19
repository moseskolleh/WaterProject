"""Water quality assessment against WHO and Sierra Leone standards."""

from .standards import load_standards, StandardEntry
from .assess import assess_sample, WaterQualityAssessment, ParameterAssessment
from .ionic import ionic_balance, IonicBalanceResult
from .corrosivity import assess_corrosivity, CorrosivityAssessment
from .indices import (
    compute_wqi,
    assess_health_risk,
    WaterQualityIndex,
    HealthRiskAssessment,
)
from .diagrams import plot_piper, plot_stiff

__all__ = [
    "load_standards",
    "StandardEntry",
    "assess_sample",
    "WaterQualityAssessment",
    "ParameterAssessment",
    "ionic_balance",
    "IonicBalanceResult",
    "assess_corrosivity",
    "CorrosivityAssessment",
    "compute_wqi",
    "assess_health_risk",
    "WaterQualityIndex",
    "HealthRiskAssessment",
    "plot_piper",
    "plot_stiff",
]
