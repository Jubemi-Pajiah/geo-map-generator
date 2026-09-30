"""mapkit -- build a Study Area map, a Geologic map with an A-A' section, and a
three-panel Location map for any small survey site, from a station coordinate
file and a short site description.

    from mapkit import build_site
    build_site("example_igarra")

Importing this package configures the interpreter (GDAL/PROJ paths, the
pyproj/rasterio split) BEFORE geopandas or rasterio load, which is the one
ordering that has to be right -- see mapkit/env.py.
"""
from . import env  # noqa: F401  -- MUST be first; sets up DLL and PROJ paths

from .config import (SiteConfig, Geology, Unit, load, available,
                     BENIN_FORMATION, OGWASHI_ASABA_FORMATION,
                     BASEMENT_COMPLEX_IGARRA)

__all__ = [
    "SiteConfig", "Geology", "Unit", "load", "available",
    "BENIN_FORMATION", "OGWASHI_ASABA_FORMATION", "BASEMENT_COMPLEX_IGARRA",
    "build_site", "MAP_BUILDERS",
]

#: Map name -> builder. Used by make_maps.py so a caller can render a subset.
MAP_BUILDERS = ("location", "study_area", "geologic")


def build_site(name, maps=MAP_BUILDERS, verbose=True):
    """Render `maps` for one site. Returns {map_name: output path}."""
    from . import geologic, location, prepare, study_area

    site = load(name) if isinstance(name, str) else name
    if verbose:
        print(f"===== {site.name}: {site.subtitle} =====")

    data = prepare.prepare(site, verbose=verbose)
    if verbose:
        print(f"  CRS {data.crs}  |  traverse {data.traverse_m:.1f} m  |  "
              f"relief {data.relief_m:.1f} m  |  "
              f"vertical exaggeration x{data.vertical_exaggeration:g}")

    builders = {"location": location.build,
                "study_area": study_area.build,
                "geologic": geologic.build}
    return {m: builders[m](data, verbose=verbose) for m in maps}
