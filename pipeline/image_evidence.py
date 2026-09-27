"""Phase 4: image evidence intelligence - validation, scanner-watermark
masking, pHash candidate retrieval, and ORB geometric confirmation, with
every threshold and detector version stored on the result.

Design principles this module exists to enforce:
  - pHash is candidate retrieval ONLY. A pHash match, by itself, is never
    scored (pipeline/cases.py never counts a 'candidate_only' signal toward
    case creation).
  - ORB + RANSAC is the only thing that can promote a candidate to
    'confirmed_visual_correspondence' - and even then that phrase means
    exactly what CLASSIFICATION_MEANINGS says below, never "duplicate work"
    or "fraud".
  - A scanner-app watermark region (top/bottom border strip - "Scanned with
    OKEN Scanner", a CamScanner logo, etc.) is masked out BEFORE keypoints
    are computed, so a match confined to that region can never look like a
    real content match. This is a heuristic border mask, not OCR - no text
    recognition is performed; see WATERMARK_BORDER_FRACTION below for why.
  - Everything here is read-only with respect to source images: masking is
    applied only to an in-memory copy used for keypoint detection, never
    written back to the cached JPEG or the original source file.
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

# --- versions --------------------------------------------------------------
# Bump any of these when the corresponding logic changes; every stored image
# and match record carries the version(s) that produced it (Phase 4 mandatory
# safeguard #7 - "store all thresholds and detector versions").
PREPROCESSING_VERSION = 'image-preprocess-v1'   # validation + watermark masking
PHASH_VERSION = 'phash-v1'                       # unchanged from Phase 1 (8x8 DCT, 32x32 grayscale)
MATCH_DETECTOR_VERSION = 'image-match-v2'        # ORB+RANSAC+masking+matched-area classification

# --- thresholds (configurable, versioned - never presented as a fixed standard) ---
MIN_IMAGE_DIM = 150  # below this on either side, an image is watermark-strip-shaped, not photo evidence.
# Suggested initial pHash bucketing distance for calibration - see
# scripts/pipeline.py's data-driven percentile-based threshold, which
# supersedes this fixed number in the real pipeline. Kept here only as the
# module-level default for standalone/test use.
PHASH_DISTANCE_THRESHOLD = 6
ORB_MIN_GOOD_MATCHES = 100
ORB_MIN_INLIER_RATIO = 0.2
ORB_RATIO_TEST = 0.75
# A confirmed match whose inlier keypoints occupy less than this fraction of
# the smaller image's area is concentrated in a tiny region - a corner stamp,
# a repeated form header, a border artifact - not genuine shared content, even
# if the match count alone cleared ORB_MIN_GOOD_MATCHES. This is what turns a
# "border-only correspondence" into `rejected_generic_similarity` instead of
# `confirmed_visual_correspondence`.
MIN_MATCHED_AREA_COVERAGE = 0.05
# Top and bottom border strip masked out before keypoint detection - a
# heuristic geometry (scanner-app footers/headers are laid out along the
# horizontal edges of the page in every sample seen in this corpus), not OCR
# text detection. Documented limitation: a watermark placed elsewhere (e.g. a
# diagonal center stamp) would not be masked by this alone.
WATERMARK_BORDER_FRACTION = 0.10

CLASSIFICATIONS = frozenset({
    'candidate_only', 'confirmed_visual_correspondence', 'rejected_watermark',
    'rejected_generic_similarity', 'insufficient_features', 'processing_failed',
})
# Exact human-facing meaning of each classification - shown in the workspace
# and never rephrased into a fraud/duplicate-work claim.
CLASSIFICATION_MEANINGS = {
    'candidate_only': 'A perceptual-hash match retrieved this pair as worth checking. No geometric confirmation has run yet, or it did not clear the confirmation bar - this carries zero risk on its own.',
    'confirmed_visual_correspondence': 'The images contain geometrically corresponding visual content and require human review. This does not mean duplicate work or fraud.',
    'rejected_watermark': 'The only geometric correspondence found is inside the masked scanner-watermark/border region - not the photographed content itself.',
    'rejected_generic_similarity': 'A correspondence was found, but it is concentrated in too small an area of the image to represent genuine shared content (e.g. a repeated form header or template edge).',
    'insufficient_features': 'Too few keypoints could be extracted from one or both images to attempt a geometric match (e.g. a low-texture or near-blank image).',
    'processing_failed': 'The image(s) could not be decoded or processed.',
}


def image_id(md5_hex: str) -> str:
    """Content-addressed - the same bytes always produce the same id, across
    every source work_id that happens to reference them."""
    return md5_hex


def match_id(image_id_a: str, image_id_b: str, preprocessing_version: str = PREPROCESSING_VERSION,
             detector_version: str = MATCH_DETECTOR_VERSION) -> str:
    """Deterministic and order-independent: the same image pair, processed by
    the same versions, always gets the same id across pipeline reruns - so a
    reviewer decision keyed to it survives a rerun. Changes when either
    version changes (a materially different pipeline needs a fresh identity,
    not a silently-mutated old one)."""
    a, b = sorted([image_id_a, image_id_b])
    payload = f'{a}\x1f{b}\x1f{preprocessing_version}\x1f{detector_version}'
    return hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]


@dataclass
class ImageValidation:
    valid: bool
    format: str | None = None
    width: int | None = None
    height: int | None = None
    decodable: bool = False
    meets_min_dimension: bool = False
    md5: str | None = None
    status: str = 'invalid'  # 'valid' | 'invalid' | 'below_minimum_dimension'
    reason: str | None = None


def validate_image_bytes(raw: bytes) -> ImageValidation:
    """MIME/format sniffed from file CONTENT (PIL's format detection reads
    the file header, not the extension), decode attempted, dimensions
    checked. Never raises - every failure mode becomes a evidence-quality
    result (Phase 4 mandatory safeguard #6 territory: an invalid image is a
    data-quality fact, not a fraud signal)."""
    if not raw:
        return ImageValidation(valid=False, status='invalid', reason='Empty file.')
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img.load()
            fmt, width, height = img.format, img.width, img.height
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        return ImageValidation(valid=False, decodable=False, status='invalid', reason=f'Could not decode: {exc}')
    md5 = hashlib.md5(raw).hexdigest()
    meets_min = min(width, height) >= MIN_IMAGE_DIM
    return ImageValidation(valid=True, format=fmt, width=width, height=height, decodable=True,
                            meets_min_dimension=meets_min, md5=md5,
                            status='valid' if meets_min else 'below_minimum_dimension',
                            reason=None if meets_min else f'Smaller dimension {min(width, height)}px < {MIN_IMAGE_DIM}px floor.')


def watermark_mask_regions(width: int, height: int, border_fraction: float = WATERMARK_BORDER_FRACTION):
    """Top and bottom border rectangles, in (x0, y0, x1, y1) pixel
    coordinates, to exclude from keypoint detection. A heuristic geometric
    mask, not OCR text-region detection - see module docstring."""
    band = max(1, int(round(height * border_fraction)))
    return [(0, 0, width, band), (0, max(0, height - band), width, height)]


def _keypoints_outside_mask(keypoints, descriptors, masks):
    if not masks or descriptors is None:
        return keypoints, descriptors
    keep = [i for i, kp in enumerate(keypoints) if not _in_any_mask(kp.pt[0], kp.pt[1], masks)]
    if not keep:
        return [], None
    return [keypoints[i] for i in keep], descriptors[keep]


def _in_any_mask(x, y, masks):
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in masks)


def _bbox_area(points):
    if len(points) == 0:
        return 0.0
    xs, ys = points[:, 0], points[:, 1]
    return float(max(xs.max() - xs.min(), 1.0) * max(ys.max() - ys.min(), 1.0))


@dataclass
class MatchResult:
    classification: str
    good_matches: int = 0
    inliers: int = 0
    inlier_ratio: float = 0.0
    matched_area_coverage: float = 0.0
    keypoints_a: int = 0
    keypoints_b: int = 0
    masked_keypoints_excluded_a: int = 0
    masked_keypoints_excluded_b: int = 0
    reason: str = ''
    risk_eligible: bool = False


def _orb_pass(img_a, img_b, masks_a, masks_b, ratio_test):
    """One ORB+BFMatcher+RANSAC pass, with masked-region keypoints excluded
    from the candidate pool entirely before matching (Phase 4 requirement:
    "exclude keypoints inside masked regions"). Returns
    (good, inliers, inlier_ratio, coverage, kp_a, kp_b, excluded_a, excluded_b)."""
    orb = cv2.ORB_create(nfeatures=1500)
    kp_a_raw, des_a_raw = orb.detectAndCompute(img_a, None)
    kp_b_raw, des_b_raw = orb.detectAndCompute(img_b, None)
    kp_a, des_a = _keypoints_outside_mask(kp_a_raw, des_a_raw, masks_a)
    kp_b, des_b = _keypoints_outside_mask(kp_b_raw, des_b_raw, masks_b)
    excluded_a, excluded_b = len(kp_a_raw or []) - len(kp_a), len(kp_b_raw or []) - len(kp_b)
    if des_a is None or des_b is None or len(kp_a) < 10 or len(kp_b) < 10:
        return None, kp_a, kp_b, excluded_a, excluded_b
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(des_a, des_b, k=2)
    good = [m for m, n in (pair for pair in matches if len(pair) == 2) if m.distance < ratio_test * n.distance]
    if len(good) < 4:
        return {'good': good, 'inliers': 0, 'inlier_ratio': 0.0, 'coverage': 0.0}, kp_a, kp_b, excluded_a, excluded_b
    src = np.float32([kp_a[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_b[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    inlier_mask = mask.ravel().astype(bool) if mask is not None else np.zeros(len(good), dtype=bool)
    inliers = int(inlier_mask.sum())
    inlier_ratio = inliers / len(good) if good else 0.0
    coverage = _bbox_area(src[inlier_mask].reshape(-1, 2)) / max(img_a.shape[0] * img_a.shape[1], 1) if inliers else 0.0
    return {'good': good, 'inliers': inliers, 'inlier_ratio': inlier_ratio, 'coverage': coverage}, kp_a, kp_b, excluded_a, excluded_b


def classify_image_pair(path_a, path_b, *, mask_watermarks: bool = True,
                         min_good_matches: int = ORB_MIN_GOOD_MATCHES,
                         min_inlier_ratio: float = ORB_MIN_INLIER_RATIO,
                         min_matched_area_coverage: float = MIN_MATCHED_AREA_COVERAGE,
                         ratio_test: float = ORB_RATIO_TEST) -> MatchResult:
    """ORB keypoints + BFMatcher(Hamming) + Lowe ratio test + RANSAC homography,
    with watermark-region keypoints excluded before matching. Classifies into
    exactly one of pipeline.image_evidence.CLASSIFICATIONS. Only
    'confirmed_visual_correspondence' is ever risk_eligible=True.

    Two passes: the masked pass is what ever determines risk eligibility.
    When the masked pass does NOT confirm, a second, unmasked probe pass
    decides whether that's because there was nothing there at all
    ('rejected_generic_similarity'/'insufficient_features') or because the
    only real correspondence was inside the watermark/border region we
    deliberately excluded ('rejected_watermark') - telling a reviewer WHY a
    pair was rejected, not just that it was."""
    img_a = cv2.imread(str(path_a), cv2.IMREAD_GRAYSCALE)
    img_b = cv2.imread(str(path_b), cv2.IMREAD_GRAYSCALE)
    if img_a is None or img_b is None:
        return MatchResult(classification='processing_failed', reason='Could not decode one or both images with OpenCV.')
    masks_a = watermark_mask_regions(img_a.shape[1], img_a.shape[0]) if mask_watermarks else []
    masks_b = watermark_mask_regions(img_b.shape[1], img_b.shape[0]) if mask_watermarks else []
    masked, kp_a, kp_b, excluded_a, excluded_b = _orb_pass(img_a, img_b, masks_a, masks_b, ratio_test)
    base = dict(keypoints_a=len(kp_a), keypoints_b=len(kp_b),
                masked_keypoints_excluded_a=excluded_a, masked_keypoints_excluded_b=excluded_b)
    if masked is None:
        classification = 'insufficient_features'
        reason = 'Fewer than 10 usable keypoints outside the masked region in one or both images.'
    else:
        good, inliers, inlier_ratio, coverage = masked['good'], masked['inliers'], masked['inlier_ratio'], masked['coverage']
        base.update(good_matches=len(good), inliers=inliers, inlier_ratio=round(inlier_ratio, 3), matched_area_coverage=round(coverage, 4))
        passed = len(good) >= min_good_matches and inlier_ratio >= min_inlier_ratio and coverage >= min_matched_area_coverage
        if passed:
            return MatchResult(classification='confirmed_visual_correspondence', reason='Cleared ORB+RANSAC '
                                'confirmation with sufficient matched-area coverage outside the masked region.',
                                risk_eligible=True, **base)
        classification, reason = 'rejected_generic_similarity', (
            f'Matched area covers only {coverage:.1%} of the image - below the {min_matched_area_coverage:.0%} floor.'
            if len(good) >= min_good_matches and inlier_ratio >= min_inlier_ratio else
            f'Below the ORB confirmation bar (>= {min_good_matches} good matches, >= {min_inlier_ratio:.0%} inlier ratio).')
    # Masked pass didn't confirm - probe unmasked to see if the watermark
    # region itself is what would have looked like a match.
    if mask_watermarks and (masks_a or masks_b):
        unmasked, *_ = _orb_pass(img_a, img_b, [], [], ratio_test)
        if unmasked is not None:
            passed_unmasked = (len(unmasked['good']) >= min_good_matches and unmasked['inlier_ratio'] >= min_inlier_ratio)
            if passed_unmasked:
                return MatchResult(classification='rejected_watermark', reason='Correspondence exists only when the '
                                    'masked watermark/border region is included - not the photographed content.', **base)
    return MatchResult(classification=classification, reason=reason, **base)


def build_image_inventory(images: list[dict], errors: list[dict]) -> dict:
    """Phase 4 section B - an evidence-quality report, computed once per
    pipeline run: total files, decodable/invalid counts, dimension/format
    breakdown, work-id coverage, images-per-work distribution, exact
    duplicates, and how many known watermark-shaped strips were seen.
    `images` is extract_images()'s per-attachment list (already includes
    width/height/phash/md5); `errors` is its failure list. This never scores
    anything - it's a data-quality-flavoured description of the corpus,
    same spirit as pipeline/data_quality.py but for images instead of CSV
    fields."""
    by_md5: dict[str, list[dict]] = {}
    for item in images:
        by_md5.setdefault(item['md5'], []).append(item)
    formats: dict[str, int] = {}
    below_min = 0
    dims = []
    for item in images:
        dims.append((item['width'], item['height']))
        formats[item.get('format', 'UNKNOWN')] = formats.get(item.get('format', 'UNKNOWN'), 0) + 1
        if min(item['width'], item['height']) < MIN_IMAGE_DIM:
            below_min += 1
    images_per_work: dict[str, int] = {}
    for item in images:
        images_per_work[item['work_id']] = images_per_work.get(item['work_id'], 0) + 1
    exact_duplicate_groups = [md5 for md5, items in by_md5.items()
                               if len({i['work_id'] for i in items}) > 1]
    per_work_counts = sorted(images_per_work.values())
    return {
        'total_attachment_references': len(images) + len(errors),
        'decodable_files': len(images),
        'invalid_or_missing_files': len(errors),
        'unique_images_by_hash': len(by_md5),
        'exact_duplicate_image_groups': len(exact_duplicate_groups),
        'below_minimum_dimension_count': below_min,
        'work_ids_with_at_least_one_image': len(images_per_work),
        'images_per_work': {
            'min': per_work_counts[0] if per_work_counts else 0,
            'max': per_work_counts[-1] if per_work_counts else 0,
            'median': per_work_counts[len(per_work_counts) // 2] if per_work_counts else 0,
        },
        'dimension_range': {
            'min_width': min((d[0] for d in dims), default=0), 'max_width': max((d[0] for d in dims), default=0),
            'min_height': min((d[1] for d in dims), default=0), 'max_height': max((d[1] for d in dims), default=0),
        },
        'formats': formats,
        'preprocessing_version': PREPROCESSING_VERSION,
    }
