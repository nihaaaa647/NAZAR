"""Build a small, deployable snapshot of data/ for a host with no room (or no
need) for the full 5.6 GB local image cache.

Only images actually referenced by data/duplicate_pairs.json are ever served —
the Evidence panel links images from pairs, never from images.json directly —
so this keeps just those, downscaled to a size that still reads clearly in the
evidence viewer (it displays at <=500px) without shipping full-resolution scans.
Everything else (works, signals, evidence pairs, personas, inefficiency findings)
is copied byte-exact; nothing about scoring or evidence changes, only the pixels
served for "open full-resolution evidence" get smaller. reports/inefficiency.json
(the corpus-wide stats behind GET /inefficiency/summary) isn't copied here — the
backend reads reports/ straight from the code checkout regardless of
NAZAR_DATA_DIR, same as reports/evaluation.json already does.

Also copies every other file backend/main.py's lifespan actually reads from
DATA (see that file for the authoritative list) - this script silently going
stale as new modules landed (data quality, cases, image evidence, satellite/
vendor) is exactly how those tabs ended up empty on a fresh deploy despite the
code being live: the backend degrades gracefully to "no data" when a file is
missing, so a stale deploy snapshot fails quietly, not loudly. satellite_cache/
images are already small compressed quicklook JPEGs (~a few hundred KB total
per asset) - copied byte-exact, no further downscaling needed.

Usage: python scripts/prepare_deploy_data.py [--out deploy_data] [--max-dim 1400] [--quality 82]
Then point a deployment at it with NAZAR_DATA_DIR=<out>.
"""
from __future__ import annotations
import argparse, json, shutil, sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='deploy_data')
    parser.add_argument('--max-dim', type=int, default=1400)
    parser.add_argument('--quality', type=int, default=82)
    args = parser.parse_args()
    out = (ROOT / args.out).resolve()

    for name in ('scored_works.parquet', 'duplicate_pairs.json', 'personas.json'):
        src = DATA / name
        if not src.exists():
            sys.exit(f'{src} missing — run scripts/pipeline.py first.')
    # inefficiency.json is separate from evidence images/pairs above (a disjoint
    # population — see scripts/pipeline.py's build_inefficiency) but just as small
    # to copy byte-exact; [] if the sanctioned-table join wasn't available.
    pairs = json.loads((DATA / 'duplicate_pairs.json').read_text(encoding='utf-8'))
    all_images = json.loads((DATA / 'images.json').read_text(encoding='utf-8'))

    referenced = {im['filename']: im for p in pairs for im in (p.get('images') or [])}
    by_filename = {im['filename']: im for im in all_images}
    missing = referenced.keys() - by_filename.keys()
    if missing:
        sys.exit(f'{len(missing)} evidence filenames have no images.json entry: {sorted(missing)[:5]}...')

    out.mkdir(parents=True, exist_ok=True)
    image_dir = out / 'image_cache'
    image_dir.mkdir(exist_ok=True)

    before = after = 0
    for filename in sorted(referenced):
        src = DATA / 'image_cache' / filename
        dst = image_dir / filename
        before += src.stat().st_size
        with Image.open(src) as img:
            img = img.convert('RGB')
            scale = min(1.0, args.max_dim / max(img.width, img.height))
            if scale < 1.0:
                img = img.resize((round(img.width * scale), round(img.height * scale)), Image.Resampling.LANCZOS)
            img.save(dst, 'JPEG', quality=args.quality, optimize=True)
        after += dst.stat().st_size

    # Trim images.json to just the referenced entries — the only ones GET
    # /image/{work_id}/{filename} will ever be asked to serve — but leave every
    # other field (work associations, phash, original width/height) untouched.
    trimmed_images = [im for im in all_images if im['filename'] in referenced]
    (out / 'images.json').write_text(json.dumps(trimmed_images, indent=2, ensure_ascii=False), encoding='utf-8')

    for name in ('scored_works.parquet', 'duplicate_pairs.json', 'personas.json', 'inefficiency.json',
                 'quality_alerts.json', 'lineage.json', 'work_directory.json',
                 'case_candidates.json', 'image_matches.json'):
        src = DATA / name
        if src.exists():
            shutil.copy2(src, out / name)
        else:
            print(f'  (skipping {name} - not present in {DATA}; that tab will show no data)')

    # canonical/ - satellite_works_scored.csv, vendor_network.csv. Optional:
    # the satellite module degrades to empty, not broken, if these are missing
    # (see docs/SATELLITE_MODULE_DATA_REALITY.md - this is itself a qualitative,
    # not corpus-scale, dataset, so copying it byte-exact is fine).
    canonical_src = DATA / 'canonical'
    if canonical_src.exists():
        canonical_out = out / 'canonical'
        canonical_out.mkdir(exist_ok=True)
        for name in ('satellite_works_scored.csv', 'vendor_network.csv'):
            src = canonical_src / name
            if src.exists():
                shutil.copy2(src, canonical_out / name)

    # satellite_cache/ - real Sentinel-2 before/after quicklook JPEGs + the
    # manifest.json that maps asset_id -> scene dates. Already small compressed
    # thumbnails (see pipeline/fetch_satellite_pairs.py), copied byte-exact.
    sat_cache_src = DATA / 'satellite_cache'
    if sat_cache_src.exists():
        sat_cache_out = out / 'satellite_cache'
        if sat_cache_out.exists():
            shutil.rmtree(sat_cache_out)
        shutil.copytree(sat_cache_src, sat_cache_out,
                         ignore=shutil.ignore_patterns('*_t1.tif', '*_t2.tif'))
        n_files = sum(1 for _ in sat_cache_out.iterdir())
        print(f'  satellite_cache/: {n_files} files copied (rgb quicklooks + manifest.json, raw band .tif excluded)')

    print(f'{len(referenced)} evidence images: {before/1e6:.1f} MB -> {after/1e6:.1f} MB (max {args.max_dim}px, q{args.quality})')
    print(f'Deploy snapshot written to {out}')
    print(f'Point the backend at it with NAZAR_DATA_DIR={out}')

if __name__ == '__main__':
    main()
