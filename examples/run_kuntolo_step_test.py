"""Kuntolo step test example: pending-discharge workflow.

The Kuntolo field sheet does not record the discharge of any step, so
this example shows exactly what the system produces in that state: the
water level and drawdown curves, the stabilised level and available
drawdown, the data verification flags (including the negative drawdown
anomaly on this sheet), and a pumping test report with transmissivity
and yield marked as pending.

Supply the discharges (uncomment below) and the same script completes
the Hantush-Bierschenk analysis and the yield recommendation.

Run from the repository root:

    python examples/run_kuntolo_step_test.py
"""

from __future__ import annotations

from pathlib import Path

from groundwater import Project
from groundwater.hydraulics import analyse_pumping_test
from groundwater.ingestion import read_pumping_workbook
from groundwater.models import SiteMetadata
from groundwater.reporting.pumping import PumpingReportInputs, build_pumping_report

HERE = Path(__file__).parent
TEST_FILE = HERE / "data" / "kuntolo" / "kuntolo_step_test.xlsx"


def main() -> None:
    project = Project.create(
        HERE / "projects" / "kuntolo",
        SiteMetadata(client="ACF", community="Kuntoloh", district="Port Loko"),
    )

    test = read_pumping_workbook(TEST_FILE)
    print(f"test type: {test.test_type}, steps: {len(test.steps)}, "
          f"SWL: {test.static_water_level_m} m")
    for flag in test.flags:
        print(" ", flag)

    # --- once the field team supplies the step discharges, enter them here ---
    # test.steps[0].discharge_m3_per_h = 1.5
    # test.steps[1].discharge_m3_per_h = 2.2
    # test.steps[2].discharge_m3_per_h = 3.0

    analysis = analyse_pumping_test(test, project.config.pumping)
    yr = analysis.yield_recommendation
    print("\ntransmissivity:", analysis.transmissivity_m2_per_day, "m2/day")
    print("available drawdown:", yr.available_drawdown_m, "m")
    print("safe yield:", yr.safe_yield_m3_per_h, "m3/h")
    print("basis:", yr.basis)

    report = build_pumping_report(
        PumpingReportInputs(
            analysis=analysis,
            figures_dir=project.figures,
            analyst_name="A. N. Analyst",
        ),
        project.report_path("Kuntolo_Pumping_Test_Report.docx"),
        project.config,
    )
    print(f"\nreport written to {report}")


if __name__ == "__main__":
    main()
