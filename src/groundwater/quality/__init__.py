"""Water quality assessment against WHO and Sierra Leone standards."""

from .standards import (
    PROVISIONAL_NATIONAL_NOTE,
    StandardEntry,
    load_standards,
    provisional_national_parameters,
)
from .assess import (
    ESSENTIAL_HEALTH_PARAMETERS,
    STATUS_LABELS,
    SUITABILITY_PHRASE,
    SUITABILITY_SENTENCE,
    VERDICT_LONG,
    VERDICT_ORDER,
    VERDICT_SHORT,
    ParameterAssessment,
    WaterQualityAssessment,
    assess_sample,
)
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
    "ESSENTIAL_HEALTH_PARAMETERS",
    "STATUS_LABELS",
    "SUITABILITY_PHRASE",
    "SUITABILITY_SENTENCE",
    "VERDICT_LONG",
    "VERDICT_ORDER",
    "VERDICT_SHORT",
    "load_standards",
    "provisional_national_parameters",
    "PROVISIONAL_NATIONAL_NOTE",
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
