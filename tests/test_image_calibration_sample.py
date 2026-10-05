"""Phase 5 A.1: the stratified real-pair sample must stay reproducible and
must never invent a human_label - the whole point is that a person fills
it in, so this only checks structure, not content."""
import csv
import json

from scripts.build_image_calibration_sample import area_bucket, build, phash_bucket


def test_phash_and_area_bucketing():
    assert phash_bucket(0) == '0'
    assert phash_bucket(2) == '1-3'
    assert phash_bucket(5) == '4-6'
    assert phash_bucket(None) == 'unknown'
    assert area_bucket(0.02) == '<0.05'
    assert area_bucket(0.1) == '0.05-0.2'
    assert area_bucket(0.5) == '>0.2'


def test_build_writes_csv_with_blank_human_columns(tmp_path, monkeypatch):
    import scripts.build_image_calibration_sample as mod
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    matches = [
        {'match_id': f'm{i}', 'work_id_a': 'W1', 'work_id_b': 'W2', 'image_id_a': 'a', 'image_id_b': 'b',
         'phash_distance': i % 6, 'good_matches': 100, 'inliers': 50, 'inlier_ratio': 0.5,
         'matched_area_coverage': 0.1, 'classification': 'confirmed_visual_correspondence',
         'preprocessing_version': 'v1', 'detector_version': 'v1'}
        for i in range(10)
    ]
    (data_dir / 'image_matches.json').write_text(json.dumps(matches), encoding='utf-8')
    monkeypatch.setattr(mod, 'DATA', data_dir)
    out_path = tmp_path / 'out.csv'
    monkeypatch.setattr(mod, 'OUT', out_path)

    sample = build(n_target=5)
    assert len(sample) > 0
    assert out_path.exists()
    with out_path.open(encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(sample)
    for row in rows:
        assert row['human_label'] == ''
        assert row['reviewer_reason'] == ''
