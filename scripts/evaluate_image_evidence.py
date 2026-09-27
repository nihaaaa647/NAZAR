"""Phase 4 section F: a synthetic, clearly-labelled calibration/negative-
control set for pipeline/image_evidence.py's ORB+RANSAC classifier.

This corpus has no curated ground-truth image-duplication labels (the real
attachments are just whatever the source portal happened to store), so this
evaluation set is entirely synthetically generated - every image is built
here, in-memory, with a known ground-truth relationship, and clearly labelled
as such throughout. It is NOT a claim about the real corpus's accuracy; it is
a calibration/regression check on the classifier itself. See docs/DECISIONS.md
(Phase 4 entry) for why a synthetic set was used instead of real photos, and
"Remaining limitations" in the completion report for what this does and
doesn't prove.

Run: python -m scripts.evaluate_image_evidence
Writes reports/image_evidence_calibration.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.image_evidence import classify_image_pair, validate_image_bytes  # noqa: E402

OUT_DIR = ROOT / 'reports'
CACHE_DIR = ROOT / '.tmp_image_evidence_eval'  # scratch only, never data/image_cache


def _textured(seed, w=900, h=1200, n_shapes=25):
    rng = np.random.default_rng(seed)
    img = (rng.random((h, w)) * 255).astype('uint8')
    for _ in range(n_shapes):
        x, y = rng.integers(0, w - 60), rng.integers(0, h - 60)
        cv2.rectangle(img, (x, y), (x + 45, y + 45), int(rng.integers(0, 255)), -1)
        cv2.circle(img, (int(x + 20), int(y + 20)), 12, int(rng.integers(0, 255)), -1)
    return img


def _watermarked(seed, w=900, h=1200, text='Scanned with OKEN Scanner'):
    img = _textured(seed, w, h, n_shapes=15)
    cv2.putText(img, text, (10, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255,), 2)
    cv2.putText(img, text, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255,), 2)
    return img


def build_calibration_set(cache_dir: Path) -> list[dict]:
    """Returns [{name, description, path_a, path_b, ground_truth_same_evidence,
    expected_classification_in}]. ground_truth_same_evidence: whether the pair
    SHOULD be treated as the same underlying evidence (duplicate/reused photo),
    independent of which technical classification produces that outcome."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cases = []

    def save(name, img):
        path = cache_dir / f'{name}.jpg'
        cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        return path

    base = _textured(1)
    p_exact_a, p_exact_b = save('exact_a', base), save('exact_b', base)
    cases.append(dict(name='exact_duplicate', description='Byte-identical content (would be caught upstream as photo_identical by MD5; included here to confirm ORB also confirms it).',
                       path_a=p_exact_a, path_b=p_exact_b, ground_truth_same_evidence=True,
                       expected_classification_in={'confirmed_visual_correspondence'}))

    resized = cv2.resize(base, (450, 600))
    resized = cv2.resize(resized, (900, 1200))
    p_resized = save('resized_recompressed', resized)
    cases.append(dict(name='resized_recompressed_duplicate', description='Same content, downscaled+upscaled and JPEG-recompressed.',
                       path_a=p_exact_a, path_b=p_resized, ground_truth_same_evidence=True,
                       expected_classification_in={'confirmed_visual_correspondence'}))

    cropped = base[40:1160, 40:860]
    cropped = cv2.resize(cropped, (900, 1200))
    p_cropped = save('minor_crop', cropped)
    cases.append(dict(name='minor_crop_duplicate', description='Same content, cropped ~4-5% from each edge.',
                       path_a=p_exact_a, path_b=p_cropped, ground_truth_same_evidence=True,
                       expected_classification_in={'confirmed_visual_correspondence'}))

    wm_a, wm_b = _watermarked(10), _watermarked(20)
    p_wm_a, p_wm_b = save('watermark_a', wm_a), save('watermark_b', wm_b)
    cases.append(dict(name='watermark_only_similarity', description='Different random content, identical scanner-watermark text top+bottom. '
                       'Accepts either rejected_watermark or rejected_generic_similarity as a pass: both are zero-risk outcomes; which specific '
                       'label applies depends on how much the rest of the image competes with the watermark text for ORB\'s top-N keypoints - '
                       'see docs/DECISIONS.md\'s Phase 4 entry for the measured case where a busy background produced rejected_generic_similarity '
                       'instead of rejected_watermark, still correctly zero-risk either way.',
                       path_a=p_wm_a, path_b=p_wm_b, ground_truth_same_evidence=False,
                       expected_classification_in={'rejected_watermark', 'rejected_generic_similarity'}))

    infra_a, infra_b = _textured(100, n_shapes=25), _textured(200, n_shapes=25)
    p_infra_a, p_infra_b = save('infra_a', infra_a), save('infra_b', infra_b)
    cases.append(dict(name='unrelated_generic_infrastructure', description='Two unrelated images built with the same generation recipe (simulating two different roads/buildings that could superficially look alike).',
                       path_a=p_infra_a, path_b=p_infra_b, ground_truth_same_evidence=False,
                       expected_classification_in={'rejected_generic_similarity', 'insufficient_features'}))

    before, after = _textured(300, n_shapes=10), _textured(400, n_shapes=40)
    p_before, p_after = save('legit_before', before), save('legit_after', after)
    cases.append(dict(name='legitimate_before_after', description='Two genuinely different scenes (simulating a legitimate before/after progress pair) - must NOT be flagged as reused evidence.',
                       path_a=p_before, path_b=p_after, ground_truth_same_evidence=False,
                       expected_classification_in={'rejected_generic_similarity', 'insufficient_features'}))

    blank_a = np.full((1200, 900), 130, dtype='uint8')
    blank_b = np.full((1200, 900), 128, dtype='uint8')
    p_blank_a, p_blank_b = save('low_texture_a', blank_a), save('low_texture_b', blank_b)
    cases.append(dict(name='low_texture_pair', description='Two low-texture/near-blank images - too few keypoints to attempt a match.',
                       path_a=p_blank_a, path_b=p_blank_b, ground_truth_same_evidence=False,
                       expected_classification_in={'insufficient_features'}))

    p_corrupt = cache_dir / 'corrupt.jpg'
    p_corrupt.write_bytes(b'this is not a valid jpeg file')
    cases.append(dict(name='corrupted_file', description='One file is not a decodable image at all.',
                       path_a=p_corrupt, path_b=p_exact_a, ground_truth_same_evidence=False,
                       expected_classification_in={'processing_failed'}))

    return cases


