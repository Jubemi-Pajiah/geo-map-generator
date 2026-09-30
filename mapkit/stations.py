"""Load survey stations, and work out where each label can go.

Handles three station-file shapes:

  * plain GPS-app export, blocks of Latitude/Longitude/Altitude/Accuracy plus a
    free-text description (the common case)
  * the same, but with '1.'/'2.' ordinals before each Latitude
  * a formatted .xlsx survey sheet
"""
import re

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString

from .env import CRS_WGS84

FT_TO_M = 0.3048

#: One block of the text export. The leading ordinal is optional -- some files
#: number the stations, some do not -- and so is the description line.
_BLOCK_RE = re.compile(
    r"(?im)^[ \t]*(?:\d+\.\s*)?Latitude:\s*(?P<lat>-?[\d.]+)[ \t]*\r?\n"
    r"[ \t]*Longitude:\s*(?P<lon>-?[\d.]+)[ \t]*\r?\n"
    r"[ \t]*Altitude:\s*(?P<elev>-?[\d.]+)\s*(?P<elev_unit>ft|m)?[ \t]*\r?\n"
    r"[ \t]*Accuracy:\s*(?P<accuracy>-?[\d.]+)\s*(?:ft|m)?[ \t]*\r?\n"
    r"(?P<description>[^\r\n]*)"
)


def _from_text(path):
    text = path.read_text(encoding="utf-8")
    records = []
    for m in _BLOCK_RE.finditer(text):
        d = m.groupdict()
        elev = float(d["elev"])
        records.append({
            "lat": float(d["lat"]),
            "lon": float(d["lon"]),
            # Unit is per-block: the files that omit it are all in feet, which
            # is what the GPS app exports.
            "elev_m": elev * (1.0 if d["elev_unit"] == "m" else FT_TO_M),
            "accuracy_ft": float(d["accuracy"]),
            "description": (d["description"] or "").strip(),
        })
    if not records:
        raise ValueError(f"No station blocks parsed from {path}")
    return pd.DataFrame(records)


def _from_excel(path):
    """Read a formatted survey sheet.

    Hand-made sheets usually carry a title row and a blank spacer above the
    real header, so the header row is found by looking for one that actually
    mentions latitude rather than assuming row 0 or 1.
    """
    raw = pd.read_excel(path, header=None)
    header_row = None
    for i in range(min(10, len(raw))):
        joined = " ".join(str(v).lower() for v in raw.iloc[i].tolist())
        if "lat" in joined and "long" in joined:
            header_row = i
            break
    if header_row is None:
        raise ValueError(f"Could not find a header row in {path}")

    df = pd.read_excel(path, header=header_row)
    df.columns = [str(c).strip().lower() for c in df.columns]

    def pick(*keys):
        for c in df.columns:
            if any(k in c for k in keys):
                return c
        return None

    lat_c, lon_c = pick("lat"), pick("lon", "long")
    elev_c = pick("elev", "alt")
    desc_c = pick("station", "name", "desc", "id", "bh")
    acc_c = pick("accur")
    if not (lat_c and lon_c and elev_c):
        raise ValueError(f"{path}: need latitude, longitude and elevation columns; "
                         f"found {list(df.columns)}")

    df = df[df[lat_c].notna()]
    elev = pd.to_numeric(df[elev_c], errors="coerce")
    # Elevation unit from the column heading, defaulting to metres: a sheet
    # that bothers to have headings normally says which.
    in_feet = any(tok in elev_c for tok in ("ft", "feet"))
    return pd.DataFrame({
        "lat": pd.to_numeric(df[lat_c], errors="coerce"),
        "lon": pd.to_numeric(df[lon_c], errors="coerce"),
        "elev_m": elev * (FT_TO_M if in_feet else 1.0),
        "accuracy_ft": (pd.to_numeric(df[acc_c], errors="coerce")
                        if acc_c else np.nan),
        "description": (df[desc_c].astype(str) if desc_c else ""),
    }).reset_index(drop=True)


