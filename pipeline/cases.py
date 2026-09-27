"""Consolidates standardized detector signals (pipeline/detection_contract.py)
for one work into at most one case candidate. The useful output of a review
system is a supported case, not a raw-alert count - see docs/DECISIONS.md's
Phase 3 entry for the reasoning behind every rule below.

Case-creation rule:
  - one 'fired' signal with strength=='strong', OR
  - two or more 'fired' medium-strength signals from DIFFERENT clusters.
A cluster groups correlated ways of measuring the same underlying thing
(cost_peer/anomaly are both "the amount looks off") so firing two signals
in one cluster never counts as two independent signals.

Case priority uses only the strongest signal within each cluster (never
sums repeated evidence for the same underlying thing), but keeps every
fired/candidate signal as evidence on the case.
"""
from __future__ import annotations

import hashlib

CASE_SCHEMA_VERSION = 'cases-v1'

# signal_code -> correlation cluster. Two signals in the same cluster measure
# the same underlying thing in different ways; two fired signals in the same
# cluster never combine into a case on the "two independent mediums" rule.
CLUSTERS = {
    'cost_peer': 'cost_anomaly', 'anomaly': 'cost_anomaly',
    'missing_evidence': 'evidence_gap',
    'photo_identical': 'photo_duplication', 'photo_similar': 'photo_duplication',
    'text_exact': 'text_duplication', 'text_similar': 'text_duplication',
    'entitlement_pace': 'entitlement',
    'late_sanction': 'late_sanction', 'long_open_work': 'long_open_work',
}
# cluster -> which priority dimension it contributes to. Inefficiency signals
# never feed anomaly_priority and vice versa - "do not mix inefficiency into
# suspected-fraud scores" (Phase 3 instructions, section 2).
CLUSTER_DIMENSION = {
    'cost_anomaly': 'anomaly', 'evidence_gap': 'anomaly', 'photo_duplication': 'anomaly',
    'text_duplication': 'anomaly', 'entitlement': 'anomaly',
    'late_sanction': 'inefficiency', 'long_open_work': 'inefficiency',
}


def _cluster(signal: dict) -> str:
    return signal.get('cluster') or CLUSTERS.get(signal['signal_code'], signal['signal_code'])


def case_id(work_id, clusters_fired, fingerprint, detector_version) -> str:
    """Deterministic across identical reruns (same evidence -> same id), and
    DIFFERENT when the underlying evidence materially changes (a fired
    signal's status/strength, or which clusters fired). Never includes raw
    float scores directly - only status+strength buckets - so float jitter
    between reruns can't destabilize a case's identity."""
    payload = f'{work_id}\x1f{",".join(sorted(clusters_fired))}\x1f{fingerprint}\x1f{detector_version}'
    return hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]


def _fingerprint(signals: list[dict]) -> str:
    material = sorted((s['signal_code'], s['status'], s['strength'] or '') for s in signals
                       if s['status'] in ('fired', 'candidate_only'))
    return hashlib.sha1(repr(material).encode('utf-8')).hexdigest()[:12]


def build_case_candidate(work_id, signals: list[dict], *, context: dict, quality_alert_severities=(),
                          detector_version=CASE_SCHEMA_VERSION) -> dict | None:
    """signals: every standardized signal computed for this work (fired,
    clear, candidate_only, unavailable, data_quality_failure - all of them,
    not pre-filtered), so evidence-completeness can be measured honestly.
    context: display fields (work_description, mp_name, state_name,
    constituency, actual_amount, ...) carried onto the case for the queue/
    detail views without a second lookup. quality_alert_severities: open
    data-quality alert severities on this work, for source_data_confidence."""
    fired = [s for s in signals if s['status'] == 'fired']
    candidates = [s for s in signals if s['status'] == 'candidate_only']
    unavailable = [s for s in signals if s['status'] in ('unavailable', 'data_quality_failure')]

    strong = [s for s in fired if s['strength'] == 'strong']
    medium_clusters = {_cluster(s) for s in fired if s['strength'] == 'medium'}
    if not strong and len(medium_clusters) < 2:
        return None

    cluster_max: dict[str, dict] = {}
    for s in fired:
        c = _cluster(s)
        if c not in cluster_max or s['score'] > cluster_max[c]['score']:
            cluster_max[c] = s
    anomaly_priority = sum(s['score'] for c, s in cluster_max.items() if CLUSTER_DIMENSION.get(c) == 'anomaly')
    inefficiency_priority = sum(s['score'] for c, s in cluster_max.items() if CLUSTER_DIMENSION.get(c) == 'inefficiency')

    available_count = sum(1 for s in signals if s['available'])
    evidence_completeness = round(available_count / len(signals), 3) if signals else 0.0

    if any(sev == 'critical' for sev in quality_alert_severities):
        source_data_confidence = 0.2
    elif any(sev == 'warning' for sev in quality_alert_severities):
        source_data_confidence = 0.5
    else:
        source_data_confidence = 1.0

    clusters_fired = sorted({_cluster(s) for s in fired})
    fingerprint = _fingerprint(signals)
    cid = case_id(work_id, clusters_fired, fingerprint, detector_version)

    all_evidence = []
    for s in fired + candidates:
        all_evidence.extend(s['evidence'])

    return {
        'case_id': cid,
        'work_id': str(work_id),
        'context': context,
        'clusters_fired': clusters_fired,
        'anomaly_priority': round(min(anomaly_priority, 1.0), 3),
        'inefficiency_priority': round(min(inefficiency_priority, 1.0), 3),
        'evidence_completeness': evidence_completeness,
        'source_data_confidence': source_data_confidence,
        'signal_codes': sorted({s['signal_code'] for s in fired}),
        'fired_signals': fired,
        'candidate_signals': candidates,
        'unavailable_checks': [{'signal_code': s['signal_code'], 'signal_family': s['signal_family'],
                                 'reason': s['unavailable_reason']} for s in unavailable],
        'what_happened': context.get('work_description') or f'Work {work_id}',
        'why_flagged': [s['explanation'] for s in sorted(fired, key=lambda s: -s['score'])],
        'recommended_action': (max(fired, key=lambda s: s['score'])['recommended_action'] if fired else ''),
        'fingerprint': fingerprint,
        'detector_version': detector_version,
    }
