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

from .maps import (
    site_location_map,
    iso_resistivity_map,
    overburden_thickness_map,
    suitability_map,
    suitability_map_state,
    points_enclose_an_area,
    to_zone,
    unplaced_text,
    MapPoint,
)
from .regional import (
    AreaWindow,
    area_window,
    ADMIN_CREDIT,
    GEOLOGY_CREDIT,
    HYDRO_CREDIT,
    AdminArea,
    GeologyUnit,
    chiefdom_of,
    aquifer_unit_at,
    canonical_chiefdom,
    chiefdom_full_names,
    district_of,
    geology_unit_at,
    load_admin,
    load_chiefdoms,
    load_geology,
    load_hydrogeology,
    plot_admin_map,
    plot_coverage_choropleth,
    plot_geological_map,
    plot_hydrogeology_map,
    plot_portfolio_map,
    plot_study_area_map,
)
from .subsurface import (
    PROTECTIVE_CLASSES,
    SUBSURFACE_CREDIT,
    TraverseProfile,
    apparent_resistivity_pseudosection,
    aquifer_thickness_map,
    bedrock_elevation_map,
    bedrock_elevation_points,
    common_ab2_spacings,
    depth_to_bedrock_map,
    geoelectric_section_along_traverse,
    ground_profile_along_traverse,
    ground_profile_state,
    iso_resistivity_points,
    protective_capacity_map,
    spacing_name,
    subsurface_map_points,
    survey_zone,
    transverse_resistance_map,
    traverse_profile,
)
from .terrain import (
    ElevationGrid,
    hillshade,
    load_elevation,
    plot_ground_profile,
    plot_topographic_map,
    read_esri_ascii,
    read_srtm_hgt,
    read_xyz,
    slope_percent,
)
from .export import export_geojson, export_gpkg
from . import geolibre
from .geolibre import (
    GEOLIBRE_WEB_APP,
    build_project,
    data_link,
    portfolio_project,
    project_link,
    site_project,
    write_project,
)

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
