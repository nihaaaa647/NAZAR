"""Phase 5 section B: the standalone eligibility gate is reconciled with the
real change-detection model (ml/cv/satellite_change.py) - its CSV output
used to exist but was never read by the backend, so a reviewer never saw
whether NAZAR's own NDVI/pixel-diff model found a change. These tests build
a minimal real fixture (manifest + change-results CSV + one satellite work
row) and hit the actual endpoint."""
import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_auth_rbac import PERSONAS, work_row


def satellite_row(work_id, asset_id, category='road', lat=18.5, lon=78.1, end_date='01-May-2026'):
    return {'work_id': work_id, 'MP_NAME': 'MP A', 'IDA_NAME': 'Agency', 'WORK_DESCRIPTION': 'A road',
            'area_name': 'Area', 'ACTUAL_AMOUNT': 100000.0, 'LETTER_NO': 'X', 'ACTUAL_END_DATE': end_date,
            'has_images': False, 'branch': 'A', 'asset_id': asset_id, 'lat': lat, 'lon': lon,
            'source_scheme': 'osm_real', 'category': category, 'vendor_id': None, 'award_date': '2026-01-01',
            'risk_score': 10.0, 'severity_band': 'Low', 'signals_json': '{}', 'review_notice': 'notice'}


@pytest.fixture
def env(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    pd.DataFrame([work_row('W1', 'MP A', 'State1', 'C1')]).to_parquet(data_dir / 'scored_works.parquet')
    (data_dir / 'personas.json').write_text(json.dumps(PERSONAS), encoding='utf-8')
    for name in ('duplicate_pairs.json', 'images.json', 'quality_alerts.json', 'case_candidates.json', 'image_matches.json'):
        (data_dir / name).write_text('[]', encoding='utf-8')
    for name in ('lineage.json', 'work_directory.json'):
        (data_dir / name).write_text('{}', encoding='utf-8')

    canonical = data_dir / 'canonical'
    canonical.mkdir()
    pd.DataFrame([
        satellite_row('SAT1', 'asset_eligible_change'),
        satellite_row('SAT2', 'asset_eligible_no_change'),
        satellite_row('SAT3', 'asset_cloudy', category='road'),
        satellite_row('SAT4', 'asset_below_res', category='streetlight'),
    ]).to_csv(canonical / 'satellite_works_scored.csv', index=False)
    pd.DataFrame([
        {'asset_id': 'asset_eligible_change', 'change_detected': True, 'confidence': 0.8, 'ndvi_delta': 0.3, 'pixel_diff_score': 0.3},
        {'asset_id': 'asset_eligible_no_change', 'change_detected': False, 'confidence': 0.0, 'ndvi_delta': 0.01, 'pixel_diff_score': 0.01},
    ]).to_csv(canonical / 'satellite_change_results.csv', index=False)
    (canonical / 'vendor_network.csv').write_text('vendor_id,network_risk_score\n', encoding='utf-8')

    sat_cache = data_dir / 'satellite_cache'
    sat_cache.mkdir()
    manifest = {
        'asset_eligible_change': {'t1': {'datetime': '2026-04-01T00:00:00Z', 'cloud_cover': 2.0, 'rgb': 'x'},
                                   't2': {'datetime': '2026-05-02T00:00:00Z', 'cloud_cover': 3.0, 'rgb': 'x'}},
        'asset_eligible_no_change': {'t1': {'datetime': '2026-04-01T00:00:00Z', 'cloud_cover': 1.0, 'rgb': 'x'},
                                      't2': {'datetime': '2026-05-02T00:00:00Z', 'cloud_cover': 1.0, 'rgb': 'x'}},
        'asset_cloudy': {'t1': {'datetime': '2026-04-01T00:00:00Z', 'cloud_cover': 80.0, 'rgb': 'x'},
                          't2': {'datetime': '2026-05-02T00:00:00Z', 'cloud_cover': 75.0, 'rgb': 'x'}},
        'asset_below_res': {'t1': {'datetime': '2026-04-01T00:00:00Z', 'cloud_cover': 1.0, 'rgb': 'x'},
                             't2': {'datetime': '2026-05-02T00:00:00Z', 'cloud_cover': 1.0, 'rgb': 'x'}},
    }
    (sat_cache / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    monkeypatch.setenv('NAZAR_DATA_DIR', str(data_dir))
    monkeypatch.setenv('NAZAR_DB_PATH', str(tmp_path / 'investigations.sqlite3'))
    monkeypatch.setenv('NAZAR_AUTH_SECRET', 'test-secret-padding-to-32-bytes-min')
    monkeypatch.delenv('NAZAR_DATABASE_URL', raising=False)
    monkeypatch.delenv('NAZAR_ENV', raising=False)
    import sys
    for mod in ('backend.main', 'backend.auth', 'backend'):
        sys.modules.pop(mod, None)
    import backend.main as main
    return main


def _login(client, main):
    from tests.test_auth_rbac import PASSWORDS
    r = client.post('/auth/login', json={'user_id': 'ministry', 'password': PASSWORDS['ministry']})
    assert r.status_code == 200, r.text
    client.headers.update({'Authorization': f'Bearer {r.json()["token"]}'})


def test_eligible_asset_with_change_detected_shows_change_visible(env):
    with TestClient(env.app) as c:
        _login(c, env)
        r = c.get('/satellite/SAT1')
        assert r.status_code == 200
        body = r.json()
        assert body['satellite_eligibility']['status'] == 'eligible'
        assert body['change_result']['outcome'] == 'change_visible'
        assert body['change_result']['message'] == env.CHANGE_DETECTED_LANGUAGE
        assert 'was not built' not in body['change_result']['message'].lower()


def test_eligible_asset_with_no_change_shows_no_reliable_change(env):
    with TestClient(env.app) as c:
        _login(c, env)
        r = c.get('/satellite/SAT2')
        body = r.json()
        assert body['change_result']['outcome'] == 'no_reliable_change_visible'
        assert body['change_result']['message'] == env.NO_CHANGE_LANGUAGE


def test_high_real_cloud_cover_blocks_eligibility_and_hides_change_result(env):
    with TestClient(env.app) as c:
        _login(c, env)
        r = c.get('/satellite/SAT3')
        body = r.json()
        assert body['satellite_eligibility']['status'] == 'cloud_obstructed'
        assert body['change_result'] is None


def test_small_asset_category_is_below_resolution_not_a_risk_signal(env):
    with TestClient(env.app) as c:
        _login(c, env)
        r = c.get('/satellite/SAT4')
        body = r.json()
        assert body['satellite_eligibility']['status'] == 'asset_below_resolution'
        assert body['change_result'] is None
