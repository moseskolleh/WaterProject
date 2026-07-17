"""Shared helpers: caches, uploads, project persistence, shared compute."""

from __future__ import annotations

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
from groundwater.supervision import load_checklists, load_separation_distances
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


def project_file_bytes() -> bytes:
    """Serialize the widget state that makes up a project."""
    state = {
        key: value
        for key, value in st.session_state.items()
        if key.startswith(_PERSIST_PREFIXES)
        and isinstance(value, (str, int, float, bool))
    }
    payload = {
        "groundwater_toolkit_project": groundwater.__version__,
        "rates_overrides": st.session_state.get("rates_overrides", {}),
        "state": state,
    }
    return yaml.safe_dump(payload, sort_keys=True).encode("utf-8")


def load_project_upload() -> None:
    """Apply an uploaded project file (button callback, runs pre-render)."""
    upload = st.session_state.get("project_upload")
    if upload is None:
        return
    try:
        payload = yaml.safe_load(upload.getvalue().decode("utf-8"))
        assert isinstance(payload, dict)
        assert isinstance(payload.get("state"), dict)
    except Exception:
        st.session_state.project_load_error = True
        return
    for key, value in payload["state"].items():
        if key.startswith(_PERSIST_PREFIXES) and isinstance(
            value, (str, int, float, bool)
        ):
            st.session_state[key] = value
    overrides = payload.get("rates_overrides") or {}
    if isinstance(overrides, dict):
        st.session_state.rates_overrides = {
            str(code): float(rate) for code, rate in overrides.items()
        }
    # reset the rate editor so it shows the loaded values
    st.session_state.pop("rates_editor", None)
    st.session_state.project_loaded = True
    # protect restored inputs from the prefill-reset checks for one run
    st.session_state.project_just_loaded = True
    # the wizard costing block only executes on its step, so it carries
    # its own grace marker, consumed when that block first runs
    st.session_state["_wiz_load_grace"] = True


def app_config() -> Config:
    """Config with the sidebar branding applied (per rerun, not global)."""
    cfg = Config()
    cfg.style.organisation = st.session_state.get("org_name", "") or ""
    cfg.style.organisation_details = st.session_state.get("org_details", "") or ""
    return cfg


# ---------------------------------------------------------------------------
# Shared compute: results several tabs read from session state
# ---------------------------------------------------------------------------


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
