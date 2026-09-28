"""
Satellite module, step 2b - high-resolution before/after quicklooks.

Sentinel-2 (pipeline/fetch_satellite_pairs.py) is ~10m/pixel - a hard
sensor limit, not a processing choice. At that resolution a single
MPLADS-scale asset (a community hall, a short road segment) covers only a
handful of pixels; you cannot see individual buildings. Per a user
request for building-level visual detail, this script replaces the
human-viewable quicklook JPEGs with real, dated, high-resolution imagery
from Esri's "World Imagery Wayback" archive instead - commercial-grade
satellite/aerial captures (sub-meter to ~1m/pixel in most of urban/rural
India), released on a rolling schedule since 2014, each a real dated
snapshot, publicly served with no API key or account:
  config:  https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json
  tiles:   https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/WMTS/1.0.0/default028mm/MapServer/tile/{release_id}/{z}/{y}/{x}

This is a deliberate two-source design, not a mix-up:
  - Sentinel-2 red/nir bands (unchanged, still fetched by
    fetch_satellite_pairs.py) remain the ONLY input to the actual
    computational signal (ml/cv/satellite_change.py's NDVI/pixel-diff) -
    Wayback has no NIR band, so it cannot feed that math.
  - Wayback imagery is for the human reviewer's own eyes only: a real,
    dated, high-resolution picture of the same coordinate, to visually
    sanity-check what the Sentinel-based signal is talking about. It does
    not, by itself, change risk_score or change_detected.
Because these are two different real sources, their dates differ from
each other and from the Sentinel-2 pair - manifest.json keeps both
dates distinct (`t1.datetime` = Sentinel-2 capture used for NDVI,
`t1.rgb_datetime`/`t1.rgb_source` = what the quicklook JPEG actually
shows) so nothing displays a date the image wasn't actually taken on.

Not every location has a materially different capture between the two
chosen releases (Wayback updates coverage in waves, not globally on every
release) - two dates ~2.5 years apart were chosen specifically to
maximize the odds of a real difference, not to guarantee one.

Usage:
    python -m pipeline.fetch_highres_quicklooks [--limit N] [--asset-id ID] [--region REGION]
"""

import argparse
import io
import json
import math
import time
from pathlib import Path

import pandas as pd
import requests
from PIL import Image

ASSETS_PATH = Path("data/geotags/sourced_assets.csv")
CACHE_DIR = Path("data/satellite_cache")
MANIFEST_PATH = CACHE_DIR / "manifest.json"

TILE_URL = ("https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/"
            "WMTS/1.0.0/default028mm/MapServer/tile/{release_id}/{z}/{y}/{x}")
# A default python-requests UA gets 403'd inconsistently by this host even
# on tiles that genuinely exist; a browser-like UA clears it up.
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                 "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

# Picked from the 196 available Wayback releases (config fetched 2026-09-28):
# ~2.5 years apart, maximizing the chance real construction shows up between
# them, without cherry-picking per asset.
BEFORE_RELEASE = {"id": "41468", "date": "2024-01-18"}
AFTER_RELEASE = {"id": "26334", "date": "2026-08-05"}

ZOOM = 18          # ~0.6m/pixel - building-level detail; z19 403s for some releases/areas
TILE_GRID = 3      # 3x3 mosaic - gives enough margin that CROP_PX never
                    # overhangs the mosaic edge regardless of where the
                    # point falls within its center tile (a 2x2 grid could)
TILE_PX = 256       # Esri WMTS tile size
CROP_PX = 340       # final square crop out of the (2*256)=512px mosaic


def deg2tile(lat: float, lon: float, zoom: int) -> tuple[int, int, float, float]:
    """Standard Web Mercator slippy-map tile math. Returns (xtile, ytile,
    frac_x, frac_y) where frac_* is the point's fractional position within
    that tile (0-1), used to center the crop."""
    lat_rad = math.radians(lat)
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return int(x), int(y), x - int(x), y - int(y)