def load(site, verbose=True):
    """Stations for `site` as a GeoDataFrame in EPSG:4326, in survey order."""
    path = site.stations_path
    df = (_from_excel(path) if path.suffix.lower() in (".xlsx", ".xls")
          else _from_text(path))

    # Drop repeated blocks. Some of these files carry the whole station list
    # twice over, because the export was pasted, then pasted again before a
    # footer was added. Parsing all of them would silently double every
    # station, duplicate each marker, and fold the A-A' trace back on itself --
    # a 3-station traverse drawn as 6 points going out and back.
    before = len(df)
    df = df.drop_duplicates(subset=["lat", "lon"], keep="first").reset_index(drop=True)
    if verbose and len(df) < before:
        print(f"  {path.name}: {before} station blocks parsed, "
              f"{before - len(df)} exact duplicates dropped -> {len(df)} stations")

    df["order"] = range(1, len(df) + 1)

    # Short name is the 'BH<n>' or 'BH-<letter>' token anywhere in the
    # description, matched case-insensitively, because these are hand-typed
    # and inconsistent ('Town BH1', 'BH2, north field', 'BH3 TOWN',
    # 'Example BH-A'). Numbered IDs normalise to 'BH1', lettered ones to
    # 'BH-A'. A block with no description at all falls back to its position
    # in the file.
    token = df["description"].astype(str).str.extract(
        r"(?i)\bBH[\s-]*(\d+|[A-Z])\b", expand=False).str.upper()
    df["station"] = [
        (f"BH{t}" if t.isdigit() else f"BH-{t}") if isinstance(t, str) else f"BH{n}"
        for t, n in zip(token, df["order"])]

    # Traverse order is the BOREHOLE ID wherever every station has one, not
    # the order blocks happen to sit in the file. These exports get pasted
    # together by hand and are not always in survey order (BH2 listed before
    # BH1 happens), which would put a needless kink in the A-A' trace and swap
    # which end is A. Letters order alphabetically: BH-A, BH-B, BH-C.
    if token.notna().all():
        df["order"] = [int(t) if t.isdigit() else ord(t) - ord("A") + 1 for t in token]
        df = df.sort_values("order").reset_index(drop=True)

    df["elev_ft"] = df["elev_m"] / FT_TO_M
    gdf = gpd.GeoDataFrame(
        df, geometry=[Point(xy) for xy in zip(df["lon"], df["lat"])], crs=CRS_WGS84)
    return gdf[["station", "description", "lat", "lon", "elev_ft", "elev_m",
                "accuracy_ft", "order", "geometry"]]


def cross_section_line(stations_utm):
    """The A-A' trace: a LineString through the stations in survey order."""
    return LineString([(g.x, g.y) for g in stations_utm.geometry])


def cumulative_distance(line_utm):
    """Distance of each vertex along the trace, for the section's x-axis."""
    dists = [0.0]
    coords = list(line_utm.coords)
    for i in range(1, len(coords)):
        dists.append(dists[-1] + LineString([coords[i - 1], coords[i]]).length)
    return dists


# --------------------------------------------------------------------------
# Automatic label placement
# --------------------------------------------------------------------------
# Where a station label may sit, as (dx, dy) in points with the matching
# alignment. Ordered by compass direction starting east, going anticlockwise.
_DIRECTIONS = [
    ((13, 0), "left", "center"),      # E
    ((11, 8), "left", "bottom"),      # NE
    ((0, 13), "center", "bottom"),    # N
    ((-11, 8), "right", "bottom"),    # NW
    ((-13, 0), "right", "center"),    # W
    ((-11, -8), "right", "top"),      # SW
    ((0, -12), "center", "top"),      # S
    ((11, -8), "left", "top"),        # SE
]


def _direction_index(angle_deg):
    return int(round((angle_deg % 360) / 45.0)) % 8


