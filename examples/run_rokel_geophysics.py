"""End to end Phase 1 example: Rokel geophysical survey.

Parses the transcribed Rokel VES workbook, runs the consistency
checks, inverts both soundings (and imports the original IPI2Win
models for comparison), interprets them hydrogeologically, and writes
the full geophysical survey report with all figures and tables into a
standard project folder.

Run from the repository root:

    python examples/run_rokel_geophysics.py
"""

from __future__ import annotations

import csv
from pathlib import Path

from groundwater import Project
from groundwater.ingestion import check_all, read_ves_workbook
from groundwater.models import SiteMetadata
from groundwater.reporting.geophysical import (
    GeophysicalReportInputs,
    build_geophysical_report,
)
from groundwater.utils import fmt_num
from groundwater.ves import (
    drilling_preference_table,
    interpret_model,
    invert_sounding,
    read_ipi2win_models,
)
from groundwater.ves.plots import plot_geoelectric_section

HERE = Path(__file__).parent
VES_FILE = HERE / "data" / "rokel" / "rokel_ves.xlsx"
IPI_FILE = HERE / "data" / "rokel" / "rokel_ipi2win_models.xlsx"


def main() -> None:
    # ---- project folder -----------------------------------------------------
    project = Project.create(
        HERE / "projects" / "rokel",
        SiteMetadata(
            client="Living Water International",
            project="Geophysical Survey",
            community="Rokel",
            district="Western Area",
            date="8th December, 2015",
        ),
    )

    # ---- parse and check ------------------------------------------------------
    soundings = read_ves_workbook(VES_FILE)
    print(f"parsed {len(soundings)} soundings from {VES_FILE.name}")
    for s in soundings:
        for flag in s.flags:
            print(" ", flag)

    flags = check_all([(s.sounding_id, s.site) for s in soundings])
    print("\nconsistency checks:")
    for flag in flags:
        print(" ", flag)

    # ---- IPI2Win import (previous interpretation, for comparison) -----------
    ipi_models = read_ipi2win_models(IPI_FILE)
    for sid, model in ipi_models.items():
        print(
            f"\nIPI2Win model {sid}: {model.n_layers} layers, "
            f"reported ERR = {model.fit_error_percent}%"
        )

    # ---- inversion and interpretation ----------------------------------------
    inversions = []
    interpretations = []
    for sounding in soundings:
        result = invert_sounding(sounding, project.config.ves)
        interp = interpret_model(sounding, result.model, project.config.ves)
        inversions.append(result)
        interpretations.append(interp)
        print(
            f"\n{sounding.sounding_id}: {result.model.n_layers} layers, "
            f"ERR = {result.fit_error_percent:.1f}%, zones = {interp.water_zones}, "
            f"max drilling depth = {interp.max_drilling_depth_m:.0f} m"
        )

    # ---- processed tables for traceability -----------------------------------
    with open(project.processed_path("layered_models.csv"), "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["sounding", "N", "rho_ohm_m", "h_m", "z_top_m", "err_percent"])
        for inv in inversions:
            for row in inv.model.as_table():
                writer.writerow(
                    [
                        inv.model.sounding_id,
                        row["N"],
                        fmt_num(row["rho_ohm_m"], 6),
                        "" if row["h_m"] is None else fmt_num(row["h_m"], 6),
                        0 if row["z_m"] == "0/0" else fmt_num(row["z_m"], 6),
                        fmt_num(inv.fit_error_percent, 3),
                    ]
                )
    rows = drilling_preference_table(interpretations)
    with open(project.processed_path("drilling_preference.csv"), "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: str(v).replace("\n", " | ") for k, v in row.items()})

    # ---- extra figure: geoelectric section along the traverse ----------------
    plot_geoelectric_section(
        [inv.model for inv in inversions],
        positions=[0.0, 60.0],
        labels=[s.sounding_id for s in soundings],
        depth_max=45.0,
        path=project.figure_path("geoelectric_section.png"),
    )

    # ---- report ---------------------------------------------------------------
    report_path = build_geophysical_report(
        GeophysicalReportInputs(
            soundings=soundings,
            inversions=inversions,
            interpretations=interpretations,
            figures_dir=project.figures,
            geologist_name="A. N. Geologist",
            geologist_phone="+232 00 000 000",
            flags=flags,
            include_qa_annex=True,
        ),
        project.report_path("Rokel_Geophysical_Survey_Report.docx"),
        project.config,
    )
    print(f"\nreport written to {report_path}")


if __name__ == "__main__":
    main()
