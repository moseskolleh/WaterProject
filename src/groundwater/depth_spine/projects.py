"""Load the bundled sample projects through the normal ingestion chain.

Nothing here is fixture data: the workbooks in ``examples/data`` are parsed by
the same readers the app uses, so the workspace shows what the toolkit actually
computes for Dr. Timbo, Rokel and Kuntolo - including the flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import Config
from ..hydraulics import analyse_pumping_test
from ..hydraulics.analysis import attach_yield_envelope
from ..ingestion import (
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
)
from .view import SpineInputs

# examples/data sits beside the package in a checkout, not inside it.
_EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "data"


@dataclass(frozen=True)
class SampleProject:
    key: str
    name: str
    folder: str
    drilling: Optional[str] = None
    pumping: Optional[str] = None
    quality: Optional[str] = None
    note: str = ""


SAMPLES: tuple[SampleProject, ...] = (
    SampleProject(
        key="dr_timbo",
        name="Dr. Timbo's Residence",
        folder="dr_timbo",
        drilling="dr_timbo_drilling_log.xlsx",
        pumping="dr_timbo_constant_test.xlsx",
        quality="dr_timbo_water_quality.xlsx",
        note="Completed borehole: drilling log, constant-rate test and a full analysis.",
    ),
    SampleProject(
        key="kuntolo",
        name="Kuntolo",
        folder="kuntolo",
        pumping="kuntolo_step_test.xlsx",
        note="Step-drawdown test only — no drilling log, so there is no section to draw.",
    ),
    SampleProject(
        key="rokel",
        name="Rokel",
        folder="rokel",
        note="Geophysical siting survey — VES soundings, drilled later.",
    ),
)


def available() -> list[SampleProject]:
    """Sample projects that carry enough data for the workspace to draw."""
    return [s for s in SAMPLES if s.drilling and (_EXAMPLES / s.folder).is_dir()]


def load(key: str, config: Config | None = None) -> SpineInputs:
    """Parse one sample project and run the analyses it supports."""
    sample = next((s for s in SAMPLES if s.key == key), None)
    if sample is None:
        raise KeyError(f"unknown sample project: {key}")
    if not sample.drilling:
        raise ValueError(
            f"{sample.name} has no drilling log, so there is no borehole section "
            "to place screens on."
        )

    config = config or Config()
    folder = _EXAMPLES / sample.folder
    log = read_drilling_workbook(folder / sample.drilling)

    analysis = None
    if sample.pumping:
        test = read_pumping_workbook(folder / sample.pumping)
        analysis = analyse_pumping_test(test, config.pumping)
        # The safe yield rests on an assumed storativity, effective radius and
        # seasonal decline. Attaching the envelope is what lets the workspace
        # show a band instead of a bare number.
        attach_yield_envelope(analysis, config.pumping)

    quality = None
    if sample.quality:
        quality = read_quality_workbook(folder / sample.quality)

    return SpineInputs(
        name=sample.name,
        log=log,
        analysis=analysis,
        quality=quality,
        config=config,
    )
