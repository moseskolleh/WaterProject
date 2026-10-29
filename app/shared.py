"""Helpers every page of the Streamlit app shares."""

from __future__ import annotations

import hashlib
import html as _html
import re as _re
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import streamlit as st
import streamlit.components.v1 as components

import groundwater
import groundwater.ves as _ves
from groundwater.calibration_sets import apply_set, check_in_force, config_for_sounding
from groundwater.config import Config
from groundwater.costing import (
    CostingInputs,
    depth_spread,
    estimate_borehole_cost,
    load_rates,
    plot_cost_breakdown,
    plot_cost_distribution,
    sample_cost,
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
from groundwater.design import design_borehole, pump_intake_floor, rising_main_choice
from groundwater.models import SiteMetadata
from groundwater.portfolio import classify_status, STATUS_LABELS, VERDICT_SCHEMA
from groundwater.project_io import (
    committee_records,
    deserialize_project,
    serialize_project,
    stale_on_load,
)
from groundwater.readiness import assess_readiness
from groundwater.registry import asset_from_dict
from groundwater.seasonal import month_of, seasonal_yield
from groundwater.supervision import load_checklists, load_separation_distances
from groundwater.text import phrase, phrase_table
from groundwater.bundle import PROGRAMME_KINDS, build_evidence_bundle, document_figures
from groundwater.verification import (
    BOREHOLE_KINDS,
    Issue,
    calibration_facts,
    clean_issue_records,
    document_record,
    evidence_entry,
    issue_records_of,
)
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
    from groundwater.depth_spine.view import SpineCosting, SpineInputs

    SPINE_ERROR = ""
except Exception as _spine_exc:  # noqa: BLE001 - optional import  # pragma: no cover
    build_spine_view = depth_spine = SpineInputs = SpineCosting = None
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


#: The Costing page's inputs and the value each starts at. The page draws its
#: widgets from these, and the Depth Spine prices its design with the same
#: values, so the price signed on the spine is the one the Costing page
#: shows, whether or not that page has been opened yet.
COSTING_DEFAULTS = {
    "cost_overburden": 0.0,
    "cost_distance": 100.0,
    "cost_overheads": 15.0,
    "cost_margin": 20.0,
    "cost_contingency": 10.0,
    "cost_fx": 23.0,
    "cost_handpumps": 1,
    "cost_samples": 1,
    "cost_dev_hours": 6.0,
    "cost_test_hours": 30.0,
    "cost_vat": 0.0,
}


def costing_setting(key: str):
    """A Costing page input: as the page left it, or as it starts."""
    return st.session_state.get(key, COSTING_DEFAULTS[key])


def working_rates():
    """The rate catalogue as the Costing page has it edited: each edited rate
    keeps its relative spread, so the distribution is drawn around it."""
    overrides = st.session_state.get("rates_overrides") or {}
    return [r.with_likely(float(overrides.get(r.code, r.unit_cost_usd)))
            for r in cached_rates()]


def spine_costing():
    """The Costing page's settings, as the Depth Spine prices its design with
    them: ``(SpineCosting, mobilisation distance in km)``.

    The spine used to price at the catalogue rates, the default percentages
    and no mobilisation at all, so a named person could sign a price on its
    "Costing & BoQ" stage that the Costing page did not show for the same
    design. The browser's spine already took that page's settings.
    """
    return SpineCosting(
        rates=working_rates(),
        overheads_percent=float(costing_setting("cost_overheads")),
        margin_percent=float(costing_setting("cost_margin")),
        contingency_percent=float(costing_setting("cost_contingency")),
        vat_percent=float(costing_setting("cost_vat")),
        exchange_rate_sle_per_usd=float(costing_setting("cost_fx")),
        # 0 applies the rule of thumb on the Costing page, as None does here
        overburden_m=float(costing_setting("cost_overburden")) or None,
        wq_samples=int(costing_setting("cost_samples")),
        handpumps=int(costing_setting("cost_handpumps")),
        development_hours=float(costing_setting("cost_dev_hours")),
        test_pumping_hours=float(costing_setting("cost_test_hours")),
    ), float(costing_setting("cost_distance"))


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


def plain(text: str) -> str:
    """A sentence for st.markdown, st.info, st.caption or st.write, its
    dollar signs kept as written. Streamlit reads text between two dollar
    signs as LaTeX, so "US$ 9,463 ... US$ 4,289" was shown with both signs
    gone."""
    return text.replace("$", "\\$")


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


class KeptPath:
    """An uploaded file kept on disk while its page is off screen.

    An elevation tile runs to 50 MB. Kept as bytes in session it was held
    twice while its uploader held it too, and once more for the rest of the
    session after that, where the reader that wants it seeks in a file and
    needs only a path. Stands in for ``UploadedFile`` as :class:`KeptFile`
    does: ``name`` is the name it was uploaded under, ``path`` where it is
    kept, and the bytes are read from there only when ``getvalue``,
    ``getbuffer`` or ``read`` asks for them.
    """

    def __init__(self, name: str, path: str | Path):
        self.name = name
        self.path = Path(path)
        self.size = self.path.stat().st_size

    def getvalue(self) -> bytes:
        return self.path.read_bytes()

    def getbuffer(self) -> memoryview:
        return memoryview(self.getvalue())

    def read(self) -> bytes:
        return self.getvalue()


def _kept_folder(key: str) -> Path:
    return workdir() / "kept" / key


def _keep_on_disk(key: str, files) -> list[tuple[str, str]]:
    """Write a new upload's files where ``kept_upload(on_disk=True)`` keeps
    them, once, and say where: ``[(name, path)]``.

    The previous upload's files go first, since nothing refers to them once
    the session holds the new ones. Each is written under its basename, so a
    crafted name cannot write outside the folder, with its place in the
    upload in front, so two files of one name do not overwrite each other.
    """
    folder = _kept_folder(key)
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    kept = []
    for n, upload in enumerate(files):
        path = folder / f"{n}_{Path(upload.name).name or 'upload'}"
        path.write_bytes(upload.getbuffer())
        kept.append((upload.name, str(path)))
    return kept


def kept_upload(label: str, key: str, *, on_disk: bool = False, **kwargs):
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

    With ``on_disk`` each new upload is written once, as it arrives, to
    ``workdir()/"kept"/<key>/<n>_<name>``, and the session holds the names
    and paths, ``[(name, path)]``, rather than the bytes. The page is then
    handed :class:`KeptPath` objects for a fresh upload and a kept one
    alike, so that it reads both the same way, from disk.
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
                              "files": _keep_on_disk(key, files) if on_disk
                              else [(f.name, bytes(f.getvalue())) for f in files]}
        if not on_disk:
            return value
        fresh = [KeptPath(name, path) for name, path in session[store]["files"]]
        return fresh if many else fresh[0]
    # empty and on screen last run: cleared by its user, unless it has been
    # empty since the page came back and the kept file stood in for it
    if not returning and not kept.get("restored"):
        _forget_upload(key, on_disk)
        return value
    if on_disk:
        # a file the session's folder no longer holds is not offered back
        restored = [KeptPath(name, path) for name, path in kept.get("files", [])
                    if Path(path).is_file()]
    else:
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
        _forget_upload(key, on_disk)
        return value
    return restored if many else restored[0]


