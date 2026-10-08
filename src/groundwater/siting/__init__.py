"""Drill-target siting decision support (prototype).

Turns the hydrogeological interpretation the toolkit already computes into
a single, ranked "where should I drill?" answer: a transparent 0-100
suitability score per candidate VES point, a grade, a plain-language
rationale, and a drill-target map; and, beside it, the chance that a
borehole at each point yields enough for a handpump (``odds``, PLAN.md
step 3.3), worked out from a cited prior and the survey's evidence.

The score is a transparent weighted scorecard over features that a siting
hydrogeologist already weighs in crystalline basement terrain, so a water
manager can see *why* a point is preferred, not just that it is. It is a
starting point: as a programme accumulates its own (VES features ->
drilling outcome) pairs, the weights can be replaced by a fitted model.
"""

from .odds import (
    SuccessOdds,
    odds_basis_text,
    odds_header,
    odds_headline,
    odds_point_text,
    odds_rows,
    odds_short,
    odds_table_caption,
    odds_text,
    success_odds,
    survey_odds,
)
from .suitability import (
    SitingSuitability,
    SuitabilityComponents,
    assess_siting,
    ranking_tie,
    suitability_map_points,
    suitability_verdict,
    tied_leaders,
)

__all__ = [
    "SitingSuitability",
    "SuccessOdds",
    "SuitabilityComponents",
    "assess_siting",
    "odds_basis_text",
    "odds_header",
    "odds_headline",
    "odds_point_text",
    "odds_rows",
    "odds_short",
    "odds_table_caption",
    "odds_text",
    "ranking_tie",
    "success_odds",
    "suitability_map_points",
    "suitability_verdict",
    "survey_odds",
    "tied_leaders",
]
