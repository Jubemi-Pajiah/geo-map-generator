"""What a site is: the small bundle of facts that actually differ between them.

Everything a site does NOT declare is derived -- from its own coordinates where
possible, from a shared default otherwise. The point is that adding a site
should mean writing down what is true about that place, not re-tuning a
pipeline. See sites/<name>/site.py for how short that ends up being.
"""
from dataclasses import dataclass, field, replace
from pathlib import Path

from .env import utm_epsg_for

ROOT = Path(__file__).resolve().parent.parent
SITES_DIR = ROOT / "sites"


# --------------------------------------------------------------------------
# Lithology
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Unit:
    """One band in the cross-section. Depths are metres below ground surface."""
    name: str
    top: float
    base: float
    color: str
    hatch: str


@dataclass(frozen=True)
class Geology:
    """A generalized, regionally-published lithostratigraphy.

    Named `label`/`legend` rather than carrying the formation name alone
    because the map prints all three differently: `label` is the big watermark
    letters on the map face, `legend` the legend row, `formation` the phrase in
    the cross-section's source note.
    """
    label: str
    formation: str
    legend: str
    color: str
    units: tuple
    section_depth: float
    #: Source note printed under the cross-section title.
    source: str
    #: Fill pattern for the surface-geology polygon and its legend key. Dots
    #: read as sand; crystalline basement wants something else.
    hatch: str = "....."
    #: What the section is based on, printed under its title. None = the
    #: default "regional lithostratigraphy of the <formation>" wording, which
    #: suits a sedimentary sequence but not a basement weathering profile.
    section_basis: str = None


BENIN_FORMATION = Geology(
    label="Bf",
    formation="Benin Formation",
    legend="Bf - Benin Formation (coastal plain sands, generalized)",
    color="#eddca3",
    section_depth=45.0,
    source=("Benin Formation (Miocene-Recent coastal plain sands), after "
            "published Edo/Delta State lithostratigraphic studies"),
    units=(
        Unit("Topsoil / lateritic clayey sand", 0.0, 3.0, "#b5651d", "xx"),
        Unit("Sandy clay / clayey sand", 3.0, 12.0, "#c2b280", ".."),
        Unit("Fine-to-medium sand", 12.0, 24.0, "#e5d07a", "//"),
        Unit("Medium-to-coarse sand (main aquifer unit)", 24.0, 45.0, "#f7e26b", "..."),
    ),
)

OGWASHI_ASABA_FORMATION = Geology(
    label="Oa",
    formation="Ogwashi-Asaba Formation",
    legend="Oa - Ogwashi-Asaba Formation (variegated clays and sands, generalized)",
    color="#e2d09b",
    section_depth=60.0,
    source=("Ogwashi-Asaba Formation (Oligocene-Miocene variegated clays, "
            "lignitic and coarse cross-bedded sands), after published "
            "southern Nigeria lithostratigraphic studies"),
    units=(
        Unit("Lateritic topsoil / reddish-brown clayey sand", 0.0, 4.0, "#b5651d", "xx"),
        Unit("Variegated (mottled) clay and sandy clay", 4.0, 18.0, "#a98467", "//"),
        Unit("Fine-to-medium sand with clay interbeds", 18.0, 36.0, "#ddc98a", ".."),
        Unit("Coarse to gritty sand with lignite streaks", 36.0, 60.0, "#f2e08a", "..."),
    ),
)

#: Crystalline basement around Igarra, Edo State: the Igarra schist belt of the
#: Nigerian Basement Complex, with Pan-African granitoid intrusions. This is a
#: DRAFT. The section is a generalized tropical weathering profile (overburden
#: and regolith over fresh rock), which is the usual way basement terrain is
#: summarised in the hydrogeological literature. The thicknesses are
#: illustrative round numbers, not measured and not taken from one borehole.
BASEMENT_COMPLEX_IGARRA = Geology(
    label="Bc",
    # TODO: confirm with Jubemi -- formation wording for the Igarra area.
    formation="Basement Complex (Igarra schist belt)",
    # TODO: confirm with Jubemi -- surface rock types listed in the legend.
    legend=("Bc - Basement Complex: schists, gneisses, quartzites and "
            "granitoids (generalized)"),
    color="#e8c4b8",
    hatch="++",
    # TODO: confirm with Jubemi -- section depth drawn below the collars.
    section_depth=40.0,
    # TODO: confirm with Jubemi -- regional description and its sources.
    source=("Basement Complex of the Igarra schist belt (Precambrian schists, "
            "gneisses, quartzites and marble, with Pan-African granitoids), "
            "after published regional geological mapping of the Igarra area. "
            "Section is a generalized weathering profile, not measured"),
    section_basis="a generalized basement weathering profile (not measured)",
    units=(
        # TODO: confirm with Jubemi -- unit name and 0-2 m thickness.
        Unit("Topsoil / lateritic overburden", 0.0, 2.0, "#b5651d", "xx"),
        # TODO: confirm with Jubemi -- unit name and 2-12 m thickness.
        Unit("Highly weathered regolith (clayey saprolite)", 2.0, 12.0, "#c9a27e", "//"),
        # TODO: confirm with Jubemi -- unit name and 12-20 m thickness.
        Unit("Partly weathered / fractured basement (saprock)", 12.0, 20.0, "#b89a9a", "\\\\"),
        # TODO: confirm with Jubemi -- unit name and 20-40 m thickness.
        Unit("Fresh basement rock (undifferentiated)", 20.0, 40.0, "#d9a3a3", "++"),
    ),
)


