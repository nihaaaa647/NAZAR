"""Build a deterministic canonical CSV snapshot from both raw CSV families.

Run: python -m pipelines.ingest. No database or network service is needed.
Raw files and historical parquet remain unchanged. One writer at a time.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

import pandas as pd

from pipeline.amount_normalize import TRANSFORMATION_VERSION as AMOUNT_TRANSFORM_VERSION, normalize_amount_series
from pipeline.consolidate import engineer_features
from pipeline.data_quality import run_quality_checks
from pipeline.lineage import build_lineage

KEY = 'WORK_RECOMMENDATION_DTL_ID'
ACTIVITY_PREFIX = r'^WS/MP\d+/\d{4}-\d{4}/\d+-'


def load_family(root: Path, filename: str) -> pd.DataFrame:
    frames = []
    for path in sorted(root.rglob(filename)):
        frame = pd.read_csv(path, dtype='string')
        if KEY not in frame or frame[KEY].isna().any():
            raise ValueError(f'Missing recommendation ID in {path.relative_to(root)}')
        if 'is_synthetic' in frame:
            if not frame.is_synthetic.str.lower().eq('false').fillna(False).all():
                raise ValueError('Synthetic or unknown-origin rows cannot enter the real snapshot')
        frame['_source_csv'] = path.relative_to(root).as_posix()
        frames.append(frame)
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=[KEY, '_source_csv'])
    if result[KEY].duplicated().any():
        raise ValueError(f'Duplicate recommendation IDs in {filename}; resolve source conflicts before ingestion')
    return result.set_index(KEY)


def build_works(root: Path) -> tuple[pd.DataFrame, dict]:
    completed = load_family(root, 'works_with_images.csv')
    sanctioned = load_family(root, 'works_sanctioned.csv')
    if completed.empty and sanctioned.empty:
        raise ValueError('No completed or sanctioned records found')
    raw = completed.combine_first(sanctioned).sort_index().reset_index()
    has_completed = raw[KEY].isin(completed.index)
    has_sanctioned = raw[KEY].isin(sanctioned.index)
    # Reuse the existing feature foundation; add missing schema columns for
    # sanctioned-only corpora, where no completed-work fields exist at all.
    for name in ['ACTUAL_END_DATE', 'LETTER_NO', 'image_count', 'STATE_NAME', 'IDA_NAME',
                 'MP_NAME', 'WORK_CATEGORY', 'ACTIVITY_NAME', 'WORK_DESCRIPTION', 'WORK_ID',
                 'CONSTITUENCY_ID', 'CONSTITUENCY', 'ACTUAL_AMOUNT', 'SANCTION_AMOUNT',
                 'SANCTION_DATE', 'RECOMMENDATION_DATE', 'WORK_STAGE', 'local_image_filenames', 'FILE_STATUS']:
        if name not in raw:
            raw[name] = pd.Series(pd.NA, index=raw.index, dtype='string')
    raw['image_count'] = pd.to_numeric(raw.image_count, errors='coerce')
    enriched = engineer_features(raw)
    out = pd.DataFrame({'record_id': raw[KEY], 'is_synthetic': False,
                        'has_completed_record': has_completed, 'has_sanctioned_record': has_sanctioned})
    names = {'WORK_ID': 'work_id', 'WORK_DESCRIPTION': 'work_description', 'LETTER_NO': 'letter_no',
             'CONSTITUENCY_ID': 'constituency_id', 'CONSTITUENCY': 'constituency',
             'MP_NAME': 'mp_name', 'STATE_NAME': 'state_name', 'IDA_NAME': 'ida_name',
             'WORK_CATEGORY': 'work_category', 'ACTIVITY_NAME': 'activity_name',
             'WORK_STAGE': 'sanctioned_work_stage', 'local_image_filenames': 'attachment_filenames',
             'FILE_STATUS': 'portal_attachment_present'}
    for source, target in names.items():
        out[target] = raw[source]
    out['completed_source_csv'] = raw[KEY].map(completed['_source_csv'])
    out['sanctioned_source_csv'] = raw[KEY].map(sanctioned['_source_csv'])
    for name in ['state_norm', 'ida_norm', 'mp_norm', 'mp_code', 'fy_start_year', 'fy_end_year', 'letter_seq', 'days_to_fy_end']:
        out[name] = enriched[name]
    out['activity_norm'] = raw.ACTIVITY_NAME.str.replace(ACTIVITY_PREFIX, '', regex=True).str.strip().str.upper()
    out['work_stage'] = raw.WORK_STAGE.mask(has_completed, 'Work Completed')
    out['stage_source'] = has_completed.map({True: 'completed_table_membership', False: 'sanctioned_table'})
    for name in ['ACTUAL_AMOUNT', 'SANCTION_AMOUNT']:
        field = name.lower()
        out[field + '_raw'] = raw[name]
        normalized = normalize_amount_series(raw[name])
        out[field] = [float(n.normalized_inr) if n.normalized_inr is not None else float('nan') for n in normalized]
        out[field + '_status'] = [n.normalization_status for n in normalized]
        out[field + '_unit_source'] = [n.unit_source for n in normalized]
        out[field + '_raw_unit'] = [n.raw_unit for n in normalized]
    for name in ['ACTUAL_END_DATE', 'SANCTION_DATE', 'RECOMMENDATION_DATE']:
        out[name.lower() + '_raw'] = raw[name]
        out[name.lower()] = pd.to_datetime(raw[name], format='%d-%b-%Y', errors='coerce')
    # Do not hide a malformed or missing date on a joined sanction record with a proxy.
    out['sanction_date_proxy'] = enriched.sanction_date_proxy.where(~has_sanctioned)
    basis = out.sanction_date.where(has_sanctioned, out.sanction_date_proxy)
    out['duration_days'] = (out.actual_end_date - basis).dt.days
    out['duration_basis'] = 'unavailable'
    out.loc[has_completed & basis.notna() & out.actual_end_date.notna(), 'duration_basis'] = 'real_sanction_date'
    out.loc[has_completed & ~has_sanctioned & basis.notna() & out.actual_end_date.notna(), 'duration_basis'] = 'fiscal_year_proxy'
    out['downloaded_attachment_count'] = raw.image_count
    issues = [[] for _ in range(len(out))]

    def flag(mask: pd.Series, code: str) -> None:
        for index in out.index[mask.fillna(False)]:
            issues[index].append(code)

    flag(enriched.mp_code.isna(), 'letter_missing_or_unparseable')
    flag(enriched.fy_end_year.ne(enriched.fy_start_year + 1) & enriched.mp_code.notna(), 'invalid_fiscal_year')
    for name, expected in [('actual_amount', has_completed), ('sanction_amount', has_sanctioned)]:
        flag(expected & out[name].isna(), name + '_missing_or_invalid')
        flag(out[name].lt(0), name + '_negative')
        flag(out[name].eq(0), name + '_zero')
    for name, expected in [('actual_end_date', has_completed), ('sanction_date', has_sanctioned), ('recommendation_date', has_sanctioned)]:
        flag(expected & out[name].isna(), name + '_missing_or_invalid')
    flag(out.actual_end_date.lt(out.sanction_date), 'completion_before_sanction')
    flag(out.sanction_date.lt(out.recommendation_date), 'sanction_before_recommendation')
    flag(has_completed & has_sanctioned & out.sanctioned_work_stage.ne('Work Completed'), 'source_stage_disagreement')
    for index, row in out.iterrows():
        if pd.isna(row.attachment_filenames) or pd.isna(row.completed_source_csv):
            continue
        for name in row.attachment_filenames.split(';'):
            if not name.strip():
                continue
            path = ((root / row.completed_source_csv).parent / name.strip()).resolve()
            if not path.is_relative_to(root.resolve()):
                issues[index].append('attachment_path_outside_corpus')
            elif not path.is_file():
                issues[index].append('attachment_missing')
    out['validation_issues'] = [json.dumps(sorted(set(codes))) for codes in issues]
    out['validation_status'] = ['requires_verification' if codes else 'valid' for codes in issues]
    run_timestamp = datetime.now(timezone.utc).isoformat()
    quality_alerts = run_quality_checks(out)
    lineage = build_lineage(out, run_timestamp, AMOUNT_TRANSFORM_VERSION)
    # work_id/record key -> jurisdiction, for every canonical row regardless
    # of whether it ever generates a quality alert or reaches the fraud-scored
    # corpus (sanctioned-only rows never do) - the backend's RBAC needs this
    # to scope /quality/lineage/{work_id} by MP/state/constituency even when
    # no alert exists to carry that context.
    def _key(row):
        wid = row['work_id']
        return str(wid) if pd.notna(wid) and str(wid).strip() else f'record:{row["record_id"]}'
    work_directory = {_key(row): {'mp_name': None if pd.isna(row.mp_name) else str(row.mp_name),
                                   'state_name': None if pd.isna(row.state_name) else str(row.state_name),
                                   'constituency': None if pd.isna(row.constituency) else str(row.constituency)}
                       for _, row in out.iterrows()}
    summary = {'canonical_rows': len(out), 'completed_rows': len(completed), 'sanctioned_rows': len(sanctioned),
               'matched_completed_rows': int((has_completed & has_sanctioned).sum()),
               'sanctioned_only_rows': int((~has_completed & has_sanctioned).sum()),
               'validation_counts': dict(Counter(code for codes in issues for code in set(codes))),
               'states': int(out.state_norm.nunique()), 'activities': int(out.activity_norm.nunique()),
               'quality_alerts': quality_alerts, 'lineage': lineage, 'work_directory': work_directory,
               'quality_alert_counts': dict(Counter(a['quality_code'] for a in quality_alerts)),
               'run_timestamp': run_timestamp}
    return out, summary


def write_snapshot(frame: pd.DataFrame, target: Path) -> None:
    """Replace one CSV atomically; byte-identical reruns leave it untouched."""
    payload = frame.to_csv(index=False, lineterminator='\n', date_format='%Y-%m-%d').encode('utf-8')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() == payload:
        return
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.tmp', delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(payload)
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def ingest(root: Path, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    if output.is_relative_to(root):
        raise ValueError('Canonical output must be outside the raw corpus')
    start = time.perf_counter()
    works, summary = build_works(root)
    target = output / 'works.csv'
    write_snapshot(works, target)
    quality_alerts = summary.pop('quality_alerts')
    lineage = summary.pop('lineage')
    work_directory = summary.pop('work_directory')
    (output / 'quality_alerts.json').write_text(json.dumps(quality_alerts, indent=2, ensure_ascii=False), encoding='utf-8')
    (output / 'lineage.json').write_text(json.dumps(lineage, indent=2, ensure_ascii=False), encoding='utf-8')
    (output / 'work_directory.json').write_text(json.dumps(work_directory, indent=2, ensure_ascii=False), encoding='utf-8')
    summary['works_csv_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    summary['elapsed_seconds'] = round(time.perf_counter() - start, 3)
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('NAZAR_DATA_ROOT', 'mplads_india')))
    parser.add_argument('--output', type=Path, default=Path(os.environ.get('NAZAR_CANONICAL_ROOT', 'data/canonical')))
    arguments = parser.parse_args()
    ingest(arguments.root, arguments.output)
