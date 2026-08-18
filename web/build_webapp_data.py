"""Bundle the toolkit's reference data into the standalone web app.

The browser app carries the same editable reference tables the Python
package does - WHO/national guideline values, the RWSN cost catalogue,
the supervision checklists, separation distances, district and chiefdom
populations and the map layers - plus the three sample datasets, so
every page works offline with one click.

Nothing here is transcribed by hand: the CSVs and GeoJSON under
``src/groundwater/data`` are the single source of truth and this script
mechanically re-emits them as ``docs/js/gwt-data.js``. Run it whenever
that data changes:

    python web/build_webapp_data.py

The sample workbooks are embedded as the original .xlsx bytes rather
than as pre-parsed records, so loading a sample exercises exactly the
same reader an uploaded file does.
"""

from __future__ import annotations

import base64
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
DATA = REPO / "src" / "groundwater" / "data"
OUT = REPO / "docs" / "js" / "gwt-data.js"

# CSV tables, emitted as arrays of row objects keyed by the header row.
CSV_TABLES = {
    "whoGuidelines": "who_guidelines.csv",
    "costItems": "borehole_cost_items.csv",
    "supervisionChecklists": "supervision_checklists.csv",
    "separationDistances": "site_separation_distances.csv",
    "districts": "sl_districts.csv",
    "chiefdomDistrict": "sl_chiefdom_district.csv",
    "populationDistrict": "sl_population_district.csv",
    "populationChiefdom": "sl_population_chiefdom.csv",
    "censusCrosswalk": "sl_census_crosswalk.csv",
}

# Map layers. Coordinates are rounded to 5 decimal places (about 1 m at the
# equator, far finer than the source boundaries) which roughly halves the
# payload with no visible difference at any zoom the app offers.
GEOJSON_LAYERS = {
    "adminBoundaries": "sl_admin_geoboundaries.geojson",
    "chiefdomBoundaries": "sl_chiefdoms_geoboundaries.geojson",
    "geology": "sl_geology_usgs.geojson",
    "hydrogeology": "sl_hydrogeology_bgs.geojson",
}

COORD_DECIMALS = 5

# The bundled sample datasets, transcribed from real survey and completion
# reports. Keyed by the project the app offers on the Overview page.
#
# The ``site`` block here is only the fallback. The header block on the
# workbook is the source of truth and is read out of it below: a hand-copied
# district drifts from the sheet the app then parses, and the browser and the
# Python engine end up disagreeing about where the same borehole is.
SAMPLE_PROJECTS = {
    "rokel": {
        "label": "Rokel - geophysical survey",
        "note": "Six Schlumberger VES points from a Living Water International "
                "siting survey; drives the VES, maps and geophysical report pages.",
        "files": {
            "ves": "rokel/rokel_ves.xlsx",
            "ipi2win": "rokel/rokel_ipi2win_models.xlsx",
        },
        "site": {
            "client": "Living Water International", "community": "Rokel",
            # the sheet says "Western Area", which is not one of the sixteen
            # districts; the recorded position settles it as Western Area Rural
            "district": "Western Area Rural", "project": "Geophysical Survey",
        },
    },
    "kuntolo": {
        "label": "Kuntoloh - step drawdown test",
        "note": "A four-step test whose discharges were never written on the "
                "sheet; shows the pending-yield path and the manual entry that "
                "resolves it.",
        "files": {"pumping": "kuntolo/kuntolo_step_test.xlsx"},
        "site": {
            "client": "ACF", "community": "Kuntoloh",
            "district": "Port Loko",
        },
    },
    "dr_timbo": {
        "label": "Dr Timbo - drilling to handover",
        "note": "A complete borehole: drilling log, constant discharge test and "
                "water quality analysis, enough for the completion, pumping "
                "test, quality and handover reports.",
        "files": {
            "drilling": "dr_timbo/dr_timbo_drilling_log.xlsx",
            "pumping": "dr_timbo/dr_timbo_constant_test.xlsx",
            "quality": "dr_timbo/dr_timbo_water_quality.xlsx",
        },
        "site": {
            "client": "Dr. Timbo", "community": "Dr. Timbo's Residence",
            "district": "Western Area Rural",
        },
    },
}

BRAND_ASSETS = {"icon": "brand/icon.svg"}


# The readers the app itself uses, in the order the header block is most
# likely to be complete: a drilling log carries the fullest one.
_SITE_READERS = ("drilling", "pumping", "quality", "ves")

_SITE_FIELDS = (
    "client", "project", "community", "chiefdom", "district", "project_ref",
    "easting", "northing", "utm_zone", "elevation_m", "date", "supervisor",
    "contractor",
)


