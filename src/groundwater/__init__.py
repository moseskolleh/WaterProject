"""Groundwater investigation analysis and reporting toolkit.

A modular toolkit for rural water supply borehole projects in Sierra
Leone, covering geophysical siting surveys (VES), borehole design,
drilling records, pumping tests, water quality assessment and report
generation.

Subpackages
-----------
ingestion
    Data templates, parsers and metadata consistency checks.
ves
    Vertical electrical sounding analysis: geometric factors, forward
    modelling, 1D inversion, IPI2Win import, curve classification,
    hydrogeological interpretation and plotting.
hydraulics
    Pumping test analysis: Cooper-Jacob, Theis, recovery, step tests,
    specific capacity and safe yield.
quality
    Water quality assessment against WHO and national standards.
design
    Borehole design rules and to-scale schematic drawings.
mapping
    Site maps, iso-resistivity and overburden thickness maps, GIS export.
reporting
    Templated .docx report generation.
"""

__version__ = "0.1.0"

from .project import Project

__all__ = ["Project", "__version__"]
