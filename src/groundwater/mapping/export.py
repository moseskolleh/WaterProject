"""GIS layer export: GeoJSON always, GeoPackage when geopandas is
installed (``pip install groundwater-toolkit[gis]``)."""

from __future__ import annotations

import json
from pathlib import Path

from ..geo import utm_to_geographic
from .maps import MapPoint


def export_geojson(
    points: list[MapPoint],
    zone: int,
    path: str | Path,
    extra_properties: dict[str, dict] | None = None,
) -> Path:
    """Write survey points as a WGS84 GeoJSON FeatureCollection.

    ``extra_properties`` maps point label to additional attribute
    dictionaries (for example layer tables or water zones).
    """
    features = []
    for p in points:
        lat, lon = utm_to_geographic(p.easting, p.northing, zone)
        props = {
            "label": p.label,
            "kind": p.kind,
            "easting_utm": p.easting,
            "northing_utm": p.northing,
            "utm_zone": f"{zone}N",
        }
        if p.value is not None:
            props["value"] = p.value
        if extra_properties and p.label in extra_properties:
            props.update(extra_properties[p.label])
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": props,
            }
        )
    collection = {"type": "FeatureCollection", "features": features}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(collection, fh, indent=2)
    return path


def export_gpkg(
    points: list[MapPoint],
    zone: int,
    path: str | Path,
    layer: str = "survey_points",
) -> Path:
    """Write survey points to a GeoPackage (requires geopandas)."""
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except ImportError as exc:
        raise ImportError(
            "GeoPackage export needs geopandas; install with "
            "'pip install groundwater-toolkit[gis]' or use export_geojson()"
        ) from exc

    records = []
    geometry = []
    for p in points:
        records.append(
            {
                "label": p.label,
                "kind": p.kind,
                "value": p.value,
                "easting_utm": p.easting,
                "northing_utm": p.northing,
            }
        )
        geometry.append(Point(p.easting, p.northing))
    epsg = 32600 + zone  # WGS84 / UTM north
    gdf = gpd.GeoDataFrame(records, geometry=geometry, crs=f"EPSG:{epsg}")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, layer=layer, driver="GPKG")
    return path
