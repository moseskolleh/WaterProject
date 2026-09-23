import numpy as np

import pytest

from groundwater.ingestion import (
    read_drilling_workbook,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)


def test_ves_parsing(sample_data):
    soundings = read_ves_workbook(sample_data / "rokel" / "rokel_ves.xlsx")
    assert len(soundings) == 2
    a = soundings[0]
    assert a.sounding_id == "A (1)"
    assert a.n_readings == 18
    # leading-zero strings parse as numbers
    assert a.rho_app[13] == 78.7
    assert a.site.easting == 708958
    assert a.site.northing == 926355
    # duplicate AB/2 at segment changes preserved
    assert np.sum(a.ab2 == 40) == 2
    assert any(f.code == "segment_overlap" for f in a.flags)
    # second sounding carries the copy-over district error from the source
    assert soundings[1].site.district == "Port Loko"


def test_pumping_parsing_kuntolo(sample_data):
    test = read_pumping_workbook(sample_data / "kuntolo" / "kuntolo_step_test.xlsx")
    assert test.test_type.startswith("step")
    assert len(test.steps) == 3
    assert test.static_water_level_m == 19.28
    assert test.step_length_min == 60
    # irregular time spacing preserved
    assert list(test.steps[0].time_min[:3]) == [1.0, 2.0, 3.0]
    assert 55.0 in test.steps[0].time_min  # 52 -> 55 jump
    # incremental drawdown column ignored; water levels kept
    assert test.steps[0].water_level_m[0] == 10.80
    # recovery block read from its own column group
    assert test.recovery_time_min is not None
    assert len(test.recovery_time_min) == 44
    # discharge missing -> flagged as pending
    assert not test.has_discharge
    assert any(f.code == "missing_discharge" for f in test.flags)
    # the negative-drawdown anomaly on this sheet is flagged
    assert any(f.code == "water_level_above_static" for f in test.flags)


def test_pumping_parsing_dr_timbo(sample_data):
    test = read_pumping_workbook(sample_data / "dr_timbo" / "dr_timbo_constant_test.xlsx")
    assert test.test_type.startswith("constant")
    assert len(test.steps) == 1
    assert test.steps[0].discharge_m3_per_h == 2.93
    assert test.static_water_level_m == 9.44
    assert test.recovery_time_min is not None
    # true drawdown recomputed from static level, not the increment column
    drawdown = test.drawdown(test.steps[0])
    assert abs(drawdown[-1] - (42.26 - 9.44)) < 1e-9


def test_drilling_parsing(sample_data):
    log = read_drilling_workbook(sample_data / "dr_timbo" / "dr_timbo_drilling_log.xlsx")
    assert log.total_depth_m == 70
    assert len(log.intervals) == 14
    assert log.intervals[0].top_m == 0 and log.intervals[0].bottom_m == 5
    assert log.water_strikes_m == [12.0, 30.0]
    assert log.grouting_depth_m == 20
    assert not any(f.code == "interval_overlap" for f in log.flags)


def test_quality_parsing(sample_data):
    sample = read_quality_workbook(sample_data / "dr_timbo" / "dr_timbo_water_quality.xlsx")
    assert len(sample.results) >= 25
    iron = sample.get("Iron")
    assert iron is not None and iron.value == 0.85
    nitrite = sample.get("Nitrite (as NO2)")
    assert nitrite.below_detection and nitrite.detection_limit == 0.01


def test_an_excel_date_cell_in_the_header_reads_as_a_date_not_a_timestamp():
    """openpyxl hands a date-typed cell back as a datetime; str() of that put
    'Survey date: 2015-12-08 00:00:00' on the report cover. ISO date is what
    the browser app prints for the same cell."""
    import datetime

    from groundwater.ingestion.common import extract_header_fields, site_from_fields

    grid = [
        ["Client", "Living Water", None, "Date", datetime.datetime(2015, 12, 8)],
        ["Community", "Rokel", None, "District", "Western Area"],
    ]
    fields = extract_header_fields(grid)
    assert fields["date"] == "2015-12-08"
    assert site_from_fields(fields).date == "2015-12-08"
    grid[0][4] = datetime.date(2015, 12, 8)
    assert extract_header_fields(grid)["date"] == "2015-12-08"
    grid[0][4] = "8th December, 2015"
    assert extract_header_fields(grid)["date"] == "8th December, 2015"