def _forget_upload(key: str, on_disk: bool) -> None:
    """Drop what ``kept_upload`` keeps for the uploader ``key``, files too."""
    if st.session_state.pop(f"{key}_kept", None) is not None and on_disk:
        shutil.rmtree(_kept_folder(key), ignore_errors=True)


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


def project_summaries(files) -> tuple[list[dict], int]:
    """The summaries of saved project files (their bytes), and how many
    could not be read as a project: the Portfolio page's table and the
    desk study's earlier projects alike."""
    read, skipped = project_files(files)
    return [summary for summary, _, _ in read], skipped


def project_files(files) -> tuple[list[tuple[dict, dict, dict | None]], int]:
    """Each saved project file's summary, its ledger of predictions and
    outcomes (PLAN.md step 5.1) and its works record (step 6.3, None where
    it carries none), and how many could not be read as a project."""
    from groundwater.geo import parse_utm_zone
    from groundwater.project_io import deserialize_project

    read, skipped = [], 0
    for data in files:
        try:
            updates = deserialize_project(data)
        except Exception:  # noqa: BLE001 - a bad file is skipped and counted
            skipped += 1
            continue
        summary = updates.get("summary")
        if not isinstance(summary, dict) or not summary:
            # an older project file without a summary: fall back to site inputs
            summary = {
                "community": updates.get("meta_community"),
                "district": updates.get("meta_district"),
                "easting": updates.get("meta_easting"),
                "northing": updates.get("meta_northing"),
                # a hand-edited zone that is not a zone ("Zone 28" reads as
                # 28, "708958" reads as nothing) leaves the field unrecorded,
                # where portfolio_stats infers it from the easting, rather
                # than taking the page down or standing in a default 29N
                "utm_zone": parse_utm_zone(updates.get("meta_zone")),
            }
        read.append((summary, updates["prediction_ledger"], updates.get("works")))
    return read, skipped


def kept_portfolio() -> list[dict] | None:
    """The summaries of the project files the Portfolio page holds, or
    None where it holds none: the desk study's earlier projects."""
    kept = st.session_state.get("portfolio_upload_kept") or {}
    files = kept.get("files") or []
    if not files:
        return None
    return project_summaries(data for _, data in files)[0]


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


