"""Phase 4: image-match workspace endpoints - RBAC across BOTH paired works,
reviewer actions (no 'declare fraud'), and review-session timing."""
import importlib
import json
import sys

import pandas as pd
import pytest

from tests.test_auth_rbac import PERSONAS, PASSWORDS, open_client, work_row


def match_record(match_id, work_a, work_b, classification, risk_eligible):
    return {'match_id': match_id, 'image_id_a': f'img-{work_a}', 'image_id_b': f'img-{work_b}',
            'work_id_a': work_a, 'work_id_b': work_b, 'phash_distance': 2, 'classification': classification,
            'risk_eligible': risk_eligible, 'reason': 'test fixture', 'good_matches': 150, 'inliers': 120,
            'inlier_ratio': 0.8, 'matched_area_coverage': 0.3, 'keypoints_a': 400, 'keypoints_b': 380,
            'masked_keypoints_excluded_a': 20, 'masked_keypoints_excluded_b': 18,
            'preprocessing_version': 'image-preprocess-v1', 'detector_version': 'image-match-v2'}


@pytest.fixture
def env(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    works = [work_row('W1', 'MP A', 'State1', 'C1'), work_row('W2', 'MP B', 'State1', 'C2'),
             work_row('W3', 'MP D', 'State2', 'C4')]
    pd.DataFrame(works).to_parquet(data_dir / 'scored_works.parquet')
    (data_dir / 'personas.json').write_text(json.dumps(PERSONAS), encoding='utf-8')
    (data_dir / 'duplicate_pairs.json').write_text('[]', encoding='utf-8')
    (data_dir / 'images.json').write_text('[]', encoding='utf-8')
    (data_dir / 'quality_alerts.json').write_text('[]', encoding='utf-8')
    (data_dir / 'lineage.json').write_text('{}', encoding='utf-8')
    (data_dir / 'work_directory.json').write_text(json.dumps({
        'W1': {'mp_name': 'MP A', 'state_name': 'State1', 'constituency': 'C1'},
        'W2': {'mp_name': 'MP B', 'state_name': 'State1', 'constituency': 'C2'},
        'W3': {'mp_name': 'MP D', 'state_name': 'State2', 'constituency': 'C4'},
    }), encoding='utf-8')
    (data_dir / 'case_candidates.json').write_text('[]', encoding='utf-8')
    matches = [
        match_record('m-in-scope', 'W1', 'W2', 'confirmed_visual_correspondence', True),   # both State1
        match_record('m-cross-jurisdiction', 'W1', 'W3', 'confirmed_visual_correspondence', True),  # State1 + State2
        match_record('m-candidate', 'W1', 'W2', 'candidate_only', False),
        match_record('m-watermark', 'W1', 'W2', 'rejected_watermark', False),
    ]
    (data_dir / 'image_matches.json').write_text(json.dumps(matches), encoding='utf-8')

    monkeypatch.setenv('NAZAR_DATA_DIR', str(data_dir))
    monkeypatch.setenv('NAZAR_DB_PATH', str(tmp_path / 'investigations.sqlite3'))
    monkeypatch.setenv('NAZAR_AUTH_SECRET', 'test-secret-for-phase-4-padding-to-32-bytes-minimum')
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


def test_state_nodal_sees_only_fully_in_scope_matches(env):
    state = client_as(env, 'state_nodal')  # scoped to State1
    body = state.get('/images/matches').json()
    ids = {m['match_id'] for m in body['items']}
    assert ids == {'m-in-scope', 'm-candidate', 'm-watermark'}
    assert 'm-cross-jurisdiction' not in ids  # W3 is State2 - excluded even though W1 is in scope


def test_ministry_sees_all_matches(env):
    ministry = client_as(env, 'ministry')
    body = ministry.get('/images/matches').json()
    assert {m['match_id'] for m in body['items']} == {'m-in-scope', 'm-cross-jurisdiction', 'm-candidate', 'm-watermark'}


def test_direct_access_to_cross_jurisdiction_match_is_403(env):
    state = client_as(env, 'state_nodal')
    r = state.get('/images/matches/m-cross-jurisdiction')
    assert r.status_code == 403
    # Ministry (has both jurisdictions) can still see it - the "route to a
    # role with access to both" fallback.
    ministry = client_as(env, 'ministry')
    assert ministry.get('/images/matches/m-cross-jurisdiction').status_code == 200


def test_review_action_cannot_declare_fraud(env):
    state = client_as(env, 'state_nodal')
    r = state.post('/images/matches/m-in-scope/review', json={'action': 'declare_fraud', 'reason': 'x'})
    assert r.status_code == 422  # not a valid enum member


def test_confirm_visual_correspondence_persists_and_is_reviewable(env):
    state = client_as(env, 'state_nodal')
    r = state.post('/images/matches/m-in-scope/review', json={'action': 'confirm_visual_correspondence', 'reason': 'looks like the same site'})
    assert r.status_code == 200
    assert r.json()['latest_action'] == 'confirm_visual_correspondence'
    reviews = state.get('/images/matches/m-in-scope/reviews').json()
    assert reviews['items'][0]['action'] == 'confirm_visual_correspondence'
    assert reviews['items'][0]['role'] == 'State Nodal Authority'


def test_dismiss_actions_and_add_note(env):
    state = client_as(env, 'state_nodal')
    assert state.post('/images/matches/m-watermark/review', json={'action': 'dismiss_watermark', 'reason': 'confirmed scanner footer'}).status_code == 200
    assert state.post('/images/matches/m-in-scope/review', json={'action': 'add_note', 'note': 'flagging for site visit'}).status_code == 200
    reviews = state.get('/images/matches/m-in-scope/reviews').json()['items']
    assert reviews[-1]['note'] == 'flagging for site visit'


def test_cross_jurisdiction_review_blocked(env):
    state = client_as(env, 'state_nodal')
    r = state.post('/images/matches/m-cross-jurisdiction/review', json={'action': 'confirm_visual_correspondence', 'reason': 'x'})
    assert r.status_code == 403


def test_candidate_only_and_watermark_are_zero_risk_by_construction(env):
    ministry = client_as(env, 'ministry')
    body = ministry.get('/images/matches').json()
    by_id = {m['match_id']: m for m in body['items']}
    assert by_id['m-candidate']['risk_eligible'] is False
    assert by_id['m-watermark']['risk_eligible'] is False
    assert by_id['m-in-scope']['risk_eligible'] is True


def test_classification_filter(env):
    ministry = client_as(env, 'ministry')
    body = ministry.get('/images/matches', params={'classification': 'rejected_watermark'}).json()
    assert {m['match_id'] for m in body['items']} == {'m-watermark'}


# --- review-session timing (section K) ---

def test_review_session_start_and_end_records_active_duration(env):
    ministry = client_as(env, 'ministry')
    cases = ministry.get('/cases').json()
    # No cases loaded in this fixture (case_candidates.json is empty) - use
    # escalation to get one real case_id to attach a session to.
    esc = ministry.post('/cases/escalate', json={'work_id': 'W1', 'reason': 'timing test'})
    case_id = esc.json()['case_id']
    start = ministry.post(f'/cases/{case_id}/review-session/start')
    assert start.status_code == 200
    session_id = start.json()['session_id']
    end = ministry.post(f'/cases/{case_id}/review-session/{session_id}/end')
    assert end.status_code == 200
    assert end.json()['active_hours'] >= 0


def test_only_the_starting_reviewer_can_end_a_session(env):
    ministry = client_as(env, 'ministry')
    esc = ministry.post('/cases/escalate', json={'work_id': 'W1', 'reason': 'timing test 2'})
    case_id = esc.json()['case_id']
    start = ministry.post(f'/cases/{case_id}/review-session/start')
    session_id = start.json()['session_id']
    other = client_as(env, 'state_nodal')
    r = other.post(f'/cases/{case_id}/review-session/{session_id}/end')
    assert r.status_code == 403


def test_metrics_use_recorded_session_time_when_available(env):
    ministry = client_as(env, 'ministry')
    esc = ministry.post('/cases/escalate', json={'work_id': 'W1', 'reason': 'timing test 3'})
    case_id = esc.json()['case_id']
    before = ministry.get('/metrics').json()
    assert before['cases_resolved_per_investigator_hour'] == 'unavailable'
    start = ministry.post(f'/cases/{case_id}/review-session/start').json()
    ministry.post(f"/cases/{case_id}/review-session/{start['session_id']}/end")
    ministry.post(f'/cases/{case_id}/transition', json={'to_status': 'TRIAGED'})
    ministry.post(f'/cases/{case_id}/transition', json={'to_status': 'UNDER_REVIEW'})
    ministry.post(f'/cases/{case_id}/transition', json={'to_status': 'RESOLVED_NO_ISSUE', 'reason': 'no issue'})
    after = ministry.get('/metrics').json()
    assert after['cases_resolved_per_investigator_hour'] != 'unavailable'
