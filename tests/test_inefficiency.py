"""Inefficiency engine: sourced/Phase-3-instructed delay signals, kept
structurally separate from the fraud signals_json / risk_score / severity_band."""
import pandas as pd
import pytest

from scripts.pipeline import (
    entitlement_rule, peer_z, long_open_work_signal, late_sanction_signal, build_inefficiency,
    MPLADS_ENTITLEMENT_PER_FY, LATE_SANCTION_REVIEW_DAYS, MIN_PEER_SIZE,
)


def test_entitlement_rule_is_one_sided_and_hedged():
    under = entitlement_rule(4_00_00_000, 'A MP', 2024)
    assert not under['flag'] and under['score'] == 0

    over = entitlement_rule(6_00_00_000, 'A MP', 2024)
    assert over['flag'] and over['score'] == pytest.approx(0.2)
    # Framed as advisory context, never a proven violation (carry-forward exists).
    assert 'not proof' in over['reason']

    missing = entitlement_rule(None, 'A MP', 2024)
    assert not missing['flag'] and missing['score'] == 0


def test_peer_z_never_flags_a_low_value():
    df = pd.DataFrame({
        'activity_norm': ['ROADS'] * 12, 'STATE_NAME': ['Bihar'] * 12,
        'amount': [100] * 10 + [10, 1000],   # a fast/low outlier and a slow/high outlier
    })
    z, group_key, sizes, _ = peer_z(df, 'amount', 'activity_norm', 'STATE_NAME')
    assert z.iloc[10] < 0            # below peers
    assert z.iloc[11] > 2.5          # above peers, flags under cost_rule/long-open-style thresholds
    assert (sizes == 12).all()


def _universe(rows):
    base = {'record_id': None, 'work_id': pd.NA, 'is_synthetic': False, 'has_completed_record': False,
            'has_sanctioned_record': True, 'mp_name': 'TEST MP', 'mp_norm': 'TEST MP', 'constituency': 'C',
            'state_name': 'Bihar', 'activity_name': 'Roads', 'activity_norm': 'ROADS', 'work_description': 'desc',
            'sanction_amount': 100000.0, 'fy_start_year': 2024,
            'sanction_date': pd.Timestamp('2024-01-01'), 'recommendation_date': pd.Timestamp('2024-01-01')}
    return pd.DataFrame([{**base, **r, 'record_id': str(i)} for i, r in enumerate(rows)])


