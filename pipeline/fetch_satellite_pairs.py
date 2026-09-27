"""
Satellite module, step 2 - real before/after imagery retrieval (see
docs/SATELLITE_VENDOR_MODULE_PLAN.md #2).

For each asset in data/geotags/sourced_assets.csv, pulls two real Sentinel-2
scenes (earliest and latest available, low cloud cover) and caches a small
windowed crop around the coordinate.

Source: Element84's "Earth Search" STAC API + the public `sentinel-cogs`
AWS Open Data bucket. This is a deliberate deviation from the plan's
originally-named source (Copernicus Data Space Ecosystem / Sentinel Hub) -
both require a free account and an OAuth token to download any pixel data
(catalog search is open, but every asset download - even the small
quicklook JPEG - returned "Token not found" without one), and creating
accounts on the user's behalf is out of scope for this agent. Earth Search
mirrors the same Sentinel-2 L2A archive as a fully public, no-auth AWS
Open Data bucket - same imagery, same resolution, no login. Confirmed
directly: https://sentinel-cogs.s3.us-west-2.amazonaws.com/... serves
without credentials.

Caveat this module must carry forward into its own DATA_REALITY-style
note (see docs/SATELLITE_MODULE_DATA_REALITY.md): Sentinel-2 is ~10m/pixel.
A single MPLADS-scale asset (a streetlight, a small culvert) is far below
that resolution - only larger footprint changes (new road segments, filled
check-dams, a new community-hall roof) are plausibly visible at all. This
is exactly why the module's Branch A/B split exists.

Cache layout (matches the existing data/image_cache/ discipline):
  data/satellite_cache/{asset_id}_t1.tif       - 2-band (red, nir) crop, date 1
  data/satellite_cache/{asset_id}_t2.tif       - 2-band (red, nir) crop, date 2
  data/satellite_cache/{asset_id}_t1_rgb.jpg   - true-color quicklook crop, date 1
  data/satellite_cache/{asset_id}_t2_rgb.jpg   - true-color quicklook crop, date 2
  data/satellite_cache/manifest.json           - per-asset scene ids/dates/cloud cover

Usage:
    python -m pipeline.fetch_satellite_pairs [--limit N] [--asset-id ID]
"""

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
from PIL import Image
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window

# GDAL's /vsicurl remote reads don't inherit `requests`' timeouts - without
# these, a stalled connection to the COG bucket can hang far longer than
# any caller expects. Bound it explicitly.
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "15")
os.environ.setdefault("GDAL_HTTP_CONNECTTIMEOUT", "10")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

ASSETS_PATH = Path("data/geotags/sourced_assets.csv")
CACHE_DIR = Path("data/satellite_cache")
MANIFEST_PATH = CACHE_DIR / "manifest.json"

STAC_SEARCH_URL = "https://earth-search.aws.element84.com/v1/search"
COLLECTION = "sentinel-2-l2a"
MAX_CLOUD_COVER = 30
WINDOW_PX = 128  # ~1.28km square at 10m/px - enough context around one asset
SEARCH_BBOX_DEG = 0.02  # ~2km search box around the point, for the STAC query


