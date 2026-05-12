"""Fallback geocoder for projects Nominatim couldn't place.

Three deterministic strategies, applied in priority order:

  1. **Manual overrides** — data/inputs/coord_overrides.csv
     Columns: site_name, lat, lon, source_note (optional)
     Curated by hand for known-bad geocodes. Highest priority.

  2. **Snap to substation** — parse location_desc for substation names
     ("Adjacent to Davenport 275kV Substation"), fuzzy-match against
     OSM substations.geojson, use that substation's lat/lon.

  3. **Town offset** — parse "Xkm <direction> of <Town>" patterns,
     look up the town in a gazetteer, apply the bearing/distance offset.

Writes back to projects.json with coords_source recording which method hit.
Keeps existing coords if already geocoded (won't downgrade).
"""
from __future__ import annotations
import csv
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
INTERMEDIATE = ROOT / "data" / "intermediate"
PROJECTS = INTERMEDIATE / "projects.json"
SUBS = INTERMEDIATE / "substations.geojson"
OVERRIDES = ROOT / "data" / "inputs" / "coord_overrides.csv"

# Major AU towns (used as anchors for "Xkm of Town" parsing).
TOWN_GAZETTEER: dict[str, tuple[float, float]] = {
    # NSW
    "sydney": (-33.87, 151.21), "newcastle": (-32.93, 151.78), "wollongong": (-34.42, 150.89),
    "wagga wagga": (-35.12, 147.37), "wagga": (-35.12, 147.37),
    "tamworth": (-31.09, 150.93), "armidale": (-30.51, 151.67), "dubbo": (-32.25, 148.60),
    "albury": (-36.08, 146.92), "cooma": (-36.24, 149.13), "lithgow": (-33.48, 150.16),
    "orange": (-33.28, 149.10), "parkes": (-33.13, 148.18), "broken hill": (-31.95, 141.45),
    "bathurst": (-33.42, 149.58), "goulburn": (-34.75, 149.72), "grafton": (-29.69, 152.93),
    "lismore": (-28.81, 153.28), "tenterfield": (-29.05, 152.02), "moree": (-29.46, 149.84),
    "narrabri": (-30.32, 149.78), "gunnedah": (-30.98, 150.26), "muswellbrook": (-32.27, 150.89),
    "denman": (-32.39, 150.69), "hay south": (-34.65, 144.84), "merriwa": (-32.13, 150.36),
    "scone": (-32.05, 150.86), "mudgee": (-32.59, 149.59), "bookham": (-34.85, 148.65),
    "boorowa": (-34.44, 148.72), "hargraves": (-32.79, 149.79), "wellington nsw": (-32.55, 148.94),
    "singleton": (-32.57, 151.17), "cessnock": (-32.83, 151.36), "gosford": (-33.43, 151.34),
    "wellington": (-32.55, 148.94), "forbes": (-33.39, 148.01), "young": (-34.31, 148.30),
    "cowra": (-33.83, 148.69), "griffith": (-34.29, 146.04), "leeton": (-34.55, 146.40),
    "hay": (-34.50, 144.84), "deniliquin": (-35.53, 144.95), "moruya": (-35.91, 150.08),
    "yass": (-34.84, 148.91), "queanbeyan": (-35.35, 149.23), "merimbula": (-36.89, 149.91),
    "inverell": (-29.78, 151.10), "glen innes": (-29.74, 151.74), "ulladulla": (-35.36, 150.47),
    "nyngan": (-31.55, 147.19), "narromine": (-32.22, 148.24),
    "keri keri": (-29.94, 149.62),  # KCI typo - Keri Keri = Kirikiri or nearest? actually NSW "Keri Keri" not a town - probable typo
    # VIC
    "melbourne": (-37.81, 144.96), "geelong": (-38.15, 144.36), "bendigo": (-36.76, 144.28),
    "ballarat": (-37.56, 143.86), "mildura": (-34.21, 142.14), "horsham": (-36.72, 142.20),
    "shepparton": (-36.38, 145.40), "wodonga": (-36.12, 146.89), "traralgon": (-38.20, 146.54),
    "hamilton": (-37.74, 142.02), "warrnambool": (-38.38, 142.49),
    "morwell": (-38.23, 146.40), "sale": (-38.10, 147.07), "wonthaggi": (-38.61, 145.59),
    "echuca": (-36.13, 144.75), "swan hill": (-35.34, 143.55), "ararat": (-37.28, 142.93),
    "portland": (-38.34, 141.60),
    # QLD
    "brisbane": (-27.47, 153.03), "townsville": (-19.26, 146.82), "cairns": (-16.92, 145.78),
    "mackay": (-21.14, 149.19), "rockhampton": (-23.38, 150.51), "gladstone": (-23.85, 151.26),
    "bundaberg": (-24.86, 152.35), "toowoomba": (-27.56, 151.95), "mount isa": (-20.73, 139.49),
    "roma": (-26.57, 148.79), "longreach": (-23.44, 144.25), "cooktown": (-15.47, 145.25),
    "ingham": (-18.65, 146.16), "ayr": (-19.57, 147.40), "biloela": (-24.40, 150.51),
    "moranbah": (-22.00, 148.04), "emerald": (-23.52, 148.16), "blackwater": (-23.58, 148.88),
    "clermont": (-22.83, 147.65), "yeppoon": (-23.13, 150.74), "warwick": (-28.22, 152.03),
    "kingaroy": (-26.54, 151.83), "dalby": (-27.18, 151.27), "stanthorpe": (-28.65, 151.94),
    "atherton": (-17.27, 145.48), "innisfail": (-17.53, 146.03), "tully": (-17.93, 145.92),
    "proserpine": (-20.40, 148.58), "hughenden": (-20.85, 144.20),
    "tara": (-27.28, 150.46), "gin gin": (-24.99, 151.96), "miles": (-26.66, 150.18),
    "chinchilla": (-26.74, 150.63), "wandoan": (-26.13, 149.96), "millmerran": (-27.87, 151.27),
    "kogan": (-27.04, 150.71), "boomber": (-26.10, 150.50), "callide": (-24.30, 150.65),
    # SA
    "adelaide": (-34.93, 138.60), "whyalla": (-33.03, 137.56), "port augusta": (-32.49, 137.77),
    "mount gambier": (-37.83, 140.78), "murray bridge": (-35.12, 139.27),
    "port lincoln": (-34.73, 135.86), "port pirie": (-33.19, 138.02), "ceduna": (-32.13, 133.68),
    "olympic dam": (-30.44, 136.89), "wudinna": (-33.04, 135.47), "kadina": (-33.96, 137.72),
    "snowtown": (-33.78, 138.21), "berri": (-34.28, 140.60), "renmark": (-34.17, 140.74),
    "naracoorte": (-36.96, 140.74), "loxton": (-34.45, 140.57), "barmera": (-34.25, 140.46),
    "tanunda": (-34.52, 138.96), "victor harbor": (-35.55, 138.62),
    "mannum": (-34.92, 139.30), "robertstown": (-33.97, 139.07), "tailem bend": (-35.27, 139.45),
    # TAS
    "hobart": (-42.88, 147.33), "launceston": (-41.43, 147.16), "devonport": (-41.18, 146.35),
    "burnie": (-41.05, 145.91), "smithton": (-40.85, 145.12), "queenstown": (-42.08, 145.55),
    "wynyard": (-40.99, 145.73), "ulverstone": (-41.16, 146.18), "george town": (-41.10, 146.83),
    "scottsdale": (-41.16, 147.51), "new norfolk": (-42.78, 147.06),
    "kingston": (-42.97, 147.30), "huonville": (-43.03, 147.04),
    "dorset": (-41.16, 147.51),  # LGA centred on Scottsdale
    "kentish": (-41.40, 146.20),  # LGA centred on Sheffield TAS
    "george town tas": (-41.10, 146.83),
}

