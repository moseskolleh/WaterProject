"""Helpers every page of the Streamlit app shares."""

from __future__ import annotations

import hashlib
import html as _html
import re as _re
import sys
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

import groundwater
import groundwater.ves as _ves
from groundwater.config import Config
from groundwater.costing import (
    CostingInputs,
    estimate_borehole_cost,
    load_rates,
    plot_cost_breakdown,
    write_boq_workbook,
)
from groundwater.coverage import (
    chiefdom_population,
    group_points_by_chiefdom,
    group_points_by_district,
    load_chiefdom_district,
    load_chiefdom_polys,
    load_district_population,
)
from groundwater.ingestion import (
    read_drilling_workbook,
    read_pumping_docx,
    read_pumping_workbook,
    read_quality_workbook,
    read_ves_workbook,
)
from groundwater.waterpoints import parse_wpdx_csv, parse_wpdx_records
from groundwater.geo import geographic_to_utm, parse_utm_zone, read_latlon
from groundwater.hydraulics.analysis import pump_intake_depth
from groundwater.design import design_borehole, pump_intake_floor
from groundwater.models import SiteMetadata
from groundwater.portfolio import classify_status, STATUS_LABELS, VERDICT_SCHEMA
from groundwater.project_io import (
    committee_records,
    deserialize_project,
    serialize_project,
    stale_on_load,
)
from groundwater.readiness import assess_readiness
from groundwater.seasonal import month_of, seasonal_yield
from groundwater.supervision import load_checklists, load_separation_distances
from groundwater.ves.cache import cache_entry, inversion_key
from groundwater.ves.interpret import rank_interpretations


# The Depth Spine workspace renders two ways. The custom component is
# interactive but needs a server to serve its frontend, so the in-browser
# (WebAssembly) demo gets the static build through st.components.v1.html
# instead - same workspace, screens edited with ordinary inputs. Import
# defensively so a deployment with neither still runs every other page.
try:
    from groundwater.depth_spine import (
        build_view as build_spine_view,
        component_available,
        depth_spine,
        render_static,
        static_build_available,
    )
    from groundwater.depth_spine.view import SpineInputs

    SPINE_ERROR = ""
except Exception as _spine_exc:  # noqa: BLE001 - optional import  # pragma: no cover
    build_spine_view = depth_spine = SpineInputs = None
    component_available = static_build_available = lambda: False
    render_static = None
    SPINE_ERROR = str(_spine_exc)

#: Chip colour per verdict state. Both failures are red - neither supply may
#: be accepted - and the label carries the difference between them. An
#: unproven result is blue: it is a question, not a finding.
_VERDICT_CHIP = {
    "health_fail": "gw-chip-red",
    "national_fail": "gw-chip-red",
    "indeterminate": "gw-chip-blue",
    "aesthetic": "gw-chip-amber",
    "pass": "gw-chip-green",
}

# ---------------------------------------------------------------------------
# Page setup and branding
# ---------------------------------------------------------------------------

_BRAND_DIR = Path(groundwater.__file__).resolve().parent / "data" / "brand"


def _brand(name: str) -> str | None:
    path = _BRAND_DIR / name
    return str(path) if path.exists() else None


_ICON = _brand("icon.png")
_LOGO = _brand("logo.png")

# Design language: the sustaintheworld style. A near-black ground with
# cards one step lighter, one neon green accent, Space Grotesk for headings
# and controls, Inter for text and IBM Plex Mono for the small uppercase
# labels. The printed reports keep their own house style (config.HouseStyle).
_GREEN = "#7CFC00"        # primary green
_GREEN_HOVER = "#9FFF4D"
_ON_GREEN = "#051000"     # ink on a green surface
_BG = "#0a0a0a"
_CARD = "#1a1a1a"
_CARD_ALT = "#141414"
_TEXT = "#ffffff"
_TEXT_SOFT = "#b0b0b0"
_LINE = "rgba(124, 252, 0, 0.18)"
_LINE_SOFT = "rgba(124, 252, 0, 0.08)"
_AMBER = "#f2b705"
_BLUE = "#2ea3e0"
_SALMON = "#e07a5f"
_EMERALD = "#3ad07a"
_BAR_COLORS = [_GREEN, _EMERALD, _BLUE, _AMBER, _SALMON, "#8c8c8c"]

CONFIG = Config()
IN_BROWSER = sys.platform == "emscripten"  # running under Pyodide (GitHub Pages demo)

# Static catalogues, parsed once per session (the script reruns on
# every widget interaction; without caching each rerun re-reads the
# bundled CSVs).
@st.cache_data
def cached_rates():
    return load_rates()


@st.cache_data
def cached_checklists():
    return load_checklists()


@st.cache_data
def cached_separation_distances():
    return load_separation_distances()


@st.cache_data
def cov_population():
    return load_district_population()


@st.cache_data
def cov_crosswalk():
    return load_chiefdom_district()


@st.cache_data
def cov_chiefdom_population():
    """(population per chiefdom polygon, census members) from the 2015 census."""
    return chiefdom_population()


def content_token(data: bytes) -> str:
    """A name for what a file holds, whatever it is called or wherever it came from."""
    return hashlib.sha256(bytes(data)).hexdigest()


@st.cache_resource(show_spinner=False, max_entries=8)
def wpdx_points(token: str, _csv_text: str | None = None, _records=None):
    """(water points, rows set aside) from a WPdx export or a live pull.

    Keyed on the content's token, so every session that loads the same
    export shares one parse. A resource, not data: a national pull is tens
    of thousands of points, and copying them out of a data cache on every
    rerun would cost what the cache saves. Nothing downstream changes them.
    """
    skipped: list = []
    if _csv_text is not None:
        return parse_wpdx_csv(_csv_text, skipped=skipped), skipped
    return parse_wpdx_records(_records, skipped=skipped), skipped


