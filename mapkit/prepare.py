"""Everything the three maps share, computed once per site.

The reference pipeline had each map script call load_stations() and fetch its
own OSM layers independently, so a full run parsed the stations three times and
each map re-derived the same extents. More importantly the maps could disagree:
whichever ran first wrote the shared OSM cache at ITS extent, and the others
silently reused it. Preparing one bundle up front makes the three maps
consistent by construction.
"""
from dataclasses import dataclass

import geopandas as gpd
from shapely.geometry import box

from . import osm, stations as stations_mod, terrain
from .env import CRS_WGS84


@dataclass
class SiteData:
    site: object
    crs: str
    stations: object            # EPSG:4326
    stations_utm: object
    roads_utm: object
    rivers_utm: object
    places_utm: object
    markets_utm: object
    markets_ok: bool
    line_utm: object
    station_dists: list
    station_elevs: list

    def extent(self, buffer_m):
        """(box, minx, miny, maxx, maxy) in the site CRS: the stations' convex
        hull buffered, then squared off so the frame is not an odd rectangle."""
        hull = self.stations_utm.union_all().convex_hull
        minx, miny, maxx, maxy = hull.buffer(buffer_m).bounds
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        half = max(maxx - minx, maxy - miny) / 2
        minx, maxx = cx - half, cx + half
        miny, maxy = cy - half, cy + half
        return box(minx, miny, maxx, maxy), minx, miny, maxx, maxy

    @property
    def traverse_m(self):
        return self.station_dists[-1] if self.station_dists else 0.0

    @property
    def relief_m(self):
        return (max(self.station_elevs) - min(self.station_elevs)
                if self.station_elevs else 0.0)

    @property
    def vertical_exaggeration(self):
        return self.site.resolved_vertical_exaggeration(self.traverse_m, self.relief_m)


def prepare(site, verbose=True):
    st = stations_mod.load(site, verbose=verbose)
    lon0, lat0 = float(st["lon"].mean()), float(st["lat"].mean())
    crs = site.resolve_crs(lon0, lat0)
    st_utm = st.to_crs(crs)

    line = stations_mod.cross_section_line(st_utm)
    dists = stations_mod.cumulative_distance(line)

    # One bbox for every OSM layer, sized to the widest map -- see
    # SiteConfig.osm_fetch_buffer_m for why this must not be per-map.
    hull = st_utm.union_all().convex_hull.buffer(site.osm_fetch_buffer_m)
    minx, miny, maxx, maxy = hull.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half = max(maxx - minx, maxy - miny) / 2
    padded = box(cx - half, cy - half, cx + half, cy + half).buffer(120)
    bbox = gpd.GeoDataFrame(geometry=[padded], crs=crs).to_crs(CRS_WGS84).total_bounds

    data_dir = site.data_dir
    lines = osm.fetch_osm_lines(bbox, data_dir / "osm_lines.geojson")
    roads = lines[lines["kind"] == "road"]
    rivers = lines[lines["kind"] == "waterway"]
    places = osm.fetch_osm_places(bbox, data_dir / "osm_places.geojson")
    markets, markets_ok = osm.fetch_osm_markets(bbox, data_dir / "osm_markets.geojson")
    if not markets.empty:
        # Drop the generic unnamed "Market" results; they are noise, not places.
        markets = markets[markets["name"].str.lower() != "market"]

    if verbose:
        named = sorted(roads[roads["name"].notna()]["name"].unique())
        print(f"  OSM in fetch bbox: {len(roads)} roads "
              f"({len(named)} named), {len(rivers)} waterways, "
              f"{len(places)} place nodes, {len(markets)} markets"
              f"{'' if markets_ok else ' (markets fetch FAILED, not "none here")'}")
        if named:
            print(f"  named roads: {', '.join(named[:6])}"
                  f"{' ...' if len(named) > 6 else ''}")

    return SiteData(
        site=site, crs=crs, stations=st, stations_utm=st_utm,
        roads_utm=roads.to_crs(crs) if not roads.empty else roads,
        rivers_utm=rivers.to_crs(crs) if not rivers.empty else rivers,
        places_utm=places.to_crs(crs) if not places.empty else places,
        markets_utm=markets.to_crs(crs) if not markets.empty else markets,
        markets_ok=markets_ok,
        line_utm=line, station_dists=dists,
        station_elevs=list(st_utm["elev_m"]),
    )


def contours_for(data, extent, buffer_tag, interval=None):
    """DEM-derived contours for an extent, cached per site under data/."""
    site = data.site
    interval = interval or site.contour_interval_m
    d = site.data_dir
    lat0, lon0 = data.stations.iloc[0]["lat"], data.stations.iloc[0]["lon"]

    tile = terrain.download_dem_tile(lat0, lon0, d)
    clip = terrain.clip_reproject_dem(tile, extent, d / f"dem_clip_{buffer_tag}.tif",
                                      dst_crs=data.crs)
    smooth = terrain.refine_dem_for_contours(clip, d / f"dem_smooth_{buffer_tag}.tif")
    cont = terrain.generate_contours(smooth, d / f"contours_{buffer_tag}.geojson",
                                     crs=data.crs, interval=interval)
    # Every 5th contour is an index contour, drawn heavier and labelled --
    # standard topographic convention.
    cont["is_index"] = (cont["elev"] % 5 == 0)
    return cont