DIR_VEC = {  # (north_delta_per_km, east_delta_per_km) at typical AU lat ~ -30
    "north": (1, 0), "n": (1, 0),
    "south": (-1, 0), "s": (-1, 0),
    "east": (0, 1), "e": (0, 1),
    "west": (0, -1), "w": (0, -1),
    "northeast": (1, 1), "north-east": (1, 1), "ne": (1, 1),
    "northwest": (1, -1), "north-west": (1, -1), "nw": (1, -1),
    "southeast": (-1, 1), "south-east": (-1, 1), "se": (-1, 1),
    "southwest": (-1, -1), "south-west": (-1, -1), "sw": (-1, -1),
}

KM_PER_DEG_LAT = 111.0

# Offshore wind zone centroids (declared zones by Australian Govt)
OFFSHORE_ZONES: dict[str, tuple[float, float]] = {
    "gippsland": (-38.7, 147.5),
    "bass strait": (-39.5, 145.5),
    "kilcunda": (-38.8, 145.5),
    "portland": (-38.7, 141.5),
    "hunter": (-32.9, 152.6),
    "illawarra": (-34.6, 151.2),
    "newcastle offshore": (-33.0, 152.5),
}


def parse_offshore(desc: str, site_name: str) -> tuple[float, float, str] | None:
    """Match offshore wind / hydrogen project location patterns."""
    if not (desc or site_name): return None
    text = f"{desc} {site_name}".lower()
    # Normalize "Off Shore" -> "offshore" for matching
    text = text.replace("off shore", "offshore")
    if "offshore" not in text and "bass strait" not in text: return None
    for zone, (lat, lon) in OFFSHORE_ZONES.items():
        if zone in text:
            return (lat, lon, f"offshore zone '{zone}'")
    # generic offshore VIC -> Gippsland
    if "offshore" in text:
        return (-38.7, 147.5, "offshore zone (generic VIC Gippsland fallback)")
    return None


