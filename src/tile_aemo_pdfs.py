"""Crop each AEMO state PDF render into tiles for vision-model ingestion.

The full-state PNG downsamples too much when displayed to a vision model. Tiling
preserves label legibility for individual project markers.
"""
from __future__ import annotations
import json
from pathlib import Path
import fitz

ROOT = Path(__file__).parent.parent
SRC = ROOT / "data" / "inputs" / "aemo_maps"
DST = ROOT / "data" / "intermediate" / "vision_tiles"
DST.mkdir(parents=True, exist_ok=True)

# (cols, rows) per state — coarse maps get fewer tiles
TILES_PER_STATE = {
    "tas": (2, 2),
    "sa":  (2, 3),
    "vic": (3, 2),
    "nsw": (3, 2),
    "qld": (3, 3),
}


def main():
    manifest = []
    for pdf_path in sorted(SRC.glob("*-map.pdf")):
        state = pdf_path.stem.replace("-map", "")
        cols, rows = TILES_PER_STATE.get(state, (2, 2))
        doc = fitz.open(pdf_path)
        page = doc[0]
        pw, ph = page.rect.width, page.rect.height
        tw, th = pw / cols, ph / rows
        scale = 4.0  # render scale per tile
        for r in range(rows):
            for c in range(cols):
                clip = fitz.Rect(c*tw, r*th, (c+1)*tw, (r+1)*th)
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
                name = f"{state}_r{r}c{c}.png"
                out = DST / name
                pix.save(str(out))
                manifest.append({
                    "state": state.upper(),
                    "file": name,
                    "row": r, "col": c, "rows": rows, "cols": cols,
                    "page_bbox": [clip.x0, clip.y0, clip.x1, clip.y1],
                    "page_w": pw, "page_h": ph,
                    "img_w": pix.width, "img_h": pix.height,
                    "size_kb": out.stat().st_size // 1024,
                })
                print(f"  {name}  {pix.width}x{pix.height}  {out.stat().st_size//1024}KB")
        doc.close()

    (DST / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nTotal tiles: {len(manifest)}  manifest: {DST/'manifest.json'}")


if __name__ == "__main__":
    main()
