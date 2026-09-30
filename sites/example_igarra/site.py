"""Example site. Everything not stated here is derived: the UTM zone from the
site's own longitude (Igarra, at about 6.09 E, falls in zone 32N), borehole
label offsets from the station geometry, road styling and the source caption
from what OSM actually returns.

The three boreholes are SYNTHETIC. They were placed on open ground near
Igarra, about 100 m apart in a straight line, to show the tool on
basement-complex terrain. They are not survey data.
"""
from mapkit import SiteConfig, BASEMENT_COMPLEX_IGARRA

SITE = SiteConfig(
    name="example_igarra",
    subtitle="Igarra, Akoko-Edo LGA, Edo State (synthetic example boreholes)",
    state="Edo",
    geology=BASEMENT_COMPLEX_IGARRA,
    synthetic_stations=True,
)