def offset_from_town(town: str, distance_km: float, direction: str
                    ) -> tuple[float, float] | None:
    town = town.lower().strip()
    if town not in TOWN_GAZETTEER:
        return None
    lat0, lon0 = TOWN_GAZETTEER[town]
    direction = direction.lower().strip().replace(" ", "")
    if direction not in DIR_VEC:
        return None
    n_unit, e_unit = DIR_VEC[direction]
    # normalise diagonal (so 10km NE goes ~7.07 km north + 7.07 km east)
    norm = math.hypot(n_unit, e_unit) or 1
    n_unit /= norm; e_unit /= norm
    lat_per_km = 1 / KM_PER_DEG_LAT
    lon_per_km = 1 / (KM_PER_DEG_LAT * math.cos(math.radians(lat0)))
    return (lat0 + n_unit * distance_km * lat_per_km,
            lon0 + e_unit * distance_km * lon_per_km)


def parse_town_offset(desc: str) -> tuple[float, float] | None:
    """Match patterns like '12km East of Keri Keri town'."""
    if not desc: return None
    # 'Xkm <direction> of <Town>'
    m = re.search(
        r"(\d+)\s*km\s+(?:to\s+the\s+)?([a-z]+(?:[-\s]?[a-z]+)?)\s+(?:of|from)\s+([a-z][a-z\s'-]+)",
        desc, re.IGNORECASE,
    )
    if m:
        dist = float(m.group(1))
        direction = m.group(2)
        town = re.sub(r"\s+(town|substation|sw\s*stn|sub-?station).*", "", m.group(3), flags=re.IGNORECASE).strip()
        # also strip trailing state suffix
        town = re.sub(r",?\s*(NSW|VIC|QLD|SA|TAS)\s*$", "", town, flags=re.IGNORECASE).strip()
        # Limit to last 3 words to avoid swallowing trailing clauses
        toks = town.split()
        for n in (3, 2, 1):
            cand = " ".join(toks[:n]).strip()
            res = offset_from_town(cand, dist, direction)
            if res: return res
    return None


def load_substations() -> list[dict]:
    if not SUBS.exists(): return []
    return json.loads(SUBS.read_text(encoding="utf-8"))["features"]


