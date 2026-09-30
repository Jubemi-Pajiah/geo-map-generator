"""OpenStreetMap (Overpass) and administrative boundaries (geoBoundaries).

Real vector data, not tile imagery -- what makes the geologic map read like a
drafted base map rather than a screenshot. Every layer is cached to disk on
first fetch, so re-rendering while tuning the cartography costs no requests.
"""
import json
import time
import urllib.request
import warnings
from pathlib import Path

import numpy as np
import geopandas as gpd
from shapely.geometry import Point, LineString, shape as shapely_shape

from .env import CRS_WGS84

# Public Overpass instances are free and shared, and 429/504 constantly --
# try several mirrors before giving up on any one request.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]
_OVERPASS_HEADERS = {
    "Content-Type": "text/plain",
    "User-Agent": "geo-map-generator/1.0 (mapkit)",
}


def _query_overpass(query, dest_path, force=False, retries=5):
    """Run an Overpass query with caching + retry across mirror instances.

    Backoff is EXPONENTIAL (10s, 20s, 40s, 80s, capped at 120s), not a flat
    5s. The public instances' failure modes are 429 rate-limits and 504
    overload, and both clear on a timescale of a minute or more -- retrying
    three times five seconds apart just burns all the attempts inside a
    single bad window and reports failure while the server is merely busy.
    Two clean reruns of this project died exactly that way."""
    dest_path = Path(dest_path)
    if dest_path.exists() and not force:
        with open(dest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    raw, last_err = None, None
    for attempt in range(retries + 1):
        for url in OVERPASS_URLS:
            try:
                req = urllib.request.Request(url, data=query.encode(), headers=_OVERPASS_HEADERS)
                with urllib.request.urlopen(req, timeout=90) as resp:
                    raw = json.loads(resp.read())
                break
            except Exception as e:
                last_err = e
                print(f"Overpass request to {url} failed ({e}), trying next option...")
        if raw is not None:
            break
        if attempt < retries:
            delay = min(10 * (2 ** attempt), 120)
            print(f"  all mirrors failed (round {attempt + 1}/{retries + 1}); "
                  f"backing off {delay}s before retrying...")
            time.sleep(delay)
    if raw is None:
        raise RuntimeError(f"All Overpass endpoints failed after retries: {last_err}")
    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    return raw


def fetch_osm_lines(bbox_wgs84, dest_path, force=False, retries=5):
    """Fetch OSM roads + waterways (real vector data, not tile imagery) within
    a WGS84 bbox (minx, miny, maxx, maxy) via the public Overpass API, cache
    to dest_path, and return a GeoDataFrame in EPSG:4326 with columns
    kind ('road'/'waterway'), highway, waterway, name."""
    minx, miny, maxx, maxy = bbox_wgs84
    query = f"""
    [out:json][timeout:40];
    (
      way["highway"]({miny},{minx},{maxy},{maxx});
      way["waterway"]({miny},{minx},{maxy},{maxx});
      way["natural"="water"]({miny},{minx},{maxy},{maxx});
    );
    out body geom;
    """
    raw = _query_overpass(query, dest_path, force, retries)

    records, geoms = [], []
    for el in raw.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el or len(el["geometry"]) < 2:
            continue
        tags = el.get("tags", {})
        coords = [(pt["lon"], pt["lat"]) for pt in el["geometry"]]
        kind = "waterway" if ("waterway" in tags or tags.get("natural") == "water") else "road"
        records.append({
            "kind": kind,
            "highway": tags.get("highway"),
            "waterway": tags.get("waterway"),
            "name": tags.get("name"),
        })
        geoms.append(LineString(coords))
    return gpd.GeoDataFrame(records, geometry=geoms, crs=CRS_WGS84)


PLACE_TAGS = ["suburb", "neighbourhood", "quarter", "village", "town",
              "hamlet", "city_block", "locality"]


def fetch_osm_places(bbox_wgs84, dest_path, force=False, retries=5):
    """Fetch named OSM place/locality nodes (real settlement/area names, like
    a traditional hand-drafted base map shows) within a WGS84 bbox via the
    public Overpass API. Returns a GeoDataFrame in EPSG:4326 with columns
    place (suburb/village/etc.) and name. May legitimately return zero rows
    at a hyper-local scale -- do not fabricate names if so."""
    minx, miny, maxx, maxy = bbox_wgs84
    place_filter = "|".join(PLACE_TAGS)
    query = f"""
    [out:json][timeout:40];
    (
      node["place"~"^({place_filter})$"]({miny},{minx},{maxy},{maxx});
    );
    out body;
    """
    raw = _query_overpass(query, dest_path, force, retries)

    records, geoms = [], []
    for el in raw.get("elements", []):
        if el.get("type") != "node" or "lat" not in el:
            continue
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        records.append({"place": tags.get("place"), "name": name})
        geoms.append(Point(el["lon"], el["lat"]))
    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs=CRS_WGS84)
    return _merge_colocated_places(gdf)


def _merge_colocated_places(places_gdf, tol_deg=1e-4):
    """Collapse place nodes mapped at (effectively) the same coordinate into a
    single labeled point, joining their names ('Name A / Name B').

    OSM sometimes carries one settlement as two nodes at an identical
    position under rival transliterations. Plotting both stacks two labels on
    the same pixel; dropping one silently picks a winner between two
    equally-valid spellings, so joining them is the honest option. Most
    frames never trip it, but the helper stays wired up so the layer
    behaves the same wherever this pipeline is pointed next."""
    if places_gdf.empty:
        return places_gdf
    gdf = places_gdf.copy()
    gdf["_kx"] = (gdf.geometry.x / tol_deg).round().astype(int)
    gdf["_ky"] = (gdf.geometry.y / tol_deg).round().astype(int)
    merged = (
        gdf.groupby(["_kx", "_ky"], as_index=False)
           .agg(name=("name", lambda s: " / ".join(sorted(dict.fromkeys(s)))),
                place=("place", "first"),
                geometry=("geometry", "first"))
    )
    return gpd.GeoDataFrame(merged.drop(columns=["_kx", "_ky"]),
                            geometry="geometry", crs=places_gdf.crs)