@st.cache_resource(show_spinner=False, max_entries=8)
def _cov_join(token: str, resolution: str, _points):
    """The chiefdom/district join for the coverage page, done once per source.

    The join is the expensive step on this page and the year and growth-rate
    inputs rerun it on every keystroke. It is keyed on the token of the
    content the points were read from (``content_token``), so the same export
    is joined once for every session that loads it. It used to be keyed on
    the points list's identity and to keep its memo in the session state of
    whichever session called it, which a cache shared by every session has
    no business touching.
    """
    if resolution == "chiefdom":
        return group_points_by_chiefdom(_points, cov_polys())
    return group_points_by_district(_points, cov_polys(), cov_crosswalk())


def cov_polys():
    """Chiefdom polygons for coverage point-in-polygon (numpy-heavy, cached by
    reference)."""
    return load_chiefdom_polys()


@st.cache_data
def cached_districts():
    """(provinces, [(district, province), ...]) from the bundled table."""
    import csv as _csv

    from groundwater._resources import bundled_text

    rows = list(_csv.DictReader(bundled_text("sl_districts.csv").splitlines()))
    provinces: list[str] = []
    for row in rows:
        if row["province"] not in provinces:
            provinces.append(row["province"])
    return provinces, [(row["district"], row["province"]) for row in rows]


def _file_stem(name: str) -> str:
    """A filename stem from a community name typed by a person.

    Anything a filesystem would object to becomes a hyphen, so "Rokel /
    Masiaka" cannot write into a directory nobody asked for.
    """
    stem = _re.sub(r"[^A-Za-z0-9]+", "-", str(name or "")).strip("-").lower()
    return stem or "site"


def workdir() -> Path:
    if "workdir" not in st.session_state:
        st.session_state.workdir = Path(tempfile.mkdtemp(prefix="gw_"))
    return st.session_state.workdir


def save_upload(uploaded) -> Path:
    # Use only the basename of the browser-supplied name so a crafted filename
    # (e.g. "../../x") cannot write outside the per-session working directory.
    safe_name = Path(uploaded.name).name or "upload"
    path = workdir() / safe_name
    path.write_bytes(uploaded.getbuffer())
    return path


def sample_data_dir() -> Path | None:
    """Bundled sample datasets, when present (repo checkout or web demo)."""
    here = Path(__file__).resolve().parent
    for candidate in (
        here.parent / "examples" / "data",
        here / "examples" / "data",
        Path("examples/data"),
    ):
        if candidate.is_dir():
            return candidate
    return None


class KeptFile:
    """An uploaded file kept while its page is off screen.

    Stands in for Streamlit's ``UploadedFile`` where the pages use one: a
    name, and the bytes through ``getvalue``, ``getbuffer`` and ``read``.
    """

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data
        self.size = len(data)

    def getvalue(self) -> bytes:
        return self._data

    def getbuffer(self) -> memoryview:
        return memoryview(self._data)

    def read(self) -> bytes:
        return self._data


def kept_upload(label: str, key: str, **kwargs):
    """``st.file_uploader`` whose file outlives a visit to another page.

    Streamlit forgets an uploader's file at the end of a run that does not
    draw it, and only the page on screen is drawn, so a workbook uploaded
    here was gone by the time its page came back. The file is kept under
    ``<key>_kept`` and handed back, with a caption saying so, while the page
    has come back to an empty uploader; a Remove button beside the caption
    does what clearing the uploader did. An uploader that holds a file, or
    that was on screen holding one and is empty now because its user
    cleared it, is taken at its word. Returns what ``st.file_uploader``
    would: a file, a list of files with ``accept_multiple_files``, or None.
    """
    session = st.session_state
    store = f"{key}_kept"
    returning = key not in session
    value = st.file_uploader(label, key=key, **kwargs)
    many = bool(kwargs.get("accept_multiple_files"))
    files = list(value or []) if many else ([value] if value is not None else [])
    kept = session.get(store) or {}
    if files:
        ids = [getattr(f, "file_id", None) or (f.name, f.size) for f in files]
        if kept.get("ids") != ids or kept.get("restored"):
            session[store] = {"ids": ids,
                              "files": [(f.name, bytes(f.getvalue())) for f in files]}
        return value
    # empty and on screen last run: cleared by its user, unless it has been
    # empty since the page came back and the kept file stood in for it
    if not returning and not kept.get("restored"):
        session.pop(store, None)
        return value
    restored = [KeptFile(name, data) for name, data in kept.get("files", [])]
    if not restored:
        return value
    session[store] = {**kept, "restored": True}
    note, remove = st.columns([5, 1])
    note.caption(
        f"Using {', '.join(f.name for f in restored)}, uploaded earlier in this "
        "session. Upload another file to replace it."
    )
    if remove.button("Remove", key=f"{key}_forget"):
        session.pop(store, None)
        return value
    return restored if many else restored[0]


def choose_input(label: str, key: str, types: list[str], samples: list[str]) -> Path | None:
    """File uploader with an optional bundled-sample fallback.

    Returns the path of the uploaded file, the chosen sample, or None.
    """
    upload = kept_upload(label, f"upload_{key}", type=types)
    if upload is not None:
        # remember the raw upload so it can be saved with the project and the
        # analysis recomputed on load without re-uploading
        st.session_state[f"src_{key}"] = {
            "name": upload.name, "bytes": bytes(upload.getvalue())
        }
        return save_upload(upload)
    root = sample_data_dir()
    if root is not None:
        available = [s for s in samples if (root / s).exists()]
        if available:
            none_option = "(or pick a bundled sample to try)"
            pick = st.selectbox(
                "No file uploaded yet", [none_option] + available, key=f"sample_{key}"
            )
            if pick != none_option:
                st.session_state[f"src_{key}"] = {"sample": pick}
                return root / pick
    return None


