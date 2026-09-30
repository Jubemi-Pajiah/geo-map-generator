"""Reusable cartographic furniture: scale bar, north arrow, graticule, corner
ticks, neatline, locator inset and content inset. Host axes are assumed to be
in a projected, metric CRS.

Which metric CRS is a PARAMETER, not a module constant. The reference version
built its coordinate transformers once at import time from a hard-coded UTM
zone, which is fine for one site per process and silently wrong the moment a
single run renders several sites in different zones -- as `make_maps.py --all`
does. Transformers are therefore built per CRS and cached.
"""
from functools import lru_cache

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines

from .env import CRS_WGS84, CRS_WEBMERC


@lru_cache(maxsize=None)
def _transformers(utm_crs):
    """(to WGS84, from WGS84) for a projected CRS, built once per CRS."""
    import pyproj
    return (pyproj.Transformer.from_crs(utm_crs, CRS_WGS84, always_xy=True),
            pyproj.Transformer.from_crs(CRS_WGS84, utm_crs, always_xy=True))


def _nice_round(value):
    """Round down to a visually clean number (1/2/5 * 10^n)."""
    if value <= 0:
        return 1
    exp = np.floor(np.log10(value))
    base = value / (10 ** exp)
    if base >= 5:
        nice = 5
    elif base >= 2:
        nice = 2
    else:
        nice = 1
    return nice * (10 ** exp)


def dd_to_dm(value, is_lat):
    """Decimal degrees -> 'D°MM.M'N/S/E/W' string, like a traditional topo sheet."""
    hemi = ("N" if value >= 0 else "S") if is_lat else ("E" if value >= 0 else "W")
    value = abs(value)
    deg = int(value)
    minutes = (value - deg) * 60
    return f"{deg}°{minutes:04.1f}'{hemi}"


def _backing_box(ax, x0, y0, x1, y1, pad_frac=0.15):
    """Solid white rounded box behind an element so it stays legible over busy
    basemap imagery, regardless of what's underneath."""
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    pad_x = (x1 - x0) * pad_frac + (xmax - xmin) * 0.006
    pad_y = (y1 - y0) * pad_frac + (ymax - ymin) * 0.006
    rect = mpatches.FancyBboxPatch(
        (x0 - pad_x, y0 - pad_y), (x1 - x0) + 2 * pad_x, (y1 - y0) + 2 * pad_y,
        boxstyle="round,pad=0,rounding_size=0", facecolor="white",
        # fully opaque: at 0.92 a dense contour set visibly bleeds through the
        # scale-bar / north-arrow panel and muddies their labels
        edgecolor="black", linewidth=0.7, alpha=1.0, zorder=9.5,
    )
    ax.add_patch(rect)
    return rect


def add_scalebar(ax, location=(0.04, 0.08), length_frac=0.28, height_m=None):
    """Draw an alternating black/white scale bar with metric ticks, based on
    the axes' real (UTM32N, meters) extent -- so it stays accurate at any
    zoom -- on a solid white backing panel so it reads over busy imagery."""
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    width_m = xmax - xmin
    target = width_m * length_frac
    bar_len = _nice_round(target)
    n_segments = 4
    seg_len = bar_len / n_segments

    if height_m is None:
        height_m = (ymax - ymin) * 0.012

    x0 = xmin + location[0] * width_m
    y0 = ymin + location[1] * (ymax - ymin)

    _backing_box(ax, x0, y0 - height_m * 3.6, x0 + bar_len, y0 + height_m * 3.0, pad_frac=0.25)

    for i in range(n_segments):
        color = "black" if i % 2 == 0 else "white"
        rect = mpatches.Rectangle(
            (x0 + i * seg_len, y0), seg_len, height_m,
            facecolor=color, edgecolor="black", linewidth=0.8, zorder=10,
        )
        ax.add_patch(rect)

    label_unit = "m" if bar_len < 1000 else "km"
    label_scale = 1 if bar_len < 1000 else 1000
    for i in range(n_segments + 1):
        val = i * seg_len / label_scale
        txt = f"{val:g}" if i > 0 else "0"
        ax.text(x0 + i * seg_len, y0 + height_m * 2.2, txt,
                 ha="center", va="bottom", fontsize=6.5, zorder=10)
    ax.text(x0 + bar_len / 2, y0 - height_m * 3.0, f"Scale (approx.) in {label_unit}",
             ha="center", va="top", fontsize=6.5, zorder=10, clip_on=False)


