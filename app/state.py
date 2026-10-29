"""The session state the app's pages share, in one place.

Streamlit keeps one ``st.session_state`` per browser session, and every
page reads and writes it. Until PLAN.md step 1.1 every page ran on every
rerun and was then hidden, so a page could rely on another having run
earlier in the same rerun, and a widget kept its value because it was
drawn every time. Now only the page on screen runs. What one page leaves
for another has to be in session state under a documented key, and a
widget whose value has to outlive its page has to be carried across the
switch, because Streamlit drops the state of every widget a run does not
draw.

The schema, by kind of key:

Navigation
    ``nav``: the title of the page on screen, set by the sidebar's grouped
    radios, by every "next step" button and by tests. It is the one source
    of truth for which page runs. ``_page_url`` is the page the browser's
    address last showed (see ``streamlit_app.resolve_page``), and
    ``workdir`` the session's working folder, where every file it builds
    is written.

Results (plain state, written by a page or by the recompute on load)
    ``ves_results`` (soundings, inversions, interpretations),
    ``pump_analysis``, ``wq_assessment``, ``drilling_log``,
    ``borehole_design``, ``cost_estimate`` and ``cost_artifacts``,
    ``programme_estimate``, ``field_checks``, ``handover_built``,
    ``wp_result``, ``spine_ledger``, the map paths (``map_paths``,
    ``subsurface_paths``, ``section_path``, ``pseudosection_path``,
    ``profile_path``, ``topo_path``, ``traverse``, ``geolibre_path``,
    ``geolibre_area``, ``geolibre_layers``; the Portfolio page's own
    ``geolibre_portfolio``), the Portfolio page's calibration report
    (``calibration_report``: its path and a digest of the pooled ledgers it
    was built from, offered only while they are the ones on the page), its
    calibration set fitted and under review (``calibration_candidate``: the
    set and a digest of the pooled ledgers and the set in force it was
    fitted under, reviewed only while both hold) and the sentence its last
    put-in-force left for the next run (``calibration_told``), the
    topographic map's source and read report
    (``topo_source``, ``topo_report``) and what it was drawn from
    (``topo_inputs``: the elevation files' upload ids and the source
    declared for them; the map is shown only while they still hold), the
    terrain analysis as the page keeps it (``terrain_result``: the folder
    its run wrote its figures and its drainage lines' GeoJSON to, deleted
    when the result is, and their paths, its summary, captions and read
    report, and the files and source it was worked out from, under the
    same rule; the analysis's own layers are not kept),
    ``asset_record``, ``proc_contract_lines``, ``proc_measured``,
    ``proc_variations``, ``artifacts`` (built files, label -> path; a
    project load takes the outgoing site's maps off it),
    ``project_summary``, ``inversion_cache`` and ``recompute_diagnostics``.

The calibration set in force (session-wide, PLAN.md step 5.3)
    ``calibration_set`` (``shared.CALIBRATION_SET``): the set a named
    person adopted, or loaded from a calibration.yaml, on the Portfolio
    page; absent or None for the provisional default. ``shared.app_config``
    puts it in force on every page. It belongs to the session, not to a
    project: no project file carries it, and opening one leaves it in force.

Project inputs (saved in the project file)
    Every key starting with one of ``groundwater.project_io.PERSIST_PREFIXES``
    (``meta_``, ``org_``, ``chk_``, ``rmk_``, ``cost_``, ``fx_``, ``ho_``,
    ``wiz_``, ``q_``, ``design_``) but the guided start's buttons
    (``shared.UNSAVED_BUTTONS``), the stored sources ``src_<role>`` (an
    uploaded file's name and bytes, or a bundled sample's path),
    ``rates_overrides``, ``ho_committee_data`` and ``sup_evidence`` (the
    photographs attached to supervision checklist items, each with its
    provenance record, saved under ``evidence``).

Invalidation markers
    ``pump_source_sig``, ``cost_design_sig``, ``wiz_prefill_sig`` and
    ``design_swl_prefilled`` remember what an input was last set from, so a
    new source clears inputs typed for the old one. ``project_just_loaded``
    marks the run a project file was applied in (the loaded inputs are not
    cleared on it) and ``_wiz_load_grace`` does the same for the guided
    start's costing step, which may be reached many runs later.

Kept uploads
    ``<key>_kept``: the file in the uploader keyed ``<key>``, kept while its
    page is not on screen (see ``shared.kept_upload``), as bytes, or for the
    elevation model's uploader (``dem_upload``) as names and paths of files
    written to ``workdir/kept/dem_upload``. A project load clears the data
    uploaders' (``upload_<role>_kept``) with the uploaders and their
    ``src_`` entries. An elevation model, its kept files, the terrain
    settings (``terrain_*``) and the figures drawn from it (``topo_path``,
    ``topo_source``, ``topo_report``, ``topo_inputs``, ``terrain_result``)
    are session-only and are dropped when a project is loaded too, with
    every other map of the site (``map_paths``, ``profile_path``,
    ``subsurface_paths``, ``section_path``, ``pseudosection_path``,
    ``traverse``) and its GeoLibre file (``geolibre_path``,
    ``geolibre_area``, ``geolibre_layers``): they belong to the outgoing
    site, and the project file does not carry them.
    The Portfolio page's GeoLibre file is of the pooled sites and stays.
    The other kept uploads (a scan, a water point export, the files pooled
    on the Portfolio and the registry) are not part of a project and
    outlive a load, as their uploaders did. The ``terrain_`` inputs are
    carried between pages (below) until then.

Carried widget values
    ``carried(key)`` below says which widget values survive while their
    page is off screen. Everything else a page draws starts again from its
    default when the page comes back, as it would in any multipage
    Streamlit app. A page's inputs reach session state, and so the project
    file, once the page has been opened: a project saved before then leaves
    them out, where every page used to write its defaults into every file,
    and a load draws them at those same defaults.

Fragments
    A part of a page that reruns on its own (``st.fragment``) holds only
    inputs that are not saved in the project file. The sidebar's Save
    project button is drawn on full runs, and would fall behind an input
    saved from a fragment rerun.
"""