def fetch_osm_markets(bbox_wgs84, dest_path, force=False, retries=5, optional=True):
    """Fetch named marketplace nodes/ways (real, notable local landmarks --
    unlike amenity=place_of_worship, which returns hundreds of small
    individual churches, marketplaces are few and genuinely map-worthy).
    Deduplicates by name (a market is often mapped as many adjacent nodes).
    Returns (GeoDataFrame in EPSG:4326 with a name column, fetch_ok).

    With optional=True an Overpass outage degrades to an empty result plus a
    loud warning instead of killing the whole map: this is a garnish layer,
    and the free public instances rate-limit and 5xx constantly (a clean
    end-to-end rerun of this project died here on an HTTP 429 with every
    mirror down). fetch_ok distinguishes 'asked, and there are none' from
    'never got an answer' -- the caller must not report the second as the
    first."""
    minx, miny, maxx, maxy = bbox_wgs84
    query = f"""
    [out:json][timeout:40];
    (
      node["amenity"="marketplace"]({miny},{minx},{maxy},{maxx});
      way["amenity"="marketplace"]({miny},{minx},{maxy},{maxx});
    );
    out center;
    """
    try:
        raw = _query_overpass(query, dest_path, force, retries)
    except RuntimeError as e:
        if not optional:
            raise
        print(f"  WARNING: marketplace layer unavailable (Overpass failed: {e}). "
              f"Map will render WITHOUT it -- this is NOT evidence that the area has no markets.")
        return gpd.GeoDataFrame({"name": []}, geometry=[], crs=CRS_WGS84), False

    seen, records, geoms = set(), [], []
    for el in raw.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name or name in seen:
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        seen.add(name)
        records.append({"name": name})
        geoms.append(Point(lon, lat))
    return gpd.GeoDataFrame(records, geometry=geoms, crs=CRS_WGS84), True


NIGERIA_ADM1_URL = (
    "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/"
    "NGA/ADM1/geoBoundaries-NGA-ADM1_simplified.geojson"
)


NIGERIA_ADM2_URL = (
    "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/"
    "NGA/ADM2/geoBoundaries-NGA-ADM2_simplified.geojson"
)


def _ensure_boundary_file(geojson_path, url):
    geojson_path = Path(geojson_path)
    if not geojson_path.exists() or geojson_path.stat().st_size == 0:
        print(f"Downloading boundaries: {url}")
        urllib.request.urlretrieve(url, geojson_path)
    return geojson_path


def _load_geoboundaries(geojson_path):
    """Parse a geoBoundaries GeoJSON into a GeoDataFrame (EPSG:4326) with a
    'name' column taken from shapeName."""
    with open(geojson_path, "r", encoding="utf-8") as f:
        gj = json.load(f)
    records, geoms = [], []
    for feat in gj["features"]:
        records.append({"name": feat["properties"].get("shapeName")})
        geoms.append(shapely_shape(feat["geometry"]))
    return gpd.GeoDataFrame(records, geometry=geoms, crs=CRS_WGS84)


def load_state_boundary(geojson_path, state_name):
    """Load one state's polygon (WGS84) from Nigeria's ADM1 boundaries
    (geoBoundaries, CC-BY 4.0), downloading the file first if not cached.

    Parameterised by state rather than hard-wired to one: the boundary file
    is national, so the only thing that actually differs between sites in
    different states is which shapeName to match."""
    _ensure_boundary_file(geojson_path, NIGERIA_ADM1_URL)
    with open(geojson_path, "r", encoding="utf-8") as f:
        gj = json.load(f)
    for feat in gj["features"]:
        if feat["properties"].get("shapeName") == state_name:
            return gpd.GeoDataFrame(
                [{"name": state_name}], geometry=[shapely_shape(feat["geometry"])],
                crs=CRS_WGS84)
    raise ValueError(f"State {state_name!r} not found in {geojson_path}")


def load_nigeria_states(geojson_path):
    """All 36 states + FCT (geoBoundaries NGA ADM1, CC-BY 4.0)."""
    _ensure_boundary_file(geojson_path, NIGERIA_ADM1_URL)
    return _load_geoboundaries(geojson_path)


def load_nigeria_lgas(geojson_path, within=None):
    """All Nigerian LGAs (geoBoundaries NGA ADM2, CC-BY 4.0). If `within` is a
    polygon in EPSG:4326, keep only the LGAs mostly inside it -- ADM2 carries
    no parent-state attribute, so a state's LGAs must be selected spatially.
    Uses a majority-overlap test rather than a point-in-polygon or `within`
    test because the simplified ADM1 and ADM2 outlines don't nest exactly, so
    strict containment silently drops real border LGAs."""
    _ensure_boundary_file(geojson_path, NIGERIA_ADM2_URL)
    gdf = _load_geoboundaries(geojson_path)
    if within is not None:
        geoms = gdf.geometry.buffer(0)          # repair any self-intersections first
        parent = within.buffer(0)
        # Areas are in square degrees, which geopandas warns about -- harmless
        # here because this is a ratio of two areas of the same small polygon in
        # the same CRS, so the degree-to-metre distortion cancels out.
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*geographic CRS.*")
            frac = geoms.intersection(parent).area / geoms.area.replace(0, np.nan)
        gdf = gdf[frac > 0.5].reset_index(drop=True)
    return gdf