def show_flags(flags, collapse_after: int = 4) -> None:
    """Data check flags, folded into an expander when there are many."""
    flags = list(flags)
    if not flags:
        return

    def _render(items) -> None:
        for flag in items:
            text = str(flag)
            if flag.level == "error":
                st.error(text)
            elif flag.level == "warning":
                st.warning(text)
            else:
                st.info(text)

    if len(flags) <= collapse_after:
        _render(flags)
        return
    worst = "error" if any(f.level == "error" for f in flags) else (
        "warning" if any(f.level == "warning" for f in flags) else "info"
    )
    icon = {"error": "🚫", "warning": "⚠️", "info": "ℹ️"}[worst]
    with st.expander(f"{icon} Data checks ({len(flags)})", expanded=(worst == "error")):
        _render(flags)


def offer_download(path: Path, label: str, keep: bool = True) -> None:
    """Download button for a produced file, and remember it as a deliverable.

    Build buttons are true for exactly one rerun, so a report's download
    button used to vanish the moment the user touched anything else and the
    report had to be rebuilt. Remembering it keeps it available from the
    Deliverables panel for the rest of the session.
    """
    if keep:
        st.session_state.setdefault("artifacts", {})[label] = str(path)
    with open(path, "rb") as fh:
        st.download_button(label, fh.read(), file_name=path.name,
                           key=f"dl_{_html.escape(label)}_{path.name}")


def _offer_raster(picture: Path) -> None:
    """Download button for the GeoTIFF a map kept beside its picture.

    Only an interpolated surface clipped to the surveyed ground is kept
    (mapping.maps._keep_surface), so a map without one offers nothing
    rather than a raster of extrapolated or lower-bound values.
    """
    raster = picture.with_suffix(".tif")
    if raster.exists():
        offer_download(raster, f"Download {raster.name} (GeoTIFF)")


def _deliverables() -> list[tuple[str, Path]]:
    """Everything built this session that still exists on disk."""
    out = []
    for label, raw in (st.session_state.get("artifacts") or {}).items():
        path = Path(raw)
        if path.exists():
            out.append((label, path))
    return out


def _working(message: str):
    """Status block for a slow operation, so the app never looks frozen."""
    return st.status(message, expanded=False)


@st.cache_data(show_spinner=False, max_entries=32)
def _parsed(kind: str, name: str, data: bytes, _path: str):
    """A data file read by its reader, cached on its name and content.

    The path is not part of the key: two sessions that upload the same
    workbook get the same reading, and one that uploads a changed workbook
    under the same name gets a new one. The reader still reads the file on
    disk, which holds ``data``, so a reading is exactly what the reader
    makes of that file.
    """
    path = Path(_path)
    skipped: list = []
    if kind == "ves":
        return read_ves_workbook(path, skipped=skipped), skipped
    if kind == "pump":
        reader = read_pumping_docx if path.suffix == ".docx" else read_pumping_workbook
        return reader(path), skipped
    if kind == "wq":
        return read_quality_workbook(path), skipped
    if kind == "log":
        return read_drilling_workbook(path), skipped
    raise ValueError(f"no reader for {kind!r}")


def parse_source(kind: str, path: Path):
    """(reading, sheets set aside) for a data file, or (None, []) on failure.

    ``kind`` is ``"ves"``, ``"pump"``, ``"wq"`` or ``"log"``. A malformed or
    mislabelled workbook shows a readable message instead of crashing the
    page. Each call returns a copy, so a page can fill in what the sheet
    left blank (a pumping test's discharges) without touching the cache.
    """
    try:
        return _parsed(kind, path.name, path.read_bytes(), str(path))
    except Exception as exc:  # noqa: BLE001 - a bad workbook is an error, not a crash
        st.error(
            f"Could not read {path.name}: {exc}. Check that the file "
            "follows the standard template (Templates page)."
        )
        return None, []


@st.cache_data(show_spinner=False, max_entries=128)
def _drawn(draw_id: str, args: tuple, kwargs: dict, _draw) -> dict[str, bytes]:
    """The files a drawing function writes, by suffix, cached on its inputs.

    The inputs are hashed by content (Streamlit hashes arrays and objects by
    what they hold), so a figure is drawn once for each distinct set of
    inputs, not once per rerun. ``draw_id`` names the function, which is
    passed separately because the function itself is not hashed.
    """
    with tempfile.TemporaryDirectory(prefix="gw_fig_") as tmp:
        target = Path(tmp) / "figure.png"
        _draw(*args, path=target, **kwargs)
        return {p.suffix: p.read_bytes() for p in Path(tmp).iterdir()
                if p.stem == "figure"}


def figure(draw, *args, file_name: str, **kwargs) -> Path:
    """Draw a figure through the cache and put it in the working folder.

    ``draw`` is one of the toolkit's plotting functions, called as
    ``draw(*args, path=..., **kwargs)``. Returns the picture's path in this
    session's working folder, where a download button or a report can find
    it, with any file the function keeps beside it (a map's GeoTIFF). A
    sibling the drawing did not make this time is removed, as the mapping
    functions remove a stale one themselves.
    """
    files = _drawn(f"{draw.__module__}.{draw.__qualname__}", args, kwargs, draw)
    picture = workdir() / file_name
    for suffix in {".png", ".tif"} | set(files):
        out = picture.with_suffix(suffix)
        blob = files.get(suffix)
        if blob is None:
            out.unlink(missing_ok=True)
        elif not out.exists() or out.read_bytes() != blob:
            out.write_bytes(blob)
    return picture


