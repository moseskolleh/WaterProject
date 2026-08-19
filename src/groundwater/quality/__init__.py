"""Water quality assessment against WHO and Sierra Leone standards."""

from .._lazy import lazy_exports
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

# Deferred: these pull matplotlib, openpyxl or python-docx, which the
# analysis half of this package does not need. See groundwater._lazy.
_LAZY = {
    "plot_piper": ".diagrams",
    "plot_stiff": ".diagrams",
}

__getattr__, __dir__ = lazy_exports(__name__, _LAZY)
