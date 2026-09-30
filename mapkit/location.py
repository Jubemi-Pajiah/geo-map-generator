"""location_map.png -- the three-panel figure a report carries in Chapter One:
(a) the country with the host state, (b) the state with its LGAs and the host
LGA, (c) the site itself on real OSM road vectors. Dashed leaders link each
panel to the next so the country -> state -> LGA -> site nesting reads at a
glance.

Complements the other two rather than repeating them: study_area_map carries
the topography, geologic_map the geology and section, this one answers "where
on earth is this".
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.patheffects as patheffects
import numpy as np
from matplotlib.patches import ConnectionPatch
from shapely.geometry import Point

from . import layers, osm, stations as stations_mod
from .cartography import (add_scalebar, add_corner_ticks, add_fancy_north_arrow,
                          dd_to_dm, _nice_round)
from .env import crs_label
from .style import STATION_COLORS, STATION_FALLBACK, MAP_BG, ROAD_STYLES

SEA_BG = "#dfeaf2"
NATION_FILL = "#f2efe4"
NATION_EDGE = "#9a9a8c"
HIGHLIGHT_FILL = "#e8b64c"
HIGHLIGHT_EDGE = "#8a1a1a"
LGA_FILL = "#f6f1df"
LGA_EDGE = "#a89f83"
CONNECT_COLOR = "#8a1a1a"

#: Shared by all three panel titles so they align. Panel (c)'s vertical DMS
#: tick labels stick a long way above its neatline, and a rotated label's
#: on-screen HEIGHT equals its unrotated text WIDTH -- easy to underestimate,
#: so this pad is larger than it looks like it needs to be.
TITLE_PAD = 44

#: What floats on top of panel (c), in axes fractions.
PANEL_C_FURNITURE = {
    "legend": (0.0, 0.70, 0.36, 1.0),
    "north arrow": (0.83, 0.72, 1.0, 1.0),
    "scale bar": (0.0, 0.0, 0.38, 0.15),
}


def _frame(ax, lw=1.3):
    """Bold neatline, leaving tick marks alone (unlike add_neatline, which also
    clears them -- panels (a) and (b) keep their degree ticks)."""
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(lw)
        spine.set_edgecolor("black")


def _fit_extent(fig, ax, bounds, k, pad_frac=0.06):
    """Expand a bbox symmetrically until its aspect matches the axes' own box,
    so each panel fills its cell without distorting shapes. `k` is the
    y-per-x factor giving equal ground scale on both axes: 1.0 for a projected
    metric CRS, 1/cos(lat) for lat/lon degrees. Reads the cell position from
    the subplotspec, not the live axes, since set_aspect shrinks the drawn box
    and would otherwise feed back."""
    west, south, east, north = bounds
    dx, dy = (east - west) * pad_frac, (north - south) * pad_frac
    west, east = west - dx, east + dx
    south, north = south - dy, north + dy

    ax.set_aspect(k)
    pos = ax.get_subplotspec().get_position(fig)
    box_ratio = (pos.height * fig.get_figheight()) / (pos.width * fig.get_figwidth())
    span_x, span_y = east - west, (north - south) * k
    if span_y / span_x < box_ratio:
        extra = (box_ratio * span_x - span_y) / k
        south, north = south - extra / 2, north + extra / 2
    else:
        extra = span_y / box_ratio - span_x
        west, east = west - extra / 2, east + extra / 2

    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    return west, south, east, north


def _geo_ticks(ax, step=None, fontsize=6.0):
    """Degree ticks in D°MM.M' form on a lat/lon panel, matching the DMS style
    add_corner_ticks gives the projected site panel."""
    west, east = ax.get_xlim()
    south, north = ax.get_ylim()
    if step is None:
        span = max(east - west, north - south)
        step = next((c for c in [0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 5.0]
                     if span / c <= 5), 5.0)
    xs = np.arange(np.ceil(west / step) * step, east + step / 2, step)
    ys = np.arange(np.ceil(south / step) * step, north + step / 2, step)
    ax.set_xticks([x for x in xs if west < x < east])
    ax.set_yticks([y for y in ys if south < y < north])
    ax.set_xticklabels([dd_to_dm(x, is_lat=False) for x in ax.get_xticks()],
                       fontsize=fontsize, rotation=90, ha="center")
    ax.set_yticklabels([dd_to_dm(y, is_lat=True) for y in ax.get_yticks()],
                       fontsize=fontsize, rotation=90, va="center")
    ax.tick_params(length=3, width=0.8, pad=1.5)


def _geo_scalebar(ax, length_frac=0.30, x_frac=0.05, y_frac=0.045, n_segments=2):
    """Scale bar for a lat/lon panel: degrees of longitude at the panel's
    mid-latitude converted to ground kilometres. Approximate by nature (scale
    varies north-south across the panel), hence the 'approx.' label."""
    west, east = ax.get_xlim()
    south, north = ax.get_ylim()
    km_per_deg = 111.32 * np.cos(np.radians((south + north) / 2))
    bar_km = _nice_round((east - west) * km_per_deg * length_frac)
    bar_deg = bar_km / km_per_deg
    seg = bar_deg / n_segments
    x0 = west + x_frac * (east - west)
    y0 = south + y_frac * (north - south)
    h = (north - south) * 0.011

    ax.add_patch(mpatches.Rectangle(
        (x0 - seg * 0.12, y0 - h * 1.9), bar_deg + seg * 0.24, h * 5.2,
        facecolor="white", edgecolor="black", linewidth=0.6, alpha=0.9, zorder=9.5))
    for i in range(n_segments):
        ax.add_patch(mpatches.Rectangle(
            (x0 + i * seg, y0), seg, h,
            facecolor="black" if i % 2 == 0 else "white",
            edgecolor="black", linewidth=0.7, zorder=10))
    for i in range(n_segments + 1):
        ax.text(x0 + i * seg, y0 + h * 1.3, f"{i * bar_km / n_segments:g}",
                ha="center", va="bottom", fontsize=5.6, zorder=10)
    ax.text(x0 + bar_deg / 2, y0 - h * 0.6, "km (approx.)", ha="center",
            va="top", fontsize=5.6, zorder=10)


def _small_north_arrow(ax, x_frac=0.92, y_frac=0.84, size_frac=0.10):
    west, east = ax.get_xlim()
    south, north = ax.get_ylim()
    cx = west + x_frac * (east - west)
    cy = south + y_frac * (north - south)
    size = size_frac * (north - south)
    ax.annotate("", xy=(cx, cy + size), xytext=(cx, cy),
                arrowprops=dict(arrowstyle="-|>", color="black", lw=1.4,
                                mutation_scale=13), zorder=11)
    ax.text(cx, cy + size * 1.05, "N", ha="center", va="bottom", fontsize=8,
            fontweight="bold", zorder=11)


def _connect(fig, ax_from, xy_from, ax_to, corners=((0, 1), (0, 0))):
    """Dashed leaders from a feature on one panel to the edge of the next --
    the standard way these nested figures show that panel N+1 blows up a spot
    on panel N."""
    for corner in corners:
        fig.add_artist(ConnectionPatch(
            xyA=xy_from, coordsA=ax_from.transData,
            xyB=corner, coordsB=ax_to.transAxes,
            color=CONNECT_COLOR, linewidth=0.9, linestyle=(0, (4, 3)), zorder=0.5))


def build(data, verbose=True):
    site = data.site
    site_lon = float(data.stations["lon"].mean())
    site_lat = float(data.stations["lat"].mean())
    site_pt = Point(site_lon, site_lat)

    d = site.data_dir
    states = osm.load_nigeria_states(d / "nigeria_states.geojson")
    state_gdf = osm.load_state_boundary(d / "nigeria_states.geojson", site.state)
    lgas = osm.load_nigeria_lgas(d / "nigeria_lgas.geojson",
                                 within=state_gdf.geometry.iloc[0])
    host = lgas[lgas.geometry.contains(site_pt)]
    host_name = host.iloc[0]["name"] if not host.empty else None

    _, minx, miny, maxx, maxy = data.extent(site.location_buffer_m)

    fig = plt.figure(figsize=(16.5, 6.2))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.15, 0.95, 1.30], wspace=0.14,
                          left=0.045, right=0.985, top=0.785, bottom=0.105)
    ax_n, ax_s, ax_c = (fig.add_subplot(gs[i]) for i in range(3))

    # ---------------- (a) the country ----------------
    ax_n.set_facecolor(SEA_BG)
    states.plot(ax=ax_n, facecolor=NATION_FILL, edgecolor=NATION_EDGE,
                linewidth=0.5, zorder=2)
    state_gdf.plot(ax=ax_n, facecolor=HIGHLIGHT_FILL, edgecolor=HIGHLIGHT_EDGE,
                   linewidth=1.2, zorder=3)
    _fit_extent(fig, ax_n, tuple(states.total_bounds),
                k=1 / np.cos(np.radians(float(states.total_bounds[[1, 3]].mean()))))

    sb = state_gdf.total_bounds
    ax_n.add_patch(mpatches.Rectangle(
        (sb[0], sb[1]), sb[2] - sb[0], sb[3] - sb[1], facecolor="none",
        edgecolor=CONNECT_COLOR, linewidth=1.1, linestyle=(0, (4, 3)), zorder=7))
    ax_n.plot(site_lon, site_lat, marker="*", markersize=12, markerfacecolor="red",
              markeredgecolor="black", markeredgewidth=0.6, zorder=8)
    ax_n.annotate(f"{site.state.upper()}\nSTATE", (sb[0], sb[3]), xytext=(-6, 14),
                  textcoords="offset points", ha="right", va="bottom", fontsize=8,
                  fontweight="bold", color=HIGHLIGHT_EDGE, zorder=8,
                  path_effects=[patheffects.withStroke(linewidth=2.4, foreground="white")])
    _geo_ticks(ax_n)
    _geo_scalebar(ax_n)
    _small_north_arrow(ax_n)
    _frame(ax_n)
    ax_n.set_title(f"(a)  Nigeria, showing {site.state} State", fontsize=9.5,
                   fontweight="bold", pad=TITLE_PAD)

    # ---------------- (b) the state ----------------
    ax_s.set_facecolor(SEA_BG)
    lgas.plot(ax=ax_s, facecolor=LGA_FILL, edgecolor=LGA_EDGE, linewidth=0.7, zorder=2)
    if host_name:
        host.plot(ax=ax_s, facecolor=HIGHLIGHT_FILL, edgecolor=HIGHLIGHT_EDGE,
                  linewidth=1.2, zorder=3)
    state_gdf.boundary.plot(ax=ax_s, color="#5a3a10", linewidth=1.6, zorder=4)
    # Mid-latitude of THIS state, so the panel is not stretched -- the
    # reference version hard-coded one state's latitude and was copied on.
    _fit_extent(fig, ax_s, tuple(state_gdf.total_bounds),
                k=1 / np.cos(np.radians(float(sb[[1, 3]].mean()))))

    # The host LGA's own name is skipped here and redrawn on a leader below:
    # where the site sits in a small LGA, the label lands under the study-area
    # star and is unreadable.
    for _, row in lgas.iterrows():
        if row["name"] == host_name:
            continue
        p = row.geometry.representative_point()
        ax_s.text(p.x, p.y, row["name"], fontsize=5.3, ha="center", va="center",
                  color="#4a4030", zorder=5,
                  path_effects=[patheffects.withStroke(linewidth=1.8, foreground="white")])
    if host_name:
        hp = host.geometry.iloc[0].representative_point()
        ax_s.annotate(f"{host_name} LGA", (hp.x, hp.y), xytext=(46, -34),
                      textcoords="offset points", ha="center", fontsize=7,
                      fontweight="bold", color=HIGHLIGHT_EDGE, zorder=8,
                      arrowprops=dict(arrowstyle="-", color=HIGHLIGHT_EDGE, lw=0.8,
                                      shrinkA=1, shrinkB=1),
                      path_effects=[patheffects.withStroke(linewidth=2.4, foreground="white")])
    ax_s.plot(site_lon, site_lat, marker="*", markersize=15, markerfacecolor="red",
              markeredgecolor="black", markeredgewidth=0.7, zorder=8)
    # West of the star, not east: the dashed leaders to panel (c) always run
    # east from the star, and a label on that side sits on top of them.
    ax_s.annotate("Study area", (site_lon, site_lat), xytext=(-11, 7),
                  textcoords="offset points", ha="right", fontsize=7.5,
                  fontweight="bold",
                  color=CONNECT_COLOR, zorder=8,
                  path_effects=[patheffects.withStroke(linewidth=2.4, foreground="white")])
    _geo_ticks(ax_s)
    _geo_scalebar(ax_s)
    _small_north_arrow(ax_s)
    _frame(ax_s)
    ax_s.set_title(f"(b)  {site.state} State, showing {host_name} LGA" if host_name
                   else f"(b)  {site.state} State and its LGAs",
                   fontsize=9.5, fontweight="bold", pad=TITLE_PAD)

    # ---------------- (c) the site ----------------
    ax_c.set_facecolor(MAP_BG)
    cminx, cminy, cmaxx, cmaxy = _fit_extent(fig, ax_c, (minx, miny, maxx, maxy),
                                             k=1.0, pad_frac=0.0)
    layers.plot_roads(ax_c, data.roads_utm)

    avoid = (list(PANEL_C_FURNITURE.values())
             + layers.avoid_boxes_for_points(ax_c, data.stations_utm))
    placed = []
    for name, size, colour in (
        (site.main_road_name, 7.0, "#2a2010"),
        (site.construction_road_name, 6.5, ROAD_STYLES["construction"]["color"]),
    ):
        if not name:
            continue
        b = layers.plot_named_road(ax_c, data.roads_utm, name, avoid=avoid,
                                   fontsize=size, color=colour, extra_avoid=placed)
        if b:
            placed.append(b)
    layers.plot_waterways(ax_c, data.rivers_utm, name=site.river_name,
                          avoid=avoid + placed)
    layers.plot_places(ax_c, data.places_utm, fontsize=7.5)
    layers.plot_markets(ax_c, data.markets_utm, fontsize=7.0)

    offsets = (site.station_label_offsets
               or stations_mod.auto_station_offsets(data.stations_utm))
    for _, row in data.stations_utm.iterrows():
        ax_c.scatter(row.geometry.x, row.geometry.y, s=115, marker="^",
                     facecolor=STATION_COLORS.get(row["station"], STATION_FALLBACK),
                     edgecolor="black", linewidth=0.9, zorder=8)
        off, ha, va = offsets.get(row["station"], ((8, 7), "left", "bottom"))
        ax_c.annotate(f"{row['station']}\n{row['elev_m']:.1f} m",
                      (row.geometry.x, row.geometry.y), xytext=off,
                      textcoords="offset points", fontsize=7, fontweight="bold",
                      ha=ha, va=va, color="#1a1a1a", zorder=9,
                      path_effects=[patheffects.withStroke(linewidth=2.4,
                                                           foreground=MAP_BG)])

    add_corner_ticks(ax_c, (cminx, cminy, cmaxx, cmaxy), data.crs, tick_frac=0.010)
    # add_corner_ticks draws its own DMS ticks outside the neatline, so the
    # axes' default metre ticks have to go or both sets render at once.
    ax_c.set_xticks([])
    ax_c.set_yticks([])
    add_scalebar(ax_c, location=(0.04, 0.07), length_frac=0.30)
    add_fancy_north_arrow(ax_c, location=(0.92, 0.85), size_frac=0.085)
    _frame(ax_c, lw=1.4)

    handles = layers.road_legend_handles(data.roads_utm, ax=ax_c)
    for _, row in data.stations_utm.iterrows():
        handles.append(mlines.Line2D(
            [], [], marker="^", color="none",
            markerfacecolor=STATION_COLORS.get(row["station"], STATION_FALLBACK),
            markeredgecolor="black", markersize=8,
            label=site.borehole_label(row['station'])))
    # facecolor must be set EXPLICITLY: framealpha=1.0 alone leaves the patch on
    # matplotlib's default near-white-but-translucent face, and a dense street
    # grid reads straight through it.
    ax_c.legend(handles=handles, loc="upper left", fontsize=6.3, framealpha=1.0,
                facecolor="white", edgecolor="black", title="Legend",
                title_fontsize=6.8).set_zorder(50)
    ax_c.set_title("(c)  The study area", fontsize=9.5, fontweight="bold", pad=TITLE_PAD)

    layers.warn_on_overlaps(ax_c, data.stations_utm.rename(columns={"station": "name"}),
                            PANEL_C_FURNITURE, what="borehole")

    _connect(fig, ax_n, (sb[2], sb[3]), ax_s, corners=((0, 1),))
    _connect(fig, ax_n, (sb[2], sb[1]), ax_s, corners=((0, 0),))
    _connect(fig, ax_s, (site_lon, site_lat), ax_c, corners=((0, 1), (0, 0)))

    fig.suptitle(f"Location Map of the Study Area\n{site.subtitle}", fontsize=13,
                 fontweight="bold", y=0.985)
    fig.text(0.5, 0.012,
             "Administrative boundaries: geoBoundaries Nigeria ADM1/ADM2 (CC-BY 4.0)  |  "
             "Roads and localities: OpenStreetMap contributors (ODbL)  |  "
             f"Projection: (a)-(b) WGS84 geographic, (c) {crs_label(data.crs)}  |  "
             f"{site.station_source_note}",
             ha="center", fontsize=6.5)

    out = site.output_dir / "location_map.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    if verbose:
        print(f"Saved {out}")
    return out
