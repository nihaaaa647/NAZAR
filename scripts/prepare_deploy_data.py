"""Build a small, deployable snapshot of data/ for a host with no room (or no
need) for the full 5.6 GB local image cache.

Only images actually referenced by data/duplicate_pairs.json are ever served —
the Evidence panel links images from pairs, never from images.json directly —
so this keeps just those, downscaled to a size that still reads clearly in the
evidence viewer (it displays at <=500px) without shipping full-resolution scans.
Everything else (works, signals, evidence pairs, personas) is copied byte-exact;
nothing about scoring or evidence changes, only the pixels served for "open
full-resolution evidence" get smaller.

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

    for name in ('scored_works.parquet', 'duplicate_pairs.json', 'personas.json'):
        shutil.copy2(DATA / name, out / name)

    print(f'{len(referenced)} evidence images: {before/1e6:.1f} MB -> {after/1e6:.1f} MB (max {args.max_dim}px, q{args.quality})')
    print(f'Deploy snapshot written to {out}')
    print(f'Point the backend at it with NAZAR_DATA_DIR={out}')

if __name__ == '__main__':
    main()
