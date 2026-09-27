"""
Satellite module, step 1 - real coordinate sourcing (see
docs/SATELLITE_VENDOR_MODULE_PLAN.md #1).

Pulls REAL, publicly-verifiable geotagged infrastructure coordinates to
ground the satellite-verification module. Not MPLADS data - MPLADS has no
public bulk geotag export. See docs/DATA_REALITY.md-style framing: every
row here is a real OpenStreetMap feature, never a fabricated coordinate.

Source: OpenStreetMap via the Overpass API. This is a deliberate deviation
from the plan's originally-named sources (Bhuvan NREGA, PMGSY GRRIS) -
both are gated behind government portal login credentials (BDO/DPC for
Bhuvan; equivalent for PMGSY OMMAS) that aren't publicly self-serve, so
they can't be pulled without someone's field-staff account. OSM is public,
requires no account, and covers exactly the categories the plan calls
"satellite-visible": dams/check-dams, community centres/halls, and named
rural roads. Attribution: (c) OpenStreetMap contributors, ODbL - keep
`source_scheme=openstreetmap` on every row so this is auditable downstream.

Categories pulled map to the plan's Branch A (satellite-visible, see
fraud_injection plan #4):
  - waterway=dam                              -> category=dam
  - amenity=community_centre                  -> category=community_centre
  - highway=tertiary|unclassified, named ways  -> category=road

Usage:
    python -m pipeline.harvest_geotags
    python -m pipeline.harvest_geotags --no-live   # cache only, no network
"""

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

OUT_DIR = Path("data/geotags")
OUT_PATH = OUT_DIR / "sourced_assets.csv"
SEED_CACHE_PATH = OUT_DIR / "_osm_seed_cache.json"

OVERPASS_ENDPOINTS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# (region_name, south, west, north, east) - Telangana/Bihar/Andhra Pradesh
# match the states already covered in the real MPLADS scrape (see
# docs/DATA_REALITY.md), so a future join against real MP/IDA metadata by
# state is at least geographically plausible.
BBOXES = [
    ("telangana", 17.0, 78.0, 18.5, 79.5),
    ("bihar", 25.0, 84.5, 26.0, 85.5),
    ("andhra_pradesh", 16.0, 80.0, 17.0, 81.0),
]

QUERY_TEMPLATE = """
[out:json][timeout:40];
(
  node["waterway"="dam"]({s},{w},{n},{e});
  way["waterway"="dam"]({s},{w},{n},{e});
  node["amenity"="community_centre"]({s},{w},{n},{e});
  way["amenity"="community_centre"]({s},{w},{n},{e});
  way["highway"~"^(tertiary|unclassified)$"]["name"]({s},{w},{n},{e});
);
out center 60;
"""


def categorize(tags: dict) -> str:
    if tags.get("waterway") == "dam":
        return "dam"
    if tags.get("amenity") == "community_centre":
        return "community_centre"
    if "highway" in tags:
        return "road"
    return "other"


def fetch_region_live(region: str, s: float, w: float, n: float, e: float) -> list[dict]:
    query = QUERY_TEMPLATE.format(s=s, w=w, n=n, e=e)
    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        for attempt in range(2):
            try:
                r = requests.get(endpoint, params={"data": query}, timeout=45)
                r.raise_for_status()
                payload = r.json()
                out = []
                for el in payload.get("elements", []):
                    lat = el.get("lat") if "lat" in el else el.get("center", {}).get("lat")
                    lon = el.get("lon") if "lon" in el else el.get("center", {}).get("lon")
                    if lat is None or lon is None:
                        continue
                    tags = el.get("tags", {})
                    out.append({
                        "type": el["type"], "id": el["id"], "lat": lat, "lon": lon,
                        "category": categorize(tags),
                        "name": tags.get("name") or tags.get("name:en") or "",
                        "region": region,
                        "observed_date": tags.get("start_date") or tags.get("date") or "",
                    })
                return out
            except Exception as exc:  # noqa: BLE001 - report and retry/fallback
                last_err = exc
                time.sleep(2)
    print(f"  live fetch failed for {region}: {last_err}", file=sys.stderr)
    return []


def load_seed_cache() -> list[dict]:
    if not SEED_CACHE_PATH.exists():
        return []
    payload = json.loads(SEED_CACHE_PATH.read_text(encoding="utf-8"))
    return [
        {**el, "observed_date": el.get("observed_date", "")}
        for el in payload["elements"]
    ]


def harvest(use_live: bool = True) -> pd.DataFrame:
    elements: list[dict] = []
    if use_live:
        for region, s, w, n, e in BBOXES:
            print(f"querying Overpass for {region}...")
            elements.extend(fetch_region_live(region, s, w, n, e))

    if not elements:
        print("live Overpass fetch produced nothing usable - falling back to "
              "the bundled real-OSM seed cache "
              f"({SEED_CACHE_PATH}, fetched 2026-09-25 via overpass.kumi.systems).")
        elements = load_seed_cache()

    if not elements:
        raise RuntimeError(
            "no coordinates available: live Overpass fetch failed and no seed "
            "cache found. Re-run with network access, or check "
            f"{SEED_CACHE_PATH} exists."
        )

    rows = []
    seen_osm_ids = set()
    for i, el in enumerate(elements, start=1):
        key = (el["type"], el["id"])
        if key in seen_osm_ids:
            continue
        seen_osm_ids.add(key)
        rows.append({
            "asset_id": f"osm_{i}",
            "lat": round(float(el["lat"]), 6),
            "lon": round(float(el["lon"]), 6),
            "source_scheme": "openstreetmap",
            "category": el["category"],
            "name": el.get("name", ""),
            "osm_type": el["type"],
            "osm_id": el["id"],
            "state_region": el.get("region", ""),
            "observed_date": el.get("observed_date", ""),
        })

    df = pd.DataFrame(rows)
    df = df[df["category"].isin(["dam", "community_centre", "road"])].reset_index(drop=True)
    df["asset_id"] = [f"osm_{i}" for i in range(1, len(df) + 1)]
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-live", action="store_true",
                         help="skip live Overpass queries, use the bundled seed cache only")
    args = parser.parse_args()

    df = harvest(use_live=not args.no_live)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"\nwrote {OUT_PATH} ({len(df)} real assets)")
    print(df["category"].value_counts().to_string())
    print(df["state_region"].value_counts().to_string())


if __name__ == "__main__":
    main()
