"""Phase 4 mandatory safeguard #2: a timestamped backup must be created
before a migration touches an EXISTING local database - including when only
SOME of the new tables already exist (a partial-overlap bug was found and
fixed in this phase: the original check skipped backup on ANY overlap
instead of requiring ALL new tables to already be present)."""
import importlib
import json
import sqlite3
import sys

import pandas as pd
import pytest

from tests.test_auth_rbac import PERSONAS, work_row


@pytest.fixture
def env(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    pd.DataFrame([work_row('W1', 'MP A', 'State1', 'C1')]).to_parquet(data_dir / 'scored_works.parquet')
    (data_dir / 'personas.json').write_text(json.dumps(PERSONAS), encoding='utf-8')
    (data_dir / 'duplicate_pairs.json').write_text('[]', encoding='utf-8')
    (data_dir / 'images.json').write_text('[]', encoding='utf-8')
    (data_dir / 'quality_alerts.json').write_text('[]', encoding='utf-8')
    (data_dir / 'lineage.json').write_text('{}', encoding='utf-8')
    (data_dir / 'work_directory.json').write_text('{}', encoding='utf-8')
    (data_dir / 'case_candidates.json').write_text('[]', encoding='utf-8')
    (data_dir / 'image_matches.json').write_text('[]', encoding='utf-8')

    monkeypatch.setenv('NAZAR_DATA_DIR', str(data_dir))
    monkeypatch.setenv('NAZAR_DB_PATH', str(tmp_path / 'investigations.sqlite3'))
    monkeypatch.setenv('NAZAR_AUTH_SECRET', 'test-secret-for-phase-4-padding-to-32-bytes-minimum')
    monkeypatch.delenv('NAZAR_DATABASE_URL', raising=False)
    monkeypatch.delenv('NAZAR_ENV', raising=False)
    sys.modules.pop('backend.main', None)
    sys.modules.pop('backend.auth', None)
    import backend.main as main
    yield main, tmp_path


def test_fresh_database_needs_no_backup(env):
    main, tmp_path = env
    db_path = tmp_path / 'investigations.sqlite3'
    monkey_db = db_path
    assert not monkey_db.exists()
    result = main.backup_before_migration({'cases'})
    assert result is None
    assert not list(tmp_path.glob('*.backup-*'))


def test_backup_created_when_a_new_table_is_genuinely_new(env):
    main, tmp_path = env
    db_path = tmp_path / 'investigations.sqlite3'
    con = sqlite3.connect(db_path)
    con.execute('CREATE TABLE investigations (work_id TEXT)')
    con.execute("INSERT INTO investigations VALUES ('W1')")
    con.commit()
    con.close()
    result = main.backup_before_migration({'cases'})
    assert result is not None
    assert result.exists()
    backup_con = sqlite3.connect(result)
    assert backup_con.execute('SELECT work_id FROM investigations').fetchall() == [('W1',)]
    backup_con.close()


def test_partial_overlap_still_triggers_backup(env):
    """The bug this test guards against: some new_tables already exist
    ('cases', from an earlier Phase 3 migration) but others don't
    ('case_context_snapshots', new in Phase 4) - a backup must still happen,
    not be skipped just because SOME overlap exists."""
    main, tmp_path = env
    db_path = tmp_path / 'investigations.sqlite3'
    con = sqlite3.connect(db_path)
    con.execute('CREATE TABLE cases (case_id TEXT PRIMARY KEY)')
    con.execute("INSERT INTO cases VALUES ('case1')")
    con.commit()
    con.close()
    result = main.backup_before_migration({'cases', 'case_context_snapshots', 'image_match_reviews'})
    assert result is not None, 'partial overlap must still back up - case_context_snapshots/image_match_reviews are genuinely new'
    assert result.exists()


def test_no_backup_when_every_new_table_already_exists(env):
    main, tmp_path = env
    db_path = tmp_path / 'investigations.sqlite3'
    con = sqlite3.connect(db_path)
    con.execute('CREATE TABLE cases (case_id TEXT PRIMARY KEY)')
    con.execute('CREATE TABLE case_history (id TEXT PRIMARY KEY)')
    con.execute("INSERT INTO cases VALUES ('case1')")
    con.commit()
    con.close()
    result = main.backup_before_migration({'cases', 'case_history'})
    assert result is None
    assert not list(tmp_path.glob('*.backup-*'))


def test_remote_database_url_skips_local_backup(env, monkeypatch):
    main, tmp_path = env
    monkeypatch.setattr(main, 'DATABASE_URL', 'postgresql://example/db')
    result = main.backup_before_migration({'cases'})
    assert result is None
