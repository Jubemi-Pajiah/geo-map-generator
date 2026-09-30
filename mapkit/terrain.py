"""Elevation: fetch a public DEM tile, clip it to the map, and derive contours.

Never imports osgeo.gdal -- contour generation shells out to gdal_contour.exe
instead, because rasterio's bundled GDAL and QGIS's osgeo bindings cannot share
a process on Windows. See mapkit/env.py.
"""
import subprocess
import urllib.request
from pathlib import Path

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.mask import mask as rio_mask
from rasterio.warp import calculate_default_transform, reproject, Resampling

from .env import GDAL_CONTOUR_EXE
from .geojson import read_geojson

DEM_NODATA = -9999.0


def dem_tile_name_for(lat, lon):
    """Copernicus GLO-30 (AWS Open Data) tile naming for a 1x1 degree cell."""
    lat_band = int(np.floor(lat))
    lon_band = int(np.floor(lon))
    ns = "N" if lat_band >= 0 else "S"
    ew = "E" if lon_band >= 0 else "W"
    name = f"Copernicus_DSM_COG_10_{ns}{abs(lat_band):02d}_00_{ew}{abs(lon_band):03d}_00_DEM"
    return name


def download_dem_tile(lat, lon, dest_dir):
    name = dem_tile_name_for(lat, lon)
    dest = dest_dir / f"{name}.tif"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = f"https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
    print(f"Downloading DEM tile: {url}")
    urllib.request.urlretrieve(url, dest)
    return dest


def clip_reproject_dem(src_path, extent_box_utm, dst_path, dst_crs,
                        pad_m=200):
    """Clip the source DEM (WGS84) to a UTM-projected extent box (padded, since
    the UTM grid is slightly rotated relative to WGS84 here, so the warped
    footprint doesn't align with an axis-aligned destination grid) and
    reproject the clipped raster into dst_crs. Cells outside the true warped
    footprint are marked nodata rather than defaulting to 0 elevation."""
    padded_extent = extent_box_utm.buffer(pad_m, join_style=2)
    extent_gdf = gpd.GeoDataFrame(geometry=[padded_extent], crs=dst_crs)
    with rasterio.open(src_path) as src:
        extent_src_crs = extent_gdf.to_crs(src.crs)
        geom = [extent_src_crs.geometry.iloc[0].__geo_interface__]
        clipped, clipped_transform = rio_mask(src, geom, crop=True, nodata=DEM_NODATA)
        clipped_meta = src.meta.copy()
        clipped_meta.update({
            "height": clipped.shape[1],
            "width": clipped.shape[2],
            "transform": clipped_transform,
            "nodata": DEM_NODATA,
        })

    transform, width, height = calculate_default_transform(
        clipped_meta["crs"], dst_crs, clipped_meta["width"], clipped_meta["height"],
        *rasterio.transform.array_bounds(clipped_meta["height"], clipped_meta["width"], clipped_transform)
    )
    dst_meta = clipped_meta.copy()
    dst_meta.update({"crs": dst_crs, "transform": transform, "width": width, "height": height})

    with rasterio.open(dst_path, "w", **dst_meta) as dst:
        reproject(
            source=clipped,
            destination=rasterio.band(dst, 1),
            src_transform=clipped_transform,
            src_crs=clipped_meta["crs"],
            src_nodata=DEM_NODATA,
            dst_transform=transform,
            dst_crs=dst_crs,
            dst_nodata=DEM_NODATA,
            resampling=Resampling.bilinear,
        )

    # final crop down to the true (unpadded) extent
    final_extent_gdf = gpd.GeoDataFrame(geometry=[extent_box_utm], crs=dst_crs)
    with rasterio.open(dst_path) as reproj_src:
        geom = [extent_box_utm.__geo_interface__]
        final_arr, final_transform = rio_mask(reproj_src, geom, crop=True, nodata=DEM_NODATA)
        final_meta = reproj_src.meta.copy()
        final_meta.update({
            "height": final_arr.shape[1],
            "width": final_arr.shape[2],
            "transform": final_transform,
        })
    with rasterio.open(dst_path, "w", **final_meta) as dst:
        dst.write(final_arr)
    return dst_path


def refine_dem_for_contours(src_path, dst_path, upsample_factor=6, smooth_sigma=1.2):
    """Fill nodata, upsample, and lightly Gaussian-smooth the DEM purely for
    cleaner-looking contour geometry -- this is standard cartographic contour
    smoothing (reduces coarse-pixel stair-stepping), not a change to the
    underlying elevation values themselves."""
    from rasterio.fill import fillnodata
    from scipy.ndimage import gaussian_filter, zoom

    with rasterio.open(src_path) as src:
        arr = src.read(1)
        mask = arr != src.nodata if src.nodata is not None else np.ones_like(arr, dtype=bool)
        filled = fillnodata(arr, mask=mask.astype("uint8"), max_search_distance=100)
        upsampled = zoom(filled, upsample_factor, order=3)
        smoothed = gaussian_filter(upsampled, sigma=smooth_sigma)

        new_transform = src.transform * src.transform.scale(
            1 / upsample_factor, 1 / upsample_factor)
        meta = src.meta.copy()
        meta.update({
            "height": smoothed.shape[0],
            "width": smoothed.shape[1],
            "transform": new_transform,
            "nodata": None,
        })

    with rasterio.open(dst_path, "w", **meta) as dst:
        dst.write(smoothed.astype(meta["dtype"]), 1)
    return dst_path


def generate_contours(dem_path, out_geojson, crs, interval=1.0):
    """Shell out to gdal_contour.exe (never import osgeo.gdal in-process)."""
    out_geojson = Path(out_geojson)
    if out_geojson.exists():
        out_geojson.unlink()
    cmd = [
        str(GDAL_CONTOUR_EXE),
        "-a", "elev",
        "-i", str(interval),
        "-f", "GeoJSON",
        str(dem_path),
        str(out_geojson),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gdal_contour failed: {result.stderr}")
    return read_geojson(out_geojson, crs=crs)


def sample_raster_along_line(dem_path, line_utm, n_samples=200):
    """Sample DEM elevation at n_samples points evenly spaced along a UTM LineString."""
    distances = np.linspace(0, line_utm.length, n_samples)
    pts = [line_utm.interpolate(d) for d in distances]
    coords = [(p.x, p.y) for p in pts]
    with rasterio.open(dem_path) as src:
        values = [v[0] for v in src.sample(coords)]
    values = np.array(values, dtype=float)
    nodata = None
    with rasterio.open(dem_path) as src:
        nodata = src.nodata
    if nodata is not None:
        values[values == nodata] = np.nan
    return distances, values