def test_a_columnar_header_block_is_read_from_the_row_beneath():
    """Labels across one row and values in the next used to parse to nothing:
    the cover printed blanks and the consistency check reported the
    coordinates missing although they were on the sheet."""
    from groundwater.ingestion.common import extract_header_fields

    grid = [
        ["Client", "Community", "District", "Sounding Number",
         "GPS Coordinate East", "GPS Coordinate North"],
        ["Living Water", "Rokel", "Western Area", "VES 2", 708958, 926355],
        [],
        ["No.", "AB/2 (m)", "MN (m)", "Rho (ohm.m)"],
    ]
    fields = extract_header_fields(grid)
    assert fields["community"] == "Rokel"
    assert fields["district"] == "Western Area"
    assert fields["easting"] == 708958 and fields["northing"] == 926355
    assert fields["sounding_id"] == "VES 2"
    # the stacked layout is unchanged: a label over a label is not a value
    stacked = [["Client", "Living Water"], ["Community", "Rokel"], ["District", None]]
    assert extract_header_fields(stacked)["community"] == "Rokel"
    assert "district" not in extract_header_fields(stacked)


def _ves_workbook(path, header, rows, sheet="VES 1"):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(["Client", "Living Water"])
    ws.append(["Community", "Rokel"])
    ws.append(["Sounding Number", sheet])
    ws.append([])
    ws.append(header)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def test_greek_resistivity_headers_are_read(tmp_path):
    """'ρa (Ω·m)' is how a geophysicist labels the column; the reader used
    to drop the sheet without a word."""
    from groundwater.ingestion import read_ves_workbook

    path = _ves_workbook(
        tmp_path / "greek.xlsx", ["No.", "AB/2 (m)", "MN (m)", "ρa (Ω·m)"],
        [[1, 1, 0.4, 1165], [2, 2, 0.4, 1193], [3, 3, 0.4, 1303], [4, 5, 0.4, 1500]],
    )
    soundings = read_ves_workbook(path)
    assert len(soundings) == 1
    assert list(soundings[0].rho_app) == [1165, 1193, 1303, 1500]


def test_a_resistance_column_is_not_a_resistivity(tmp_path):
    """A sheet that records V/I in ohms matched the 'ohm' test and every
    reading came through as a resistivity of 0.9; now rho = K x R."""
    from groundwater.ingestion import read_ves_workbook
    from groundwater.ves.arrays import geometric_factor

    path = _ves_workbook(
        tmp_path / "resistance.xlsx", ["No.", "AB/2 (m)", "MN (m)", "R (ohm)"],
        [[1, 1, 0.4, 150.0], [2, 2, 0.4, 40.0], [3, 3, 0.4, 18.0], [4, 5, 0.4, 6.5]],
    )
    soundings = read_ves_workbook(path)
    assert len(soundings) == 1
    k = geometric_factor("schlumberger", ab2=2.0, mn=0.4)
    assert soundings[0].rho_app[1] == pytest.approx(float(k) * 40.0)
    assert any(f.code == "rho_computed_from_resistance" for f in soundings[0].flags)


def test_a_skipped_sheet_is_named_with_its_reason(tmp_path):
    from openpyxl import Workbook

    from groundwater.ingestion import read_ves_workbook

    path = _ves_workbook(
        tmp_path / "mixed.xlsx", ["No.", "AB/2 (m)", "MN (m)", "Rho (ohm.m)"],
        [[1, 1, 0.4, 1165], [2, 2, 0.4, 1193], [3, 3, 0.4, 1303], [4, 5, 0.4, 1500]],
    )
    from openpyxl import load_workbook

    wb = load_workbook(path)
    bad = wb.create_sheet("VES 2")
    bad.append(["Sounding Number", "VES 2"])
    bad.append(["No.", "AB/2 (m)", "MN (m)", "Apparent"])   # header, no rows
    empty = wb.create_sheet("Notes")
    empty.append(["Nothing here"])
    wb.save(path)
    del Workbook
    skipped = []
    soundings = read_ves_workbook(path, skipped=skipped)
    assert [s.sounding_id for s in soundings] == ["VES 1"]
    reasons = {f.message for f in skipped}
    assert any("'VES 2'" in r and "no numeric rows" in r for r in reasons)
    assert any("'Notes'" in r and "no data table" in r for r in reasons)
    assert all(f.code == "sheet_skipped" for f in skipped)


def test_overlap_readings_that_disagree_are_a_warning_not_an_info(sample_data):
    """At AB/2 = 40 m the Rokel A (1) sheet reads 156.1 and 78.7 ohm-m with
    the two MN spacings: a factor of two, which is a field or transcription
    problem, not the few-percent segment shift the splice is built for."""
    from groundwater.ingestion import read_ves_workbook

    soundings = read_ves_workbook(sample_data / "rokel" / "rokel_ves.xlsx")
    a = soundings[0]
    codes = [f.code for f in a.flags]
    assert "segment_overlap" in codes
    assert "segment_overlap_discrepancy" in codes
    warning = next(f for f in a.flags if f.code == "segment_overlap_discrepancy")
    assert warning.level == "warning"
    assert "AB/2 40 m: 156.1 and 78.7 ohm-m (ratio 1.98)" in warning.message
    assert "AB/2 3 m" not in warning.message  # 1303 vs 1317 agree


