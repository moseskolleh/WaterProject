"""Maps and GIS export.

Three scales, and a section through the ground beneath them:

* **the country** - administrative location, the borehole portfolio, the
  coverage choropleth;
* **the study area** - the local map a report opens on, with its locator
  inset, and the regional geology, aquifer and topographic settings;
* **the survey** - the site plan, the iso-resistivity and overburden
  surfaces, and the subsurface maps built from the interpretations
  themselves;
* **beneath it** - the apparent-resistivity pseudo-section and the
  geo-electric section along the traverse.

Plus the survey as an interactive GeoLibre project file, and GeoJSON and
GeoPackage export.
"""

from .._lazy import lazy_exports as _lazy_exports

__all__ = [
    "site_location_map",
    "iso_resistivity_map",
    "overburden_thickness_map",
    "suitability_map",
    "suitability_map_state",
    "points_enclose_an_area",
    "to_zone",
    "unplaced_text",
    "MapPoint",
    "ADMIN_CREDIT",
    "GEOLOGY_CREDIT",
    "HYDRO_CREDIT",
    "AdminArea",
    "AreaWindow",
    "area_window",
    "GeologyUnit",
    "chiefdom_of",
    "aquifer_unit_at",
    "canonical_chiefdom",
    "chiefdom_full_names",
    "district_of",
    "geology_unit_at",
    "load_admin",
    "load_chiefdoms",
    "load_geology",
    "load_hydrogeology",
    "plot_admin_map",
    "plot_coverage_choropleth",
    "plot_geological_map",
    "plot_hydrogeology_map",
    "plot_portfolio_map",
    "plot_study_area_map",
    # subsurface, from this survey's own soundings
    "PROTECTIVE_CLASSES",
    "SUBSURFACE_CREDIT",
    "TraverseProfile",
    "apparent_resistivity_pseudosection",
    "aquifer_thickness_map",
    "bedrock_elevation_map",
    "bedrock_elevation_points",
    "common_ab2_spacings",
    "depth_to_bedrock_map",
    "geoelectric_section_along_traverse",
    "ground_profile_along_traverse",
    "ground_profile_state",
    "iso_resistivity_points",
    "protective_capacity_map",
    "spacing_name",
    "subsurface_map_points",
    "survey_zone",
    "transverse_resistance_map",
    "traverse_profile",
    # topography, from an elevation model the operator supplies
    "ElevationGrid",
    "hillshade",
    "load_elevation",
    "plot_ground_profile",
    "plot_topographic_map",
    "read_esri_ascii",
    "read_srtm_hgt",
    "read_xyz",
    "slope_percent",
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

# Deferred: nearly every module here draws with matplotlib, and a caller
# after one lookup - district_of for a field sheet - should not import
# the plotting stack to get it. See groundwater._lazy.
_LAZY = {
    "site_location_map": ".maps",
    "iso_resistivity_map": ".maps",
    "overburden_thickness_map": ".maps",
    "suitability_map": ".maps",
    "suitability_map_state": ".maps",
    "points_enclose_an_area": ".maps",
    "to_zone": ".maps",
    "unplaced_text": ".maps",
    "MapPoint": ".maps",
    "AreaWindow": ".regional",
    "area_window": ".regional",
    "ADMIN_CREDIT": ".regional",
    "GEOLOGY_CREDIT": ".regional",
    "HYDRO_CREDIT": ".regional",
    "AdminArea": ".regional",
    "GeologyUnit": ".regional",
    "chiefdom_of": ".regional",
    "aquifer_unit_at": ".regional",
    "canonical_chiefdom": ".regional",
    "chiefdom_full_names": ".regional",
    "district_of": ".regional",
    "geology_unit_at": ".regional",
    "load_admin": ".regional",
    "load_chiefdoms": ".regional",
    "load_geology": ".regional",
    "load_hydrogeology": ".regional",
    "plot_admin_map": ".regional",
    "plot_coverage_choropleth": ".regional",
    "plot_geological_map": ".regional",
    "plot_hydrogeology_map": ".regional",
    "plot_portfolio_map": ".regional",
    "plot_study_area_map": ".regional",
    "PROTECTIVE_CLASSES": ".subsurface",
    "SUBSURFACE_CREDIT": ".subsurface",
    "TraverseProfile": ".subsurface",
    "apparent_resistivity_pseudosection": ".subsurface",
    "aquifer_thickness_map": ".subsurface",
    "bedrock_elevation_map": ".subsurface",
    "bedrock_elevation_points": ".subsurface",
    "common_ab2_spacings": ".subsurface",
    "depth_to_bedrock_map": ".subsurface",
    "geoelectric_section_along_traverse": ".subsurface",
    "ground_profile_along_traverse": ".subsurface",
    "ground_profile_state": ".subsurface",
    "iso_resistivity_points": ".subsurface",
    "protective_capacity_map": ".subsurface",
    "spacing_name": ".subsurface",
    "subsurface_map_points": ".subsurface",
    "survey_zone": ".subsurface",
    "transverse_resistance_map": ".subsurface",
    "traverse_profile": ".subsurface",
    "ElevationGrid": ".terrain",
    "hillshade": ".terrain",
    "load_elevation": ".terrain",
    "plot_ground_profile": ".terrain",
    "plot_topographic_map": ".terrain",
    "read_esri_ascii": ".terrain",
    "read_srtm_hgt": ".terrain",
    "read_xyz": ".terrain",
    "slope_percent": ".terrain",
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

# The submodules stayed reachable as attributes of the package while
# the eager imports bound them; keep that true without importing them.
_LAZY_MODULES = (
    "maps",
    "regional",
    "subsurface",
    "terrain",
    "export",
    "geolibre",
    "lithology",
    "cartography",
)

__getattr__, __dir__ = _lazy_exports(__name__, _LAZY, _LAZY_MODULES)
