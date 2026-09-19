"""Inefficiency engine: sourced (MPLADS Guidelines 2023) delay signals, kept
structurally separate from the fraud signals_json / risk_score / severity_band."""
import pandas as pd
import pytest

from scripts.pipeline import (
    entitlement_rule, peer_z, idle_funds_signal, late_sanction_signal, build_inefficiency,
    MPLADS_ENTITLEMENT_PER_FY, SANCTION_DEADLINE_DAYS,
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
    assert z.iloc[11] > 2.5          # above peers, flags under cost_rule/idle-style thresholds
    assert (sizes == 12).all()


def _universe(rows):
    base = {'record_id': None, 'work_id': pd.NA, 'is_synthetic': False, 'has_completed_record': False,
            'has_sanctioned_record': True, 'mp_name': 'TEST MP', 'mp_norm': 'TEST MP', 'constituency': 'C',
            'state_name': 'Bihar', 'activity_name': 'Roads', 'activity_norm': 'ROADS', 'work_description': 'desc',
            'sanction_amount': 100000.0, 'fy_start_year': 2024,
            'sanction_date': pd.Timestamp('2024-01-01'), 'recommendation_date': pd.Timestamp('2024-01-01')}
    return pd.DataFrame([{**base, **r, 'record_id': str(i)} for i, r in enumerate(rows)])


def test_idle_and_late_signals_are_disjoint_populations():
    run_date = pd.Timestamp('2026-01-01')
    peers = [{'has_completed_record': False, 'sanction_date': run_date - pd.Timedelta(days=30 + i),
              'recommendation_date': run_date - pd.Timedelta(days=40 + i)} for i in range(9)]
    universe = _universe([
        *peers,
        # Sanctioned long ago, still not completed, far past its peer group — idle.
        {'has_completed_record': False, 'sanction_date': pd.Timestamp('2020-01-01')},
        # Completed, sanctioned fast — neither idle (has a completed record) nor late.
        {'has_completed_record': True, 'work_id': 'W1', 'sanction_date': pd.Timestamp('2024-01-10'),
         'recommendation_date': pd.Timestamp('2024-01-01')},
        # Completed, but took far longer than SANCTION_DEADLINE_DAYS to sanction — late only.
        {'has_completed_record': True, 'work_id': 'W2', 'sanction_date': pd.Timestamp('2024-06-01'),
         'recommendation_date': pd.Timestamp('2024-01-01')},
    ])
    outlier, fast, late_only = universe.record_id.iloc[9], universe.record_id.iloc[10], universe.record_id.iloc[11]

    idle = idle_funds_signal(universe, run_date)
    assert len(idle) == 10  # the 9 peers + the outlier; completed rows are never idle candidates
    assert bool(idle.set_index('record_id').loc[outlier].flag)
    assert not idle.set_index('record_id').loc[universe.record_id.iloc[0]].flag

    late = late_sanction_signal(universe)
    assert len(late) == 12  # every row here has both dates
    by_id = late.set_index('record_id')
    assert not by_id.loc[fast].flag and by_id.loc[late_only].flag

    findings, stats = build_inefficiency(universe, run_date)
    assert stats['idle_flagged'] == 1 and stats['late_sanction_flagged'] == 1
    ids = {f['RECORD_ID'] for f in findings}
    assert ids == {outlier, late_only}  # the 9 in-range peers and the fast-completed row never appear
    idle_finding = next(f for f in findings if f['RECORD_ID'] == outlier)
    assert idle_finding['idle_funds']['flag'] and idle_finding['late_sanction'] is not None
    assert idle_finding['WORK_ID'] is None and idle_finding['is_completed'] is False
    late_finding = next(f for f in findings if f['RECORD_ID'] == late_only)
    assert late_finding['late_sanction']['flag'] and late_finding['idle_funds'] is None
    assert late_finding['WORK_ID'] == 'W2'