def add_scalebar_outside(fig, host_ax, width_frac=0.30, height_frac=0.028,
                          margin_frac=0.012, length_frac_of_panel=0.85, corner="lower left"):
    """Scale bar drawn in its own small axes positioned just outside host_ax's
    border (in the figure's white margin), rather than on top of map content.
    Preserves the host map's true meters-per-inch scale: the new axes' data
    width is set to the same real-world fraction of host_ax's data width as
    its physical width is a fraction of host_ax's physical width."""
    fig.canvas.draw()
    pos = host_ax.get_position()
    xmin, xmax = host_ax.get_xlim()
    width_m = xmax - xmin

    w = width_frac * pos.width
    h = height_frac * pos.height
    panel_data_width_m = width_m * width_frac

    if corner == "lower left":
        x0 = pos.x0
        y0 = pos.y0 - h - margin_frac * pos.height
    elif corner == "lower right":
        x0 = pos.x1 - w
        y0 = pos.y0 - h - margin_frac * pos.height
    else:
        x0 = pos.x0
        y0 = pos.y0 - h - margin_frac * pos.height

    bar_ax = fig.add_axes((x0, y0, w, h))
    bar_ax.axis("off")

    bar_len = _nice_round(panel_data_width_m * length_frac_of_panel)
    n_segments = 4
    seg_len = bar_len / n_segments
    bar_ax.set_xlim(0, panel_data_width_m)
    bar_ax.set_ylim(0, 1)

    for i in range(n_segments):
        color = "black" if i % 2 == 0 else "white"
        bar_ax.add_patch(mpatches.Rectangle(
            (i * seg_len, 0.38), seg_len, 0.30,
            facecolor=color, edgecolor="black", linewidth=0.8, clip_on=False))

    label_unit = "m" if bar_len < 1000 else "km"
    label_scale = 1 if bar_len < 1000 else 1000
    for i in range(n_segments + 1):
        val = i * seg_len / label_scale
        txt = f"{val:g}" if i > 0 else "0"
        bar_ax.text(i * seg_len, 0.78, txt, ha="center", va="bottom",
                    fontsize=6.5, clip_on=False)
    bar_ax.text(bar_len / 2, 0.02, f"Scale (approx.) in {label_unit}",
                ha="center", va="bottom", fontsize=6.5, clip_on=False)
    return bar_ax


def add_north_arrow(ax, location=(0.94, 0.90), size_frac=0.06):
    """Simple triangular north arrow with an 'N' label on a white backing panel."""
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    w, h = xmax - xmin, ymax - ymin
    cx = xmin + location[0] * w
    cy = ymin + location[1] * h
    size = size_frac * h

    _backing_box(ax, cx - size * 0.55, cy - size * 0.5, cx + size * 0.55, cy + size * 1.55,
                 pad_frac=0.18)

    ax.annotate(
        "", xy=(cx, cy + size), xytext=(cx, cy - size * 0.4),
        arrowprops=dict(arrowstyle="-|>", color="black", lw=1.8, mutation_scale=20),
        zorder=11,
    )
    ax.text(cx, cy + size * 1.25, "N", ha="center", va="bottom",
             fontsize=11, fontweight="bold", zorder=11)


