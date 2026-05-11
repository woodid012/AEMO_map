# NEM Generation Map

Interactive map of every generation project in the National Electricity Market — Enquiry, Application, Anticipated, Committed, Existing — with project name, capacity, owner, technology, stage, and a transmission-line base layer. Designed to be a more complete and current view than AEMO's quarterly generation map.

Open `outputs/nem_map.html` in any browser to use the map.

## What's in the box

- **1,876 projects** across NSW · VIC · QLD · SA · TAS
- **1,162 geocoded** to real coordinates (Nominatim); rest sit at region centroid
- **219 projects flagged as on the AEMO map** (text-match + vision pass)
- **12,302 transmission-line segments** ≥132 kV from OpenStreetMap
- **2,051 substations** ≥66 kV
- **5 AEMO state PDFs** rendered as togglable raster underlays (rough coastline + transmission reference)
- **Filter sidebar**: search, stage, state, capacity slider, technology, AEMO map underlay toggles, base-layer toggles
- **Dashboard tab**: live MW pipeline by stage × state, MW by technology, totals cards

## Brief mapping

| Brief layer | Source | Implementation |
| --- | --- | --- |
| 1. Application/Committed projects (capacity & stage) | AEMO state maps | Vision pass over 31 tiles → 216 markers extracted |
| 2. Committed project names | AEMO Regional Boundaries layer | `extract_aemo_pdfs.py` text match → 76 confident matches |
| 3. Broad project list (Enquiry/Application/Committed) | KCI Datafile Compiled NEM | `build_map.py` |
| 4. Stage classification (Enquiry vs Application) | NEM Generation Information Oct 2025 | `build_map.py::classify_stage` |

Stage logic per brief, with vision overlay:
- On AEMO map (text OR vision) → stage from AEMO map (Application / Committed / etc.)
- In KCI **and** NEM Gen Info but **not** on AEMO map → Application
- In KCI only → Enquiry

## Folder layout

```
map_connections/
├── README.md
├── .gitignore
├── src/                                # pipeline scripts
│   ├── pipeline.py                     # orchestrator — runs all steps in order
│   ├── build_map.py                    # KCI + NEM → projects.json (base unified table)
│   ├── extract_aemo_pdfs.py            # match AEMO PDF text → projects.json names
│   ├── render_aemo_overlays.py         # render state PDFs as georeferenced PNGs
│   ├── tile_aemo_pdfs.py               # crop state PDFs to tiles for vision review
│   ├── integrate_vision.py             # merge AEMO map vision extracts → projects.json
│   ├── geocode.py                      # Nominatim geocoder (rate-limited, cached)
│   ├── fetch_transmission_lines.py     # OSM Overpass → transmission lines + substations
│   ├── slim_transmission.py            # filter to ≥132 kV backbone, shrink coords
│   ├── build_leaflet.py                # assemble final standalone Leaflet HTML
│   └── helpers/                        # per-state vision extract scripts (replayable)
│       ├── append_vision_extracts.py
│       ├── _extract_sa.py  _extract_nsw.py  _extract_vic.py  _extract_qld.py
├── data/
│   ├── inputs/                         # raw user-supplied data
│   │   ├── KCI Datafile Compiled NEM.xlsx
│   │   ├── NEM Generation Information Oct 2025.xlsx
│   │   └── aemo_maps/                  # PDFs manually downloaded from AEMO
│   │       ├── nem_regional_boundaries.pdf
│   │       └── {nsw,vic,qld,sa,tas}-map.pdf
│   └── intermediate/                   # derived JSON / caches (rebuildable)
│       ├── projects.json               # unified table — the canonical data
│       ├── aemo_pdf_matches.json       # AEMO PDF text matches
│       ├── aemo_overlays.json          # PNG bounds for Leaflet ImageOverlay
│       ├── aemo_vision_extracts.json   # vision pass over AEMO map tiles (216 markers)
│       ├── vision_match_report.json    # how vision markers mapped to projects
│       ├── geocode_cache.json          # Nominatim cache (preserves rate-limited work)
│       ├── transmission_lines.geojson  # raw OSM dump (~15 MB)
│       ├── transmission_lines.slim.geojson  # ≥132 kV backbone (~5 MB)
│       ├── substations.geojson
│       └── vision_tiles/               # tiled state PDFs (ephemeral)
└── outputs/
    ├── nem_map.html                    # CANONICAL output (~7 MB)
    └── assets/{nsw,vic,qld,sa,tas}.png # state raster underlays referenced by HTML
```