def site_from_state() -> SiteMetadata:
    """Site metadata from the shared sidebar site details."""
    get = st.session_state.get

    def num(key):
        value = get(key, 0.0)
        return float(value) if value else None

    return SiteMetadata(
        community=get("meta_community", "") or "",
        chiefdom=get("meta_chiefdom", "") or "",
        district=get("meta_district", "") or "",
        client=get("meta_client", "") or "",
        project=get("meta_project", "") or "",
        contractor=get("meta_contractor", "") or "",
        supervisor=get("meta_supervisor", "") or "",
        date=get("meta_date", "") or "",
        easting=num("meta_easting"),
        northing=num("meta_northing"),
        # "Zone 28" copied into the zone cell is the zone 28, and a cell this
        # cannot read leaves the zone unrecorded - SiteMetadata.utm then
        # infers it from the easting and the checks say so - rather than
        # defaulting to 29N. A zone relabelled instead of read keeps the
        # easting and moves the site 660 km into the next zone.
        utm_zone=parse_utm_zone(get("meta_zone", "29N")),
    )


def _project_summary() -> dict:
    """Headline summary of the current project, saved for the portfolio view."""
    site = site_from_state()
    summary = {
        "community": site.community, "district": site.district,
        "chiefdom": site.chiefdom, "easting": site.easting,
        "northing": site.northing, "utm_zone": site.utm_zone,
    }
    log = st.session_state.get("drilling_log")
    if log is not None:
        if log.status:
            summary["status"] = log.status
        if log.total_depth_m:
            summary["total_depth_m"] = log.total_depth_m
    analysis = st.session_state.get("pump_analysis")
    yr = analysis.yield_recommendation if analysis is not None else None
    if yr is not None and yr.safe_yield_m3_per_h:
        summary["safe_yield_m3_per_h"] = yr.safe_yield_m3_per_h
    wq = st.session_state.get("wq_assessment")
    if wq is not None:
        # The full five-state verdict. The old three states folded a national
        # standard failure into "aesthetic" and had no way to say "we cannot
        # tell", so a breached or unevaluable supply read as merely a matter
        # of taste. The schema marker lets a reader tell a new file from an
        # old one and translate the old vocabulary safely.
        summary["water_verdict"] = wq.verdict_state
        summary["verdict_schema"] = VERDICT_SCHEMA
    cost = st.session_state.get("cost_estimate")
    if cost is not None:
        summary["cost_per_meter_usd"] = cost.cost_per_meter_usd
    if "ves_results" in st.session_state and "status" not in summary:
        summary["status"] = "sited"
    return {k: v for k, v in summary.items() if v not in (None, "")}


# ---------------------------------------------------------------------------
# Certification gate
# ---------------------------------------------------------------------------

def _loaded_sources() -> dict:
    """The files this project was built from, keyed by upload role.

    The same `src_*` keys the project file saves and `recompute_results`
    reads, handed to the gate so it can tell a report drawn from the
    bundled examples from one drawn from this site's own work.
    """
    return {
        str(key)[len("src_"):]: value
        for key, value in st.session_state.items()
        if str(key).startswith("src_") and isinstance(value, dict)
    }


def _project_state() -> dict:
    """The session, keyed as groundwater.readiness expects it."""
    return {
        "site": site_from_state(),
        "sources": _loaded_sources(),
        "drilling_log": st.session_state.get("drilling_log"),
        "pump_analysis": st.session_state.get("pump_analysis"),
        "wq_assessment": st.session_state.get("wq_assessment"),
        "borehole_design": st.session_state.get("borehole_design"),
        "cost_estimate": st.session_state.get("cost_estimate"),
    }


def _overrides_for(report: str) -> dict:
    """Overrides the analyst recorded for this report, from session state."""
    return st.session_state.get(f"_override_{report}") or {}


def report_gate(report: str, scope: str = ""):
    """Show what this report can and cannot stand behind, and return it.

    Deliberately never disables the button. An analyst who needs an interim
    document will produce one either way; the useful thing is that the
    document says what it rests on, so this renders the outstanding items,
    offers a recorded override, and hands the result to the report builder
    to stamp on its own cover.

    ``scope`` distinguishes two gates for the same report kind on one run -
    the widget keys have to differ, while the recorded override does not:
    an override of the costing evidence is an override wherever it is shown.
    """
    keyed = f"{report}_{scope}" if scope else report
    readiness = assess_readiness(_project_state(), report, _overrides_for(report))
    if readiness.state == "ready":
        st.success("Ready to certify: " + readiness.summary)
    else:
        renderer = st.warning if readiness.state == "ready_with_overrides" else st.error
        renderer(readiness.summary)
        with st.expander("What this report cannot yet stand behind", expanded=True):
            for req in readiness.unmet:
                st.markdown(f"**{req.title}** — {req.detail}")
            for req in readiness.overridden:
                who = f" ({req.override_by})" if req.override_by else ""
                st.markdown(
                    f"**{req.title}** — {req.detail}  \n"
                    f"_Overridden{who}: {req.override_reason or 'no reason recorded'}_"
                )
            if readiness.unmet:
                st.caption(
                    "The report will still be produced, stamped PROVISIONAL and "
                    "listing these items. To issue it as an interim document "
                    "instead, record who is issuing it and why."
                )
                with st.form(f"override_{keyed}"):
                    by = st.text_input("Issued by", key=f"ovr_by_{keyed}")
                    reason = st.text_area("Reason", key=f"ovr_why_{keyed}")
                    picked = st.multiselect(
                        "Requirements to issue on override",
                        [r.key for r in readiness.unmet],
                        format_func=lambda k: dict(
                            (r.key, r.title) for r in readiness.unmet)[k],
                        key=f"ovr_keys_{keyed}",
                    )
                    if st.form_submit_button("Record override"):
                        # A named issuer is the whole point of an override: it
                        # is somebody's authority standing in for the missing
                        # evidence, and an unsigned one is nobody's.
                        if not picked or not reason.strip() or not by.strip():
                            st.warning(
                                "An override needs the requirement(s) it "
                                "covers, who is issuing the report, and why."
                            )
                        else:
                            st.session_state[f"_override_{report}"] = {
                                key: {"reason": reason.strip(), "by": by.strip()}
                                for key in picked
                            }
                            st.rerun()
    if readiness.assumptions:
        st.caption("Assumptions carried into this report: "
                   + "; ".join(readiness.assumptions))
    return readiness


