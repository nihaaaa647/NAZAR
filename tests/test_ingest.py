import json

import pandas as pd
import pytest

from pipelines.ingest import ingest


def corpus(tmp_path, *, end='01-May-2025', amount='90'):
    raw = tmp_path / 'raw'
    raw.mkdir()
    common = {'WORK_RECOMMENDATION_DTL_ID': '1', 'LETTER_NO': 'LN/\t MP319/2025-2026/32',
              'STATE_NAME': 'State', 'WORK_CATEGORY': 'Normal/Others', 'ACTIVITY_NAME': 'WS/MP319/2025-2026/1-Roads'}
    pd.DataFrame([{**common, 'WORK_ID': '20', 'ACTUAL_AMOUNT': amount, 'ACTUAL_END_DATE': end,
                   'image_count': 1, 'local_image_filenames': 'missing.jpg'}]).to_csv(raw / 'works_with_images.csv', index=False)
    pd.DataFrame([{**common, 'SANCTION_DATE': '10-Apr-2025', 'RECOMMENDATION_DATE': '01-Apr-2025',
                   'SANCTION_AMOUNT': '100', 'WORK_STAGE': 'Physical Inspection'},
                  {**common, 'WORK_RECOMMENDATION_DTL_ID': '2', 'SANCTION_DATE': '11-Apr-2025',
                   'RECOMMENDATION_DATE': '01-Apr-2025', 'SANCTION_AMOUNT': '200', 'WORK_STAGE': 'Sanction'}
                 ]).to_csv(raw / 'works_sanctioned.csv', index=False)
    return raw


def test_csv_union_real_dates_and_repeatable_snapshot(tmp_path):
    raw = corpus(tmp_path)
    output = tmp_path / 'canonical'
    first = ingest(raw, output)
    timestamp = (output / 'works.csv').stat().st_mtime_ns
    second = ingest(raw, output)
    assert first['works_csv_sha256'] == second['works_csv_sha256']
    assert timestamp == (output / 'works.csv').stat().st_mtime_ns
    rows = pd.read_csv(output / 'works.csv')
    assert len(rows) == 2
    assert rows.iloc[0].duration_days == 21
    assert rows.iloc[0].duration_basis == 'real_sanction_date'
    assert rows.iloc[0].work_stage == 'Work Completed'
    assert rows.iloc[0].sanctioned_work_stage == 'Physical Inspection'
    assert rows.iloc[1].work_stage == 'Sanction'
    assert pd.isna(rows.iloc[1].actual_amount)
    assert rows.iloc[0].activity_norm == 'ROADS'
    assert 'attachment_missing' in json.loads(rows.iloc[0].validation_issues)


def test_invalid_values_are_preserved_and_flagged(tmp_path):
    raw = corpus(tmp_path, end='02-Apr-2025', amount='-5')
    ingest(raw, tmp_path / 'canonical')
    rows = pd.read_csv(tmp_path / 'canonical/works.csv')
    assert rows.iloc[0].actual_amount == -5
    issues = json.loads(rows.iloc[0].validation_issues)
    assert 'actual_amount_negative' in issues
    assert 'completion_before_sanction' in issues


def test_duplicate_source_ids_fail_without_replacing_snapshot(tmp_path):
    raw = corpus(tmp_path)
    output = tmp_path / 'canonical'
    ingest(raw, output)
    before = (output / 'works.csv').read_bytes()
    source = raw / 'works_sanctioned.csv'
    rows = pd.read_csv(source)
    pd.concat([rows, rows.iloc[:1]]).to_csv(source, index=False)
    with pytest.raises(ValueError, match='Duplicate'):
        ingest(raw, output)
    assert (output / 'works.csv').read_bytes() == before


def test_rejects_synthetic_source_and_raw_output_directory(tmp_path):
    raw = corpus(tmp_path)
    with pytest.raises(ValueError, match='outside the raw corpus'):
        ingest(raw, raw / 'canonical')
    source = raw / 'works_with_images.csv'
    rows = pd.read_csv(source)
    rows['is_synthetic'] = True
    rows.to_csv(source, index=False)
    with pytest.raises(ValueError, match='Synthetic'):
        ingest(raw, tmp_path / 'canonical')
