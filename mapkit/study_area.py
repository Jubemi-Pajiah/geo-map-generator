"""study_area_map.png -- satellite basemap, contours, labelled stations, and
the full set of cartographic furniture."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import matplotlib.patheffects as patheffects
import contextily as ctx

from . import osm
from .env import crs_label
from .cartography import (add_scalebar, add_north_arrow, add_graticule,
                          add_neatline, add_locator_inset)
from .prepare import contours_for
from .style import STATION_COLORS, STATION_FALLBACK


def build(data, verbose=True):
    site = data.site
    extent, minx, miny, maxx, maxy = data.extent(site.study_buffer_m)
    contours = contours_for(data, extent, "study")

    lat0 = data.stations.iloc[0]["lat"]
    lon0 = data.stations.iloc[0]["lon"]

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect("equal")

    ctx.add_basemap(ax, crs=data.crs, source=ctx.providers.Esri.WorldImagery,
                    zoom=18, attribution=False)

    contours[~contours["is_index"]].plot(ax=ax, color="yellow", linewidth=0.55,
                                         alpha=0.85, zorder=4)
    contours[contours["is_index"]].plot(ax=ax, color="orange", linewidth=1.1,
                                        alpha=0.95, zorder=4.5)

    # Index-contour elevation labels. The smoothed DEM runs a little past the
    # map extent, so a contour's midpoint can land just outside the frame;
    # matplotlib Text defaults to clip_on=False, which would draw the label out
    # in the margin AND make bbox_inches="tight" grow the whole canvas to
    # include it. Skip out-of-frame midpoints, and clip as a safety net.
    for _, row in contours[contours["is_index"]].iterrows():
        pt = row.geometry.interpolate(0.5, normalized=True)
        if not (minx <= pt.x <= maxx and miny <= pt.y <= maxy):
            continue
        ax.text(pt.x, pt.y, f"{row['elev']:.0f}", fontsize=5.5, color="orange",
                fontweight="bold", ha="center", va="center", zorder=4.6,
                clip_on=True)

    for _, row in data.stations_utm.iterrows():
        c = STATION_COLORS.get(row["station"], STATION_FALLBACK)
        ax.scatter(row.geometry.x, row.geometry.y, s=130, marker="^",
                   facecolor=c, edgecolor="black", linewidth=1.0, zorder=8)
        ax.annotate(f"{row['station']}\n{row['elev_m']:.1f} m",
                    (row.geometry.x, row.geometry.y), xytext=(9, 9),
                    textcoords="offset points", fontsize=8, fontweight="bold",
                    color="white", zorder=9,
                    path_effects=[patheffects.withStroke(linewidth=2.5,
                                                         foreground="black")])

    # Anything floating over the frame swallows the graticule label underneath
    # it. Footprints are measured from what these actually render as, not
    # guessed: add_locator_inset at width_frac=height_frac=0.26 with
    # margin_frac=0.035 occupies y 0.705-0.965, and the scale bar's backing
    # panel reaches y~0.13. Declaring the inset down to y=0.66 suppressed a
    # latitude tick that nothing was covering. The north-arrow panel spans
    # roughly x 0.90-1.0, y 0.84-1.0; longitude labels are right-aligned to
    # their meridian, so the region starts a little further left.
    add_graticule(ax, (minx, miny, maxx, maxy), data.crs,
                  suppress_region=[(0.0, 0.70, 0.32, 1.0),    # locator inset
                                   (0.0, 0.00, 0.36, 0.14),   # scale bar panel
                                   (0.88, 0.80, 1.0, 1.0)])   # north arrow panel
    add_scalebar(ax)
    add_north_arrow(ax)
    add_neatline(ax)

    boundary = osm.load_state_boundary(site.data_dir / "nigeria_states.geojson",
                                       site.state)
    # margin_frac above the default so the inset's own title clears the
    # neatline instead of sitting on it
    add_locator_inset(fig, ax, lon0, lat0, boundary_gdf=boundary,
                      title=f"{site.state} State", margin_frac=0.035)

    handles = [
        mlines.Line2D([], [], color="orange", lw=1.4, label="Index contour (5 m)"),
        mlines.Line2D([], [], color="yellow", lw=0.9,
                      label=f"Contour ({site.contour_interval_m:g} m interval)"),
    ]
    for _, row in data.stations_utm.iterrows():
        handles.append(mlines.Line2D(
            [], [], marker="^", color="none",
            markerfacecolor=STATION_COLORS.get(row["station"], STATION_FALLBACK),
            markeredgecolor="black", markersize=10,
            label=site.borehole_label(row['station'])))
    ax.legend(handles=handles, loc="lower right", fontsize=7.5, framealpha=1.0,
              facecolor="white", edgecolor="black", title="Legend",
              title_fontsize=8).set_zorder(50)

    ax.set_title(f"Study Area Map\n{site.subtitle}", fontsize=12,
                 fontweight="bold", pad=26)

    # Wrapped onto several lines deliberately: as one long line this caption is
    # wider than the map, and bbox_inches="tight" then pads the saved PNG out
    # to the caption's width, stranding the map in white space.
    notes = [
        "Basemap: Esri World Imagery (Esri, Maxar, Earthstar Geographics, and the GIS User Community)  |  "
        f"Elevation: Copernicus GLO-30 DEM ({site.contour_interval_m:g} m contours, lightly smoothed for line clarity)",
        f"Projection: {crs_label(data.crs)}  |  {site.station_source_note}",
    ] + list(site.extra_notes)
    fig.text(0.5, 0.005, "\n".join(notes), ha="center", va="bottom",
             fontsize=6.5, linespacing=1.6)

    out = site.output_dir / "study_area_map.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    plt.close(fig)
    if verbose:
        print(f"Saved {out}")
    return out
