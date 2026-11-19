"""Pumping tests: the spread and diagnostics (PLAN.md step 3.2), sheets at
the edges of what the reader takes, time cells, and the step test analysed
with typed discharges - the "pumping_spread", "pumping_cases", "time_cells"
and "step_analysis" entries of ``reference.json``.

``pc_tolerated``, which ``--check`` reads a badly fitting large-diameter
fit's numbers with, is in ``common.py``.
"""

from __future__ import annotations

import json
import math

import numpy as np

from groundwater.hydraulics import analyse_pumping_test, test_type_text
from groundwater.ingestion import read_pumping_workbook

from .common import clean, DATA, flags


# ------------------------------------- pumping spread and diagnostics (step 3.2)

def _large_diameter_grid() -> list[list]:
    """Dr Timbo's sheet rewritten as a thirty-minute test on a borehole whose
    casing holds most of what is pumped (T = 0.3 m2/day): every fit is
    disqualified and the Papadopulos-Cooper fit is adopted."""
    from groundwater.hydraulics.spread import pc_model
    from groundwater.ingestion import common

    grid, _ = common.load_grid(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    grid = json.loads(json.dumps(grid, default=str))
    for row in grid[11:]:
        for c in range(15):
            row[c] = None
    grid[4][4], grid[5][1], grid[5][4], grid[8][2] = 60, 5.0, 50, 1.0
    times = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30]
    drawdown = pc_model(24.0, 0.1, 0.0615)(
        np.array(times[1:], float) / 1440.0, math.log10(0.3), -3.0)
    levels = [5.0] + [round(5.0 + float(s), 2) for s in drawdown]
    for i, (t, level) in enumerate(zip(times, levels, strict=True)):
        grid[11 + i][0], grid[11 + i][1] = t, level
    for i, t in enumerate([0, 1, 2, 3, 4, 5, 10, 15, 20, 30]):
        grid[11 + i][12] = t
        grid[11 + i][13] = round(levels[-1] - 0.05 * math.log1p(t), 2)
    return grid


def _wide_band_grid() -> list[list]:
    """An hour's test whose readings scatter by up to three metres about a
    straight line on log time: the Theis fit is adopted, two resamples fail,
    and the band is too wide for the safety factor, so the rate is not called
    sustainable."""
    from groundwater.ingestion import common

    grid, _ = common.load_grid(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    grid = json.loads(json.dumps(grid, default=str))
    for row in grid[11:]:
        for c in range(15):
            row[c] = None
    grid[4][4], grid[5][1], grid[5][4], grid[8][2] = 60, 5.0, 50, 2.0
    times = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60]
    wobble = [0, 0.1, -0.2, 0.15, -0.1, 0.3, -0.4, 0.5, -0.3, 0.6, -0.5, 0.7, -0.6,
              0.8, -0.7, 0.9, -0.2]
    for i, t in enumerate(times):
        s = 0.0 if t == 0 else 1.2 * math.log10(t) + 2.0 + 3.5 * wobble[i]
        grid[11 + i][0], grid[11 + i][1] = t, round(5.0 + s, 2)
    return grid