def _apply_latlon() -> None:
    """Convert the decimal lat/lon entry into the UTM site fields.

    Runs as a widget callback (before the script reruns) so it can write
    the meta_easting / meta_northing / meta_zone widget state safely. Field
    crews read decimal degrees off a phone or handheld GPS; this removes the
    UTM-typing friction and the wrong-zone errors it causes.
    """
    raw = (st.session_state.get("latlon_paste", "") or "").strip()
    lat = st.session_state.get("latlon_lat", 0.0)
    lon = st.session_state.get("latlon_lon", 0.0)
    assumed = ""
    if raw:
        # read_latlon reads N/S/E/W as signs and degrees and minutes as
        # degrees and minutes. Discarding the letter and taking the number at
        # face value put every W longitude 26 degrees east of the site,
        # silently and on the wrong side of the continent, and "8 27.942 N"
        # came back as latitude 27.942. What it refuses, and what it assumed
        # where it read a longitude as west, comes back as a sentence, which
        # is shown rather than dropped.
        reading = read_latlon(raw)
        if not reading.ok:
            st.session_state["latlon_error"] = (
                f"{reading.message} Enter 'lat, lon' in decimal degrees - "
                "8.4657, -13.2317 or 8.4657 N, 13.2317 W - or in degrees and "
                "minutes, 8 27.942 N, 13 13.902 W."
            )
            st.session_state["latlon_assumed"] = ""
            return
        lat, lon = reading.lat, reading.lon
        assumed = reading.message
    if not lat or not lon:
        st.session_state["latlon_error"] = (
            "Enter a latitude and longitude (or paste them) first."
        )
        st.session_state["latlon_assumed"] = ""
        return
    utm = geographic_to_utm(lat, lon)
    if utm.zone not in (28, 29) or utm.hemisphere != "N":
        # The site fields hold Sierra Leone's two zones. Labelling this
        # easting 28N or 29N would relabel the position rather than convert
        # it, and land the site inside the country: an unsigned 13.2317
        # projected in zone 33 and relabelled 29N used to come out 270 km
        # east of Freetown with nothing said.
        st.session_state["latlon_error"] = (
            f"{lat:.4f}, {lon:.4f} falls in UTM zone {utm.zone}"
            f"{utm.hemisphere}, outside Sierra Leone's 28N and 29N, so it "
            "cannot be stored as a site position. Check the coordinates - a "
            "western longitude needs its minus sign or its W."
        )
        st.session_state["latlon_assumed"] = ""
        return
    st.session_state["meta_easting"] = float(round(utm.easting))
    st.session_state["meta_northing"] = float(round(utm.northing))
    st.session_state["meta_zone"] = f"{utm.zone}N"
    st.session_state["latlon_error"] = ""
    st.session_state["latlon_assumed"] = assumed


# ---------------------------------------------------------------------------
# Project file: save and restore the whole working state
# ---------------------------------------------------------------------------

def _inversion_cache_now() -> dict:
    """The inversions on show, as the project file saves them.

    Taken from the results rather than kept alongside them, so what is
    saved is always what the pages show, whichever of the VES page or a
    project load inverted it.
    """
    ves = st.session_state.get("ves_results")
    if not ves:
        return {}
    entries = {}
    for sounding, result in zip(ves[0], ves[1], strict=True):
        key = inversion_key(sounding, CONFIG.ves)
        entry = cache_entry(key, result) if key else None
        if entry is not None:
            entries[key] = entry
    return entries


#: Buttons whose keys start with a prefix the project file saves. Between
#: clicks a button holds False in session state, so a project saved while
#: its page was drawn carried it, and Streamlit refuses a button's value set
#: through session state: loading that file with the guided start on screen
#: took the page down. Files saved before this carry them, so they are left
#: out on load as well as on save.
UNSAVED_BUTTONS = frozenset({
    "wiz_back", "wiz_next", "wiz_restart", "wiz_cost_run", "wiz_run_ves",
})


def project_file_bytes() -> bytes:
    """Serialize the widget state that makes up a project."""
    session = {key: value for key, value in st.session_state.items()
               if key not in UNSAVED_BUTTONS}
    session["inversion_cache"] = _inversion_cache_now()
    return serialize_project(session, groundwater.__version__)


def _load_project() -> None:
    """Apply an uploaded project file (button callback, runs pre-render)."""
    upload = st.session_state.get("project_upload")
    if upload is None:
        return
    try:
        updates = deserialize_project(upload.getvalue())
    except ValueError:
        st.session_state.project_load_error = True
        return
    # a loaded project fully replaces the working state: drop the previous
    # data sources, recompute inputs and computed results first, so a stale
    # dataset from earlier in the session cannot bleed into the loaded project
    for stale in stale_on_load(st.session_state):
        st.session_state.pop(stale, None)
    for result_key in (
        "ves_results", "pump_analysis", "wq_assessment", "borehole_design",
        "drilling_log", "cost_estimate", "cost_artifacts",
        "wp_result", "handover_built", "_design_follows_page",
        # cleared too, so a project with no sources at all cannot inherit the
        # previous project's rebuild banner
        "recompute_diagnostics",
    ):
        st.session_state.pop(result_key, None)
    overrides = updates.pop("rates_overrides", None)
    # a file saved in a newer project format says so instead of half-loading
    st.session_state["project_load_warnings"] = updates.pop("warnings", []) or []
    committee = updates.pop("committee", None)
    sources = updates.pop("sources", None)
    # the file names it "asset"; the session key it belongs under is the one
    # serialize_project reads back, so the round trip has to be closed here
    asset = updates.pop("asset", None)
    for key, value in updates.items():
        if key not in UNSAVED_BUTTONS:
            st.session_state[key] = value
    if isinstance(overrides, dict):
        st.session_state.rates_overrides = overrides
    if isinstance(asset, dict) and asset:
        st.session_state["asset_record"] = asset
    # restore the saved data files and flag a recompute so the analyses and
    # reports are rebuilt without re-uploading
    if isinstance(sources, dict) and sources:
        for skey, src in sources.items():
            st.session_state[f"src_{skey}"] = src
        st.session_state["_recompute_pending"] = True
    # restore the WASH committee: set the data_editor base and clear its
    # stale edit delta so the saved rows show cleanly after loading
    if isinstance(committee, list) and committee:
        st.session_state["ho_committee_rows"] = committee
        st.session_state["ho_committee_data"] = committee
        st.session_state.pop("ho_committee", None)
    # reset the rate editor so it shows the loaded values
    st.session_state.pop("rates_editor", None)
    st.session_state.project_loaded = True
    # protect restored inputs from the prefill-reset checks for one run
    st.session_state.project_just_loaded = True
    # the wizard costing block only executes on its step, so it carries
    # its own grace marker, consumed when that block first runs
    st.session_state["_wiz_load_grace"] = True