def add_fancy_north_arrow_outside(ax, extent_utm, frac_from_top=0.10, size_frac=0.09,
                                   side="right", gap_frac=0.05):
    """A more decorative compass-style north arrow (shaded kite spike +
    shorter tail, classic drafting-compass look), drawn entirely outside the
    map's neatline in the figure's white margin -- consistent with the
    coordinate ticks and scale bar also living outside the frame."""
    minx, miny, maxx, maxy = extent_utm
    w, h = maxx - minx, maxy - miny
    size = size_frac * h
    gap = gap_frac * w

    if side == "right":
        cx = maxx + gap + size * 0.5
    else:
        cx = minx - gap - size * 0.5
    cy = maxy - frac_from_top * h

    spike_w = size * 0.62
    spike_h = size
    tail_h = size * 0.38

    left_spike = mpatches.Polygon(
        [(cx, cy + spike_h), (cx - spike_w / 2, cy), (cx, cy)],
        closed=True, facecolor="white", edgecolor="black", linewidth=1.1, zorder=12, clip_on=False)
    right_spike = mpatches.Polygon(
        [(cx, cy + spike_h), (cx + spike_w / 2, cy), (cx, cy)],
        closed=True, facecolor="black", edgecolor="black", linewidth=1.1, zorder=12, clip_on=False)
    left_tail = mpatches.Polygon(
        [(cx, cy - tail_h), (cx - spike_w * 0.55 / 2, cy), (cx, cy)],
        closed=True, facecolor="black", edgecolor="black", linewidth=1.0, zorder=12, clip_on=False)
    right_tail = mpatches.Polygon(
        [(cx, cy - tail_h), (cx + spike_w * 0.55 / 2, cy), (cx, cy)],
        closed=True, facecolor="white", edgecolor="black", linewidth=1.0, zorder=12, clip_on=False)
    for p in (left_spike, right_spike, left_tail, right_tail):
        ax.add_patch(p)

    hub = mpatches.Circle((cx, cy), radius=spike_w * 0.09, facecolor="white",
                          edgecolor="black", linewidth=1.0, zorder=13, clip_on=False)
    ax.add_patch(hub)

    ax.text(cx, cy + spike_h * 1.18, "N", ha="center", va="bottom",
             fontsize=13, fontweight="bold", zorder=13, clip_on=False)


def add_fancy_north_arrow(ax, location=(0.90, 0.86), size_frac=0.075):
    """Same decorative compass-spike design as add_fancy_north_arrow_outside,
    but positioned inside the axes (fractional position, like the original
    simple add_north_arrow), with a white backing panel so it reads clearly
    over map content."""
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    w, h = xmax - xmin, ymax - ymin
    cx = xmin + location[0] * w
    cy = ymin + location[1] * h
    size = size_frac * h

    spike_w = size * 0.62
    spike_h = size
    tail_h = size * 0.38

    _backing_box(ax, cx - spike_w * 0.7, cy - tail_h * 1.3, cx + spike_w * 0.7,
                 cy + spike_h * 1.35, pad_frac=0.12)

    left_spike = mpatches.Polygon(
        [(cx, cy + spike_h), (cx - spike_w / 2, cy), (cx, cy)],
        closed=True, facecolor="white", edgecolor="black", linewidth=1.1, zorder=12)
    right_spike = mpatches.Polygon(
        [(cx, cy + spike_h), (cx + spike_w / 2, cy), (cx, cy)],
        closed=True, facecolor="black", edgecolor="black", linewidth=1.1, zorder=12)
    left_tail = mpatches.Polygon(
        [(cx, cy - tail_h), (cx - spike_w * 0.55 / 2, cy), (cx, cy)],
        closed=True, facecolor="black", edgecolor="black", linewidth=1.0, zorder=12)
    right_tail = mpatches.Polygon(
        [(cx, cy - tail_h), (cx + spike_w * 0.55 / 2, cy), (cx, cy)],
        closed=True, facecolor="white", edgecolor="black", linewidth=1.0, zorder=12)
    for p in (left_spike, right_spike, left_tail, right_tail):
        ax.add_patch(p)

    hub = mpatches.Circle((cx, cy), radius=spike_w * 0.09, facecolor="white",
                          edgecolor="black", linewidth=1.0, zorder=13)
    ax.add_patch(hub)

    ax.text(cx, cy + spike_h * 1.18, "N", ha="center", va="bottom",
             fontsize=13, fontweight="bold", zorder=13)


