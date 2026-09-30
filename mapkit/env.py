"""Interpreter setup that MUST run before geopandas/pyproj/rasterio are imported.

Import this module first, always. `mapkit/__init__.py` does that for you, so
`import mapkit` (or any `from mapkit.x import y`) is enough -- but a script that
reaches for `geopandas` before touching mapkit will get a permanently broken
pyproj, because geopandas probes for pyproj once at import time and caches the
answer. The symptom is a later `.to_crs()` failing with

    Importing pyproj resulted in: DLL load failed while importing _context

and the fix is always import order, never the CRS you passed.

Two separate Windows conflicts are handled here:

1. rasterio's PyPI wheel bundles its OWN GDAL, which is a different build from
   the one QGIS's `osgeo` bindings link. Windows resolves same-named DLLs by
   whichever loaded first, so importing both in one process crashes. Nothing in
   mapkit may ever `from osgeo import gdal` -- contours shell out to
   gdal_contour.exe, and GeoJSON is parsed by hand (see mapkit.geojson) because
   geopandas' default pyogrio engine links a conflicting GDAL too.

2. pyproj (QGIS's) and rasterio (its own, newer) need DIFFERENT proj.db files.
   Setting the PROJ_LIB environment variable forces one on the other and breaks
   CRS lookups with a DATABASE.LAYOUT.VERSION mismatch. So pyproj is pointed at
   QGIS's copy through its own API, and rasterio's env var is left unset so it
   keeps finding its bundled data.
"""
import os
import sys
import warnings
from pathlib import Path


def _find_qgis():
    """The QGIS install supplying GDAL, PROJ and the base scientific stack.

    Looked up rather than hard-coded, so a machine with a different QGIS
    version or install location works without edits:

    1. the QGIS_ROOT environment variable, if set;
    2. the QGIS that owns this interpreter (a venv built from QGIS's bundled
       Python has sys.base_prefix = <QGIS>/apps/Python3xx);
    3. any "QGIS *" folder under Program Files, newest first.
    """
    env_root = os.environ.get("QGIS_ROOT")
    if env_root and os.path.isdir(env_root):
        return Path(env_root)
    parents = Path(sys.base_prefix).resolve().parents
    if len(parents) > 1 and (parents[1] / "bin" / "gdal_contour.exe").is_file():
        return parents[1]
    # fall back to any QGIS in Program Files, newest first
    pf = Path(r"C:\Program Files")
    if pf.is_dir():
        found = sorted((p for p in pf.glob("QGIS *") if p.is_dir()), reverse=True)
        if found:
            return found[0]
    return None


QGIS_ROOT = _find_qgis()
if QGIS_ROOT is None:
    raise RuntimeError(
        "No QGIS installation found. mapkit borrows GDAL/PROJ and the "
        "gdal_contour CLI from QGIS; set the QGIS_ROOT environment variable "
        "to its install folder."
    )

QGIS_BIN = QGIS_ROOT / "bin"
GDAL_CONTOUR_EXE = QGIS_BIN / "gdal_contour.exe"

# Make QGIS's DLLs and command-line tools findable even when this was not
# launched from inside an already-configured OSGeo4W shell.
if QGIS_BIN.is_dir():
    os.environ["PATH"] = str(QGIS_BIN) + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(QGIS_BIN))

with warnings.catch_warnings():
    warnings.simplefilter("ignore", UserWarning)
    import pyproj

# Via pyproj's own API, NOT the PROJ_LIB env var -- see the module docstring.
_proj_share = QGIS_ROOT / "share" / "proj"
if _proj_share.is_dir():
    pyproj.datadir.set_data_dir(str(_proj_share))

CRS_WGS84 = "EPSG:4326"
CRS_WEBMERC = "EPSG:3857"


def utm_epsg_for(lon, lat):
    """The WGS84 UTM CRS whose zone actually contains this longitude.

    Derived rather than configured. Hard-coding one zone and copying it from
    site to site is an easy mistake: in southern Nigeria a site east of 6 E
    belongs in zone 32N, where 31N would still "work" -- pyproj happily
    projects points ~130 km outside a zone -- while quietly distorting every
    distance, contour and scale bar on the map. A wrong zone produces a
    plausible map, not an error, so it is computed here once and never typed.
    """
    zone = int((lon + 180.0) // 6.0) + 1
    return f"EPSG:{(326 if lat >= 0 else 327)}{zone:02d}"


def crs_label(epsg):
    """'EPSG:32632' -> 'WGS84 UTM Zone 32N (EPSG:32632)', for figure captions."""
    code = str(epsg).split(":")[-1]
    if code.startswith(("326", "327")) and len(code) == 5:
        hemi = "N" if code.startswith("326") else "S"
        return f"WGS84 UTM Zone {int(code[3:])}{hemi} (EPSG:{code})"
    return f"EPSG:{code}"
