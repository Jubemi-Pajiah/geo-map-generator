"""Drawing map content, and deciding where labels can safely go.

The label-placement machinery here exists because matplotlib will happily draw
a label somewhere useless and tell you nothing about it. Three failure modes
recur, and each has a helper below:

  * a label placed from a long line's UNCLIPPED centroid lands off-frame, because
    OSM maps a highway as one very long way          -> clip_to_frame
  * a label anchored at its centre near the neatline is clipped mid-word,
    yet scores best because the frame edge is uncluttered -> pick_frac_clear_of
  * a label under a legend or inset is painted over and vanishes, whatever the
    call order                                        -> warn_on_overlaps
"""
import numpy as np
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.patheffects as patheffects
from shapely.geometry import box

from .style import (ROAD_STYLES, DEFAULT_ROAD_STYLE, MAJOR_ROAD_CLASSES,
                    ROAD_LEGEND_GROUPS, MAP_BG, RIVER_COLOR, PLACE_COLOR,
                    PLACE_TEXT, MARKET_COLOR, MARKET_TEXT)


# --------------------------------------------------------------------------
# Geometry / frame helpers
# --------------------------------------------------------------------------
def clip_to_frame(ax, segs):
    """Clip line geometries to the axes' current view, dropping what falls out.

    Always clip before placing a label on a line. OSM maps a major road as a
    single very long way -- an expressway can be ~12 km as one
    geometry -- so the whole line's centroid can sit far outside the visible
    frame even while a long stretch runs right through it.
    """
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    frame = box(xmin, ymin, xmax, ymax)
    segs = segs.copy()
    segs["geometry"] = segs.geometry.intersection(frame)
    return segs[~segs.geometry.is_empty]


def frac_position(ax, geom, frac):
    """Axes-fraction (fx, fy) of the point `frac` along `geom`."""
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    pt = geom.interpolate(frac, normalized=True)
    # Clamp: UTM grid convergence (meridians are not exactly vertical in a
    # projected CRS) can put a point conceptually "on the edge" at fx=-0.0005,
    # which then dodges a naive 0.0 <= fx bounds test.
    return (min(1.0, max(0.0, (pt.x - xmin) / (xmax - xmin))),
            min(1.0, max(0.0, (pt.y - ymin) / (ymax - ymin))))


def in_frame(ax, points_utm):
    """Rows whose geometry actually falls inside the axes limits."""
    if points_utm is None or points_utm.empty:
        return points_utm
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    return points_utm[points_utm.geometry.apply(
        lambda g: xmin <= g.x <= xmax and ymin <= g.y <= ymax)]


def label_halfwidth_frac(ax, text, fontsize, pad_frac=0.015):
    """Half the width `text` will really occupy, as a fraction of axes width.

    Measured through the renderer rather than estimated from character count,
    because the true width depends on font, weight and DPI. Callers use it to
    require that much clearance from the neatline.
    """
    fig = ax.figure
    try:
        renderer = fig.canvas.get_renderer()
        probe = ax.text(0, 0, text, fontsize=fontsize, fontweight="bold",
                        transform=ax.transAxes)
        bb = probe.get_window_extent(renderer=renderer)
        probe.remove()
        ax_w = ax.get_window_extent().width
        if ax_w > 0:
            return 0.5 * bb.width / ax_w + pad_frac
    except Exception:
        pass
    ax_w_pts = ax.get_window_extent().width * 72.0 / fig.dpi
    if ax_w_pts <= 0:
        return pad_frac
    return 0.5 * (0.58 * fontsize * len(text)) / ax_w_pts + pad_frac