def site_from_workbooks(sources: dict[str, Path], fallback: dict) -> dict:
    """Read the sample's header block out of its own workbooks.

    The app parses these files on load, so anything written here by hand is
    a second copy that can disagree with the first. Values found on a sheet
    win; the hand-written block only fills what no sheet carries.
    """
    from groundwater.ingestion import (
        read_drilling_workbook,
        read_pumping_workbook,
        read_quality_workbook,
        read_ves_workbook,
    )

    readers = {
        "drilling": read_drilling_workbook,
        "pumping": read_pumping_workbook,
        "quality": read_quality_workbook,
        "ves": read_ves_workbook,
    }
    site = dict(fallback)
    known_districts = {row["district"] for row in read_csv_rows("sl_districts.csv")}
    for role in _SITE_READERS:
        source = sources.get(role)
        if source is None:
            continue
        try:
            read = readers[role](source)
            # the VES reader hands back one record per sounding; they share
            # the sheet's header block, so the first one carries it
            parsed = (read[0] if isinstance(read, list) else read).site
        except Exception as exc:  # noqa: BLE001 - a bad sheet is the app's problem
            print(f"  ! could not read the header block from {source.name}: {exc}")
            continue
        if parsed is None:
            continue
        for field in _SITE_FIELDS:
            value = getattr(parsed, field, None)
            if value in (None, ""):
                continue
            # A field sheet is filled in by hand and the administrative
            # name is the field most often written loosely - "Western Area"
            # is not one of the sixteen districts. A name the country does
            # not have is not evidence, so it does not overwrite anything.
            if field == "district" and value not in known_districts:
                print(f"  ! {source.name}: district {value!r} is not one of "
                      f"the sixteen; keeping {site.get(field)!r}")
                continue
            if site.get(field) in (None, ""):
                site[field] = value
            elif str(site[field]) != str(value):
                print(f"  ! {source.name}: {field} is {value!r} on the sheet "
                      f"but {site[field]!r} in build_webapp_data.py; "
                      f"using the sheet")
                site[field] = value

    # A recorded position beats any name written on a sheet: it is the one
    # field that can be checked against the boundaries.
    if site.get("easting") is not None and site.get("northing") is not None:
        from groundwater.geo import infer_zone_for_sierra_leone, utm_to_geographic
        from groundwater.mapping import chiefdom_of

        zone = site.get("utm_zone") or infer_zone_for_sierra_leone(
            float(site["easting"]))
        lat, lon = utm_to_geographic(float(site["easting"]),
                                     float(site["northing"]), int(zone))
        chiefdom, district = chiefdom_of(lat, lon)
        for field, found in (("chiefdom", chiefdom), ("district", district)):
            if not found:
                continue
            if site.get(field) not in (None, "", found):
                print(f"  ! {field} is {site[field]!r} on the sheet but the "
                      f"recorded position falls in {found!r}; using the position")
            site[field] = found
    return site


def read_csv_rows(name: str) -> list[dict]:
    with open(DATA / name, "r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def round_coords(node):
    """Round every coordinate pair in a GeoJSON geometry, in place."""
    if isinstance(node, list):
        if node and all(isinstance(v, (int, float)) for v in node):
            return [round(float(v), COORD_DECIMALS) for v in node]
        return [round_coords(v) for v in node]
    return node


def read_geojson(name: str) -> dict:
    with open(DATA / name, "r", encoding="utf-8") as fh:
        layer = json.load(fh)
    for feature in layer.get("features", []):
        geometry = feature.get("geometry") or {}
        if "coordinates" in geometry:
            geometry["coordinates"] = round_coords(geometry["coordinates"])
    return layer


def encode_file(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def build() -> Path:
    payload: dict[str, object] = {}

    for key, name in CSV_TABLES.items():
        payload[key] = read_csv_rows(name)

    payload["geo"] = {key: read_geojson(name) for key, name in GEOJSON_LAYERS.items()}

    samples = {}
    for key, spec in SAMPLE_PROJECTS.items():
        files = {}
        sources: dict[str, Path] = {}
        for role, rel in spec["files"].items():
            source = REPO / "examples" / "data" / rel
            if not source.exists():
                raise FileNotFoundError(
                    f"{source} is missing; run examples/build_sample_data.py first"
                )
            sources[role] = source
            files[role] = {"name": source.name, "b64": encode_file(source)}
        samples[key] = {
            "label": spec["label"], "note": spec["note"],
            "site": site_from_workbooks(sources, spec["site"]), "files": files,
        }
    payload["samples"] = samples

    brand = {}
    for key, rel in BRAND_ASSETS.items():
        path = DATA / rel
        if path.exists():
            mime = "image/svg+xml" if path.suffix == ".svg" else "image/png"
            brand[key] = f"data:{mime};base64,{encode_file(path)}"
    payload["brand"] = brand

    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    header = (
        "/* gwt-data.js - reference tables and sample datasets for the "
        "Groundwater Toolkit web app.\n"
        " *\n"
        " * GENERATED FILE - do not edit. The source of truth is the CSV and\n"
        " * GeoJSON under src/groundwater/data and the workbooks under\n"
        " * examples/data; regenerate with:\n"
        " *\n"
        " *     python web/build_webapp_data.py\n"
        " */\n"
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        header + "(function (global) {\n"
        "  'use strict';\n"
        "  var GWT = global.GWT || (global.GWT = {});\n"
        "  GWT.data = " + body + ";\n"
        "}(typeof window !== 'undefined' ? window : globalThis));\n",
        encoding="utf-8",
    )
    size_kb = OUT.stat().st_size / 1024
    counts = ", ".join(
        f"{len(payload[k])} {k}" for k in CSV_TABLES if isinstance(payload[k], list)
    )
    print(f"wrote {OUT} ({size_kb:.0f} KB)")
    print(f"  tables: {counts}")
    print(f"  layers: {', '.join(GEOJSON_LAYERS)}")
    print(f"  samples: {', '.join(samples)}")
    return OUT


if __name__ == "__main__":
    build()
