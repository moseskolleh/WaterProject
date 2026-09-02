"""The command line: the same library calls the apps make, for batch use."""

from __future__ import annotations

import json

import pytest

from groundwater.cli import main


def _project_file(sample_data, tmp_path, name="p.yaml", **extra):
    from groundwater.project_io import serialize_project

    session = {
        "meta_community": "Dr Timbo", "meta_district": "Bombali",
        "src_pump": {"sample": "dr_timbo/dr_timbo_constant_test.xlsx"},
        "src_wq": {"sample": "dr_timbo/dr_timbo_water_quality.xlsx"},
        "src_log": {"sample": "dr_timbo/dr_timbo_drilling_log.xlsx"},
        "project_summary": {
            "community": "Dr Timbo", "district": "Bombali", "status": "Successful",
            "total_depth_m": 62.0, "safe_yield_m3_per_h": 0.97, "water_verdict": "health_fail",
            "verdict_schema": 2, "cost_per_meter_usd": 130.0,
            "easting": 778000.0, "northing": 946000.0, "utm_zone": 28,
        },
    }
    session.update(extra)
    path = tmp_path / name
    path.write_bytes(serialize_project(session, "0.2.0"))
    return path


def test_recompute_reports_every_source_and_writes_a_summary(sample_data, tmp_path, capsys):
    project = _project_file(sample_data, tmp_path)
    out = tmp_path / "summary.json"
    code = main(["recompute", str(project), "--json", str(out),
                 "--sample-root", str(sample_data), "--tmp-dir", str(tmp_path)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "ok:" in printed
    summary = json.loads(out.read_text())
    assert summary["pumping"]["transmissivity_source"] == "recovery"
    assert summary["pumping"]["safe_yield_m3_per_h"] > 0
    assert summary["water_quality"]["verdict"] == "health_fail"
    assert summary["design"]["screens"]


def test_recompute_exits_nonzero_when_a_source_cannot_be_read(sample_data, tmp_path, capsys):
    project = _project_file(sample_data, tmp_path, name="bad.yaml",
                            src_pump={"name": "junk.xlsx", "bytes": b"not a workbook"})
    code = main(["recompute", str(project), "--sample-root", str(sample_data),
                 "--tmp-dir", str(tmp_path)])
    printed = capsys.readouterr().out
    assert code == 1
    assert "error:" in printed


def test_portfolio_pools_project_files_into_a_table(sample_data, tmp_path, capsys):
    a = _project_file(sample_data, tmp_path, name="a.yaml")
    b = _project_file(sample_data, tmp_path, name="b.yaml")
    (tmp_path / "broken.yaml").write_text("state: [1, 2]\n")
    csv_out = tmp_path / "portfolio.csv"
    code = main(["portfolio", str(a), str(b), str(tmp_path / "broken.yaml"),
                 "--csv", str(csv_out), "--map", str(tmp_path / "map.png")])
    captured = capsys.readouterr()
    assert code == 0
    assert "n_projects: 2" in captured.out and "skipped broken.yaml" in captured.err
    assert csv_out.read_text().count("Dr Timbo") == 2
    assert (tmp_path / "map.png").stat().st_size > 1000


def test_templates_are_written(tmp_path, capsys):
    assert main(["templates", str(tmp_path / "templates")]) == 0
    written = capsys.readouterr().out.splitlines()
    assert len(written) == 5 and all(line.endswith(".xlsx") for line in written)


def test_the_console_script_is_declared():
    from importlib import metadata
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'groundwater = "groundwater.cli:main"' in text
    # and the installed distribution actually exposes it
    scripts = {ep.name: ep.value for ep in metadata.entry_points(group="console_scripts")}
    assert scripts.get("groundwater") == "groundwater.cli:main"


def test_an_unknown_command_is_refused():
    with pytest.raises(SystemExit):
        main(["frobnicate"])