def pick_frac_clear_of(ax, geom, avoid, candidates=None, min_edge=0.0):
    """Where along `geom` (already frame-clipped) to put its label.

    Scores each candidate by its axes-fraction margin from the nearest `avoid`
    box -- positive means outside it -- and takes the largest. Falling back to
    "furthest from trouble" means a line that cannot avoid the furniture still
    gets labelled in the least-bad spot rather than not at all.

    Fitting inside the neatline is a HARD constraint applied as a filter, not
    another term in that score. A long name is anchored at its CENTRE, so a
    position can clear every furniture box -- and therefore score best -- while
    still running the name off the frame to be clipped mid-word. That is
    exactly how a long highway name once rendered as "...Coastal Hig":
    sitting out near the empty edge was what made it win. Pass the label's own
    measured half-width as `min_edge`.
    """
    if candidates is None:
        candidates = [i / 20 for i in range(2, 19)]

    scored = []
    for f in candidates:
        fx, fy = frac_position(ax, geom, f)
        margin = (min(max(x0 - fx, fx - x1, y0 - fy, fy - y1)
                      for x0, y0, x1, y1 in avoid) if avoid else 1.0)
        # A road label is ROTATED to follow its road, so how much room it needs
        # in x versus y depends on the local bearing. Checking only the
        # horizontal is right for an east-west road and useless for a
        # north-south one: an expressway running near-vertically
        # was clipped against the TOP neatline while passing a width-only test
        # comfortably. Resolve the half-width along both axes instead.
        ang = np.radians(_local_bearing(geom, f))
        need_x, need_y = abs(np.cos(ang)), abs(np.sin(ang))
        scored.append((f, fx, fy, margin, need_x, need_y))

    if min_edge > 0:
        fits = [s for s in scored
                if min(s[1], 1 - s[1]) >= min_edge * s[4]
                and min(s[2], 1 - s[2]) >= min_edge * s[5]]
        if fits:
            scored = fits
    return max(scored, key=lambda s: s[3])[0]


def _local_bearing(geom, frac):
    """Bearing of `geom` at `frac` along it, in degrees -- the angle the label
    will be rotated to."""
    if geom.geom_type == "MultiLineString":
        geom = max(geom.geoms, key=lambda g: g.length)
    coords = list(geom.coords)
    if len(coords) < 2:
        return 0.0
    i = max(1, min(int(len(coords) * frac), len(coords) - 2))
    p0, p1 = coords[i - 1], coords[i + 1]
    return np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0]))


def inboard_offset(fx, fy, pad_pts=34, edge=0.10):
    """Nudge a label off whichever frame edge it sits on, in POINTS.

    A road running ALONG the border has no position anywhere on it where a
    centred label fits, so choosing a better spot along the line cannot help --
    the label has to move sideways off the line instead. (Where the road merely
    crosses the frame, pick_frac_clear_of's min_edge filter handles it first.)
    Offsets are in screen points, so they do not distort with the projection.
    """
    dx = pad_pts if fx < edge else (-pad_pts if fx > 1 - edge else 0)
    dy = pad_pts * 0.5 if fy < edge else (-pad_pts * 0.5 if fy > 1 - edge else 0)
    return (dx, dy)


def edge_aware_offset(fx, fy, dx=6, dy=6):
    """Which side of a marker its label should sit on. A marker can sit well
    inside the frame while its LABEL still runs off the edge, so near an edge
    the label is flipped inboard. Returns (xytext, ha, va)."""
    ha = "right" if fx > 0.62 else "left"
    va = "top" if fy > 0.90 else "bottom"
    return ((-dx if ha == "right" else dx), (-dy if va == "top" else dy)), ha, va


def avoid_boxes_for_points(ax, points_utm, halfwidth=0.10, halfheight=0.07):
    """Keep-out boxes around plotted points, so a road label can be steered off
    them. The furniture table alone is not enough on a panel whose real
    obstacles are the boreholes and their labels. Boxes are deliberately
    asymmetric -- a station label is wider than it is tall."""
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    boxes = []
    for _, row in points_utm.iterrows():
        fx = (row.geometry.x - xmin) / (xmax - xmin)
        fy = (row.geometry.y - ymin) / (ymax - ymin)
        boxes.append((fx - halfwidth, fy - halfheight, fx + halfwidth, fy + halfheight))
    return boxes