def _spread_summary(analysis) -> dict:
    """What step 3.2 adds to an analysis, as parity.mjs reads it back."""
    from groundwater.hydraulics.spread import (
        diagnostic_text,
        papadopulos_cooper_text,
        spread_paragraphs,
        sustainable_sentence,
    )

    th, pc, sp, dg = (analysis.theis, analysis.papadopulos_cooper, analysis.spread,
                      analysis.diagnostic)
    boot = sp.bootstrap if sp else None
    rec = analysis.yield_recommendation
    return clean({
        "source": analysis.transmissivity_source,
        "T": analysis.transmissivity_m2_per_day,
        "theis": [th.transmissivity_m2_per_day, th.transmissivity_low_m2_per_day,
                  th.transmissivity_high_m2_per_day] if th else None,
        "pc": [pc.transmissivity_m2_per_day, pc.storativity, pc.alpha, pc.rmse_m,
               pc.transmissivity_low_m2_per_day, pc.transmissivity_high_m2_per_day]
              if pc else None,
        "pc_invalid": analysis.papadopulos_cooper_invalid,
        "boot": {k: getattr(boot, k) for k in (
            "method", "replicates", "failed", "block_length", "seed", "n_points",
            "p10", "p50", "p90", "reason")} if boot else None,
        "spread": [sp.safe_yield_low_m3_per_h, sp.safe_yield_high_m3_per_h,
                   sp.long_term_low_m3_per_h, sp.holds_at_dry_season,
                   sp.pump_depth_low_m, sp.pump_depth_high_m] if sp else None,
        "diagnostic": {
            "t": dg.derivative_time_min, "d": dg.derivative_m, "slopes": dg.slopes,
            "regimes": [[r.key, r.start_min, r.end_min, r.slope, r.n_points]
                        for r in dg.regimes],
            "plateau": dg.plateau_transmissivity_m2_per_day,
        } if dg else None,
        "safe": rec.safe_yield_m3_per_h if rec else None,
        "range_text": rec.yield_range_text if rec else None,
        "confidence": rec.confidence if rec else None,
        "text": spread_paragraphs(analysis) + [
            diagnostic_text(dg), papadopulos_cooper_text(analysis),
            sustainable_sentence(rec, sp) or ""],
    })


def _regime_curves() -> dict:
    """Synthetic drawdowns with one regime each, as minutes and metres."""
    from scipy.special import exp1

    from groundwater.hydraulics.spread import pc_model

    t = np.geomspace(0.5, 3000, 45)

    def theis(radius=0.1):
        u = radius**2 * 1e-3 / (4 * 5.0 * t / 1440)
        return 48.0 / (4 * math.pi * 5.0) * exp1(u)

    return {
        "radial": theis(),
        "storage": pc_model(48.0, 0.1, 0.0615)(t / 1440, math.log10(0.5), -3.0),
        "linear": 0.3 * np.sqrt(t),
        "recharge": theis() - theis(60.0),
        "barrier": theis() + theis(60.0),
    }, t


