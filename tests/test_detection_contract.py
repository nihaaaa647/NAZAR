import pytest

from pipeline.detection_contract import make_signal, strength_of


def test_strength_buckets():
    assert strength_of(0.0) == 'weak'
    assert strength_of(0.33) == 'weak'
    assert strength_of(0.34) == 'medium'
    assert strength_of(0.66) == 'medium'
    assert strength_of(0.67) == 'strong'
    assert strength_of(1.0) == 'strong'


def test_fired_signal_shape():
    s = make_signal('W1', 'cost_peer', 'anomaly', 'fired', score=0.8, explanation='high', recommended_action='check',
                     detector_version='v1', threshold_version='t1')
    assert s['available'] is True
    assert s['strength'] == 'strong'
    assert s['unavailable_reason'] is None
    assert s['data_mode'] == 'real'


def test_unavailable_requires_reason():
    with pytest.raises(ValueError):
        make_signal('W1', 'entitlement_pace', 'anomaly', 'unavailable')


def test_unavailable_is_never_clear():
    s = make_signal('W1', 'entitlement_pace', 'anomaly', 'unavailable', unavailable_reason='no match')
    assert s['available'] is False
    assert s['score'] == 0.0
    assert s['strength'] is None
    assert s['status'] != 'clear'


def test_clear_is_a_real_status_distinct_from_unavailable():
    clear = make_signal('W1', 'anomaly', 'anomaly', 'clear', explanation='not an outlier')
    assert clear['available'] is True
    assert clear['status'] == 'clear'


def test_candidate_only_never_defaults_to_fired_strength_rules():
    s = make_signal('W1', 'photo_similar', 'anomaly', 'candidate_only', score=0.5)
    assert s['status'] == 'candidate_only'
    # candidate_only signals carry a score but no 'strength' bucket - they
    # never independently qualify for case creation (pipeline/cases.py only
    # counts 'fired' signals toward strong/medium thresholds).
    assert s['strength'] is None


def test_synthetic_demo_data_mode_is_explicit():
    s = make_signal('W1', 'anomaly', 'anomaly', 'clear', data_mode='synthetic_demo')
    assert s['data_mode'] == 'synthetic_demo'


def test_rejects_unknown_status_and_family():
    with pytest.raises(AssertionError):
        make_signal('W1', 'x', 'anomaly', 'not-a-real-status')
    with pytest.raises(AssertionError):
        make_signal('W1', 'x', 'not-a-real-family', 'clear')