def search_scenes(lat: float, lon: float, limit: int = 20) -> list[dict]:
    bbox = [lon - SEARCH_BBOX_DEG, lat - SEARCH_BBOX_DEG,
            lon + SEARCH_BBOX_DEG, lat + SEARCH_BBOX_DEG]
    params = {
        "collections": COLLECTION,
        "bbox": ",".join(str(b) for b in bbox),
        "limit": limit,
        "sortby": "-properties.datetime",
        "query": json.dumps({"eo:cloud_cover": {"lt": MAX_CLOUD_COVER}}),
    }
    r = requests.get(STAC_SEARCH_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("features", [])


def pick_pair(scenes: list[dict]) -> tuple[dict, dict] | None:
    """Earliest and latest low-cloud scene, maximizing the time gap between
    them (a wider gap gives change-detection more room to find something
    real, at the cost of more seasonal/vegetation noise)."""
    if len(scenes) < 2:
        return None
    scenes_sorted = sorted(scenes, key=lambda s: s["properties"]["datetime"])
    return scenes_sorted[0], scenes_sorted[-1]


def _point_to_pixel(src, lat: float, lon: float) -> tuple[int, int]:
    """lat/lon are WGS84; Sentinel-2 COGs are in a per-tile UTM CRS -
    reproject the point before indexing, or every window lands off-grid."""
    xs, ys = warp_transform("EPSG:4326", src.crs, [lon], [lat])
    return src.index(xs[0], ys[0])


def read_window(href: str, lat: float, lon: float, size_px: int):
    with rasterio.open(href) as src:
        row, col = _point_to_pixel(src, lat, lon)
        half = size_px // 2
        window = Window(col - half, row - half, size_px, size_px)
        arr = src.read(1, window=window, boundless=True, fill_value=0)
        transform = src.window_transform(window)
        return arr, transform, src.crs


def save_band_pair(asset_id: str, scene: dict, lat: float, lon: float, tag: str) -> dict:
    assets = scene["assets"]
    red, transform, crs = read_window(assets["red"]["href"], lat, lon, WINDOW_PX)
    nir, _, _ = read_window(assets["nir"]["href"], lat, lon, WINDOW_PX)

    stacked = np.stack([red, nir]).astype("uint16")
    out_tif = CACHE_DIR / f"{asset_id}_{tag}.tif"
    profile = {
        "driver": "GTiff", "height": WINDOW_PX, "width": WINDOW_PX,
        "count": 2, "dtype": "uint16", "crs": crs, "transform": transform,
    }
    with rasterio.open(out_tif, "w", **profile) as dst:
        dst.write(stacked)
        dst.descriptions = ("red", "nir")

    out_jpg = CACHE_DIR / f"{asset_id}_{tag}_rgb.jpg"
    thumb_href = assets.get("thumbnail", {}).get("href")
    if thumb_href:
        # scene-wide quicklook (fast, single GET) rather than a windowed
        # crop from the full-res visual COG - much cheaper over the
        # network, at the cost of not being tightly cropped to the asset.
        resp = requests.get(thumb_href, timeout=30)
        resp.raise_for_status()
        out_jpg.write_bytes(resp.content)
    else:
        rgb = read_visual_window(assets["visual"]["href"], lat, lon, WINDOW_PX)
        Image.fromarray(rgb).save(out_jpg, format="JPEG", quality=85)

    return {
        "scene_id": scene["id"],
        "datetime": scene["properties"]["datetime"],
        "cloud_cover": scene["properties"].get("eo:cloud_cover"),
        "tif": str(out_tif), "rgb": str(out_jpg),
    }


def read_visual_window(href: str, lat: float, lon: float, size_px: int) -> np.ndarray:
    with rasterio.open(href) as src:
        row, col = _point_to_pixel(src, lat, lon)
        half = size_px // 2
        window = Window(col - half, row - half, size_px, size_px)
        arr = src.read([1, 2, 3], window=window, boundless=True, fill_value=0)
    return np.moveaxis(arr, 0, -1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="cap number of assets processed")
    parser.add_argument("--asset-id", type=str, default=None, help="process a single asset_id")
    args = parser.parse_args()

    assets = pd.read_csv(ASSETS_PATH)
    if args.asset_id:
        assets = assets[assets["asset_id"] == args.asset_id]
    if args.limit:
        assets = assets.head(args.limit)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {}

    n_ok, n_fail = 0, 0
    for _, row in assets.iterrows():
        asset_id = row["asset_id"]
        if asset_id in manifest:
            continue
        try:
            scenes = search_scenes(row["lat"], row["lon"])
            pair = pick_pair(scenes)
            if pair is None:
                print(f"  {asset_id}: fewer than 2 usable scenes found, skipping")
                n_fail += 1
                continue
            t1_scene, t2_scene = pair
            t1 = save_band_pair(asset_id, t1_scene, row["lat"], row["lon"], "t1")
            t2 = save_band_pair(asset_id, t2_scene, row["lat"], row["lon"], "t2")
            manifest[asset_id] = {
                "lat": row["lat"], "lon": row["lon"], "category": row["category"], "t1": t1, "t2": t2,
            }
            MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))
            n_ok += 1
            print(f"  {asset_id} ({row['category']}): t1={t1['datetime'][:10]} t2={t2['datetime'][:10]}", flush=True)
        except Exception as exc:  # noqa: BLE001 - keep going, report at the end
            print(f"  {asset_id}: FAILED - {exc}")
            n_fail += 1
        time.sleep(0.2)  # be polite to the public bucket / STAC API

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, default=str))
    print(f"\nwrote {MANIFEST_PATH}: {n_ok} assets fetched this run, "
          f"{len(manifest)} total cached, {n_fail} failed/skipped")


if __name__ == "__main__":
    main()