# ---------------------------------------------------------------------------
# Navigation: one workspace, pages grouped by lifecycle stage
# ---------------------------------------------------------------------------

NAV_GROUPS: list[tuple[str, list[str]]] = [
    ("Project", ["Overview", "Guided start", "Site maps"]),
    ("Investigation", ["Geophysics (VES)", "Borehole design", "Depth Spine",
                       "Scanned sheets"]),
    ("Testing", ["Pumping test", "Water quality"]),
    ("Delivery", ["Costing & BoQ", "Procurement", "Supervision", "Handover",
                  "Templates"]),
    ("Area analysis", ["Water points", "Coverage gap", "Portfolio",
                       "Asset registry"]),
]
_ALL_PAGES = [p for _, pages in NAV_GROUPS for p in pages]
DEFAULT_PAGE = "Overview"


def _page_key(name: str) -> str:
    return "page_" + "".join(c if c.isalnum() else "_" for c in name.lower())


def _group_key(group: str) -> str:
    return "nav_" + "".join(c if c.isalnum() else "_" for c in group.lower())


def _nav_changed(group_key: str) -> None:
    """A page picked in one sidebar group becomes the single active page."""
    choice = st.session_state.get(group_key)
    if choice:
        st.session_state["nav"] = choice


def _goto(page: str) -> None:
    st.session_state["nav"] = page


def _next_step(label: str, page: str, note: str = "", key: str = "") -> None:
    """Bottom-of-page route to the next lifecycle step.

    Every page except the Overview used to dead-end: having read the
    recommended drilling depth there was no way on to Costing except hunting
    through the sidebar.

    ``key`` disambiguates when two pages route to the same destination - the
    key is otherwise derived from the destination alone, which would collide.
    """
    st.divider()
    col_a, col_b = st.columns([3, 1])
    col_a.caption(note or f"Next: {page}")
    col_b.button(label, key=key or f"next_{_page_key(page)}", width="stretch",
                 on_click=_goto, args=(page,))


def _spine_iframe(html: str, height: int) -> None:
    """Put the static workspace in an iframe, whichever API this runtime has.

    ``st.components.v1.html`` is deprecated in favour of ``st.iframe``, but the
    in-browser demo pins an older Streamlit that has only the former, and the
    project supports streamlit>=1.57. Use whichever exists.
    """
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:  # pragma: no cover - older runtimes, including the browser demo
        components.html(html, height=height, scrolling=True)


def _spine_frame_height(view: dict) -> int:
    """Tall enough for the workspace without a scrollbar in the common case.

    The section is a fixed-height track; what varies is how far the rail runs,
    and the water-quality stage is the longest of the three. Erring tall costs
    whitespace, erring short costs a nested scrollbar, so err tall.
    """
    base = 780
    if view.get("quality"):
        base = 1180
    return base


def _spine_screen_editor(view: dict, state_key: str, placed) -> None:
    """Edit the screened intervals without the drag handles.

    The static workspace cannot hand anything back, so the same edit is offered
    as numbers. It goes through design_borehole exactly as a dragged interval
    does - this is a different gesture, not a different calculation.
    """
    screens = view["design"]["screens"]
    limits = view["section"]["screenLimits"]
    with st.expander("Edit the screened intervals", expanded=False):
        st.caption(
            "Dragging needs the full application; here the same intervals are "
            "typed. They are re-derived through the same design rules, and "
            "anything that does not fit is clipped or dropped with a flag."
        )
        edited: list[tuple[float, float]] = []
        for index, screen in enumerate(screens):
            col_top, col_base = st.columns(2)
            top = col_top.number_input(
                f"Screen {index + 1} top (m)",
                min_value=float(limits["top"]),
                max_value=float(limits["base"]),
                value=float(screen["top"]),
                step=0.5,
                key=f"{state_key}_top_{index}",
            )
            base = col_base.number_input(
                f"Screen {index + 1} base (m)",
                min_value=float(limits["top"]),
                max_value=float(limits["base"]),
                value=float(screen["base"]),
                step=0.5,
                key=f"{state_key}_base_{index}",
            )
            edited.append((float(top), float(base)))

        apply_col, reset_col = st.columns([1, 1])
        if apply_col.button("Apply to the design", key=f"{state_key}_apply") and edited != placed:
            st.session_state[state_key] = edited
            st.rerun()
        if placed and reset_col.button(
            "Back to the generated design", key=f"{state_key}_reset_editor"
        ):
            del st.session_state[state_key]
            st.rerun()