def add_graticule(ax, extent_utm, utm_crs, step_deg=None, label=True,
                  suppress_region=None):
    """Draw faint lat/lon graticule lines + edge tick labels inside a UTM32N
    axes. Labels sit just inside the frame so they never spill into the title.
    suppress_region, if given, is (x0, y0, x1, y1) in axes-fraction (0-1)
    coordinates -- labels falling inside it are skipped (e.g. so they don't
    render underneath a locator inset added on top as a separate axes). A
    LIST of such tuples is also accepted: a map typically has more than one
    thing floating over the frame (locator inset AND scale-bar panel AND
    north-arrow panel), and every one of them can swallow a tick label."""
    _TO_WGS84, _FROM_WGS84 = _transformers(utm_crs)
    minx, miny, maxx, maxy = extent_utm
    corners_wgs = [_TO_WGS84.transform(x, y) for x, y in
                   [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]]
    lons = [c[0] for c in corners_wgs]
    lats = [c[1] for c in corners_wgs]
    lon_min, lon_max = min(lons), max(lons)
    lat_min, lat_max = min(lats), max(lats)

    if step_deg is None:
        span = max(lon_max - lon_min, lat_max - lat_min)
        for candidate in [0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05]:
            if span / candidate <= 6:
                step_deg = candidate
                break
        else:
            step_deg = 0.05

    def round_to_step(v, step, up):
        return (np.ceil(v / step) if up else np.floor(v / step)) * step

    lon_ticks = np.arange(round_to_step(lon_min, step_deg, True),
                           round_to_step(lon_max, step_deg, False) + step_deg / 2, step_deg)
    lat_ticks = np.arange(round_to_step(lat_min, step_deg, True),
                           round_to_step(lat_max, step_deg, False) + step_deg / 2, step_deg)

    label_inset = (maxy - miny) * 0.012

    if suppress_region is None:
        regions = []
    elif isinstance(suppress_region[0], (int, float)):
        regions = [suppress_region]          # a single (x0, y0, x1, y1) tuple
    else:
        regions = list(suppress_region)      # a list of them

    def _suppressed(x, y):
        # clamp: labels near the left/top edge transform to a slightly negative
        # fraction due to UTM grid convergence (meridians aren't exactly
        # vertical), which would otherwise dodge an sx0=0.0 / sy... boundary
        fx = min(1.0, max(0.0, (x - minx) / (maxx - minx)))
        fy = min(1.0, max(0.0, (y - miny) / (maxy - miny)))
        return any(sx0 <= fx <= sx1 and sy0 <= fy <= sy1
                   for sx0, sy0, sx1, sy1 in regions)

    for lon in lon_ticks:
        pts = [_FROM_WGS84.transform(lon, lat) for lat in np.linspace(lat_min, lat_max, 20)]
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color="white", lw=0.6, ls=(0, (1, 3)), alpha=0.8, zorder=5)
        if label:
            x_top, _ = _FROM_WGS84.transform(lon, lat_max)
            if not _suppressed(x_top, maxy):
                ax.text(x_top, maxy - label_inset, f"{lon:.4f}°E", rotation=90, ha="right",
                         va="top", fontsize=6, color="black", zorder=11, clip_on=True,
                         bbox=dict(boxstyle="square,pad=0.1", facecolor="white",
                                   edgecolor="none", alpha=0.75))

    for lat in lat_ticks:
        pts = [_FROM_WGS84.transform(lon, lat) for lon in np.linspace(lon_min, lon_max, 20)]
        xs, ys = zip(*pts)
        ax.plot(xs, ys, color="white", lw=0.6, ls=(0, (1, 3)), alpha=0.8, zorder=5)
        if label:
            x_left, y_left = _FROM_WGS84.transform(lon_min, lat)
            if _suppressed(x_left, y_left):
                continue
            ax.text(minx + label_inset, y_left, f"{lat:.4f}°N", ha="left", va="center",
                     fontsize=6, color="black", zorder=11, clip_on=True,
                     bbox=dict(boxstyle="square,pad=0.1", facecolor="white",
                               edgecolor="none", alpha=0.75))

    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)