def fetch_tile(release_id: str, z: int, y: int, x: int, retries: int = 3) -> Image.Image | None:
    """Individual tiles can 403 even when neighboring tiles at the same
    release succeed - a given release only patches the tiles that actually
    changed, and the redirect Esri issues for an unpatched tile doesn't
    always resolve cleanly. Retry a few times (transient), then give up on
    just this one tile rather than the whole asset."""
    url = TILE_URL.format(release_id=release_id, z=z, y=y, x=x)
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=20, headers=REQUEST_HEADERS)
            if r.status_code == 200:
                return Image.open(io.BytesIO(r.content)).convert("RGB")
        except requests.RequestException:
            pass
        time.sleep(0.5 * (attempt + 1))
    return None


def fetch_mosaic(release_id: str, lat: float, lon: float) -> Image.Image:
    xtile, ytile, fx, fy = deg2tile(lat, lon, ZOOM)
    half = TILE_GRID // 2
    mosaic = Image.new("RGB", (TILE_GRID * TILE_PX, TILE_GRID * TILE_PX))
    n_missing = 0
    for dy in range(-half, TILE_GRID - half):
        for dx in range(-half, TILE_GRID - half):
            tile = fetch_tile(release_id, ZOOM, ytile + dy, xtile + dx)
            if tile is None:
                n_missing += 1
                continue
            mosaic.paste(tile, ((dx + half) * TILE_PX, (dy + half) * TILE_PX))
    if n_missing == TILE_GRID * TILE_GRID:
        raise RuntimeError(f"all {n_missing} tiles failed for release {release_id} at ({lat},{lon})")

    # Pixel position of the actual coordinate within the mosaic, then crop
    # a centered square around it.
    px = (half + fx) * TILE_PX
    py = (half + fy) * TILE_PX
    left, top = int(px - CROP_PX / 2), int(py - CROP_PX / 2)
    return mosaic.crop((left, top, left + CROP_PX, top + CROP_PX))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--asset-id", type=str, default=None)
    parser.add_argument("--region", type=str, default=None)
    parser.add_argument("--force", action="store_true", help="re-fetch even if already done")
    args = parser.parse_args()

    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"{MANIFEST_PATH} not found - run fetch_satellite_pairs.py first")
    manifest = json.loads(MANIFEST_PATH.read_text())

    assets = pd.read_csv(ASSETS_PATH)
    if args.asset_id:
        assets = assets[assets["asset_id"] == args.asset_id]
    if args.region:
        assets = assets[assets["state_region"] == args.region]
    if args.limit:
        assets = assets.head(args.limit)

    n_ok, n_fail, n_skip = 0, 0, 0
    for _, row in assets.iterrows():
        asset_id = row["asset_id"]
        if asset_id not in manifest:
            continue  # no Sentinel pair fetched for this asset yet
        entry = manifest[asset_id]
        if not args.force and entry.get("t1", {}).get("rgb_source") == "esri_wayback":
            n_skip += 1
            continue
        try:
            before_img = fetch_mosaic(BEFORE_RELEASE["id"], row["lat"], row["lon"])
            after_img = fetch_mosaic(AFTER_RELEASE["id"], row["lat"], row["lon"])
            before_img.save(CACHE_DIR / f"{asset_id}_t1_rgb.jpg", format="JPEG", quality=95)
            after_img.save(CACHE_DIR / f"{asset_id}_t2_rgb.jpg", format="JPEG", quality=95)
            entry["t1"]["rgb_source"] = "esri_wayback"
            entry["t1"]["rgb_datetime"] = BEFORE_RELEASE["date"]
            entry["t2"]["rgb_source"] = "esri_wayback"
            entry["t2"]["rgb_datetime"] = AFTER_RELEASE["date"]
            manifest[asset_id] = entry
            MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))
            n_ok += 1
            print(f"  {asset_id}: high-res quicklooks {BEFORE_RELEASE['date']} / {AFTER_RELEASE['date']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  {asset_id}: FAILED - {exc}")
            n_fail += 1
        time.sleep(0.15)

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))
    print(f"\n{n_ok} assets upgraded, {n_skip} already done, {n_fail} failed")


if __name__ == "__main__":
    main()