def _band(value, bands: list[tuple[float, str]], above: str) -> str:
    """First label whose upper bound the value falls under, else ``above``.

    A number with no interpretation is not useful to a drilling supervisor:
    12 percent model fit or 4 m2/day transmissivity mean nothing on their own.
    """
    if value is None:
        return ""
    for limit, label in bands:
        if float(value) < limit:
            return label
    return above


def _status_chip() -> tuple[str, str]:
    """(label, css class) for the current project's lifecycle status."""
    summary = _project_summary()
    if "status" not in summary:
        return "New", "gw-chip-grey"
    status = classify_status(summary)
    label = {
        "successful": "Successful",
        "dry": "Dry / failed",
        "sited": "Sited",
    }.get(status) or STATUS_LABELS.get(
        status, str(summary.get("status", "")).title()
    )
    css = {
        "successful": "gw-chip-green",
        "dry": "gw-chip-red",
        "sited": "gw-chip-amber",
    }.get(status, "gw-chip-grey")
    return label, css


def app_config() -> Config:
    """Config with the sidebar branding applied (per rerun, not global)."""
    cfg = Config()
    cfg.style.organisation = st.session_state.get("org_name", "") or ""
    cfg.style.organisation_details = st.session_state.get("org_details", "") or ""
    return cfg


def reported_pump_intake(analysis) -> float | None:
    """The pump intake the pumping report prints, for the design to use.

    The pumping report sets the intake at the deeper of the test day's depth
    and the drought year's, from the month and swing chosen under "Through
    the year" (hydraulics-6); the design took the test day's alone, so with
    a swing entered the drawing and the completion report named one depth
    and the pumping report another. The browser app had the same fault.
    """
    if analysis is None or analysis.yield_recommendation is None:
        return None
    pumping = app_config().pumping
    month = st.session_state.get("seasonal_month")
    if month is None:
        month = month_of(analysis.test.site.date)[0]
    seasonal = seasonal_yield(
        analysis, pumping, month=(month or None),
        annual_range_m=st.session_state.get("seasonal_range", pumping.seasonal_allowance_m),
    )
    return pump_intake_depth(analysis, seasonal)[0]


#: The WASH committee table the Handover page starts from.
DEFAULT_COMMITTEE = [
    {"Role": "Chair", "Name": "", "Phone": ""},
    {"Role": "Secretary", "Name": "", "Phone": ""},
    {"Role": "Treasurer", "Name": "", "Phone": ""},
    {"Role": "Caretaker", "Name": "", "Phone": ""},
]


def spine_screens_key(log) -> str:
    """Where the screens placed on the Depth Spine are kept, per borehole.

    Keyed by the borehole so one hole's screens never land on another's.
    """
    return f"spine_screens_{log.borehole_ref or 'bh'}"


def _intake_floor(analysis):
    if analysis and analysis.yield_recommendation:
        return pump_intake_floor(analysis.yield_recommendation,
                                 CONFIG.pumping.pump_submergence_min_m)
    return None


def page_design(log, analysis, swl_input):
    """The design the Borehole design page draws from a drilling log.

    Designed against the pumping test when the Pumping test page has run
    one: its static water level unless the analyst typed another
    (``swl_input``), and the intake the pumping report prints.
    """
    test_swl = analysis.test.static_water_level_m if analysis else None
    return design_borehole(
        log=log,
        static_water_level_m=swl_input or test_swl,
        pump_intake_m=reported_pump_intake(analysis),
        pump_intake_floor_m=_intake_floor(analysis),
        rules=CONFIG.design,
    )


def spine_design(log, analysis, placed):
    """The design with the screens the analyst placed on the Depth Spine."""
    return design_borehole(
        log=log,
        static_water_level_m=(
            analysis.test.static_water_level_m if analysis else None
        ),
        pump_intake_m=reported_pump_intake(analysis),
        pump_intake_floor_m=_intake_floor(analysis),
        rules=CONFIG.design,
        screens_m=placed,
    )


def cost_design_sig(design, use_design: bool) -> str:
    """What the costing depth was last set from.

    A keyed widget ignores a changed ``value=`` once it has state, so the
    depth is reset when the design source changes or is toggled. A string,
    so the project file carries it and a loaded project's depth is not
    wiped by a false "source changed".
    """
    return f"{bool(use_design)}:{float(design.total_depth_m) if design else 0.0:.1f}"


def fill_defaults() -> None:
    """Project state a page used to fill on every run, filled when missing.

    The Costing page kept the working rate table in ``rates_overrides`` and
    the Handover page the committee in ``ho_committee_data``, drawing them
    on every run whichever page was on screen, so a project saved without
    visiting either still carried both. Only the page on screen runs now.
    """
    session = st.session_state
    base = cached_rates()
    overrides = session.get("rates_overrides") or {}
    if any(r.code not in overrides for r in base):
        session["rates_overrides"] = {
            r.code: float(overrides.get(r.code, r.unit_cost_usd)) for r in base
        }
    if "ho_committee_data" not in session:
        session["ho_committee_data"] = committee_records(
            session.get("ho_committee_rows", DEFAULT_COMMITTEE))