def run_evaluation(cache_dir: Path = CACHE_DIR) -> dict:
    cases = build_calibration_set(cache_dir)
    results = []
    start = time.perf_counter()
    for case in cases:
        t0 = time.perf_counter()
        result = classify_image_pair(case['path_a'], case['path_b'])
        elapsed = time.perf_counter() - t0
        predicted_same_evidence = result.classification == 'confirmed_visual_correspondence'
        results.append({
            'name': case['name'], 'description': case['description'],
            'ground_truth_same_evidence': case['ground_truth_same_evidence'],
            'expected_classification_in': sorted(case['expected_classification_in']),
            'actual_classification': result.classification,
            'matches_expectation': result.classification in case['expected_classification_in'],
            'predicted_same_evidence': predicted_same_evidence,
            'good_matches': result.good_matches, 'inliers': result.inliers,
            'inlier_ratio': result.inlier_ratio, 'matched_area_coverage': result.matched_area_coverage,
            'elapsed_seconds': round(elapsed, 3),
        })
    total_elapsed = time.perf_counter() - start

    n = len(results)
    correct = sum(r['matches_expectation'] for r in results)
    positives = [r for r in results if r['ground_truth_same_evidence']]
    negatives = [r for r in results if not r['ground_truth_same_evidence']]
    true_positives = sum(1 for r in positives if r['predicted_same_evidence'])
    false_positives = sum(1 for r in negatives if r['predicted_same_evidence'])
    watermark_cases = [r for r in results if 'watermark' in r['name']]
    watermark_rejected = sum(1 for r in watermark_cases if r['actual_classification'] == 'rejected_watermark')
    watermark_zero_risk = sum(1 for r in watermark_cases if not r['predicted_same_evidence'])
    generic_infra_cases = [r for r in results if r['name'] == 'unrelated_generic_infrastructure']
    generic_false_matches = sum(1 for r in generic_infra_cases if r['predicted_same_evidence'])
    processing_failures = sum(1 for r in results if r['actual_classification'] == 'processing_failed')

    summary = {
        'label': 'SYNTHETIC calibration set - not derived from or representative of real MPLADS attachments. '
                 'Measures the classifier\'s own behavior on known-relationship pairs, not real-corpus accuracy.',
        'case_count': n,
        'cases_matching_expected_classification': correct,
        'phash_candidate_recall_note': 'Not measured here - this set is small enough that every pair was run through '
                                        'ORB directly; pHash bucketing recall on the real corpus is reported separately '
                                        'in reports/pipeline.json (tier2_candidates_before_gating vs after).',
        'orb_confirmation_precision': round(true_positives / max(len(positives), 1), 3),
        'orb_confirmation_recall': round(true_positives / max(len(positives), 1), 3),
        'watermark_only_specifically_labelled_rejected_watermark_rate': round(watermark_rejected / max(len(watermark_cases), 1), 3),
        'watermark_only_zero_risk_rate': round(watermark_zero_risk / max(len(watermark_cases), 1), 3),
        'watermark_labelling_note': 'A watermark-only pair may classify as rejected_generic_similarity instead of '
                                     'rejected_watermark when the rest of the image is busy enough to crowd the '
                                     'watermark text out of ORB\'s top-N keypoints - still zero-risk either way; '
                                     'watermark_only_zero_risk_rate is the metric that actually matters for safety.',
        'false_matches_on_generic_infrastructure': generic_false_matches,
        'false_positive_count_overall': false_positives,
        'processing_failures': processing_failures,
        'average_candidate_pairs_per_image_note': 'One pair evaluated per case here by design (a curated set, not a '
                                                    'corpus scan) - see reports/pipeline.json\'s tier2/tier3 stats for '
                                                    'the real corpus\'s actual candidates-per-image distribution.',
        'batch_runtime_seconds': round(total_elapsed, 3),
        'cases': results,
    }
    return summary


def main():
    summary = run_evaluation()
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / 'image_evidence_calibration.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if k != 'cases'}, indent=2))
    for case in summary['cases']:
        flag = 'OK' if case['matches_expectation'] else 'MISMATCH'
        print(f"[{flag}] {case['name']}: {case['actual_classification']} (expected one of {case['expected_classification_in']})")


if __name__ == '__main__':
    main()
