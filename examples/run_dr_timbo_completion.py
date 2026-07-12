"""Dr. Timbo completion example: the full Phase 2 chain.

Drilling log + constant discharge test + water quality results are
parsed from the transcribed template files, the borehole design is
generated and drawn to scale, and three reports are produced: the
borehole completion report, the water quality report and the project
handover report.

Run from the repository root:

    python examples/run_dr_timbo_completion.py
"""

from __future__ import annotations

from pathlib import Path

from groundwater import Project
from groundwater.design import design_borehole
from groundwater.hydraulics import analyse_pumping_test
from groundwater.ingestion import (
    check_all,
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
)
from groundwater.quality import assess_sample
from groundwater.reporting.completion import (
    CompletionReportInputs,
    build_completion_report,
)
from groundwater.reporting.handover import (
    CommitteeMember,
    HandoverReportInputs,
    build_handover_report,
)
from groundwater.reporting.quality import QualityReportInputs, build_quality_report

HERE = Path(__file__).parent
DATA = HERE / "data" / "dr_timbo"


def main() -> None:
    project = Project.open(HERE / "projects" / "dr_timbo")

    # ---- parse everything -----------------------------------------------------
    log = read_drilling_workbook(DATA / "dr_timbo_drilling_log.xlsx")
    test = read_pumping_workbook(DATA / "dr_timbo_constant_test.xlsx")
    sample = read_quality_workbook(DATA / "dr_timbo_water_quality.xlsx")
    project.site = log.site
    project.save_metadata()

    print("consistency checks:")
    for flag in check_all(
        [("drilling log", log.site), ("pumping test", test.site), ("quality", sample.site)]
    ):
        print(" ", flag)

    # ---- analysis ----------------------------------------------------------------
    analysis = analyse_pumping_test(test, project.config.pumping)
    print(
        f"\nT = {analysis.transmissivity_m2_per_day and round(analysis.transmissivity_m2_per_day, 2)} m2/day, "
        f"safe yield = {analysis.yield_recommendation.safe_yield_m3_per_h and round(analysis.yield_recommendation.safe_yield_m3_per_h, 2)} m3/h"
    )
    assessment = assess_sample(sample)
    print("water quality:", assessment.verdict.split(".")[0] + ".")

    design = design_borehole(
        log=log,
        static_water_level_m=test.static_water_level_m,
        pump_intake_m=analysis.yield_recommendation.pump_installation_depth_m,
        rules=project.config.design,
    )

    # ---- reports --------------------------------------------------------------------
    completion = build_completion_report(
        CompletionReportInputs(
            log=log,
            design=design,
            pumping=analysis,
            quality=assessment,
            figures_dir=project.figures,
            development_record=[
                ("17:00", "17:17", "", "Muddy water flushed out"),
                ("17:17", "17:47", "2.5", "Cloudy water flushed out"),
                ("17:48", "18:00", "", "Clean water flushed out"),
            ],
            development_note=(
                "The borehole was developed by surging with compressed air and "
                "air lifting for a total of two hours."
            ),
            pump_type="Submersible pump",
            preparer_name="A. N. Manager",
        ),
        project.report_path("Dr_Timbo_Borehole_Completion_Report.docx"),
        project.config,
    )
    print("\ncompletion report:", completion.name)

    quality_report = build_quality_report(
        QualityReportInputs(
            assessment=assessment,
            figures_dir=project.figures,
            analyst_name="A. N. Analyst",
        ),
        project.report_path("Dr_Timbo_Water_Quality_Report.docx"),
        project.config,
    )
    print("water quality report:", quality_report.name)

    handover = build_handover_report(
        HandoverReportInputs(
            site=log.site,
            log=log,
            design=design,
            pumping=analysis,
            quality=assessment,
            figures_dir=project.figures,
            committee=[
                CommitteeMember("Chairperson", "To be completed"),
                CommitteeMember("Secretary", "To be completed"),
                CommitteeMember("Treasurer", "To be completed"),
                CommitteeMember("Caretaker", "To be completed"),
            ],
            pump_type="Submersible pump",
            contractor_rep="WiNGiN Heavy Duty Machines Co. Ltd",
            client_rep="Dr. Timbo",
        ),
        project.report_path("Dr_Timbo_Handover_Report.docx"),
        project.config,
    )
    print("handover report:", handover.name)


if __name__ == "__main__":
    main()
