"""Read GeoJSON without touching pyogrio or fiona.

geopandas' default vector engine (pyogrio) links its own GDAL/OGR build, which
collides with the one rasterio's wheel bundles the moment both are loaded in
one process on Windows. GeoJSON is plain JSON, so parsing it directly sidesteps
the whole problem -- see mapkit/env.py for the full story.
"""
import json

import geopandas as gpd
from shapely.geometry import shape as shapely_shape


def read_geojson(path, crs=None):
    """Parse a GeoJSON file into a GeoDataFrame without touching pyogrio/fiona.
    Needed because rasterio's bundled GDAL and QGIS's OGR bindings (used by
    pyogrio) collide with a DLL version conflict when both are loaded in the
    same process on Windows -- see module docstring."""
    with open(path, "r", encoding="utf-8") as f:
        gj = json.load(f)
    if crs is None and gj.get("crs"):
        crs = gj["crs"]["properties"]["name"]  # e.g. "urn:ogc:def:crs:EPSG::32632"
    records = []
    geoms = []
    for feat in gj["features"]:
        records.append(feat.get("properties", {}))
        geoms.append(shapely_shape(feat["geometry"]))
    return gpd.GeoDataFrame(records, geometry=geoms, crs=crs)