# --------------------------------------------------------------------------
# Site
# --------------------------------------------------------------------------
@dataclass
class SiteConfig:
    """One survey site. Only `name`, `subtitle`, `state` and `geology` are
    genuinely required; the rest have defaults or are derived at load time."""

    name: str
    subtitle: str
    state: str
    geology: Geology

    #: Station file, relative to the site folder. Plain-text GPS exports and
    #: .xlsx survey sheets are both handled; see mapkit.stations.
    stations_file: str = "coords.txt"

    #: True when the stations are made-up example points rather than survey
    #: data. Every map then says so in its legend and caption, so a sample
    #: figure cannot be mistaken for a real survey.
    synthetic_stations: bool = False

    # --- map extents (metres of buffer around the station convex hull) -----
    study_buffer_m: float = 350.0
    geologic_buffer_m: float = 1400.0
    location_buffer_m: float = 450.0

    # --- named features to label (None = this site has none; nothing is
    #     substituted, and the legend omits the key rather than showing a
    #     symbol that never appears) ---------------------------------------
    main_road_name: str = None
    construction_road_name: str = None
    river_name: str = None

    # --- cross-section ----------------------------------------------------
    #: None = choose one from the real relief so the section box comes out
    #: roughly square. See resolved_vertical_exaggeration.
    vertical_exaggeration: float = None
    contour_interval_m: float = 1.0

    # --- overrides; leave empty to auto-derive from station geometry ------
    detail_label_offsets: dict = field(default_factory=dict)
    station_label_offsets: dict = field(default_factory=dict)
    end_label_offsets: dict = field(default_factory=dict)
    main_end_label_offsets: dict = field(default_factory=dict)

    #: Extra source-note lines appended to every figure's caption.
    extra_notes: tuple = ()

    #: Set only to override the derived UTM zone; normally leave it alone.
    utm_epsg: str = None

    # --- filled in by load() ---------------------------------------------
    folder: Path = None

    # -------------------------------------------------------------- paths --
    @property
    def data_dir(self):
        d = self.folder / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def output_dir(self):
        d = self.folder / "output"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def stations_path(self):
        return self.folder / self.stations_file

    # ------------------------------------------------------------ derived --
    @property
    def osm_fetch_buffer_m(self):
        """One bbox for every OSM layer, sized to the WIDEST map drawn.

        Keying the cache to each map's own extent is a trap: the maps share
        cache filenames, so whichever ran first won. On a clean run that was
        the location map with its ~1 km site panel, and the geologic map then
        silently reused that narrow cache and lost the named roads that are the
        entire reason its frame is wider. One bbox makes the result independent
        of map order, and costs fewer calls to the flaky public Overpass
        instances rather than more.
        """
        return max(self.study_buffer_m, self.geologic_buffer_m,
                   self.location_buffer_m)

    def borehole_label(self, station):
        """Legend text for one station, flagged when the data are synthetic."""
        if self.synthetic_stations:
            return f"Example borehole {station} (synthetic)"
        return f"Borehole {station}"

    @property
    def station_source_note(self):
        """Caption phrase saying where the borehole positions came from."""
        if self.synthetic_stations:
            return ("Boreholes: SYNTHETIC example points for demonstration, "
                    "not survey data")
        return "Borehole coordinates and elevations: field GPS"

    def resolve_crs(self, lon, lat):
        """UTM CRS for this site: declared if overridden, else derived."""
        return self.utm_epsg or utm_epsg_for(lon, lat)

    def resolved_vertical_exaggeration(self, traverse_m, relief_m):
        """Pick a vertical exaggeration that renders the section near-square.

        Hand-set exaggeration is one of the easiest things to get wrong when
        copying a site: too much turns real relief into a sheer cliff with the
        lithology squeezed into a sliver, too little flattens it to a line. The
        section box is `traverse_m` wide and `relief + section_depth` tall, so
        the factor that squares it is just the ratio -- snapped to a friendly
        number and clamped so it never caricatures genuinely steep ground.

        For example, a steep traverse with 45 m of fall over 100 m lands on x1
        (it is already steep), and a flat one with 10 m over 300 m on x5
        (otherwise the relief would be invisible).
        """
        if self.vertical_exaggeration is not None:
            return self.vertical_exaggeration
        height = max(relief_m, 1e-6) + self.geology.section_depth
        if height <= 0 or traverse_m <= 0:
            return 1
        ideal = traverse_m / height
        for candidate in (1, 2, 3, 5, 6, 8, 10):
            if ideal <= candidate * 1.5:
                return candidate
        return 10


def load(name):
    """Import sites/<name>/site.py and return its SITE, with folder attached."""
    import importlib.util

    folder = SITES_DIR / name
    site_py = folder / "site.py"
    if not site_py.exists():
        raise FileNotFoundError(f"No site definition at {site_py}")

    spec = importlib.util.spec_from_file_location(f"_site_{name}", site_py)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    site = module.SITE
    if site.name != name:
        raise ValueError(f"{site_py} declares name={site.name!r}, expected {name!r}")
    return replace(site, folder=folder)


def available():
    """Every site folder carrying a site.py, in alphabetical order."""
    if not SITES_DIR.is_dir():
        return []
    return sorted(p.name for p in SITES_DIR.iterdir() if (p / "site.py").exists())
