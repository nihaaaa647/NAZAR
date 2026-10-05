"""Phase 5 section E: production startup must fail loudly rather than
silently run insecurely. Both gates raise a RuntimeError at import time
(module-level code), before any request can be served - so these tests
import the module fresh under each env combination rather than hitting
an endpoint."""
import sys

import pytest


def _fresh_import(monkeypatch, **env):
    # Popping 'backend.main'/'backend.auth' alone isn't enough: once
    # 'backend.auth' has been imported anywhere in the process, Python sets
    # it as an attribute on the already-cached 'backend' package object, and
    # `from backend import auth` finds that attribute directly without
    # re-running backend/auth.py - so the package itself must be popped too,
    # or a later test in the same run sees a stale (already-secret-bearing)
    # auth module regardless of the env this test sets.
    for mod in ('backend.main', 'backend.auth', 'backend'):
        sys.modules.pop(mod, None)
    for key in ('NAZAR_ENV', 'NAZAR_AUTH_SECRET', 'NAZAR_CORS_ORIGINS', 'NAZAR_DATABASE_URL'):
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import backend.main as main
    return main


def test_production_without_auth_secret_refuses_to_start(monkeypatch):
    with pytest.raises(RuntimeError, match='NAZAR_AUTH_SECRET'):
        _fresh_import(monkeypatch, NAZAR_ENV='production')


def test_production_with_auth_secret_but_wildcard_cors_refuses_to_start(monkeypatch):
    with pytest.raises(RuntimeError, match='NAZAR_CORS_ORIGINS'):
        _fresh_import(monkeypatch, NAZAR_ENV='production',
                       NAZAR_AUTH_SECRET='a' * 32)


def test_production_with_secret_and_explicit_cors_origin_starts(monkeypatch):
    main = _fresh_import(monkeypatch, NAZAR_ENV='production', NAZAR_AUTH_SECRET='a' * 32,
                          NAZAR_CORS_ORIGINS='https://nazar-review.example')
    assert main.app is not None


def test_development_defaults_start_without_either_var(monkeypatch):
    # Development is deliberately permissive (a random per-process secret,
    # wildcard CORS) - only NAZAR_ENV=production is a hard gate.
    main = _fresh_import(monkeypatch)
    assert main.app is not None


# --- request-size limit and security headers, against a running app ---

from tests.test_auth_rbac import PERSONAS, work_row  # noqa: E402
import json  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def running_env(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    pd.DataFrame([work_row('W1', 'MP A', 'State1', 'C1')]).to_parquet(data_dir / 'scored_works.parquet')
    (data_dir / 'personas.json').write_text(json.dumps(PERSONAS), encoding='utf-8')
    for name in ('duplicate_pairs.json', 'images.json', 'quality_alerts.json', 'case_candidates.json', 'image_matches.json'):
        (data_dir / name).write_text('[]', encoding='utf-8')
    for name in ('lineage.json', 'work_directory.json'):
        (data_dir / name).write_text('{}', encoding='utf-8')
    monkeypatch.setenv('NAZAR_DATA_DIR', str(data_dir))
    monkeypatch.setenv('NAZAR_DB_PATH', str(tmp_path / 'investigations.sqlite3'))
    monkeypatch.setenv('NAZAR_AUTH_SECRET', 'test-secret-padding-to-32-bytes-min')
    monkeypatch.delenv('NAZAR_DATABASE_URL', raising=False)
    monkeypatch.delenv('NAZAR_ENV', raising=False)
    for mod in ('backend.main', 'backend.auth', 'backend'):
        sys.modules.pop(mod, None)
    import backend.main as main
    return main


def test_oversized_request_body_is_rejected(running_env):
    with TestClient(running_env.app) as c:
        big_reason = 'x' * (running_env.MAX_REQUEST_BODY_BYTES + 1000)
        r = c.post('/auth/login', json={'user_id': 'ministry', 'password': big_reason})
        assert r.status_code == 413


def test_response_carries_basic_security_headers(running_env):
    with TestClient(running_env.app) as c:
        r = c.get('/personas')
        assert r.headers.get('x-content-type-options') == 'nosniff'
        assert r.headers.get('x-frame-options') == 'DENY'


def test_health_ready_version_capabilities_endpoints(running_env):
    with TestClient(running_env.app) as c:
        h = c.get('/health')
        assert h.status_code == 200 and h.json() == {'status': 'ok'}

        r = c.get('/ready')
        assert r.status_code == 200
        body = r.json()
        assert body['ready'] is True
        assert body['checks']['database'] == 'ok'
        assert body['checks']['scored_works_loaded'] == 'ok'

        v = c.get('/version')
        assert v.status_code == 200
        assert v.json()['database'] == 'sqlite'
        assert 'build_commit' in v.json()

        caps = c.get('/capabilities')
        assert caps.status_code == 200
        body = caps.json()
        for key in ('IMPLEMENTED_PUBLIC_DATA', 'SYNTHETIC_DEMONSTRATION', 'AUTHORISED_DATA_REQUIRED', 'UNAVAILABLE'):
            assert key in body
        # never claim fraud is automatically declared anywhere in the capability list
        assert not any('fraud detected' in x.lower() or 'declares fraud' in x.lower()
                        for v in body.values() for x in v)


def test_satellite_image_rejects_unknown_and_path_traversal_asset_ids(running_env):
    # running_env has no satellite manifest at all, so satellite_asset_ids is
    # empty - every asset_id, including a traversal attempt, must 404, never
    # touch the filesystem with an unvalidated path.
    with TestClient(running_env.app) as c:
        for asset_id in ('unknown_asset', '..\\..\\..\\Windows\\System32\\drivers\\etc\\hosts', '../../../../etc/passwd'):
            r = c.get(f'/satellite/image/{asset_id}/t1')
            assert r.status_code == 404


def test_login_rate_limit_blocks_after_max_attempts(running_env):
    with TestClient(running_env.app) as c:
        for _ in range(running_env.LOGIN_RATE_LIMIT_MAX_ATTEMPTS):
            r = c.post('/auth/login', json={'user_id': 'ministry', 'password': 'wrong'})
            assert r.status_code == 401
        r = c.post('/auth/login', json={'user_id': 'ministry', 'password': 'wrong'})
        assert r.status_code == 429
        # Rate limiting is a client-IP throttle, not an account lockout - the
        # correct password is rejected too, same as any other attempt right now.
        r = c.post('/auth/login', json={'user_id': 'ministry', 'password': 'ministry-lookcloser-24'})
        assert r.status_code == 429
