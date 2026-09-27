from pipeline.cases import build_case_candidate, case_id
from pipeline.detection_contract import make_signal

CTX = {'work_description': 'Test work', 'mp_name': 'MP A', 'state_name': 'State', 'constituency': 'C1', 'actual_amount': 100000.0}


def fired(code, family='anomaly', score=0.8, cluster=None):
    return make_signal('W1', code, family, 'fired', score=score, explanation=f'{code} fired',
                        recommended_action=f'check {code}', detector_version='v1', threshold_version='t1', cluster=cluster)


def clear(code, family='anomaly'):
    return make_signal('W1', code, family, 'clear', explanation=f'{code} clear', detector_version='v1', threshold_version='t1')


def unavailable(code, family='anomaly', reason='no data'):
    return make_signal('W1', code, family, 'unavailable', unavailable_reason=reason, detector_version='v1', threshold_version='t1')


def test_one_strong_signal_creates_a_case():
    signals = [fired('photo_identical', score=0.9)] + [clear(c) for c in ('cost_peer', 'anomaly')]
    case = build_case_candidate('W1', signals, context=CTX)
    assert case is not None
    assert 'photo_identical' in case['signal_codes']


def test_correlated_mediums_in_same_cluster_do_not_create_a_case():
    # cost_peer + anomaly are both the 'cost_anomaly' cluster - two correlated
    # mediums must NOT combine into "two independent signals".
    signals = [fired('cost_peer', score=0.5), fired('anomaly', score=0.5)]
    case = build_case_candidate('W1', signals, context=CTX)
    assert case is None


def test_two_independent_medium_signals_create_a_case():
    signals = [fired('cost_peer', score=0.5), fired('photo_identical', score=0.5)]
    case = build_case_candidate('W1', signals, context=CTX)
    assert case is not None
    assert set(case['clusters_fired']) == {'cost_anomaly', 'photo_duplication'}


def test_single_medium_signal_does_not_create_a_case():
    case = build_case_candidate('W1', [fired('cost_peer', score=0.5)], context=CTX)
    assert case is None


def test_priority_uses_only_strongest_signal_per_cluster_but_keeps_all_evidence():
    signals = [fired('cost_peer', score=0.9, cluster='cost_anomaly'),
               fired('anomaly', score=0.4, cluster='cost_anomaly'),
               fired('photo_identical', score=0.5, cluster='photo_duplication')]
    case = build_case_candidate('W1', signals, context=CTX)
    assert case is not None
    # anomaly_priority = max(cost_anomaly cluster) + max(photo_duplication cluster) = 0.9 + 0.5
    assert case['anomaly_priority'] == 1.0  # capped at 1.0, would be 1.4 uncapped
    # but both cost_peer and anomaly remain as retained evidence
    assert {'cost_peer', 'anomaly', 'photo_identical'} <= set(case['signal_codes'])


def test_inefficiency_and_anomaly_priority_are_never_mixed():
    signals = [fired('cost_peer', score=0.9), fired('late_sanction', family='inefficiency', score=0.9, cluster='late_sanction')]
    case = build_case_candidate('W1', signals, context=CTX)
    assert case is not None
    assert case['anomaly_priority'] == 0.9
    assert case['inefficiency_priority'] == 0.9  # tracked separately, not summed into anomaly_priority


def test_two_independent_inefficiency_signals_alone_can_create_a_case():
    signals = [fired('late_sanction', family='inefficiency', score=0.5, cluster='late_sanction'),
               fired('long_open_work', family='inefficiency', score=0.5, cluster='long_open_work')]
    case = build_case_candidate('W1', signals, context=CTX)
    assert case is not None
    assert case['anomaly_priority'] == 0.0
    assert case['inefficiency_priority'] > 0


def test_deterministic_case_id_same_evidence_same_id():
    signals = [fired('photo_identical', score=0.9)]
    a = build_case_candidate('W1', signals, context=CTX)
    b = build_case_candidate('W1', signals, context=CTX)
    assert a['case_id'] == b['case_id']


def test_case_id_changes_when_material_evidence_changes():
    strong = build_case_candidate('W1', [fired('photo_identical', score=0.9)], context=CTX)
    # Same signal_code, but now 'clear' instead of 'fired' - materially different.
    now_clear = [clear('photo_identical'), fired('cost_peer', score=0.5), fired('text_exact', score=0.5)]
    other = build_case_candidate('W1', now_clear, context=CTX)
    assert other is not None
    assert strong['case_id'] != other['case_id']


def test_case_id_unaffected_by_unavailable_or_clear_signal_noise():
    base = [fired('photo_identical', score=0.9), clear('missing_evidence')]
    plus_unavailable = base + [unavailable('entitlement_pace')]
    a = build_case_candidate('W1', base, context=CTX)
    b = build_case_candidate('W1', plus_unavailable, context=CTX)
    assert a['case_id'] == b['case_id']  # unavailable/clear noise isn't "material" evidence


def test_unavailable_checks_are_surfaced_on_the_case():
    signals = [fired('photo_identical', score=0.9), unavailable('entitlement_pace', reason='no matched record')]
    case = build_case_candidate('W1', signals, context=CTX)
    assert {'signal_code': 'entitlement_pace', 'signal_family': 'anomaly', 'reason': 'no matched record'} in case['unavailable_checks']


def test_evidence_completeness_reflects_available_fraction():
    all_available = [fired('photo_identical', score=0.9), clear('cost_peer')]
    case_full = build_case_candidate('W1', all_available, context=CTX)
    assert case_full['evidence_completeness'] == 1.0

    half_available = all_available + [unavailable('entitlement_pace'), unavailable('missing_evidence')]
    case_half = build_case_candidate('W1', half_available, context=CTX)
    assert case_half['evidence_completeness'] == 0.5


def test_source_data_confidence_downgraded_by_open_quality_alerts():
    signals = [fired('photo_identical', score=0.9)]
    clean = build_case_candidate('W1', signals, context=CTX, quality_alert_severities=[])
    warned = build_case_candidate('W1', signals, context=CTX, quality_alert_severities=['warning'])
    critical = build_case_candidate('W1', signals, context=CTX, quality_alert_severities=['critical'])
    assert clean['source_data_confidence'] == 1.0
    assert warned['source_data_confidence'] < clean['source_data_confidence']
    assert critical['source_data_confidence'] < warned['source_data_confidence']


def test_case_id_helper_is_pure_and_deterministic():
    a = case_id('W1', ['cost_anomaly'], 'fp1', 'v1')
    b = case_id('W1', ['cost_anomaly'], 'fp1', 'v1')
    c = case_id('W1', ['cost_anomaly'], 'fp2', 'v1')
    assert a == b
    assert a != c
