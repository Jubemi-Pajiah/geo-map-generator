r"""Render site maps.

    .venv\Scripts\python.exe make_maps.py example_igarra
    .venv\Scripts\python.exe make_maps.py site_a site_b
    .venv\Scripts\python.exe make_maps.py --all
    .venv\Scripts\python.exe make_maps.py example_igarra --only geologic
    .venv\Scripts\python.exe make_maps.py --list

Outputs land in sites/<name>/output/. Intermediate downloads are cached in
sites/<name>/data/ and reused, so re-running to tune the cartography costs no
network traffic; delete that folder to force a genuinely clean rebuild.
"""
import argparse
import sys
import traceback

import mapkit


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Build study-area, geologic and location maps for a survey site.")
    ap.add_argument("sites", nargs="*", help="site names (folders under sites/)")
    ap.add_argument("--all", action="store_true", help="build every site")
    ap.add_argument("--list", action="store_true", help="list known sites and exit")
    ap.add_argument("--only", nargs="+", choices=mapkit.MAP_BUILDERS,
                    default=list(mapkit.MAP_BUILDERS),
                    help="build only these maps (default: all three)")
    args = ap.parse_args(argv)

    known = mapkit.available()
    if args.list:
        print("Known sites:")
        for name in known:
            site = mapkit.load(name)
            print(f"  {name:12s} {site.subtitle}")
        return 0

    names = known if args.all else args.sites
    if not names:
        ap.error("name at least one site, or pass --all (see --list)")

    unknown = [n for n in names if n not in known]
    if unknown:
        ap.error(f"unknown site(s): {', '.join(unknown)}. Known: {', '.join(known)}")

    # One site failing must not abandon the rest -- a full run is long, and the
    # usual cause is a transient Overpass outage on one site's fetch.
    failed = []
    for name in names:
        try:
            mapkit.build_site(name, maps=tuple(args.only))
        except Exception:
            failed.append(name)
            print(f"!! {name} FAILED:", file=sys.stderr)
            traceback.print_exc()

    built = [n for n in names if n not in failed]
    print(f"\nBuilt {len(built)}/{len(names)} site(s): {', '.join(built) or '-'}")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
