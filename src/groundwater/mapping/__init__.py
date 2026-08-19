"""Maps and GIS export: site location, iso-resistivity, overburden,
regional geological setting, administrative location, and the survey as
an interactive GeoLibre project file."""

from .._lazy import lazy_exports

__all__ = [
    "site_location_map",
    "iso_resistivity_map",
    "overburden_thickness_map",
    "suitability_map",
    "MapPoint",
    "ADMIN_CREDIT",
    "GEOLOGY_CREDIT",
    "HYDRO_CREDIT",
    "AdminArea",
    "GeologyUnit",
    "chiefdom_of",
    "district_of",
    "load_admin",
    "load_chiefdoms",
    "load_geology",
    "load_hydrogeology",
    "plot_admin_map",
    "plot_coverage_choropleth",
    "plot_geological_map",
    "plot_hydrogeology_map",
    "plot_portfolio_map",
    "export_geojson",
    "export_gpkg",
    "geolibre",
    "GEOLIBRE_WEB_APP",
    "build_project",
    "data_link",
    "portfolio_project",
    "project_link",
    "site_project",
    "write_project",
]

# Deferred: these pull matplotlib, openpyxl or python-docx, which the
# analysis half of this package does not need. See groundwater._lazy.
_LAZY = {
    "site_location_map": ".maps",
    "iso_resistivity_map": ".maps",
    "overburden_thickness_map": ".maps",
    "suitability_map": ".maps",
    "MapPoint": ".maps",
    "ADMIN_CREDIT": ".regional",
    "GEOLOGY_CREDIT": ".regional",
    "HYDRO_CREDIT": ".regional",
    "AdminArea": ".regional",
    "GeologyUnit": ".regional",
    "chiefdom_of": ".regional",
    "district_of": ".regional",
    "load_admin": ".regional",
    "load_chiefdoms": ".regional",
    "load_geology": ".regional",
    "load_hydrogeology": ".regional",
    "plot_admin_map": ".regional",
    "plot_coverage_choropleth": ".regional",
    "plot_geological_map": ".regional",
    "plot_hydrogeology_map": ".regional",
    "plot_portfolio_map": ".regional",
    "export_geojson": ".export",
    "export_gpkg": ".export",
    "GEOLIBRE_WEB_APP": ".geolibre",
    "build_project": ".geolibre",
    "data_link": ".geolibre",
    "portfolio_project": ".geolibre",
    "project_link": ".geolibre",
    "site_project": ".geolibre",
    "write_project": ".geolibre",
}
_LAZY_MODULES = ("geolibre",)

__getattr__, __dir__ = lazy_exports(__name__, _LAZY, _LAZY_MODULES)