def forget_artifacts(paths) -> None:
    """Take files off the Deliverables list: the page that built them no
    longer shows them, so the Overview does not offer them either."""
    gone = {str(path) for path in paths}
    artifacts = st.session_state.get("artifacts") or {}
    for label in [label for label, path in artifacts.items() if path in gone]:
        del artifacts[label]


def discard_terrain_result(result: dict | None) -> None:
    """Delete the terrain figures and drainage lines of a result the Site
    maps page no longer shows, with the folder its run wrote them to, and
    take them off the Deliverables list."""
    if not result:
        return
    forget_artifacts([path for _, png, svg in result["figures"] for path in (png, svg)] + [result["geojson"]])
    shutil.rmtree(result["folder"], ignore_errors=True)


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
    """The session, keyed as groundwater.readiness expects it, with the
    documents issued from it, which the draft asset record carries."""
    return {
        "site": site_from_state(),
        "sources": _loaded_sources(),
        "drilling_log": st.session_state.get("drilling_log"),
        "pump_analysis": st.session_state.get("pump_analysis"),
        "wq_assessment": st.session_state.get("wq_assessment"),
        "borehole_design": st.session_state.get("borehole_design"),
        "cost_estimate": st.session_state.get("cost_estimate"),
        "supervision": {
            "items": cached_checklists(),
            "responses": supervision_answers(),
            "evidence": st.session_state.get("sup_evidence") or {},
        },
        "issued": st.session_state.get("issued_documents") or [],
    }


# ---------------------------------------------------------------------------
# Documents issued (PLAN.md step 8.1)
# ---------------------------------------------------------------------------

#: The upload keys the session keeps its files under, by the role a
#: manifest names each by (the browser app's roles).
_EVIDENCE_ROLES = {"ves": "ves", "wiz_ves": "ves", "log": "drilling", "pump": "pumping",
                   "wq": "quality"}


def _source_bytes(source) -> tuple[str, bytes] | None:
    """A kept source's file name and bytes; a bundled sample's are read
    from its file. None where there are none to read."""
    if not isinstance(source, dict):
        return None
    if source.get("bytes") is not None:
        return str(source.get("name") or "data"), bytes(source["bytes"])
    root = sample_data_dir()
    if source.get("sample") and root is not None:
        path = root / str(source["sample"])
        if path.is_file():
            return path.name, path.read_bytes()
    return None


def photo_evidence(photo: dict) -> dict:
    """A photograph as a manifest lists it: by the SHA-256 of the file as it
    arrived, which its provenance record holds, or by the bytes kept where
    it was attached before records existed."""
    import base64

    what = phrase_table("verification.evidence_kinds")["photo"]
    held = (photo.get("provenance") or {}).get("sha256")
    if isinstance(held, str) and _re.fullmatch(r"[0-9a-f]{64}", held):
        return {"what": what, "name": str(photo.get("name") or ""), "sha256": held}
    return evidence_entry(what, str(photo.get("name") or ""),
                          base64.b64decode(str(photo.get("b64") or "")))


def project_file_evidence(name: str, data: bytes) -> dict:
    """A saved project file pooled or read into the register, as a manifest
    lists it."""
    return evidence_entry(phrase_table("verification.evidence_kinds")["project"], name, data)


def issue_for(kind: str, photos=(), files=()) -> Issue:
    """What the app knows of a document it is about to issue: the day, which
    is today unless a page names another (the engine never reads the
    clock), and the evidence it is issued from. A document about the
    borehole is issued from every file the session holds and the
    photographs it embeds; the others from the ``files`` they are drawn
    from, or from none. The browser app's ``issueFor`` is the twin."""
    import datetime

    kinds = phrase_table("verification.evidence_kinds")
    evidence = []
    if kind in BOREHOLE_KINDS:
        for key, role in _EVIDENCE_ROLES.items():
            held = _source_bytes(st.session_state.get(f"src_{key}"))
            if held is not None:
                evidence.append(evidence_entry(kinds[role], held[0], held[1]))
    evidence += [photo_evidence(photo) for photo in photos]
    evidence += list(files)
    return Issue(issued_on=datetime.date.today().isoformat(), evidence=tuple(evidence))


