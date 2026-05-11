"""Warp AEMO state PDFs to real geography using a thin-plate spline (TPS).

Inputs:
  data/intermediate/aemo_overlays.json    (per-state anchors + raw bounds)
  data/inputs/aemo_maps/{state}-map.pdf   (source PDF)

Outputs:
  outputs/assets/{state}.png              (overwritten - warped raster)
  data/intermediate/aemo_overlays.json    (updated bounds = state bbox)

Approach:
  1. Render the AEMO PDF at high DPI to get a source raster.
  2. Take all anchor pairs (page_x, page_y) <-> (real lat, real lon).
  3. Fit a thin-plate spline RBF that maps real (lon, lat) -> page (x, y).
  4. Create an output canvas covering the state's real bbox at a grid resolution.
  5. For each output pixel (lon, lat) compute the source (page x, y) via TPS,
     then sample the source image at that location.
  6. Save the warped image; its bounds in lat/lon are exactly the state bbox.

This is inverse warping: we walk the output and pull from the source.
Result: coastlines and transmission lines in the AEMO drawing line up with
real geography to within the anchor-fitting error.

Note: TPS extrapolates poorly outside the convex hull of anchors. We fill
the no-source regions with a soft white so they don't dominate the view.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.interpolate import RBFInterpolator
from scipy.ndimage import map_coordinates
import fitz

ROOT = Path(__file__).parent.parent
PDFS = ROOT / "data" / "inputs" / "aemo_maps"
OVERLAYS_PATH = ROOT / "data" / "intermediate" / "aemo_overlays.json"
EXTRACTS_V2 = ROOT / "data" / "intermediate" / "aemo_vision_extracts_v2.json"
TILES_MANIFEST = ROOT / "data" / "intermediate" / "vision_tiles" / "manifest.json"
OUT_DIR = ROOT / "outputs" / "assets"
OUT_DIR.mkdir(parents=True, exist_ok=True)

STATE_PDF_STEM = {"NSW":"nsw-map","VIC":"vic-map","QLD":"qld-map","SA":"sa-map","TAS":"tas-map"}

# Target output bounding box per state (s, n, w, e) - generous so we don't crop transmission
STATE_OUT_BBOX = {
    "NSW": (-37.5, -28.0, 140.9, 153.7),
    "VIC": (-39.3, -33.9, 140.9, 150.0),
    "QLD": (-29.5, -10.0, 137.9, 154.0),
    "SA":  (-38.5, -25.9, 129.0, 141.1),
    "TAS": (-43.7, -39.5, 144.5, 148.5),
}

OUT_PIXELS_PER_DEG = 80   # ~1 km/pixel near the equator; smaller -> faster, larger -> sharper


def render_pdf_to_array(pdf_path: Path, scale: float = 3.0) -> tuple[np.ndarray, float, float]:
    doc = fitz.open(pdf_path)
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[..., :3]
    page_w, page_h = page.rect.width, page.rect.height
    doc.close()
    return img, page_w, page_h


def warp_one(state: str, overlay: dict, markers: list[dict] | None, tile_bbox: dict | None) -> dict:
    pdf = PDFS / f"{STATE_PDF_STEM[state]}.pdf"
    if not pdf.exists():
        print(f"  {state}: missing PDF")
        return overlay

    anchors = overlay.get("anchors_used", [])
    if len(anchors) < 4:
        print(f"  {state}: too few anchors ({len(anchors)})")
        return overlay

    print(f"\n{state}: {len(anchors)} anchors")
    src, page_w, page_h = render_pdf_to_array(pdf, scale=3.0)
    src_h, src_w = src.shape[:2]
    img_scale = src_w / page_w  # pixels per page unit
    print(f"  source: {src_w}x{src_h}")

    # anchor real (lon, lat) -> page (x, y)
    real = np.array([[a["lon"], a["lat"]] for a in anchors])  # (n, 2)
    page = np.array([[a["x"] * img_scale, a["y"] * img_scale] for a in anchors])  # (n, 2)

    # Fit TPS (one per output channel: page_x and page_y) for inverse warping.
    rbf_x = RBFInterpolator(real, page[:, 0], kernel="thin_plate_spline", smoothing=2.0)
    rbf_y = RBFInterpolator(real, page[:, 1], kernel="thin_plate_spline", smoothing=2.0)
    # Forward TPS (page page-units -> real lon/lat) for transforming markers
    page_units = page / img_scale  # back to page units, not image pixels
    rbf_lon = RBFInterpolator(page_units, real[:, 0], kernel="thin_plate_spline", smoothing=2.0)
    rbf_lat = RBFInterpolator(page_units, real[:, 1], kernel="thin_plate_spline", smoothing=2.0)

    # Output grid
    s, n, w, e = STATE_OUT_BBOX[state]
    out_w = int(round((e - w) * OUT_PIXELS_PER_DEG))
    out_h = int(round((n - s) * OUT_PIXELS_PER_DEG))
    print(f"  output: {out_w}x{out_h}  bbox S{s:.2f} N{n:.2f} W{w:.2f} E{e:.2f}")

    lons = np.linspace(w, e, out_w)
    lats = np.linspace(n, s, out_h)  # north at top
    lon_g, lat_g = np.meshgrid(lons, lats)
    query = np.column_stack([lon_g.ravel(), lat_g.ravel()])

    src_x = rbf_x(query).reshape(out_h, out_w)
    src_y = rbf_y(query).reshape(out_h, out_w)

    # Mask regions outside the source image (TPS extrapolation gone wild)
    mask = (src_x >= 0) & (src_x < src_w) & (src_y >= 0) & (src_y < src_h)

    # Sample each channel
    warped = np.full((out_h, out_w, 4), 255, dtype=np.uint8)  # RGBA, default white+opaque
    for ch in range(3):
        sampled = map_coordinates(
            src[..., ch], [src_y.ravel(), src_x.ravel()],
            order=1, mode="constant", cval=255,
        ).reshape(out_h, out_w)
        warped[..., ch] = sampled
    # Alpha: transparent where outside source
    alpha = np.where(mask, 255, 0).astype(np.uint8)
    warped[..., 3] = alpha

    out_path = OUT_DIR / f"{state.lower()}.png"
    Image.fromarray(warped).save(out_path, optimize=True)
    print(f"  wrote {out_path.name} ({out_path.stat().st_size//1024} KB)")

    # Remap markers through the same TPS so they stay locked to the warped underlay.
    if markers is not None and tile_bbox is not None:
        remapped = 0
        for m in markers:
            if m.get("state") != state: continue
            tile = m.get("tile")
            if tile not in tile_bbox: continue
            xpct = m.get("x_pct"); ypct = m.get("y_pct")
            if xpct is None or ypct is None: continue
            x0, y0, x1, y1 = tile_bbox[tile]
            px = x0 + (xpct/100) * (x1 - x0)
            py = y0 + (ypct/100) * (y1 - y0)
            q = np.array([[px, py]])
            new_lon = float(rbf_lon(q)[0])
            new_lat = float(rbf_lat(q)[0])
            m["page_x"] = round(px, 1)
            m["page_y"] = round(py, 1)
            m["lat"] = round(new_lat, 5)
            m["lon"] = round(new_lon, 5)
            m["coord_method"] = "tps"
            remapped += 1
        print(f"  remapped {remapped} markers via TPS")

    overlay = dict(overlay)
    overlay["image"] = f"assets/{state.lower()}.png"
    overlay["bounds"] = [[s, w], [n, e]]
    overlay["warp_method"] = "thin_plate_spline"
    overlay["warp_anchors"] = len(anchors)
    return overlay


def main():
    overlays = json.loads(OVERLAYS_PATH.read_text(encoding="utf-8"))

    # Load v2 markers + tile bboxes for marker remapping
    markers = None
    tile_bbox = None
    if EXTRACTS_V2.exists() and TILES_MANIFEST.exists():
        ev2 = json.loads(EXTRACTS_V2.read_text(encoding="utf-8"))
        markers = ev2.get("markers", [])
        manifest = json.loads(TILES_MANIFEST.read_text(encoding="utf-8"))
        tile_bbox = {Path(t["file"]).stem: tuple(t["page_bbox"]) for t in manifest}

    new = []
    for ov in overlays:
        st = ov.get("state")
        if st not in STATE_PDF_STEM:
            new.append(ov); continue
        new.append(warp_one(st, ov, markers, tile_bbox))
    OVERLAYS_PATH.write_text(json.dumps(new, indent=2), encoding="utf-8")
    print(f"\nUpdated {OVERLAYS_PATH}")

    if markers is not None:
        ev2["markers"] = markers
        EXTRACTS_V2.write_text(json.dumps(ev2, indent=2), encoding="utf-8")
        print(f"Updated {EXTRACTS_V2}")


if __name__ == "__main__":
    main()
