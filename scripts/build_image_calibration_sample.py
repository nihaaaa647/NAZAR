"""Phase 5 A.1: reproducible adjudication workflow for real image-match
pairs. This does NOT measure precision - it draws a stratified sample of
REAL candidate pairs from data/image_matches.json and writes a CSV with
empty human_label/reviewer_reason columns for a person to fill in by
actually looking at the images. Until that happens, real-pair precision is
unmeasured - see the printed notice and docs/DETECTOR_VALIDATION.md.

Strata actually distinguishable in this pipeline's output today:
  - classification (confirmed_visual_correspondence / rejected_generic_similarity / rejected_watermark)
  - phash_distance bucket (0 / 1-3 / 4-6)
  - matched_area_coverage bucket (<0.05 / 0.05-0.2 / >0.2)

Strata the Phase 5 brief asks for that this pipeline cannot currently
stratify by, disclosed rather than faked:
  - work category (not carried into image_matches.json - would need a join
    against data/canonical/works.csv's WORK_CATEGORY per work_id)
  - same-work pairs (photo_duplicates() only ever compares across DIFFERENT
    work_ids today - see pipeline/image_evidence.py's module docstring on
    "compare primarily cross-work-ID, same-work as separate context"; the
    same-work comparison was never separately implemented)
  - low-texture images (not a property image_matches.json records per pair)

Usage: python scripts/build_image_calibration_sample.py [--n 60]
"""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
OUT = ROOT / 'reports' / 'image_calibration_sample.csv'


def phash_bucket(d):
    if d is None: return 'unknown'
    if d == 0: return '0'
    if d <= 3: return '1-3'
    return '4-6'


def area_bucket(a):
    if a is None: return 'unknown'
    if a < 0.05: return '<0.05'
    if a < 0.2: return '0.05-0.2'
    return '>0.2'


def build(n_target=60, seed=42):
    import random
    matches = json.loads((DATA / 'image_matches.json').read_text(encoding='utf-8'))
    strata = {}
    for m in matches:
        key = (m['classification'], phash_bucket(m['phash_distance']), area_bucket(m['matched_area_coverage']))
        strata.setdefault(key, []).append(m)

    rng = random.Random(seed)
    per_stratum = max(1, n_target // max(len(strata), 1))
    sample = []
    for key, items in strata.items():
        rng.shuffle(items)
        sample.extend(items[:per_stratum])
    sample = sample[:n_target] if len(sample) > n_target else sample

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['match_id', 'work_id_a', 'work_id_b', 'image_id_a', 'image_id_b',
                    'phash_distance', 'good_matches', 'inliers', 'inlier_ratio', 'matched_area_coverage',
                    'machine_classification', 'preprocessing_version', 'detector_version',
                    'human_label', 'reviewer_reason'])
        for m in sample:
            w.writerow([m['match_id'], m['work_id_a'], m['work_id_b'], m['image_id_a'], m['image_id_b'],
                        m['phash_distance'], m['good_matches'], m['inliers'], m['inlier_ratio'], m['matched_area_coverage'],
                        m['classification'], m['preprocessing_version'], m['detector_version'], '', ''])
    print(f'Wrote {len(sample)} pairs across {len(strata)} strata to {OUT}')
    print('human_label/reviewer_reason are BLANK - fill them in by opening each pair '
          '(e.g. via the Image Evidence Workspace) before drawing any precision conclusion.')
    print('Strata this sample covers:', sorted({s[0] for s in strata}))
    print('Real-pair precision remains unmeasured until this file is filled in and scored.')
    return sample


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=60)
    args = p.parse_args()
    build(n_target=args.n)
