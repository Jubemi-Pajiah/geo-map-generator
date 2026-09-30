"""Shared palette and road styling.

One road hierarchy serves every site. The reference projects each grew their
own table, which meant a rural site's farm tracks were styled as faint grey
hairlines when copied from a town, and a town's 270 residential streets came
out as thick primary roads when copied from a village. The weights below are
chosen so that whichever classes a frame happens to contain still read: tracks
and paths are dashed and dark enough to carry a rural map on their own, while
residential streets stay light enough to read as texture under a trunk road.
"""

#: One colour per borehole, identical across all three maps and the
#: cross-section, so a reader can follow a station between panels.
STATION_COLORS = {
    "BH1": "#ff2d2d",
    "BH2": "#2dd4ff",
    "BH3": "#2dff6e",
    "BH4": "#ffd12d",
    "BH5": "#c77dff",
    "BH6": "#ff8c42",
}
# Lettered IDs (BH-A, BH-B, ...) take the same colours in the same order.
STATION_COLORS.update({f"BH-{chr(ord('A') + i)}": c
                       for i, c in enumerate(list(STATION_COLORS.values()))})
STATION_FALLBACK = "#dddddd"

MAP_BG = "#faf6ea"
RIVER_COLOR = "#3a7ca5"
TRACE_COLOR = "#8a1a1a"
PLACE_COLOR = "#3a5a1a"
PLACE_TEXT = "#2a4a10"
MARKET_COLOR = "#8a4a1a"
MARKET_TEXT = "#6a3410"

ROAD_STYLES = {
    "trunk":        dict(lw=3.0, color="#4a3a2a", zorder=5.9),
    "trunk_link":   dict(lw=1.8, color="#4a3a2a", zorder=5.85),
    "primary":      dict(lw=2.5, color="#5a4632", zorder=5.8),
    "primary_link": dict(lw=1.6, color="#5a4632", zorder=5.75),
    "secondary":    dict(lw=2.0, color="#5a4632", zorder=5.7),
    "secondary_link": dict(lw=1.3, color="#5a4632", zorder=5.68),
    "tertiary":     dict(lw=1.6, color="#3a3a3a", zorder=5.6),
    "tertiary_link": dict(lw=1.1, color="#3a3a3a", zorder=5.55),
    "unclassified": dict(lw=1.3, color="#555555", zorder=5.4),
    "residential":  dict(lw=0.95, color="#6a6a6a", zorder=5.3),
    "service":      dict(lw=0.7, color="#8a8a8a", zorder=5.0),
    # Under construction: its own colour and dash, never the same ink as a
    # built road. Drawing an unbuilt highway like an existing one misstates
    # what is on the ground.
    "construction": dict(lw=2.2, color="#9a6a2a", zorder=5.5, ls=(0, (9, 4))),
    "track":        dict(lw=1.1, color="#7a6a4a", zorder=5.2, ls=(0, (7, 3))),
    "path":         dict(lw=0.7, color="#8a8a7a", zorder=5.1, ls=(0, (2, 2.5))),
    "footway":      dict(lw=0.7, color="#8a8a7a", zorder=5.1, ls=(0, (2, 2.5))),
    "cycleway":     dict(lw=0.7, color="#8a8a7a", zorder=5.1, ls=(0, (2, 2.5))),
}
DEFAULT_ROAD_STYLE = dict(lw=0.8, color="#888888", zorder=5.0)

#: Classes that get a thin light centreline, reading as a dual carriageway.
#: Deliberately excludes `construction`.
MAJOR_ROAD_CLASSES = {"trunk", "primary"}

#: How road classes are described in a legend, and how they group. Several OSM
#: classes collapse onto one legend row so the key stays short.
ROAD_LEGEND_GROUPS = [
    (("trunk", "trunk_link"), "Trunk road"),
    (("primary", "primary_link"), "Primary road"),
    (("secondary", "secondary_link"), "Secondary road"),
    (("tertiary", "tertiary_link"), "Tertiary road"),
    (("unclassified",), "Minor road, unclassified"),
    (("residential",), "Residential street"),
    (("service",), "Service road"),
    (("construction",), "Under construction"),
    (("track",), "Farm track"),
    (("path", "footway", "cycleway"), "Footpath"),
]