def warn_on_overlaps(ax, points_utm, footprints, what="label"):
    """Report any plotted point whose label lands inside one of `footprints` --
    axes-fraction boxes for things drawn ON TOP of the map. Those always paint
    over map content regardless of call order, so a label underneath one is
    silently swallowed. Prints rather than raises: it is a review aid, and the
    fix (move the box, or move the label) is a judgement call."""
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    hits = []
    for _, row in points_utm.iterrows():
        fx = min(1.0, max(0.0, (row.geometry.x - xmin) / (xmax - xmin)))
        fy = min(1.0, max(0.0, (row.geometry.y - ymin) / (ymax - ymin)))
        for name, (x0, y0, x1, y1) in footprints.items():
            if x0 <= fx <= x1 and y0 <= fy <= y1:
                hits.append(f"  !! {what} '{row.get('name', '?')}' "
                            f"(fx={fx:.3f}, fy={fy:.3f}) falls under the {name}")
    print("\n".join(hits) if hits
          else f"  overlap check: no {what} hidden behind map furniture")
    return hits


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------
def plot_roads(ax, roads_utm):
    """Roads styled by OSM class, major ones with a light centreline."""
    for _, row in roads_utm.iterrows():
        style = ROAD_STYLES.get(row["highway"], DEFAULT_ROAD_STYLE)
        xs, ys = row.geometry.xy
        ax.plot(xs, ys, solid_capstyle="round", **style)
        if row["highway"] in MAJOR_ROAD_CLASSES:
            ax.plot(xs, ys, color="#e8dfc4", lw=max(style["lw"] * 0.35, 0.5),
                    zorder=style["zorder"] + 0.05, solid_capstyle="round")


def road_legend_handles(roads_utm, ax=None, named=None):
    """Legend rows for the road classes ACTUALLY drawn in this frame.

    Built from the data rather than declared per site. A hand-written legend
    drifts out of step with the map the moment the extent changes -- listing
    keys for symbols that never appear (which reads as "the map failed to draw
    them") or omitting ones that do.
    """
    if roads_utm is None or roads_utm.empty:
        return []
    # Restrict to what the frame really shows where we can. `roads_utm` is
    # fetched for the widest map's bbox, so on a narrower panel it contains
    # classes that never render there -- and a key for a symbol that never
    # appears reads as "the map failed to draw it".
    visible = clip_to_frame(ax, roads_utm) if ax is not None else roads_utm
    present = set(visible["highway"].dropna().unique())

    handles = []
    for classes, label in ROAD_LEGEND_GROUPS:
        hit = [c for c in classes if c in present]
        if not hit:
            continue
        style = ROAD_STYLES.get(hit[0], DEFAULT_ROAD_STYLE)
        text = label
        if named and hit[0] in named:
            text = f"{label} - {named[hit[0]]}"
        handles.append(mlines.Line2D(
            [], [], color=style["color"], lw=min(style["lw"], 2.6),
            ls=style.get("ls", "-"), label=f"{text} (OSM)"))
    return handles


def label_along_line(ax, geom, text, fontsize, color, stroke, zorder,
                     frac=0.5, offset_pts=(0, 0)):
    """Place `text` along a line, rotated to follow the local bearing (flipped
    to stay right-way-up). Assumes `geom` is ALREADY clipped to the frame."""
    if geom.geom_type == "MultiLineString":
        geom = max(geom.geoms, key=lambda g: g.length)
    mid = geom.interpolate(frac, normalized=True)
    coords = list(geom.coords)
    i = max(1, min(int(len(coords) * frac), len(coords) - 2))
    p0, p1 = coords[i - 1], coords[i + 1]
    angle = np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0]))
    if angle > 90:
        angle -= 180
    elif angle < -90:
        angle += 180
    ax.annotate(text, (mid.x, mid.y), xytext=offset_pts,
                textcoords="offset points", rotation=angle,
                rotation_mode="anchor", fontsize=fontsize, fontweight="bold",
                ha="center", va="center", color=color, zorder=zorder,
                clip_on=True,
                path_effects=[patheffects.withStroke(linewidth=3.2, foreground=stroke)])