def pumping_spread_reference() -> dict:
    """The bands, the derivative and the large-diameter fit, in both engines.

    The generator's stream, the Bessel functions and the well function are
    compared value for value; each pumping sheet's analysis is compared
    through _spread_summary, its sentences word for word.
    """
    from types import SimpleNamespace

    from scipy.special import k0e, k1e

    from groundwater.hydraulics.spread import (
        Mulberry32,
        block_length,
        diagnose,
        pc_well_function,
        quantile,
    )
    from groundwater.ingestion.pumping import _assemble

    out: dict = {}
    streams = {}
    for seed in (1, 32, 4294967295):
        rng = Mulberry32(seed)
        streams[str(seed)] = [rng.next_float() for _ in range(50)]
    out["mulberry32"] = streams
    out["blocks"] = [[n, block_length(n)] for n in (1, 5, 8, 9, 26, 27, 28, 64, 65, 125)]
    values = [3.0, 1.0, 4.0, 1.5, 9.0, 2.6, 5.35]
    out["quantile"] = {"values": values,
                       "q": [[q, quantile(values, q)] for q in (0, 0.1, 0.25, 0.5, 0.9, 1)]}
    out["bessel"] = [[x, float(k0e(x)), float(k1e(x))]
                     for x in (1e-6, 0.01, 0.5, 1.999, 2.0, 2.001, 7.5, 40.0, 900.0)]
    out["well_function"] = [[u, a, pc_well_function(u, a)]
                            for a in (1e-1, 1e-3, 1e-5) for u in (1.0, 1e-2, 1e-4, 1e-6)]

    curves, t = _regime_curves()
    regimes = {}
    for name, s in curves.items():
        test = SimpleNamespace(static_water_level_m=0.0, steps=[SimpleNamespace(
            time_min=t, water_level_m=np.asarray(s), discharge_m3_per_h=2.0)])
        dg = diagnose(SimpleNamespace(test=test))
        regimes[name] = {
            "t": clean(t), "s": clean(np.asarray(s)),
            "regimes": clean([[r.key, r.start_min, r.end_min, r.slope, r.n_points]
                              for r in dg.regimes]),
            "plateau": clean(dg.plateau_transmissivity_m2_per_day),
        }
    out["regimes"] = regimes

    from groundwater.ingestion import common

    # the edge sheets travel in pumping_cases already; parity reads them there.
    # The audit's sheets are not about the bands, and their readings are clean
    # Theis curves with no casing storage in them, which leave the
    # large-diameter fit's storativity running off down its valley to 1e-22
    # or 1e-78, where the engines stop 1 percent apart: they are held in
    # pumping_cases alone.
    audit = _audit_case_grids()
    edge = {name: grid for name, grid in _pumping_case_grids().items() if name not in audit}
    timbo, _ = common.load_grid(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    own = {"dr_timbo": json.loads(json.dumps(timbo, default=str)),
           "large_diameter": _large_diameter_grid(),
           "wide_band": _wide_band_grid()}
    cases = {}
    for name, grid in list(own.items()) + list(edge.items()):
        test = _assemble(grid, f"{name}.xlsx")
        cases[name] = {"grid": json.dumps(grid) if name in own else None,
                       **_spread_summary(analyse_pumping_test(test))}
    out["cases"] = cases
    return out


# ------------------------------------------------- pumping sheets at the edges

def _pumping_case_grids() -> dict[str, list[list]]:
    """The bundled pumping sheets with the cells rewritten that each
    hydraulics defect turned on: a recovery line that misses the origin, a
    level below the pump, a hole too shallow for the intake the test implies,
    hourly blocks read every few minutes, step times that restart, short
    steps inside the casing-storage period. Row 4 carries the borehole depth
    and row 5 the static level and pump setting in column 4 and 1; row 8 the
    step discharges; row 9 the block headings; readings start on row 11."""
    from groundwater.ingestion import common

    def grid_of(path):
        grid, _ = common.load_grid(path)
        return json.loads(json.dumps(grid, default=str))

    def copy(grid):
        return json.loads(json.dumps(grid))

    def clear_readings(grid):
        for row in grid[11:]:
            for c in range(15):
                row[c] = None

    timbo = grid_of(DATA / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    kuntolo = grid_of(DATA / "kuntolo" / "kuntolo_step_test.xlsx")
    swl = 9.44
    cases: dict[str, list[list]] = {}

    # the recovery on a clean line meeting t/t' = 1 at 20 m, beside fits that
    # are all disqualified; then with too few readings for any drawdown fit
    rejected = copy(timbo)
    for i, t_prime in enumerate([0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 45,
                                 50, 55, 60]):
        rejected[11 + i][13] = (42.26 if t_prime == 0 else round(
            swl + 20.0 + 9.0 * math.log10((30 + t_prime) / t_prime), 2))
    cases["rejected_recovery"] = rejected
    alone = copy(rejected)
    for row in alone[15:]:
        row[0] = row[1] = row[2] = None
    cases["every_fit_rejected"] = alone

    # the recovery line meeting t/t' = 1 below zero
    negative = copy(timbo)
    for i, t_prime in enumerate([0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 45,
                                 50, 55, 60]):
        negative[11 + i][13] = (42.26 if t_prime == 0 else round(
            swl - 8.0 + 20.0 * math.log10((30 + t_prime) / t_prime), 2))
    cases["negative_intercept"] = negative

    # the pump written at 15 m, 27 m above the deepest level recorded
    below_pump = copy(timbo)
    below_pump[5][4] = 15
    cases["level_below_pump"] = below_pump

    # a 45.5 m hole with the pump at 44 m
    shallow = copy(timbo)
    shallow[4][4] = 45.5
    shallow[5][4] = 44
    cases["shallow_hole"] = shallow

    # four hours in hourly blocks, hours two to four read every 5, 10 and 15
    # minutes and counted within the hour
    blocks = copy(timbo)
    clear_readings(blocks)
    for b, (start, times) in enumerate([
            (0, [0, 1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 40, 50, 60]),
            (60, [5, 10, 15, 20, 25, 30, 40, 50, 60]),
            (120, [10, 20, 30, 40, 50, 60]), (180, [15, 30, 45, 60])]):
        for i, t in enumerate(times):
            blocks[11 + i][3 * b] = t
            blocks[11 + i][3 * b + 1] = round(
                swl + (0 if start + t == 0 else 3.0 * math.log10(start + t) + 5.0), 2)
    cases["blocks_by_heading"] = blocks

    # Kuntolo with its discharges, each step's time counted from its own start
    restart = copy(kuntolo)
    restart[8][2], restart[8][5], restart[8][8] = 1.5, 2.2, 3.0
    for row in restart[11:]:
        for col, offset in ((3, 60), (6, 120)):
            if isinstance(row[col], (int, float)):
                row[col] = row[col] - offset
    cases["step_restart"] = restart

    # three 50-minute steps, every one inside an 80-minute casing storage
    short = copy(kuntolo)
    short[2][4] = 50
    short[5][1] = 10.0
    short[8][2], short[8][5], short[8][8] = 1.0, 2.0, 3.0
    clear_readings(short)
    rates = [1.0, 2.0, 3.0]

    def drawdown(t):
        s = 0.0
        for i, q in enumerate(rates):
            if t > 50 * i:
                dq = q - (rates[i - 1] if i else 0.0)
                s += 2.303 * dq * 24 / (4 * math.pi * 2.5) * math.log10(
                    2.25 * 2.5 * ((t - 50 * i) / 1440) / (0.01 * 1e-3))
        q = rates[min(int((t - 1e-9) // 50), 2)]
        return s + 0.002 * (q * 24) ** 2 / 24

    for k in range(3):
        for i, t in enumerate([1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50]):
            short[11 + i][3 * k] = 50 * k + t
            short[11 + i][3 * k + 1] = round(10.0 + drawdown(50 * k + t), 2)
    cases["short_steps"] = short
    cases.update(_audit_case_grids())
    return cases


def _audit_sheet(blocks, *, recovery=None, headings=None, step_length=None,
                 rates=(2.0,), test_type="constant", pump=45.0, time_head="Time (min)",
                 recovery_head="Time (min)", extra=()) -> list[list]:
    """A pumping sheet as the template lays one out, from ``blocks`` of
    (time, level) side by side and a recovery block: the static level 10 m,
    the hole 60 m deep, the step rates in row 4 and the readings from row 7."""
    rows = [["PUMPING TEST FIELD SHEET"],
            ["Community", "Test", None, "Static water level (m)", 10.0],
            ["Depth of Borehole (m)", 60.0, None, "Pump setting (m)", pump],
            ["Test type (step or constant)", test_type, None,
             "Length of each step (min)", step_length]]
    q_row = ["Discharge per step (m3/h)"]
    for i, q in enumerate(rates):
        q_row += [f"Step {i + 1} Q", q, None]
    rows.append(q_row)
    rows += [list(row) for row in extra]
    groups = list(blocks) + ([recovery] if recovery is not None else [])
    heads = list(headings or [None] * len(groups))
    rows.append(sum(([h, None, None] for h in heads), []))
    header = []
    for _ in blocks:
        header += [time_head, "Water Level (m)", "Drawdown (m)"]
    if recovery is not None:
        header += [recovery_head, "Water Level (m)", "Recovery (m)"]
    rows.append(header)
    for i in range(max(len(g) for g in groups)):
        row = []
        for g in groups:
            row += [g[i][0], g[i][1], None] if i < len(g) else [None, None, None]
        rows.append(row)
    width = max(len(r) for r in rows)
    return [r + [None] * (width - len(r)) for r in rows]


def _audit_case_grids() -> dict[str, list[list]]:
    """The sheets the audit of the pumping test reader and analysis turned
    on: times written as clocks (in rows out of order too), a time of day, a
    recovery in two blocks and
    one on the test's clock, the step length in hours, blank and unreadable,
    a last step with no rate, the casing on the sheet (with no unit, no
    wider than its riser, and with the riser left blank above another
    label), a Theis drawdown, a flattened one and a step test whose last
    step flattens, a handpump line
    Cooper-Jacob used to refuse, and a yield under 0.01 m3/h."""
    from scipy.special import exp1

    def theis(t, T, q, S=1e-3, r=0.1):
        u = r * r * S / (4 * T * (t / 1440.0))
        return q * 24 / (4 * math.pi * T) * float(exp1(u))

    def steps_of(times, rates, T, loss=0.002):
        """Superposed Theis drawdown of a step test whose steps begin every
        ``len`` minutes, with C Q^2 of well loss."""
        length = times[-1]
        out = []
        for k in range(len(rates)):
            block = []
            for m in times:
                t = length * k + m
                s = sum(theis(t - length * i, T, q - (rates[i - 1] if i else 0.0))
                        for i, q in enumerate(rates[:k + 1]))
                block.append((t, round(10.0 + s + loss * (rates[k] * 24) ** 2 / 24, 3)))
            out.append(block)
        return out

    day = [1, 2, 3, 5, 8, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 360, 480, 600,
           720, 840, 960, 1080, 1200, 1320, 1380, 1440]
    eight = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 80, 100, 120,
             150, 180, 210, 240, 300, 360, 420, 480]
    since = [1, 2, 3, 5, 10, 20, 30, 45, 60]
    cases: dict[str, list[list]] = {}

    def recovery_after(stop, T, q, minutes=since, offset=0.0):
        return [(offset + m, round(10.0 + theis(stop + m, T, q) - theis(m, T, q), 3))
                for m in minutes]

    def clock(m, seconds=True):
        return (f"{int(m) // 60:02d}:{int(m) % 60:02d}:00" if seconds
                else f"{int(m) // 60}:{int(m) % 60:02d}")

    # an eight-hour test with every reading from the first hour on in a clock
    # cell, as the browser's reader writes one, and minute 90 typed as 1:30
    levels = [(m, round(10.0 + theis(m, 20.0, 2.0), 3)) for m in eight]
    cases["clock_cells"] = _audit_sheet(
        [[(clock(m, seconds=m != 90) if m >= 60 else m, wl) for m, wl in levels]],
        recovery=recovery_after(480, 20.0, 2.0))
    # a column that names its clock as minutes and seconds
    cases["clock_minutes_seconds"] = _audit_sheet(
        [[(f"{int(m)}:{int(round(m % 1 * 60)):02d}", round(10.0 + theis(m, 20.0, 2.0), 3))
          for m in (0.5, 1, 1.5, 2, 3, 5, 7.5, 10, 15, 20, 30)]],
        time_head="Time (mm:ss)")
    # the clock on the wall
    cases["time_of_day"] = _audit_sheet(
        [[(f"08:{m:02d}", round(10.0 + theis(m - 4, 20.0, 2.0), 3))
          for m in (5, 6, 7, 9, 14, 24, 34, 49, 59)]],
        recovery=recovery_after(55, 20.0, 2.0))
    # elapsed clocks in rows out of order, the top one past the first hour
    cases["clock_rows_out_of_order"] = _audit_sheet(
        [[(clock(m, seconds=False), round(10.0 + theis(m, 20.0, 2.0), 3))
          for m in (90, 5, 60, 1, 240, 30, 120, 10, 180, 2)]])
    # four hours and a two-hour recovery in two hourly blocks, the second
    # counted within its own hour
    four = [(m, round(10.0 + theis(m, 20.0, 2.0), 3)) for m in eight if m <= 240]
    first = recovery_after(240, 20.0, 2.0)
    second = recovery_after(240, 20.0, 2.0, minutes=[65, 70, 80, 90, 105, 120],
                            offset=-60.0)
    grid = _audit_sheet([four, first], headings=["Constant discharge 0-240 min",
                                                 "Recovery 0-60 min"])
    grid[5] += ["Recovery 61-120 min", None, None]
    grid[6] += ["Time (min)", "Water Level (m)", "Recovery (m)"]
    for i, row in enumerate(grid[7:]):
        row += [second[i][0], second[i][1], None] if i < len(second) else [None] * 3
    for row in grid[:5]:
        row += [None] * 3
    cases["recovery_blocks"] = grid
    # the recovery written on with the test's clock
    cases["recovery_test_clock"] = _audit_sheet(
        [four], recovery=recovery_after(240, 20.0, 2.0, offset=240.0))
    # four steps of an hour, the length written in hours
    hourly = steps_of([1, 2, 3, 5, 10, 15, 20, 30, 45, 60], [1.0, 2.0, 3.0, 4.0], 15.0)
    cases["step_length_hour"] = _audit_sheet(
        hourly, step_length="1 hr", rates=(1.0, 2.0, 3.0, 4.0), test_type="step",
        recovery=recovery_after(240, 15.0, 4.0))
    # four steps of 100 minutes with the length left blank, and unreadable
    hundred = steps_of([1, 2, 3, 5, 10, 20, 30, 45, 60, 80, 100], [1.0, 2.0, 3.0, 4.0], 15.0)
    cases["step_length_blank"] = _audit_sheet(
        hundred, rates=(1.0, 2.0, 3.0, 4.0), test_type="step")
    cases["step_length_unreadable"] = _audit_sheet(
        hundred, step_length="1 fortnight", rates=(1.0, 2.0, 3.0, 4.0), test_type="step")
    # the last rate blank, with a recovery that needs it
    cases["last_rate_missing"] = _audit_sheet(
        hundred, step_length=100, rates=(1.0, 2.0, 3.0, None), test_type="step",
        recovery=recovery_after(400, 15.0, 4.0))
    # the casing and riser a co-pilot writes, and a diameter with no unit
    copilot = [[None] * 16 + ["Casing diameter (in)", 8],
               [None] * 16 + ["Riser diameter (in)", "50 mm"]]
    cases["sheet_casing"] = _audit_sheet(
        [[(m, round(10.0 + theis(m, 5.0, 2.0), 3)) for m in eight]], extra=copilot)
    cases["bare_casing"] = _audit_sheet(
        [[(m, round(10.0 + theis(m, 5.0, 2.0), 3)) for m in eight]],
        extra=[["Casing diameter", 6]])
    cases["swapped_casing"] = _audit_sheet(
        [[(m, round(10.0 + theis(m, 5.0, 2.0), 3)) for m in eight]],
        extra=[[None] * 16 + ["Casing diameter (in)", 2],
               [None] * 16 + ["Riser diameter (in)", 5]])
    # the co-pilot's riser left blank, its planned rate standing under it
    cases["blank_riser"] = _audit_sheet(
        [[(m, round(10.0 + theis(m, 5.0, 2.0), 3)) for m in eight]],
        extra=[[None] * 16 + ["Casing diameter (in)", 8],
               [None] * 16 + ["Riser diameter (in)", None],
               [None] * 16 + ["Planned rate (m3/h)", 2.93]])
    # a day at 2 m3/h in 10 m2/day, its last readings an hour apart within 5 cm
    cases["theis_day"] = _audit_sheet(
        [[(m, round(10.0 + theis(m, 10.0, 2.0), 2)) for m in day]], pump=50.0)
    # Theis to two hours, then 1.5 cm a log cycle
    flattened = []
    for m in day:
        s = theis(min(m, 120), 20.0, 3.0) + (0.015 * math.log10(m / 120) if m > 120 else 0.0)
        flattened.append((m, round(10.0 + s, 3)))
    cases["stabilised_tail"] = _audit_sheet([flattened], rates=(3.0,), pump=50.0)
    # a step test whose second step flattens after an hour of its own clock
    own = [1, 2, 3, 5, 8, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240]
    step_one = [round(theis(m, 20.0, 1.5), 3) for m in own]
    step_two = [round(step_one[-1] + theis(min(m, 60), 20.0, 1.5)
                      + (0.002 * math.log10(m / 60) if m > 60 else 0.0), 3) for m in own]
    cases["stabilised_last_step"] = _audit_sheet(
        [[(m, 10.0 + s) for m, s in zip(own, step_one, strict=True)],
         [(240 + m, 10.0 + s) for m, s in zip(own, step_two, strict=True)]],
        rates=(1.5, 3.0), test_type="step", step_length=240, pump=50.0)
    # a handpump in 250 m2/day, levels to the millimetre
    cases["handpump_line"] = _audit_sheet(
        [[(m, round(10.6 + theis(m, 250.0, 1.0), 3)) for m in eight]], rates=(1.0,),
        pump=50.0)
    # 0.05 m3/h in 0.2 m2/day with 0.7 m of drawdown to spend
    cases["low_yield"] = _audit_sheet(
        [[(m, round(10.0 + theis(m, 0.2, 0.05), 3)) for m in eight if m <= 240]],
        rates=(0.05,), pump=16.0)
    return cases


#: Time cells as a sheet holds them, each with the column header it sits
#: under: clocks, a clock under a header that names minutes and seconds, a
#: clock past a day, text that starts as a clock and is not one, hours and
#: minutes as words, numbers with a unit or a note in the cell, and an
#: Excel TRUE.
TIME_CELLS = [
    ("1:30", "Time (min)"), ("01:30:00", "Time (min)"), ("00:05:00", "Time (min)"),
    ("01:30:00.500000", "Time (min)"), ("100:00", "Time (min)"), (" 2:05 ", "Time (h)"),
    ("5:30", "Time (mm:ss)"), ("5:30", "Time (min:sec)"), ("00:05:30", "Time (mm:ss)"),
    ("90:30", "Time (m:s)"), ("5:30", "Time (hh:mm)"), ("1:5", "Time (min)"),
    ("1:60", "Time (min)"), ("12 min", "Time (min)"), ("1 hr", "Time (min)"),
    ("5 (approx)", "Time (min)"), ("1 fortnight", "Time (min)"), (45, "Time (h)"),
    (90, "Time (min)"), ("", "Time (min)"), ("n/a", "Time (min)"),
    ("1:30 pm", "Time (min)"), ("08:05 AM", "Time (min)"), ("10:00 (approx)", "Time (min)"),
    ("1: 30", "Time (min)"), ("-1:30", "Time (min)"), ("1000:00", "Time (min)"),
    ("1h 30m", "Time (min)"), ("1 hr 30 min", "Time (min)"), ("1h30", "Time (min)"),
    ("2 h", "Time (min)"), ("1.30", "Time (min)"), ("1:30 ", "Time (min)"),
    (True, "Time (min)"),
]


def time_cells_reference() -> list:
    """What the readers make of each of TIME_CELLS (units.read_time)."""
    from groundwater.units import clock_format, read_time

    out = []
    for cell, header in TIME_CELLS:
        quantity, written = read_time(cell, header)
        out.append({"cell": cell, "header": header, "format": clock_format(header),
                    "value": clean(quantity.value), "status": quantity.status,
                    "unit": quantity.unit_text, "written": written})
    return out


def pumping_cases() -> dict:
    """What Python makes of each edge sheet, with the sheet itself.

    The grid travels as a JSON string so the browser parses exactly the cells
    Python parsed; the rest is compared quantity by quantity, the prose word
    for word."""
    from groundwater.ingestion.pumping import _assemble
    from groundwater.models import step_offsets_min

    out = {}
    for name, grid in _pumping_case_grids().items():
        test = _assemble(grid, f"{name}.xlsx")
        analysis = analyse_pumping_test(test)
        rec = analysis.yield_recommendation
        out[name] = {
            "grid": json.dumps(grid),
            "steps": [[s.step_number, clean(s.discharge_m3_per_h), len(s.time_min),
                       clean(float(np.min(s.time_min))), clean(float(np.max(s.time_min)))]
                      for s in test.steps],
            "duration": clean(test.pumping_duration_min),
            "offsets": step_offsets_min(test.steps),
            "source": analysis.transmissivity_source,
            "qualifies": analysis.adopted_fit()[2],
            "disqualified": sorted(analysis.disqualified),
            "invalid": sorted(analysis.invalid_fits),
            "T": clean(analysis.transmissivity_m2_per_day),
            "safe": clean(rec.safe_yield_m3_per_h),
            "range_text": rec.yield_range_text,
            "pump_depth": clean(rec.pump_installation_depth_m),
            "confidence": rec.confidence,
            "confidence_reasons": list(rec.confidence_reasons),
            "pending_reason": rec.pending_reason,
            "pump_depth_basis": rec.pump_depth_basis,
            "envelope_basis": rec.envelope_basis,
            "rec_pumping_time": clean(analysis.recovery.pumping_time_min)
                                if analysis.recovery else None,
            "step_numbers": [s["step"] for s in analysis.step_test.steps]
                            if analysis.step_test else None,
            "flags": flags(analysis.flags),
            # what the audit of the reader and the analysis moved
            "step_length": clean(test.step_length_min),
            "recovery": None if test.recovery_time_min is None else [
                len(test.recovery_time_min), clean(float(np.min(test.recovery_time_min))),
                clean(float(np.max(test.recovery_time_min)))],
            "residual_end": clean(analysis.recovery.residual_at_end_m)
                            if analysis.recovery else None,
            "stabilised": clean(analysis.stabilised_level_m),
            "casing_in": clean(analysis.casing_diameter_in),
            "riser_in": clean(analysis.riser_diameter_in),
            "casing_min": clean(analysis.casing_storage_min),
            "long_term": clean(rec.long_term_yield_m3_per_h),
        }
    return out


def fill_step_analysis(out: dict) -> None:
    """Fill "step_analysis": the Kuntolo step test, analysed with typed discharges.

    It fills ``out`` in place, where build() calls it: build.py says why."""
    # The step test with the discharges an analyst would type in: the first
    # step ends above static and gets no drawdown fit, the recovery is read
    # against an equivalent time, and the two-step Hantush-Bierschenk line
    # says it is exact by construction.
    step_q = read_pumping_workbook(DATA / "kuntolo" / "kuntolo_step_test.xlsx")
    for step, q in zip(step_q.steps, (1.5, 2.2, 3.0), strict=True):
        step.discharge_m3_per_h = q
    step_analysis = analyse_pumping_test(step_q)
    step_rec = step_analysis.yield_recommendation
    out["step_analysis"] = {
        "T": clean(step_analysis.transmissivity_m2_per_day),
        "source": step_analysis.transmissivity_source,
        "qualifies": step_analysis.adopted_fit()[2],
        "cj": clean(step_analysis.cooper_jacob.transmissivity_m2_per_day)
              if step_analysis.cooper_jacob else None,
        "theis": clean(step_analysis.theis.transmissivity_m2_per_day)
                 if step_analysis.theis else None,
        "rec": clean(step_analysis.recovery.transmissivity_m2_per_day)
               if step_analysis.recovery else None,
        "rec_pumping_time": clean(step_analysis.recovery.pumping_time_min)
                            if step_analysis.recovery else None,
        "rec_equivalent": step_analysis.recovery.equivalent_time
                          if step_analysis.recovery else None,
        "B": clean(step_analysis.step_test.aquifer_loss_B) if step_analysis.step_test else None,
        "C": clean(step_analysis.step_test.well_loss_C) if step_analysis.step_test else None,
        "two_point": step_analysis.step_test.two_point if step_analysis.step_test else None,
        "safe": clean(step_rec.safe_yield_m3_per_h),
        "pump_depth": clean(step_rec.pump_installation_depth_m),
        "confidence": step_rec.confidence,
        "confidence_reasons": list(step_rec.confidence_reasons),
        "pump_depth_basis": step_rec.pump_depth_basis,
        "specific_capacity_basis": step_rec.specific_capacity_basis,
        "flags": [[f.level, f.code] for f in step_analysis.flags],
        "type_text": test_type_text(step_q.test_type),
        # the sheet's own step numbers, not a count of the steps that fitted
        "step_numbers": [s["step"] for s in step_analysis.step_test.steps]
                        if step_analysis.step_test else None,
    }
