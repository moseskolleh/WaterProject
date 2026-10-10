"""Time the toolkit, so a change that claims to be faster can show it.

Each measure is a thing a user waits for: importing a subsystem, one call
of the forward model, inverting a sample sounding, analysing a sample
pumping test, building each report the package offers, recomputing a
saved project the way ``groundwater recompute`` does, and one run of the
Streamlit app's script. Every one is run on the bundled examples, so two
commits are timed on the same work.

The method is the same for every in-process measure, and is written into
the output beside each number:

- one warm-up call first, whose time is thrown away, so the numbers are
  steady-state: bytecode compiled, lookup tables and caches built, files
  in the page cache;
- then ``--repeats`` samples (5, or 2 with ``--quick``). A call quicker
  than 0.2 s is looped until one sample lasts at least that long and the
  sample is divided by the loop count, so a 1 ms call is not timed at the
  resolution of the clock;
- the median is the number, and the spread is the interquartile range
  beside the minimum and maximum. The median rather than the mean,
  because on a shared machine the noise is one-sided: another process
  only ever makes a sample slower.

An import is timed in a fresh interpreter every time, since a second
import in the same process costs nothing: the wall time of
``python -c "import groundwater.X"`` minus that of ``python -c "pass"``,
the two run back to back and subtracted pair by pair so that a slow
moment on the machine lands in both.

numpy runs with one BLAS thread (``OPENBLAS_NUM_THREADS=1`` and its
cousins, unless already set): the inversion's matrices are too small to
gain from more, and with more its time follows whatever else the machine
is running.

Run from the repository root:

    python bench/run.py                              # everything
    python bench/run.py --quick --only inversion     # one group, quickly
    python bench/run.py --compare bench/baseline.json
    python bench/run.py --from a.json --from b.json --out merged.json

``--from`` reads measures from files instead of running anything, which
is how a ``bench/web.mjs`` result is merged into the baseline or compared
against it. The package is imported from this checkout's ``src/``, not
from wherever it happens to be installed, so the timings are of the code
beside this file.
"""

from __future__ import annotations

import argparse
import contextlib
import gc
import io
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SRC = REPO / "src"
DATA = REPO / "examples" / "data"
APP = REPO / "app" / "streamlit_app.py"
sys.path.insert(0, str(SRC))
os.environ.setdefault("MPLBACKEND", "Agg")
# One BLAS thread, set before numpy is first imported. The inversion's
# matrices are small, and OpenBLAS's default of a thread per CPU spends more
# time waking threads than it saves; on a machine with anything else running
# it made Rokel A 2.3x slower and ten times noisier (1.5 s, IQR 0.04 s, with
# one thread; 3.5 s, IQR 0.45 to 0.67 s, with four). A number that moves
# with the neighbours' load cannot compare two commits. setdefault, so a
# run can still ask for more and the machine block records it.
BLAS_THREADS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
for _name in BLAS_THREADS:
    os.environ.setdefault(_name, "1")

#: The output's own layout number; ``--from`` refuses a file in another.
SCHEMA = 1
TOOL = "bench/run.py"
GROUPS = ("import", "forward", "inversion", "range", "cost", "pumping", "reports",
          "recompute", "streamlit")
MIN_SAMPLE_S = 0.2


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

def _once(fn: Callable[[], object], loops: int) -> float:
    gc.collect()
    start = time.perf_counter()
    for _ in range(loops):
        fn()
    return time.perf_counter() - start


def time_call(fn: Callable[[], object], repeats: int) -> tuple[list[float], int]:
    """Per-call samples after one warm-up, and the loop count each sample used."""
    first = _once(fn, 1)                     # the warm-up, discarded
    loops = 1
    if first < MIN_SAMPLE_S:
        loops = max(1, round(MIN_SAMPLE_S / max(first, 1e-6)))
    return [_once(fn, loops) / loops for _ in range(repeats)], loops


def _subprocess_env() -> dict:
    env = dict(os.environ, MPLBACKEND="Agg")
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(SRC), env.get("PYTHONPATH", "")) if p)
    return env


def _wall(code: str, env: dict) -> float:
    start = time.perf_counter()
    subprocess.run([sys.executable, "-c", code], env=env, check=True,
                   stdout=subprocess.DEVNULL)
    return time.perf_counter() - start


