import json

import pandas as pd
import pytest

from pipelines.ingest import ingest
from pipeline.data_quality import alert_id, run_quality_checks


def corpus(tmp_path, *, extra_completed=None, extra_sanctioned=None):
    raw = tmp_path / 'raw'
    raw.mkdir()
    common = {'WORK_RECOMMENDATION_DTL_ID': '1', 'LETTER_NO': 'LN/MP319/2025-2026/32',
              'STATE_NAME': 'State', 'WORK_CATEGORY': 'Normal/Others', 'ACTIVITY_NAME': 'WS/MP319/2025-2026/1-Roads'}
    completed_rows = [{**common, 'WORK_ID': '20', 'ACTUAL_AMOUNT': '90', 'ACTUAL_END_DATE': '01-May-2025',
                        'image_count': 1, 'local_image_filenames': ''}]
    if extra_completed:
        completed_rows += extra_completed
    sanctioned_rows = [{**common, 'SANCTION_DATE': '10-Apr-2025', 'RECOMMENDATION_DATE': '01-Apr-2025',
                         'SANCTION_AMOUNT': '100', 'WORK_STAGE': 'Physical Inspection'}]
    if extra_sanctioned:
        sanctioned_rows += extra_sanctioned
    pd.DataFrame(completed_rows).to_csv(raw / 'works_with_images.csv', index=False)
    pd.DataFrame(sanctioned_rows).to_csv(raw / 'works_sanctioned.csv', index=False)
    return raw


def test_zero_fraud_score_contribution(tmp_path):
    """A quality alert dict has no field that could feed a risk score - it's a
    structurally separate artifact from signals_json/risk_score (backend
    keeps them in different endpoints entirely)."""
    raw = corpus(tmp_path)
    ingest(raw, tmp_path / 'canonical')
    alerts = json.loads((tmp_path / 'canonical/quality_alerts.json').read_text(encoding='utf-8'))
    for a in alerts:
        assert set(a) == {'id', 'work_id', 'quality_code', 'severity', 'field', 'raw_value',
                           'explanation', 'affected_analyses', 'recommended_action', 'status', 'detector_version',
                           'group_key', 'mp_name', 'state_name', 'constituency'}
        assert 'risk_score' not in a and 'score' not in a and 'flag' not in a


def test_lineage_reproducibility(tmp_path):
    raw = corpus(tmp_path)
    output = tmp_path / 'canonical'
    ingest(raw, output)
    first = json.loads((output / 'lineage.json').read_text(encoding='utf-8'))
    ingest(raw, output)
    second = json.loads((output / 'lineage.json').read_text(encoding='utf-8'))
    # Same raw input -> same lineage entries, modulo the run timestamp.
    def strip_timestamp(lineage):
        return {k: [{kk: vv for kk, vv in entry.items() if kk != 'timestamp'} for entry in v]
                for k, v in lineage.items()}
    assert strip_timestamp(first) == strip_timestamp(second)
    entries = first['20']
    amount_entry = next(e for e in entries if e['raw_field'] == 'ACTUAL_AMOUNT')
    assert amount_entry['raw_value'] == '90'
    assert amount_entry['normalized_value'] == '90.0'
    assert amount_entry['version'] == 'amount-normalize-v1'


def test_duplicate_work_id_detected(tmp_path):
    raw = corpus(tmp_path, extra_completed=[{'WORK_RECOMMENDATION_DTL_ID': '2', 'WORK_ID': '20',
                                              'LETTER_NO': 'LN/MP319/2025-2026/33', 'STATE_NAME': 'State',
                                              'WORK_CATEGORY': 'Normal/Others', 'ACTIVITY_NAME': 'WS/MP319/2025-2026/1-Roads',
                                              'ACTUAL_AMOUNT': '90', 'ACTUAL_END_DATE': '02-May-2025', 'image_count': 1}])
    ingest(raw, tmp_path / 'canonical')
    alerts = json.loads((tmp_path / 'canonical/quality_alerts.json').read_text(encoding='utf-8'))
    codes = {a['quality_code'] for a in alerts if a['work_id'] == '20'}
    assert 'work_id_duplicate' in codes


def test_invalid_date_sequence_flagged(tmp_path):
    raw = corpus(tmp_path)
    # Completion before sanction: reuse the ingest fixture's helper directly.
    df = pd.read_csv(raw / 'works_with_images.csv')
    df.loc[0, 'ACTUAL_END_DATE'] = '02-Apr-2025'  # before the 10-Apr-2025 sanction date
    df.to_csv(raw / 'works_with_images.csv', index=False)
    ingest(raw, tmp_path / 'canonical')
    alerts = json.loads((tmp_path / 'canonical/quality_alerts.json').read_text(encoding='utf-8'))
    codes = {a['quality_code'] for a in alerts if a['work_id'] == '20'}
    assert 'date_sequence_invalid' in codes


def test_missing_location_flagged(tmp_path):
    raw = corpus(tmp_path)
    df = pd.read_csv(raw / 'works_with_images.csv')
    df.loc[0, 'STATE_NAME'] = ''
    df.to_csv(raw / 'works_with_images.csv', index=False)
    ingest(raw, tmp_path / 'canonical')
    alerts = json.loads((tmp_path / 'canonical/quality_alerts.json').read_text(encoding='utf-8'))
    codes = {a['quality_code'] for a in alerts if a['work_id'] == '20'}
    assert 'location_missing_or_invalid' in codes


