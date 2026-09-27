"""
Satellite module, step 3 - change-detection baseline (see
docs/SATELLITE_VENDOR_MODULE_PLAN.md #3).

NDVI diff + raw pixel diff between the t1/t2 red+nir crops
pipeline/fetch_satellite_pairs.py cached. Zero training, fully
explainable - matches the human-in-loop posture the rest of this project
already uses for photo-reuse confirmation (see ORB keypoint confirmation
in ml/cv/, docs/PROJECT_FEATURES.md). This is the baseline only; the
Siamese change-detection stretch goal (OSCD/LEVIR-CD weights) is not
implemented here.

Output per asset: {asset_id, ndvi_t1_mean, ndvi_t2_mean, ndvi_delta,
pixel_diff_score, change_detected, confidence, review_required}.
change_detected/confidence are a threshold call on ndvi_delta and
pixel_diff_score together - both signals must agree past a threshold
before flagging change, to reduce false positives from seasonal
vegetation swings alone (NDVI moves with monsoon/dry-season timing
regardless of any real construction).

This result is never auto-scored - review_required is always true, same
Confirm/Dismiss posture as every other signal in this project
(backend/main.py's investigations flow).

Usage:
    python -m ml.cv.satellite_change
"""

import json
from pathlib import Path

import numpy as np
import rasterio

CACHE_DIR = Path("data/satellite_cache")
MANIFEST_PATH = CACHE_DIR / "manifest.json"
OUT_PATH = Path("data/canonical/satellite_change_results.csv")

# NDVI delta and normalized pixel-diff thresholds tuned to be conservative
# (biased toward "review it" over "auto-clear it") since this is advisory,
# not a verdict - see the module-level docstring.
NDVI_DELTA_THRESHOLD = 0.15
PIXEL_DIFF_THRESHOLD = 0.25


def read_bands(tif_path: Path) -> tuple[np.ndarray, np.ndarray]:
    with rasterio.open(tif_path) as src:
        red = src.read(1).astype("float32")
        nir = src.read(2).astype("float32")
    return red, nir


def ndvi(red: np.ndarray, nir: np.ndarray) -> np.ndarray:
    denom = nir + red
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(denom == 0, 0.0, (nir - red) / denom)
    return result


def normalized_pixel_diff(red1, nir1, red2, nir2) -> float:
    """Mean absolute difference in reflectance, normalized to [0,1]-ish by
    the typical Sentinel-2 L2A digital-number ceiling (~10000)."""
    diff = np.abs(red1.astype("float32") - red2.astype("float32")) + \
           np.abs(nir1.astype("float32") - nir2.astype("float32"))
    return float(diff.mean() / (2 * 10000))


def score_asset(asset_id: str, entry: dict) -> dict:
    red1, nir1 = read_bands(Path(entry["t1"]["tif"]))
    red2, nir2 = read_bands(Path(entry["t2"]["tif"]))

    ndvi1, ndvi2 = ndvi(red1, nir1), ndvi(red2, nir2)
    ndvi1_mean, ndvi2_mean = float(ndvi1.mean()), float(ndvi2.mean())
    ndvi_delta = abs(ndvi2_mean - ndvi1_mean)

    pixel_diff_score = normalized_pixel_diff(red1, nir1, red2, nir2)

    change_detected = ndvi_delta > NDVI_DELTA_THRESHOLD and pixel_diff_score > PIXEL_DIFF_THRESHOLD
    # confidence: how far past both thresholds, capped at 1.0 - a rough
    # signal-strength readout, not a calibrated probability.
    confidence = min(1.0, 0.5 * (ndvi_delta / NDVI_DELTA_THRESHOLD) +
                      0.5 * (pixel_diff_score / PIXEL_DIFF_THRESHOLD)) if change_detected else 0.0

    return {
        "asset_id": asset_id,
        "category": entry.get("category"),
        "t1_date": entry["t1"]["datetime"][:10],
        "t2_date": entry["t2"]["datetime"][:10],
        "ndvi_t1_mean": round(ndvi1_mean, 4),
        "ndvi_t2_mean": round(ndvi2_mean, 4),
        "ndvi_delta": round(ndvi_delta, 4),
        "pixel_diff_score": round(pixel_diff_score, 4),
        "change_detected": change_detected,
        "confidence": round(confidence, 3),
        "review_required": True,
    }


def main() -> None:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"{MANIFEST_PATH} not found - run "
            "`python -m pipeline.fetch_satellite_pairs` first"
        )
    manifest = json.loads(MANIFEST_PATH.read_text())

    import pandas as pd
    rows = [score_asset(asset_id, entry) for asset_id, entry in manifest.items()]
    df = pd.DataFrame(rows)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"wrote {OUT_PATH} ({len(df)} assets scored)")
    print(f"  change_detected=True: {df['change_detected'].sum()} / {len(df)}")
    print(df.groupby("category")["change_detected"].mean().to_string())


if __name__ == "__main__":
    main()
