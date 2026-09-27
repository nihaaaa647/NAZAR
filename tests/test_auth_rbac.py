"""Phase 2: real authentication + backend-enforced RBAC.

Builds a small multi-jurisdiction fixture (two MPs in the same state, two
states) so isolation can actually be exercised rather than asserted against
a single-persona fixture."""
import importlib
import json
import sys
import time

import jwt as pyjwt
import pandas as pd
import pytest
from fastapi.testclient import TestClient


PERSONAS = [
    {'id': 'mp_office', 'role': 'MP Office', 'label': 'MP A', 'jurisdiction_summary': 'MP A / C1',
     'filter': {'MP_NAME': ['MP A'], 'CONSTITUENCY': ['C1']}},
    {'id': 'district_authority', 'role': 'District Authority', 'label': 'Cluster', 'jurisdiction_summary': 'C1, C2 . State1',
     'filter': {'STATE_NAME': ['State1'], 'CONSTITUENCY': ['C1', 'C2']}},
    {'id': 'state_nodal', 'role': 'State Nodal Authority', 'label': 'State1', 'jurisdiction_summary': 'State1',
     'filter': {'STATE_NAME': ['State1']}},
    {'id': 'ministry', 'role': 'Ministry', 'label': 'Loaded corpus', 'jurisdiction_summary': 'National', 'filter': {}},
]


def work_row(wid, mp, state, constituency, severity='Low'):
    return {'WORK_ID': wid, 'WORK_DESCRIPTION': f'Work {wid}', 'MP_NAME': mp, 'CONSTITUENCY': constituency,
            'STATE_NAME': state, 'IDA_NAME': 'Agency', 'ACTUAL_AMOUNT': 1000.0, 'risk_score': 10.0,
            'severity_band': severity, 'review_notice': 'notice', 'fy_start_year': 2025, 'image_count': 1,
            'signals_json': json.dumps({}), 'ACTUAL_END_DATE': '2025-05-01', 'LETTER_NO': 'X'}


def quality_alert(aid, work_id, mp, state, constituency, code='amount_zero'):
    return {'id': aid, 'work_id': work_id, 'quality_code': code, 'severity': 'warning', 'field': 'actual_amount',
            'raw_value': '0', 'explanation': 'zero amount', 'affected_analyses': ['cost_peer'],
            'recommended_action': 'confirm', 'status': 'open', 'detector_version': 'quality-checks-v2',
            'group_key': f'{code}|actual_amount', 'mp_name': mp, 'state_name': state, 'constituency': constituency}