def add_corner_ticks(ax, extent_utm, utm_crs, step_deg=None, tick_frac=0.014):
    """Traditional topo-sheet style: short DMS-labeled tick marks at the map
    border only (no interior grid lines), plus a bold neatline. Matches the
    look of classic hand-drafted local base maps."""
    _TO_WGS84, _FROM_WGS84 = _transformers(utm_crs)
    minx, miny, maxx, maxy = extent_utm
    corners_wgs = [_TO_WGS84.transform(x, y) for x, y in
                   [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]]
    lons = [c[0] for c in corners_wgs]
    lats = [c[1] for c in corners_wgs]
    lon_min, lon_max = min(lons), max(lons)
    lat_min, lat_max = min(lats), max(lats)

    if step_deg is None:
        span = max(lon_max - lon_min, lat_max - lat_min)
        for candidate in [0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05]:
            if span / candidate <= 6:
                step_deg = candidate
                break
        else:
            step_deg = 0.05

    def round_to_step(v, step, up):
        return (np.ceil(v / step) if up else np.floor(v / step)) * step

    lon_ticks = np.arange(round_to_step(lon_min, step_deg, True),
                           round_to_step(lon_max, step_deg, False) + step_deg / 2, step_deg)
    lat_ticks = np.arange(round_to_step(lat_min, step_deg, True),
                           round_to_step(lat_max, step_deg, False) + step_deg / 2, step_deg)

    tick_len_x = (maxx - minx) * tick_frac
    tick_len_y = (maxy - miny) * tick_frac

    # Ticks straddle the neatline (short mark inside + short mark outside);
    # labels sit clear of the border in the figure's white margin so they
    # never touch/overlap the map frame or its contents.
    label_gap = 2.6

    for lon in lon_ticks:
        x, _ = _FROM_WGS84.transform(lon, lat_max)
        if not (minx <= x <= maxx):
            continue
        ax.plot([x, x], [maxy - tick_len_y, maxy + tick_len_y], color="black",
                 lw=1.2, zorder=11, clip_on=False)
        ax.plot([x, x], [miny - tick_len_y, miny + tick_len_y], color="black",
                 lw=1.2, zorder=11, clip_on=False)
        ax.text(x, maxy + tick_len_y * label_gap, dd_to_dm(lon, is_lat=False), rotation=90,
                 ha="left", va="bottom", fontsize=6.2, fontweight="bold", zorder=11, clip_on=False)

    for lat in lat_ticks:
        _, y = _FROM_WGS84.transform(lon_min, lat)
        if not (miny <= y <= maxy):
            continue
        ax.plot([minx - tick_len_x, minx + tick_len_x], [y, y], color="black",
                 lw=1.2, zorder=11, clip_on=False)
        ax.plot([maxx - tick_len_x, maxx + tick_len_x], [y, y], color="black",
                 lw=1.2, zorder=11, clip_on=False)
        ax.text(minx - tick_len_x * label_gap, y, dd_to_dm(lat, is_lat=True),
                 ha="right", va="center", fontsize=6.2, fontweight="bold", zorder=11, clip_on=False)

    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)


def add_neatline(ax, linewidth=1.4):
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(linewidth)
        spine.set_edgecolor("black")
    ax.set_xticks([])
    ax.set_yticks([])