def record_issue(path) -> dict | None:
    """Keep the issue record of the document just written at ``path``: in the
    session's ``issued_documents``, which the project file saves, and for a
    document about the borehole in its stored asset record. A record stored
    later starts from the session's, as the draft carries them."""
    record = document_record(Path(path).read_bytes())
    if record is None:
        return None
    st.session_state["issued_documents"] = clean_issue_records(
        [*(st.session_state.get("issued_documents") or []), record])
    held = st.session_state.get("asset_record")
    asset = asset_from_dict(held) if held and record["kind"] in BOREHOLE_KINDS else None
    if asset is not None:
        asset.documents = clean_issue_records([*asset.documents, record])
        st.session_state["asset_record"] = asset.as_dict()
    return record


def offer_document(path: Path, label: str, keep: bool = True) -> dict | None:
    """Keep the issue record of a document just written and offer it for
    download, with its code beside the button."""
    record = record_issue(path)
    offer_download(path, label, keep=keep)
    if record is not None:
        st.caption(phrase("verification.cover_code", code=record["code"]))
    return record


# ---------------------------------------------------------------------------
# The evidence bundle (PLAN.md step 8.3)
# ---------------------------------------------------------------------------

def _project_records() -> list[dict]:
    """The issue records the project holds: its own and its asset record's."""
    return issue_records_of({"issued": st.session_state.get("issued_documents") or [],
                             "asset": st.session_state.get("asset_record")})


def session_documents() -> list[tuple[str, bytes]]:
    """The documents built in this session that a borehole's bundle carries:
    the latest of each on the Deliverables list whose issue record the
    project holds (so a document built before another project was opened
    stays out), leaving out the calibration report and the round sheets,
    which are about many boreholes. The browser app's ``bundleDocuments`` is
    the twin."""
    held = {r["sha256"] for r in _project_records()}
    out: dict[str, bytes] = {}
    for _, path in _deliverables():
        if path.suffix.lower() != ".docx" or str(path) in out:
            continue
        data = path.read_bytes()
        record = document_record(data)
        if record is not None and record["kind"] not in PROGRAMME_KINDS and record["sha256"] in held:
            out[str(path)] = data
    return sorted((Path(p).name, d) for p, d in out.items())


def evidence_bundle(added=()) -> dict:
    """This borehole's evidence bundle: every sheet the session holds, as it
    was uploaded, the documents built in this session and those ``added``
    (``(name, bytes)`` pairs), the figures each document embeds, and the
    issue records the project file and the asset record keep; made on the
    device's day, with the calibration set in force. Raises ValueError, in
    the catalogue's words, for a document that cannot go in."""
    import datetime

    kinds = phrase_table("verification.evidence_kinds")
    files: list[dict] = []
    for key, role in _EVIDENCE_ROLES.items():
        held = _source_bytes(st.session_state.get(f"src_{key}"))
        if held is not None:
            files.append({"folder": "raw", "name": held[0], "data": held[1], "what": kinds[role]})
    for name, data in [*session_documents(), *added]:
        files.append({"folder": "reports", "name": name, "data": data})
        files += document_figures(name, data)
    site = site_from_state()
    stored = st.session_state.get("asset_record")
    asset = asset_from_dict(stored) if stored else None
    return build_evidence_bundle(
        site.community or site.project, files, borehole=asset.asset_id if asset is not None else "",
        made_on=datetime.date.today().isoformat(), calibration=calibration_facts(app_config().calibration),
        records=_project_records())


#: The supervision page's radio labels, as the checklist's answer codes.
ANSWER_CODES = {"Pending": "pending", "Yes": "yes", "No": "no", "N/A": "na"}


def supervision_answers() -> dict[str, str]:
    """Each checklist item's answer code, from the ``chk_`` keys."""
    return {
        item.item_id: ANSWER_CODES.get(
            st.session_state.get(f"chk_{item.item_id}", "Pending"), "pending")
        for item in cached_checklists()
    }


def _overrides_for(report: str) -> dict:
    """Overrides the analyst recorded for this report, from session state."""
    return st.session_state.get(f"_override_{report}") or {}


def report_gate(report: str, scope: str = "", decided: dict | None = None):
    """Show what this report can and cannot stand behind, and return it.

    Deliberately never disables the button. An analyst who needs an interim
    document will produce one either way; the useful thing is that the
    document says what it rests on, so this renders the outstanding items,
    offers a recorded override, and hands the result to the report builder
    to stamp on its own cover.

    ``scope`` distinguishes two gates for the same report kind on one run -
    the widget keys have to differ, while the recorded override does not:
    an override of the costing evidence is an override wherever it is shown.

    ``decided`` is what the report's decision numbers are read from where
    the session does not hold it under the gate's keys (PLAN.md step 3.6):
    the ranked interpretations, their ranges and odds for the geophysical
    report, the cost distribution for the cost report.
    """
    keyed = f"{report}_{scope}" if scope else report
    state = {**_project_state(), **(decided or {})}
    readiness = assess_readiness(state, report, _overrides_for(report))
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