@pytest.fixture
def env(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    works = [
        work_row('W1', 'MP A', 'State1', 'C1', 'Critical'),   # in every scope except state_nodal's C-filter... actually State1 covers it
        work_row('W2', 'MP B', 'State1', 'C2', 'Critical'),   # different MP, same state/district cluster
        work_row('W3', 'MP C', 'State1', 'C3', 'Critical'),   # outside district cluster, inside state
        work_row('W4', 'MP D', 'State2', 'C4', 'Critical'),   # different state entirely
    ]
    pd.DataFrame(works).to_parquet(data_dir / 'scored_works.parquet')
    (data_dir / 'personas.json').write_text(json.dumps(PERSONAS), encoding='utf-8')
    (data_dir / 'duplicate_pairs.json').write_text('[]', encoding='utf-8')
    (data_dir / 'images.json').write_text('[]', encoding='utf-8')
    alerts = [
        quality_alert('a1', 'W1', 'MP A', 'State1', 'C1'),
        quality_alert('a2', 'W2', 'MP B', 'State1', 'C2'),
        quality_alert('a3', 'W3', 'MP C', 'State1', 'C3'),
        quality_alert('a4', 'W4', 'MP D', 'State2', 'C4'),
    ]
    (data_dir / 'quality_alerts.json').write_text(json.dumps(alerts), encoding='utf-8')
    (data_dir / 'lineage.json').write_text(json.dumps({
        'W1': [{'source': 's', 'raw_field': 'ACTUAL_AMOUNT', 'raw_value': '0', 'transformation': 'amount_normalize:ok',
                'normalized_value': '0', 'version': 'v1', 'timestamp': 't'}],
        'W4': [{'source': 's', 'raw_field': 'ACTUAL_AMOUNT', 'raw_value': '0', 'transformation': 'amount_normalize:ok',
                'normalized_value': '0', 'version': 'v1', 'timestamp': 't'}],
    }), encoding='utf-8')
    (data_dir / 'work_directory.json').write_text(json.dumps({
        'W1': {'mp_name': 'MP A', 'state_name': 'State1', 'constituency': 'C1'},
        'W4': {'mp_name': 'MP D', 'state_name': 'State2', 'constituency': 'C4'},
    }), encoding='utf-8')

    monkeypatch.setenv('NAZAR_DATA_DIR', str(data_dir))
    monkeypatch.setenv('NAZAR_DB_PATH', str(tmp_path / 'investigations.sqlite3'))
    monkeypatch.setenv('NAZAR_AUTH_SECRET', 'test-secret-for-phase-2-padding-to-32-bytes-minimum')
    monkeypatch.delenv('NAZAR_DATABASE_URL', raising=False)
    sys.modules.pop('backend.main', None)
    sys.modules.pop('backend.auth', None)
    import backend.main as main
    importlib.reload(main)
    yield main


PASSWORDS = {'mp.office': 'mp-lookcloser-24', 'district.authority': 'district-lookcloser-24',
             'state.nodal': 'state-lookcloser-24', 'ministry': 'ministry-lookcloser-24'}


def open_client(main):
    # TestClient only runs FastAPI's lifespan (populating app.state) inside
    # its context manager - enter it explicitly and let it close with the
    # interpreter/test session rather than threading a `with` through every
    # test, since several tests need two independently-authenticated clients
    # (or the same client re-logging-in) against one running app.
    c = TestClient(main.app)
    c.__enter__()
    return c


def client_as(main, persona_id):
    user_id = {'mp_office': 'mp.office', 'district_authority': 'district.authority',
               'state_nodal': 'state.nodal', 'ministry': 'ministry'}[persona_id]
    c = open_client(main)
    r = c.post('/auth/login', json={'user_id': user_id, 'password': PASSWORDS[user_id]})
    assert r.status_code == 200, r.text
    c.headers.update({'Authorization': f'Bearer {r.json()["token"]}'})
    return c


# --- B: authentication ---

def test_valid_login_returns_token_and_persona(env):
    c = open_client(env)
    r = c.post('/auth/login', json={'user_id': 'ministry', 'password': 'ministry-lookcloser-24'})
    assert r.status_code == 200
    body = r.json()
    assert body['persona']['id'] == 'ministry'
    assert 'token' in body and body['token'].count('.') == 2  # JWT shape


def test_invalid_password_rejected(env):
    c = open_client(env)
    r = c.post('/auth/login', json={'user_id': 'ministry', 'password': 'wrong-password'})
    assert r.status_code == 401


def test_unknown_user_rejected(env):
    c = open_client(env)
    r = c.post('/auth/login', json={'user_id': 'nobody', 'password': 'whatever'})
    assert r.status_code == 401


def test_missing_token_rejected(env):
    c = open_client(env)
    assert c.get('/works').status_code == 401
    assert c.get('/quality/alerts').status_code == 401


def test_tampered_token_rejected(env):
    c = client_as(env, 'ministry')
    token = c.headers['Authorization'].split(' ', 1)[1]
    tampered = token[:-4] + ('a' if token[-4] != 'a' else 'b') + token[-3:]
    c.headers.update({'Authorization': f'Bearer {tampered}'})
    assert c.get('/auth/me').status_code == 401


def test_expired_token_rejected(env, monkeypatch):
    from backend import auth
    monkeypatch.setattr(auth, 'AUTH_SECRET', 'test-secret-for-phase-2-padding-to-32-bytes-minimum')
    expired_claims = {'sub': 'ministry', 'persona_id': 'ministry', 'role': 'Ministry',
                       'iat': int(time.time()) - 100, 'exp': int(time.time()) - 50, 'jti': 'expired-jti'}
    token = pyjwt.encode(expired_claims, 'test-secret-for-phase-2-padding-to-32-bytes-minimum', algorithm='HS256')
    c = open_client(env)
    c.headers.update({'Authorization': f'Bearer {token}'})
    assert c.get('/auth/me').status_code == 401


def test_logout_revokes_token(env):
    c = client_as(env, 'ministry')
    assert c.get('/auth/me').status_code == 200
    assert c.post('/auth/logout').status_code == 200
    assert c.get('/auth/me').status_code == 401


def test_login_failure_is_audited(env):
    c = open_client(env)
    c.post('/auth/login', json={'user_id': 'ministry', 'password': 'wrong'})
    ministry = client_as(env, 'ministry')
    events = ministry.get('/audit', params={'event_type': 'login_failure'}).json()
    assert events['total'] >= 1
    assert events['items'][0]['user_id'] == 'ministry'
    assert events['items'][0]['success'] is False


# --- C: RBAC / jurisdiction isolation ---

def test_mp_office_sees_only_its_own_mp(env):
    c = client_as(env, 'mp_office')
    ids = {w['WORK_ID'] for w in c.get('/works', params={'status': 'Flagged'}).json()['items']}
    assert ids == {'W1'}


def test_mp_to_mp_isolation_returns_403_on_direct_fetch(env):
    c = client_as(env, 'mp_office')
    r = c.get('/works/W2')  # a different MP's work, same state
    assert r.status_code == 403


def test_district_authority_sees_its_cluster_not_other_districts(env):
    c = client_as(env, 'district_authority')
    ids = {w['WORK_ID'] for w in c.get('/works', params={'status': 'Flagged'}).json()['items']}
    assert ids == {'W1', 'W2'}  # C1, C2 - not W3 (C3, same state, different district)
    assert c.get('/works/W3').status_code == 403


def test_state_to_state_isolation(env):
    c = client_as(env, 'state_nodal')
    ids = {w['WORK_ID'] for w in c.get('/works', params={'status': 'Flagged'}).json()['items']}
    assert ids == {'W1', 'W2', 'W3'}  # all of State1
    assert c.get('/works/W4').status_code == 403  # State2


def test_ministry_has_national_access(env):
    c = client_as(env, 'ministry')
    ids = {w['WORK_ID'] for w in c.get('/works', params={'status': 'Flagged'}).json()['items']}
    assert ids == {'W1', 'W2', 'W3', 'W4'}
    for wid in ids:
        assert c.get(f'/works/{wid}').status_code == 200


def test_quality_alerts_are_jurisdiction_scoped(env):
    mp = client_as(env, 'mp_office')
    body = mp.get('/quality/alerts', params={'status': 'open'}).json()
    assert {a['work_id'] for a in body['items']} == {'W1'}

    state = client_as(env, 'state_nodal')
    body = state.get('/quality/alerts', params={'status': 'open'}).json()
    assert {a['work_id'] for a in body['items']} == {'W1', 'W2', 'W3'}

    ministry = client_as(env, 'ministry')
    body = ministry.get('/quality/alerts', params={'status': 'open'}).json()
    assert {a['work_id'] for a in body['items']} == {'W1', 'W2', 'W3', 'W4'}


def test_quality_alert_detail_403_outside_scope(env):
    mp = client_as(env, 'mp_office')
    assert mp.get('/quality/alerts/a2').status_code == 403  # MP B's alert
    assert mp.get('/quality/alerts/a1').status_code == 200  # its own


def test_quality_lineage_403_outside_scope(env):
    mp = client_as(env, 'mp_office')
    assert mp.get('/quality/lineage/W4').status_code == 403
    assert mp.get('/quality/lineage/W1').status_code == 200


def test_resolve_quality_alert_403_outside_scope(env):
    mp = client_as(env, 'mp_office')
    r = mp.post('/quality/alerts/a2/resolve', json={'status': 'resolved', 'reason': 'trying to resolve another MP’s alert'})
    assert r.status_code == 403


def test_direct_api_bypass_attempt_via_forged_persona_claim_fails(env):
    """A token whose persona_id claim was hand-edited to 'ministry' but signed
    with the WRONG secret must be rejected outright - proves the server
    verifies the signature, not just trusts whatever persona_id a client
    sends."""
    forged = pyjwt.encode({'sub': 'mp.office', 'persona_id': 'ministry', 'role': 'Ministry',
                            'iat': int(time.time()), 'exp': int(time.time()) + 3600, 'jti': 'forged'},
                           'attacker-does-not-know-the-real-secret', algorithm='HS256')
    c = open_client(env)
    c.headers.update({'Authorization': f'Bearer {forged}'})
    assert c.get('/works').status_code == 401


def test_audit_endpoint_is_ministry_only(env):
    mp = client_as(env, 'mp_office')
    assert mp.get('/audit').status_code == 403
    ministry = client_as(env, 'ministry')
    assert ministry.get('/audit').status_code == 200


# --- D: reviewer attribution comes from the token, not the request body ---

def test_investigation_decision_attributed_to_authenticated_persona_not_body(env):
    c = client_as(env, 'mp_office')
    r = c.post('/investigations', json={'work_id': 'W1', 'decision': 'Confirm', 'reason': 'evidence reviewed'})
    assert r.status_code == 200
    assert r.json()['persona_id'] == 'mp_office'  # server-derived, Investigation has no persona_id field at all
    detail = c.get('/works/W1').json()
    assert detail['investigations'][0]['persona_id'] == 'mp_office'


def test_quality_resolution_attributed_to_authenticated_persona(env):
    c = client_as(env, 'mp_office')
    r = c.post('/quality/alerts/a1/resolve', json={'status': 'resolved', 'reason': 'checked at source'})
    assert r.status_code == 200
    ministry = client_as(env, 'ministry')
    events = ministry.get('/audit', params={'event_type': 'quality_alert_resolved'}).json()
    assert events['items'][0]['persona_id'] == 'mp_office'
    assert events['items'][0]['entity_id'] == 'a1'
    assert events['items'][0]['before_state'] == {'status': 'open'}
    assert events['items'][0]['after_state'] == {'status': 'resolved'}