def _quality_workbook(path, rows):
    """A minimal laboratory certificate: header block, then the results."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    ws.append(["Community", "Test"])
    ws.append(["Sample ID", "WQ-1"])
    ws.append([])
    ws.append(["Parameter", "Unit", "Value", "Detection limit"])
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


def test_a_non_detect_written_with_its_limit_is_a_non_detect(tmp_path):
    """"ND (<0.05)" is absence, and it was read as a measured 0.05.

    Only an exact match against the absence words counted, so every one of
    these forms came through as a concentration and was graded as exceeding
    a health guideline - the arsenic a laboratory reported as absent was
    the worst reading on the sheet.
    """
    from groundwater.ingestion import read_quality_workbook

    sample = read_quality_workbook(_quality_workbook(tmp_path / "nd.xlsx", [
        ["Arsenic", "mg/L", "ND (<0.05)", None],
        ["Lead", "mg/L", "BDL (0.02)", None],
        ["Cadmium", "mg/L", "ND<0.1", None],
        ["Mercury", "mg/L", "Not detected (<0.001)", None],
        ["Nitrate (as NO3)", "mg/L", "12.5", None],
    ]))
    by_name = {r.parameter: r for r in sample.results}
    for name, limit in (("Arsenic", 0.05), ("Lead", 0.02),
                        ("Cadmium", 0.1), ("Mercury", 0.001)):
        row = by_name[name]
        assert row.value is None, name
        assert row.below_detection, name
        assert row.detection_limit == pytest.approx(limit), name
    # a real number is still a real number
    assert by_name["Nitrate (as NO3)"].value == pytest.approx(12.5)


def test_a_count_the_laboratory_did_not_quantify_is_not_absence(tmp_path):
    """"TNTC" and ">50" used to read as "not measured" and as exactly 50."""
    from groundwater.ingestion import read_quality_workbook

    sample = read_quality_workbook(_quality_workbook(tmp_path / "tntc.xlsx", [
        ["Total coliforms", "CFU/100 mL", "TNTC", None],
        ["E. coli", "CFU/100 mL", "0", None],
        ["Faecal streptococci", "CFU/100 mL", ">50", None],
        ["Salmonella", "per 100 mL", "Present", None],
    ]))
    by_name = {r.parameter: r for r in sample.results}
    assert by_name["Total coliforms"].value is None
    assert by_name["Total coliforms"].greater_than == 0.0
    assert by_name["Total coliforms"].detected_not_quantified
    assert not by_name["Total coliforms"].below_detection
    assert by_name["Faecal streptococci"].greater_than == pytest.approx(50.0)
    assert by_name["Faecal streptococci"].value is None
    assert by_name["Salmonella"].greater_than == 0.0
    assert by_name["E. coli"].value == pytest.approx(0.0)


def _drilling_grid(rows):
    """A drilling sheet as the reader sees it: header block, then the log table.

    The column headings are the ones the bundled template writes, so a test
    row is read exactly as a crew's row is.
    """
    return [
        ["BOREHOLE DRILLING LOG"],
        ["Community", "Testville", None, "Client", "Living Water"],
        ["Borehole Ref. No.", "BH-1", None, "Total depth (m)", 30],
        [],
        ["Depth interval (m)", "From time", "To time", "Penetration rate (m/min)",
         "Sample / lithology description", "Drilling diameter (in)",
         "Water strike depth (m)"],
        *rows,
    ]


def test_a_depth_interval_typed_with_an_en_dash_is_read_not_dropped():
    """A row written "5–10" was dropped without a word, and the only trace
    was an interval_gap flag blaming the crew for a gap they never left.

    Word turns the hyphen into an en dash as the sheet is typed and the dash
    survives the copy into Excel, so the loss is invisible to the crew: the
    log simply came back one interval short of what they drilled.
    """
    from groundwater.ingestion.drilling import drilling_from_grid

    log = drilling_from_grid(_drilling_grid([
        ["0-5", "13:30", "13:35", 1, "Lateritic topsoil", 6.5, None],
        ["5\u201310", "13:36", "13:41", 1, "Clayey laterite", 6.5, None],
        ["10\u201415", "13:55", "14:10", 0.33, "Saprolite", 6.5, None],
        ["15\u221220", "14:14", "14:26", 0.42, "Weathered granite", 6.5, None],
        ["20-30", "14:30", "14:38", 0.63, "Granite", 6.5, None],
    ]))
    assert [(iv.top_m, iv.bottom_m) for iv in log.intervals] == [
        (0.0, 5.0), (5.0, 10.0), (10.0, 15.0), (15.0, 20.0), (20.0, 30.0)
    ]
    assert not any(f.code == "interval_gap" for f in log.flags)
    # the same dash in a screens cell is the same typing, and the same loss
    from groundwater.ingestion.drilling import parse_installed_screens

    assert parse_installed_screens("25\u201335; 48\u201453 m") == [(25.0, 35.0), (48.0, 53.0)]


def test_a_clock_time_in_a_water_strike_note_is_not_a_strike_depth():
    """"Water strike: 8 m at 14:30" recorded a strike at 30 m - the minutes of
    the clock - because the note was read as the last number after the last
    colon, and a note naming two strikes recorded only the first."""
    from groundwater.ingestion.drilling import drilling_from_grid

    grid = _drilling_grid([
        ["0-5", None, None, None, "Lateritic topsoil", 6.5, None],
        ["5-30", None, None, None, "Granite", 6.5, None],
        ["Water strike: 8 m at 14:30"],
    ])
    assert drilling_from_grid(grid).water_strikes_m == [8.0]

    grid[-1] = ["Water strikes at 12 m and 30 m"]
    assert drilling_from_grid(grid).water_strikes_m == [12.0, 30.0]

    # one unit at the end of a list carries the whole list
    grid[-1] = ["Water strikes: 12, 18 and 30 m"]
    assert drilling_from_grid(grid).water_strikes_m == [12.0, 18.0, 30.0]


def test_a_zero_in_the_water_strike_column_is_an_empty_cell_not_a_strike():
    """A crew writes 0 in the strike column for a dry run of rods; it was read
    as a strike at 0 m, which seeded a 0-5 m screen against the topsoil."""
    from groundwater.ingestion.drilling import drilling_from_grid

    log = drilling_from_grid(_drilling_grid([
        ["0-5", None, None, None, "Lateritic topsoil", 6.5, 0],
        ["5-10", None, None, None, "Clayey laterite", 6.5, 0],
        ["10-30", None, None, None, "Fractured granite", 6.5, 12],
    ]))
    assert log.water_strikes_m == [12.0]
    zero = next(f for f in log.flags if f.code == "water_strike_zero_ignored")
    assert zero.level == "info" and "0 on 2 row(s)" in zero.message


def test_a_water_strike_note_that_cannot_be_read_is_flagged_not_guessed():
    """A strike depth places the screens, so a note that does not say which of
    its numbers are depths is refused and named rather than guessed at."""
    from groundwater.ingestion.drilling import drilling_from_grid

    log = drilling_from_grid(_drilling_grid([
        ["0-30", None, None, None, "Granite", 6.5, None],
        ["Water strikes at 12 and 30"],
    ]))
    assert log.water_strikes_m == []
    flag = next(f for f in log.flags if f.code == "water_strike_unreadable")
    assert flag.level == "warning"
    assert "Water strikes at 12 and 30" in flag.message
    assert "none of them carries a unit" in flag.message


def test_a_diameter_in_millimetres_is_not_a_diameter_in_inches():
    """"165 mm" was recorded as a 165 inch hole and "5 min/m" as five metres a
    minute, because both columns were read as bare numbers whatever unit the
    crew had written in the cell."""
    from groundwater.ingestion.drilling import drilling_from_grid

    log = drilling_from_grid(_drilling_grid([
        ["0-5", None, None, "5 min/m", "Lateritic topsoil", "165 mm", None],
        ["5-20", None, None, "30 m/hr", "Saprolite", '6 1/2"', None],
        ["20-30", None, None, 0.63, "Granite", 6.5, None],
    ]))
    assert [iv.bit_diameter_in for iv in log.intervals] == [6.5, 6.5, 6.5]
    assert [iv.penetration_rate_m_per_min for iv in log.intervals] == [0.2, 0.5, 0.63]


def test_a_zone_cell_that_looks_like_a_label_does_not_become_the_easting():
    """A sheet whose zone cell reads "Zone 28" carried a zone of 708958.

    "Zone 28" typed as the value matches the same ``^zone`` pattern the label
    does, so the header scan took the value cell for a second label, looked
    below it for a value of its own, and found the easting sitting in the row
    beneath. The site was then carried as "zone 708958", which projects to a
    longitude of four million degrees - a position no map can draw and no
    report should print. A zone that cannot be read is left unrecorded and
    inferred from the easting, with the assumption stated.
    """
    from groundwater.ingestion.checks import check_site_consistency
    from groundwater.ingestion.common import extract_header_fields, site_from_fields

    grid = [
        ["UTM Zone (28N or 29N)", "Zone 28"],
        ["GPS Coordinate East", "0708958"],
        ["GPS Coordinate North", "0926355"],
        ["District", "Western Area"],
    ]
    site = site_from_fields(extract_header_fields(grid), "sheet.xlsx")
    assert site.utm_zone is None
    assert site.utm.zone == 28
    lat, lon = site.latlon
    assert 6.9 <= lat <= 10.0 and -13.3 <= lon <= -10.3
    assert [f.code for f in check_site_consistency(site)] == ["utm_zone_assumed"]

    # a zone cell that states one zone is still read as that zone
    plain = [["UTM Zone", "29N"], ["GPS Coordinate East", 178000],
             ["GPS Coordinate North", 1000000]]
    assert site_from_fields(extract_header_fields(plain)).utm_zone == 29


def test_a_clock_time_written_without_a_colon_is_not_a_strike_depth():
    """"Water strike at 1430 hrs" recorded a water strike at 1430 m.

    The colon form was read as a time, but the form a driller more often
    writes - the hour with no separator and the word after it - was not, so
    the only number in the note went through as a depth. A thirty metre
    borehole was handed to the client recording a strike twenty times deeper
    than the hole, with no flag against it, because nothing in the reader
    knew that a four-digit number carrying "hrs" is a time of day.
    """
    from groundwater.ingestion.drilling import drilling_from_grid

    log = drilling_from_grid(_drilling_grid([
        ["0-30", None, None, None, "Fractured granite", 6.5,
         "Water strike at 1430 hrs"],
    ]))
    assert log.water_strikes_m == []
    assert log.total_depth_m == 30

    # the depth beside such a time is still read, and an elapsed time in
    # hours is too short a number to be a clock and is left where it is
    grid = _drilling_grid([
        ["0-30", None, None, None, "Fractured granite", 6.5,
         "Water strike 12 m at 1430 hrs"],
    ])
    assert drilling_from_grid(grid).water_strikes_m == [12.0]
    grid[-1][6] = "Water strike 8 m after 2 hrs"
    assert drilling_from_grid(grid).water_strikes_m == [8.0]


def test_a_unit_spelled_out_or_pluralised_is_still_the_unit_it_names():
    """"165 mms" was a 165 inch hole and "30 metres/hour" thirty metres a minute.

    The unit patterns listed the abbreviations without their plurals and the
    metre only as "m", so a sheet one character away from a spelling they did
    know - "mms" for "mm", "m/hrs" for "m/hr", "metres/hour" for "m/hr" -
    fell past them to the bare number and was read in the column's default
    unit. The bit diameter is what sizes the casing and the gravel pack, so
    that reading reaches the bill of quantities.
    """
    from groundwater.ingestion.drilling import (parse_bit_diameter_in,
                                                parse_penetration_rate_m_per_min)

    for text in ("165 mm", "165 mms", "165 millimetres"):
        assert parse_bit_diameter_in(text) == 6.5, text
    for text in ("16.5 cm", "16.5 cms"):
        assert parse_bit_diameter_in(text) == 6.5, text

    for text in ("30 m/hr", "30 m/hrs", "30 m/h", "30 metres/hour",
                 "30 meters/hour", "30 metres per hour"):
        assert parse_penetration_rate_m_per_min(text) == 0.5, text
    for text in ("5 min/m", "5 min/metre", "5 minutes per metre"):
        assert parse_penetration_rate_m_per_min(text) == 0.2, text
    for text in ("12 s/m", "12 s/metre", "12 seconds per metre"):
        assert parse_penetration_rate_m_per_min(text) == 5.0, text
    # and a cell with no unit still reads in the unit its column asks for
    assert parse_bit_diameter_in("6.5") == 6.5
    assert parse_penetration_rate_m_per_min("0.33") == 0.33


def test_a_fraction_in_a_strike_cell_names_no_depth():
    """"Water strike 1/2 m" is half a metre, and it read as a strike at 2 m.

    The slash was a list separator, so the cell first came out as two
    strikes and then, with the separator tightened, as its own denominator.
    A depth places a screen, so the honest answer is to record none and say
    why.
    """
    from groundwater.ingestion.drilling import parse_water_strike_depths

    depths, reason = parse_water_strike_depths("Water strike 1/2 m")
    assert depths == []
    assert "fraction" in reason
    # a real list is still read
    assert parse_water_strike_depths("strikes at 12, 18 and 30 m")[0] == [12.0, 18.0, 30.0]


def test_a_clock_written_without_a_separator_is_not_a_depth():
    """"1430 hrs" recorded a strike 1430 m down."""
    from groundwater.ingestion.drilling import parse_water_strike_depths

    assert parse_water_strike_depths("Water strike at 1430 hrs")[0] == []
    assert parse_water_strike_depths("Water strike 8 m at 1430 hrs")[0] == [8.0]


def test_a_strike_below_the_bottom_of_the_hole_is_not_recorded(tmp_path):
    """It is a depth the drilling never reached, printed to the client.

    The screen designer clips it out, so nothing else in the toolkit ever
    contradicted it; the handover report simply listed it.
    """
    from openpyxl import Workbook

    from groundwater.ingestion import read_drilling_workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Log"
    ws.append(["BOREHOLE DRILLING LOG"])
    ws.append(["Community", "Test", None, "Client", "Test"])
    ws.append([None, None, None, "Total depth (m)", 30])
    ws.append([])
    ws.append(["Depth interval (m)", "From time", "To time",
               "Penetration rate (m/min)", "Sample / lithology description",
               "Water strike (m)"])
    ws.append(["0-15", None, None, 1, "Weathered granite", None])
    ws.append(["15-30", None, None, 1, "Fresh granite", "8 m and 1430 m"])
    path = tmp_path / "deep.xlsx"
    wb.save(path)

    log = read_drilling_workbook(path)
    assert log.water_strikes_m == [8.0]
    flag = next(f for f in log.flags if f.code == "water_strike_below_total_depth")
    assert "1430 m" in flag.message and "30 m" in flag.message


def _pumping_workbook(path, headings, headers, rows, *, test_type="constant"):
    """A pumping sheet as the reader sees it: the header block the template
    prints, the heading over each column block, then the column headers and
    the readings."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Pumping Test"
    ws.append(["PUMPING TEST FIELD SHEET (STEP / CONSTANT DISCHARGE)"])
    ws.append(["Community", "Testville", None, "Date", "1st April, 2017"])
    ws.append(["Client", "Living Water", None, "Depth of Borehole (m)", 70])
    ws.append(["Borehole Ref. No.", "BH-1", None, "Pump setting (m)", 67])
    ws.append(["Static water level (m)", 9.44, None, "District", "Port Loko"])
    ws.append(["Test type (step or constant)", test_type])
    ws.append([])
    ws.append(["Discharge per step (m3/h)", "Step 1 Q", 2.93])
    ws.append(headings)
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)
    return path