def _apply_degree_boxes() -> None:
    """Convert degrees typed into the UTM boxes into UTM (a button callback).

    Pressed only by the operator: degrees in the two boxes are refused by
    the gate, the maps and the asset identifier in both apps, and this is
    the operator saying they are a latitude and a longitude. The pair is put
    in the paste box and read exactly as a pasted pair is, so an unsigned
    longitude is west and the conversion says so.
    """
    easting = st.session_state.get("meta_easting")
    northing = st.session_state.get("meta_northing")
    st.session_state["latlon_paste"] = f"{float(northing)!r}, {float(easting)!r}"
    _apply_latlon()


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
    "proc_award", "proc_build",
})


def project_file_bytes() -> bytes:
    """Serialize the widget state that makes up a project."""
    session = {key: value for key, value in st.session_state.items()
               if key not in UNSAVED_BUTTONS}
    session["inversion_cache"] = _inversion_cache_now()
    # the ledger goes out with the borehole's outcome as the project now
    # holds it: a corrected log corrects it
    session["prediction_ledger"] = current_ledger()
    # and the works record for the contractor scorecards, from the project
    # as it now stands
    session["works_record"] = current_works()
    return serialize_project(session, groundwater.__version__)


def procurement_variations(rows) -> list[dict]:
    """The Procurement page's variation orders, from its table's rows, as
    plain records (ref, date, code, quantity_delta, rate_usd, reason,
    authorised_by): what the page's certificate values and the works record
    counts. A row naming no line is left out, an empty or unreadable number
    is none (a quantity of nought, the contract's rate), and a signature of
    white space alone is no signature, as the browser's form has it."""
    import math

    def number(value):
        try:
            x = float(value)
        except (TypeError, ValueError):
            return None
        return x if math.isfinite(x) else None

    def text(value) -> str:
        # an empty cell of the data editor comes back as None or NaN
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        return str(value)

    out = []
    for row in rows or []:
        if not hasattr(row, "get") or not text(row.get("Code")).strip():
            continue
        out.append({
            "ref": text(row.get("Ref")), "date": text(row.get("Date")), "code": text(row.get("Code")),
            "quantity_delta": number(row.get("Quantity change")) or 0.0,
            "rate_usd": number(row.get("New rate (USD)")),
            "reason": text(row.get("Reason")),
            "authorised_by": text(row.get("Authorised by")).strip(),
        })
    return out


def current_works() -> dict | None:
    """The project's works record (PLAN.md step 6.3): what it records of its
    contractor's work, for the Portfolio page's contractor scorecards, or
    None where it records nothing they read."""
    from groundwater.scorecards import works_record

    config = app_config()
    lines = st.session_state.get("proc_contract_lines")
    procurement = None
    if lines:
        procurement = {"lines": lines,
                       "variations": procurement_variations(st.session_state.get("proc_variations")),
                       "due": st.session_state.get("proc_due") or ""}
    metres = {"logged_m": st.session_state.get("fx_logs_m"), "claimed_m": st.session_state.get("fx_invoiced_m")}
    return works_record(site_from_state(), st.session_state.get("drilling_log"),
                        st.session_state.get("pump_analysis"), current_ledger(), supervision_answers(),
                        metres, procurement, config, cached_checklists())


def current_ledger() -> dict:
    """The project's ledger of predictions and outcomes (PLAN.md step 5.1),
    with the completion the project holds attached to the point it was
    drilled at; with none, the outcomes the ledger already has."""
    from groundwater.ledger import attach_outcome, completion_outcome

    config = app_config()
    # the project's drilling contractor wins over the log's own, as the
    # site details win over every sheet's in the reports' headers
    outcome = completion_outcome(st.session_state.get("drilling_log"),
                                 st.session_state.get("pump_analysis"), config,
                                 contractor=site_from_state().contractor)
    return attach_outcome(st.session_state.get("prediction_ledger"), outcome, config)


def ledger_site(soundings) -> SimpleNamespace:
    """The place a survey's points are recorded under: the project's
    community and district from the site details, each the survey's own
    where the details leave it blank, and the survey's zone; and the
    project's field supervisor, the survey team of a point whose own sheet
    names none."""
    project, survey = site_from_state(), soundings[0].site
    return SimpleNamespace(community=project.community or survey.community,
                           district=project.district or survey.district,
                           utm_zone=survey.utm_zone or project.utm_zone,
                           supervisor=project.supervisor)


