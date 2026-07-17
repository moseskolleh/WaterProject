"""Shared helpers: caches, uploads, project persistence, shared compute."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st
import yaml

import groundwater
from groundwater.config import Config
from groundwater.costing import (
    estimate_borehole_cost,
    load_rates,
    plot_cost_breakdown,
    write_boq_workbook,
)
from groundwater.models import SiteMetadata
from groundwater.supervision import (
    ChecklistResponse,
    load_checklists,
    load_separation_distances,
)
from groundwater.ves import interpret_model, invert_sounding

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
def cached_districts():
    """(provinces, [(district, province), ...]) from the bundled table."""
    import csv as _csv
    from importlib import resources

    text = (
        resources.files("groundwater") / "data" / "sl_districts.csv"
    ).read_text(encoding="utf-8")
    rows = list(_csv.DictReader(text.splitlines()))
    provinces: list[str] = []
    for row in rows:
        if row["province"] not in provinces:
            provinces.append(row["province"])
    return provinces, [(row["district"], row["province"]) for row in rows]


def workdir() -> Path:
    if "workdir" not in st.session_state:
        st.session_state.workdir = Path(tempfile.mkdtemp(prefix="gw_"))
    return st.session_state.workdir


def save_upload(uploaded) -> Path:
    path = workdir() / uploaded.name
    path.write_bytes(uploaded.getbuffer())
    return path


def sample_data_dir() -> Path | None:
    """Bundled sample datasets, when present (repo checkout or web demo)."""
    here = Path(__file__).resolve().parent
    for candidate in (
        here.parent.parent / "examples" / "data",  # repository checkout
        here.parent / "examples" / "data",
        Path("examples/data"),  # web demo mount / current directory
    ):
        if candidate.is_dir():
            return candidate
    return None


def choose_input(label: str, key: str, types: list[str], samples: list[str]) -> Path | None:
    """File uploader with an optional bundled-sample fallback.

    Returns the path of the uploaded file, the chosen sample, or None.
    """
    upload = st.file_uploader(label, type=types, key=f"upload_{key}")
    if upload is not None:
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


def offer_download(path: Path, label: str) -> None:
    with open(path, "rb") as fh:
        st.download_button(label, fh.read(), file_name=path.name)


def _soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def convert_report_to_pdf(docx_path: Path) -> Path | None:
    """Convert a built .docx to PDF with headless LibreOffice, if present.

    Streamlit Community Cloud installs LibreOffice through the
    repository's ``packages.txt``; where the binary is missing (the
    browser demo, minimal installs) this quietly returns None.
    """
    exe = _soffice()
    if exe is None:
        return None
    pdf_path = docx_path.with_suffix(".pdf")
    try:
        subprocess.run(
            [exe, "--headless", "--convert-to", "pdf",
             "--outdir", str(docx_path.parent), str(docx_path)],
            check=True, capture_output=True, timeout=180,
        )
    except Exception:
        return None
    return pdf_path if pdf_path.exists() else None


def offer_report_download(path: Path, label: str) -> None:
    """Report download: the .docx plus a PDF twin when convertible."""
    offer_download(path, label)
    pdf = convert_report_to_pdf(path)
    if pdf is not None:
        offer_download(pdf, label.replace("(.docx)", "(.pdf)"))
    elif not IN_BROWSER:
        st.caption(
            "PDF export needs LibreOffice on the server "
            "(packages.txt installs it on Streamlit Cloud; see DEPLOY.md)."
        )


def parse_upload(reader, path: Path):
    """Run a parser on an uploaded file, surfacing failures as errors.

    A malformed or mislabelled workbook should show a readable message
    instead of crashing the tab.
    """
    try:
        return reader(path)
    except Exception as exc:
        st.error(
            f"Could not read {path.name}: {exc}. Check that the file "
            "follows the standard template (Templates tab)."
        )
        return None


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
        utm_zone=int(get("meta_zone", "29N").rstrip("N")),
    )


# ---------------------------------------------------------------------------
# Project file: save and restore the whole working state
# ---------------------------------------------------------------------------

_PERSIST_PREFIXES = (
    "org_", "meta_", "chk_", "rmk_", "cost_", "fx_", "ho_", "wiz_",
)

# button state also lives under these prefixes but must never be saved:
# Streamlit forbids assigning trigger-widget values on load
_TRIGGER_KEYS = frozenset({
    "wiz_next", "wiz_back", "wiz_restart", "wiz_run_ves", "wiz_cost_run",
    "org_logo_remove",
})


def project_file_bytes() -> bytes:
    """Serialize the widget state that makes up a project."""
    state = {
        key: value
        for key, value in st.session_state.items()
        if key.startswith(_PERSIST_PREFIXES)
        and key not in _TRIGGER_KEYS
        and isinstance(value, (str, int, float, bool))
    }
    payload = {
        "groundwater_toolkit_project": groundwater.__version__,
        "rates_overrides": st.session_state.get("rates_overrides", {}),
        "state": state,
    }
    return yaml.safe_dump(payload, sort_keys=True).encode("utf-8")


def apply_project_payload(payload) -> bool:
    """Apply a parsed project file to session state; False if malformed."""
    if not (isinstance(payload, dict) and isinstance(payload.get("state"), dict)):
        return False
    for key, value in payload["state"].items():
        if (
            key.startswith(_PERSIST_PREFIXES)
            and key not in _TRIGGER_KEYS  # old files may carry button state
            and isinstance(value, (str, int, float, bool))
        ):
            st.session_state[key] = value
    overrides = payload.get("rates_overrides") or {}
    if isinstance(overrides, dict):
        st.session_state.rates_overrides = {
            str(code): float(rate) for code, rate in overrides.items()
        }
    # reset widgets that mirror loaded state so they show the new values
    st.session_state.pop("rates_editor", None)
    st.session_state.pop("meta_date_widget", None)
    st.session_state.project_loaded = True
    # protect restored inputs from the prefill-reset checks for one run
    st.session_state.project_just_loaded = True
    # the wizard costing block only executes on its step, so it carries
    # its own grace marker, consumed when that block first runs
    st.session_state["_wiz_load_grace"] = True
    return True


def load_project_upload() -> None:
    """Apply an uploaded project file (button callback, runs pre-render)."""
    upload = st.session_state.get("project_upload")
    if upload is None:
        return
    try:
        payload = yaml.safe_load(upload.getvalue().decode("utf-8"))
    except Exception:
        st.session_state.project_load_error = True
        return
    if not apply_project_payload(payload):
        st.session_state.project_load_error = True


# ---------------------------------------------------------------------------
# Autosave: the project YAML written to disk after every change, so a
# browser refresh or crash costs nothing (server installs only; the
# browser demo's filesystem does not survive a reload)
# ---------------------------------------------------------------------------


def autosave_dir() -> Path:
    override = os.environ.get("GW_AUTOSAVE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".groundwater_toolkit" / "autosaves"


def _project_slug() -> str:
    name = (
        (st.session_state.get("meta_community") or "").strip()
        or (st.session_state.get("meta_project") or "").strip()
    )
    slug = "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()
    return slug or "untitled"


def project_state_digest(payload: bytes | None = None) -> str:
    return hashlib.md5(payload or project_file_bytes()).hexdigest()


def autosave_project() -> None:
    """Write the project file when named and changed; end of each rerun."""
    if IN_BROWSER:
        return
    if not (
        (st.session_state.get("meta_community") or "").strip()
        or (st.session_state.get("meta_project") or "").strip()
    ):
        return
    payload = project_file_bytes()
    digest = project_state_digest(payload)
    if st.session_state.get("_autosave_hash") == digest:
        return
    try:
        directory = autosave_dir()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{_project_slug()}.yaml").write_bytes(payload)
    except OSError:
        return  # read-only or full disk: autosave is best effort
    st.session_state["_autosave_hash"] = digest


def list_autosaves() -> list[Path]:
    directory = autosave_dir()
    if not directory.is_dir():
        return []
    return sorted(
        directory.glob("*.yaml"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def restore_autosave() -> None:
    """Load the picked autosave file (button callback, runs pre-render)."""
    pick = st.session_state.get("autosave_pick")
    if not pick:
        return
    try:
        payload = yaml.safe_load(Path(pick).read_text(encoding="utf-8"))
    except Exception:
        st.session_state.project_load_error = True
        return
    if not apply_project_payload(payload):
        st.session_state.project_load_error = True


def app_config() -> Config:
    """Config with the sidebar branding applied (per rerun, not global)."""
    cfg = Config()
    cfg.style.organisation = st.session_state.get("org_name", "") or ""
    cfg.style.organisation_details = st.session_state.get("org_details", "") or ""
    logo = st.session_state.get("org_logo_path", "") or ""
    if logo and Path(logo).exists():
        cfg.style.logo_path = logo
    return cfg


def checklist_responses(items) -> dict[str, ChecklistResponse]:
    """The supervision checklist answers currently in session state."""
    responses: dict[str, ChecklistResponse] = {}
    for item in items:
        status = st.session_state.get(f"chk_{item.item_id}", "Pending")
        mapped = {"Pending": "pending", "Yes": "yes", "No": "no",
                  "N/A": "na"}.get(status, "pending")
        # a remark typed while the item was No must not linger on a
        # later Yes/N/A answer
        remark = (
            st.session_state.get(f"rmk_{item.item_id}", "")
            if mapped == "no"
            else ""
        )
        responses[item.item_id] = ChecklistResponse(item.item_id, mapped, remark)
    return responses


# ---------------------------------------------------------------------------
# Shared compute: results several tabs read from session state
# ---------------------------------------------------------------------------


def top_interpretation():
    """Best ranked VES interpretation, read fresh from session state.

    Called where needed rather than once per rerun, so code that has
    just run the inversion sees its own result.
    """
    if "ves_results" not in st.session_state:
        return None
    _, _, interps = st.session_state.ves_results
    ranked = sorted(interps, key=lambda i: (i.rank or 99, -i.score))
    return ranked[0] if ranked else None


def run_ves_inversion(soundings) -> None:
    """Invert and interpret the soundings, storing the shared results."""
    # a fresh siting result is a genuine source change: the wizard
    # costing prefill must follow it, not a previously loaded project
    st.session_state.pop("_wiz_load_grace", None)
    results = []
    interps = []
    progress = st.progress(0.0)
    for i, sounding in enumerate(soundings):
        result = invert_sounding(sounding, CONFIG.ves)
        interp = interpret_model(sounding, result.model, CONFIG.ves)
        results.append(result)
        interps.append(interp)
        progress.progress((i + 1) / len(soundings))
    st.session_state.ves_results = (soundings, results, interps)


def compute_cost_estimate(inputs, rates, **kwargs) -> None:
    """Estimate and build the shared artifacts (chart and BoQ workbook)."""
    estimate = estimate_borehole_cost(inputs, rates, **kwargs)
    st.session_state.cost_estimate = estimate
    chart_path = workdir() / "cost_breakdown.png"
    plot_cost_breakdown(estimate, chart_path, app_config().style)
    boq_path = workdir() / "Bill_of_Quantities.xlsx"
    write_boq_workbook(estimate, boq_path)
    st.session_state.cost_artifacts = (chart_path, boq_path)
