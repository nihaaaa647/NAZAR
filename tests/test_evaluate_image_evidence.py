"""Regression guard for the Phase 4 synthetic calibration set (section F) -
never touches data/image_cache, only a tmp_path-scoped scratch directory."""
from scripts.evaluate_image_evidence import run_evaluation


def test_calibration_set_matches_expected_classifications(tmp_path):
    summary = run_evaluation(cache_dir=tmp_path / 'eval_images')
    mismatches = [c for c in summary['cases'] if not c['matches_expectation']]
    assert not mismatches, mismatches
    assert summary['case_count'] == 8


def test_no_false_positive_on_generic_infrastructure_or_legit_before_after(tmp_path):
    summary = run_evaluation(cache_dir=tmp_path / 'eval_images')
    assert summary['false_matches_on_generic_infrastructure'] == 0
    assert summary['false_positive_count_overall'] == 0


def test_watermark_case_is_always_zero_risk(tmp_path):
    summary = run_evaluation(cache_dir=tmp_path / 'eval_images')
    assert summary['watermark_only_zero_risk_rate'] == 1.0


def test_corrupted_file_is_a_processing_failure_not_a_crash(tmp_path):
    summary = run_evaluation(cache_dir=tmp_path / 'eval_images')
    assert summary['processing_failures'] == 1
