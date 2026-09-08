"""Read-only corpus audit. Outputs measurements, never detection scores.

PDF probing is deliberately limited to byte-preserved embedded JPEG streams;
unsupported PDFs are counted, not rasterized or declared empty of evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import shutil
import sys
import time

import numpy as np
import pandas as pd
from PIL import Image, UnidentifiedImageError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.consolidate import engineer_features, parse_letter_no

ACTIVITY_PREFIX = r"^WS/MP\d+/\d{4}-\d{4}/\d+-"
MEDIA_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.docx', '.tif', '.tiff', '.webp'}


def counts(values: pd.Series) -> dict:
    return {str(k): int(v) for k, v in values.value_counts(dropna=False).items()}


def distribution(values: pd.Series) -> dict:
    numeric = pd.to_numeric(values, errors='coerce').dropna()
    if numeric.empty:
        return {'count': 0}
    return {str(k): float(v) if pd.notna(v) else None for k, v in numeric.describe(
        percentiles=[.01, .05, .25, .5, .75, .95, .99]).items()}


def load_family(root: Path, filename: str) -> tuple[pd.DataFrame, list[Path]]:
    files = sorted(root.rglob(filename))
    frames = []
    for path in files:
        frame = pd.read_csv(path, dtype='string')
        frame['_source_csv'] = path.relative_to(root).as_posix()
        frames.append(frame)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), files


def profile_table(frame: pd.DataFrame) -> dict:
    result = {'rows': len(frame), 'columns': {}, 'dates': {}}
    for name, column in frame.items():
        result['columns'][name] = {
            'null_count': int(column.isna().sum()),
            'null_rate': float(column.isna().mean()) if len(column) else None,
            'cardinality': int(column.nunique()), 'top_values': dict(list(counts(column).items())[:10]),
        }
        if 'DATE' in name.upper() and not name.startswith('_'):
            date_format = '%b %d, %Y %I:%M:%S %p' if name.startswith('TENURE_') else '%d-%b-%Y'
            parsed = pd.to_datetime(column, format=date_format, errors='coerce')
            failures = column.notna() & parsed.isna()
            result['dates'][name] = {
                'format': date_format, 'missing': int(column.isna().sum()),
                'parse_failures': int(failures.sum()),
                'parse_failure_rate_non_null': float(failures.sum() / column.notna().sum()) if column.notna().any() else None,
                'min': str(parsed.min()), 'max': str(parsed.max()),
                'failure_examples': column[failures].head(5).tolist(),
            }
    if 'LETTER_NO' in frame:
        parts = parse_letter_no(frame['LETTER_NO'])
        result['letter_no'] = {
            'missing_or_unparseable': int(parts.mp_code.isna().sum()),
            'non_null_unparseable': int((frame.LETTER_NO.notna() & parts.mp_code.isna()).sum()),
            'failure_rate': float(parts.mp_code.isna().mean()),
            'invalid_fy_sequence': int((parts.fy_end_year != parts.fy_start_year + 1)[parts.mp_code.notna()].sum()),
            'fy_start_years': counts(parts.fy_start_year),
        }
    return result


def jpeg_streams(data: bytes) -> list[bytes]:
    """Probe JPEG markers; Pillow subsequently verifies and decodes thumbnails.

    This is not a general PDF parser. Embedded streams using other encodings
    remain unmeasured and are reported separately.
    """
    streams, offset = [], 0
    while (start := data.find(b'\xff\xd8\xff', offset)) >= 0:
        end = data.find(b'\xff\xd9', start + 3)
        if end < 0:
            break
        streams.append(data[start:end + 2])
        offset = end + 2
    return streams


def image_measurements(payload: bytes) -> dict:
    with Image.open(io.BytesIO(payload)) as check:
        check.verify()
    with Image.open(io.BytesIO(payload)) as original:
        width, height = original.size
        exif_present = bool(original.getexif())
        # Color metrics are thumbnail statistics. JPEG draft decoding avoids
        # allocating a full-resolution scanned page solely to shrink it again.
        # Dimensions and the digest always refer to the original payload.
        original.draft('RGB', (256, 256))
        original.load()
        image = original.convert('RGB')
        image.thumbnail((256, 256))
        rgb = np.asarray(image, dtype=float)
        rg = rgb[:, :, 0] - rgb[:, :, 1]
        yb = (rgb[:, :, 0] + rgb[:, :, 1]) / 2 - rgb[:, :, 2]
        colorfulness = np.hypot(rg.std(), yb.std()) + .3 * np.hypot(rg.mean(), yb.mean())
        return {'width': width, 'height': height, 'min_dimension': min(width, height),
                'entropy': image.convert('L').entropy(), 'colorfulness': float(colorfulness),
                'exif_present': exif_present, 'sha256': hashlib.sha256(payload).hexdigest()}


def attachment_inventory(root: Path, completed: pd.DataFrame, output: Path) -> dict:
    references = defaultdict(set)
    invalid_references = []
    for row in completed.to_dict('records'):
        names = row.get('local_image_filenames')
        if pd.isna(names):
            continue
        for name in str(names).split(';'):
            if not name.strip():
                continue
            path = (root / row['_source_csv']).parent / name.strip()
            path = path.resolve()
            if not path.is_relative_to(root):
                invalid_references.append({'source': row['_source_csv'], 'filename': name})
                continue
            references[path].add(str(row['WORK_ID']))
    files = sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS)
    print(f'Probing {len(files)} attachment files ({len(references)} referenced paths)', flush=True)
    records, statuses = [], Counter()
    measured_by_digest = {}
    for index, path in enumerate(files):
        linked = path in references
        record = {'path': path.relative_to(root).as_posix(), 'extension': path.suffix.lower(),
                  'referenced': linked, 'work_ids': ';'.join(sorted(references.get(path, set())))}
        if not linked:
            # Directory walks must not silently include legacy injected evidence.
            records.append({**record, 'status': 'unreferenced_not_analyzed'})
            continue
        try:
            data = path.read_bytes()
            is_pdf = data.startswith(b'%PDF-')
            payloads = jpeg_streams(data) if is_pdf else [data]
            if not payloads:
                records.append({**record, 'status': 'no_embedded_jpeg_probe'})
            for n, payload in enumerate(payloads):
                try:
                    digest = hashlib.sha256(payload).hexdigest()
                    if digest not in measured_by_digest:
                        measured_by_digest[digest] = image_measurements(payload)
                    metrics = measured_by_digest[digest]
                    records.append({**record, **metrics, 'image_index': n, 'pdf_wrapped': is_pdf, 'status': 'decoded'})
                except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
                    records.append({**record, 'image_index': n, 'status': 'decode_failed', 'error': str(error)})
        except OSError as error:
            records.append({**record, 'status': 'read_failed', 'error': str(error)})
        if (index + 1) % 500 == 0:
            print(f'Attachment inventory: {index + 1}/{len(files)} files', flush=True)
    table = pd.DataFrame(records)
    table.to_csv(output / 'attachments.csv', index=False)
    decoded = table[table.status == 'decoded'] if len(table) else pd.DataFrame()
    duplicate_groups = []
    if len(decoded):
        for digest, group in decoded.groupby('sha256'):
            works = {wid for value in group.work_ids for wid in value.split(';')}
            if len(works) > 1:
                duplicate_groups.append({'sha256': digest, 'work_ids': sorted(works),
                                         'paths': sorted(set(group.path)),
                                         'min_dimension': int(group.min_dimension.min())})
    statuses.update(table.status if len(table) else [])
    return {
        'files_on_disk': len(files), 'extensions_on_disk': dict(Counter(p.suffix.lower() for p in files)),
        'referenced_paths': len(references), 'unreferenced_paths': [p.relative_to(root).as_posix() for p in files if p not in references],
        'missing_referenced_paths': [p.relative_to(root).as_posix() for p in references if not p.is_file()],
        'invalid_references': invalid_references, 'statuses': dict(statuses),
        'decoded_images': len(decoded),
        'pdf_wrapped_images': int(decoded.pdf_wrapped.sum()) if len(decoded) else 0,
        'min_dimension_below_200': int((decoded.min_dimension < 200).sum()) if len(decoded) else 0,
        'exif_present': int(decoded.exif_present.sum()) if len(decoded) else 0,
        'dimensions': counts(decoded.width.astype(int).astype(str) + 'x' + decoded.height.astype(int).astype(str)) if len(decoded) else {},
        'measurements': {c: distribution(decoded[c]) for c in ['width', 'height', 'min_dimension', 'entropy', 'colorfulness']} if len(decoded) else {},
        'cross_work_sha256_groups': duplicate_groups,
        'method': 'CSV-linked evidence only; PDF JPEG marker probe, Pillow verify and reduced JPEG decode; colorfulness on <=256px RGB thumbnail. Original dimensions and SHA-256. No semantic triage or pHash yet.',
    }


def profile(root: Path, output: Path) -> dict:
    start = time.perf_counter()
    root = root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    print('Loading completed and sanctioned CSVs', flush=True)
    completed, cfiles = load_family(root, 'works_with_images.csv')
    sanctioned, sfiles = load_family(root, 'works_sanctioned.csv')
    print(f'Loaded {len(completed)} completed and {len(sanctioned)} sanctioned rows', flush=True)
    if completed.empty:
        raise ValueError('No completed work rows found; check --root / NAZAR_DATA_ROOT')
    result = {'generated_at': datetime.now(timezone.utc).isoformat(),
              'completed_files': len(cfiles), 'sanctioned_files': len(sfiles),
              'completed': profile_table(completed), 'sanctioned': profile_table(sanctioned)}
    result['states'] = counts(completed.STATE_NAME)
    result['duplicate_ids'] = {c: int(completed[c].dropna().duplicated().sum()) for c in ['WORK_ID', 'WORK_RECOMMENDATION_DTL_ID']}
    activity = completed.ACTIVITY_NAME.str.replace(ACTIVITY_PREFIX, '', regex=True).str.strip().str.upper()
    result['activity_norm'] = counts(activity)
    result['work_category'] = counts(completed.WORK_CATEGORY)
    amount = pd.to_numeric(completed.ACTUAL_AMOUNT, errors='coerce')
    result['amount'] = {'distribution': distribution(amount), 'non_null_parse_failures': int((completed.ACTUAL_AMOUNT.notna() & amount.isna()).sum()),
                        'negative': int((amount < 0).sum()), 'at_most_one': int((amount <= 1).sum()),
                        'multiples_100000_including_zero': int((amount % 100000 == 0).sum()),
                        '900000_to_1000000_exclusive': int(((amount >= 900000) & (amount < 1000000)).sum()),
                        'above_1000000': int((amount > 1000000).sum())}
    key = 'WORK_RECOMMENDATION_DTL_ID'
    if not sanctioned.empty:
        duplicates = sanctioned[key].dropna().duplicated()
        result['sanctioned_duplicate_ids'] = int(duplicates.sum())
        if duplicates.any():
            result['join'] = {'error': 'Duplicate sanctioned IDs; comparison withheld to avoid row multiplication.'}
        else:
            joined = completed[completed[key].notna()].merge(sanctioned[sanctioned[key].notna()], on=key, how='inner', suffixes=('', '_sanctioned'), validate='many_to_one')
            difference = pd.to_numeric(joined.ACTUAL_AMOUNT, errors='coerce') - pd.to_numeric(joined.SANCTION_AMOUNT, errors='coerce')
            result['join'] = {'matched': len(joined), 'unmatched': len(completed) - len(joined), 'rate': len(joined) / len(completed),
                              'matched_by_state': counts(joined.STATE_NAME), 'comparable_amounts': int(difference.notna().sum()),
                              'overruns': int((difference > 0).sum()), 'equal': int((difference == 0).sum()), 'underspend': int((difference < 0).sum()),
                              'actual_minus_sanction': distribution(difference)}
        result['work_stage'] = counts(sanctioned.WORK_STAGE)
        gap = pd.to_datetime(sanctioned.SANCTION_DATE, format='%d-%b-%Y', errors='coerce') - pd.to_datetime(sanctioned.RECOMMENDATION_DATE, format='%d-%b-%Y', errors='coerce')
        result['recommendation_to_sanction_days'] = distribution(gap.dt.days)
    else:
        result['join'] = {'matched': 0, 'unmatched': len(completed), 'rate': 0}
    progress = root / '_progress.json'
    result['scraper_progress'] = {k: len(v) if isinstance(v, list) else v for k, v in json.loads(progress.read_text()).items()} if progress.exists() else None
    stale = root / '_consolidated/master_works.parquet'
    if stale.exists():
        import pyarrow.parquet as pq
        result['existing_parquet_rows'] = pq.read_metadata(stale).num_rows
    # Run existing feature code in memory without overwriting historical parquet.
    source = completed.copy()
    for column in ['ACTUAL_AMOUNT', 'image_count']:
        source[column] = pd.to_numeric(source[column], errors='coerce')
    features = engineer_features(source)
    result['existing_features'] = {'rows': len(features), 'columns': len(features.columns),
                                   'zero_images': int((~features.has_images).sum())}
    result['attachments'] = attachment_inventory(root, completed, output)
    packages = ['pandas', 'numpy', 'Pillow', 'pyarrow', 'pytest', 'requests', 'scipy', 'scikit-learn', 'fastapi', 'SQLAlchemy', 'alembic', 'ImageHash', 'PyMuPDF', 'sentence-transformers', 'torch', 'pytesseract']
    versions = {}
    for name in packages:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    result['environment'] = {'python': sys.version, 'packages': versions,
                             'commands_on_path': {n: bool(shutil.which(n)) for n in ['tesseract', 'postgres', 'psql', 'docker']}}
    result['elapsed_seconds'] = round(time.perf_counter() - start, 2)
    (output / 'data_profile.json').write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    summary = {k: result[k] for k in ['completed_files', 'sanctioned_files', 'states', 'duplicate_ids', 'amount', 'join', 'existing_features', 'existing_parquet_rows', 'elapsed_seconds'] if k in result}
    summary['completed_rows'] = len(completed)
    summary['sanctioned_rows'] = len(sanctioned)
    summary['activity_count'] = len(result['activity_norm'])
    summary['attachments'] = {k: result['attachments'][k] for k in ['files_on_disk', 'extensions_on_disk', 'statuses', 'decoded_images', 'pdf_wrapped_images', 'min_dimension_below_200']}
    summary['cross_work_sha256_groups'] = len(result['attachments']['cross_work_sha256_groups'])
    summary_text = json.dumps(summary, indent=2, ensure_ascii=False)
    (output / 'profile_summary.txt').write_text(summary_text + '\n', encoding='utf-8')
    print(summary_text)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('NAZAR_DATA_ROOT', 'mplads_india')))
    parser.add_argument('--output', type=Path, default=Path('reports'))
    args = parser.parse_args()
    profile(args.root, args.output)
