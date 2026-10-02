"""Field sheets as a crew fills them in, generated for the fuzz suite.

Each strategy draws a *case*: a kind, the cells of one workbook laid out in
the template the readers expect (``groundwater.ingestion.templates`` and the
sample workbooks under ``examples/data``), and the options the analysis is
run with. The values are plausible rather than arbitrary - resistivity
curves come from the forward model of a layered earth, drawdowns from the
Theis solution with well loss - and the cells carry the things real sheets
carry: numbers typed as text with leading zeros or a decimal comma, units
written into the cell, non-detects, blank rows, dates where text was meant,
clocks restarted at every step.

A case is plain JSON (``to_json``), so a counterexample can be committed
under ``tests/fuzz/regressions`` and read by a person; ``workbook_bytes``
turns its cells into the .xlsx both engines read.
"""

from __future__ import annotations

import datetime
import io
import math

import numpy as np
from hypothesis import strategies as st
from openpyxl import Workbook

# ------------------------------------------------------------------ cells

# A date or a clock time cannot travel in JSON as itself; it is written as a
# one-key object and turned back into the cell type when the workbook is made.


def date_cell(value: datetime.datetime) -> dict:
    return {"date": value.isoformat()}


def time_cell(hour: int, minute: int) -> dict:
    return {"time": f"{hour:02d}:{minute:02d}"}


def _cell(value):
    if isinstance(value, dict):
        if "date" in value:
            return datetime.datetime.fromisoformat(value["date"])
        if "time" in value:
            h, m = value["time"].split(":")
            return datetime.time(int(h), int(m))
        raise ValueError(f"unknown cell {value!r}")
    return value


def workbook_bytes(sheets: list[dict]) -> bytes:
    """The .xlsx for ``[{"name": ..., "rows": [[cell, ...], ...]}, ...]``."""
    wb = Workbook()
    wb.remove(wb.active)
    for sheet in sheets:
        ws = wb.create_sheet(sheet["name"])
        for r, row in enumerate(sheet["rows"], start=1):
            for c, value in enumerate(row, start=1):
                if value is not None:
                    ws.cell(row=r, column=c, value=_cell(value))
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _place(rows: list[list], r: int, c: int, value) -> None:
    while len(rows) <= r:
        rows.append([])
    row = rows[r]
    while len(row) <= c:
        row.append(None)
    row[c] = value


def _rectangular(rows: list[list]) -> list[list]:
    width = max((len(r) for r in rows), default=0)
    return [r + [None] * (width - len(r)) for r in rows]


# ------------------------------------------------------- how a number is typed

def chance(draw, p: float) -> bool:
    """True with probability ``p``, and False once Hypothesis has shrunk it.

    Hypothesis shrinks a float towards 0, so the rare branch is taken at the
    top of the range: a shrunk counterexample keeps only the oddities it
    needs, and reads like an ordinary sheet otherwise.
    """
    return draw(st.floats(0, 1)) > 1 - p


def rare_first(draw) -> float:
    """A uniform draw for a ladder whose first rungs are the rare branches;
    it shrinks to 1, past every rung, to the ordinary case."""
    return 1.0 - draw(st.floats(0, 1))

def typed(draw, value: float, digits: int = 2, text_rate: float = 0.25):
    """A number as a crew types it: mostly a number, sometimes text.

    Text keeps leading zeros ("078.7"), a decimal comma ("1,5"), a unit
    against the number ("80m") or stray spaces, all of which the readers
    have to take as the number.
    """
    value = round(float(value), digits)
    if value == int(value) and draw(st.booleans()):
        value = int(value)
    if not chance(draw, text_rate):
        return value
    style = draw(st.sampled_from(["plain", "zero", "comma", "unit", "space"]))
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".") if digits else str(int(value))
    if style == "zero" and value < 1000:
        return "0" + text
    if style == "comma":
        return text.replace(".", ",")
    if style == "unit":
        return text + draw(st.sampled_from(["m", " m", "M"]))
    if style == "space":
        return " " + text + " "
    return text


# ------------------------------------------------------------- header blocks

COMMUNITIES = ["Rokel", "Kuntoloh", "Dr. Timbo's Residence", "Mile 91", "Ma-Ama",
               "Koidu – Kono", " Lungi ", "Bo", "Kamakwie", "Ñ village"]
