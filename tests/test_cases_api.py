"""Phase 3: case workflow, RBAC-scoped case endpoints, metrics, and the
production-mode auth-secret safeguard. Every fixture DB lives under tmp_path
(Phase 3 mandatory safeguard #2: tests never touch the real database)."""
import importlib
import json
import subprocess
import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_auth_rbac import PERSONAS, PASSWORDS, open_client, work_row


def case_candidate(case_id, work_id, mp, state, constituency, *, anomaly=0.8, inefficiency=0.0,
                    signal_codes=('photo_identical',), fired=None):
    family = 'inefficiency' if signal_codes[0] in ('late_sanction', 'long_open_work') else 'anomaly'
    fired = fired or [{'work_id': work_id, 'signal_code': signal_codes[0], 'signal_family': family,
                        'status': 'fired', 'score': anomaly or inefficiency, 'strength': 'strong', 'available': True,
                        'unavailable_reason': None, 'detector_version': 'v1', 'threshold_version': 't1',
                        'evidence': [], 'explanation': 'evidence found', 'recommended_action': 'review it',
                        'source': None, 'data_mode': 'real', 'cluster': 'photo_duplication' if family == 'anomaly' else signal_codes[0]}]
    return {'case_id': case_id, 'work_id': work_id,
            'context': {'work_description': f'Work {work_id}', 'mp_name': mp, 'state_name': state,
                        'constituency': constituency, 'work_category': 'Roads', 'actual_amount': 100000.0},
            'clusters_fired': ['photo_duplication'], 'anomaly_priority': anomaly, 'inefficiency_priority': inefficiency,
            'evidence_completeness': 1.0, 'source_data_confidence': 1.0, 'signal_codes': list(signal_codes),
            'fired_signals': fired, 'candidate_signals': [], 'unavailable_checks': [],
            'what_happened': f'Work {work_id}', 'why_flagged': ['evidence found'],
            'recommended_action': 'review it', 'fingerprint': 'fp1', 'detector_version': 'v1'}