## How to run

From the project root:

```bash
python src/pipeline.py
```

Or step-by-step (any step is rerunnable; nothing destructive):

```bash
python src/build_map.py              # 1. unified base table
python src/extract_aemo_pdfs.py      # 2. AEMO PDF text matches
python src/build_map.py              # 3. rerun so matches feed stage classification
python src/render_aemo_overlays.py   # 4. render state PDFs as raster underlays
python src/tile_aemo_pdfs.py         # 5. cut tiles for vision review
# 6. MANUAL: have Claude/GPT vision enumerate markers from each tile,
#    save to data/intermediate/aemo_vision_extracts.json. Existing extract is preserved.
python src/integrate_vision.py       # 7. merge vision into projects.json
python src/geocode.py                # 8. Nominatim ~30 min, cached
python src/fetch_transmission_lines.py  # 9. OSM Overpass, ~5 min, chunked by state
python src/slim_transmission.py      # 10. shrink to ≥132 kV
python src/build_leaflet.py          # 11. final HTML
```

## Dependencies

```bash
pip install openpyxl pdfplumber pymupdf folium
```

Standard library only otherwise (`urllib`, `json`, `re`, `pathlib`).

## Map features

**Sidebar — Filters tab**
- Text search (name / owner / location)
- Stage checkboxes (colour-coded, AEMO conventions)
- State checkboxes
- Capacity slider (MW minimum)
- Technology dropdown
- AEMO map underlay toggles (per state)
- Network base layer toggles (transmission lines, substations)
- "Only show projects on AEMO map" · "Only real-geocoded locations"

**Sidebar — Dashboard tab**
- Cards: project count, total MW, storage MWh, on-AEMO-map count
- Bar chart: MW by stage
- Table: stage × state MW pipeline
- Bar chart: MW by technology (top 10)
- All figures update live with filter changes

**Visual conventions**
- Marker colour by stage (AEMO Generation Symbols palette):
  | Stage | Colour |
  |---|---|
  | Existing | dark grey/black |
  | Committed | green |
  | Anticipated | amber |
  | Application | blue |
  | Enquiry | red |
- Marker radius ∝ log(capacity_mw)
- Transmission lines coloured by voltage (AEMO conventions: 500 kV yellow, 330 kV orange, 275 kV pink, 220 kV blue, 132 kV red, 66 kV brown)
- AEMO state PDFs render at 55% opacity as raster underlays

## Stage classification details

`src/build_map.py::classify_stage` and `src/integrate_vision.py` together apply:

| Source signal | On AEMO map? | Display stage |
| --- | --- | --- |
| NEM Gen Info `In Service` | — | Existing |
| NEM Gen Info `Committed` / `In Commissioning` | — | Committed |
| NEM Gen Info `Anticipated` | yes | Committed |
| NEM Gen Info `Anticipated` | no | Anticipated |
| NEM Gen Info `Publicly Announced` | yes | Committed |
| NEM Gen Info `Publicly Announced` | no | Application |
| NEM Gen Info `Withdrawn – Permanent` | — | Withdrawn |
| Vision pass `Operational` | — | Existing |
| Vision pass `Commissioning` / `Registration` / `Pre-Registration` | — | Committed |
| Vision pass `Application` | — | Application |
| KCI-only, NER "application to connect" | — | Application |
| KCI-only, NER "connection enquiry" | — | Enquiry |

