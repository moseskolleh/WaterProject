"""Coverage as a planning figure, and the WPdx+ rows both readers read alike:
the "wpdx_fields", "wpdx_reader_rows", "wpdx_reader", "growth_rate" and
"planning" entries of ``reference.json``.
"""

from __future__ import annotations

from .common import clean


#: WPdx+ rows both readers read alike: positions no map holds ("nan",
#: "inf", past 90 or 180, UTM metres in the degree columns, a cell of
#: spaces, numbers one language reads and the other does not), and install
#: years written as 0, as a fraction, as installation_year and as text.
WPDX_READER_ROWS = [
    {"row_id": "ok", "lat_deg": "8.5", "lon_deg": "-11.5", "install_year": "2012"},
    {"row_id": "nan", "lat_deg": "nan", "lon_deg": "nan"},
    {"row_id": "inf", "lat_deg": "8.5", "lon_deg": "inf"},
    {"row_id": "Infinity", "lat_deg": "Infinity", "lon_deg": "-11.5"},
    {"row_id": "range", "lat_deg": "95", "lon_deg": "200"},
    {"row_id": "utm", "lat_deg": "936224.6", "lon_deg": "694667.5"},
    {"row_id": "spaces", "lat_deg": "  ", "lon_deg": "-11.5"},
    {"row_id": "underscore", "lat_deg": "8.5", "lon_deg": "-11_5"},
    {"row_id": "hex", "lat_deg": "0x8", "lon_deg": "-11.5"},
    {"row_id": "true", "lat_deg": True, "lon_deg": -11.5},
    {"row_id": "edge", "lat_deg": 90, "lon_deg": -180},
    {"row_id": "padded", "lat_deg": " 8.25\t", "lon_deg": "-11.5e0", "install_year": "0"},
    {"row_id": "fraction", "lat_deg": 8.3, "lon_deg": -11.6, "install_year": "2009.6"},
    {"row_id": "installation", "lat_deg": 8.3, "lon_deg": -11.6, "installation_year": "2011"},
    {"row_id": "blank", "lat_deg": 8.3, "lon_deg": -11.6, "install_year": "", "installation_year": 2003},
    {"row_id": "negative", "lat_deg": 8.3, "lon_deg": -11.6, "install_year": "-4"},
    {"row_id": "text", "lat_deg": 8.3, "lon_deg": -11.6, "install_year": "unknown"},
    {"row_id": "number", "lat_deg": "+.5", "lon_deg": "-11.", "install_year": 1998},
    "not a record",
]


def fill_planning(out: dict) -> None:
    """Fill "wpdx_fields", "wpdx_reader_rows", "wpdx_reader", "growth_rate" and
    "planning".

    It fills ``out`` in place, where build() calls it: build.py says why."""
    # Coverage as a planning figure: projection, freshness and the
    # dry-season band.
    from groundwater import planning as _planning
    from groundwater.waterpoints import WaterPoint as _WaterPoint

    def _wp(functional, year, months):
        return _WaterPoint(
            row_id="x", lat=8.0, lon=-13.0, functional=functional,
            status="", source="Borehole", technology="Hand Pump",
            install_year=None, adm2="", report_year=year,
            months_per_year=months)

    from groundwater.waterpoints import _months_per_year, _year_of

    out["wpdx_fields"] = [
        {"date": d, "year": _year_of(d),
         "months_text": m, "months": _months_per_year(m)}
        for d, m in (("2019-04-02T00:00:00", "12"), ("02/04/2019", "yes"),
                     ("2019", "6 months"), ("", ""), ("not a date", "seasonal"),
                     ("1899-01-01", "14"), ("survey 2024 round 2", "no"))
    ]
    from groundwater.waterpoints import parse_wpdx_records as _parse_wpdx

    _skipped: list = []
    _read = _parse_wpdx(WPDX_READER_ROWS, _skipped)
    out["wpdx_reader_rows"] = WPDX_READER_ROWS
    out["wpdx_reader"] = {
        "points": [[p.row_id, p.lat, p.lon, p.install_year] for p in _read],
        "flags": [[f.level, f.code, f.message] for f in _skipped],
    }
    out["growth_rate"] = _planning.intercensal_growth_rate()
    _planning_population = {
        "Bo": 575478.0, "Kono": 506100.0, "Pujehun": 346461.0,
        "Falaba": 202566.0, "Western Area Urban": 1055964.0,
    }
    _planning_points = {
        "Bo": [_wp(True, 2024, 12), _wp(True, 2010, None), _wp(False, 2024, 12)],
        "Kono": [_wp(True, None, None), _wp(True, 2003, 6)],
        "Pujehun": [_wp(False, 2020, None)],
        "Western Area Urban": [_wp(True, 2025, 12), _wp(True, 2025, None),
                               _wp(True, 2019, 4)],
    }
    out["planning"] = {}
    for _label, _year, _rate, _rates in (
        ("census", 2015, None, None),
        ("today", 2026, None, None),
        ("slow", 2026, 0.015, None),
        ("districts", 2026, None, {"Western Area Urban": 0.06, "Pujehun": 0.01}),
        ("before the surveys", 2018, None, None),
    ):
        _rows, _proj = _planning.planning_rows(
            _planning_population, _planning_points,
            as_of_year=_year, rate=_rate, rates=_rates)
        out["planning"][_label] = clean({
            "projection": _proj.as_dict(),
            "stats": _planning.planning_stats(_rows, _proj),
            "rows": [r.as_dict() for r in _rows],
        })
