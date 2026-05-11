"""Apply per-PDF affine transforms to vision markers with pixel positions.

Reads:
  data/intermediate/aemo_vision_extracts_v2.json   (markers with x_pct, y_pct in [0,100])
  data/intermediate/vision_tiles/manifest.json     (tile -> page bbox)
  data/intermediate/aemo_overlays.json             (per-state affine a*y+b, c*x+d)

Writes back to the same v2 JSON with lat, lon, page_x, page_y fields on each marker.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
INTERMEDIATE = ROOT / "data" / "intermediate"
V2 = INTERMEDIATE / "aemo_vision_extracts_v2.json"
MANIFEST = INTERMEDIATE / "vision_tiles" / "manifest.json"
OVERLAYS = INTERMEDIATE / "aemo_overlays.json"


def main():
    extracts = json.loads(V2.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    overlays = json.loads(OVERLAYS.read_text(encoding="utf-8"))

    # index: tile name (without .png) -> page bbox
    tile_to_bbox: dict[str, tuple[float, float, float, float]] = {}
    for t in manifest:
        name = Path(t["file"]).stem  # e.g. 'tas_r0c0'
        tile_to_bbox[name] = tuple(t["page_bbox"])

    # state -> affine transform
    state_xform: dict[str, dict] = {}
    for ov in overlays:
        state_xform[ov["state"]] = ov["transform"]

    n_ok = n_skip = 0
    for m in extracts["markers"]:
        tile = m.get("tile")
        if tile not in tile_to_bbox:
            n_skip += 1; continue
        xpct = m.get("x_pct"); ypct = m.get("y_pct")
        if xpct is None or ypct is None:
            n_skip += 1; continue
        x0, y0, x1, y1 = tile_to_bbox[tile]
        page_x = x0 + (xpct / 100) * (x1 - x0)
        page_y = y0 + (ypct / 100) * (y1 - y0)
        st = m["state"]
        if st not in state_xform:
            n_skip += 1; continue
        t = state_xform[st]
        lat = t["a"] * page_y + t["b"]
        lon = t["c"] * page_x + t["d"]
        m["page_x"] = round(page_x, 1)
        m["page_y"] = round(page_y, 1)
        m["lat"] = round(lat, 5)
        m["lon"] = round(lon, 5)
        n_ok += 1

    V2.write_text(json.dumps(extracts, indent=2), encoding="utf-8")
    print(f"Geo-located {n_ok} markers, skipped {n_skip}")


if __name__ == "__main__":
    main()