from __future__ import annotations

from collections.abc import MutableMapping

NAV = "nav"
PAGE_URL = "_page_url"

#: Widget keys, by prefix, whose value is kept while their page is off
#: screen. These are the inputs a user types or picks on a page and expects
#: to find when they come back, and the inputs another page reads (the
#: pumping test's month and swing, which the borehole design uses). Buttons,
#: uploaders and data editors are never carried: Streamlit refuses a value
#: set on any of them, and each has its own way of keeping what it holds
#: (``shared.kept_upload``; the editors' tables live in ``rates_overrides``,
#: ``ho_committee_data``, ``proc_measured`` and ``proc_variations``). Nor is
#: a picker whose options change with the data (the iso-resistivity
#: spacing, the portfolio's site): Streamlit refuses a value set through
#: the Session State API that is not among a widget's options.
CARRIED_PREFIXES = (
    "sample_",      # bundled-sample pickers
    "q_",           # pumping test step discharges
    "seasonal_",    # the pumping test's month and annual swing
    "cost_",        # costing inputs
    "fx_",          # supervision field acceptance checks
)
CARRIED_KEYS = frozenset({
    "design_swl",
    "wiz_manual_depth", "wiz_cost_depth", "wiz_cost_over", "wiz_cost_dist",
    "sup_stage", "meta_community_rep",
    "ho_pump_type", "ho_tariff", "ho_committee_notes", "ho_works", "ho_recs",
    "ho_contractor_rep", "ho_client_rep", "ho_community_rep",
    "map_radius", "study_area_geology", "wp_radius",
    # the elevation model's declared source, a picker with fixed options,
    # and the terrain analysis's radius and drainage threshold; a project
    # load still clears them with the model (project_io's "terrain_" prefix)
    "terrain_source", "terrain_source_text", "terrain_radius_km", "terrain_area_km2",
    "cov_source", "cov_resolution", "cov_year", "cov_rate",
    "asset_lookup",
    # the service rounds' area mechanics by chiefdom (PLAN.md step 7.3),
    # saved with the project by its org_ prefix
    "org_area_mechanics",
    # the report address plates link to (PLAN.md step 7.1), saved likewise,
    # and the day for SMS messages that carry none, which is not
    "org_report_url", "reports_received_on",
    "proc_ref", "proc_retention", "proc_advance", "proc_number", "proc_date",
    "proc_previous",
})


def carried(key: str) -> bool:
    """Whether a widget value under this key is kept while its page is off screen."""
    key = str(key)
    return key in CARRIED_KEYS or key.startswith(CARRIED_PREFIXES)


def carry_widget_values(session: MutableMapping) -> list[str]:
    """Keep the carried widget values through this run, drawn or not.

    Streamlit removes a widget's value at the end of a run that does not
    draw it. A value written through the Session State API is kept instead,
    until the run after next, when Streamlit files it under the widget
    again. So every value is written back to itself on every run, before any
    widget is drawn: Streamlit's documented way to keep a widget's value
    across pages. A widget drawn this run then starts from the same value it
    would have had, and one that is not keeps it for the page's return.
    """
    keys = [key for key in list(session) if carried(key)]
    for key in keys:
        session[key] = session[key]
    return keys