@pytest.fixture
def env(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    works = [work_row('W1', 'MP A', 'State1', 'C1', 'Critical'), work_row('W2', 'MP B', 'State1', 'C2', 'Critical')]
    pd.DataFrame(works).to_parquet(data_dir / 'scored_works.parquet')
    (data_dir / 'personas.json').write_text(json.dumps(PERSONAS), encoding='utf-8')
    (data_dir / 'duplicate_pairs.json').write_text('[]', encoding='utf-8')
    (data_dir / 'images.json').write_text('[]', encoding='utf-8')
    (data_dir / 'quality_alerts.json').write_text('[]', encoding='utf-8')
    (data_dir / 'lineage.json').write_text('{}', encoding='utf-8')
    (data_dir / 'work_directory.json').write_text('{}', encoding='utf-8')
    candidates = [
        case_candidate('case1', 'W1', 'MP A', 'State1', 'C1'),
        case_candidate('case2', 'W2', 'MP B', 'State1', 'C2', signal_codes=('late_sanction',)),
    ]
    (data_dir / 'case_candidates.json').write_text(json.dumps(candidates), encoding='utf-8')

    monkeypatch.setenv('NAZAR_DATA_DIR', str(data_dir))
    monkeypatch.setenv('NAZAR_DB_PATH', str(tmp_path / 'investigations.sqlite3'))
    monkeypatch.setenv('NAZAR_AUTH_SECRET', 'test-secret-for-phase-3-padding-to-32-bytes-minimum')
    monkeypatch.delenv('NAZAR_DATABASE_URL', raising=False)
    monkeypatch.delenv('NAZAR_ENV', raising=False)
    sys.modules.pop('backend.main', None)
    sys.modules.pop('backend.auth', None)
    import backend.main as main
    importlib.reload(main)
    yield main


def client_as(main, persona_id):
    user_id = {'mp_office': 'mp.office', 'district_authority': 'district.authority',
               'state_nodal': 'state.nodal', 'ministry': 'ministry'}[persona_id]
    c = open_client(main)
    r = c.post('/auth/login', json={'user_id': user_id, 'password': PASSWORDS[user_id]})
    assert r.status_code == 200, r.text
    c.headers.update({'Authorization': f'Bearer {r.json()["token"]}'})
    return c


def test_cases_merge_as_new_on_first_run(env):
    ministry = client_as(env, 'ministry')
    body = ministry.get('/cases').json()
    assert body['total'] == 2
    assert {c['case_id'] for c in body['items']} == {'case1', 'case2'}
    assert all(c['status'] == 'NEW' for c in body['items'])


def test_cases_are_jurisdiction_scoped(env):
    mp = client_as(env, 'mp_office')
    body = mp.get('/cases').json()
    assert {c['case_id'] for c in body['items']} == {'case1'}
    assert mp.get('/cases/case2').status_code == 403
    assert mp.get('/cases/case1').status_code == 200


def test_signal_code_and_family_filters(env):
    ministry = client_as(env, 'ministry')
    r = ministry.get('/cases', params={'signal_code': 'late_sanction'})
    assert {c['case_id'] for c in r.json()['items']} == {'case2'}
    r = ministry.get('/cases', params={'signal_family': 'inefficiency'})
    assert {c['case_id'] for c in r.json()['items']} == {'case2'}


def test_pagination_and_stable_sort(env):
    ministry = client_as(env, 'ministry')
    first = ministry.get('/cases', params={'limit': 1, 'offset': 0}).json()
    second = ministry.get('/cases', params={'limit': 1, 'offset': 1}).json()
    assert len(first['items']) == 1 and len(second['items']) == 1
    assert first['items'][0]['case_id'] != second['items'][0]['case_id']


def test_valid_transition_sequence(env):
    ministry = client_as(env, 'ministry')
    assert ministry.post('/cases/case1/transition', json={'to_status': 'TRIAGED'}).status_code == 200
    assert ministry.post('/cases/case1/transition', json={'to_status': 'UNDER_REVIEW'}).status_code == 200
    r = ministry.post('/cases/case1/transition', json={'to_status': 'RESOLVED_NO_ISSUE', 'reason': 'checked, fine'})
    assert r.status_code == 200
    assert r.json()['status'] == 'RESOLVED_NO_ISSUE'


def test_invalid_transition_rejected(env):
    ministry = client_as(env, 'ministry')
    r = ministry.post('/cases/case1/transition', json={'to_status': 'CLOSED'})  # NEW -> CLOSED is not allowed
    assert r.status_code == 422


def test_resolution_requires_reason(env):
    ministry = client_as(env, 'ministry')
    ministry.post('/cases/case1/transition', json={'to_status': 'TRIAGED'})
    ministry.post('/cases/case1/transition', json={'to_status': 'UNDER_REVIEW'})
    r = ministry.post('/cases/case1/transition', json={'to_status': 'RESOLVED_NO_ISSUE'})
    assert r.status_code == 422


def test_role_cannot_refer_or_close(env):
    mp = client_as(env, 'mp_office')
    mp.post('/cases/case1/transition', json={'to_status': 'TRIAGED'})
    r = mp.post('/cases/case1/transition', json={'to_status': 'UNDER_REVIEW'})
    assert r.status_code == 200
    r = mp.post('/cases/case1/transition', json={'to_status': 'REFERRED', 'reason': 'escalating'})
    assert r.status_code == 403


def test_reopen_requires_reason(env):
    ministry = client_as(env, 'ministry')
    ministry.post('/cases/case1/transition', json={'to_status': 'TRIAGED'})
    ministry.post('/cases/case1/transition', json={'to_status': 'UNDER_REVIEW'})
    ministry.post('/cases/case1/transition', json={'to_status': 'RESOLVED_NO_ISSUE', 'reason': 'fine'})
    r = ministry.post('/cases/case1/transition', json={'to_status': 'UNDER_REVIEW'})
    assert r.status_code == 422
    r = ministry.post('/cases/case1/transition', json={'to_status': 'UNDER_REVIEW', 'reason': 'new evidence surfaced'})
    assert r.status_code == 200


def test_case_history_visible_within_scope(env):
    mp = client_as(env, 'mp_office')
    mp.post('/cases/case1/transition', json={'to_status': 'TRIAGED'})
    hist = mp.get('/cases/case1/history').json()
    assert hist['items'][0]['to_status'] == 'TRIAGED'
    assert hist['items'][0]['persona_id'] == 'mp_office'
    assert mp.get('/cases/case2/history').status_code == 403


def test_manual_escalation_creates_new_case(env):
    mp = client_as(env, 'mp_office')
    r = mp.post('/cases/escalate', json={'work_id': 'W1', 'reason': 'suspicious pattern I noticed on-site'})
    assert r.status_code == 200
    case_id = r.json()['case_id']
    assert r.json()['status'] == 'NEW'
    assert r.json()['source'] == 'manual_escalation'
    hist = mp.get(f'/cases/{case_id}/history').json()
    assert hist['items'][0]['action'] == 'manual_escalation'


def test_manual_case_survives_restart(env):
    mp = client_as(env, 'mp_office')
    r = mp.post('/cases/escalate', json={'work_id': 'W1', 'reason': 'needs a closer look after a site visit'})
    case_id = r.json()['case_id']
    mp.post(f'/cases/{case_id}/transition', json={'to_status': 'TRIAGED'})

    # Simulate a full process restart: reload backend.main so lifespan reruns
    # from scratch, reading only what's in the (same, on-disk) database -
    # case_candidates.json never contained this case at all.
    importlib.reload(env)
    ministry = client_as(env, 'ministry')
    restarted = ministry.get(f'/cases/{case_id}')
    assert restarted.status_code == 200
    body = restarted.json()
    assert body['status'] == 'TRIAGED'  # workflow state survived
    assert body['source'] == 'manual_escalation'
    assert body['context']['work_description'] is not None  # context snapshot reconstructed, not blank
    assert 'needs a closer look' in body['why_flagged'][0]
    hist = ministry.get(f'/cases/{case_id}/history').json()
    assert {h['action'] for h in hist['items']} >= {'manual_escalation', 'transition'}


def test_escalation_requires_reason(env):
    mp = client_as(env, 'mp_office')
    r = mp.post('/cases/escalate', json={'work_id': 'W1', 'reason': ''})
    assert r.status_code == 422


def test_escalation_blocked_outside_jurisdiction(env):
    mp = client_as(env, 'mp_office')
    r = mp.post('/cases/escalate', json={'work_id': 'W2', 'reason': 'trying another MP’s work'})
    assert r.status_code == 403


def test_notes_scoped_and_listed(env):
    mp = client_as(env, 'mp_office')
    r = mp.post('/cases/case1/notes', json={'note': 'Called the implementing agency.'})
    assert r.status_code == 200
    notes = mp.get('/cases/case1/notes').json()
    assert notes['items'][0]['note'] == 'Called the implementing agency.'
    assert mp.post('/cases/case2/notes', json={'note': 'x'}).status_code == 403


def test_metrics_scoped_and_honest_about_unavailable(env):
    ministry = client_as(env, 'ministry')
    metrics = ministry.get('/metrics').json()
    assert metrics['cases_resolved_per_investigator_hour'] == 'unavailable'
    assert metrics['open_reviewable_cases'] == 2  # both still NEW
    ministry.post('/cases/case1/transition', json={'to_status': 'TRIAGED'})
    metrics = ministry.get('/metrics').json()
    assert metrics['median_time_to_first_review'] != 'unavailable'

    mp = client_as(env, 'mp_office')
    mp_metrics = mp.get('/metrics').json()
    assert mp_metrics['open_reviewable_cases'] == 1  # only case1 in scope


def test_dismissal_and_escalation_rate_by_signal(env):
    ministry = client_as(env, 'ministry')
    ministry.post('/cases/case1/transition', json={'to_status': 'TRIAGED'})
    ministry.post('/cases/case1/transition', json={'to_status': 'UNDER_REVIEW'})
    ministry.post('/cases/case1/transition', json={'to_status': 'RESOLVED_NO_ISSUE', 'reason': 'no issue found'})
    metrics = ministry.get('/metrics').json()
    assert metrics['dismissal_rate_by_signal'].get('photo_identical') == 1.0


def test_case_transition_unknown_case_404(env):
    ministry = client_as(env, 'ministry')
    assert ministry.post('/cases/does-not-exist/transition', json={'to_status': 'TRIAGED'}).status_code == 404


def test_temporary_database_is_isolated_from_real_data(env, tmp_path):
    # The fixture's NAZAR_DB_PATH points inside tmp_path - proves the test
    # suite never writes to a developer's real data/investigations.sqlite3.
    assert str(tmp_path) in str(env.DB)


def test_production_mode_fails_without_auth_secret():
    env_vars = {'NAZAR_ENV': 'production'}
    result = subprocess.run([sys.executable, '-c', 'import backend.main'], env=_clean_env(env_vars),
                             capture_output=True, text=True, cwd=str(_repo_root()))
    assert result.returncode != 0
    assert 'NAZAR_AUTH_SECRET' in result.stderr


def test_development_mode_warns_but_starts_without_auth_secret():
    result = subprocess.run([sys.executable, '-c', 'import backend.main; print("STARTED")'],
                             env=_clean_env({}), capture_output=True, text=True, cwd=str(_repo_root()))
    assert result.returncode == 0
    assert 'STARTED' in result.stdout
    assert 'NAZAR_AUTH_SECRET is not set' in result.stderr


def _repo_root():
    from pathlib import Path
    return Path(__file__).resolve().parents[1]


def _clean_env(overrides):
    import os
    env = dict(os.environ)
    env.pop('NAZAR_AUTH_SECRET', None)
    env.pop('NAZAR_ENV', None)
    env.update(overrides)
    return env