KCI `Withdrawn` / `Cancelled` rows are dropped.

## How the vision pass works

`tile_aemo_pdfs.py` cuts each state PDF into 4–9 tiles at 4× DPI. A vision-capable LLM (Claude Opus 4.7 used here) reads each tile and enumerates every project marker, classifying:
- **Stage** by icon colour: orange Application / yellow-green Pre-Reg / green Registration / pink Commissioning / dark-blue Operational
- **Fuel** by icon shape: Wind / Solar / OCGT / Hydro / Pumped Hydro / Diesel / Coal / CCGT / Biomass / Battery / Substation
- **Capacity** from the adjacent number label
- **Nearest substation/town** from the closest text label

Each marker gets a per-field confidence rating (high/medium/low). `integrate_vision.py` matches markers to existing project records by (state, capacity ±15%, fuel-family compatibility, label-token overlap with site name or location description). 215/216 markers matched in the current run.

## Known limitations

1. **Geocoder hit rate is 62%.** Nominatim couldn't find some KCI location descriptions ("5km east of Armidale", "near ElectraNet's existing Tungkillo substation"). The rest fall back to region centroid + per-project jitter. A manual override CSV is the natural next step.
2. **AEMO PDF underlays are schematic.** Anchor-town residuals range from ~30 km (TAS, QLD) to ~125 km (SA). AEMO repositions labels for readability rather than strict geographic accuracy. Good for "where on the coast" reference, not for precise placement.
3. **Vision-extracted markers don't have real coordinates yet.** They inherit the region centroid for the matched project; the 1 unmatched marker shows at region centroid. A future enhancement is to use each PDF's affine transform to derive lat/lon from tile (x, y).
4. **Run order matters.** `build_map.py` is destructive on `projects.json`. Use `pipeline.py` to run everything in the right order, or rerun `integrate_vision.py` whenever you rerun `build_map.py`.
5. **AEMO state PDFs have many unreadable markers at tile zoom.** The Adelaide CBD cluster, Sydney metro, Latrobe Valley all have stacked markers in tight space — vision confidence on those is medium-to-low. A second pass at higher tile density would help.

## Output statistics (current run)

- 1,876 unified projects across NEM
- Stages: 521 Enquiry · 791 Application · 45 Anticipated · 64 Committed · 452 Existing · 3 Withdrawn
- Source: 320 NEM+KCI · 964 NEM only · 591 KCI only · 1 AEMO-map-only (vision)
- AEMO map flagged: 219 (76 from text + ~143 net from vision integration)
- Real-geocoded coords: 1,162 (62%)
- Vision markers extracted: 216 (215 matched to projects, 1 new pseudo)
- Transmission lines ≥132 kV: 12,302 segments
- Substations ≥66 kV: 2,051
- Final HTML size: ~6.7 MB

## Future work

- **Real coordinates from AEMO tiles.** Use the affine transform from `render_aemo_overlays.py` to convert each vision marker's tile (x, y) to lat/lon. Would put vision-only projects at their actual position.
- **Manual override CSV** for known-bad geocodes — simple sidecar file that takes precedence over Nominatim.
- **Lazy-load transmission GeoJSON** via fetch so the HTML stays small and transmission can be filtered by voltage progressively.
- **Stage colour calibration per AEMO PDF**: sample the legend colour swatches programmatically so vector-shape colours map to AEMO's published stage names deterministically.
- **CSV / Excel export** of the currently visible project set.
- **Dash app** version when filtering needs outgrow static HTML.
- **Quarterly refresh pipeline**: diff new KCI / NEM Gen Info / AEMO maps against the previous quarter, flag added or changed projects.
- **Owner / proponent grouping** view (competitive intel).
- **Improve geocoder fallbacks**: parse "Xkm of Town" patterns and offset from town centroid; tokenize site names against a town gazetteer.