# One hour of readings as a crew takes them: close together at first, then
# every fifteen minutes, closing the hour on the sixtieth minute.
_HOUR_TIMES = [1, 2, 3, 5, 10, 20, 30, 45, 60]
_HOUR_LEVELS = [
    [12.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0],
    [21.2, 21.4, 21.6, 21.8, 22.0, 22.2, 22.4, 22.6, 22.8],
    [23.0, 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7, 23.8],
]


def _hourly_rows(levels_by_block, times_by_block=None):
    """Side by side hourly blocks of Time / Water Level / Drawdown."""
    times_by_block = times_by_block or [_HOUR_TIMES] * len(levels_by_block)
    rows = []
    for i in range(len(times_by_block[0])):
        row = []
        for times, levels in zip(times_by_block, levels_by_block, strict=True):
            increment = 0 if i == 0 else round(levels[i] - levels[i - 1], 2)
            row += [times[i], levels[i], increment]
        rows.append(row)
    return rows


def test_hourly_blocks_that_count_from_one_are_joined_not_interleaved(tmp_path):
    """Three hours of a constant test, each block counting 1, 2, 3 within its
    own hour, were read as one column and sorted into a sawtooth: minute 1 of
    every hour, then minute 2 of every hour, so the levels jumped between the
    three hours at every point and the drawdown curve - and the transmissivity
    fitted to it - belonged to no test that was ever run.
    """
    headings = ["Constant discharge 0-60 min", None, None,
                "Constant discharge 61-120 min", None, None,
                "Constant discharge 121-180 min", None, None]
    headers = ["Time (min)", "Water Level (m)", "Drawdown (m)"] * 3
    path = _pumping_workbook(tmp_path / "hourly.xlsx", headings, headers,
                             _hourly_rows(_HOUR_LEVELS))

    test = read_pumping_workbook(path)
    assert len(test.steps) == 1
    step = test.steps[0]
    assert list(step.time_min) == [
        1, 2, 3, 5, 10, 20, 30, 45, 60,
        61, 62, 63, 65, 70, 80, 90, 105, 120,
        121, 122, 123, 125, 130, 140, 150, 165, 180,
    ]
    assert list(step.water_level_m) == sum(_HOUR_LEVELS, [])
    # the level only ever deepens on this sheet; the sawtooth had it rise and
    # fall between the three hours at every minute
    assert np.all(np.diff(step.water_level_m) > 0)
    assert not any(f.code == "time_not_increasing" for f in test.flags)

    joined = next(f for f in test.flags if f.code == "constant_blocks_joined")
    assert joined.level == "info"
    assert "Constant discharge 61-120 min" in joined.message
    assert "1 to 180 min" in joined.message

    # the same sheet with nothing written over the blocks: the restart itself
    # says the block is a fresh count, and it continues from the last reading
    plain = _pumping_workbook(tmp_path / "unheaded.xlsx", [], headers,
                              _hourly_rows(_HOUR_LEVELS))
    unheaded = read_pumping_workbook(plain)
    assert list(unheaded.steps[0].time_min) == list(step.time_min)
    note = next(f for f in unheaded.flags if f.code == "constant_blocks_joined")
    assert "continuing from the last reading before it" in note.message


