"""
Nominatim geocoder for the NEM project list.

- Reads projects.json
- Builds per-project query strings (prefer location_desc, fall back to site_name)
- Hits Nominatim at 1 req/sec (their usage policy)
- Caches every response to geocode_cache.json (keyed by query string)
- Writes lat/lon back to projects.json (keeps existing centroid coords as `lat_approx`,
  `lon_approx` so we can fall back if geocoding failed)

Re-running picks up from where it left off (cache is persistent).
"""

from __future__ import annotations
import json
import re
import time
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT = Path(__file__).parent.parent
INTERMEDIATE = ROOT / "data" / "intermediate"
PROJECTS = INTERMEDIATE / "projects.json"
CACHE = INTERMEDIATE / "geocode_cache.json"

# AU NEM bounding box (lon_min, lat_min, lon_max, lat_max) — clips Nominatim's search
AU_NEM_VIEWBOX = "129.0,-44.0,154.0,-10.0"

REGION_VIEWBOX = {
    "NSW1": "140.9,-37.6,153.7,-28.1",
    "VIC1": "140.9,-39.3,150.0,-33.9",
    "QLD1": "137.9,-29.2,153.6,-10.0",
    "SA1":  "129.0,-38.1,141.0,-25.9",
    "TAS1": "144.5,-43.8,148.7,-39.5",
}


def clean_location_desc(s: str) -> str:
    if not s:
        return ""
    s = s.strip().replace("\xa0", " ")
    # drop coordinate-y noise like "5km east of" → "east of"
    s = re.sub(r"\b\d+\s*km\s*(north|south|east|west|north[- ]?east|north[- ]?west|south[- ]?east|south[- ]?west)\s+of\s+",
               "", s, flags=re.IGNORECASE)
    # collapse whitespace
    s = " ".join(s.split())
    # trim trailing punctuation
    s = s.rstrip(".,;:- ")
    return s


def project_queries(p: dict) -> list[str]:
    """Ordered list of queries to try for one project."""
    state = p.get("state") or ""
    region = p.get("region") or ""
    loc = clean_location_desc(p.get("location_desc") or "")
    site = (p.get("site_name") or "").strip()
    # strip "BESS", "Solar Farm" etc to expose the toponym
    site_core = re.sub(
        r"\b(BESS|Battery Energy Storage System|Solar Farm|Wind Farm|Solar PV|"
        r"Solar And BESS|Hybrid Facility|Hybrid Power Station|Power Station|"
        r"Pumped Hydro|Stage \d+|Phase \d+|\(.*?\))\b",
        "", site, flags=re.IGNORECASE,
    ).strip(" -–—,.")
    site_core = " ".join(site_core.split())

    queries: list[str] = []
    if loc:
        queries.append(f"{loc}, {state}, Australia" if state else f"{loc}, Australia")
    if site_core and site_core.lower() not in (loc.lower() if loc else ""):
        queries.append(f"{site_core}, {state}, Australia" if state else f"{site_core}, Australia")
    if site and site_core != site:
        queries.append(f"{site}, {state}, Australia" if state else f"{site}, Australia")
    # dedupe preserving order
    seen, out = set(), []
    for q in queries:
        k = q.lower()
        if k not in seen and len(q) > 5:
            seen.add(k); out.append(q)
    return out


def nominatim(query: str, region: str | None) -> dict | None:
    params = {
        "q": query,
        "format": "json",
        "limit": "1",
        "countrycodes": "au",
        "viewbox": REGION_VIEWBOX.get(region, AU_NEM_VIEWBOX),
        "bounded": "1",
    }
    url = "https://nominatim.openstreetmap.org/search?" + urlencode(params)
    req = Request(url, headers={
        "User-Agent": "nem-generation-map/0.1 (contact: expenses.woodenduck@gmail.com)",
        "Accept-Language": "en-AU,en;q=0.9",
    })
    try:
        with urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
            if data:
                d = data[0]
                return {"lat": float(d["lat"]), "lon": float(d["lon"]),
                        "display_name": d.get("display_name", ""),
                        "class": d.get("class"), "type": d.get("type")}
    except (HTTPError, URLError, TimeoutError, ValueError) as e:
        print(f"  err: {e}", file=sys.stderr)
    return None


def main():
    projects = json.loads(PROJECTS.read_text(encoding="utf-8"))
    cache: dict = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    print(f"Loaded {len(projects)} projects, {len(cache)} cached queries")

    DELAY = 1.05  # > 1 req/sec per Nominatim policy
    new_hits = 0
    misses = 0
    last_save = time.time()

    # build a list of queries to run, deduped, so caching is maximal
    unique_queries: list[tuple[str, str]] = []  # (query, region)
    seen = set()
    for p in projects:
        for q in project_queries(p):
            key = q.lower()
            if key in cache or key in seen:
                continue
            seen.add(key)
            unique_queries.append((q, p.get("region", "")))

    print(f"{len(unique_queries)} unique queries to fetch")
    for i, (q, region) in enumerate(unique_queries):
        res = nominatim(q, region)
        cache[q.lower()] = res  # store None for misses too — don't retry
        if res:
            new_hits += 1
        else:
            misses += 1
        if (i + 1) % 25 == 0 or i == len(unique_queries) - 1:
            print(f"  [{i+1}/{len(unique_queries)}] hits={new_hits} misses={misses}  last={q[:80]}")
        if time.time() - last_save > 30:
            CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
            last_save = time.time()
        time.sleep(DELAY)

    CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    print(f"Wrote {CACHE}: hits={new_hits} misses={misses}")

    # apply to projects.json
    apply_cache_to_projects(projects, cache)
    PROJECTS.write_text(json.dumps(projects, indent=2, default=str), encoding="utf-8")
    print(f"Updated {PROJECTS} with real lat/lon where available")


def apply_cache_to_projects(projects: list[dict], cache: dict) -> None:
    geocoded = 0
    for p in projects:
        if "lat_approx" not in p:  # preserve original centroid
            p["lat_approx"] = p.get("lat")
            p["lon_approx"] = p.get("lon")
        hit = None
        for q in project_queries(p):
            r = cache.get(q.lower())
            if r:
                hit = r; p["geocode_query"] = q; break
        if hit:
            p["lat"] = hit["lat"]; p["lon"] = hit["lon"]
            p["geocode_display"] = hit.get("display_name", "")
            p["geocoded"] = True
            geocoded += 1
        else:
            p["lat"] = p["lat_approx"]; p["lon"] = p["lon_approx"]
            p["geocoded"] = False
    print(f"Geocoded {geocoded}/{len(projects)} projects ({geocoded/len(projects)*100:.0f}%)")


if __name__ == "__main__":
    main()