def test_amount_unit_ambiguous_excluded_from_cost_detectors(tmp_path):
    raw = corpus(tmp_path)
    df = pd.read_csv(raw / 'works_with_images.csv')
    df['ACTUAL_AMOUNT'] = df['ACTUAL_AMOUNT'].astype('object')
    df.loc[0, 'ACTUAL_AMOUNT'] = '5 lakh crore'  # conflicting units, unresolved
    df.to_csv(raw / 'works_with_images.csv', index=False)
    ingest(raw, tmp_path / 'canonical')
    rows = pd.read_csv(tmp_path / 'canonical/works.csv')
    assert pd.isna(rows.iloc[0].actual_amount)  # excluded, not guessed
    assert rows.iloc[0].actual_amount_status == 'ambiguous_unit'
    alerts = json.loads((tmp_path / 'canonical/quality_alerts.json').read_text(encoding='utf-8'))
    codes = {a['quality_code'] for a in alerts if a['work_id'] == '20'}
    assert 'amount_unit_ambiguous' in codes


def test_alert_id_stable_across_reruns(tmp_path):
    raw = corpus(tmp_path)
    output = tmp_path / 'canonical'
    ingest(raw, output)
    first = json.loads((output / 'quality_alerts.json').read_text(encoding='utf-8'))
    ingest(raw, output)
    second = json.loads((output / 'quality_alerts.json').read_text(encoding='utf-8'))
    assert {a['id'] for a in first} == {a['id'] for a in second}
    assert alert_id('20', 'amount_zero', 'actual_amount') == alert_id('20', 'amount_zero', 'actual_amount')


def test_unknown_category_flagged_when_blank():
    df = pd.DataFrame([{'work_id': '1', 'record_id': '1', 'work_description': 'X', 'mp_name': 'MP',
                         'state_name': 'S', 'constituency': 'C', 'work_category': '', 'has_completed_record': True,
                         'has_sanctioned_record': False, 'actual_amount_status': 'ok', 'actual_amount_raw': '90',
                         'actual_amount_raw_unit': None, 'actual_amount': 90.0, 'sanction_amount_status': 'missing',
                         'sanction_amount_raw': None, 'sanction_amount_raw_unit': None, 'sanction_amount': None,
                         'actual_end_date': '2025-05-01', 'actual_end_date_raw': '01-May-2025', 'sanction_date': None,
                         'sanction_date_raw': None, 'recommendation_date': None, 'recommendation_date_raw': None,
                         'validation_issues': '[]', 'attachment_filenames': None, 'sanctioned_work_stage': None}])
    alerts = run_quality_checks(df)
    codes = {a['quality_code'] for a in alerts}
    assert 'category_unknown' in codes
    assert all(a['status'] == 'open' for a in alerts)


def test_alert_id_stable_when_raw_value_unchanged():
    assert alert_id('20', 'amount_zero', 'actual_amount', '0') == alert_id('20', 'amount_zero', 'actual_amount', '0')


def test_alert_id_changes_when_raw_value_changes():
    # A resolution keyed to the old id is never invalidated in place - it
    # simply stops matching any currently-generated (open) alert, which is
    # how "preserve previous resolution history, generate the current state"
    # is implemented: the old id's row in the resolutions table is untouched.
    before = alert_id('20', 'amount_zero', 'actual_amount', '0')
    after = alert_id('20', 'amount_zero', 'actual_amount', '5')
    assert before != after


def test_resolution_survives_identical_rerun(tmp_path):
    raw = corpus(tmp_path)
    output = tmp_path / 'canonical'
    ingest(raw, output)
    first = {a['id'] for a in json.loads((output / 'quality_alerts.json').read_text(encoding='utf-8'))}
    ingest(raw, output)
    second = {a['id'] for a in json.loads((output / 'quality_alerts.json').read_text(encoding='utf-8'))}
    # A rerun with byte-identical inputs must regenerate byte-identical ids -
    # a resolution recorded against `first` still applies to `second`.
    assert first == second


def test_raw_value_change_creates_new_alert_and_keeps_history(tmp_path):
    raw = corpus(tmp_path)
    df = pd.read_csv(raw / 'works_with_images.csv')
    df['ACTUAL_AMOUNT'] = df['ACTUAL_AMOUNT'].astype('object')
    df.loc[0, 'ACTUAL_AMOUNT'] = '0'
    df.to_csv(raw / 'works_with_images.csv', index=False)
    output = tmp_path / 'canonical'
    ingest(raw, output)
    before = json.loads((output / 'quality_alerts.json').read_text(encoding='utf-8'))
    before_zero = next(a for a in before if a['quality_code'] == 'amount_zero' and a['work_id'] == '20')
    # Simulate a reviewer resolution existing against `before_zero['id']`
    # (see tests/test_quality_api.py for that persistence), then change the
    # underlying raw amount and confirm a DIFFERENT id is generated for the
    # new value - the old id's resolution history is never touched because
    # nothing deletes rows from the resolutions store on rerun.
    df.loc[0, 'ACTUAL_AMOUNT'] = '500'
    df.to_csv(raw / 'works_with_images.csv', index=False)
    ingest(raw, output)
    after = json.loads((output / 'quality_alerts.json').read_text(encoding='utf-8'))
    after_ids = {a['id'] for a in after}
    assert before_zero['id'] not in after_ids
    assert not any(a['quality_code'] == 'amount_zero' and a['work_id'] == '20' for a in after)