def test_a_block_is_placed_by_its_heading_not_by_its_first_reading(tmp_path):
    """Hours two to four read every five, ten and fifteen minutes, each block
    counting within its own hour. Each block was placed by lining its first
    reading up with its heading, so "61-120 min" read at 5 to 60 was put at
    61 to 116, the four-hour test ended at 226 minutes, and the analysis
    called it a short test."""
    headings = ["Constant discharge 0-60 min", None, None,
                "Constant discharge 61-120 min", None, None,
                "Constant discharge 121-180 min", None, None,
                "Constant discharge 181-240 min", None, None]
    headers = ["Time (min)", "Water Level (m)", "Drawdown (m)"] * 4
    times = [[0, 5, 10, 20, 30, 40, 50, 60], [5, 10, 15, 20, 30, 40, 50, 60],
             [10, 20, 30, 40, 45, 50, 55, 60], [15, 20, 25, 30, 40, 45, 50, 60]]
    levels = [[9.44 + 0.1 * (60 * b + t) ** 0.5 for t in block]
              for b, block in enumerate(times)]
    path = _pumping_workbook(tmp_path / "every_five.xlsx", headings, headers,
                             _hourly_rows(levels, times))

    test = read_pumping_workbook(path)
    step = test.steps[0]
    assert list(step.time_min) == [
        0, 5, 10, 20, 30, 40, 50, 60,
        65, 70, 75, 80, 90, 100, 110, 120,
        130, 140, 150, 160, 165, 170, 175, 180,
        195, 200, 205, 210, 220, 225, 230, 240,
    ]
    assert test.pumping_duration_min == 240
    joined = next(f for f in test.flags if f.code == "constant_blocks_joined")
    assert ("heading 'Constant discharge 61-120 min' covers 61 to 120 min, so 60 min "
            "were added to it and its first reading, at 5 min, is minute 65 of the "
            "test") in joined.message
    assert "0 to 240 min" in joined.message
    from groundwater.hydraulics import analyse_pumping_test

    assert not any(f.code == "short_test" for f in analyse_pumping_test(test).flags)