def plot_named_road(ax, roads_utm, name, avoid=None, fontsize=10.0,
                    color="#2a2010", extra_avoid=()):
    """Label ONE named road, chosen by exact OSM `name` tag.

    Deliberately one name per road, not a label on every way: a town frame here
    carries ~270 residential streets and labelling them buries the map. Returns
    an (x0, y0, x1, y1) axes-fraction keep-out box for the label just drawn, so
    a second road label can be steered clear of the first, or None if nothing
    was drawn.
    """
    if roads_utm is None or roads_utm.empty or not name:
        return None
    segs = roads_utm[roads_utm["name"] == name]
    if segs.empty:
        return None
    segs = clip_to_frame(ax, segs)
    if segs.empty:
        return None

    segs = segs.copy()
    segs["length"] = segs.geometry.length
    geom = segs.loc[segs["length"].idxmax()].geometry
    if geom.geom_type == "MultiLineString":
        geom = max(geom.geoms, key=lambda g: g.length)

    half_w = label_halfwidth_frac(ax, name, fontsize)
    avoid_all = list(avoid or []) + list(extra_avoid)
    frac = pick_frac_clear_of(ax, geom, avoid_all, min_edge=half_w)
    fx, fy = frac_position(ax, geom, frac)
    ox, oy = inboard_offset(fx, fy)
    label_along_line(ax, geom, name, fontsize=fontsize, color=color,
                     stroke=MAP_BG, zorder=6.6, frac=frac,
                     offset_pts=(ox, oy + 8))
    return (fx - half_w, fy - 0.045, fx + half_w, fy + 0.045)


def plot_waterways(ax, rivers_utm, name=None, avoid=None):
    """Draw OSM waterways and label the named one. Returns whether any drew."""
    if rivers_utm is None or rivers_utm.empty:
        return False
    segs = clip_to_frame(ax, rivers_utm)
    if segs.empty:
        return False
    for _, row in segs.iterrows():
        geoms = (row.geometry.geoms if row.geometry.geom_type == "MultiLineString"
                 else [row.geometry])
        for g in geoms:
            xs, ys = g.xy
            ax.plot(xs, ys, color=RIVER_COLOR, lw=2.0, solid_capstyle="round",
                    zorder=4.5)
    if not name:
        return True
    named = segs[segs["name"] == name]
    if not named.empty:
        named = named.copy()
        named["length"] = named.geometry.length
        geom = named.loc[named["length"].idxmax()].geometry
        if geom.geom_type == "MultiLineString":
            geom = max(geom.geoms, key=lambda g: g.length)
        frac = pick_frac_clear_of(ax, geom, avoid or [],
                                  min_edge=label_halfwidth_frac(ax, name, 10.5))
        ox, oy = inboard_offset(*frac_position(ax, geom, frac))
        label_along_line(ax, geom, name, fontsize=10.5, color=RIVER_COLOR,
                         stroke=MAP_BG, zorder=6.6, frac=frac,
                         offset_pts=(ox, oy + 9))
    return True


def plot_points(ax, points_utm, marker, facecolor, textcolor, fontsize,
                size=42, dy=0):
    """Named point features (localities, markets), clipped to the frame and
    labelled edge-aware. Returns whether any drew."""
    if points_utm is None or points_utm.empty:
        return False
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    drawn = False
    for _, row in points_utm.iterrows():
        x, y = row.geometry.x, row.geometry.y
        if not (xmin <= x <= xmax and ymin <= y <= ymax):
            continue
        drawn = True
        ax.scatter([x], [y], marker=marker, s=size, facecolor=facecolor,
                   edgecolor="white", linewidth=0.8, zorder=6.8)
        xytext, ha, va = edge_aware_offset((x - xmin) / (xmax - xmin),
                                           (y - ymin) / (ymax - ymin))
        ax.annotate(row["name"], (x, y), xytext=(xytext[0], xytext[1] + dy),
                    textcoords="offset points", ha=ha, va=va, fontsize=fontsize,
                    fontweight="bold", fontstyle="italic", color=textcolor,
                    zorder=6.9, clip_on=True,
                    path_effects=[patheffects.withStroke(linewidth=2.8,
                                                         foreground=MAP_BG)])
    return drawn


def plot_places(ax, places_utm, fontsize=13):
    return plot_points(ax, places_utm, "o", PLACE_COLOR, PLACE_TEXT, fontsize)