def test_long_open_and_late_signals_are_disjoint_populations():
    as_of_date = pd.Timestamp('2026-01-01')
    peers = [{'has_completed_record': False, 'sanction_date': as_of_date - pd.Timedelta(days=30 + i),
              'recommendation_date': as_of_date - pd.Timedelta(days=40 + i)} for i in range(9)]
    universe = _universe([
        *peers,
        # Sanctioned long ago, still not completed, far past its peer group — long-open.
        {'has_completed_record': False, 'sanction_date': pd.Timestamp('2020-01-01')},
        # Completed, sanctioned fast — neither long-open (has a completed record) nor late.
        {'has_completed_record': True, 'work_id': 'W1', 'sanction_date': pd.Timestamp('2024-01-10'),
         'recommendation_date': pd.Timestamp('2024-01-01')},
        # Completed, but took far longer than the review window to sanction — late only.
        {'has_completed_record': True, 'work_id': 'W2', 'sanction_date': pd.Timestamp('2024-06-01'),
         'recommendation_date': pd.Timestamp('2024-01-01')},
    ])
    outlier, fast, late_only = universe.record_id.iloc[9], universe.record_id.iloc[10], universe.record_id.iloc[11]

    long_open = long_open_work_signal(universe, as_of_date)
    assert len(long_open) == 10  # the 9 peers + the outlier; completed rows are never long-open candidates
    assert bool(long_open.set_index('record_id').loc[outlier].flag)
    assert not long_open.set_index('record_id').loc[universe.record_id.iloc[0]].flag
    # Peer definition/sample/median/threshold are stored, not just a bare z-score.
    outlier_row = long_open.set_index('record_id').loc[outlier]
    assert outlier_row.peer_size == 10  # includes itself, same as the cost-peer convention
    assert outlier_row.peer_median_days > 0
    assert outlier_row.peer_threshold_days > outlier_row.peer_median_days

    late = late_sanction_signal(universe)
    assert len(late) == 12  # every row here has both dates
    by_id = late.set_index('record_id')
    assert not by_id.loc[fast].flag and by_id.loc[late_only].flag

    findings, stats = build_inefficiency(universe, as_of_date)
    assert stats['long_open_flagged'] == 1 and stats['late_sanction_flagged'] == 1
    assert stats['late_sanction_review_days'] == LATE_SANCTION_REVIEW_DAYS
    ids = {f['RECORD_ID'] for f in findings}
    assert outlier in ids and late_only in ids
    # Every sanctioned/dated candidate now gets a finding row (fired/clear/unavailable) -
    # not silently dropped when it wasn't flagged.
    assert universe.record_id.iloc[0] in ids
    long_open_finding = next(f for f in findings if f['RECORD_ID'] == outlier)
    assert long_open_finding['long_open_work']['flag']
    assert long_open_finding['WORK_ID'] is None and long_open_finding['is_completed'] is False
    late_finding = next(f for f in findings if f['RECORD_ID'] == late_only)
    assert late_finding['late_sanction']['flag'] and late_finding['long_open_work'] is None
    assert late_finding['WORK_ID'] == 'W2'
    fast_finding = next(f for f in findings if f['RECORD_ID'] == fast)
    assert fast_finding['late_sanction']['status'] == 'clear'


def test_missing_recommendation_date_is_unavailable_not_a_proxy():
    """No fiscal-year-start or other substitute is used when the real start
    date is missing - the late_sanction block for that row must say
    'unavailable', never compute a lag from a guessed date."""
    universe = _universe([
        {'has_completed_record': True, 'work_id': 'W1', 'sanction_date': pd.Timestamp('2024-03-01'),
         'recommendation_date': pd.NaT},
    ])
    findings, _ = build_inefficiency(universe, pd.Timestamp('2024-06-01'))
    finding = findings[0]
    assert finding['late_sanction']['status'] == 'unavailable'
    assert 'recommendation date' in finding['late_sanction']['unavailable_reason']
    # No numeric lag was silently computed from a substitute start date.
    assert 'sanction_lag_days' not in finding['late_sanction']


def test_explicit_as_of_date_is_used_not_wall_clock():
    fixed = pd.Timestamp('2030-01-01')
    universe = _universe([{'sanction_date': pd.Timestamp('2029-01-01')}])
    long_open = long_open_work_signal(universe, fixed)
    assert long_open.iloc[0].days_since_sanction == 365
    _, stats = build_inefficiency(universe, fixed)
    assert stats['as_of_date'] == '2030-01-01'


def test_minimum_peer_group_size_marks_unavailable():
    # Only 3 comparable peers - below MIN_PEER_SIZE - must not compute a threshold.
    as_of_date = pd.Timestamp('2026-01-01')
    universe = _universe([{'sanction_date': as_of_date - pd.Timedelta(days=d)} for d in (10, 20, 900)])
    long_open = long_open_work_signal(universe, as_of_date, min_peer_size=MIN_PEER_SIZE)
    assert long_open.peer_insufficient.all()
    assert not long_open.flag.any()  # never flagged off an unreliable threshold
    findings, stats = build_inefficiency(universe, as_of_date)
    assert stats['long_open_insufficient_peers'] == 3
    assert all(f['long_open_work']['status'] == 'unavailable' for f in findings)


def test_inefficiency_never_touches_fraud_scoring_fields():
    findings, _ = build_inefficiency(_universe([{'has_completed_record': True, 'work_id': 'W1'}]), pd.Timestamp('2024-06-01'))
    for f in findings:
        assert 'risk_score' not in f and 'signals_json' not in f and 'severity_band' not in f