def test_a_block_whose_place_in_the_test_is_unreadable_is_left_out_and_named(tmp_path):
    """A block that starts inside the hour already read and runs past it is
    neither the test's own elapsed time nor a fresh count within the block,
    and joining it at a guessed minute would put readings on the drawdown
    curve at times nobody can check."""
    headers = ["Time (min)", "Water Level (m)", "Drawdown (m)"] * 2
    straddling = [30, 40, 50, 60, 70, 75, 80, 85, 90]
    path = _pumping_workbook(
        tmp_path / "straddle.xlsx", [], headers,
        _hourly_rows(_HOUR_LEVELS[:2], [_HOUR_TIMES, straddling]))

    test = read_pumping_workbook(path)
    assert list(test.steps[0].time_min) == _HOUR_TIMES
    assert list(test.steps[0].water_level_m) == _HOUR_LEVELS[0]
    flag = next(f for f in test.flags if f.code == "constant_block_unreadable")
    assert flag.level == "warning"
    assert "Block 2" in flag.message and "30 min" in flag.message
    assert "60 min already read" in flag.message


# A recovery block written with both increment columns, as crews do when the
# sheet is retyped: Time / Level / Drawdown / Recovery.
_RECOVERY_TIMES = [0, 1, 2, 3, 5, 10, 20, 30]
_RECOVERY_LEVELS = [42.26, 42.2, 41.78, 41.39, 30.0, 20.0, 12.0, 9.5]