def normalise_sub_name(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\b(substation|sub-station|switching station|switching stn|ts|zs|bsp|switchyard)\b", "", s)
    s = re.sub(r"\b\d+\s*kv\b", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def snap_to_substation(desc: str, state: str, substations: list[dict]) -> tuple[float, float, str] | None:
    if not desc: return None
    dl = desc.lower()
    if not any(kw in dl for kw in ("substation", "sub-station", "switch", "ts", "zs", "switchyard", "kv")):
        return None
    desc_norm = normalise_sub_name(desc)
    if not desc_norm: return None

    # State filter on OSM (state field is e.g. 'NSW_N')
    state_subs = [s for s in substations if s["properties"].get("state", "").startswith(state)]
    best = None; best_score = 0
    for sub in state_subs:
        name = sub["properties"].get("name") or ""
        if not name or len(name) < 4: continue
        norm = normalise_sub_name(name)
        if not norm or len(norm) < 4: continue
        # token-overlap score; require all tokens of name to appear in description
        sub_tokens = set(norm.split())
        desc_tokens = set(desc_norm.split())
        if not sub_tokens.issubset(desc_tokens): continue
        # score = length of overlap (favour longer / more specific names)
        score = sum(len(t) for t in sub_tokens)
        if score > best_score:
            best_score = score
            best = sub
    if best is None: return None
    lon, lat = best["geometry"]["coordinates"]
    name = best["properties"].get("name", "substation")
    return (lat, lon, f"OSM substation '{name}'")


def load_overrides() -> dict[str, tuple[float, float, str]]:
    overrides: dict[str, tuple[float, float, str]] = {}
    if not OVERRIDES.exists():
        return overrides
    with OVERRIDES.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                lat = float(row["lat"]); lon = float(row["lon"])
            except (KeyError, ValueError):
                continue
            key = row.get("site_name", "").strip().lower()
            note = row.get("source_note") or row.get("note") or ""
            if key:
                overrides[key] = (lat, lon, f"manual override: {note}".strip(": "))
    return overrides


def extract_town_from_address(desc: str) -> tuple[float, float] | None:
    """Match patterns like '12 Main St, Town NSW 2345' or 'Lot X, Y Road, Town, STATE'."""
    if not desc: return None
    # Try to find <Town> <STATE> [postcode]
    m = re.search(r"([a-z][a-z\s'-]+?),?\s+(?:NSW|VIC|QLD|SA|TAS)(?:\s+\d{4})?\b", desc, re.IGNORECASE)
    if m:
        town_text = m.group(1).strip().lower()
        # Try progressively shorter substrings (right-most tokens are usually the town)
        toks = town_text.split()
        for n in range(min(3, len(toks)), 0, -1):
            cand = " ".join(toks[-n:])
            if cand in TOWN_GAZETTEER:
                return TOWN_GAZETTEER[cand]
    return None


def find_town_in_text(text: str) -> tuple[float, float, str] | None:
    """Scan free text for any town name in our gazetteer (longest match first)."""
    if not text: return None
    t = re.sub(r"[^a-z0-9 ]+", " ", text.lower())
    toks = t.split()
    # try 3-grams, 2-grams, 1-grams
    for n in (3, 2, 1):
        for i in range(len(toks) - n + 1):
            cand = " ".join(toks[i:i+n])
            if cand in TOWN_GAZETTEER:
                lat, lon = TOWN_GAZETTEER[cand]
                return (lat, lon, cand)
    return None


def loose_substation_match(text: str, state: str, substations: list[dict]) -> tuple[float, float, str] | None:
    """Same as snap_to_substation but without requiring the 'substation' keyword."""
    if not text: return None
    text_norm = normalise_sub_name(text)
    if not text_norm: return None
    state_subs = [s for s in substations if s["properties"].get("state", "").startswith(state)]
    best = None; best_score = 0
    for sub in state_subs:
        name = sub["properties"].get("name") or ""
        if not name or len(name) < 5: continue  # stricter min length without the substation keyword
        norm = normalise_sub_name(name)
        if not norm or len(norm) < 5: continue
        sub_tokens = set(norm.split())
        text_tokens = set(text_norm.split())
        if not sub_tokens.issubset(text_tokens): continue
        if all(len(t) < 4 for t in sub_tokens): continue  # avoid "north south east" style false matches
        score = sum(len(t) for t in sub_tokens)
        if score > best_score:
            best_score = score
            best = sub
    if best is None: return None
    lon, lat = best["geometry"]["coordinates"]
    return (lat, lon, f"OSM substation '{best['properties'].get('name')}' (loose match)")


def main():
    projects = json.loads(PROJECTS.read_text(encoding="utf-8"))
    subs = load_substations()
    overrides = load_overrides()
    print(f"Loaded {len(projects)} projects, {len(subs)} OSM substations, {len(overrides)} manual overrides")

    stats = {"override": 0, "substation": 0, "town_offset": 0,
             "address_town": 0, "loose_substation": 0, "site_name_town": 0,
             "skipped_already_geocoded": 0, "no_hit": 0}

    for p in projects:
        if p.get("coords_source") in {"aemo_map_vision"}:
            # Already authoritative — leave alone
            continue
        # Override always wins (even over Nominatim)
        key = (p.get("site_name") or "").strip().lower()
        if key in overrides:
            lat, lon, note = overrides[key]
            p["nominatim_lat"] = p.get("lat"); p["nominatim_lon"] = p.get("lon")
            p["lat"] = lat; p["lon"] = lon
            p["geocoded"] = True
            p["coords_source"] = "manual_override"
            p["coord_note"] = note
            stats["override"] += 1
            continue

        if p.get("geocoded"):
            stats["skipped_already_geocoded"] += 1
            continue

        desc = p.get("location_desc") or ""
        state = p.get("state") or ""
        site_name = p.get("site_name") or ""

        # offshore wind / hydrogen first (won't match anything onshore)
        off = parse_offshore(desc, site_name)
        if off:
            p["lat"], p["lon"], note = off
            p["geocoded"] = True
            p["coords_source"] = "offshore_zone"
            p["coord_note"] = note
            stats.setdefault("offshore", 0)
            stats["offshore"] += 1
            continue

        # try substation snap
        snap = snap_to_substation(desc, state, subs)
        if snap:
            lat, lon, note = snap
            p["lat"] = lat; p["lon"] = lon
            p["geocoded"] = True
            p["coords_source"] = "snap_substation"
            p["coord_note"] = note
            stats["substation"] += 1
            continue

        # try town offset
        offset = parse_town_offset(desc)
        if offset:
            lat, lon = offset
            p["lat"] = lat; p["lon"] = lon
            p["geocoded"] = True
            p["coords_source"] = "town_offset"
            stats["town_offset"] += 1
            continue

        # try address parser ('..., Town NSW 2345')
        addr = extract_town_from_address(desc)
        if addr:
            p["lat"], p["lon"] = addr
            p["geocoded"] = True
            p["coords_source"] = "address_town"
            stats["address_town"] += 1
            continue

        # loose substation match (no 'substation' keyword required)
        loose = loose_substation_match(desc, state, subs)
        if loose:
            p["lat"], p["lon"], note = loose
            p["geocoded"] = True
            p["coords_source"] = "loose_substation"
            p["coord_note"] = note
            stats["loose_substation"] += 1
            continue

        # site_name based fallback - scan name for any town in gazetteer
        site_name = p.get("site_name") or ""
        hit = find_town_in_text(site_name)
        if hit:
            lat, lon, town = hit
            # only accept if town is in the project's region (rough lat bounds)
            state_bounds = {
                "NSW": (-37.5, -28.0), "VIC": (-39.3, -33.9), "QLD": (-29.5, -10.0),
                "SA": (-38.5, -25.9), "TAS": (-43.7, -39.5),
            }
            if state in state_bounds:
                lo, hi = state_bounds[state]
                if not (lo <= lat <= hi):
                    stats["no_hit"] += 1
                    continue
            p["lat"] = lat; p["lon"] = lon
            p["geocoded"] = True
            p["coords_source"] = "site_name_town"
            p["coord_note"] = f"matched town '{town}' in site name"
            stats["site_name_town"] += 1
            continue

        # site_name based substation match
        sub_hit = loose_substation_match(site_name, state, subs)
        if sub_hit:
            p["lat"], p["lon"], note = sub_hit
            p["geocoded"] = True
            p["coords_source"] = "site_name_substation"
            p["coord_note"] = note
            stats["loose_substation"] += 1
            continue

        stats["no_hit"] += 1

    PROJECTS.write_text(json.dumps(projects, indent=2, default=str), encoding="utf-8")
    print(f"Stats: {stats}")
    print(f"Total now geocoded: {sum(1 for x in projects if x.get('geocoded'))} of {len(projects)}")


if __name__ == "__main__":
    main()