def time_import(module: str | None, repeats: int) -> list[float]:
    """Import cost in a fresh interpreter, less a bare interpreter's start."""
    env = _subprocess_env()
    if module is None:
        _wall("pass", env)
        return [_wall("pass", env) for _ in range(repeats)]
    _wall(f"import {module}", env)           # warm-up: writes the bytecode
    samples = []
    for _ in range(repeats):
        bare = _wall("pass", env)
        samples.append(_wall(f"import {module}", env) - bare)
    return samples


def summarise(samples: list[float]) -> dict:
    ordered = sorted(samples)
    if len(ordered) >= 2:
        q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    else:
        q1 = q3 = ordered[0]
    return {
        "median": statistics.median(ordered),
        "iqr": q3 - q1,
        "min": ordered[0],
        "max": ordered[-1],
        "n": len(ordered),
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# What is timed
# ---------------------------------------------------------------------------

@dataclass
class Measure:
    group: str
    name: str
    #: Builds the inputs (untimed) and returns the call that is timed.
    setup: Callable[[Path], Callable[[], object]] | None = None
    #: For an import measure, the module; ``""`` is the bare interpreter.
    module: str | None = None

    @property
    def id(self) -> str:
        return f"{self.group}/{self.name}"


class Inputs:
    """The parsed examples and the analyses built on them, made once.

    Parsing and the analyses a report is written from are not what a report
    measure times, so they are built here on first use and shared.
    """

    def __init__(self):
        self._cache: dict = {}

    def _get(self, key, build):
        if key not in self._cache:
            self._cache[key] = build()
        return self._cache[key]

    @property
    def config(self):
        from groundwater.config import Config
        return self._get("config", Config)

    def ves_workbooks(self) -> list[Path]:
        return sorted(DATA.glob("*/*_ves.xlsx"))

    def soundings(self, path: Path):
        from groundwater.ingestion import read_ves_workbook
        return self._get(("soundings", path), lambda: read_ves_workbook(path))

    def inversion(self, path: Path, index: int):
        from groundwater.ves import invert_sounding
        return self._get(("inversion", path, index), lambda: invert_sounding(
            self.soundings(path)[index], self.config.ves))

    def rokel(self):
        def build():
            from groundwater.ingestion import check_all
            from groundwater.ves import interpret_model, read_ipi2win_models
            path = DATA / "rokel" / "rokel_ves.xlsx"
            soundings = self.soundings(path)
            inversions = [self.inversion(path, i) for i in range(len(soundings))]
            interps = [interpret_model(s, r.model, self.config.ves)
                       for s, r in zip(soundings, inversions, strict=True)]
            return {
                "soundings": soundings, "inversions": inversions,
                "interpretations": interps,
                "flags": check_all([(s.sounding_id, s.site) for s in soundings]),
                "ipi": read_ipi2win_models(DATA / "rokel" / "rokel_ipi2win_models.xlsx"),
            }
        return self._get("rokel", build)

    def pumping_test(self, name: str):
        from groundwater.ingestion import read_pumping_workbook
        return self._get(("pump", name), lambda: read_pumping_workbook(DATA / name))

    def kuntolo_with_discharges(self):
        def build():
            import copy
            test = copy.deepcopy(self.pumping_test("kuntolo/kuntolo_step_test.xlsx"))
            # the illustrative discharges run_kuntolo_step_test.py carries in
            # its comments; they exercise the Hantush-Bierschenk path the
            # sheet as recorded never reaches
            for step, q in zip(test.steps, (1.5, 2.2, 3.0), strict=False):
                step.discharge_m3_per_h = q
            return test
        return self._get("kuntolo_q", build)

    def timbo(self):
        def build():
            from groundwater.design import design_borehole, pump_intake_floor
            from groundwater.hydraulics import analyse_pumping_test
            from groundwater.ingestion import read_drilling_workbook, read_quality_workbook
            from groundwater.quality import assess_sample
            from groundwater.readiness import assess_readiness
            log = read_drilling_workbook(DATA / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
            test = self.pumping_test("dr_timbo/dr_timbo_constant_test.xlsx")
            sample = read_quality_workbook(DATA / "dr_timbo" / "dr_timbo_water_quality.xlsx")
            analysis = analyse_pumping_test(test, self.config.pumping)
            assessment = assess_sample(sample)
            design = design_borehole(
                log=log, static_water_level_m=test.static_water_level_m,
                pump_intake_m=analysis.yield_recommendation.pump_installation_depth_m,
                pump_intake_floor_m=pump_intake_floor(
                    analysis.yield_recommendation,
                    self.config.pumping.pump_submergence_min_m),
                rules=self.config.design,
            )
            state = {
                "site": log.site, "drilling_log": log, "pump_analysis": analysis,
                "wq_assessment": assessment, "borehole_design": design,
                "sources": {
                    "log": {"name": "dr_timbo_drilling_log.xlsx"},
                    "pump": {"name": "dr_timbo_constant_test.xlsx"},
                    "wq": {"name": "dr_timbo_water_quality.xlsx"},
                },
            }
            gates = {kind: assess_readiness(state, kind)
                     for kind in ("completion", "quality", "handover", "costing",
                                  "supervision", "procurement")}
            return {"log": log, "analysis": analysis, "assessment": assessment,
                    "design": design, "gates": gates}
        return self._get("timbo", build)

    def estimate(self):
        def build():
            from groundwater.costing import estimate_borehole_cost, inputs_from_design
            return estimate_borehole_cost(inputs_from_design(self.timbo()["design"]))
        return self._get("estimate", build)


INPUTS = Inputs()


def _import_measures() -> list[Measure]:
    import pkgutil
    pkg = SRC / "groundwater"
    subpackages = sorted(m.name for m in pkgutil.iter_modules([str(pkg)]) if m.ispkg)
    return ([Measure("import", "bare interpreter start", module=""),
             Measure("import", "groundwater", module="groundwater")]
            + [Measure("import", f"groundwater.{name}", module=f"groundwater.{name}")
               for name in subpackages])


def _forward_measures() -> list[Measure]:
    def setup(_tmp):
        from groundwater.ves.forward import forward_for_sounding
        path = DATA / "rokel" / "rokel_ves.xlsx"
        sounding = INPUTS.soundings(path)[0]
        model = INPUTS.inversion(path, 0).model
        return lambda: forward_for_sounding(model, sounding)
    return [Measure("forward", "rokel sounding A, fitted model", setup)]


def _inversion_measures() -> list[Measure]:
    from groundwater.ingestion import read_ves_workbook
    out = []
    for path in INPUTS.ves_workbooks():
        # the soundings are listed from the workbook so a sample added later
        # is timed without editing this file
        for index, sounding in enumerate(read_ves_workbook(path)):
            def setup(_tmp, path=path, index=index):
                from groundwater.ves import invert_sounding
                sounding = INPUTS.soundings(path)[index]
                return lambda: invert_sounding(sounding, INPUTS.config.ves)
            out.append(Measure("inversion",
                               f"{path.parent.name} sounding {sounding.sounding_id}",
                               setup))
    return out


def _range_measures() -> list[Measure]:
    # The range of models (PLAN.md step 3.1) at the default settings, around
    # the inversion's own fit: the Latin hypercube starts polished, the
    # chains' burn-in and the kept samples. Each Rokel sounding, since a
    # three-layer model and a two-layer one cost differently per call.
    out = []
    path = DATA / "rokel" / "rokel_ves.xlsx"
    for index in range(2):
        def setup(_tmp, index=index):
            from groundwater.ves.model_range import sample_model_range
            sounding = INPUTS.soundings(path)[index]
            inversion = INPUTS.inversion(path, index)
            return lambda: sample_model_range(sounding, inversion, INPUTS.config)
        out.append(Measure("range", f"rokel sounding {'AB'[index]}, default settings",
                           setup))
    return out


def _cost_measures() -> list[Measure]:
    # The cost as a distribution (PLAN.md step 3.4) at the default sample
    # count, on the Dr Timbo design's bill of quantities, the depth drawn
    # from Rokel A's range at the default settings (sampled beforehand) and
    # dry holes at a 60 percent chance; the programme is ten boreholes at 60
    # percent with the same depth.
    def spread():
        def build():
            from groundwater.costing import depth_spread
            from groundwater.ves.model_range import sample_model_range
            path = DATA / "rokel" / "rokel_ves.xlsx"
            r = sample_model_range(INPUTS.soundings(path)[0], INPUTS.inversion(path, 0),
                                   INPUTS.config)
            return depth_spread(r, INPUTS.config)
        return INPUTS._get("rokel_a_depth", build)

    def inputs():
        from groundwater.costing import inputs_from_design
        return inputs_from_design(INPUTS.timbo()["design"], mobilisation_distance_km=100.0)

    def single(_tmp):
        from groundwater.costing import sample_cost
        given, depth = inputs(), spread()
        return lambda: sample_cost(given, depth=depth, success_probability=0.6,
                                   odds_source="A", config=INPUTS.config)

    def programme(_tmp):
        from groundwater.costing import sample_programme_cost
        given, depth = inputs(), spread()
        return lambda: sample_programme_cost(given, 10, success_rate_percent=60.0,
                                             depth=depth, config=INPUTS.config)

    return [Measure("cost", "dr_timbo bill of quantities, depth from rokel A", single),
            Measure("cost", "programme of ten, depth from rokel A", programme)]


def _pumping_measures() -> list[Measure]:
    def analyse(get):
        def setup(_tmp):
            from groundwater.hydraulics import analyse_pumping_test
            test = get()
            return lambda: analyse_pumping_test(test, INPUTS.config.pumping)
        return setup
    return [
        Measure("pumping", "kuntolo step test, discharges pending",
                analyse(lambda: INPUTS.pumping_test("kuntolo/kuntolo_step_test.xlsx"))),
        Measure("pumping", "kuntolo step test, example discharges",
                analyse(INPUTS.kuntolo_with_discharges)),
        Measure("pumping", "dr_timbo constant rate and recovery",
                analyse(lambda: INPUTS.pumping_test("dr_timbo/dr_timbo_constant_test.xlsx"))),
    ]


def _report_measures() -> list[Measure]:
    # Each builds into its own scratch folder, figures included, as the
    # example scripts do into a project folder.
    def geophysical(tmp):
        from groundwater.readiness import assess_readiness
        from groundwater.reporting.geophysical import (
            GeophysicalReportInputs, build_geophysical_report)
        r = INPUTS.rokel()
        inputs = GeophysicalReportInputs(
            soundings=r["soundings"], inversions=r["inversions"],
            interpretations=r["interpretations"], figures_dir=tmp,
            readiness=assess_readiness({"site": r["soundings"][0].site}, "geophysical"),
            flags=r["flags"], include_qa_annex=True, reference_models=r["ipi"])
        return lambda: build_geophysical_report(inputs, tmp / "geophysical.docx",
                                                INPUTS.config)

    def pumping(tmp):
        from groundwater.hydraulics import analyse_pumping_test
        from groundwater.readiness import assess_readiness
        from groundwater.reporting.pumping import PumpingReportInputs, build_pumping_report
        test = INPUTS.pumping_test("kuntolo/kuntolo_step_test.xlsx")
        analysis = analyse_pumping_test(test, INPUTS.config.pumping)
        inputs = PumpingReportInputs(
            analysis=analysis, figures_dir=tmp,
            readiness=assess_readiness({"site": test.site, "pump_analysis": analysis},
                                       "pumping"))
        return lambda: build_pumping_report(inputs, tmp / "pumping.docx", INPUTS.config)

    def completion(tmp):
        from groundwater.reporting.completion import (
            CompletionReportInputs, build_completion_report)
        t = INPUTS.timbo()
        inputs = CompletionReportInputs(
            log=t["log"], design=t["design"], pumping=t["analysis"],
            quality=t["assessment"], readiness=t["gates"]["completion"],
            figures_dir=tmp, pump_type="Submersible pump")
        return lambda: build_completion_report(inputs, tmp / "completion.docx",
                                               INPUTS.config)

    def quality(tmp):
        from groundwater.reporting.quality import QualityReportInputs, build_quality_report
        t = INPUTS.timbo()
        inputs = QualityReportInputs(assessment=t["assessment"], figures_dir=tmp,
                                     readiness=t["gates"]["quality"])
        return lambda: build_quality_report(inputs, tmp / "quality.docx", INPUTS.config)

    def handover(tmp):
        from groundwater.reporting.handover import (
            CommitteeMember, HandoverReportInputs, build_handover_report)
        t = INPUTS.timbo()
        inputs = HandoverReportInputs(
            site=t["log"].site, log=t["log"], design=t["design"], pumping=t["analysis"],
            quality=t["assessment"], figures_dir=tmp,
            committee=[CommitteeMember(role, "To be completed") for role in
                       ("Chairperson", "Secretary", "Treasurer", "Caretaker")],
            pump_type="Submersible pump", readiness=t["gates"]["handover"])
        return lambda: build_handover_report(inputs, tmp / "handover.docx", INPUTS.config)

    def cost(tmp):
        from groundwater.reporting.costing import CostReportInputs, build_cost_report
        t = INPUTS.timbo()
        inputs = CostReportInputs(estimate=INPUTS.estimate(), site=t["log"].site,
                                  figures_dir=tmp, readiness=t["gates"]["costing"])
        return lambda: build_cost_report(inputs, tmp / "cost.docx", INPUTS.config)

    def certificate(tmp):
        from groundwater.procurement import Measurement, certify, contract_from_estimate
        from groundwater.reporting.procurement import (
            PaymentCertificateInputs, build_payment_certificate)
        contract = contract_from_estimate(INPUTS.estimate(), ref="BENCH/1")
        # half of every line measured, so each line is valued
        measured = [Measurement(line.code, line.quantity / 2) for line in contract.lines]
        inputs = PaymentCertificateInputs(
            contract=contract,
            certificate=certify(contract, measured, number=1, date="2024-04-01"),
            site=INPUTS.timbo()["log"].site, figures_dir=tmp,
            readiness=INPUTS.timbo()["gates"]["procurement"])
        return lambda: build_payment_certificate(inputs, tmp / "certificate.docx",
                                                 INPUTS.config)

    def supervision(tmp):
        from groundwater.reporting.supervision import (
            SupervisionReportInputs, build_supervision_report)
        from groundwater.supervision import (
            ChecklistResponse, evaluate_checklist, load_checklists)
        items = load_checklists()
        responses = {i.item_id: ChecklistResponse(i.item_id, "yes") for i in items}
        t = INPUTS.timbo()
        inputs = SupervisionReportInputs(
            site=t["log"].site, items=items, responses=responses,
            assessment=evaluate_checklist(items, responses), figures_dir=tmp,
            readiness=t["gates"]["supervision"])
        return lambda: build_supervision_report(inputs, tmp / "supervision.docx",
                                                INPUTS.config)

    def _asset():
        from datetime import date

        from groundwater.models import SiteMetadata
        from groundwater.registry import Asset, AssetEvent, mint_asset_id
        # The Dr Timbo sheets carry no position, and an asset needs one for
        # its identifier. This is the test suite's fixture position, used so
        # the area map is drawn and timed; the documents are thrown away.
        site = SiteMetadata(community="Dr. Timbo's", district="Western Area Rural",
                            easting=694912.0, northing=938150.0, utm_zone=28)
        asset = Asset(asset_id=mint_asset_id(site), community=site.community,
                      district=site.district, easting=site.easting,
                      northing=site.northing, utm_zone=site.utm_zone,
                      total_depth_m=62.0, pump_type="India Mark II",
                      events=[AssetEvent("2020-01-10", "commissioned")])
        return asset, date(2024, 6, 1)

    def placard(tmp):
        from groundwater.reporting.registry import AssetReportInputs, build_asset_placard
        asset, today = _asset()
        inputs = AssetReportInputs(asset=asset, figures_dir=tmp, today=today)
        return lambda: build_asset_placard(inputs, tmp / "placard.docx", INPUTS.config)

    def record(tmp):
        from groundwater.reporting.registry import AssetReportInputs, build_asset_record
        asset, today = _asset()
        inputs = AssetReportInputs(asset=asset, figures_dir=tmp, today=today)
        return lambda: build_asset_record(inputs, tmp / "record.docx", INPUTS.config)

    return [
        Measure("reports", "geophysical survey (rokel)", geophysical),
        Measure("reports", "pumping test (kuntolo)", pumping),
        Measure("reports", "borehole completion (dr_timbo)", completion),
        Measure("reports", "water quality (dr_timbo)", quality),
        Measure("reports", "handover (dr_timbo)", handover),
        Measure("reports", "cost estimate (dr_timbo)", cost),
        Measure("reports", "payment certificate (dr_timbo)", certificate),
        Measure("reports", "supervision (dr_timbo)", supervision),
        Measure("reports", "asset placard", placard),
        Measure("reports", "asset record", record),
    ]


#: The saved-project form of each example: the upload keys the apps would
#: have stored, each pointing at the bundled sample it came from.
PROJECT_SOURCES = {
    "rokel": {"ves": "rokel/rokel_ves.xlsx"},
    "kuntolo": {"pump": "kuntolo/kuntolo_step_test.xlsx"},
    "dr_timbo": {"pump": "dr_timbo/dr_timbo_constant_test.xlsx",
                 "wq": "dr_timbo/dr_timbo_water_quality.xlsx",
                 "log": "dr_timbo/dr_timbo_drilling_log.xlsx"},
}


def _recompute_measures() -> list[Measure]:
    # examples/projects/*/project.yaml are the example scripts' output
    # folders, not saved app projects, and carry no sources to recompute.
    # So each example is saved here the way the apps save one, and the
    # recompute is the command line's, parse of the file included.
    # The Rokel project is also timed as it is saved once it has been
    # inverted, with the inversions in the file (PLAN.md step 1.6): that is
    # reopening a survey, where the other is opening one for the first time.
    def setup_for(name, inverted=False):
        def setup(tmp):
            from groundwater.cli import main
            from groundwater.project_io import serialize_project
            from groundwater.recompute import recompute_results
            session = {f"src_{key}": {"sample": sample}
                       for key, sample in PROJECT_SOURCES[name].items()}
            session["meta_community"] = name
            if inverted:
                sources = {key: {"sample": sample}
                           for key, sample in PROJECT_SOURCES[name].items()}
                session["inversion_cache"] = recompute_results(
                    sources, sample_root=DATA, tmp_dir=tmp)["inversion_cache"]
            project = tmp / f"{name}.yaml"
            project.write_bytes(serialize_project(session, "bench"))
            argv = ["recompute", str(project), "--sample-root", str(DATA),
                    "--tmp-dir", str(tmp), "--json", str(tmp / "summary.json")]

            def run():
                with contextlib.redirect_stdout(io.StringIO()):
                    code = main(argv)
                if code:
                    raise RuntimeError(f"groundwater recompute {name} exited {code}")
            return run
        return setup
    return [Measure("recompute", f"{name} saved project", setup_for(name))
            for name in PROJECT_SOURCES] + [
        Measure("recompute", "rokel saved project, inversions saved",
                setup_for("rokel", inverted=True))]


#: The pages a loaded rerun is timed on: the dashboard, each page that draws
#: from a loaded sample, and the two that only read what the others produced.
STREAMLIT_PAGES = ("Overview", "Geophysics (VES)", "Pumping test", "Water quality",
                   "Borehole design", "Depth Spine", "Costing & BoQ", "Supervision")


def _streamlit_measures() -> list[Measure]:
    # A Streamlit app runs its whole script again on every click, so the time
    # of one run is what a user waits for after each one. AppTest runs the
    # real script in this process, as the app tests do. Streamlit is an
    # optional extra; without it the group is left out and says so.
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError:
        print("  streamlit is not installed; the streamlit group is left out",
              file=sys.stderr)
        return []

    def started():
        at = AppTest.from_file(str(APP), default_timeout=600)
        at.run()
        return at

    def checked(at):
        if at.exception:
            raise RuntimeError(f"the Streamlit app failed: {at.exception}")
        return at

    def goto(at, page):
        # the session's page, as the sidebar navigation sets it; before
        # PLAN.md step 1.1 every page ran whichever this was
        at.session_state["nav"] = page
        return checked(at.run())

    def first_run(_tmp):
        return lambda: checked(started())

    def rerun_empty(_tmp):
        at = checked(started())
        return lambda: checked(at.run())

    loaded: list = []

    def loaded_app():
        # every sample loaded and every analysis run, as a user has it by
        # the time they reach the costing page, each picked on its own page.
        # Built once and shared: a rerun that changes nothing leaves it as it
        # was, so each page's measure starts from the same state.
        if loaded:
            return loaded[0]
        at = checked(started())
        for page, key, sample in (
                ("Geophysics (VES)", "sample_ves", "rokel/rokel_ves.xlsx"),
                ("Pumping test", "sample_pump", "dr_timbo/dr_timbo_constant_test.xlsx"),
                ("Water quality", "sample_wq", "dr_timbo/dr_timbo_water_quality.xlsx"),
                ("Borehole design", "sample_log", "dr_timbo/dr_timbo_drilling_log.xlsx")):
            goto(at, page)
            at.selectbox(key=key).select(sample)
            checked(at.run())
        for page, key in (("Geophysics (VES)", "run_ves"), ("Costing & BoQ", "run_cost")):
            goto(at, page)
            at.button(key=key).click()
            checked(at.run())
        loaded.append(at)
        return at

    def rerun_loaded_on(page):
        # the timed rerun changes nothing, so it is the cost each later click
        # on that page pays before its own work
        def setup(_tmp):
            at = goto(loaded_app(), page)
            return lambda: checked(at.run())
        return setup

    return ([Measure("streamlit", "first run, new session", first_run),
             Measure("streamlit", "rerun, new session", rerun_empty),
             Measure("streamlit", "rerun, every sample loaded and analysed",
                     rerun_loaded_on("Overview"))]
            + [Measure("streamlit", f"rerun on {page}, every sample loaded",
                       rerun_loaded_on(page))
               for page in STREAMLIT_PAGES[1:]])


def all_measures(groups) -> list[Measure]:
    builders = {"import": _import_measures, "forward": _forward_measures,
                "inversion": _inversion_measures, "range": _range_measures,
                "cost": _cost_measures,
                "pumping": _pumping_measures,
                "reports": _report_measures, "recompute": _recompute_measures,
                "streamlit": _streamlit_measures}
    return [m for g in GROUPS if g in groups for m in builders[g]()]


def method_of(measure: Measure, repeats: int, loops: int = 1) -> str:
    if measure.group == "import":
        if measure.module == "":
            return (f"wall time of `python -c pass`; 1 warm-up, {repeats} samples, "
                    "median")
        return (f"fresh interpreter each sample: wall time of `python -c \"import "
                f"{measure.module}\"` minus `python -c pass` run just before it; "
                f"1 warm-up, {repeats} samples, median")
    looped = f", each sample {loops} calls averaged" if loops > 1 else ""
    return (f"in process, OPENBLAS_NUM_THREADS={os.environ.get('OPENBLAS_NUM_THREADS')}; "
            f"1 warm-up call, {repeats} samples{looped}, median")


def run_measures(measures: list[Measure], repeats: int, echo=print) -> list[dict]:
    results = []
    with tempfile.TemporaryDirectory(prefix="gwt-bench-") as scratch:
        for i, measure in enumerate(measures):
            tmp = Path(scratch) / f"m{i}"
            tmp.mkdir()
            echo(f"  {measure.id} ...", end="", flush=True)
            if measure.group == "import":
                samples = time_import(measure.module or None, repeats)
                loops = 1
            else:
                samples, loops = time_call(measure.setup(tmp), repeats)
            row = {"id": measure.id, "group": measure.group, "name": measure.name,
                   "tool": TOOL, "unit": "s", "method": method_of(measure, repeats, loops),
                   **summarise(samples)}
            echo(f" {fmt_value(row['median'], 's')}")
            results.append(row)
    return results


# ---------------------------------------------------------------------------
# Where it ran
# ---------------------------------------------------------------------------

def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def run_header(options: dict) -> dict:
    import numpy
    import scipy
    return {
        "tool": TOOL,
        "commit": _git("rev-parse", "HEAD"),
        # a dirty tree is not the commit it names, and a comparison should say so
        "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": {
            "cpu": _cpu_model(),
            "cpu_count": os.cpu_count(),
            "os": platform.platform(),
            "python": platform.python_version(),
            "numpy": numpy.__version__,
            "scipy": scipy.__version__,
            "blas_threads": {name: os.environ.get(name) for name in BLAS_THREADS},
            # a load average well above zero means another process shared the
            # machine, and the numbers are slower than they would be alone
            "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        },
        "options": options,
    }


# ---------------------------------------------------------------------------
# Reading, merging and printing
# ---------------------------------------------------------------------------

def load_document(path: Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise SystemExit(f"{path}: not a bench result in layout {SCHEMA}")
    return doc


def merge(documents: list[dict], notes: str | None = None) -> dict:
    """One document from several; a later measure replaces an earlier one."""
    measures: dict[str, dict] = {}
    runs = []
    for doc in documents:
        runs.extend(doc.get("runs", []))
        for m in doc.get("measures", []):
            measures[m["id"]] = m
    if notes is None:
        notes = next((d["notes"] for d in documents if d.get("notes")), "")
    return {"schema": SCHEMA, "notes": notes, "runs": runs,
            "measures": list(measures.values())}


def fmt_value(value: float | None, unit: str) -> str:
    if value is None:
        return "-"
    if value == 0:
        return "0"
    if unit == "bytes":
        return f"{value / 1e6:.2f} MB" if value >= 1e6 else f"{value / 1e3:.1f} kB"
    if unit == "ms":
        value /= 1000.0
    if value >= 1:
        return f"{value:.2f} s"
    if value >= 1e-3:
        return f"{value * 1e3:.1f} ms"
    return f"{value * 1e6:.0f} us"


def print_table(doc: dict, out=sys.stdout) -> None:
    rows = [("measure", "median", "spread (IQR)", "min", "max", "n")]
    for m in doc["measures"]:
        u = m.get("unit", "s")
        rows.append((m["id"], fmt_value(m["median"], u), fmt_value(m.get("iqr"), u),
                     fmt_value(m.get("min"), u), fmt_value(m.get("max"), u),
                     str(m.get("n", ""))))
    _print_rows(rows, out)


def print_comparison(doc: dict, baseline: dict, out=sys.stdout) -> None:
    """Each measure beside the baseline's, and current / baseline."""
    before = {m["id"]: m for m in baseline["measures"]}
    rows = [("measure", "baseline", "now", "now/baseline", "baseline IQR", "now IQR")]
    for m in doc["measures"]:
        u = m.get("unit", "s")
        b = before.get(m["id"])
        if b is None:
            rows.append((m["id"], "(new)", fmt_value(m["median"], u), "", "",
                         fmt_value(m.get("iqr"), u)))
            continue
        bu = b.get("unit", "s")
        if b["median"]:
            ratio = f"{m['median'] / b['median']:.2f}"
        else:
            ratio = "same" if not m["median"] else "(was 0)"
        rows.append((m["id"], fmt_value(b["median"], bu), fmt_value(m["median"], u),
                     ratio, fmt_value(b.get("iqr"), bu), fmt_value(m.get("iqr"), u)))
    _print_rows(rows, out)
    for run in baseline.get("runs", []):
        print(f"baseline {run.get('tool')}: {run.get('commit', '')[:10]}"
              f"{' (dirty)' if run.get('dirty') else ''} at {run.get('timestamp')}",
              file=out)
    print("A ratio below 1 is faster (or smaller) than the baseline. A change "
          "smaller than either spread is not a change.", file=out)


def _print_rows(rows, out) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for n, row in enumerate(rows):
        cells = [row[0].ljust(widths[0])] + [c.rjust(w) for c, w in zip(row[1:], widths[1:], strict=True)]
        print("  ".join(cells), file=out)
        if n == 0:
            print("  ".join("-" * w for w in widths), file=out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--quick", action="store_true",
                        help="2 samples per measure instead of 5")
    parser.add_argument("--repeats", type=int, help="samples per measure")
    parser.add_argument("--only", action="append", choices=GROUPS, metavar="GROUP",
                        help=f"run only this group ({', '.join(GROUPS)}); repeatable")
    parser.add_argument("--out", type=Path, help="write the result as JSON here")
    parser.add_argument("--compare", type=Path, metavar="BASELINE.json",
                        help="print each measure beside this file's, with the ratio")
    parser.add_argument("--from", dest="sources", action="append", type=Path,
                        metavar="FILE", help="read measures from a result file "
                        "instead of running; repeatable, later files win")
    parser.add_argument("--notes", help="free text stored with the result")
    args = parser.parse_args(argv)

    if args.sources:
        doc = merge([load_document(p) for p in args.sources], args.notes)
    else:
        repeats = args.repeats or (2 if args.quick else 5)
        groups = args.only or list(GROUPS)
        header = run_header({"repeats": repeats, "groups": groups})
        print(f"timing {', '.join(groups)} at {header['commit'][:10] or 'unknown commit'}"
              f", {repeats} samples each", file=sys.stderr)
        measures = run_measures(
            all_measures(groups), repeats,
            echo=lambda *a, **k: print(*a, **k, file=sys.stderr))
        doc = {"schema": SCHEMA, "notes": args.notes or "", "runs": [header],
               "measures": measures}

    if args.out:
        args.out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        print(f"written to {args.out}", file=sys.stderr)
    if args.compare:
        print_comparison(doc, load_document(args.compare))
    else:
        print_table(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