def _recovery_rows(pumping_levels, recovery_levels):
    rows = []
    for i in range(len(_HOUR_TIMES)):
        row = [_HOUR_TIMES[i], pumping_levels[i],
               0 if i == 0 else round(pumping_levels[i] - pumping_levels[i - 1], 2)]
        if i < len(recovery_levels):
            level = recovery_levels[i]
            rise = 0 if i == 0 else round(recovery_levels[i - 1] - level, 2)
            row += [_RECOVERY_TIMES[i], level, round(level - 9.44, 2), rise]
        rows.append(row)
    return rows


def test_a_recovery_block_with_a_drawdown_column_reads_the_level_as_the_level(tmp_path):
    """A recovery block laid out Time / Level / Drawdown / Recovery had its
    fourth column read as the water level, so a recovery that climbed from
    42.26 m back to 9.5 m was reported as a handful of centimetre increments -
    a borehole that never recovered, and a recovery transmissivity fitted to
    the rise between readings."""
    headings = ["Constant discharge 0-60 min", None, None, "Recovery"]
    headers = ["Time (min)", "Water Level (m)", "Drawdown (m)",
               "Time (min)", "Level (m)", "Drawdown (m)", "Recovery (m)"]
    path = _pumping_workbook(tmp_path / "recovery.xlsx", headings, headers,
                             _recovery_rows(_HOUR_LEVELS[0], _RECOVERY_LEVELS))

    test = read_pumping_workbook(path)
    assert test.recovery_level_m is not None
    assert list(test.recovery_level_m) == _RECOVERY_LEVELS
    assert list(test.recovery_time_min) == _RECOVERY_TIMES
    # the pumping block is still read as the pumping block
    assert len(test.steps) == 1
    assert list(test.steps[0].water_level_m) == _HOUR_LEVELS[0]
    assert not any(f.code == "recovery_layout_unreadable" for f in test.flags)

    # and the same layout with nothing written over the blocks: the headers
    # name the columns, so the level is read as the level either way
    plain = _pumping_workbook(tmp_path / "recovery_unheaded.xlsx", [], headers,
                              _recovery_rows(_HOUR_LEVELS[0], _RECOVERY_LEVELS))
    assert list(read_pumping_workbook(plain).recovery_level_m) == _RECOVERY_LEVELS