def _angular_gap(a, b):
    """Smallest angle between two bearings, in degrees (0-180)."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _slot_scores(xs, ys, i, blocked_bearings=()):
    """Score all 8 compass slots for station `i`: higher is more room.

    A slot is good when it points AWAY from the other stations. Each competing
    bearing is weighted by how far away that station is (`d_j / d_min`), so a
    neighbour 40 m away constrains the choice far more than one 300 m off --
    a label only collides with what is close enough to reach.

    "Away from the cluster centroid" was the obvious first rule and it is
    wrong for the most common survey layout: the MIDDLE borehole of
    a straight three-station traverse sits essentially ON the centroid, so its
    outward direction is numerically meaningless and lands wherever rounding
    error points -- straight into a neighbour. Scoring against the other
    stations instead gives that station the perpendicular, which is the answer
    a person would draw.
    """
    others = [(j, np.hypot(xs[j] - xs[i], ys[j] - ys[i]),
               np.degrees(np.arctan2(ys[j] - ys[i], xs[j] - xs[i])))
              for j in range(len(xs)) if j != i]
    dmin = min((d for _, d, _ in others), default=1.0) or 1.0

    scores = []
    for slot in range(8):
        angle = slot * 45.0
        gaps = [_angular_gap(angle, bearing) * (d / dmin) for _, d, bearing in others]
        gaps += [_angular_gap(angle, b) for b in blocked_bearings]
        scores.append(min(gaps) if gaps else 180.0)
    return scores


def auto_station_offsets(stations_utm):
    """Choose a label direction per station from the geometry itself.

    Replaces the per-site offset tables that were the most error-prone part of
    adding a site. Those tables encode one fact -- which way is "clear" for this
    particular arrangement of boreholes -- which is already in the coordinates.
    Hand-copying them between sites repeatedly put labels onto neighbouring
    markers (a triangle buried under its own two-line label; one label walking
    into the next station).

    Slots are assigned greedily, most-constrained station first, so the station
    with the least room picks before the ones with options.
    """
    xs = np.array([g.x for g in stations_utm.geometry], dtype=float)
    ys = np.array([g.y for g in stations_utm.geometry], dtype=float)
    n = len(xs)
    if n == 0:
        return {}

    all_scores = [_slot_scores(xs, ys, i) for i in range(n)]
    # Most constrained first: the station whose best slot is worst has the
    # least freedom, so let it choose before stations that can go anywhere.
    order = sorted(range(n), key=lambda i: max(all_scores[i]))

    taken, chosen = set(), {}
    for i in order:
        ranked = sorted(range(8), key=lambda s: all_scores[i][s], reverse=True)
        pick = next((s for s in ranked if s not in taken), ranked[0])
        taken.add(pick)
        chosen[i] = pick

    names = list(stations_utm["station"])
    return {names[i]: _DIRECTIONS[chosen[i]] for i in range(n)}


def auto_end_offsets(stations_utm, station_offsets=None, spread=True):
    """Where the 'A' and 'A\\'' end labels go.

    A and A' sit at the SAME coordinates as the first and last boreholes, so
    they always have something to dodge -- and what they must dodge differs by
    panel, which is why this takes `station_offsets`.

    On the map panel the whole traverse is a few percent of the frame with no
    station labels drawn, so the only thing A and A' can hit is each other:
    they are thrown outward along the traverse axis, in opposing directions
    (`spread=True`). In the detail inset the stations are far apart and each
    carries a two-line label, so each end label instead takes a compass point
    well away from its own station's label (`spread=False`).

    Both failure modes were real: sharing one table across panels left A and A'
    printed on top of each other as a single blob on one panel, and buried
    under the borehole labels on the other.
    """
    geoms = list(stations_utm.geometry)
    names = list(stations_utm["station"])
    first, last = geoms[0], geoms[-1]

    if spread:
        # Along the traverse, pointing outward from each end.
        angle = np.degrees(np.arctan2(last.y - first.y, last.x - first.x))
        return {
            "A": _DIRECTIONS[_direction_index(angle + 180)],
            "A_prime": _DIRECTIONS[_direction_index(angle)],
        }

    # Detail inset: score against the other stations exactly as their own
    # labels were, but additionally treat this station's OWN label direction as
    # blocked -- A sits at the same coordinates as BH1, so the one place it
    # must not go is wherever the "BH1 / <elevation>" label already is. Scoring rather than
    # simply taking the opposite slot matters on a straight traverse, where the
    # opposite of the end station's label points back down the line into its
    # neighbour.
    xs = np.array([g.x for g in geoms], dtype=float)
    ys = np.array([g.y for g in geoms], dtype=float)
    out, taken = {}, set()
    for key, idx in (("A", 0), ("A_prime", len(geoms) - 1)):
        blocked = []
        own = station_offsets.get(names[idx]) if station_offsets else None
        if own is not None:
            blocked.append(_DIRECTIONS.index(own) * 45.0)
        scores = _slot_scores(xs, ys, idx, blocked_bearings=blocked)
        ranked = sorted(range(8), key=lambda s: scores[s], reverse=True)
        pick = next((s for s in ranked if s not in taken), ranked[0])
        taken.add(pick)
        out[key] = _DIRECTIONS[pick]
    return out
