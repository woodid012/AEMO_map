"""
Build a standalone Leaflet HTML map with:
  - Filter sidebar (stage, state, technology, capacity range, search)
  - AEMO PDF underlays as toggleable raster layers (per state)
  - AEMO-style colour legend
  - Project markers sized by capacity, coloured by stage

Inputs (run order):
  build_map.py            -> projects.json
  render_aemo_overlays.py -> aemo_overlays.json + assets/{state}.png
  geocode.py              -> updates projects.json with real lat/lon

Output:
  nem_map.html  (self-contained except for Leaflet CDN + assets/*.png paths)
"""

from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent
INTERMEDIATE = ROOT / "data" / "intermediate"
OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(parents=True, exist_ok=True)

STAGE_COLOUR = {
    "Existing":    "#1f2937",
    "Committed":   "#16a34a",
    "Anticipated": "#f59e0b",
    "Application": "#2563eb",
    "Enquiry":     "#dc2626",
    "Withdrawn":   "#9ca3af",
    "Unknown":     "#6b7280",
}
STAGE_ORDER = ["Existing", "Committed", "Anticipated", "Application", "Enquiry", "Withdrawn", "Unknown"]
STATES = ["NSW", "VIC", "QLD", "SA", "TAS"]


def main():
    projects = json.loads((INTERMEDIATE / "projects.json").read_text(encoding="utf-8"))
    overlays_path = INTERMEDIATE / "aemo_overlays.json"
    overlays = json.loads(overlays_path.read_text(encoding="utf-8")) if overlays_path.exists() else []
    # prefer slim ≥132 kV version if present (much smaller)
    tx_slim = INTERMEDIATE / "transmission_lines.slim.geojson"
    tx_full = INTERMEDIATE / "transmission_lines.geojson"
    tx_path = tx_slim if tx_slim.exists() else tx_full
    transmission = json.loads(tx_path.read_text(encoding="utf-8")) if tx_path.exists() else {"type":"FeatureCollection","features":[]}
    sub_path = INTERMEDIATE / "substations.geojson"
    substations = json.loads(sub_path.read_text(encoding="utf-8")) if sub_path.exists() else {"type":"FeatureCollection","features":[]}

    # collect technologies for filter
    techs = sorted({(p.get("technology") or "Other").strip() or "Other" for p in projects})

    # compress projects to needed fields to keep HTML small
    slim = []
    for p in projects:
        if p.get("lat") is None or p.get("lon") is None:
            continue
        slim.append({
            "n": p.get("site_name", ""),
            "s": p.get("stage", "Unknown"),
            "r": p.get("region", ""),
            "st": p.get("state", ""),
            "t": (p.get("technology") or "Other").strip() or "Other",
            "f": p.get("fuel", ""),
            "o": p.get("owner", ""),
            "c": p.get("capacity_mw") or 0,
            "mwh": p.get("storage_mwh"),
            "loc": p.get("location_desc", ""),
            "src": p.get("source", ""),
            "aemo": bool(p.get("on_aemo_map")),
            "g": bool(p.get("geocoded")),
            "lat": p["lat"], "lon": p["lon"],
        })

    cap_max = max((p["c"] for p in slim if p["c"]), default=1000)

    data_js = json.dumps({
        "projects": slim,
        "overlays": overlays,
        "transmission": transmission,
        "substations": substations,
        "stages": STAGE_ORDER,
        "stageColour": STAGE_COLOUR,
        "states": STATES,
        "techs": techs,
        "capMax": cap_max,
    })

    html = HTML_TEMPLATE.replace("__DATA__", data_js)
    out = OUTPUTS / "nem_map.html"
    out.write_text(html, encoding="utf-8")
    print(f"Wrote {out}  ({len(slim)} markers, {len(overlays)} overlays)")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>NEM Generation Map</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  html,body { margin:0; padding:0; height:100%; font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  #app { display:flex; height:100%; }
  #sidebar {
    width: 340px; flex-shrink:0; height:100%; display:flex; flex-direction:column;
    background:#f8fafc; border-right:1px solid #e2e8f0; box-sizing:border-box;
  }
  #sidebar-header { padding:14px 16px 0; }
  #sidebar-tabs { display:flex; gap:0; border-bottom:1px solid #e2e8f0; margin-top:10px; }
  #sidebar-tabs button {
    flex:1; padding:8px 10px; font-size:12px; background:none; border:none; border-bottom:2px solid transparent;
    cursor:pointer; color:#64748b;
  }
  #sidebar-tabs button.active { color:#0f172a; border-bottom-color:#0f172a; font-weight:600; }
  .tab-panel { flex:1; overflow-y:auto; padding:12px 16px 24px; display:none; box-sizing:border-box; }
  .tab-panel.active { display:block; }
  #map { flex:1; }
  h1 { font-size:15px; margin:0 0 4px; }
  h2 { font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:#475569; margin:14px 0 6px; }
  .meta { color:#64748b; font-size:11px; margin-bottom:8px; }
  .row { display:flex; align-items:center; gap:6px; font-size:12px; margin:2px 0; cursor:pointer; }
  .row input[type=checkbox] { margin:0; }
  .swatch { display:inline-block; width:10px; height:10px; border-radius:50%; }
  .count { color:#94a3b8; font-size:10px; margin-left:auto; }
  input[type=search], select, input[type=range] {
    width: 100%; box-sizing:border-box; padding:5px 7px; font-size:12px;
    border:1px solid #cbd5e1; border-radius:4px; background:white;
  }
  #search { margin-bottom:4px; }
  .range-row { display:flex; align-items:center; gap:6px; font-size:11px; color:#475569; }
  .range-row input { flex:1; }
  .legend-block { display:flex; align-items:center; gap:6px; font-size:11px; margin:2px 0; }
  .pill { display:inline-block; padding:1px 6px; font-size:10px; border-radius:8px; background:#e2e8f0; color:#334155; }
  details summary { cursor:pointer; font-size:11px; color:#475569; outline:none; padding:2px 0; }
  details > div { padding:2px 0 6px 4px; }
  button.reset { font-size:11px; padding:3px 8px; border:1px solid #cbd5e1; background:white; border-radius:4px; cursor:pointer; color:#334155; }
  button.reset:hover { background:#f1f5f9; }
  /* Dashboard */
  .stat-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:14px; }
  .stat-card { background:white; border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px; }
  .stat-card .v { font-size:18px; font-weight:600; color:#0f172a; }
  .stat-card .l { font-size:10px; color:#64748b; text-transform:uppercase; letter-spacing:.04em; }
  .pipeline-table { width:100%; border-collapse:collapse; font-size:11px; }
  .pipeline-table th, .pipeline-table td { text-align:right; padding:4px 6px; border-bottom:1px solid #f1f5f9; }
  .pipeline-table th:first-child, .pipeline-table td:first-child { text-align:left; }
  .pipeline-table thead th { color:#64748b; font-weight:500; font-size:10px; text-transform:uppercase; }
  .pipeline-table tfoot td { font-weight:600; border-top:1px solid #cbd5e1; border-bottom:none; }
  .stage-cell { display:flex; align-items:center; gap:6px; }
  .bar-row td { padding:2px 6px; }
  .bar { height:14px; background:#e2e8f0; border-radius:2px; position:relative; }
  .bar > span { display:block; height:100%; border-radius:2px; }
  .bar-label { font-size:10px; color:#475569; display:flex; justify-content:space-between; margin-top:2px; }
  .leaflet-popup-content { font-size:12px; }
  .leaflet-popup-content .pname { font-weight:600; font-size:13px; margin-bottom:4px; }
  .source-chip { font-size:10px; color:#64748b; }
  .aemo-overlay-image { image-rendering: auto; mix-blend-mode: multiply; }
</style>
</head>
<body>
<div id="app">
  <div id="sidebar">
   <div id="sidebar-header">
    <h1>NEM Generation Map</h1>
    <div class="meta" id="meta">—</div>
    <div id="sidebar-tabs">
      <button data-tab="filters" class="active">Filters</button>
      <button data-tab="dashboard">Dashboard</button>
    </div>
   </div>

   <div class="tab-panel active" id="tab-filters">
    <h2>Search</h2>
    <input id="search" type="search" placeholder="Site name, owner, location...">

    <h2>Stage</h2>
    <div id="stage-filter"></div>

    <h2>State</h2>
    <div id="state-filter"></div>

    <h2>Capacity (MW)</h2>
    <div class="range-row">
      <span id="cap-lo">0</span>
      <input id="cap-min" type="range" min="0" value="0">
      <span id="cap-hi">—</span>
    </div>

    <h2>Technology</h2>
    <select id="tech-filter">
      <option value="">All technologies</option>
    </select>

    <h2>Network base layers</h2>
    <label class="row"><input type="checkbox" id="show-transmission" checked> Transmission lines (OSM)</label>
    <label class="row"><input type="checkbox" id="show-substations"> Substations (≥66 kV)</label>

    <h2>AEMO map underlays</h2>
    <div id="overlay-filter"></div>

    <h2 style="margin-top:18px">Other</h2>
    <label class="row"><input type="checkbox" id="only-aemo"> Only show projects on AEMO map</label>
    <label class="row"><input type="checkbox" id="only-geocoded"> Only show real-geocoded locations</label>

    <div style="margin-top:14px;display:flex;gap:6px;flex-wrap:wrap">
      <button class="reset" id="reset-btn">Reset filters</button>
      <button class="reset" id="export-btn">Export visible as CSV</button>
    </div>

    <h2>Marker size</h2>
    <div class="meta">∝ log(capacity)</div>
   </div>

   <div class="tab-panel" id="tab-dashboard">
    <h2 style="margin-top:0">Currently visible</h2>
    <div class="stat-grid">
      <div class="stat-card"><div class="v" id="dash-count">—</div><div class="l">Projects</div></div>
      <div class="stat-card"><div class="v" id="dash-mw">—</div><div class="l">Total MW</div></div>
      <div class="stat-card"><div class="v" id="dash-mwh">—</div><div class="l">Storage MWh</div></div>
      <div class="stat-card"><div class="v" id="dash-aemo">—</div><div class="l">On AEMO map</div></div>
    </div>

    <h2>MW by stage</h2>
    <div id="dash-stage-bars"></div>

    <h2>Pipeline by stage × state (MW)</h2>
    <div style="overflow-x:auto">
      <table class="pipeline-table" id="dash-pipeline"></table>
    </div>

    <h2>MW by technology</h2>
    <div id="dash-tech-bars"></div>

    <div class="meta" style="margin-top:18px">Totals update as you change filters.</div>
   </div>
  </div>
  <div id="map"></div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const DATA = __DATA__;
const HOME_VIEW = { center: [-30.0, 144.0], zoom: 5 };
const NEM_BOUNDS = L.latLngBounds([[-44, 128], [-9, 156]]);
const map = L.map('map', {
  preferCanvas: true,
  maxBounds: NEM_BOUNDS.pad(0.3),  // soft clamp - can't pan to Antarctica
  minZoom: 4,
  maxZoom: 14,
}).setView(HOME_VIEW.center, HOME_VIEW.zoom);

// Home / recenter control
const HomeControl = L.Control.extend({
  options: { position: 'topleft' },
  onAdd: function() {
    const c = L.DomUtil.create('div', 'leaflet-bar');
    const a = L.DomUtil.create('a', '', c);
    a.href = '#';
    a.title = 'Recenter on NEM';
    a.innerHTML = '⌂';
    a.style.fontSize = '18px';
    a.style.lineHeight = '26px';
    a.style.textAlign = 'center';
    L.DomEvent.on(a, 'click', e => {
      L.DomEvent.preventDefault(e);
      map.setView(HOME_VIEW.center, HOME_VIEW.zoom);
    });
    return c;
  },
});
map.addControl(new HomeControl());

// Per-state zoom shortcuts
const STATE_VIEW = {
  NSW: [[-32.5, 147], 6], VIC: [[-37, 145], 6], QLD: [[-22, 145], 5],
  SA:  [[-33, 138], 6], TAS: [[-42, 146.5], 7],
};
const StateZoomControl = L.Control.extend({
  options: { position: 'topleft' },
  onAdd: function() {
    const c = L.DomUtil.create('div', 'leaflet-bar');
    Object.entries(STATE_VIEW).forEach(([st, view]) => {
      const a = L.DomUtil.create('a', '', c);
      a.href = '#';
      a.title = `Zoom to ${st}`;
      a.textContent = st;
      a.style.fontSize = '10px';
      a.style.lineHeight = '26px';
      a.style.padding = '0 4px';
      a.style.minWidth = '24px';
      L.DomEvent.on(a, 'click', e => {
        L.DomEvent.preventDefault(e);
        map.setView(view[0], view[1]);
      });
    });
    return c;
  },
});
map.addControl(new StateZoomControl());
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; OpenStreetMap &copy; CARTO',
  maxZoom: 19,
}).addTo(map);

// --- AEMO underlays ---
const overlayLayers = {};
DATA.overlays.forEach(ov => {
  const img = L.imageOverlay(ov.image, ov.bounds, { opacity: 0.55, className: 'aemo-overlay-image' });
  overlayLayers[ov.state] = img;
});

// --- Transmission lines (OSM) ---
function txStyle(f) {
  const v = f.properties.v || f.properties.voltage_kv || 0;
  // AEMO-aligned voltage palette
  let color = '#999';
  if (v >= 500) color = '#fde047';        // yellow 500 kV
  else if (v >= 330) color = '#f59e0b';   // orange 330 kV
  else if (v >= 275) color = '#ec4899';   // pink/magenta 275 kV
  else if (v >= 220) color = '#1d4ed8';   // blue 220 kV
  else if (v >= 132) color = '#dc2626';   // red 132/110 kV
  else if (v >= 66)  color = '#7c2d12';   // brown 66 kV
  return { color, weight: v >= 275 ? 1.6 : 1.1, opacity: 0.75 };
}
const transmissionLayer = L.geoJSON(DATA.transmission, {
  style: txStyle,
  onEachFeature: (f, l) => {
    const p = f.properties;
    const v = p.v || p.voltage_kv;
    const n = p.n || p.name;
    const o = p.o || p.operator;
    l.bindTooltip(`${v} kV${n ? ' • ' + n : ''}${o ? ' • ' + o : ''}`);
  },
}).addTo(map);
transmissionLayer.bringToBack();

const substationLayer = L.geoJSON(DATA.substations, {
  pointToLayer: (f, latlng) => L.circleMarker(latlng, {
    radius: 2.5, color: '#475569', weight: 1, fillColor: '#cbd5e1', fillOpacity: 0.8,
  }),
  onEachFeature: (f, l) => {
    const p = f.properties;
    l.bindTooltip(`${p.name || 'Substation'} • ${p.voltage_kv} kV`);
  },
});

// --- Markers ---
function radiusFor(cap) {
  if (!cap || cap <= 0) return 3;
  return Math.max(3, Math.min(18, 3 + Math.log10(cap + 1) * 4));
}
const markers = DATA.projects.map(p => {
  const colour = DATA.stageColour[p.s] || DATA.stageColour["Unknown"];
  const m = L.circleMarker([p.lat, p.lon], {
    radius: radiusFor(p.c),
    color: colour, weight: 1,
    fillColor: colour, fillOpacity: 0.75,
  });
  m._p = p;
  m.bindTooltip(`${p.n} — ${p.c ? p.c.toFixed(0) : '?'} MW — ${p.s}`);
  m.bindPopup(() => popupHtml(p));
  return m;
});
const markerLayer = L.layerGroup(markers).addTo(map);

function popupHtml(p) {
  const colour = DATA.stageColour[p.s] || DATA.stageColour["Unknown"];
  const aemoBadge = p.aemo ? `<span class="pill" style="background:${colour}20;color:${colour}">on AEMO map</span>` : '';
  const geo = p.g ? '' : `<div style="color:#b45309;font-size:11px">approx location (region centroid)</div>`;
  return `
    <div class="pname">${escapeHtml(p.n)}</div>
    <div><b>Stage:</b> <span style="color:${colour}">${p.s}</span> ${aemoBadge}</div>
    <div><b>Capacity:</b> ${p.c ? p.c.toFixed(1) : '?'} MW${p.mwh ? ` / ${p.mwh} MWh` : ''}</div>
    <div><b>State:</b> ${p.st} (${p.r})</div>
    <div><b>Technology:</b> ${escapeHtml(p.t)}${p.f ? ' / ' + escapeHtml(p.f) : ''}</div>
    <div><b>Owner:</b> ${escapeHtml(p.o)}</div>
    ${p.loc ? `<div><b>Location:</b> ${escapeHtml(p.loc)}</div>` : ''}
    ${geo}
    <div class="source-chip" style="margin-top:4px">Source: ${p.src}</div>
  `;
}
function escapeHtml(s){ return (s||'').replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"})[c]); }

// --- Sidebar UI ---
function counts(field) {
  const c = {};
  DATA.projects.forEach(p => { c[p[field]] = (c[p[field]]||0) + 1; });
  return c;
}
const stageCounts = counts('s');
const stateCounts = counts('st');

function makeCheckboxes(containerId, items, colourFn, defaults) {
  const el = document.getElementById(containerId);
  items.forEach(it => {
    const id = `${containerId}-${it.value}`;
    const row = document.createElement('label');
    row.className = 'row';
    row.innerHTML = `
      <input type="checkbox" id="${id}" data-value="${it.value}" ${defaults.has(it.value) ? 'checked' : ''}>
      ${colourFn ? `<span class="swatch" style="background:${colourFn(it.value)}"></span>` : ''}
      <span>${it.label}</span>
      <span class="count">${it.count||''}</span>`;
    el.appendChild(row);
  });
}
const stageDefaults = new Set(DATA.stages.filter(s => s !== 'Existing' && s !== 'Withdrawn'));
makeCheckboxes('stage-filter',
  DATA.stages.map(s => ({value:s, label:s, count:stageCounts[s]||0})),
  v => DATA.stageColour[v], stageDefaults);
makeCheckboxes('state-filter',
  DATA.states.map(s => ({value:s, label:s, count:stateCounts[s]||0})),
  null, new Set(DATA.states));
makeCheckboxes('overlay-filter',
  DATA.states.filter(s => DATA.overlays.find(o=>o.state===s)).map(s => ({value:s, label:`${s} map`, count:''})),
  null, new Set());

const techSel = document.getElementById('tech-filter');
DATA.techs.forEach(t => {
  const opt = document.createElement('option'); opt.value = t; opt.textContent = t;
  techSel.appendChild(opt);
});

const capMin = document.getElementById('cap-min');
capMin.max = DATA.capMax;
document.getElementById('cap-hi').textContent = DATA.capMax + '+';
capMin.addEventListener('input', () => {
  document.getElementById('cap-lo').textContent = capMin.value;
  applyFilters();
});

document.getElementById('search').addEventListener('input', applyFilters);
document.getElementById('tech-filter').addEventListener('change', applyFilters);
document.getElementById('only-aemo').addEventListener('change', applyFilters);
document.getElementById('only-geocoded').addEventListener('change', applyFilters);
document.querySelectorAll('#stage-filter input, #state-filter input').forEach(el =>
  el.addEventListener('change', applyFilters));
document.getElementById('show-transmission').addEventListener('change', e => {
  if (e.target.checked) { transmissionLayer.addTo(map); transmissionLayer.bringToBack(); }
  else map.removeLayer(transmissionLayer);
});
document.getElementById('show-substations').addEventListener('change', e => {
  if (e.target.checked) substationLayer.addTo(map);
  else map.removeLayer(substationLayer);
});

document.querySelectorAll('#overlay-filter input').forEach(el =>
  el.addEventListener('change', () => {
    DATA.overlays.forEach(ov => {
      const cb = document.querySelector(`#overlay-filter input[data-value='${ov.state}']`);
      const layer = overlayLayers[ov.state];
      if (cb && cb.checked) {
        if (!map.hasLayer(layer)) layer.addTo(map);
      } else {
        if (map.hasLayer(layer)) map.removeLayer(layer);
      }
    });
  }));

document.getElementById('reset-btn').addEventListener('click', () => {
  document.querySelectorAll('#stage-filter input').forEach(el => el.checked = stageDefaults.has(el.dataset.value));
  document.querySelectorAll('#state-filter input').forEach(el => el.checked = true);
  document.getElementById('search').value = '';
  document.getElementById('tech-filter').value = '';
  capMin.value = 0; document.getElementById('cap-lo').textContent = '0';
  document.getElementById('only-aemo').checked = false;
  document.getElementById('only-geocoded').checked = false;
  window.applyFilters();
});

// --- CSV export ---
function csvEscape(v) {
  if (v == null) return '';
  const s = String(v);
  if (/[",\n\r]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
  return s;
}
document.getElementById('export-btn').addEventListener('click', () => {
  const cols = [
    ['site_name','n'], ['state','st'], ['region','r'], ['stage','s'],
    ['capacity_mw','c'], ['storage_mwh','mwh'], ['technology','t'], ['fuel','f'],
    ['owner','o'], ['location_desc','loc'], ['lat','lat'], ['lon','lon'],
    ['on_aemo_map','aemo'], ['geocoded','g'], ['source','src'],
  ];
  const vis = markers.filter(m => markerLayer.hasLayer(m)).map(m => m._p);
  const header = cols.map(c => c[0]).join(',');
  const rows = vis.map(p => cols.map(c => csvEscape(p[c[1]])).join(','));
  const csv = '﻿' + header + '\n' + rows.join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const ts = new Date().toISOString().replace(/[:T]/g,'-').slice(0,16);
  a.href = url;
  a.download = `nem_projects_${ts}_${vis.length}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
});

function applyFilters() {
  const stages = new Set([...document.querySelectorAll('#stage-filter input:checked')].map(e => e.dataset.value));
  const states = new Set([...document.querySelectorAll('#state-filter input:checked')].map(e => e.dataset.value));
  const tech = document.getElementById('tech-filter').value;
  const q = document.getElementById('search').value.trim().toLowerCase();
  const capMinV = +capMin.value;
  const onlyAemo = document.getElementById('only-aemo').checked;
  const onlyGeo = document.getElementById('only-geocoded').checked;

  let shown = 0;
  markers.forEach(m => {
    const p = m._p;
    let ok = stages.has(p.s) && states.has(p.st);
    if (ok && tech) ok = (p.t === tech);
    if (ok && q) ok = (p.n.toLowerCase().includes(q) || (p.o||'').toLowerCase().includes(q) || (p.loc||'').toLowerCase().includes(q));
    if (ok && capMinV > 0) ok = (p.c||0) >= capMinV;
    if (ok && onlyAemo) ok = p.aemo;
    if (ok && onlyGeo) ok = p.g;
    if (ok) { if (!markerLayer.hasLayer(m)) markerLayer.addLayer(m); shown++; }
    else { if (markerLayer.hasLayer(m)) markerLayer.removeLayer(m); }
  });
  document.getElementById('meta').textContent =
    `${shown.toLocaleString()} of ${DATA.projects.length.toLocaleString()} projects shown`;
}
// --- Tabs ---
document.querySelectorAll('#sidebar-tabs button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#sidebar-tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'dashboard') renderDashboard();
  });
});

// --- Dashboard ---
function fmtMW(v) {
  if (v >= 1000) return (v/1000).toFixed(1) + ' GW';
  return Math.round(v).toLocaleString() + ' MW';
}
function fmtMWh(v) {
  if (!v) return '—';
  if (v >= 1000) return (v/1000).toFixed(1) + ' GWh';
  return Math.round(v).toLocaleString();
}
function visibleProjects() {
  return markers.filter(m => markerLayer.hasLayer(m)).map(m => m._p);
}
function renderDashboard() {
  const vis = visibleProjects();
  const totalMW = vis.reduce((s, p) => s + (p.c || 0), 0);
  const totalMWh = vis.reduce((s, p) => s + (p.mwh || 0), 0);
  const onAemo = vis.filter(p => p.aemo).length;

  document.getElementById('dash-count').textContent = vis.length.toLocaleString();
  document.getElementById('dash-mw').textContent = fmtMW(totalMW);
  document.getElementById('dash-mwh').textContent = fmtMWh(totalMWh);
  document.getElementById('dash-aemo').textContent = onAemo.toLocaleString();

  // MW by stage horizontal bars
  const byStage = {}; DATA.stages.forEach(s => byStage[s] = 0);
  vis.forEach(p => { byStage[p.s] = (byStage[p.s]||0) + (p.c||0); });
  const maxStage = Math.max(1, ...Object.values(byStage));
  const stageEl = document.getElementById('dash-stage-bars');
  stageEl.innerHTML = DATA.stages.filter(s => byStage[s] > 0).map(s => `
    <div style="margin-bottom:6px">
      <div class="bar-label"><span style="color:${DATA.stageColour[s]};font-weight:600">${s}</span><span>${fmtMW(byStage[s])}</span></div>
      <div class="bar"><span style="width:${(byStage[s]/maxStage*100).toFixed(1)}%;background:${DATA.stageColour[s]}"></span></div>
    </div>
  `).join('');

  // Pipeline table stage x state
  const pipeline = {};
  DATA.stages.forEach(s => { pipeline[s] = {}; DATA.states.forEach(st => pipeline[s][st] = 0); });
  vis.forEach(p => { if (pipeline[p.s] && p.st in pipeline[p.s]) pipeline[p.s][p.st] += (p.c||0); });
  const colTotal = {}; DATA.states.forEach(st => colTotal[st] = 0);
  let grand = 0;
  let html = '<thead><tr><th>Stage</th>';
  DATA.states.forEach(st => html += `<th>${st}</th>`);
  html += '<th>Total</th></tr></thead><tbody>';
  DATA.stages.forEach(s => {
    const rowTot = DATA.states.reduce((a,st) => a + pipeline[s][st], 0);
    if (rowTot === 0) return;
    html += `<tr><td><span class="stage-cell"><span class="swatch" style="background:${DATA.stageColour[s]}"></span>${s}</span></td>`;
    DATA.states.forEach(st => {
      const v = pipeline[s][st];
      colTotal[st] += v; grand += v;
      html += `<td>${v ? Math.round(v).toLocaleString() : '—'}</td>`;
    });
    html += `<td><b>${Math.round(rowTot).toLocaleString()}</b></td></tr>`;
  });
  html += '</tbody><tfoot><tr><td>Total</td>';
  DATA.states.forEach(st => html += `<td>${Math.round(colTotal[st]).toLocaleString()}</td>`);
  html += `<td>${Math.round(grand).toLocaleString()}</td></tr></tfoot>`;
  document.getElementById('dash-pipeline').innerHTML = html;

  // MW by technology (top 10)
  const byTech = {};
  vis.forEach(p => { byTech[p.t] = (byTech[p.t]||0) + (p.c||0); });
  const techs = Object.entries(byTech).filter(([,v]) => v>0).sort((a,b)=>b[1]-a[1]).slice(0, 10);
  const maxTech = Math.max(1, ...techs.map(t=>t[1]));
  document.getElementById('dash-tech-bars').innerHTML = techs.map(([t,v]) => `
    <div style="margin-bottom:6px">
      <div class="bar-label"><span>${escapeHtml(t)}</span><span>${fmtMW(v)}</span></div>
      <div class="bar"><span style="width:${(v/maxTech*100).toFixed(1)}%;background:#475569"></span></div>
    </div>
  `).join('');
}

// re-render dashboard whenever filters change AND the dashboard tab is open
const origApply = applyFilters;
applyFilters = function() {
  origApply();
  if (document.querySelector('#sidebar-tabs button[data-tab="dashboard"].active')) renderDashboard();
};
applyFilters();

// --- Legend ---
const legend = L.control({position:'bottomleft'});
legend.onAdd = function() {
  const div = L.DomUtil.create('div');
  div.style.background = 'white'; div.style.padding = '8px 12px';
  div.style.border = '1px solid #cbd5e1'; div.style.borderRadius = '4px';
  div.style.boxShadow = '0 1px 3px rgba(0,0,0,.15)';
  div.style.fontSize = '11px'; div.style.fontFamily = 'system-ui';
  let h = '<div style="font-weight:600;margin-bottom:4px">Project stage</div>';
  DATA.stages.forEach(s => {
    h += `<div class="legend-block"><span class="swatch" style="background:${DATA.stageColour[s]}"></span>${s}</div>`;
  });
  h += '<div style="font-weight:600;margin:8px 0 4px">Transmission (kV)</div>';
  const tx = [['500','#fde047'],['330','#f59e0b'],['275','#ec4899'],['220','#1d4ed8'],['132/110','#dc2626'],['66','#7c2d12']];
  tx.forEach(([v,c]) => {
    h += `<div class="legend-block"><span style="display:inline-block;width:14px;height:3px;background:${c};margin-right:6px"></span>${v} kV</div>`;
  });
  div.innerHTML = h;
  return div;
};
legend.addTo(map);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