DISTRICTS = ["Port Loko", "Western Area Rural", "Bo", "Karene", "Falaba",
             "western area", "Port Loko District", "Kono", "Atlantis", "", "Ko",
             "Western Area"]
CLIENTS = ["Living Water International", "ACF", "Dr. Timbo", "UNICEF", "", "Ministry"]
PEOPLE = ["WiNGiN", "M. Kamara", "Field Supervisor", "", "A. B. Sesay"]


@st.composite
def site_values(draw) -> dict:
    """Header values a sheet carries, some missing, some typed oddly."""
    out: dict = {}
    if draw(st.booleans()):
        out["Client"] = draw(st.sampled_from(CLIENTS))
    out["Community"] = draw(st.sampled_from(COMMUNITIES))
    out["District"] = draw(st.sampled_from(DISTRICTS))
    if draw(st.booleans()):
        east = draw(st.integers(160_000, 820_000))
        north = draw(st.integers(780_000, 1_100_000))
        out["GPS Coordinate East"] = draw(st.sampled_from(
            [east, f"0{east}", east + 0.5, f"{east}"]))
        out["GPS Coordinate North"] = draw(st.sampled_from(
            [north, f"0{north}", north + 0.25, f"{north} m"]))
        out["UTM Zone (28N or 29N)"] = draw(st.sampled_from(
            ["28N", "29N", 28, 29, "Zone 28", "28 N", "", "29P", "28/29"]))
    if draw(st.booleans()):
        out["Elevation (m)"] = draw(st.sampled_from([71, "71 m", 71.5, 0, "n/a", "071"]))
    if draw(st.booleans()):
        out["Date"] = draw(st.one_of(
            st.sampled_from(["8th December, 2015", "2015-12-08", "1 Jan 2020", ""]),
            st.datetimes(datetime.datetime(2010, 1, 1), datetime.datetime(2026, 12, 31))
            .map(lambda d: date_cell(d.replace(second=0, microsecond=0))),
        ))
    if draw(st.booleans()):
        out["Chiefdom"] = draw(st.sampled_from(["Koya", "Maforki", "", "Kaffu Bullom"]))
    return out


def header_rows(draw, title: str, pairs: list[tuple[str, object]], columns: list[int],
                first_row: int = 1) -> list[list]:
    """The title and the label/value pairs, laid out as the templates do.

    ``columns`` are the label columns of each pair in a row (A and C on the
    VES sheet, A, D and G on the pumping sheet); the value sits in the next
    column. Sometimes a crew writes the pair into one cell as "Label: value".
    """
    rows: list[list] = []
    _place(rows, 0, 0, title)
    r, k = first_row, 0
    for label, value in pairs:
        c = columns[k]
        if (isinstance(value, (str, int, float)) and not isinstance(value, bool)
                and chance(draw, 0.08)):
            _place(rows, r, c, f"{label}: {value}")
        else:
            _place(rows, r, c, label)
            if value is not None and value != "":
                _place(rows, r, c + 1, value)
        k += 1
        if k == len(columns):
            k, r = 0, r + 1
    return rows


# --------------------------------------------------------------- VES sheets

SCHLUMBERGER_SPACINGS = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30,
                         40, 50, 60, 70, 80, 100, 120, 150, 200, 250, 300]
MN_STEPS = [0.2, 0.4, 0.5, 0.8, 1.0, 1.5, 2.0, 4.0, 5.0, 7.6, 10.0, 14.0, 20.0, 40.0]


@st.composite
def layered_earth(draw) -> tuple[list[float], list[float]]:
    """A layered earth of one to five layers."""
    n = draw(st.integers(1, 5))
    rho = [round(10 ** draw(st.floats(0.5, 3.8)), 1) for _ in range(n)]
    h = [round(10 ** draw(st.floats(-0.3, 1.8)), 1) for _ in range(n - 1)]
    return rho, h


def _apparent(rho, h, spacing, wenner: bool) -> np.ndarray:
    from groundwater.ves.forward import forward_schlumberger, forward_wenner

    spacing = np.asarray(spacing, dtype=float)
    if len(rho) == 1:
        return np.full(len(spacing), float(rho[0]))
    model = (np.array(rho, dtype=float), np.array(h, dtype=float))
    return forward_wenner(model, spacing) if wenner else forward_schlumberger(model, spacing)


