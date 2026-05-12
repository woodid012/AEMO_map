"""Orchestrate the full data pipeline in dependency order.

Usage:
    python src/pipeline.py            # full run
    python src/pipeline.py --skip-geocode  # skip the ~30 min Nominatim call
    python src/pipeline.py --skip-transmission  # skip OSM fetch
    python src/pipeline.py --no-vision  # skip vision-integration step (needs prior aemo_vision_extracts.json)

Order (each step writes only files it owns; nothing is overwritten by a later step):
  1. build_map.py              KCI + NEM Gen Info -> projects.json (base)
  2. extract_aemo_pdfs.py      AEMO PDF text -> aemo_pdf_matches.json
  3. build_map.py (re-run)     pulls in aemo_pdf_matches -> projects.json
  4. render_aemo_overlays.py   state PDFs -> outputs/assets/{state}.png + aemo_overlays.json
  5. tile_aemo_pdfs.py         state PDFs -> data/intermediate/vision_tiles/*  (for vision review)
  6. (manual)                  Claude vision -> aemo_vision_extracts.json
  7. integrate_vision.py       merges vision extracts into projects.json
  8. geocode.py                Nominatim -> real lat/lon
  9. fetch_transmission_lines.py  OSM Overpass -> transmission_lines.geojson + substations.geojson
 10. slim_transmission.py      shrink to ≥132 kV backbone
 11. build_leaflet.py          assemble outputs/nem_map.html

Steps 6 (vision) is the one human-in-the-loop step. The helpers/_extract_*.py
files are the assistant's per-state outputs and can be replayed with:
    python src/helpers/_extract_sa.py    (etc.)
"""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"


def run(script: str, *args: str) -> None:
    cmd = [sys.executable, str(SRC / script), *args]
    print(f"\n=== {script} ===")
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f"{script} failed ({r.returncode})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-geocode", action="store_true")
    ap.add_argument("--skip-transmission", action="store_true")
    ap.add_argument("--no-vision", action="store_true",
                    help="Skip integrate_vision (use only if vision extracts haven't been produced).")
    args = ap.parse_args()

    run("build_map.py")
    run("extract_aemo_pdfs.py")
    run("build_map.py")        # rerun so AEMO map presence feeds stage classification
    run("render_aemo_overlays.py")
    run("tile_aemo_pdfs.py")

    extracts = ROOT / "data" / "intermediate" / "aemo_vision_extracts.json"
    if not args.no_vision and extracts.exists():
        run("integrate_vision.py")
    else:
        print(f"\n(skipping integrate_vision: extracts={'present' if extracts.exists() else 'missing'}, --no-vision={args.no_vision})")

    if not args.skip_geocode:
        run("geocode.py")
    else:
        print("\n(skipping geocode)")

    # Fallback geocoder runs every time — fills gaps from substation snap, town
    # offsets, offshore zones, address parsing, manual overrides.
    run("fallback_geocoder.py")

    if not args.skip_transmission:
        run("fetch_transmission_lines.py")
        run("slim_transmission.py")
    else:
        print("\n(skipping transmission fetch)")

    run("build_leaflet.py")
    print("\nDone. Open outputs/nem_map.html in a browser.")


if __name__ == "__main__":
    main()
