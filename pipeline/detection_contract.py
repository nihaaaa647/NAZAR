"""Standard detection-result contract (Phase 3): every detector — fraud/anomaly,
inefficiency, or data-quality — reports through the same shape, so a case can
be consolidated from mixed signal families without each caller re-inventing
its own notion of "did this fire."

Fields:
  work_id            str
  signal_code         str   -- e.g. 'cost_peer', 'late_sanction', 'amount_zero'
  signal_family       'anomaly' | 'inefficiency' | 'data_quality'
  status              'fired' | 'clear' | 'candidate_only' | 'unavailable' | 'data_quality_failure'
  score               float, 0.0-1.0 (0.0 when status isn't 'fired'/'candidate_only')
  strength            'weak' | 'medium' | 'strong' (only meaningful when status=='fired')
  available           bool  -- convenience mirror of status not in (unavailable, data_quality_failure)
  unavailable_reason  str | None  -- required whenever available is False
  detector_version    str
  threshold_version    str
  evidence            list[dict]  -- summarized, references full evidence elsewhere (duplicate_pairs.json etc)
  explanation         str   -- the old `reason` text, renamed
  recommended_action  str
  source              str | None  -- citation for a sourced (non-heuristic) threshold, e.g. 'MPLADS Guidelines 2023'
  data_mode           'real' | 'synthetic_demo'
  cluster             str   -- correlation-suppression grouping key, see pipeline/cases.py

`status` distinctions that matter for case consolidation:
  'clear'      the detector ran and found nothing - a real, informative negative.
  'unavailable' the detector could not run at all (e.g. no matched sanctioned
               record for entitlement_pace) - never treated as "clear" and never
               silently defaults to a score of 0 that looks like a real negative.
  'data_quality_failure' specifically: unavailable *because* a data-quality
               problem (an ambiguous/unparseable amount, a missing date) blocked
               it - distinct from 'unavailable' so a reviewer can tell "nothing
               to see here" apart from "this needs the underlying data fixed
               before it can be evaluated at all."
  'candidate_only' evidence exists but didn't clear a confirmation bar (e.g. a
               visually-similar photo pair ORB/RANSAC couldn't confirm) - never
               contributes to case creation on its own, but is retained as
               evidence if a case exists for other reasons.
"""
from __future__ import annotations

STATUSES = frozenset({'fired', 'clear', 'candidate_only', 'unavailable', 'data_quality_failure'})
FAMILIES = frozenset({'anomaly', 'inefficiency', 'data_quality'})
STRENGTHS = frozenset({'weak', 'medium', 'strong'})


def strength_of(score: float) -> str:
    if score >= 0.67:
        return 'strong'
    if score >= 0.34:
        return 'medium'
    return 'weak'


def make_signal(work_id, signal_code, signal_family, status, *, score=0.0, evidence=None,
                 explanation='', recommended_action='', detector_version='', threshold_version='',
                 unavailable_reason=None, source=None, data_mode='real', cluster=None) -> dict:
    assert status in STATUSES, f'unknown status {status!r}'
    assert signal_family in FAMILIES, f'unknown signal_family {signal_family!r}'
    available = status not in ('unavailable', 'data_quality_failure')
    if not available and not unavailable_reason:
        raise ValueError(f'{signal_code}: unavailable_reason is required when status={status!r}')
    # Phase 4 section D/I: "a pHash candidate alone must remain unscored" -
    # only a 'fired' signal ever carries a nonzero score. 'candidate_only'
    # keeps zero risk exactly like 'clear'/'unavailable', even though
    # evidence exists (it's retained via the `evidence` field, not the score).
    effective_score = float(score) if status == 'fired' else 0.0
    return {
        'work_id': None if work_id is None else str(work_id),
        'signal_code': signal_code,
        'signal_family': signal_family,
        'status': status,
        'score': effective_score,
        'strength': strength_of(effective_score) if status == 'fired' else None,
        'available': available,
        'unavailable_reason': unavailable_reason,
        'detector_version': detector_version,
        'threshold_version': threshold_version,
        'evidence': evidence or [],
        'explanation': explanation,
        'recommended_action': recommended_action,
        'source': source,
        'data_mode': data_mode,
        # None unless the caller explicitly overrides it - pipeline/cases.py's
        # CLUSTERS table is the default lookup (by signal_code) for grouping
        # correlated signals; a bare signal_code fallback here would silently
        # defeat that lookup for every signal that doesn't set its own cluster.
        'cluster': cluster,
    }