def refresh_derived(page: str | None = None) -> None:
    """Bring up to date the results that follow from other results.

    Every page used to run on every rerun, so the Borehole design page
    re-derived the design from the pumping test whichever page was on
    screen, the Depth Spine laid its screens over it, and the Costing page
    reset its depth when the design's changed. Only the page on screen runs
    now, so those steps run here, in the same order: before the page, so it
    reads current results, and after it, so the project file saved from this
    run carries them. ``page`` is the page that has just run; its widgets
    are drawn, and Streamlit refuses a write to a drawn widget's value, so
    the step that page does itself is left to it.
    """
    session = st.session_state
    analysis = session.get("pump_analysis")
    # The box shows the level the design uses: the test's, unless the
    # analyst typed another. A box still at 0.0, or at the level last
    # prefilled, has not been typed over and follows the test.
    test_swl = analysis.test.static_water_level_m if analysis else None
    if test_swl is not None and page != "Borehole design":
        prefill = round(float(test_swl), 2)
        if session.get("design_swl") in (
            None, 0.0, session.get("design_swl_prefilled"),
        ):
            session["design_swl"] = prefill
        session["design_swl_prefilled"] = prefill

    log = session.get("drilling_log")
    if log is not None:
        # the design page's design, while that page has a log selected, as
        # it recomputed it on every run...
        if session.get("_design_follows_page"):
            session["borehole_design"] = page_design(
                log, analysis, session.get("design_swl"))
        # ...and an analyst-placed design is the project's design: the
        # drawing, the bill of quantities and the completion report all
        # follow from the same object
        placed = session.get(spine_screens_key(log))
        if placed and build_spine_view is not None:
            session["borehole_design"] = spine_design(log, analysis, placed)

    if page != "Costing & BoQ":
        design = session.get("borehole_design")
        use_design = design is not None and bool(session.get("cost_use_design", True))
        sig = cost_design_sig(design, use_design)
        if session.get("cost_design_sig") != sig:
            session["cost_design_sig"] = sig
            if not session.get("project_just_loaded"):
                session.pop("cost_depth", None)


def run_ves_inversion(soundings) -> None:
    """Invert and interpret the soundings, storing the shared results.

    A sounding that fails to invert is named in an error and nothing is
    stored, so the last successful result stays in place: it is still the
    best siting answer, and the reports and costing prefill read it.
    """
    results = []
    interps = []
    progress = st.progress(0.0)
    for i, sounding in enumerate(soundings):
        try:
            # looked up on the package at each call rather than imported
            # once: this module outlives a rerun, and the app's tests make
            # one sounding fail by patching groundwater.ves
            result = _ves.invert_sounding(sounding, CONFIG.ves)
            interp = _ves.interpret_model(sounding, result.model, CONFIG.ves)
        except Exception as exc:  # noqa: BLE001 - one bad sounding is an error, not a crash
            # a bar left part full beside the error reads as a run still going
            progress.empty()
            kept = ("The results shown are from the previous successful run."
                    if "ves_results" in st.session_state else "")
            st.error(
                f"Inversion failed for sounding "
                f"{sounding.sounding_id or i + 1}: {exc}. Check its readings "
                f"in the workbook. {kept}".rstrip()
            )
            return
        results.append(result)
        interps.append(interp)
        progress.progress((i + 1) / len(soundings))
    # rank before anything reads interp.rank: the Overview used to render
    # earlier in the run than the VES page that was the only thing ranking
    # them, so it named whichever sounding was parsed first as the drill target
    rank_interpretations(interps)
    st.session_state.ves_results = (soundings, results, interps)
    # only a stored siting result is a source change the wizard costing
    # prefill must follow; a failed run leaves a loaded project's grace
    st.session_state.pop("_wiz_load_grace", None)


def _manual_costing_rules() -> dict:
    """The design rules a manual estimate prices when there is no drawing.

    Without a design the diameters and the seal depth would fall back to
    the costing module's own defaults, so an estimate typed in from a
    depth could disagree with the rules the design page draws by.
    """
    rules = CONFIG.design
    return {
        "borehole_diameter_in": rules.borehole_diameter_in,
        "casing_diameter_in": rules.casing_diameter_in,
        "sanitary_seal_m": rules.sanitary_seal_depth_m,
    }

def compute_cost_estimate(inputs: CostingInputs, rates, **kwargs) -> None:
    """Estimate and build the shared artifacts (chart and BoQ workbook)."""
    estimate = estimate_borehole_cost(inputs, rates, **kwargs)
    st.session_state.cost_estimate = estimate
    chart_path = workdir() / "cost_breakdown.png"
    plot_cost_breakdown(estimate, chart_path, app_config().style)
    boq_path = workdir() / "Bill_of_Quantities.xlsx"
    write_boq_workbook(estimate, boq_path)
    st.session_state.cost_artifacts = (chart_path, boq_path)


# ---------------------------------------------------------------------------
# Overview - the project dashboard
# ---------------------------------------------------------------------------

# Upper bound of the guided start's depth fields. Streamlit raises on a
# prefilled value outside a number_input's range, so anything derived from a
# survey result has to be clamped into it before it is passed in.
WIZ_MAX_DEPTH_M = 300.0


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


def _source_signature(source) -> tuple:
    """A cheap identity for an uploaded file or bundled sample.

    Used to notice that a page is now looking at a different borehole's
    sheet, so inputs typed for the previous one are not carried over.
    """
    if not isinstance(source, dict):
        return ()
    if source.get("sample"):
        return ("sample", str(source["sample"]))
    blob = source.get("bytes") or b""
    return ("upload", str(source.get("name") or ""), len(blob))


def _rows_html(rows: list[tuple[str, str]]) -> str:
    return "".join(
        f"<div class='gw-row'><span>{_html.escape(str(k))}</span>"
        f"<b>{_html.escape(str(v))}</b></div>"
        for k, v in rows
    )


def _stepper_html(steps: list[tuple[str, bool]]) -> str:
    parts = ["<div class='gw-steps'>"]
    for i, (label, done) in enumerate(steps):
        if i:
            joined = steps[i - 1][1] and done
            parts.append(
                "<div class='gw-step-line"
                + ("" if joined else " gw-step-line-todo")
                + "'></div>"
            )
        cls = "gw-step-done" if done else "gw-step-todo"
        dot = "✓" if done else str(i + 1)
        parts.append(
            f"<div class='gw-step {cls}'><span class='gw-step-dot'>{dot}</span>"
            f"<span class='gw-step-label'>{_html.escape(label)}</span></div>"
        )
    parts.append("</div>")
    return "".join(parts)
