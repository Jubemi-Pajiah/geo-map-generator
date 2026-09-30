"""geologic_map.png -- two panels side by side: generalized surface geology
drawn in a hand-drafted style over real OSM road vectors, and the modeled A-A'
subsurface section.

Side by side rather than stacked so the exported image comes out wide rather
than very tall, with the map as the dominant panel -- it is the deliverable,
the section is support.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.patheffects as patheffects
import numpy as np
from shapely.geometry import box

from . import layers, stations as stations_mod
from .cartography import (add_scalebar_outside, add_fancy_north_arrow,
                          add_corner_ticks, add_neatline, add_content_inset)
from .env import crs_label
from .style import STATION_COLORS, STATION_FALLBACK, MAP_BG, TRACE_COLOR, ROAD_STYLES

#: Furniture whose position is fixed, as (x0, y0, x1, y1) in axes fractions.
#: The detail inset is added to a copy of this at build time, once its corner
#: has been chosen from the content.
#: Anything drawn ON TOP of the map panel Matplotlib paints the legend and every separately added inset
#: Axes above the host axes' content regardless of call order, so anything
#: underneath one of these is silently erased. Declared once and used both to
#: PLACE road labels and to AUDIT locality labels -- keeping two copies in sync
#: by hand is how a road name once ended up rendering half-clipped.
BASE_FURNITURE = {
    "legend": (0.00, 0.00, 0.48, 0.22),
    "north arrow": (0.82, 0.78, 1.00, 1.00),
}


def build(data, verbose=True):
    site = data.site
    geo = site.geology
    extent, minx, miny, maxx, maxy = data.extent(site.geologic_buffer_m)

    xs, ys = zip(*data.line_utm.coords)
    ve = data.vertical_exaggeration

    fig = plt.figure(figsize=(15.5, 11.5))
    # Generous bottom margin: the scale bar is drawn BELOW the map panel, and
    # with a tight bottom it lands exactly where the source caption sits.
    gs = fig.add_gridspec(1, 2, width_ratios=[2.2, 1], wspace=0.10,
                          left=0.045, right=0.99, top=0.90, bottom=0.115)
    ax_map = fig.add_subplot(gs[0])
    ax_sec = fig.add_subplot(gs[1])

    # ---------------- (a) surface geology ----------------
    ax_map.set_xlim(minx, maxx)
    ax_map.set_ylim(miny, maxy)
    ax_map.set_aspect("equal")
    ax_map.set_facecolor(MAP_BG)

    ax_map.add_patch(mpatches.Polygon(
        list(box(minx, miny, maxx, maxy).exterior.coords), closed=True,
        facecolor=geo.color, edgecolor="none", zorder=1, hatch=geo.hatch))
    ax_map.text((minx + maxx) / 2, maxy - (maxy - miny) * 0.065, geo.label,
                fontsize=24, fontweight="bold", ha="center", va="center",
                color="#8a6a2a", alpha=0.55, zorder=1.5)

    layers.plot_roads(ax_map, data.roads_utm)

    # Decide where the detail inset goes BEFORE placing any label, then build
    # the furniture table from that. The inset paints over whatever is beneath
    # it, so a label steered around a hard-coded "upper left" box while the
    # inset actually sits lower right is steered around nothing.
    corner = layers.choose_inset_corner(
        ax_map, [data.places_utm, data.markets_utm],
        reserved=[BASE_FURNITURE["legend"], BASE_FURNITURE["north arrow"]],
        stations_utm=data.stations_utm)
    furniture = dict(BASE_FURNITURE)
    furniture["borehole detail inset"] = layers._CORNER_BOXES[corner]
    if verbose:
        print(f"  detail inset placed {corner}")

    # Which road to name: the site's choice if it made one, otherwise the
    # longest named road actually crossing this frame. Leaving it undeclared is
    # the common case and used to mean the map simply carried no road label at
    # all, even where OSM had a perfectly good name for the road running
    # through it.
    main_road = site.main_road_name or layers.longest_named_road(ax_map, data.roads_utm)

    # Label the named roads, each steered clear of the furniture AND of the
    # label already placed, so two names on converging roads do not collide.
    placed = []
    for name, size, colour in (
        (main_road, 10.0, "#2a2010"),
        (site.construction_road_name, 9.0, ROAD_STYLES["construction"]["color"]),
    ):
        if not name:
            continue
        box_ = layers.plot_named_road(
            ax_map, data.roads_utm, name, avoid=list(furniture.values()),
            fontsize=size, color=colour, extra_avoid=placed)
        if box_:
            placed.append(box_)

    river_drawn = layers.plot_waterways(
        ax_map, data.rivers_utm, name=site.river_name,
        avoid=list(furniture.values()) + placed)
    places_drawn = layers.plot_places(ax_map, data.places_utm)
    markets_drawn = layers.plot_markets(ax_map, data.markets_utm)

    ax_map.plot(xs, ys, color=TRACE_COLOR, lw=2.2, ls=(0, (6, 3)), zorder=7)
    layers.draw_section_ends(
        ax_map, xs, ys,
        site.main_end_label_offsets or stations_mod.auto_end_offsets(
            data.stations_utm, spread=True),
        fontsize=13, stroke_lw=3, zorder=8)

    # Markers only, deliberately NOT per-station text. On this wider frame the
    # traverse spans a few percent of the width, so three labels here render as
    # one unreadable blob whatever offsets they are given. The legend's colour
    # key identifies them at this scale; the detail inset carries the named,
    # elevation-tagged labels.
    for _, row in data.stations_utm.iterrows():
        ax_map.scatter(row.geometry.x, row.geometry.y, s=140, marker="^",
                       facecolor=STATION_COLORS.get(row["station"], STATION_FALLBACK),
                       edgecolor="black", linewidth=1.1, zorder=9)

    # Zoomed detail inset, because at this extent the stations and their labels
    # would be illegible. The connector rectangle on the main map shows what is
    # magnified.
    sminx, sminy, smaxx, smaxy = data.stations_utm.total_bounds
    scx, scy = (sminx + smaxx) / 2, (sminy + smaxy) / 2
    half = max(smaxx - sminx, smaxy - sminy) * 0.75 + 40
    detail = add_content_inset(
        fig, ax_map, (scx - half, scx + half), (scy - half, scy + half),
        corner=corner, title="Borehole Detail (zoomed)",
        facecolor=geo.color, margin_frac=0.05)
    detail.plot(xs, ys, color=TRACE_COLOR, lw=2.2, ls=(0, (6, 3)), zorder=3)

    detail_offsets = (site.detail_label_offsets
                      or stations_mod.auto_station_offsets(data.stations_utm))
    layers.draw_section_ends(
        detail, xs, ys,
        site.end_label_offsets or stations_mod.auto_end_offsets(
            data.stations_utm, detail_offsets, spread=False),
        fontsize=11, stroke_lw=2.5, zorder=4)
    for _, row in data.stations_utm.iterrows():
        detail.scatter(row.geometry.x, row.geometry.y, s=170, marker="^",
                       facecolor=STATION_COLORS.get(row["station"], STATION_FALLBACK),
                       edgecolor="black", linewidth=1.2, zorder=5)
        off, ha, va = detail_offsets.get(row["station"], ((10, 10), "left", "bottom"))
        detail.annotate(f"{row['station']}\n{row['elev_m']:.1f} m",
                        (row.geometry.x, row.geometry.y), xytext=off,
                        textcoords="offset points", ha=ha, va=va, fontsize=8,
                        fontweight="bold", zorder=6,
                        path_effects=[patheffects.withStroke(linewidth=2.5,
                                                             foreground="white")])

    add_corner_ticks(ax_map, (minx, miny, maxx, maxy), data.crs)
    add_fancy_north_arrow(ax_map)
    add_neatline(ax_map, linewidth=2.4)

    handles = [
        mpatches.Patch(facecolor=geo.color, edgecolor="black", hatch=geo.hatch,
                       label=geo.legend),
        mlines.Line2D([], [], color=TRACE_COLOR, lw=2.2, ls=(0, (6, 3)),
                      label="Cross-section trace A-A'"),
    ]
    named = {}
    if main_road and not data.roads_utm.empty:
        hit = data.roads_utm[data.roads_utm["name"] == main_road]
        if not hit.empty:
            named[hit.iloc[0]["highway"]] = main_road
    if site.construction_road_name:
        named["construction"] = site.construction_road_name
    handles += layers.road_legend_handles(data.roads_utm, ax=ax_map, named=named)

    # Every remaining key is conditional on the symbol ACTUALLY being drawn. On
    # a sparse site a legend of keys for absent symbols reads as "the map
    # failed to render them" rather than "they are not there".
    if river_drawn:
        handles.append(mlines.Line2D([], [], color="#3a7ca5", lw=2.0,
                                     label="River / stream (OSM)"))
    if places_drawn:
        handles.append(mlines.Line2D([], [], marker="o", color="none",
                                     markerfacecolor="#3a5a1a", markeredgecolor="white",
                                     markersize=7, label="Named locality (OSM)"))
    if markets_drawn:
        handles.append(mlines.Line2D([], [], marker="s", color="none",
                                     markerfacecolor="#8a4a1a", markeredgecolor="white",
                                     markersize=7, label="Market (OSM)"))
    for _, row in data.stations_utm.iterrows():
        handles.append(mlines.Line2D(
            [], [], marker="^", color="none",
            markerfacecolor=STATION_COLORS.get(row["station"], STATION_FALLBACK),
            markeredgecolor="black", markersize=10,
            label=site.borehole_label(row['station'])))

    ax_map.legend(handles=handles, loc="lower left", fontsize=7.3, framealpha=1.0,
                  facecolor="white", edgecolor="black", title="Legend",
                  title_fontsize=8).set_zorder(50)

    if data.places_utm is not None and not data.places_utm.empty:
        layers.warn_on_overlaps(ax_map, layers.in_frame(ax_map, data.places_utm),
                                furniture, what="locality label")
    elif verbose:
        # Say it out loud on every run. An empty locality layer is a property
        # of the source data, not a silent rendering failure, and that
        # distinction is easy to lose when re-running months later.
        print("  no OSM place/locality node in frame -- locality layer "
              "intentionally empty, nothing substituted")

    ax_map.set_title(f"Geologic Map\n{site.subtitle}", fontsize=12,
                     fontweight="bold", pad=112)
    add_scalebar_outside(fig, ax_map, margin_frac=0.03)

    # ---------------- (b) A-A' section ----------------
    _draw_section(ax_sec, data, ve)

    # --- source caption -------------------------------------------------
    notes = [_provenance_note(data, main_road),
             f"Regional geology: {geo.source}  |  Projection: {crs_label(data.crs)}",
             site.station_source_note]
    notes += list(site.extra_notes)
    fig.text(0.5, 0.005, "\n".join(notes), ha="center", va="bottom",
             fontsize=6.5, linespacing=1.6)

    out = site.output_dir / "geologic_map.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    if verbose:
        print(f"Saved {out}")
    return out


def _provenance_note(data, main_road=None):
    """State what OSM actually gave us, generated from the fetched data.

    Written from the layers themselves rather than typed per site so it cannot
    drift out of step with the map: if a site has no locality node, the caption
    says so, and if it gains one later the caption follows without an edit.
    """
    site = data.site
    named = sorted(data.roads_utm[data.roads_utm["name"].notna()]["name"].unique()) \
        if not data.roads_utm.empty else []
    bits = ["Roads: OpenStreetMap contributors (ODbL)."]
    if site.construction_road_name:
        bits.append(f"The {site.construction_road_name} is tagged "
                    "highway=construction in OSM and is drawn as under "
                    "construction, not as an existing road.")
    absent = []
    if data.places_utm is None or data.places_utm.empty:
        absent.append("locality node")
    if data.rivers_utm is None or data.rivers_utm.empty:
        absent.append("waterway")
    if absent:
        bits.append("OSM carries NO " + " and NO ".join(absent) +
                    " in this frame; nothing has been substituted.")
    if not named:
        bits.append("No named road exists here at any scale tried; none has "
                    "been invented.")
    return " ".join(bits)


def _draw_section(ax, data, ve):
    """The lithology panel: bands hung off the surveyed ground surface.

    Kept deliberately plain -- black surface line, clean bands, no decorative
    fills. Styling added on top of the lithology reads as clutter on what is
    meant to be a readable section.
    """
    from scipy.interpolate import PchipInterpolator

    site = data.site
    geo = site.geology
    depth = geo.section_depth
    dists = np.array(data.station_dists, dtype=float)
    elevs = np.array(data.station_elevs, dtype=float)
    total = dists[-1]

    # Shape-preserving interpolation through the ACTUAL surveyed points: no
    # overshoot, and the curve passes exactly through each collar, so the
    # ground line is a smooth terrain profile rather than linear kinks.
    dense_x = np.linspace(0, total, 400)
    dense_y = PchipInterpolator(dists, elevs)(dense_x)

    ax.set_facecolor("white")
    for unit in geo.units:
        ax.fill_between(dense_x, dense_y - unit.base, dense_y - unit.top,
                        color=unit.color, hatch=unit.hatch, edgecolor="#3a2a10",
                        linewidth=0.3, zorder=2)
    ax.plot(dense_x, dense_y, color="black", lw=1.8, zorder=5)

    cutoff = dense_y - depth
    ax.fill_between(dense_x, cutoff - 3, cutoff, color="white", zorder=1)
    ax.text(total / 2, cutoff.min() - 1.5, "Not penetrated / inferred continuation",
            ha="center", va="top", fontsize=7.5, style="italic", color="dimgray")

    for d, e, name in zip(dists, elevs, data.stations_utm["station"]):
        ax.plot([d, d], [e, e - depth], color="black", lw=0.7, ls=":", zorder=6)
        ax.scatter([d], [e], marker="v", s=90,
                   facecolor=STATION_COLORS.get(name, STATION_FALLBACK),
                   edgecolor="black", zorder=7)
        ha = "left" if d <= total * 0.1 else ("right" if d >= total * 0.9 else "center")
        dx = 6 if ha == "left" else (-6 if ha == "right" else 0)
        # Clear the ground the label SPANS, not just its own collar. An end
        # station low on a rising traverse has its label pushed inland, over
        # ground that climbs well above the collar, and a fixed rise then lays
        # the text straight across the surface line -- e.g. a collar at 90 m
        # with the ground already near 101 m one label-width away.
        # Flat and falling spans yield zero clearance, so every section that
        # was already correct is left exactly as it was.
        span = total * 0.15
        lo, hi = ((d, d + span) if ha == "left" else
                  (d - span, d) if ha == "right" else
                  (d - span / 2, d + span / 2))
        window = dense_y[(dense_x >= lo) & (dense_x <= hi)]
        anchor = max(e, window.max()) if window.size else e
        ax.annotate(f"{name}\n{e:.1f} m", (d, anchor), xytext=(dx, 10),
                    textcoords="offset points", ha=ha, fontsize=8,
                    fontweight="bold", zorder=8,
                    path_effects=[patheffects.withStroke(linewidth=2.5,
                                                         foreground="white")])

    ax.annotate("A", (0, elevs[0]), xytext=(-18, 0), textcoords="offset points",
                fontsize=13, fontweight="bold", va="center")
    ax.annotate("A'", (total, elevs[-1]), xytext=(10, 0),
                textcoords="offset points", fontsize=13, fontweight="bold",
                va="center")

    ax.set_xlim(-total * 0.06, total * 1.06)
    ax.set_ylim(cutoff.min() - 5, elevs.max() + 8)
    # Lock the true vertical exaggeration; anchor="N" keeps the panel flush to
    # the top of its cell rather than centring with wasted gaps.
    ax.set_aspect(ve, adjustable="box", anchor="N")
    ax.set_xlabel("Distance along A-A' (m)", fontsize=9)
    ax.set_ylabel("Elevation (m)", fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(True, ls=":", lw=0.4, alpha=0.6, zorder=0)

    unit_handles = [
        mpatches.Patch(facecolor=u.color, edgecolor="#3a2a10", hatch=u.hatch,
                       label=f"{u.name} ({u.top:.0f}-{u.base:.0f} m)")
        for u in geo.units]
    unit_handles.append(mlines.Line2D([], [], color="black", lw=1.8,
                                      label=("Ground surface (through synthetic collars)"
                                             if site.synthetic_stations
                                             else "Ground surface (surveyed)")))
    # Below the panel, not squeezed inside it: freed from the panel's narrow
    # width the legend can run bigger and clearer.
    ax.legend(handles=unit_handles, loc="upper center", bbox_to_anchor=(0.5, -0.09),
              bbox_transform=ax.transAxes, fontsize=10.5, framealpha=1.0,
              facecolor="white", edgecolor="black", ncol=1,
              title="Lithologic units", title_fontsize=12, handlelength=2.6,
              handleheight=1.6, borderpad=0.9, labelspacing=0.7).set_zorder(50)

    # "x1" is not an exaggeration, and printing it as one invites the reader to
    # discount relief that is drawn at true scale. Say which it is.
    note = "no vertical exaggeration" if ve == 1 else f"Vertical Exaggeration x{ve:g}"
    # Title and sub-note anchored with a FIXED POINTS offset, not an
    # axes-fraction one: a fraction offset looks right at one panel size and
    # balloons into a huge disconnected gap the moment the panel is resized.
    ax.annotate(f"Cross-Section A-A'  ({note})", xy=(0.5, 1.0),
                xycoords="axes fraction", xytext=(0, 58),
                textcoords="offset points", ha="center", va="bottom",
                fontsize=10.5, fontweight="bold", clip_on=False)
    basis = geo.section_basis or f"regional lithostratigraphy of the {geo.formation}"
    ax.annotate(f"Based on {basis}",
                xy=(0.5, 1.0), xycoords="axes fraction", xytext=(0, 10),
                textcoords="offset points", ha="center", va="bottom",
                fontsize=8, color=TRACE_COLOR, style="italic", clip_on=False)
