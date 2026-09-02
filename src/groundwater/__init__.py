"""Groundwater investigation toolkit for rural water supply boreholes.

Subpackages
-----------
ingestion
    Excel/CSV field-sheet templates, parsers and metadata consistency checks.
ves
    Vertical electrical sounding: geometric factors, 1D forward model and
    inversion, IPI2Win import, curve classification, interpretation.
hydraulics
    Pumping test analysis (Cooper-Jacob, Theis, recovery, step tests),
    safe yield and pump setting depth.
quality
    Water quality against WHO and national standards, ionic balance,
    indices, corrosivity, Piper and Stiff diagrams.
design
    Borehole construction design rules and to-scale drawings.
costing
    RWSN-style cost model, bills of quantities, programme estimates,
    enterprise calculators and Excel export.
supervision
    Drilling supervision checklists and numeric field acceptance checks.
mapping
    Site, geology and aquifer maps, GIS export, GeoLibre project files.
siting
    Suitability scoring of drill targets.
reporting
    House-styled .docx report builders, one per document.
extraction
    Scanned field sheet extraction with review flagging.
depth_spine
    The interactive borehole workspace and its Streamlit bridge.

Modules
-------
readiness, seasonal, planning, procurement, registry, qr, coverage,
waterpoints, portfolio, recompute, project, project_io, units, geo, config,
models, utils.
"""

from importlib import metadata as _metadata

try:
    # single source of truth is pyproject.toml; the literal below is only
    # for a checkout that was never installed
    __version__ = _metadata.version("groundwater-toolkit")
except _metadata.PackageNotFoundError:  # pragma: no cover - uninstalled checkout
    __version__ = "0.2.0"

from .project import Project

__all__ = ["Project", "__version__"]