def add_locator_inset(fig, host_ax, site_lon, site_lat, zoom=6,
                       bounds_4326=(2.6, 4.0, 14.7, 14.0),
                       boundary_gdf=None, title="Nigeria", margin_frac_bounds=0.15,
                       corner="upper left", width_frac=0.26, height_frac=0.26,
                       margin_frac=0.015):
    """Small inset with a star marker at the site. If boundary_gdf is given
    (a single-polygon GeoDataFrame in EPSG:4326, e.g. Edo State), zooms tightly
    to its bounds and draws the actual boundary outline; otherwise falls back
    to a low-zoom basemap crop of bounds_4326. Positioned relative to
    host_ax's actual figure-space bbox, in a corner, so it never overlaps the
    main map content regardless of figure layout."""
    import contextily as ctx
    import pyproj

    fig.canvas.draw()  # finalize host_ax position before reading it
    pos = host_ax.get_position()
    m_x = margin_frac * pos.width
    m_y = margin_frac * pos.height
    w = width_frac * pos.width
    h = height_frac * pos.height
    if corner == "upper left":
        x0, y0 = pos.x0 + m_x, pos.y1 - h - m_y
    elif corner == "upper right":
        x0, y0 = pos.x1 - w - m_x, pos.y1 - h - m_y
    elif corner == "lower left":
        x0, y0 = pos.x0 + m_x, pos.y0 + m_y
    else:  # lower right
        x0, y0 = pos.x1 - w - m_x, pos.y0 + m_y

    transformer = pyproj.Transformer.from_crs(CRS_WGS84, CRS_WEBMERC, always_xy=True)
    inset_ax = fig.add_axes((x0, y0, w, h))

    if boundary_gdf is not None:
        bminx, bminy, bmaxx, bmaxy = boundary_gdf.total_bounds
        mx = (bmaxx - bminx) * margin_frac_bounds
        my = (bmaxy - bminy) * margin_frac_bounds
        west, south, east, north = bminx - mx, bminy - my, bmaxx + mx, bmaxy + my
    else:
        west, south, east, north = bounds_4326

    xmin, ymin = transformer.transform(west, south)
    xmax, ymax = transformer.transform(east, north)

    # pick a zoom that actually fits the requested bounds tightly, rather than
    # a fixed level -- a small state-sized bbox at a fixed low zoom pulls in
    # whole extra tiles (and thus a much wider area than intended)
    auto_zoom = ctx.tile._calculate_zoom(west, south, east, north)
    zoom = min(max(auto_zoom, zoom), 12)

    img, ext = ctx.bounds2img(xmin, ymin, xmax, ymax, zoom=zoom,
                               source=ctx.providers.Esri.WorldTopoMap, ll=False)
    inset_ax.imshow(img, extent=ext)

    if boundary_gdf is not None:
        boundary_3857 = boundary_gdf.to_crs(CRS_WEBMERC)
        boundary_3857.boundary.plot(ax=inset_ax, color="#8a1a1a", linewidth=1.3, zorder=6)
        boundary_3857.plot(ax=inset_ax, facecolor="#ffcc66", alpha=0.28, zorder=5)

    sx, sy = transformer.transform(site_lon, site_lat)
    inset_ax.plot(sx, sy, marker="*", markersize=14, markerfacecolor="red",
                  markeredgecolor="black", markeredgewidth=0.7, zorder=10)
    inset_ax.set_xlim(ext[0], ext[1])
    inset_ax.set_ylim(ext[2], ext[3])
    inset_ax.set_xticks([])
    inset_ax.set_yticks([])
    # white backing on the title: the inset floats over the main map, and over
    # dark basemap imagery (dense vegetation here) plain black text on the
    # photo is barely readable
    inset_ax.set_title(title, fontsize=7, pad=3,
                       bbox=dict(boxstyle="square,pad=0.25", facecolor="white",
                                 edgecolor="none"))
    for spine in inset_ax.spines.values():
        spine.set_linewidth(1.0)
        spine.set_edgecolor("black")
    return inset_ax


def add_content_inset(fig, host_ax, xlim, ylim, corner="lower left",
                       width_frac=0.27, height_frac=0.22, margin_frac=0.015,
                       title=None, facecolor="white"):
    """A blank, empty inset axes positioned in a corner of host_ax (same
    figure-space anchoring as add_locator_inset), for the caller to plot
    arbitrary content into (e.g. a zoomed-in detail view of a cramped
    cluster of features) -- also draws a connector rectangle on host_ax
    showing the zoomed extent, standard "detail inset" cartographic
    convention. Returns the new axes."""
    fig.canvas.draw()
    pos = host_ax.get_position()
    m_x = margin_frac * pos.width
    m_y = margin_frac * pos.height
    w = width_frac * pos.width
    h = height_frac * pos.height
    if corner == "upper left":
        x0, y0 = pos.x0 + m_x, pos.y1 - h - m_y
    elif corner == "upper right":
        x0, y0 = pos.x1 - w - m_x, pos.y1 - h - m_y
    elif corner == "lower left":
        x0, y0 = pos.x0 + m_x, pos.y0 + m_y
    else:  # lower right
        x0, y0 = pos.x1 - w - m_x, pos.y0 + m_y

    inset_ax = fig.add_axes((x0, y0, w, h))
    inset_ax.set_xlim(*xlim)
    inset_ax.set_ylim(*ylim)
    inset_ax.set_aspect("equal")
    inset_ax.set_facecolor(facecolor)
    inset_ax.set_xticks([])
    inset_ax.set_yticks([])
    if title:
        inset_ax.set_title(title, fontsize=7.5, fontweight="bold", pad=3)
    for spine in inset_ax.spines.values():
        spine.set_linewidth(1.3)
        spine.set_edgecolor("black")

    rect = mpatches.Rectangle((xlim[0], ylim[0]), xlim[1] - xlim[0], ylim[1] - ylim[0],
                              facecolor="none", edgecolor="black", linewidth=1.0,
                              linestyle="--", zorder=20)
    host_ax.add_patch(rect)
    return inset_ax