def plot_markets(ax, markets_utm, fontsize=11):
    return plot_points(ax, markets_utm, "s", MARKET_COLOR, MARKET_TEXT,
                       fontsize, size=40, dy=-10)


#: Candidate corners for a floating inset, and the axes-fraction footprint each
#: occupies at the sizes add_content_inset uses.
_CORNER_BOXES = {
    "upper left":  (0.00, 0.66, 0.36, 1.00),
    "upper right": (0.64, 0.66, 1.00, 1.00),
    "lower left":  (0.00, 0.00, 0.36, 0.34),
    "lower right": (0.64, 0.00, 1.00, 0.34),
}


def choose_inset_corner(ax, content_points, reserved=(), stations_utm=None):
    """Pick the emptiest corner for a floating inset.

    An inset always paints over the host axes' content, whatever the call
    order, so a fixed corner silently eats whatever happens to sit there -- at
    one site a locality name ended up half-hidden under a hard-coded "upper
    left" inset, readable only as "...vbuomoma".

    Corners are scored by how much labelled content they would cover, and the
    borehole cluster is treated as content too, since covering the very
    features the inset magnifies is the one unambiguous mistake. `reserved` is
    for furniture already committed (legend, north arrow).
    """
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()

    pts = []
    for gdf in content_points:
        if gdf is None or len(gdf) == 0:
            continue
        for geom in gdf.geometry:
            pts.append(((geom.x - xmin) / (xmax - xmin),
                        (geom.y - ymin) / (ymax - ymin)))
    if stations_utm is not None and len(stations_utm):
        cx = float(np.mean([g.x for g in stations_utm.geometry]))
        cy = float(np.mean([g.y for g in stations_utm.geometry]))
        # weighted heavily: never cover the stations themselves
        pts += [((cx - xmin) / (xmax - xmin), (cy - ymin) / (ymax - ymin))] * 5

    best, best_cost = "upper left", None
    for corner, (x0, y0, x1, y1) in _CORNER_BOXES.items():
        cost = sum(1 for fx, fy in pts if x0 <= fx <= x1 and y0 <= fy <= y1)
        cost += sum(3 for rx0, ry0, rx1, ry1 in reserved
                    if not (x1 < rx0 or x0 > rx1 or y1 < ry0 or y0 > ry1))
        if best_cost is None or cost < best_cost:
            best, best_cost = corner, cost
    return best


def longest_named_road(ax, roads_utm):
    """The name of the longest named road actually crossing this frame.

    Used when a site does not declare one. The single most useful label on a
    geologic map is the road a reader already knows, and which road that is is
    a property of the frame, not something worth writing down per site --
    especially since it changes if the extent does.
    """
    if roads_utm is None or roads_utm.empty:
        return None
    named = roads_utm[roads_utm["name"].notna()]
    if named.empty:
        return None
    named = clip_to_frame(ax, named)
    if named.empty:
        return None
    named = named.copy()
    named["_len"] = named.geometry.length
    return named.groupby("name")["_len"].sum().idxmax()


def draw_section_ends(ax, xs, ys, offsets, fontsize, stroke_lw, zorder):
    """Draw the 'A' and 'A\\'' end labels on the cross-section trace.

    A and A' sit at the SAME coordinates as the first and last boreholes, so
    they always have something to dodge -- and what they must dodge differs by
    panel, which is why `offsets` is passed in rather than fixed. See
    mapkit.stations.auto_end_offsets.
    """
    from .style import TRACE_COLOR
    ends = [("A", (xs[0], ys[0]), offsets["A"]),
            ("A'", (xs[-1], ys[-1]), offsets["A_prime"])]
    for lbl, (x, y), (xytext, ha, va) in ends:
        ax.annotate(lbl, (x, y), xytext=xytext, textcoords="offset points",
                    fontsize=fontsize, fontweight="bold", color=TRACE_COLOR,
                    ha=ha, va=va, zorder=zorder,
                    path_effects=[patheffects.withStroke(linewidth=stroke_lw,
                                                         foreground="white")])
