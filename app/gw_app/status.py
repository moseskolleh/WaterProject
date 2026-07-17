"""Project status board and cross-tab consistency checks."""

from __future__ import annotations

import streamlit as st

from groundwater.registry import depth_prior_note
from groundwater.supervision import evaluate_checklist

from .common import (
    cached_checklists,
    checklist_responses,
    site_from_state,
    top_interpretation,
    workdir,
)


def _depths_differ(a: float, b: float) -> bool:
    """More than 5 m and 10 percent apart - a real disagreement, not
    rounding to the nearest drill pipe."""
    return abs(a - b) > max(5.0, 0.1 * max(a, b))


def consistency_warnings() -> list[str]:
    """Cross-tab disagreements: the sheets pass their own checks but
    the project contradicts itself (sited 45 m, costed 60 m, ...)."""
    warnings: list[str] = []
    interp = top_interpretation()
    design = st.session_state.get("borehole_design")
    estimate = st.session_state.get("cost_estimate")
    pumping = st.session_state.get("pump_analysis")

    if (
        interp is not None
        and design is not None
        and _depths_differ(interp.max_drilling_depth_m, design.total_depth_m)
    ):
        warnings.append(
            f"The siting result recommends drilling to "
            f"{interp.max_drilling_depth_m:g} m but the borehole design "
            f"is {design.total_depth_m:g} m deep - check which is current."
        )
    if estimate is not None:
        costed = float(estimate.inputs.total_depth_m)
        if design is not None and _depths_differ(costed, design.total_depth_m):
            warnings.append(
                f"The cost estimate prices a {costed:g} m borehole but "
                f"the design is {design.total_depth_m:g} m - re-run the "
                "estimate with 'Use the design' switched on."
            )
        elif (
            design is None
            and interp is not None
            and _depths_differ(costed, interp.max_drilling_depth_m)
        ):
            warnings.append(
                f"The cost estimate prices a {costed:g} m borehole but "
                f"the siting result recommends "
                f"{interp.max_drilling_depth_m:g} m - update the costing "
                "depth."
            )
    if pumping is not None and design is not None:
        yr = pumping.yield_recommendation
        pump_depth = getattr(yr, "pump_installation_depth_m", None) if yr else None
        if pump_depth and pump_depth > design.total_depth_m:
            warnings.append(
                f"The recommended pump depth ({pump_depth:g} m) is below "
                f"the designed borehole depth ({design.total_depth_m:g} m)."
            )

    # the registry's district record as a prior on the planned depth
    registry_rows = st.session_state.get("registry_records") or []
    planned = None
    if design is not None:
        planned = float(design.total_depth_m)
    elif estimate is not None:
        planned = float(estimate.inputs.total_depth_m)
    elif interp is not None:
        planned = float(interp.max_drilling_depth_m)
    district = st.session_state.get("meta_district", "")
    if registry_rows and planned and district:
        note = depth_prior_note(registry_rows, district, planned)
        if note:
            warnings.append(note)
    return warnings


def render_board() -> None:
    """One glance: what the project has and what is still missing."""
    site = site_from_state()
    interp = top_interpretation()
    estimate = st.session_state.get("cost_estimate")
    design = st.session_state.get("borehole_design")
    pumping = st.session_state.get("pump_analysis")
    quality = st.session_state.get("wq_assessment")
    items = cached_checklists()
    assessment = evaluate_checklist(items, checklist_responses(items))
    reports = sorted(workdir().glob("*.docx"))

    row1 = st.columns(4)
    row1[0].metric("Site", site.community or "not set",
                   help="Community from the sidebar site details.")
    row1[1].metric(
        "Siting (VES)",
        f"{interp.max_drilling_depth_m:g} m" if interp is not None else "not yet",
        help="Recommended drilling depth from the best ranked sounding.",
    )
    row1[2].metric(
        "Cost estimate",
        f"${estimate.price_usd:,.0f}" if estimate is not None else "not yet",
        help="Contract price from the Costing tab.",
    )
    row1[3].metric(
        "Supervision",
        f"{assessment.answered}/{assessment.total}",
        help="Checklist items answered.",
    )

    if pumping is not None:
        yr = pumping.yield_recommendation
        safe_yield = getattr(yr, "safe_yield_m3_per_h", None) if yr else None
        pump_text = (
            f"{safe_yield:.1f} m3/h" if safe_yield else "pending"
        )
    else:
        pump_text = "not yet"
    if quality is not None:
        if quality.health_exceedances:
            quality_text = f"{len(quality.health_exceedances)} health issue(s)"
        elif quality.aesthetic_exceedances:
            quality_text = "aesthetic only"
        else:
            quality_text = "passes"
    else:
        quality_text = "not yet"

    row2 = st.columns(4)
    row2[0].metric(
        "Design",
        f"{design.total_depth_m:g} m" if design is not None else "not yet",
        help="As-built design from the drilling log.",
    )
    row2[1].metric("Safe yield", pump_text,
                   help="From the pumping test analysis.")
    row2[2].metric("Water quality", quality_text,
                   help="WHO/national verdict for the lab sample.")
    row2[3].metric("Reports built", len(reports),
                   help="Report documents produced this session.")

    for warning in consistency_warnings():
        st.warning(warning, icon="⚠️")