@st.composite
def ves_sheet(draw, index: int) -> dict:
    """One VES worksheet: a header block, then No., AB/2 (or a), MN, rho."""
    wenner = chance(draw, 0.3)
    rho_model, h_model = draw(layered_earth())

    # The spread: Schlumberger spacings from a start, for as many readings as
    # the crew took - a very short spread is one to three readings.
    start = draw(st.integers(0, 6))
    count = draw(st.one_of(st.integers(1, 4), st.integers(5, 22)))
    spacings = SCHLUMBERGER_SPACINGS[start:start + count]
    if not spacings:
        spacings = [SCHLUMBERGER_SPACINGS[start]]
    if wenner:
        spacings = [round(s * 1.5, 1) if draw(st.booleans()) else s for s in spacings]
        spacings = sorted(set(spacings))

    readings: list[tuple[float, float | None]] = []   # (spacing, MN)
    if wenner:
        readings = [(s, s) for s in spacings]
    else:
        mn_i = draw(st.integers(0, 4))
        for s in spacings:
            mn = MN_STEPS[mn_i]
            # MN moves on when AB/2 has grown to a few times it; the reading
            # at the change is taken with both MN, which is the overlap
            if s >= draw(st.sampled_from([3, 5, 8, 12])) * mn and mn_i + 1 < len(MN_STEPS):
                readings.append((s, mn))
                mn_i += draw(st.integers(1, 2))
                mn_i = min(mn_i, len(MN_STEPS) - 1)
                readings.append((s, MN_STEPS[mn_i]))
            else:
                readings.append((s, mn))
    # a repeated spacing that is not an MN change: the crew read it twice
    if readings and chance(draw, 0.1):
        k = draw(st.integers(0, len(readings) - 1))
        readings.insert(k + 1, readings[k])

    true_rho = _apparent(rho_model, h_model, [s for s, _ in readings], wenner)
    noise = draw(st.sampled_from([0.0, 0.01, 0.03, 0.08]))
    values = []
    for rho in true_rho:
        jitter = draw(st.floats(-1, 1)) * noise
        if chance(draw, 0.03):
            jitter = draw(st.sampled_from([-0.5, 0.6, 1.5]))  # a misread
        values.append(max(float(rho) * (1 + jitter), 0.05))

    # The table's header row, in the wordings crews use
    tabulate_a = wenner and draw(st.booleans())
    spacing_head = (draw(st.sampled_from(["a (m)", "a", "a-spacing (m)"])) if tabulate_a
                    else draw(st.sampled_from(["AB/2 (m)", "AB/2", "AB / 2 (m)", "ab2"])))
    mn_head = None
    if not wenner or chance(draw, 0.3):
        mn_head = draw(st.sampled_from(["MN (m)", "MN (m)", "MN/2 (m)", "MN / 2 (m)", None]))
    resistance = chance(draw, 0.1)
    rho_head = (draw(st.sampled_from(["R (ohm)", "V/I (ohm)", "Resistance (ohm)"]))
                if resistance else
                draw(st.sampled_from(["Apparent Resistivity (ohm-m)", "Rho (ohm.m)",
                                      "ρa (Ω·m)", "Resistivity", "App. Res. (ohm-m)"])))
    header = ["No.", spacing_head] + ([mn_head] if mn_head else []) + [rho_head]

    # The header block
    array_field = (draw(st.sampled_from(["Schlumberger", "schlumberger array",
                                         "Wenner alpha", "Wenner", "",
                                         "Schlumberger / Wenner", "Dipole"]))
                   if chance(draw, 0.25)
                   else ("Wenner" if wenner else "Schlumberger"))
    site = draw(site_values())
    number = draw(st.sampled_from([f"VES {index + 1}", index + 1, f"A ({index + 1})",
                                   float(index) + 0.5, "", "VES 1"]))
    pairs = list(site.items()) + [("Sounding Number", number), ("Array", array_field),
                                  ("Instrument", draw(st.sampled_from(
                                      ["Syscal Junior", "ABEM SAS 1000", ""])))]
    title = draw(st.sampled_from(["SCHLUMBERGER ARRAY VES FIELD DATA", "VES FIELD DATA",
                                  "WENNER SOUNDING"]))
    rows = header_rows(draw, title, pairs, [0, 2])
    rows.append([])
    rows.append(header)

    for k, ((s, mn), rho) in enumerate(zip(readings, values, strict=True), start=1):
        if chance(draw, 0.04):
            rows.append([])          # a spacer at a segment change
        tab_s = s * 1.5 if (wenner and not tabulate_a) else s
        row = [k, typed(draw, tab_s, 1, 0.15)]
        if mn_head:
            if mn is None or (wenner and draw(st.booleans())):
                row.append(None)
            else:
                written = mn / 2 if "/" in mn_head else mn
                row.append(typed(draw, written, 2, 0.1))
        if resistance:
            from groundwater.ves.arrays import geometric_factor
            if wenner:
                k_factor = float(geometric_factor("wenner", a=s))
            else:
                k_factor = float(geometric_factor("schlumberger", ab2=s, mn=mn or 1.0))
            row.append(round(rho / k_factor, 5))
        else:
            row.append(typed(draw, rho, 1, 0.3))
        rows.append(row)
    if draw(st.booleans()):
        rows.append([])
        rows.append(["Notes: MN is the full potential electrode spacing."])
    name = draw(st.sampled_from([f"VES {index + 1}", f"V{index + 1}", f"Sheet{index + 1}"]))
    return {"name": name, "rows": _rectangular(rows)}


