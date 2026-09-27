"""Phase 4: image validation, watermark masking, and ORB classification.
Every image here is synthetically generated in tmp_path - no dependency on
the real corpus, and no writes anywhere but tmp_path (mandatory safeguard #3:
tests only ever touch temporary image directories)."""
import numpy as np
import cv2
import pytest

from pipeline.image_evidence import (
    validate_image_bytes, watermark_mask_regions, classify_image_pair,
    image_id, match_id, MIN_IMAGE_DIM, CLASSIFICATIONS, CLASSIFICATION_MEANINGS,
)


def _textured(path, seed, w=800, h=1000):
    rng = np.random.default_rng(seed)
    img = (rng.random((h, w)) * 255).astype('uint8')
    for _ in range(20):
        x, y = rng.integers(0, w - 50), rng.integers(0, h - 50)
        cv2.rectangle(img, (x, y), (x + 40, y + 40), int(rng.integers(0, 255)), -1)
    cv2.imwrite(str(path), img)
    return path


def _watermarked(path, seed, w=800, h=1000, text='Scanned with OKEN Scanner'):
    rng = np.random.default_rng(seed)
    img = (rng.random((h, w)) * 30 + 20).astype('uint8')
    cv2.putText(img, text, (10, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255,), 2)
    cv2.putText(img, text, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255,), 2)
    cv2.imwrite(str(path), img)
    return path


# --- validation ---

def test_corrupt_file_is_invalid_not_a_fraud_signal():
    result = validate_image_bytes(b'this is not an image')
    assert result.valid is False
    assert result.status == 'invalid'


def test_empty_file_is_invalid():
    assert validate_image_bytes(b'').valid is False


def test_valid_image_reports_dimensions_and_hash(tmp_path):
    path = tmp_path / 'a.jpg'
    _textured(path, 1)
    result = validate_image_bytes(path.read_bytes())
    assert result.valid is True
    assert result.width == 800 and result.height == 1000
    assert result.md5 is not None
    assert result.status == 'valid'
    assert result.meets_min_dimension is True


def test_below_minimum_dimension_is_a_distinct_status(tmp_path):
    path = tmp_path / 'strip.jpg'
    cv2.imwrite(str(path), np.zeros((60, 600), dtype='uint8'))
    result = validate_image_bytes(path.read_bytes())
    assert result.valid is True
    assert result.status == 'below_minimum_dimension'
    assert result.meets_min_dimension is False
    assert str(MIN_IMAGE_DIM) in result.reason


# --- deterministic ids ---

def test_image_id_is_content_addressed():
    assert image_id('deadbeef') == 'deadbeef'


def test_match_id_is_order_independent_and_deterministic():
    assert match_id('a', 'b') == match_id('b', 'a')
    assert match_id('a', 'b') == match_id('a', 'b')


def test_match_id_changes_with_detector_version():
    assert match_id('a', 'b', detector_version='v1') != match_id('a', 'b', detector_version='v2')


# --- watermark masking ---

def test_watermark_mask_covers_top_and_bottom_borders():
    masks = watermark_mask_regions(1000, 2000, border_fraction=0.1)
    assert len(masks) == 2
    top, bottom = masks
    assert top == (0, 0, 1000, 200)
    assert bottom[1] == 1800 and bottom[3] == 2000


# --- ORB classification: the six required outcomes ---

def test_identical_content_confirms_and_is_risk_eligible(tmp_path):
    a, b = _textured(tmp_path / 'a.jpg', 1), _textured(tmp_path / 'b.jpg', 1)
    result = classify_image_pair(a, b)
    assert result.classification == 'confirmed_visual_correspondence'
    assert result.risk_eligible is True
    assert result.matched_area_coverage > 0
    assert CLASSIFICATION_MEANINGS[result.classification]  # every classification has reviewer-facing text


def test_watermark_only_match_is_rejected_and_zero_risk(tmp_path):
    a = _watermarked(tmp_path / 'a.jpg', 10)
    b = _watermarked(tmp_path / 'b.jpg', 20)  # different random content, same watermark text
    result = classify_image_pair(a, b)
    assert result.classification == 'rejected_watermark'
    assert result.risk_eligible is False


def test_masking_disabled_shows_strong_raw_correspondence_from_watermark_text(tmp_path):
    # Proves the watermark pair really would look like a strong match
    # without masking (the rejection above is the masking doing real work,
    # not a pair that was never going to match anyway) - it still doesn't
    # clear the separate matched-area-coverage floor, since the identical
    # text occupies only a thin strip of the frame, but the raw ORB/RANSAC
    # numbers show the correspondence the mask is specifically excluding.
    a = _watermarked(tmp_path / 'a.jpg', 10)
    b = _watermarked(tmp_path / 'b.jpg', 20)
    result = classify_image_pair(a, b, mask_watermarks=False)
    assert result.good_matches >= 100
    assert result.inlier_ratio >= 0.2


def test_unrelated_textured_images_are_generic_negative(tmp_path):
    a, b = _textured(tmp_path / 'a.jpg', 100), _textured(tmp_path / 'b.jpg', 200)
    result = classify_image_pair(a, b)
    assert result.classification == 'rejected_generic_similarity'
    assert result.risk_eligible is False


def test_low_texture_images_are_insufficient_features(tmp_path):
    a, b = tmp_path / 'a.jpg', tmp_path / 'b.jpg'
    cv2.imwrite(str(a), np.full((400, 400), 128, dtype='uint8'))
    cv2.imwrite(str(b), np.full((400, 400), 128, dtype='uint8'))
    result = classify_image_pair(a, b)
    assert result.classification == 'insufficient_features'
    assert result.risk_eligible is False


def test_corrupt_image_pair_is_processing_failed(tmp_path):
    corrupt = tmp_path / 'corrupt.jpg'
    corrupt.write_bytes(b'not an image')
    good = _textured(tmp_path / 'good.jpg', 1)
    result = classify_image_pair(corrupt, good)
    assert result.classification == 'processing_failed'
    assert result.risk_eligible is False


def test_matched_area_below_floor_is_rejected_not_confirmed(tmp_path):
    # A pair that clears good_matches/inlier_ratio but whose inliers are
    # concentrated in a tiny corner should not confirm - regression guard on
    # the matched-area-coverage floor specifically. Construct a small shared
    # patch pasted into two otherwise-unrelated large random images.
    rng = np.random.default_rng(5)
    patch = (rng.random((60, 60)) * 255).astype('uint8')
    for _ in range(8):
        x, y = rng.integers(0, 50), rng.integers(0, 50)
        cv2.rectangle(patch, (x, y), (x + 8, y + 8), int(rng.integers(0, 255)), -1)
    big_a = (rng.random((1200, 1200)) * 255).astype('uint8')
    big_b = (rng.random((1200, 1200)) * 255).astype('uint8')
    big_a[40:100, 40:100] = patch
    big_b[900:960, 900:960] = patch
    pa, pb = tmp_path / 'pa.jpg', tmp_path / 'pb.jpg'
    cv2.imwrite(str(pa), big_a)
    cv2.imwrite(str(pb), big_b)
    result = classify_image_pair(pa, pb, min_matched_area_coverage=0.5)  # deliberately high floor for this test
    assert result.classification != 'confirmed_visual_correspondence'


def test_all_classifications_have_reviewer_facing_meaning():
    assert CLASSIFICATIONS == set(CLASSIFICATION_MEANINGS)
    # Every meaning may discuss fraud only to disclaim it - never assert it.
    for text in CLASSIFICATION_MEANINGS.values():
        assert 'is fraud' not in text.lower() and 'confirms fraud' not in text.lower()