def test_a_recovery_column_the_sheet_never_explains_is_refused_not_guessed(tmp_path):
    """A recovery column standing apart from the water level column may hold
    levels or the rise between readings, and read as levels an increment
    column gives a recovery that climbs a few centimetres out of a borehole
    tens of metres deep. The reader used to take it for the levels in silence.
    """
    headers = ["Time (min)", "Water Level (m)", "Drawdown (m)", "Remarks",
               "Recovery (m)"]
    rows = [[t, wl, 0, None, 0.1]
            for t, wl in zip(_HOUR_TIMES, _HOUR_LEVELS[0], strict=True)]
    test = read_pumping_workbook(
        _pumping_workbook(tmp_path / "apart.xlsx", [], headers, rows))

    assert test.recovery_time_min is None
    assert list(test.steps[0].water_level_m) == _HOUR_LEVELS[0]
    flag = next(f for f in test.flags if f.code == "recovery_layout_unreadable")
    assert flag.level == "warning"
    assert "Recovery (m)" in flag.message

    # a Time / Level / Drawdown / Recovery block alone on a sheet is the same
    # question: with no other block holding the pumping readings, nothing says
    # whether it is a recovery block or a whole test against one time column
    alone = ["Time (min)", "Level (m)", "Drawdown (m)", "Recovery (m)"]
    rows = [[t, wl, 0, 0.1] for t, wl in zip(_HOUR_TIMES, _HOUR_LEVELS[0], strict=True)]
    single = read_pumping_workbook(
        _pumping_workbook(tmp_path / "alone.xlsx", [], alone, rows))
    assert single.recovery_time_min is None
    assert list(single.steps[0].water_level_m) == _HOUR_LEVELS[0]
    assert any(f.code == "recovery_layout_unreadable" for f in single.flags)


def test_a_block_that_was_left_out_is_not_also_reported_as_joined(tmp_path):
    """A block placed by its own heading and then found to run backwards into
    the block before it was named in both flags at once: the warning said it
    had been left out of the series, and the very next sentence of the info
    flag said it had been joined with twenty-nine minutes added to it. A
    reader had no way to tell which of the two the curve was drawn from.
    """
    headings = ["Constant discharge 1-60 min", None, None,
                "Constant discharge 30-90 min", None, None]
    headers = ["Time (min)", "Water Level (m)", "Drawdown (m)"] * 2
    path = _pumping_workbook(tmp_path / "backwards.xlsx", headings, headers,
                             _hourly_rows(_HOUR_LEVELS[:2]))

    test = read_pumping_workbook(path)
    assert list(test.steps[0].time_min) == _HOUR_TIMES
    dropped = next(f for f in test.flags if f.code == "constant_block_unreadable")
    assert "still starts at 30 min once placed" in dropped.message
    # the block was left out, so nothing says it was joined
    assert not any(f.code == "constant_blocks_joined" for f in test.flags)