@st.composite
def ves_case(draw) -> dict:
    n = draw(st.integers(1, 3))
    sheets = [draw(ves_sheet(i)) for i in range(n)]
    # sheet names must differ in a workbook
    seen = set()
    for i, s in enumerate(sheets):
        if s["name"] in seen:
            s["name"] = f"{s['name']} ({i})"
        seen.add(s["name"])
    if chance(draw, 0.05):
        sheets.append({"name": "Summary", "rows": [["Summary of soundings"], ["see sheets"]]})
    return {"kind": "ves", "sheets": sheets, "options": {}}


# ----------------------------------------------------------- pumping sheets

READING_MINUTES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20, 25, 30, 35, 40,
                   45, 50, 55, 60, 70, 80, 90, 100, 120]


def _theis_drawdown(t_min: float, q_m3h: float, T: float, S: float) -> float:
    from scipy.special import exp1

    if t_min <= 0 or q_m3h <= 0:
        return 0.0
    u = 0.01 * S / (4 * T * (t_min / 1440.0))
    return q_m3h * 24.0 / (4 * math.pi * T) * float(exp1(u))


@st.composite
def pumping_case(draw) -> dict:
    """A pumping test sheet in the template's layout.

    Step tests of one to four steps and constant tests in one to four hourly
    blocks; times counted from the start of the test or restarted at every
    block; readings left out, blank rows, an unreadable reading; discharges
    in m3/h, L/s or L/min, in a note, or missing; a recovery block or none.
    """
    step = draw(st.booleans())
    nblocks = draw(st.integers(1, 4))
    length = draw(st.sampled_from([60, 60, 60, 90, 100, 120, 45]))
    T = 10 ** draw(st.floats(0, 2.7))
    S = 10 ** draw(st.floats(-4, -1.5))
    C = draw(st.sampled_from([0.0, 0.0, 1e-4, 1e-3]))
    swl = round(draw(st.floats(1, 40)), 2)
    q0 = round(draw(st.floats(0.3, 6.0)), 2)
    rates = ([round(q0 * (1 + 0.5 * i), 2) for i in range(nblocks)] if step
             else [q0] * nblocks)
    restart = draw(st.booleans())
    time_unit = draw(st.sampled_from(["min"] * 8 + ["h", "s", "hrs"]))
    scale = {"min": 1.0, "h": 1 / 60, "hrs": 1 / 60, "s": 60.0}[time_unit]

    def level(t):
        s = 0.0
        for i, q in enumerate(rates):
            if t > length * i:
                dq = q - (rates[i - 1] if i else 0.0)
                s += _theis_drawdown(t - length * i, dq, T, S)
        q = rates[min(int((t - 1e-9) // length), nblocks - 1)]
        return swl + s + C * (q * 24) ** 2

    blocks = []
    for b in range(nblocks):
        minutes = [m for m in READING_MINUTES if m <= length]
        if chance(draw, 0.3):   # a gap: readings not taken
            k = draw(st.integers(0, max(len(minutes) - 2, 0)))
            del minutes[k:k + draw(st.integers(1, 4))]
        if not minutes:
            minutes = [length]
        readings = []
        for m in minutes:
            t = length * b + m
            noise = draw(st.sampled_from([0.0, 0.0, 0.01, 0.05]))
            wl = level(t) + draw(st.floats(-1, 1)) * noise
            shown = (m if restart and b else t) * scale
            readings.append((shown, round(wl, 2)))
        blocks.append(readings)

    recovery = None
    if chance(draw, 0.6):
        stop = length * nblocks
        recovery = []
        for m in [1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30, 45, 60][:draw(st.integers(1, 13))]:
            residual = sum(
                _theis_drawdown(stop + m - length * i, (q - (rates[i - 1] if i else 0.0)),
                                T, S) for i, q in enumerate(rates)
            ) - _theis_drawdown(m, rates[-1], T, S)
            recovery.append((m * scale, round(swl + max(residual, 0.0), 2)))

    # header block, as on the template
    site = draw(site_values())
    test_type = draw(st.sampled_from(
        (["step", "Step", "step drawdown", ""] if step
         else ["constant", "Constant rate", "constant discharge", ""])))
    pairs = [("Community", site.get("Community")), ("Date", site.get("Date")),
             ("Client", site.get("Client")),
             ("Length of each step (min)", typed(draw, length, 0, 0.1)),
             ("Test conducted by", draw(st.sampled_from(PEOPLE))),
             ("Start time", draw(st.sampled_from([None, "08:00", time_cell(8, 30)]))),
             ("Borehole Ref. No.", draw(st.sampled_from(["KTL-01", "BH-1", "", 7]))),
             ("Depth of Borehole (m)", draw(st.sampled_from(
                 [None, 70, 45.5, "60m", round(swl + draw(st.floats(5, 80)), 1)]))),
             ("Static water level (m)", (None if chance(draw, 0.05)
                                         else typed(draw, swl, 2, 0.2))),
             ("Pump setting (m)", draw(st.sampled_from(
                 [None, 60, 44, round(swl + draw(st.floats(2, 60)), 1)]))),
             ("Test type (step or constant)", test_type),
             ("District", site.get("District"))]
    rows = header_rows(draw, "PUMPING TEST FIELD SHEET (STEP / CONSTANT DISCHARGE)",
                       pairs, [0, 3])
    for key, label_col in (("GPS Coordinate East", 2), ("GPS Coordinate North", 3),
                           ("UTM Zone (28N or 29N)", 4), ("Elevation (m)", 5)):
        if key in site:
            _place(rows, label_col - 1, 6, key)
            _place(rows, label_col - 1, 7, site[key])
    while len(rows) < 8:
        rows.append([])

    # the discharge row: "Step n Q" and the value beside it
    unit_head = draw(st.sampled_from(["Discharge per step (m3/h)", "Discharge per step",
                                      "Discharge per step (L/s)", "Discharge (m3/hr)"]))
    _place(rows, 8, 0, unit_head)
    head_unit = ("L/s" if "L/s" in unit_head
                 else "m3/h" if "m3" in unit_head else None)
    for i in range(4):
        _place(rows, 8, 1 + 3 * i, f"Step {i + 1} Q")
        if i >= nblocks or chance(draw, 0.12):
            continue            # not measured
        q = rates[i]
        style = draw(st.sampled_from(["head", "head", "m3/h", "L/s", "L/min", "gpm"]))
        if style == "head":
            value = round(q / 3.6, 3) if head_unit == "L/s" else round(q, 2)
            cell = typed(draw, value, 3, 0.1)
        elif style == "m3/h":
            cell = f"{q:g} m3/h"
        elif style == "L/s":
            cell = f"{q / 3.6:.2f} L/s"
        elif style == "L/min":
            cell = f"{q * 1000 / 60:.0f} L/min"
        else:
            cell = f"{q * 4.403:.1f} gpm"
        _place(rows, 8, 2 + 3 * i, cell)
    if chance(draw, 0.1):
        _place(rows, 7, 0, f"Constant Discharge of {rates[0]:g}m3/h")

    # block headings, the column headers and the readings
    time_head = f"Time ({time_unit})"
    for b in range(4):
        c0 = 3 * b
        heading = draw(st.sampled_from([
            f"Constant discharge {length * b if b == 0 else length * b + 1}-{length * (b + 1)} min",
            f"Step {b + 1}", None]))
        if heading:
            _place(rows, 9, c0, heading)
        for k, head in enumerate([time_head, "Water Level (m)", "Drawdown (m)"]):
            _place(rows, 10, c0 + k, head)
    _place(rows, 9, 12, "Recovery")
    for k, head in enumerate([time_head, "Water Level (m)", "Recovery (m)"]):
        _place(rows, 10, 12 + k, head)

    for b, readings in enumerate(blocks):
        r = 11
        previous = None
        for t, wl in readings:
            if chance(draw, 0.03):
                r += 1            # a blank row
            cell_t = round(t, 4) if time_unit != "min" else t
            odd = rare_first(draw)
            if odd < 0.02:
                cell_t = f"{cell_t} (approx)"
            elif odd < 0.03 and time_unit == "min" and t < 1440:
                # minutes typed into a cell Excel formats as a clock
                cell_t = time_cell(int(t) // 60, int(t) % 60)
            _place(rows, r, 3 * b, cell_t)
            _place(rows, r, 3 * b + 1, typed(draw, wl, 2, 0.05))
            _place(rows, r, 3 * b + 2, 0 if previous is None else round(wl - previous, 2))
            previous = wl
            r += 1
    if recovery:
        previous = None
        for k, (t, wl) in enumerate(recovery):
            _place(rows, 11 + k, 12, round(t, 4))
            _place(rows, 11 + k, 13, wl)
            _place(rows, 11 + k, 14, 0 if previous is None else round(previous - wl, 2))
            previous = wl
    return {"kind": "pumping",
            "sheets": [{"name": "Pumping Test", "rows": _rectangular(rows)}],
            "options": {}}


# -------------------------------------------------------------- lab sheets

PARAMETERS = [
    ("pH", "pH units", (5.0, 9.0)), ("Electrical conductivity", "uS/cm", (20, 2500)),
    ("TDS", "mg/L", (10, 1500)), ("Turbidity", "NTU", (0.1, 40)),
    ("Temperature", "deg C", (22, 32)), ("Total hardness", "mg/L as CaCO3", (5, 400)),
    ("Alkalinity", "mg/L as CaCO3", (5, 300)), ("Calcium", "mg/L", (1, 120)),
    ("Magnesium", "mg/L", (0.5, 60)), ("Sodium", "mg/L", (1, 250)),
    ("Potassium", "mg/L", (0.2, 20)), ("Bicarbonate", "mg/L", (5, 400)),
    ("Chloride", "mg/L", (1, 400)), ("Sulfate", "mg/L", (0.5, 300)),
    ("Nitrate (as NO3)", "mg/L", (0.1, 80)), ("Nitrite (as NO2)", "mg/L", (0.01, 5)),
    ("Ammonia (as N)", "mg/L", (0.01, 3)), ("Fluoride", "mg/L", (0.05, 3)),
    ("Iron", "mg/L", (0.01, 3)), ("Manganese", "mg/L", (0.01, 1)),
    ("Arsenic", "mg/L", (0.001, 0.05)), ("Lead", "mg/L", (0.001, 0.05)),
    ("Copper", "mg/L", (0.01, 3)), ("Zinc", "mg/L", (0.01, 5)),
    ("Chromium (total)", "mg/L", (0.001, 0.1)), ("Cadmium", "mg/L", (0.0005, 0.01)),
    ("E. coli", "CFU/100 mL", (0, 50)), ("Total coliforms", "CFU/100 mL", (0, 300)),
    ("Colour", "TCU", (1, 50)), ("Free chlorine", "mg/L", (0.1, 2)),
]
NON_DETECTS = ["<{dl}", "< {dl}", "ND", "nd", "Not detected", "BDL", "ND (<{dl} mg/L)",
               "<LOD", "ND (DL {dl})", "<{dl} mg/L", "<{dl_ug} ug/L", "0.5 ND",
               "<{comma}"]
COUNTS = ["TNTC", "TNTC (>300)", ">300", ">=50", "Present", "Absent", "Present in 100 mL",
          "Absent/100 mL", "P", "A", "0", "too numerous to count"]


@st.composite
def quality_case(draw) -> dict:
    site = draw(site_values())
    pairs = [("Community", site.get("Community")), ("Client", site.get("Client")),
             ("Sample ID", draw(st.sampled_from(["WQ-BH1-01", "S1", "", 12]))),
             ("Borehole Ref. No.", draw(st.sampled_from(["BH-1", "", "KTL-01"]))),
             ("Sample date", site.get("Date")),
             ("Laboratory", draw(st.sampled_from(["Example Laboratory, Freetown", "",
                                                  "GVWC lab"]))),
             ("District", site.get("District")),
             ("Project", draw(st.sampled_from(["Borehole completion", ""])))]
    rows = header_rows(draw, "WATER QUALITY LABORATORY RESULTS", pairs, [0, 3])
    rows.append([])
    with_dl = draw(st.booleans())
    rows.append(["Parameter", "Unit", "Value"] + (["Detection limit"] if with_dl else [])
                + ["Method"])

    chosen = draw(st.lists(st.sampled_from(range(len(PARAMETERS))), min_size=1,
                           max_size=len(PARAMETERS), unique=True))
    if draw(st.booleans()):
        chosen = sorted(chosen)
    for i in chosen:
        name, unit, (low, high) = PARAMETERS[i]
        value = low + (high - low) * draw(st.floats(0, 1)) ** 2
        digits = 3 if high < 1 else 2 if high < 10 else 1
        dl = None
        cell = typed(draw, value, digits, 0.1)
        style = rare_first(draw)
        bacterial = "CFU" in unit
        if bacterial and style < 0.4:
            cell = draw(st.sampled_from(COUNTS))
        elif style < 0.2:
            dl_value = draw(st.sampled_from([0.001, 0.005, 0.01, 0.05, 0.1, 1.0]))
            cell = draw(st.sampled_from(NON_DETECTS)).format(
                dl=f"{dl_value:g}", dl_ug=f"{dl_value * 1000:g}",
                comma=f"{dl_value:g}".replace(".", ","))
            if with_dl and draw(st.booleans()):
                dl = dl_value
        elif style < 0.25 and with_dl:
            cell, dl = None, draw(st.sampled_from([0.001, 0.01, "0.05", "<0.01"]))
        elif style < 0.3:
            cell = draw(st.sampled_from(["see note", "-", "n/a", "", "1.2.3", "~5"]))
        # the unit as a laboratory writes it
        if unit == "mg/L" and chance(draw, 0.25):
            u = draw(st.sampled_from(["ug/L", "µg/L", "mg/l", "ppm", "ppb", "MG/L", "", "g/L"]))
            if u in ("ug/L", "µg/L", "ppb") and isinstance(cell, (int, float)):
                cell = round(cell * 1000, 3)
            unit = u
        row = [name, unit, cell] + ([dl] if with_dl else [])
        row.append(draw(st.sampled_from([None, None, "APHA 4500", "Photometric"])))
        rows.append(row)
    if draw(st.booleans()):
        rows.append([])
        rows.append(["Notes: for results below detection write <DL in Value."])
    return {"kind": "quality",
            "sheets": [{"name": "Water Quality", "rows": _rectangular(rows)}],
            "options": {}}


# ------------------------------------------------------------ drilling logs

ROCKS = ["Reddish brown lateritic topsoil", "Light yellow clayey laterites",
         "Clayey saprolite", "Weathered granite", "Light colour granite",
         "Granite, fractured", "Granite, fresh", "Sandstone", "Coarse sand",
         "Dolerite", "Schist, weathered", "Quartzite"]


@st.composite
def drilling_case(draw) -> dict:
    total = draw(st.sampled_from([30, 40, 45, 50, 60, 70, 80]))
    step = draw(st.sampled_from([3, 5, 5, 10]))
    tops = list(range(0, total, step))
    rows_data = []
    strikes_written = []
    for top in tops:
        bottom = min(top + step, total)
        style = draw(st.floats(0, 1))
        if style < 0.6:
            interval = f"{top}-{bottom}"
        elif style < 0.7:
            interval = f"{top} - {bottom}"
        elif style < 0.78:
            interval = f"{top}m-{bottom}m"
        elif style < 0.85:
            interval = f"{top}–{bottom}"
        elif style < 0.9:
            interval = f"{top} to {bottom} m"
        elif style < 0.93 and 1 <= top <= 12 and 1 <= bottom <= 28:
            # "5-10" typed into a General cell, which Excel turns into 10 May
            interval = date_cell(datetime.datetime(2026, top, bottom))
        elif style < 0.96:
            continue             # a row not written: a gap in the log
        else:
            interval = f"{top}-"
        description = draw(st.sampled_from(ROCKS))
        extra = rare_first(draw)
        if extra < 0.1:
            a = draw(st.integers(top, bottom))
            description += f", fracture zone {a}-{a + draw(st.integers(1, 4))} m"
        elif extra < 0.15:
            description += f", wet from {draw(st.integers(top, bottom))} m"
        elif extra < 0.2:
            description += f", fractures at {top + 1} and {bottom - 1} m"
        rate = draw(st.sampled_from([None, 1, 0.5, 0.33, 0.42, "0.6", "1,2"]))
        diameter = draw(st.sampled_from([6.5, 6.5, 8, '8½"', '8-1/2"', 165, "6½", None, 254]))
        strike = None
        if chance(draw, 0.12):
            depth = draw(st.integers(top, bottom))
            strike = draw(st.sampled_from([depth, f"{depth} m", f"Strike 1: {depth} m",
                                           f"SWL {depth / 3:.1f}", "14:30",
                                           f"{depth}, {bottom}"]))
            strikes_written.append(depth)
        times = draw(st.sampled_from(["text", "none", "cells"]))
        if times == "text":
            from_t, to_t = "13:30", "13:35"
        elif times == "cells":
            from_t, to_t = time_cell(13, 30), time_cell(13, 41)
        else:
            from_t = to_t = None
        rows_data.append([interval, from_t, to_t, rate, description, diameter, strike])

    site = draw(site_values())
    grout = draw(st.sampled_from([None, 6, 20, "0-20", "20 m", 90]))
    screens = draw(st.sampled_from([None, None, None, "25-35; 48-53", "40-46",
                                    f"{total - 12}-{total - 3}"]))
    pairs = [("Community", site.get("Community")), ("Client", site.get("Client")),
             ("Contractor", draw(st.sampled_from(["WiNGiN Heavy Duty Machines", ""]))),
             ("Borehole Ref. No.", draw(st.sampled_from(["BH-1", "", 3]))),
             ("Drilling start date", site.get("Date")), ("Completion date", None),
             ("Drilling method", draw(st.sampled_from(["Air rotary (DTH hammer)",
                                                       "Mud rotary", "DTH", ""]))),
             ("Total depth (m)", draw(st.sampled_from([total, f"{total}m", None,
                                                       total + 0.5]))),
             ("District", site.get("District")),
             ("BH status", draw(st.sampled_from(["Successful", "Dry", ""]))),
             ("GPS Coordinate East", site.get("GPS Coordinate East")),
             ("GPS Coordinate North", site.get("GPS Coordinate North")),
             ("UTM Zone (28N or 29N)", site.get("UTM Zone (28N or 29N)")),
             ("Elevation (m)", site.get("Elevation (m)")),
             ("Grouting depth (m)", grout), ("Drill rig", None),
             ("Screens installed (m)", screens)]
    rows = header_rows(draw, "BOREHOLE DRILLING LOG", pairs, [0, 3])
    rows.append([])
    rate_head = draw(st.sampled_from(["Penetration rate (m/min)", "Penetration rate (min/m)",
                                      "Penetration rate"]))
    diameter_head = draw(st.sampled_from(["Drilling diameter (in)", "Bit diameter (mm)",
                                          "Bit size"]))
    rows.append(["Depth interval (m)", "From time", "To time", rate_head,
                 "Sample / lithology description", diameter_head, "Water strike depth (m)"])
    rows.extend(rows_data)
    note = draw(st.sampled_from([None, "Water strike 1: 18 m, water strike 2: 42 m",
                                 "Water strike at 20 m; rest water level 4.5 m",
                                 "Notes: write depth intervals as 0-5, 5-10 and so on."]))
    if note:
        rows.append([])
        rows.append([note])
    swl = draw(st.sampled_from([None, 4.5, 9.44, 15.0, round(total * 0.8, 1)]))
    pump = draw(st.sampled_from([None, None, round(total * 0.7, 1), total + 5]))
    return {"kind": "drilling",
            "sheets": [{"name": "Drilling Log", "rows": _rectangular(rows)}],
            "options": {"swl": swl, "pump": pump}}


CASES = {"ves": ves_case, "pumping": pumping_case, "quality": quality_case,
         "drilling": drilling_case}
