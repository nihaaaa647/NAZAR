import importlib
import json
import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    pd.DataFrame([{'WORK_ID': 'W1', 'WORK_DESCRIPTION': 'Road repair', 'MP_NAME': 'MP A',
                    'CONSTITUENCY': 'C1', 'STATE_NAME': 'State', 'IDA_NAME': 'Agency A',
                    'ACTUAL_AMOUNT': 1000.0, 'risk_score': 10.0, 'severity_band': 'Low',
                    'review_notice': 'notice', 'fy_start_year': 2025, 'image_count': 1,
                    'signals_json': json.dumps({}), 'ACTUAL_END_DATE': '2025-05-01', 'LETTER_NO': 'X'}]
                 ).to_parquet(data_dir / 'scored_works.parquet')
    (data_dir / 'personas.json').write_text(json.dumps(
        [{'id': 'ministry', 'role': 'Ministry', 'label': 'Loaded corpus', 'jurisdiction_summary': 'All', 'filter': {}}]),
        encoding='utf-8')
    (data_dir / 'duplicate_pairs.json').write_text('[]', encoding='utf-8')
    (data_dir / 'images.json').write_text('[]', encoding='utf-8')
    alerts = [
        {'id': 'a1', 'work_id': 'W1', 'quality_code': 'amount_zero', 'severity': 'warning', 'field': 'actual_amount',
         'raw_value': '0', 'explanation': 'zero amount', 'affected_analyses': ['cost_peer'],
         'recommended_action': 'confirm', 'status': 'open', 'detector_version': 'quality-checks-v1'},
        {'id': 'a2', 'work_id': 'W2', 'quality_code': 'amount_parsing_failed', 'severity': 'critical',
         'field': 'actual_amount', 'raw_value': 'garbled', 'explanation': 'could not parse',
         'affected_analyses': ['cost_peer'], 'recommended_action': 'check source', 'status': 'open',
         'detector_version': 'quality-checks-v1'},
    ]
    (data_dir / 'quality_alerts.json').write_text(json.dumps(alerts), encoding='utf-8')
    lineage = {'W1': [{'source': 'works_with_images.csv', 'raw_field': 'ACTUAL_AMOUNT', 'raw_value': '1000',
                        'transformation': 'amount_normalize:ok', 'normalized_value': '1000.0',
                        'version': 'amount-normalize-v1', 'timestamp': '2026-01-01T00:00:00+00:00'}]}
    (data_dir / 'lineage.json').write_text(json.dumps(lineage), encoding='utf-8')

    monkeypatch.setenv('NAZAR_DATA_DIR', str(data_dir))
    monkeypatch.setenv('NAZAR_DB_PATH', str(tmp_path / 'investigations.sqlite3'))
    monkeypatch.delenv('NAZAR_DATABASE_URL', raising=False)
    sys.modules.pop('backend.main', None)
    import backend.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        token = c.post('/auth/login', json={'user_id': 'ministry', 'password': 'ministry-lookcloser-24'}).json()['token']
        c.headers.update({'Authorization': f'Bearer {token}'})
        yield c


def test_list_alerts_filtering_and_pagination(client):
    r = client.get('/quality/alerts')
    assert r.status_code == 200
    body = r.json()
    assert body['total'] == 2
    assert body['notice'] == 'Data-quality issues reduce analytical confidence; they are not evidence of fraud.'
    # Stable sort: critical before warning.
    assert [a['id'] for a in body['items']] == ['a2', 'a1']

    r = client.get('/quality/alerts', params={'severity': 'critical'})
    assert r.json()['total'] == 1
    assert r.json()['items'][0]['id'] == 'a2'

    r = client.get('/quality/alerts', params={'work_id': 'W1'})
    assert r.json()['total'] == 1

    r = client.get('/quality/alerts', params={'limit': 1, 'offset': 1})
    assert len(r.json()['items']) == 1
    assert r.json()['items'][0]['id'] == 'a1'


def test_alert_detail_includes_lineage(client):
    r = client.get('/quality/alerts/a1')
    assert r.status_code == 200
    body = r.json()
    assert body['lineage'][0]['raw_field'] == 'ACTUAL_AMOUNT'

    assert client.get('/quality/alerts/does-not-exist').status_code == 404


def test_lineage_endpoint(client):
    r = client.get('/quality/lineage/W1')
    assert r.status_code == 200
    assert r.json()['entries'][0]['normalized_value'] == '1000.0'
    assert client.get('/quality/lineage/does-not-exist').status_code == 404


def test_resolve_requires_reason(client):
    r = client.post('/quality/alerts/a1/resolve', json={'status': 'resolved', 'reason': ''})
    assert r.status_code == 422


def test_resolution_persists(client):
    r = client.post('/quality/alerts/a1/resolve', json={'status': 'dismissed', 'reason': 'Confirmed with source portal.'})
    assert r.status_code == 200
    assert r.json()['status'] == 'dismissed'
    assert r.json()['resolution_reason'] == 'Confirmed with source portal.'

    listed = client.get('/quality/alerts', params={'status': 'dismissed'}).json()
    assert listed['total'] == 1
    assert listed['items'][0]['id'] == 'a1'

    # Still open in the raw source file - the resolution lives only in the DB.
    still_open = client.get('/quality/alerts', params={'status': 'open'}).json()
    assert still_open['total'] == 1
    assert still_open['items'][0]['id'] == 'a2'

    # Overwriting a resolution updates in place rather than duplicating.
    r2 = client.post('/quality/alerts/a1/resolve', json={'status': 'resolved', 'reason': 'Re-checked.'})
    assert r2.json()['status'] == 'resolved'
    assert client.get('/quality/alerts').json()['counts']['status']['resolved'] == 1


def test_resolve_unknown_alert_404(client):
    r = client.post('/quality/alerts/nope/resolve', json={'status': 'resolved', 'reason': 'x'})
    assert r.status_code == 404


def test_summary(client):
    r = client.get('/quality/summary')
    assert r.status_code == 200
    body = r.json()
    assert body['total'] == 2
    assert body['severity']['critical'] == 1
    assert body['severity']['warning'] == 1
