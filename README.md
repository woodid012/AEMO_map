# NEM Generation Map

Interactive map of every generation project in Australia's National Electricity Market — Enquiry, Application, Anticipated, Committed, and Existing — with project name, capacity, owner, technology, and stage. Designed to be a more complete and current view than AEMO's quarterly maps.

**Open `outputs/nem_map.html` in any browser.**

To share publicly: enable [GitHub Pages](https://github.com/woodid012/AEMO_map/settings/pages) (main branch, root folder), then your URL is `https://woodid012.github.io/AEMO_map/outputs/nem_map.html`.

## What's in the map

- **1,876 projects** across NSW · VIC · QLD · SA · TAS
- **214 markers extracted from AEMO state maps** via vision pass (icon position + capacity)
- **12,302 transmission lines (≥132 kV)** + 2,051 substations from OpenStreetMap
- **5 AEMO state PDFs TPS-warped** to real geography — coastlines + transmission line up
- **Filter sidebar**: search, stage, state, capacity slider, technology, AEMO underlay toggles
- **Dashboard tab**: live MW pipeline by stage × state, totals cards, MW by technology
- **CSV export** of the currently visible project set
- **Home + per-state zoom buttons** for navigation

## Project / data model

| Field | Source |
|---|---|
| Project name + capacity + owner + technology | KCI + NEM Generation Info Oct 2025 |
| Stage (Enquiry / Application / Anticipated / Committed / Existing) | NEM Gen Info Unit Status, KCI NER type, AEMO map vision pass |
| Real coordinates | AEMO icon position (via TPS warp) > Nominatim geocode > region centroid |
| On AEMO map flag | text matching (Regional Boundaries layer) + vision pass on state maps |

**Stage logic** (per the brief):
- On AEMO map → use the AEMO stage
- In KCI **and** NEM Gen Info but **not** on AEMO map → Application
- In KCI only → Enquiry

**Coordinate priority** (latest): AEMO icon position is canonical when the project appears on the AEMO map. Nominatim is retained as a cross-reference. This guarantees markers sit on the same lat/lon frame as the warped AEMO underlay.

## How the AEMO PDFs become geographic

AEMO publishes the state maps as **schematic PDFs** — labels are deliberately repositioned for readability. To overlay them on a real-world basemap we run a four-step warp:

1. **Anchor discovery** — match phrase text in the PDF against:
   - A hand-curated town gazetteer (Sydney, Melbourne, Brisbane, etc.)
   - OSM substation names (≥66 kV) in the state's bounding box
   This gives 9-71 anchors per state.

2. **ICP densification** — extract every transmission polyline from the PDF (classified by stroke colour → voltage), sample dense points along each, use the *current* TPS to project to real coords, snap to the nearest OSM transmission line of the same voltage. Each snapped point pair becomes an additional anchor. Iterate 3 times. Densified anchor counts:
   | State | Base | After ICP |
   |---|---|---|
   | NSW | 28 | 832 |
   | QLD | 66 | ~800 |
   | SA | 19 | 367 |
   | TAS | 21 | 216 |
   | VIC | 9 | 741 |

3. **Thin-plate spline warp** — fit a TPS through the densified anchors. TPS interpolates through every anchor and curves smoothly between them, which is the right model for AEMO's smooth-but-non-uniform schematic distortion. Final residuals are 3-8 km max in-sample across all states.

4. **Raster output** — inverse-warp each PDF into a real-geography grid (1 km/pixel near equator). Output bounds = state bbox. Markers from the same PDF are remapped through the same TPS so they stay locked to the warped underlay.

The fitted TPS coefficients are durable — converting a new page (x, y) to real (lat, lon) is microseconds after the fit. The expensive step is the fit itself (O(n³) for n anchors).

## Folder layout

```
map_connections/
├── README.md
├── .gitignore
├── src/                                # pipeline scripts (run order ↓)
│   ├── pipeline.py                     # orchestrator
│   ├── build_map.py                    # KCI + NEM → projects.json (base table)
│   ├── extract_aemo_pdfs.py            # text-match AEMO PDFs → matched names
│   ├── render_aemo_overlays.py         # initial affine render of state PDFs (legacy)
│   ├── tile_aemo_pdfs.py               # tile PDFs for vision pass
│   ├── integrate_vision.py             # merge vision extracts into projects.json
│   ├── geocode.py                      # Nominatim, rate-limited, cached
│   ├── fetch_transmission_lines.py     # OSM Overpass → transmission lines + substations
│   ├── slim_transmission.py            # filter to ≥132 kV backbone, shrink coords
│   ├── refine_aemo_alignment.py        # OSM substations + towns as anchors → affine
│   ├── warp_aemo_pdfs.py               # TPS warp PDFs → real geography raster
│   ├── icp_warp.py                     # ICP densify anchors via tx line geometry
│   ├── verify_warp.py                  # leave-one-out validation of TPS
│   ├── vision_to_coords.py             # convert vision marker tile coords → lat/lon
│   ├── build_leaflet.py                # assemble final standalone Leaflet HTML
│   └── helpers/                        # per-state vision extract scripts (replayable)
│       ├── append_vision_extracts.py + append_vision_v2.py
│       ├── _extract_{nsw,vic,qld,sa,tas}.py        # v1, no pixel positions
│       └── _extract_{nsw,vic,qld,sa,tas}_v2.py     # v2, with (x_pct, y_pct)
├── data/
│   ├── inputs/                         # user-supplied raw data
│   │   ├── KCI Datafile Compiled NEM.xlsx
│   │   ├── NEM Generation Information Oct 2025.xlsx
│   │   └── aemo_maps/                  # downloaded AEMO PDFs
│   └── intermediate/                   # derived / reproducible from inputs
│       ├── projects.json               # unified table (canonical data)
│       ├── aemo_pdf_matches.json       # AEMO Regional Boundaries text matches
│       ├── aemo_overlays.json          # per-state warp metadata + anchors
│       ├── aemo_vision_extracts.json   # v1 vision (no positions)
│       ├── aemo_vision_extracts_v2.json # v2 vision (with positions)
│       ├── vision_match_report.json    # how vision markers mapped to projects
│       ├── geocode_cache.json          # Nominatim cache (preserves rate-limited work)
│       ├── transmission_lines.geojson  # raw OSM (~15 MB)
│       ├── transmission_lines.slim.geojson # ≥132 kV backbone (~5 MB)
│       ├── substations.geojson
│       └── vision_tiles/               # tiled state PDFs + manifest
└── outputs/
    ├── nem_map.html                    # CANONICAL output (~7 MB)
    └── assets/{nsw,vic,qld,sa,tas}.png # state raster underlays (TPS-warped)
```

## How to run

From the project root:

```bash
python src/pipeline.py
```

Or step-by-step:

```bash
python src/build_map.py              # 1. unified base table
python src/extract_aemo_pdfs.py      # 2. AEMO PDF text matches
python src/build_map.py              # 3. rerun so matches feed stage classification
python src/render_aemo_overlays.py   # 4. initial PNG renders + bounds
python src/tile_aemo_pdfs.py         # 5. cut tiles for vision review
# 6. MANUAL: vision pass produces aemo_vision_extracts_v2.json with positions
python src/refine_aemo_alignment.py  # 7. OSM substation anchors → affine
python src/fetch_transmission_lines.py  # 8. OSM Overpass (slow, ~5 min)
python src/slim_transmission.py      # 9. shrink transmission for HTML
python src/icp_warp.py               # 10. ICP densify anchors using tx geometry
python src/warp_aemo_pdfs.py         # 11. TPS warp PDFs to real geography
python src/integrate_vision.py       # 12. merge vision into projects.json
python src/geocode.py                # 13. Nominatim ~30 min, cached (optional)
python src/build_leaflet.py          # 14. final HTML
```

## Dependencies

```bash
pip install openpyxl pdfplumber pymupdf folium scipy numpy Pillow shapely
```

The pipeline uses standard library `urllib` for Overpass + Nominatim calls.

## Map UI features

**Filters tab**
- Text search (name / owner / location)
- Stage checkboxes (AEMO colour-coded)
- State checkboxes
- Capacity slider (MW minimum)
- Technology dropdown
- AEMO map underlay toggles (per state)
- Network base layer toggles (transmission lines, substations)
- "Only show projects on AEMO map" · "Only real-geocoded locations"

**Dashboard tab**
- Cards: project count, total MW, storage MWh, on-AEMO-map count
- Bar chart: MW by stage
- Table: stage × state MW pipeline
- Bar chart: MW by technology (top 10)
- All figures update live with filter changes

**Navigation**
- Home button (⌂) — reset to NEM-wide view
- Per-state zoom buttons (NSW / VIC / QLD / SA / TAS)
- `maxBounds` clamp keeps you within the NEM region

**Visual conventions**
- Marker colour by stage (AEMO Generation Symbols palette: Existing dark, Committed green, Anticipated amber, Application blue, Enquiry red)
- Marker radius ∝ log(capacity_mw)
- Transmission lines coloured by voltage (500 kV yellow → 66 kV brown)
- AEMO state PDFs render at 55% opacity as raster underlays

## How the vision pass works

`tile_aemo_pdfs.py` cuts each state PDF into 4-9 tiles at 4× DPI. A vision-capable LLM (Claude Opus 4.7 used here) reads each tile and enumerates every project marker:

- **Stage** from icon colour: orange Application / yellow-green Pre-Reg / green Registration / pink Commissioning / dark-blue Operational
- **Fuel** from icon shape: Wind / Solar / OCGT / Hydro / Pumped Hydro / Diesel / Coal / CCGT / Biomass / Battery / Substation
- **Capacity** from the adjacent number label
- **Pixel position** within the tile (x_pct, y_pct in [0, 100])
- **Nearest substation/town** from the closest text label

Each marker gets per-field confidence. `vision_to_coords.py` converts (x_pct, y_pct) → page coords → lat/lon via the per-state TPS. `integrate_vision.py` matches markers to project records by (state, capacity ±15%, fuel-family compatibility, label-token overlap). 214/214 markers matched in the current run.

## Honest limitations

1. **Geocoder hit rate is 62%.** Nominatim couldn't find some KCI location descriptions ("5km east of Armidale", "near ElectraNet's existing Tungkillo substation"). Those projects fall back to region centroid. Workarounds (not yet implemented): snap-to-substation when description mentions one, parse "Xkm of Town" patterns, or maintain a manual override CSV.

2. **The TPS warp is mathematically real but imperfect.** Leave-one-out residuals (excluding the held-out anchor): TAS 6 km median, NSW 14 km, QLD 16 km, SA 16 km, **VIC 33 km** (before ICP densification). After ICP with 200-800 anchors per state, in-sample fit is < 8 km max — but the warp can only be as good as its references (OSM transmission line accuracy + AEMO labels matching OSM names).

3. **AEMO maps are schematic.** They were never designed to be geographic. The warp forces them into real-world coordinates which is useful for overlay, but a purist would say AEMO's drawing represents *topology* (which-project-at-which-substation), not coordinates. Use AEMO's data files for technical work; use this map for *spatial overview*.

4. **OSM transmission data isn't perfect either.** Coverage of the major 220+ kV backbone is excellent; some 132 kV lines are missing or mis-tagged. The warp aligns AEMO to OSM, so if OSM is slightly wrong, AEMO inherits the same error.

5. **Run order matters.** `build_map.py` rewrites `projects.json` from scratch. If you've run the vision integration or geocoding, those overlays must be replayed in the right order. `pipeline.py` handles this; bare reruns of `build_map.py` will wipe vision flags until `integrate_vision.py` reruns.

## Output statistics (current run)

- 1,876 unified projects across NEM
- Stages: 521 Enquiry · 791 Application · 45 Anticipated · 64 Committed · 452 Existing · 3 Withdrawn
- Source: 320 NEM+KCI · 964 NEM only · 591 KCI only · 1 AEMO-map-only (vision)
- AEMO map flagged: 220
- Real coordinates: 1,162 Nominatim + 172 AEMO icon position = 1,334 (71%)
- Vision markers extracted: 214 (all matched)
- Transmission segments ≥132 kV: 12,302
- Substations ≥66 kV: 2,051
- Final HTML size: ~7 MB

## Roadmap

**High-value next steps:**
- **Snap-to-substation** geocoding fallback for KCI descriptions mentioning known substations
- **"Xkm of Town"** regex parser to handle the bulk of KCI location patterns
- **Manual coord override CSV** (`data/inputs/coord_overrides.csv`) for known-bad geocodes
- **Lazy-load transmission GeoJSON** via fetch — shrinks HTML from 7 MB to ~1 MB
- **Quarterly refresh pipeline**: diff new KCI / NEM Gen Info releases, flag added or changed projects
- **Second vision pass at higher tile resolution** for dense metros (Adelaide CBD, Sydney metro, Latrobe Valley)

**Strategic:**
- **Dash app** when filtering needs outgrow static HTML
- **Owner / proponent grouping** view for competitive intel
- **Diff vs previous quarter** showing new / removed projects

**Quality / governance:**
- Serialise fitted TPS coefficients to `.npz` so future scripts can transform points without refitting
- Add "as at" timestamps and source dates to the map
- Project name normalization rules (handle "Stage 1" / "Stage 2" splits, hybrid sites)
