"""Transformation lineage: source -> raw field/value -> transformation ->
normalized value -> version -> timestamp, for every field the ingestion
pipeline normalizes (amounts, dates). One run's lineage is fully
reproducible from its inputs — same raw row in, same lineage entries out,
see tests/test_data_quality.py."""
from __future__ import annotations

DATE_TRANSFORM_VERSION = 'date-parse-v1'

_AMOUNT_FIELDS = (('actual_amount', 'completed_source_csv', 'ACTUAL_AMOUNT'),
                   ('sanction_amount', 'sanctioned_source_csv', 'SANCTION_AMOUNT'))
_DATE_FIELDS = (('actual_end_date', 'completed_source_csv', 'ACTUAL_END_DATE'),
                ('sanction_date', 'sanctioned_source_csv', 'SANCTION_DATE'),
                ('recommendation_date', 'sanctioned_source_csv', 'RECOMMENDATION_DATE'))


def _is_na(value) -> bool:
    try:
        import pandas as pd
        return bool(pd.isna(value))
    except (ImportError, TypeError, ValueError):
        return value is None


def _entry(source, raw_field, raw_value, transformation, normalized_value, version, timestamp):
    return {'source': None if _is_na(source) else str(source), 'raw_field': raw_field,
            'raw_value': None if _is_na(raw_value) else str(raw_value),
            'transformation': transformation, 'normalized_value': None if _is_na(normalized_value) else str(normalized_value),
            'version': version, 'timestamp': timestamp}


def build_lineage(df, run_timestamp: str, amount_transform_version: str) -> dict:
    """{work_id_or_'record:<id>': [entry, ...]}, one call per pipeline run."""
    lineage: dict[str, list[dict]] = {}
    for _, row in df.iterrows():
        work_id = row.get('work_id')
        key = str(work_id) if not _is_na(work_id) and str(work_id).strip() not in ('', 'nan', 'None') else f'record:{row.get("record_id")}'
        entries = []
        for field, source_col, raw_name in _AMOUNT_FIELDS:
            source = row.get(source_col)
            entries.append(_entry(source, raw_name, row.get(f'{field}_raw'),
                                   f'amount_normalize:{row.get(f"{field}_status")}', row.get(field),
                                   amount_transform_version, run_timestamp))
        for field, source_col, raw_name in _DATE_FIELDS:
            source = row.get(source_col)
            entries.append(_entry(source, raw_name, row.get(f'{field}_raw'), 'date_parse:%d-%b-%Y',
                                   row.get(field), DATE_TRANSFORM_VERSION, run_timestamp))
        lineage[key] = entries
    return lineage