def record_survey_predictions(soundings, interps, ranges, odds) -> list[str]:
    """Write the survey's predictions into the project's ledger, as recorded
    before drilling unless the borehole has been drilled, and return the ids
    of the points whose forecast was kept as it was made. The borehole has
    been drilled when the project holds a drilling log or a pumping test (a
    test is run in a drilled hole), when the ledger holds an outcome already,
    or when the point drilled has been chosen (``record_predictions`` reads
    those two itself)."""
    import datetime

    from groundwater.ledger import record_predictions, survey_predictions
    from groundwater.siting import assess_siting

    config = app_config()
    predictions = survey_predictions(interps, ranges, odds, ledger_site(soundings), config,
                                     teams=[sounding.site.supervisor for sounding in soundings],
                                     siting=assess_siting(interps, config.ves))
    drilled = (st.session_state.get("drilling_log") is not None
               or st.session_state.get("pump_analysis") is not None)
    ledger, kept = record_predictions(current_ledger(), predictions, datetime.date.today().isoformat(),
                                      drilled, groundwater.__version__)
    st.session_state["prediction_ledger"] = ledger
    return kept


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
    # the outgoing site's maps leave the Deliverables list with it, where
    # they would pass as the loaded site's: every file its maps' keys hold,
    # with the GeoTIFF a map keeps beside its picture, and the terrain
    # figures and drainage lines, deleted with their folder
    outgoing = []
    for key in ("topo_path", "profile_path", "map_paths", "subsurface_paths", "section_path",
                "pseudosection_path", "geolibre_path"):
        held = st.session_state.get(key) or []
        for path in held if isinstance(held, list) else [held]:
            outgoing += [str(path), str(Path(path).with_suffix(".tif"))]
    forget_artifacts(outgoing)
    discard_terrain_result(st.session_state.get("terrain_result"))
    # a loaded project fully replaces the working state: drop the previous
    # data sources, recompute inputs and computed results first, so a stale
    # dataset from earlier in the session cannot bleed into the loaded project
    for stale in stale_on_load(st.session_state):
        st.session_state.pop(stale, None)
    for result_key in (
        "ves_results", "ves_ranges", "pump_analysis", "wq_assessment", "borehole_design",
        "drilling_log", "cost_estimate", "cost_artifacts", "cost_spread", "allocation_cost",
        "wp_result", "handover_built", "_design_follows_page",
        # cleared too, so a project with no sources at all cannot inherit the
        # previous project's rebuild banner
        "recompute_diagnostics",
        # the outgoing site's maps, drawn around its position from its
        # elevation model and its soundings, and the GeoLibre file built
        # from them
        "topo_path", "topo_source", "topo_report", "topo_inputs", "terrain_result",
        "profile_path", "map_paths", "subsurface_paths", "section_path",
        "pseudosection_path", "traverse", "geolibre_path", "geolibre_area",
        "geolibre_layers",
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
    evidence = updates.pop("evidence", None)
    # the contract on the Procurement page, as its tables hold it; the works
    # record is worked out again from the project when it is next saved
    procurement = updates.pop("procurement", None)
    updates.pop("works", None)
    if isinstance(procurement, dict) and procurement.get("lines"):
        st.session_state["proc_contract_lines"] = procurement["lines"]
        st.session_state["proc_measured"] = procurement.get("measured") or None
        st.session_state["proc_variations"] = procurement.get("variations") or None
    if isinstance(evidence, dict) and evidence:
        st.session_state["sup_evidence"] = evidence
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
    ("Project", ["Overview", "Guided start", "Site maps", "Verify a document"]),
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


#: The session's key for the calibration set in force (PLAN.md step 5.3):
#: one a named person adopted, put in force on the Portfolio page; absent
#: or None for the provisional default.
CALIBRATION_SET = "calibration_set"


def app_config() -> Config:
    """Config with the sidebar branding applied (per rerun, not global), and
    the calibration set in force for the session."""
    cfg = Config()
    cfg.style.organisation = st.session_state.get("org_name", "") or ""
    cfg.style.organisation_details = st.session_state.get("org_details", "") or ""
    # the report address a plate's symbol links to (PLAN.md step 7.1), as
    # typed on the Asset registry page; checked where a plate is printed
    cfg.service.report_url = str(st.session_state.get("org_report_url", "") or "")
    held = st.session_state.get(CALIBRATION_SET)
    return apply_set(cfg, held) if held is not None else cfg


def _edges_read(config: Config, soundings) -> list:
    """The resistivity edges each sounding is read by under ``config``."""
    return [(c.ves.clay_max_rho, c.ves.fresh_basement_min_rho)
            for c in (config_for_sounding(config, sounding) for sounding in soundings)]


def put_set_in_force(s) -> None:
    """Put the calibration set ``s`` in force for the session, or refuse it
    with ValueError, in the sentence the page shows, unless a named person
    adopted it or it is the provisional default.

    The survey on show is read again by it: each sounding by the edges the
    set fitted for the geology unit under it, and ranked by its weights. Its
    sampled range of models is dropped where a sounding is read by other
    edges than it was sampled with, to be sampled again on the VES page.
    """
    s = check_in_force(s)
    before = app_config()
    st.session_state[CALIBRATION_SET] = None if s["version"] == 0 else s
    after = app_config()
    held = st.session_state.get("ves_results")
    if not held or not held[0]:
        return
    soundings, results, _ = held
    interps = [_ves.interpret_model(sounding, result.model, config_for_sounding(after, sounding).ves)
               for sounding, result in zip(soundings, results, strict=True)]
    rank_interpretations(interps, config=after.ves)
    st.session_state.ves_results = (soundings, results, interps)
    if _edges_read(before, soundings) != _edges_read(after, soundings):
        st.session_state.pop("ves_ranges", None)


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
        # the rising main follows the Water quality page's sample
        quality=st.session_state.get("wq_assessment"),
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
        quality=st.session_state.get("wq_assessment"),
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
    # The rising main follows the sample on the Water quality page, which can
    # change while no page that redesigns is on screen: a design restored
    # from a project, or kept from an earlier run, takes the current one.
    stored = session.get("borehole_design")
    if stored is not None:
        stored.rising_main = rising_main_choice(session.get("wq_assessment"), CONFIG.design)

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
    config = app_config()
    progress = st.progress(0.0)
    for i, sounding in enumerate(soundings):
        try:
            # looked up on the package at each call rather than imported
            # once: this module outlives a rerun, and the app's tests make
            # one sounding fail by patching groundwater.ves
            result = _ves.invert_sounding(sounding, CONFIG.ves)
            # read by the edges the calibration set in force fitted for the
            # geology unit under the sounding, if any
            interp = _ves.interpret_model(sounding, result.model, config_for_sounding(config, sounding).ves)
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
    rank_interpretations(interps, config=config.ves)
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
    # with no drawing the rising main still follows the water, priced over
    # the whole depth (the estimate says so) since no intake is drawn
    choice = rising_main_choice(st.session_state.get("wq_assessment"), rules)
    return {
        "borehole_diameter_in": rules.borehole_diameter_in,
        "casing_diameter_in": rules.casing_diameter_in,
        "sanitary_seal_m": rules.sanitary_seal_depth_m,
        "rising_main_material": choice["material"] if choice["upgraded"] else "",
    }

def first_point_survey():
    """The survey's first-ranked point as the costing reads it: its chance of
    a working borehole and its sampled range of models (the range None where
    none was sampled around these very inversions), or (None, None) before a
    survey is inverted. Read as the Geophysics page reads them."""
    from groundwater.siting import assess_siting, survey_odds

    held = st.session_state.get("ves_results")
    if not held or not held[2]:
        return None, None
    soundings, results, interps = held
    kept = st.session_state.get("ves_ranges")
    ranges = kept[1] if kept is not None and kept[0] is results else [None] * len(results)
    # by position, not id: two points can share an id
    i = assess_siting(interps, app_config().ves)[0].index
    site = soundings[0].site
    odds = survey_odds([interps[i]], [ranges[i]], site.utm_zone, site.latlon, app_config())[0]
    return odds, ranges[i]


def survey_measurements(spread):
    """What one more measurement at the survey's first-ranked point is worth
    (PLAN.md step 3.5), priced from the cost distribution ``spread``: one
    for each kind, or an empty list before a survey is inverted. The odds
    are read as first_point_survey reads them, at every point, so the
    alternative to the first-ranked point is one of the others."""
    from groundwater.siting import assess_siting, measurement_values, survey_odds

    held = st.session_state.get("ves_results")
    if not held or not held[2]:
        return []
    soundings, results, interps = held
    kept = st.session_state.get("ves_ranges")
    ranges = kept[1] if kept is not None and kept[0] is results else [None] * len(results)
    site = soundings[0].site
    odds = survey_odds(interps, ranges, site.utm_zone, site.latlon, app_config())
    ranking = [s.index for s in assess_siting(interps, app_config().ves)]
    return measurement_values(odds, ranking, spread.mean, spread.dry_mean)


def show_measurements(values, nested: bool = False) -> None:
    """What one more measurement is worth, on a page: the plan's sentence for
    each kind, then the rest of its sentences and its decision table, what a
    measurement could read, and the basis. The reports print the same.
    ``nested`` is for a page that shows it inside an expander already, which
    Streamlit does not nest: the readings go in a bordered box instead."""
    from groundwater.siting.measurement import (
        measurement_basis,
        measurement_decision_caption,
        measurement_decision_header,
        measurement_decision_rows,
        measurement_reading_header,
        measurement_reading_rows,
        measurement_readings_caption,
        measurement_text,
    )

    if nested:
        st.markdown(f"**{phrase('measurement.heading')}**")
    else:
        st.subheader(phrase("measurement.heading"))
    st.caption(phrase("measurement.lead"))
    if not values:
        st.info(phrase("measurement.no_survey"))
        return
    for v in values:
        text = measurement_text(v)
        with st.container(border=True):
            st.markdown(f"**{plain(text[0])}**")
            st.write(plain(" ".join(text[1:])))
            st.table([dict(zip(measurement_decision_header(v), row, strict=True))
                      for row in measurement_decision_rows(v)])
            st.caption(measurement_decision_caption())
    with (st.container(border=True) if nested
          else st.expander(measurement_readings_caption(values[0]))):
        st.table([dict(zip(measurement_reading_header(), row, strict=True))
                  for row in measurement_reading_rows(values[0])])
        if nested:
            st.caption(plain(measurement_readings_caption(values[0])))
    st.caption(plain(measurement_basis(values[0])))


def cost_spread_inputs() -> dict:
    """What the cost distribution draws the depth and the dry holes from: the
    first-ranked point's range and odds, where the survey has them."""
    odds, model_range = first_point_survey()
    return {
        "depth": depth_spread(model_range, app_config()),
        "success_probability": odds.probability if odds is not None else 1.0,
        "odds_source": odds.sounding_id if odds is not None else None,
    }


def compute_cost_estimate(inputs: CostingInputs, rates, **kwargs) -> None:
    """Estimate and build the shared artifacts (chart and BoQ workbook), and
    sample the planning figure beside it (PLAN.md step 3.4), kept with the
    estimate it belongs to."""
    estimate = estimate_borehole_cost(inputs, rates, **kwargs)
    st.session_state.cost_estimate = estimate
    chart_path = workdir() / "cost_breakdown.png"
    plot_cost_breakdown(estimate, chart_path, app_config().style)
    boq_path = workdir() / "Bill_of_Quantities.xlsx"
    write_boq_workbook(estimate, boq_path)
    st.session_state.cost_artifacts = (chart_path, boq_path)
    pct = {k: v for k, v in kwargs.items() if k != "exchange_rate_sle_per_usd"}
    _sample_cost_spread(estimate, inputs, rates, pct, cost_spread_inputs())


def _sample_cost_spread(estimate, inputs, rates, pct: dict, survey: dict) -> None:
    spread = sample_cost(inputs, rates, config=app_config(), **survey, **pct)
    spread_path = workdir() / "cost_distribution.png"
    marks = phrase_table("cost_range.marks")
    plot_cost_distribution(
        spread.curve, [(marks["boq"], spread.boq_usd), (marks["budget"], spread.budget_usd)],
        spread_path, app_config().style, title=marks["title"])
    st.session_state.cost_spread = (estimate, spread, spread_path, inputs, rates, pct, survey)


def allocation_cost():
    """The cost distribution the Coverage gap page prices a programme's
    boreholes from (PLAN.md step 6.1): the Costing page's borehole, its
    inputs, rates and percentages as estimated, sampled with the depth held
    at the estimate's and no dry hole drawn, since the range of models and
    the odds at the survey's first-ranked point belong to one site and the
    allocation gives every area its own odds. None before an estimate is
    made (or where one was made without its distribution). Kept with the
    estimate it belongs to and the sampling settings, so the page does not
    sample it again on every rerun."""
    kept = st.session_state.get("cost_spread")
    estimate = st.session_state.get("cost_estimate")
    if kept is None or estimate is None or kept[0] is not estimate:
        return None
    _estimate, _spread, _path, inputs, rates, pct, _survey = kept
    settings = (app_config().cost_range.seed, app_config().cost_range.samples)
    held = st.session_state.get("allocation_cost")
    if held is not None and held[0] is estimate and held[1] == settings:
        return held[2]
    spread = sample_cost(inputs, rates, config=app_config(), **pct)
    st.session_state.allocation_cost = (estimate, settings, spread)
    return spread


def cost_spread_for(estimate):
    """The distribution sampled with ``estimate`` and its figure, or None
    where the estimate was made without one (or another has replaced it).
    A range sampled, or a survey inverted, since the estimate was made
    changes what the depth and the dry holes are drawn from, so the
    distribution is sampled again with them rather than shown stale."""
    kept = st.session_state.get("cost_spread")
    if kept is None or kept[0] is not estimate:
        return None
    _estimate, spread, path, inputs, rates, pct, survey = kept
    now = cost_spread_inputs()
    if now != survey:
        _sample_cost_spread(estimate, inputs, rates, pct, now)
        spread, path = st.session_state.cost_spread[1:3]
    return spread, path


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
