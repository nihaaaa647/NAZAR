"""Phase 4 section I: image-similarity case integration - a pHash candidate
alone, or an ORB rejection (watermark/generic), must contribute zero risk;
only a genuinely confirmed cross-work correspondence can fire."""
import importlib

import numpy as np
import pandas as pd

pipeline = importlib.import_module('scripts.pipeline')


def _row(work_id, is_synthetic=False):
    return pd.Series({'WORK_ID': work_id, 'ACTUAL_AMOUNT': 100000.0, 'ACTUAL_AMOUNT_status': 'ok',
                       'is_synthetic': is_synthetic, 'peer_group_key': 'ROADS | Bihar', 'peer_size': 12,
                       'MP_NAME': 'A MP', 'fy_start_year': np.nan})


def test_confirmed_correspondence_fires_photo_similar():
    signals = {'photo_similar': {'flag': True, 'raw': 1, 'score': 1.0, 'reason': 'confirmed'}}
    out = [s for s in pipeline.standardize_fraud_signals(_row('W1'), _full_signals(signals), 0, 'confirmed_visual_correspondence')
           if s['signal_code'] == 'photo_similar'][0]
    assert out['status'] == 'fired'
    assert out['score'] > 0
    assert out['strength'] == 'strong'


def test_candidate_only_contributes_zero_risk():
    signals = {'photo_similar': {'flag': False, 'raw': 0, 'score': 0.0, 'reason': 'not confirmed'}}
    out = [s for s in pipeline.standardize_fraud_signals(_row('W1'), _full_signals(signals), 1, 'candidate_only')
           if s['signal_code'] == 'photo_similar'][0]
    assert out['status'] == 'candidate_only'
    assert out['score'] == 0.0
    assert out['strength'] is None


def test_rejected_watermark_is_clear_not_candidate_or_fired():
    signals = {'photo_similar': {'flag': False, 'raw': 0, 'score': 0.0, 'reason': 'not confirmed'}}
    out = [s for s in pipeline.standardize_fraud_signals(_row('W1'), _full_signals(signals), 0, 'rejected_watermark')
           if s['signal_code'] == 'photo_similar'][0]
    assert out['status'] == 'clear'
    assert out['score'] == 0.0
    assert out['available'] is True  # the check ran and found a real negative


def test_rejected_generic_similarity_is_clear():
    signals = {'photo_similar': {'flag': False, 'raw': 0, 'score': 0.0, 'reason': 'not confirmed'}}
    out = [s for s in pipeline.standardize_fraud_signals(_row('W1'), _full_signals(signals), 0, 'rejected_generic_similarity')
           if s['signal_code'] == 'photo_similar'][0]
    assert out['status'] == 'clear'
    assert out['score'] == 0.0


def test_insufficient_features_is_unavailable_not_clear():
    signals = {'photo_similar': {'flag': False, 'raw': 0, 'score': 0.0, 'reason': 'not confirmed'}}
    out = [s for s in pipeline.standardize_fraud_signals(_row('W1'), _full_signals(signals), 0, 'insufficient_features')
           if s['signal_code'] == 'photo_similar'][0]
    assert out['status'] == 'unavailable'
    assert out['available'] is False
    assert out['unavailable_reason'] is not None


def test_processing_failed_is_unavailable():
    signals = {'photo_similar': {'flag': False, 'raw': 0, 'score': 0.0, 'reason': 'not confirmed'}}
    out = [s for s in pipeline.standardize_fraud_signals(_row('W1'), _full_signals(signals), 0, 'processing_failed')
           if s['signal_code'] == 'photo_similar'][0]
    assert out['status'] == 'unavailable'


def _full_signals(overrides):
    base = {
        'cost_peer': {'flag': False, 'raw': 0.0, 'score': 0.0, 'reason': ''},
        'missing_evidence': {'flag': False, 'raw': 1, 'score': 0.0, 'reason': ''},
        'anomaly': {'flag': False, 'raw': 0.0, 'score': 0.0, 'reason': ''},
        'photo_identical': {'flag': False, 'raw': 0, 'score': 0.0, 'reason': ''},
        'photo_similar': {'flag': False, 'raw': 0, 'score': 0.0, 'reason': ''},
        'text_exact': {'flag': False, 'raw': 0, 'score': 0.0, 'reason': ''},
        'text_similar': {'flag': False, 'raw': 0, 'score': 0.0, 'reason': ''},
        'entitlement_pace': {'flag': False, 'raw': 0.0, 'score': 0.0, 'reason': 'No matched sanctioned-table record for this MP and fiscal year.'},
    }
    base.update(overrides)
    return base
