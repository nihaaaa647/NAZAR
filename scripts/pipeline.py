"""Read-only corpus scoring. All thresholds are review heuristics, not legal rules."""
from __future__ import annotations
import argparse, hashlib, io, itertools, json, os, re, sys
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import cv2
import fitz  # PyMuPDF - used only to classify/extract from PDF attachments, never for CSV/tabular data
import numpy as np
import pandas as pd
from PIL import Image, UnidentifiedImageError
from scipy.fftpack import dct
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.amount_normalize import normalize_amount_series
from pipeline.cases import build_case_candidate
from pipeline.consolidate import parse_letter_no
from pipeline.detection_contract import make_signal
from pipeline.image_evidence import (
    MATCH_DETECTOR_VERSION as IMAGE_MATCH_DETECTOR_VERSION, PREPROCESSING_VERSION as IMAGE_PREPROCESSING_VERSION,
    build_image_inventory, classify_image_pair, image_id as image_id_of, match_id as image_match_id,
)
from pipelines.ingest import build_works
DATA = ROOT / 'data'
NOTICE = 'Computational signal — needs human review.'
# Scanner-app footers ("Scanned with OKEN Scanner", CamScanner logo) are short wide
# strips well below this floor. They repeat byte-for-byte across unrelated works, so
# without this gate they dominate both photo tiers as spurious "reused image" evidence.
# Re-exported from pipeline.image_evidence (single source of truth, no drift)
# rather than redefined here.
from pipeline.image_evidence import MIN_IMAGE_DIM, ORB_MIN_GOOD_MATCHES, ORB_MIN_INLIER_RATIO, ORB_RATIO_TEST
# Sourced MPLADS Guidelines 2023 thresholds (mplads.gov.in "Pocket Book on MPLADS
# Guidelines"; PIB release on the Revised MPLADS Guidelines 2023) — not heuristics.
# See astra/FINDINGS_TO_VERIFY.md F7 and docs/DECISIONS.md for what was checked
# and why the trust/society ceiling and outside-constituency cap are NOT included
# here: this corpus can only partially link IDA entity type and MP home district,
# and a wrong "sourced" flag is worse than no flag.
MPLADS_ENTITLEMENT_PER_FY = 5_00_00_000  # Rs 5 crore per MP per fiscal year, released as two Rs 2.5 crore installments.
# Phase 1/2 cited a 75-day sanctioning window (see docs/DECISIONS.md, 2026-09-19).
# Phase 3's brief instructs a 45-day review indicator instead. Both numbers come
# from MPLADS Guidelines material but this session did not re-verify a primary
# source for 45 specifically - it is used here because the Phase 3 instructions
# say to, not because it was independently re-confirmed. Flagged in
# docs/DECISIONS.md as a limitation a human should check before treating either
# number as authoritative; SANCTION_DEADLINE_DAYS is kept only as a legacy
# constant for anyone auditing Phase 1/2's original citation.
SANCTION_DEADLINE_DAYS = 75
LATE_SANCTION_REVIEW_DAYS = 45            # Phase 3's instructed review indicator, used by late_sanction_signal below.
MIN_PEER_SIZE = 10                        # below this, a peer comparison is "insufficient data", not a number.
DETECTOR_VERSION = 'pipeline-scoring-v2'  # Phase 3: standardized signal contract, see pipeline/detection_contract.py.
THRESHOLD_VERSION = 'thresholds-v1'       # z>2.5, ORB thresholds, etc. - see individual rule docstrings for citations.
# Tier 3 — ORB keypoint confirmation for Tier-2 (photo_similar) candidates.
# Measured, not guessed: on this corpus's 229 unique-image Tier-2 candidate pairs
# vs. a 60-pair negative control of random unrelated images (2026-09-19), raw ORB
# match count alone already separated the two almost perfectly — the negative
# control topped out at 98 good matches (its RANSAC inlier_ratio is *not*
# trustworthy at that low a match count: with few correspondences a degenerate
# homography can fit all of them by chance, so inlier_ratio alone would have
# called some random pairs "confirmed"). ORB_MIN_GOOD_MATCHES=100 sits just above
# that observed ceiling; ORB_MIN_INLIER_RATIO=0.2 is the second, independent check.
# Together: 0/60 negative-control false-confirms, 197/229 (86.0%) of real Tier-2
# candidates confirmed. See docs/DECISIONS.md (2026-09-19). Phase 4 added a third,
# independent check (matched-area coverage) and watermark-region keypoint
# exclusion on top of these two - see pipeline/image_evidence.py.

def is_photo_evidence(item):
    """True for a real completion photo/scan, False for a scanner-app watermark strip."""
    return min(item['width'], item['height']) >= MIN_IMAGE_DIM

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')

def load_corpus(root):
    frames = []
    for path in sorted(Path(root).rglob('works_with_images.csv')):
        frame = pd.read_csv(path, dtype=str).fillna('')
        frame['_source_csv'] = str(path.resolve())
        frames.append(frame)
    if not frames:
        raise ValueError(f'No completed-work CSVs in {root}. Supply --root with the existing corpus.')
    df = pd.concat(frames, ignore_index=True)
    if df.WORK_ID.duplicated().any() or df.WORK_ID.eq('').any():
        raise ValueError('Missing or repeated WORK_ID: resolve source identity before scoring.')
    df = pd.concat([df, parse_letter_no(df.LETTER_NO.astype('string'))], axis=1)
    df['activity_norm'] = df.ACTIVITY_NAME.str.replace(r'^WS/MP\d+/\d{4}-\d{4}/\d+-', '', regex=True).str.strip()
    df['description_norm'] = df.WORK_DESCRIPTION.str.strip().str.lower().str.replace(r'\s+', ' ', regex=True)
    # Decimal-based normalization (rupee/thousand/lakh/crore, Indian comma
    # grouping) so an amount that can't be resolved to a single INR figure -
    # rather than being coerced to some guessed number - drops out as NaN here,
    # same as before, and is excluded from every amount-based detector below.
    df['ACTUAL_AMOUNT_raw'] = df.ACTUAL_AMOUNT
    _normalized = normalize_amount_series(df.ACTUAL_AMOUNT)
    df['ACTUAL_AMOUNT'] = [float(n.normalized_inr) if n.normalized_inr is not None else float('nan') for n in _normalized]
    df['ACTUAL_AMOUNT_status'] = [n.normalization_status for n in _normalized]
    df['image_count'] = pd.to_numeric(df.image_count, errors='coerce').fillna(0)
    df['actual_end_date'] = pd.to_datetime(df.ACTUAL_END_DATE, format='%d-%b-%Y', errors='coerce').dt.strftime('%Y-%m-%d').fillna('')
    df['is_synthetic'] = False
    return df

def jpeg_from_pdf(raw):
    i, j = raw.find(b'\xff\xd8\xff'), raw.rfind(b'\xff\xd9')
    return raw[i:j+2] if i >= 0 and j > i else None

ATTACHMENT_FAILURE_CATEGORIES = (
    'broken_source_reference', 'encrypted_document', 'corrupt_document',
    'pdf_without_extractable_image', 'document_page', 'unsupported_image_format', 'extraction_failure',
)

def classify_pdf_failure(raw):
    """Phase 5 A.4. Returns (jpeg_bytes_or_None, category, detail). Only
    called for a PDF whose naive byte-scan (jpeg_from_pdf) found no embedded
    JPEG - tries a real PDF parse via PyMuPDF to say WHY, and recovers a
    genuine embedded raster image (any format PyMuPDF/Pillow can decode) if
    the PDF has one at or above the usable-content floor. Never renders a
    page to manufacture an image - only bytes the PDF itself embeds as a
    raster XObject count, so a text-only document page can never become
    'evidence'. A small embedded raster (logo/letterhead/signature, below
    MIN_IMAGE_DIM) is reported as 'document_page', never treated as a photo."""
    try:
        doc = fitz.open(stream=raw, filetype='pdf')
    except Exception as exc:
        return None, 'corrupt_document', str(exc)
    try:
        if doc.is_encrypted or doc.needs_pass:
            return None, 'encrypted_document', 'PDF requires a password / is encrypted'
        best = None
        for page in doc:
            for img_info in page.get_images(full=True):
                try:
                    extracted = doc.extract_image(img_info[0])
                except Exception:
                    continue
                img_bytes = extracted.get('image')
                if not img_bytes:
                    continue
                try:
                    with Image.open(io.BytesIO(img_bytes)) as im:
                        im.load()
                        w, h = im.width, im.height
                except (OSError, UnidentifiedImageError):
                    continue
                if best is None or (w * h) > (best[1] * best[2]):
                    best = (img_bytes, w, h)
        if best is None:
            return None, 'pdf_without_extractable_image', 'No embedded raster image found in the PDF'
        img_bytes, w, h = best
        if min(w, h) < MIN_IMAGE_DIM:
            return None, 'document_page', f'Only a small embedded raster ({w}x{h}) below the usable-content floor - likely a logo/letterhead, not a photograph'
        try:
            with Image.open(io.BytesIO(img_bytes)) as im:
                im.load()
                buf = io.BytesIO()
                im.convert('RGB').save(buf, format='JPEG', quality=92)
                return buf.getvalue(), 'recovered', None
        except (OSError, UnidentifiedImageError) as exc:
            return None, 'unsupported_image_format', str(exc)
    finally:
        doc.close()

def phash(img):
    a = np.asarray(img.convert('L').resize((32, 32), Image.Resampling.LANCZOS), dtype=float)
    v = dct(dct(a, axis=0, norm='ortho'), axis=1, norm='ortho')[:8, :8].flatten()[1:]
    return np.packbits(v > np.median(v)).tobytes().hex()

def extract_images(df, cache=DATA / 'image_cache'):
    cache.mkdir(parents=True, exist_ok=True)
    manifest_path = cache / 'manifest.json'
    old = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    manifest, images, errors = {}, [], []
    for row in df.to_dict('records'):
        folder = Path(row['_source_csv']).parent
        for name in str(row['local_image_filenames']).split(';'):
            if not name.strip(): continue
            path = (folder / name.strip()).resolve()
            if not path.is_relative_to(folder.resolve()):
                errors.append({'file': name, 'error': 'Outside source directory', 'category': 'broken_source_reference'}); continue
            try:
                stat = path.stat()
                key = str(path)
                stamp = [stat.st_size, stat.st_mtime_ns]
                item = old.get(key)
                if not item or item['stamp'] != stamp or 'format' not in item or not (cache / item['filename']).exists():
                    raw = path.read_bytes()
                    is_pdf = raw.startswith(b'%PDF')
                    jpeg = jpeg_from_pdf(raw) if is_pdf else raw
                    recovered_via_pdf_parse = False
                    if not jpeg and is_pdf:
                        jpeg, category, detail = classify_pdf_failure(raw)
                        if jpeg is None:
                            errors.append({'file': str(path), 'error': detail or category, 'category': category}); continue
                        recovered_via_pdf_parse = True
                    elif not jpeg:
                        errors.append({'file': str(path), 'error': 'Not a decodable image or PDF', 'category': 'unsupported_image_format'}); continue
                    with Image.open(io.BytesIO(jpeg)) as img:
                        img.load()
                        digest = hashlib.md5(jpeg).hexdigest()
                        item = {'stamp': stamp, 'filename': digest + '.jpg', 'md5': digest,
                                'width': img.width, 'height': img.height, 'phash': phash(img),
                                'format': img.format or 'UNKNOWN', 'recovered_via_pdf_parse': recovered_via_pdf_parse}
                    (cache / item['filename']).write_bytes(jpeg)
                manifest[key] = item
                images.append({**item, 'work_id': str(row['WORK_ID']), 'source_filename': name.strip()})
            except UnidentifiedImageError as exc:
                errors.append({'file': str(path), 'error': str(exc), 'category': 'unsupported_image_format'})
            except FileNotFoundError as exc:
                errors.append({'file': str(path), 'error': str(exc), 'category': 'broken_source_reference'})
            except (OSError, ValueError) as exc:
                errors.append({'file': str(path), 'error': str(exc), 'category': 'extraction_failure'})
    write_json(manifest_path, manifest)
    return images, errors

def photo_duplicates(images, image_dir=DATA / 'image_cache'):
    """Returns (pairs, image_matches, stats). `pairs` keeps its Phase 1 shape
    (backward compatible with data/duplicate_pairs.json and the existing
    Evidence viewer/tests) plus a few new fields (classification,
    risk_eligible, matched_area_coverage). `image_matches` is the new Phase 4
    persistence-ready schema (deterministic match_id, both image ids,
    detector/preprocessing versions, full ORB metrics) - see
    pipeline/image_evidence.py. Both are built from exactly one
    classify_image_pair call per unique image pair - never recomputed twice."""
    pairs, image_matches, groups = [], [], defaultdict(list)
    for item in images: groups[item['md5']].append(item)
    def pair(a, b, tier, **extra):
        return {'tier': tier, 'work_ids': [a['work_id'], b['work_id']], 'images': [a, b], **extra}
    def match_record(img_a, img_b, phash_distance, result):
        return {'match_id': image_match_id(image_id_of(img_a['md5']), image_id_of(img_b['md5'])),
                'image_id_a': image_id_of(img_a['md5']), 'image_id_b': image_id_of(img_b['md5']),
                'work_id_a': img_a['work_id'], 'work_id_b': img_b['work_id'],
                'phash_distance': phash_distance, 'classification': result.classification,
                'risk_eligible': result.risk_eligible, 'reason': result.reason,
                'good_matches': result.good_matches, 'inliers': result.inliers,
                'inlier_ratio': result.inlier_ratio, 'matched_area_coverage': result.matched_area_coverage,
                'keypoints_a': result.keypoints_a, 'keypoints_b': result.keypoints_b,
                'masked_keypoints_excluded_a': result.masked_keypoints_excluded_a,
                'masked_keypoints_excluded_b': result.masked_keypoints_excluded_b,
                'preprocessing_version': IMAGE_PREPROCESSING_VERSION, 'detector_version': IMAGE_MATCH_DETECTOR_VERSION}
    exact_groups = 0
    tier1_watermark_groups = []
    for values in groups.values():
        values = list({x['work_id']: x for x in values}.values())
        if len(values) <= 1:
            continue
        # A byte-identical strip shared across works is a scanner-app watermark, not
        # reused evidence — the tag itself is never the signal. Log it, don't pair it.
        if not is_photo_evidence(values[0]):
            tier1_watermark_groups.append(sorted(x['work_id'] for x in values))
            continue
        exact_groups += 1
        identical = type('R', (), dict(classification='confirmed_visual_correspondence', risk_eligible=True,
                          reason='Byte-identical file content across different works.', good_matches=None,
                          inliers=None, inlier_ratio=None, matched_area_coverage=1.0, keypoints_a=None,
                          keypoints_b=None, masked_keypoints_excluded_a=None, masked_keypoints_excluded_b=None))()
        for a, b in itertools.combinations(values, 2):
            pairs.append(pair(a, b, 'photo_identical', keypoint_confirmed=True, classification=identical.classification, risk_eligible=True))
            image_matches.append(match_record(a, b, 0, identical))
    # Compare unique bytes once; preserve all work associations when expanding accepted pairs.
    reps = [v[0] for v in groups.values()]
    gated = [v for v in reps if is_photo_evidence(v)]
    hist = np.zeros(65, dtype=np.int64)
    candidates = []
    for i, a in enumerate(gated):
        ah = int(a['phash'], 16)
        for j in range(i + 1, len(gated)):
            distance = (ah ^ int(gated[j]['phash'], 16)).bit_count()
            hist[distance] += 1
            if distance <= 6: candidates.append((i, j, distance))
    # A conservative low-tail cutoff, derived from the measured 1st percentile and capped at 6.
    # Suggested initial calibration, re-derived from this corpus every run - not an
    # established industry standard for pHash bucketing.
    total = int(hist.sum())
    percentile = lambda p: int(np.searchsorted(np.cumsum(hist), max(1, total * p))) if total else 0
    threshold = min(6, max(2, percentile(.01) // 2))
    candidates = [c for c in candidates if c[2] <= threshold]
    parent = list(range(len(gated)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for i, j, _ in candidates: parent[find(i)] = find(j)
    memberships = defaultdict(set)
    for i, a in enumerate(gated):
        memberships[find(i)].update(x['work_id'] for x in groups[a['md5']])
    suppressed = [sorted(v) for v in memberships.values() if len(v) > 6]
    classification_counts = defaultdict(int)
    keypoint_evaluated = keypoint_confirmed_groups = 0
    for i, j, distance in candidates:
        if len(memberships[find(i)]) > 6: continue
        # One ORB pass per unique image pair, not per expanded work pair — several
        # work_ids can share the same underlying MD5-deduped image on either side.
        # pHash retrieved this candidate; ORB is what may promote it - a pHash
        # match alone (below) never sets risk_eligible.
        result = classify_image_pair(image_dir / gated[i]['filename'], image_dir / gated[j]['filename'])
        keypoint_evaluated += 1
        classification_counts[result.classification] += 1
        if result.risk_eligible: keypoint_confirmed_groups += 1
        for a, b in itertools.product(groups[gated[i]['md5']], groups[gated[j]['md5']]):
            if a['work_id'] != b['work_id']:
                pairs.append(pair(a, b, 'photo_similar', hamming_distance=distance,
                                   keypoint_confirmed=result.risk_eligible,
                                   keypoint_good_matches=result.good_matches,
                                   keypoint_inliers=result.inliers,
                                   keypoint_inlier_ratio=result.inlier_ratio,
                                   classification=result.classification,
                                   risk_eligible=result.risk_eligible,
                                   matched_area_coverage=result.matched_area_coverage))
                image_matches.append(match_record(a, b, distance, result))
    # Count the same threshold before dimension gating to make its effect measurable.
    before = sum((int(a['phash'],16)^int(b['phash'],16)).bit_count() <= threshold
                 for a,b in itertools.combinations(reps,2))
    stats = {'attachments': len(images), 'unique_images': len(reps), 'dimension_eligible': len(gated),
             'tier1_groups': exact_groups, 'threshold': threshold, 'hamming_histogram': hist.tolist(),
             'hamming_percentiles': {str(p): percentile(p/100) for p in [1,5,25,50,75,95]},
             'tier2_candidates_before_gating': before, 'tier2_candidates_after_dimension_gate': len(candidates),
             'tier2_pairs_after_all_gates': sum(p['tier']=='photo_similar' for p in pairs),
             'suppressed_common_components': suppressed,
             'tier1_watermark_groups': tier1_watermark_groups,
             'tier1_watermark_strips_suppressed': len(tier1_watermark_groups),
             'threshold_reason': 'Half the measured lower 1% Hamming distance, constrained to 2–6; heuristic, not an established standard.',
             'tier3_unique_image_pairs_evaluated': keypoint_evaluated,
             'tier3_keypoint_confirmed_pairs': keypoint_confirmed_groups,
             'tier3_classification_counts': dict(classification_counts),
             'tier3_method': f'ORB (nfeatures=1500, watermark-region keypoints excluded) + Lowe ratio test ({ORB_RATIO_TEST}) '
                              f'+ RANSAC homography; confirmed if good_matches>={ORB_MIN_GOOD_MATCHES}, inlier_ratio>={ORB_MIN_INLIER_RATIO} '
                              f'and matched_area_coverage — see pipeline/image_evidence.py for versions and docs/DECISIONS.md for calibration.',
             'preprocessing_version': IMAGE_PREPROCESSING_VERSION, 'detector_version': IMAGE_MATCH_DETECTOR_VERSION}
    return pairs, image_matches, stats

def text_duplicates(df, near=True):
    pairs = []
    for _, frame in df.groupby('MP_NAME'):
        descriptions = defaultdict(list)
        for row in frame.to_dict('records'):
            if row['description_norm'] and pd.notna(row['fy_start_year']):
                descriptions[row['description_norm']].append(row)
        def emit(a, b, tier, similarity):
            if a['fy_start_year'] != b['fy_start_year'] and a['WORK_ID'] != b['WORK_ID']:
                pairs.append({'tier': tier, 'work_ids': [a['WORK_ID'], b['WORK_ID']],
                              'descriptions': [a['WORK_DESCRIPTION'], b['WORK_DESCRIPTION']],
                              'years': [int(a['fy_start_year']), int(b['fy_start_year'])], 'similarity': similarity})
        for values in descriptions.values():
            for a, b in itertools.combinations(values, 2): emit(a,b,'text_exact',1.0)
        if near:
            for (a, av), (b, bv) in itertools.combinations(descriptions.items(), 2):
                if not any(x['fy_start_year'] != y['fy_start_year'] for x in av for y in bv): continue
                matcher = SequenceMatcher(None,a,b,autojunk=False)
                if matcher.real_quick_ratio() <= .9 or matcher.quick_ratio() <= .9: continue
                ratio = matcher.ratio()
                if ratio > .9:
                    for x,y in itertools.product(av,bv): emit(x,y,'text_similar',ratio)
    return pairs

def peer_z(df, value_col, category_col, state_col, min_size=10):
    """One-sided robust z-score of value_col within a category x state peer group,
    falling back to category-only then the whole population under min_size peers.
    Returns (z, peer_group_key, peer_size), aligned to df's index. Shared by the
    cost-peer rule and the long-open-work duration check — same fallback ladder, same
    "only above-peers is scored" convention, so a low/fast value never flags."""
    keys = df[category_col].astype(str) + ' | ' + df[state_col].astype(str)
    counts = keys.map(keys.value_counts())
    cats = df[category_col].map(df[category_col].value_counts())
    group_key = np.where(counts >= min_size, keys, np.where(cats >= min_size, df[category_col], 'Whole corpus'))
    grouped = df.assign(_peer_group_key=group_key)
    med = pd.Series(0., index=df.index); mad = med.copy(); sizes = med.copy(); populations = {}
    for key, assigned in grouped.groupby('_peer_group_key'):
        example = assigned.iloc[0]
        eligible = ((df[category_col].eq(example[category_col]) & df[state_col].eq(example[state_col]))
                    if key == str(example[category_col]) + ' | ' + str(example[state_col])
                    else df[category_col].eq(example[category_col]) if key == example[category_col]
                    else pd.Series(True, index=df.index))
        populations[key] = eligible
        values = df.loc[eligible, value_col]; median = values.median()
        med.loc[assigned.index] = median
        mad.loc[assigned.index] = (values - median).abs().median()
        sizes.loc[assigned.index] = int(eligible.sum())
    # Zero MAD: use a 10% median scale to avoid zero/infinite deviations on constant peers.
    scale = (1.4826 * mad).where(mad > 0, med.abs().mul(.1).clip(lower=1))
    z = ((df[value_col] - med) / scale).fillna(0)
    return z, pd.Series(group_key, index=df.index), sizes.astype(int), populations

def cost_rule(z, group, size, amount):
    # One-sided: only an amount well above its peers is a concern. A low amount is
    # reported for context but never flagged and never adds to the risk score.
    high = z > 2.5
    reason = (f'Amount ₹{amount:,.0f} is unusually high compared to {size} peers in {group}.' if high
              else f'Amount ₹{amount:,.0f} is below its {size} peers in {group}; low cost is not flagged.' if z < -2.5
              else f'Amount ₹{amount:,.0f} is within the usual range for {size} peers in {group}.')
    return {'flag': bool(high), 'raw': float(z), 'score': min(max(float(z),0)/6,1), 'reason': reason}

def missing_rule(count):
    return {'flag': bool(count == 0), 'raw': int(count), 'score': float(count == 0),
            'reason': f'{int(count)} source-listed attachments. Missing completion evidence is advisory; unavailable downloads are tracked separately.'}

def entitlement_totals(universe, cap=MPLADS_ENTITLEMENT_PER_FY):
    """{(mp_norm, fy_start_year): total sanctioned Rs} from the full sanctioned
    universe (completed + not-yet-completed) — a single-year comparison needs
    everything sanctioned in the year, not just what has since been completed."""
    if universe is None: return {}
    valid = universe.dropna(subset=['mp_norm', 'fy_start_year', 'sanction_amount'])
    if valid.empty: return {}
    totals = valid.groupby(['mp_norm', valid.fy_start_year.astype(int)]).sanction_amount.sum()
    return totals.to_dict()

def entitlement_rule(total, mp_name, fy_start_year, cap=MPLADS_ENTITLEMENT_PER_FY):
    # Deliberately NOT framed as a "breach": MPLADS entitlement is non-lapsable and
    # carries forward across an MP's tenure, so sanctioning more than one year's
    # ₹5cr in a single fiscal year is exactly what legitimate catch-up on a prior
    # under-utilised year looks like — this corpus has no tenure-start date wired
    # through to test the real cumulative cap, so a single-FY total above the
    # nominal entitlement is advisory context, not a sourced violation. Low weight,
    # not part of the Critical floor (see docs/DECISIONS.md).
    if total is None:
        return {'flag': False, 'raw': 0.0, 'score': 0.0,
                'reason': 'No matched sanctioned-table record for this MP and fiscal year.'}
    over = total > cap
    fy = f'FY{fy_start_year}-{fy_start_year + 1}' if fy_start_year else 'this fiscal year'
    reason = (f'₹{total:,.0f} sanctioned for {mp_name} in {fy}, above the ₹5 crore/MP/year nominal entitlement '
              f'(MPLADS Guidelines 2023). Entitlement is non-lapsable and carries forward across years, so this '
              f'alone is not proof of a limit breach — a busy year can legitimately draw on an under-used prior year.'
              if over else
              f'₹{total:,.0f} sanctioned for {mp_name} in {fy}, within the ₹5 crore/MP/year nominal entitlement.')
    return {'flag': bool(over), 'raw': float(total), 'score': float(min(max((total - cap) / cap, 0), 1)), 'reason': reason}

def long_open_work_signal(universe, as_of_date, min_peer_size=MIN_PEER_SIZE):
    """Works sanctioned but with no completed record yet, held open materially
    longer than comparable peers (State/UT x activity category, sanction-year
    implicit in as_of_date being a fixed snapshot). Disjoint by construction
    from the fraud-scored completed corpus — every row here has no completed
    record. Named `long_open_work`, never "idle funds" — this corpus has no
    released/spent balance fields, so there is no financial basis to claim
    money is sitting idle, only that the work has been open a long time
    (Phase 3 instructions, section 2)."""
    long_open = universe[~universe.has_completed_record & universe.has_sanctioned_record].copy()
    long_open = long_open.dropna(subset=['sanction_date', 'activity_norm', 'state_name'])
    long_open['days_since_sanction'] = (as_of_date - long_open.sanction_date).dt.days
    z, group_key, sizes, populations = peer_z(long_open, 'days_since_sanction', 'activity_norm', 'state_name')
    long_open['duration_z'], long_open['peer_group_key'], long_open['peer_size'] = z, group_key, sizes
    # Insufficient peer sample: don't compute a threshold off fewer than
    # min_peer_size comparable works - mark unavailable rather than guess.
    long_open['peer_insufficient'] = long_open.peer_size < min_peer_size
    long_open['flag'] = (long_open.duration_z > 2.5) & ~long_open.peer_insufficient
    # Peer median/threshold in days, for display (Phase 3: "store the peer
    # definition, sample size, median and threshold").
    medians = long_open.groupby('peer_group_key').days_since_sanction.median()
    long_open['peer_median_days'] = long_open.peer_group_key.map(medians)
    scales = long_open.groupby('peer_group_key').days_since_sanction.apply(
        lambda v: 1.4826 * (v - v.median()).abs().median())
    long_open['peer_threshold_days'] = long_open.peer_group_key.map(
        lambda k: medians[k] + 2.5 * (scales[k] if scales[k] > 0 else max(medians[k] * .1, 1)))
    return long_open

def late_sanction_signal(universe, review_days=LATE_SANCTION_REVIEW_DAYS):
    """Recommendation-to-sanction/rejection gap versus the Phase 3 review
    indicator. Computed ONLY when both a reliable recommendation date and a
    sanction (or rejection) date exist - a row missing either is excluded
    here and reported `unavailable` (never a fiscal-year-start substitute;
    see build_inefficiency's unavailable handling below) by the caller."""
    late = universe.dropna(subset=['recommendation_date', 'sanction_date']).copy()
    late['sanction_lag_days'] = (late.sanction_date - late.recommendation_date).dt.days
    late['flag'] = late.sanction_lag_days > review_days
    return late

def _bucketed_score(excess_ratio):
    """0.0 at the threshold itself, growing toward 1.0 (strong) the further
    past it a value is - deliberately NO floor at 'medium': with the Phase 3
    45-day late_sanction window, roughly two-thirds of all sanctioned records
    exceed it at all, so a bare pass/fail flag with an artificial medium
    floor would make nearly every late-sanctioned record independently
    case-eligible - exactly the alert-volume problem Phase 3 asks to avoid.
    A record barely over the line scores near 0 (weak); one far past it
    scores high (strong) - see docs/DECISIONS.md's Phase 3 entry."""
    return float(min(max(excess_ratio, 0), 1.0))

def standardize_inefficiency_signals(finding):
    """Adapts one build_inefficiency finding (a real WORK_ID row) into the
    Phase 3 standard contract. Only called for findings with a WORK_ID - a
    sanctioned-only record with no WORK_ID yet has no stable identity a case
    could attach to across pipeline reruns."""
    out = []
    lo = finding.get('long_open_work')
    if lo is not None:
        if lo['status'] == 'unavailable':
            out.append(make_signal(finding['WORK_ID'], 'long_open_work', 'inefficiency', 'unavailable',
                                    unavailable_reason=lo['unavailable_reason'], detector_version=DETECTOR_VERSION,
                                    threshold_version=THRESHOLD_VERSION))
        else:
            excess = (lo['days_since_sanction'] - lo['peer_threshold_days']) / max(lo['peer_threshold_days'], 1)
            out.append(make_signal(finding['WORK_ID'], 'long_open_work', 'inefficiency',
                                    'fired' if lo['flag'] else 'clear', score=_bucketed_score(excess) if lo['flag'] else 0.0,
                                    explanation=lo['reason'], recommended_action='Follow up with the implementing agency on completion status.',
                                    evidence=[{'type': 'peer_stat', 'peer_group': lo['peer_group'], 'peer_size': lo['peer_size'],
                                               'peer_median_days': lo['peer_median_days'], 'peer_threshold_days': lo['peer_threshold_days']}],
                                    detector_version=DETECTOR_VERSION, threshold_version=THRESHOLD_VERSION))
    late = finding.get('late_sanction')
    if late is not None:
        if late['status'] == 'unavailable':
            out.append(make_signal(finding['WORK_ID'], 'late_sanction', 'inefficiency', 'unavailable',
                                    unavailable_reason=late['unavailable_reason'], detector_version=DETECTOR_VERSION,
                                    threshold_version=THRESHOLD_VERSION, source='MPLADS Guidelines'))
        else:
            excess = (late['sanction_lag_days'] - late['threshold_days']) / max(late['threshold_days'], 1)
            out.append(make_signal(finding['WORK_ID'], 'late_sanction', 'inefficiency',
                                    'fired' if late['flag'] else 'clear', score=_bucketed_score(excess) if late['flag'] else 0.0,
                                    explanation=late['reason'], recommended_action='Escalate the sanctioning delay to the district authority.',
                                    evidence=[{'type': 'date_range', 'start_date': late['start_date'], 'end_date': late['end_date'],
                                               'sanction_lag_days': int(late['sanction_lag_days']), 'threshold_days': int(late['threshold_days']),
                                               'days_over_threshold': int(late['sanction_lag_days'] - late['threshold_days'])}],
                                    detector_version=DETECTOR_VERSION, threshold_version=THRESHOLD_VERSION,
                                    source='Phase 3 review indicator (docs/DECISIONS.md)'))
    return out

def build_inefficiency(universe, as_of_date, min_peer_size=MIN_PEER_SIZE, review_days=LATE_SANCTION_REVIEW_DAYS):
    """Inefficiency findings — kept entirely separate from the fraud signals_json /
    risk_score / severity_band: a different artifact, a different population (this
    includes 6,000+ sanctioned-but-not-completed works the fraud corpus never
    sees), no shared weighting, no shared severity language. Every sanctioned
    record gets a finding row now (not only flagged ones) so an `unavailable`
    detector state is visible rather than silently omitted; `/inefficiency`
    still defaults to flagged-only for the review queue (see backend/main.py)."""
    long_open = long_open_work_signal(universe, as_of_date, min_peer_size)
    late = late_sanction_signal(universe, review_days)
    merged = (universe
              .merge(long_open[['record_id', 'days_since_sanction', 'duration_z', 'peer_group_key', 'peer_size',
                                 'peer_median_days', 'peer_threshold_days', 'peer_insufficient', 'flag']]
                     .rename(columns={'peer_group_key': 'lo_peer_group', 'peer_size': 'lo_peer_size',
                                       'peer_median_days': 'lo_peer_median', 'peer_threshold_days': 'lo_peer_threshold',
                                       'peer_insufficient': 'lo_peer_insufficient', 'flag': 'lo_flag'}),
                     on='record_id', how='left')
              .merge(late[['record_id', 'sanction_lag_days', 'flag']].rename(columns={'flag': 'late_flag'}),
                     on='record_id', how='left'))
    merged['lo_flag'] = merged.lo_flag.fillna(False)
    merged['late_flag'] = merged.late_flag.fillna(False)
    # A candidate for either detector: has a completed-record-eligible row for
    # long_open (sanctioned, not completed) or a dated pair for late_sanction.
    merged['is_lo_candidate'] = ~merged.has_completed_record & merged.has_sanctioned_record
    # A candidate whenever the record should have both dates (it's a sanctioned
    # record) and has at least one of them - a row with neither is truly
    # nothing to report, but a row missing just one gets an explicit
    # `unavailable` finding rather than being silently dropped.
    merged['is_late_candidate'] = merged.has_sanctioned_record & (merged.recommendation_date.notna() | merged.sanction_date.notna())
    relevant = merged[merged.is_lo_candidate | merged.is_late_candidate].copy()
    relevant = relevant.sort_values(['lo_flag', 'days_since_sanction', 'late_flag', 'sanction_lag_days'],
                                     ascending=False, na_position='last')

    def row_to_finding(r):
        long_open_block = None
        if pd.notna(r.days_since_sanction):
            if r.lo_peer_insufficient:
                long_open_block = {'status': 'unavailable', 'days_since_sanction': int(r.days_since_sanction),
                                    'unavailable_reason': f'Fewer than {min_peer_size} comparable peers '
                                                           f'({int(r.lo_peer_size)} in {r.lo_peer_group}) - no reliable threshold.'}
            else:
                long_open_block = {'status': 'fired' if r.lo_flag else 'clear', 'flag': bool(r.lo_flag),
                                    'days_since_sanction': int(r.days_since_sanction), 'peer_group': r.lo_peer_group,
                                    'peer_size': int(r.lo_peer_size), 'peer_median_days': round(float(r.lo_peer_median), 1),
                                    'peer_threshold_days': round(float(r.lo_peer_threshold), 1),
                                    'reason': (f'Sanctioned {int(r.days_since_sanction)} days ago with no completion record yet — '
                                               f'past the {round(r.lo_peer_threshold)}-day threshold for {int(r.lo_peer_size)} peers '
                                               f'in {r.lo_peer_group} (peer median {round(r.lo_peer_median)} days).'
                                               if r.lo_flag else
                                               f'Sanctioned {int(r.days_since_sanction)} days ago with no completion record yet; '
                                               f'within the usual range for {int(r.lo_peer_size)} peers in {r.lo_peer_group} '
                                               f'(peer median {round(r.lo_peer_median)} days, threshold {round(r.lo_peer_threshold)}).')}
        elif r.is_lo_candidate:
            long_open_block = {'status': 'unavailable', 'unavailable_reason': 'Missing sanction date, activity category or state.'}
        late_block = None
        if pd.notna(r.sanction_lag_days):
            over = int(r.sanction_lag_days) - review_days
            # Phase 4 A.1: this corpus has no distinct rejection-date field
            # (only a sanction date), so `end_date` here is always the
            # sanction date - "sanctioned or rejected" per the instructed
            # wording is the general case this calculation supports, not a
            # claim that rejections are separately tracked in this data.
            late_block = {'status': 'fired' if r.late_flag else 'clear', 'flag': bool(r.late_flag),
                          'sanction_lag_days': int(r.sanction_lag_days), 'threshold_days': review_days,
                          'start_date': None if pd.isna(r.recommendation_date) else r.recommendation_date.strftime('%Y-%m-%d'),
                          'end_date': None if pd.isna(r.sanction_date) else r.sanction_date.strftime('%Y-%m-%d'),
                          'reason': (f'Exceeded the {review_days}-day administrative sanction/rejection timeline '
                                     f'by {over} days ({int(r.sanction_lag_days)} days from recommendation-received to '
                                     f'sanctioned). This is a computational timeline check, not a finding of fraud or '
                                     f'proven non-compliance.'
                                     if r.late_flag else
                                     f'Sanctioned {int(r.sanction_lag_days)} days after recommendation — within the '
                                     f'{review_days}-day administrative sanction/rejection timeline.')}
        elif pd.notna(r.recommendation_date) or pd.notna(r.sanction_date):
            missing = ('recommendation date (date recommendation received)' if pd.isna(r.recommendation_date) else 'sanction/rejection date')
            late_block = {'status': 'unavailable', 'unavailable_reason': f'Missing a reliable {missing}; not substituted with a fiscal-year proxy.'}
        text = lambda v: None if pd.isna(v) else str(v)
        return {'RECORD_ID': str(r.record_id), 'WORK_ID': text(r.work_id),
                'MP_NAME': text(r.mp_name), 'CONSTITUENCY': text(r.constituency), 'STATE_NAME': text(r.state_name),
                'ACTIVITY_NAME': text(r.activity_name), 'WORK_DESCRIPTION': text(r.work_description),
                'is_completed': bool(r.has_completed_record),
                'sanction_amount': None if pd.isna(r.sanction_amount) else float(r.sanction_amount),
                'sanction_date': None if pd.isna(r.sanction_date) else r.sanction_date.strftime('%Y-%m-%d'),
                'recommendation_date': None if pd.isna(r.recommendation_date) else r.recommendation_date.strftime('%Y-%m-%d'),
                'long_open_work': long_open_block, 'late_sanction': late_block}

    relevant = relevant.reset_index(drop=True)
    findings = [row_to_finding(r) for r in relevant.itertuples()]
    stats = {'sanctioned_universe_rows': int(len(universe)), 'completed_rows': int(universe.has_completed_record.sum()),
             'sanctioned_only_rows': int((~universe.has_completed_record & universe.has_sanctioned_record).sum()),
             'long_open_candidates': int(len(long_open)), 'long_open_flagged': int(long_open.flag.sum()),
             'long_open_insufficient_peers': int(long_open.peer_insufficient.sum()), 'min_peer_size': min_peer_size,
             'late_sanction_candidates': int(len(late)), 'late_sanction_flagged': int(late.flag.sum()),
             'late_sanction_fraction': float(late.flag.mean()) if len(late) else None,
             'late_sanction_review_days': review_days, 'as_of_date': as_of_date.strftime('%Y-%m-%d'),
             'source': f'Phase 3 review indicator: {review_days}-day recommendation-to-sanction window '
                       f'(see docs/DECISIONS.md for the discrepancy with Phase 1/2’s original 75-day citation).'}
    return findings, stats

# Same relative importance as score_works's risk_score weights below (not
# duplicated by accident - re-using the one place this was already decided
# and documented). A signal's raw 0/1 or 0-1 score measures "did this fire
# and how far," not "how much should this matter" - missing_evidence's flag
# is binary (0 or 1) but carries weight 5 of 105 in the original model, so a
# work with zero photos must NOT standardize to 'strong' just because its
# own raw score maxed out. Normalizing every signal's contribution to this
# same 0-1 importance scale before bucketing into weak/medium/strong is what
# keeps a single missing_evidence flag from opening a case on its own (see
# docs/DECISIONS.md's Phase 3 entry for the alert-volume investigation that
# found this).
IMPORTANCE_WEIGHTS = dict(cost_peer=15, missing_evidence=5, anomaly=15, photo_identical=25,
                           photo_similar=10, text_exact=20, text_similar=5, entitlement_pace=5)
_MAX_IMPORTANCE = max(IMPORTANCE_WEIGHTS.values())

def _importance_scaled(code, raw_score):
    return raw_score * IMPORTANCE_WEIGHTS[code] / _MAX_IMPORTANCE

def _amount_unavailable_status(amount_status):
    """Maps amount_normalize's status to the detection-contract's distinction
    between 'a data defect blocked this' and 'genuinely nothing recorded'."""
    if amount_status in ('unparseable', 'ambiguous_unit'):
        return 'data_quality_failure', f'Amount normalization status: {amount_status}.'
    return 'unavailable', 'No amount value available for this record.'

def standardize_fraud_signals(row, signals, unconfirmed_similar_count, photo_classification=None):
    """Adapts score_works's existing per-work signal dict (unchanged shape,
    unchanged evidence) into the Phase 3 standard contract. Preserves every
    existing detector's evidence/reason - this only re-labels status/family/
    strength around it, never re-derives the underlying numbers."""
    out = []
    amount_available = bool(np.isfinite(row.ACTUAL_AMOUNT))
    for code in ('cost_peer',):
        s = signals[code]
        if not amount_available:
            status, reason = _amount_unavailable_status(row.ACTUAL_AMOUNT_status)
            out.append(make_signal(row.WORK_ID, code, 'anomaly', status, unavailable_reason=reason,
                                    detector_version=DETECTOR_VERSION, threshold_version=THRESHOLD_VERSION,
                                    explanation=s['reason'], data_mode='synthetic_demo' if row.is_synthetic else 'real'))
            continue
        out.append(make_signal(row.WORK_ID, code, 'anomaly', 'fired' if s['flag'] else 'clear', score=_importance_scaled(code, s['score']),
                                explanation=s['reason'], recommended_action='Verify the amount against the source record and its peer works.',
                                evidence=[{'type': 'peer_stat', 'peer_group': row.peer_group_key, 'peer_size': int(row.peer_size)}],
                                detector_version=DETECTOR_VERSION, threshold_version=THRESHOLD_VERSION,
                                data_mode='synthetic_demo' if row.is_synthetic else 'real'))
    s = signals['missing_evidence']
    out.append(make_signal(row.WORK_ID, 'missing_evidence', 'anomaly', 'fired' if s['flag'] else 'clear', score=_importance_scaled('missing_evidence', s['score']),
                            explanation=s['reason'], recommended_action='Confirm completion attachments exist at the source portal.',
                            detector_version=DETECTOR_VERSION, threshold_version=THRESHOLD_VERSION,
                            data_mode='synthetic_demo' if row.is_synthetic else 'real'))
    s = signals['anomaly']
    out.append(make_signal(row.WORK_ID, 'anomaly', 'anomaly', 'fired' if s['flag'] else 'clear', score=_importance_scaled('anomaly', s['score']),
                            explanation=s['reason'], recommended_action='Compare this work against its peer group in detail.',
                            evidence=[{'type': 'isolation_forest_raw', 'value': s['raw']}],
                            detector_version=DETECTOR_VERSION, threshold_version=THRESHOLD_VERSION,
                            data_mode='synthetic_demo' if row.is_synthetic else 'real'))
    for code in ('photo_identical', 'text_exact', 'text_similar'):
        s = signals[code]
        out.append(make_signal(row.WORK_ID, code, 'anomaly', 'fired' if s['flag'] else 'clear', score=_importance_scaled(code, s['score']),
                                explanation=s['reason'], recommended_action='Open the linked evidence pair(s) and compare directly.',
                                evidence=[{'type': 'pair_count', 'count': s['raw']}],
                                detector_version=DETECTOR_VERSION, threshold_version=THRESHOLD_VERSION,
                                data_mode='synthetic_demo' if row.is_synthetic else 'real'))
    s = signals['photo_similar']
    # Phase 4: status driven by the actual image-match classification
    # (pipeline/image_evidence.py), not a bare confirmed/unconfirmed flag -
    # 'insufficient_features'/'processing_failed' are 'unavailable' (a check
    # that couldn't run), never silently folded into 'clear' (a check that
    # ran and found nothing) or 'candidate_only' (evidence exists, unscored).
    if s['flag']:
        status, unavailable_reason = 'fired', None
    elif photo_classification in ('insufficient_features', 'processing_failed'):
        status, unavailable_reason = 'unavailable', f'Image-match check could not run: {photo_classification.replace("_", " ")}.'
    elif unconfirmed_similar_count:
        status, unavailable_reason = 'candidate_only', None
    else:
        status, unavailable_reason = 'clear', None
    # Phase 4 explicitly upgrades a genuinely ORB+RANSAC-confirmed cross-work
    # correspondence to "one strong review signal" - full score (not the
    # original risk_score model's lower 10/105 weight, which only ever
    # governed the numeric risk_score/severity_band, left untouched above).
    out.append(make_signal(row.WORK_ID, 'photo_similar', 'anomaly', status,
                            score=1.0 if status == 'fired' else 0.0,
                            explanation=s['reason'], recommended_action='Open the linked evidence pair(s) and compare directly.',
                            unavailable_reason=unavailable_reason,
                            evidence=[{'type': 'pair_count', 'count': s['raw']}, {'type': 'unconfirmed_candidate_count', 'count': unconfirmed_similar_count},
                                      {'type': 'strongest_classification', 'value': photo_classification}],
                            detector_version=DETECTOR_VERSION, threshold_version=IMAGE_MATCH_DETECTOR_VERSION,
                            data_mode='synthetic_demo' if row.is_synthetic else 'real'))
    s = signals['entitlement_pace']
    if s['reason'].startswith('No matched'):
        out.append(make_signal(row.WORK_ID, 'entitlement_pace', 'anomaly', 'unavailable',
                                unavailable_reason='No matched sanctioned-table record for this MP and fiscal year.',
                                explanation=s['reason'], detector_version=DETECTOR_VERSION, threshold_version=THRESHOLD_VERSION,
                                source='MPLADS Guidelines 2023', data_mode='synthetic_demo' if row.is_synthetic else 'real'))
    else:
        out.append(make_signal(row.WORK_ID, 'entitlement_pace', 'anomaly', 'fired' if s['flag'] else 'clear', score=_importance_scaled('entitlement_pace', s['score']),
                                explanation=s['reason'], recommended_action='Check this MP’s full-tenure entitlement usage, not just this fiscal year.',
                                detector_version=DETECTOR_VERSION, threshold_version=THRESHOLD_VERSION,
                                source='MPLADS Guidelines 2023', data_mode='synthetic_demo' if row.is_synthetic else 'real'))
    return out

def score_works(df, pairs, entitlement=None):
    df = df.copy()
    df['amount_z'], df['peer_group_key'], df['peer_size'], populations = peer_z(df, 'ACTUAL_AMOUNT', 'activity_norm', 'STATE_NAME')
    df['cost_per_unit_z'] = df.amount_z
    features = ['amount_z','cost_per_unit_z','image_count']
    X = df[features].to_numpy(dtype=float)
    forest = IsolationForest(contamination=.05, random_state=42, n_estimators=150)
    scaled = RobustScaler().fit_transform(X)
    anomaly_raw = -forest.fit(scaled).decision_function(scaled)
    df['anomaly_raw'] = anomaly_raw
    df['anomaly_score'] = pd.Series(anomaly_raw).rank(pct=True).to_numpy()
    deviations=pd.DataFrame(0.,index=df.index,columns=features)
    for key,assigned in df.groupby('peer_group_key'):
        peer_features=df.loc[populations[key],features]
        deviations.loc[assigned.index]=(assigned[features]-peer_features.mean())/peer_features.std().replace(0,1).fillna(1)
    # photo_similar only counts toward the flag/score once ORB + RANSAC confirms
    # it (keypoint_confirm) — precision matters more than recall for photo reuse.
    # An unconfirmed candidate still appears as evidence in duplicate_pairs.json /
    # the Evidence viewer, honestly labelled, just not counted here.
    index = defaultdict(lambda: defaultdict(int))
    unconfirmed_similar = defaultdict(int)
    # Phase 4: the strongest image-match classification touching each work,
    # for standardize_fraud_signals's photo_similar status (distinguishing
    # 'clear' - a rejected watermark/generic match, a real negative - from
    # 'candidate_only' and 'unavailable', never just a binary confirmed flag).
    _PRIORITY = {'confirmed_visual_correspondence': 4, 'candidate_only': 3, 'insufficient_features': 2,
                 'processing_failed': 2, 'rejected_watermark': 1, 'rejected_generic_similarity': 1}
    photo_classification_by_work: dict[str, str] = {}
    for p in pairs:
        if p['tier'] != 'photo_similar': continue
        classification = p.get('classification', 'confirmed_visual_correspondence' if p.get('keypoint_confirmed') else 'rejected_generic_similarity')
        for wid in set(p['work_ids']):
            if _PRIORITY.get(classification, 0) > _PRIORITY.get(photo_classification_by_work.get(wid), -1):
                photo_classification_by_work[wid] = classification
    for p in pairs:
        if p['tier'] == 'photo_similar' and not p.get('keypoint_confirmed'):
            for wid in set(p['work_ids']): unconfirmed_similar[wid] += 1
            continue
        for wid in set(p['work_ids']): index[wid][p['tier']] += 1
    signals_out, risks, bands, standard_out = [], [], [], []
    for i,row in df.iterrows():
        signals = {'cost_peer': cost_rule(row.amount_z,row.peer_group_key,int(row.peer_size),row.ACTUAL_AMOUNT),
                   'missing_evidence': missing_rule(row.image_count)}
        feature = deviations.loc[i].abs().idxmax()
        signals['anomaly'] = {'flag': bool(row.anomaly_raw>0), 'raw': float(row.anomaly_raw),
                              'score': float(row.anomaly_score),
                              'reason': f'This work is a statistical outlier compared to peers, largely due to its {feature.replace("_z","")}.'}
        for tier in ['photo_identical','photo_similar','text_exact','text_similar']:
            n = index[row.WORK_ID][tier]
            if tier == 'photo_similar':
                reason = (f'{n} linked evidence pairs: visually similar, ORB + RANSAC keypoint-confirmed '
                          f'(≥{ORB_MIN_GOOD_MATCHES} good matches, ≥{ORB_MIN_INLIER_RATIO:.0%} inlier ratio).')
                u = unconfirmed_similar[row.WORK_ID]
                if u: reason += f' {u} further visually-similar candidate(s) seen but not keypoint-confirmed — shown as evidence, not counted here.'
            else:
                reason = f'{n} linked evidence pairs: '+ {'photo_identical':'identical extracted image bytes; shared templates may also match.', 'text_exact':'same normalized description for this MP across fiscal years.', 'text_similar':'description similarity above 90% for this MP across fiscal years.'}[tier]
            signals[tier] = {'flag': n>0,'raw':n,'score':float(n>0),'reason': reason}
        mp_key = (str(row.MP_NAME).strip().upper(), int(row.fy_start_year)) if pd.notna(row.fy_start_year) else None
        signals['entitlement_pace'] = entitlement_rule((entitlement or {}).get(mp_key), row.MP_NAME,
                                                          int(row.fy_start_year) if pd.notna(row.fy_start_year) else None)
        # Evidence has the most weight; missing_evidence/entitlement_pace are weak
        # advisory cues (entitlement_pace deliberately low — see entitlement_rule
        # for why a single-year total above the nominal cap isn't proof of anything
        # by itself). Floors preserve strong-match visibility. round_amount was
        # removed (see docs/DECISIONS.md) — it was a bare heuristic with no
        # statistical or regulatory basis, never validated by the injection
        # harness, and round sanctioned amounts are routine in government
        # budgeting for entirely legitimate reasons.
        weights = dict(cost_peer=15, missing_evidence=5, anomaly=15, photo_identical=25,
                        photo_similar=10, text_exact=20, text_similar=5, entitlement_pace=5)
        risk = round(min(sum(weights[k]*v['score'] for k,v in signals.items()), 100), 2)
        band = ('Critical' if signals['photo_identical']['flag'] or signals['text_exact']['flag'] or risk>80
                else 'High' if risk>60 else 'Moderate' if risk>30 else 'Low')
        signals_out.append(json.dumps(signals, ensure_ascii=False)); risks.append(risk); bands.append(band)
        standard_out.append(json.dumps(standardize_fraud_signals(row, signals, unconfirmed_similar[row.WORK_ID],
                                                                   photo_classification_by_work.get(row.WORK_ID)), ensure_ascii=False))
    df['signals_json'],df['risk_score'],df['severity_band'] = signals_out,risks,bands
    df['standard_signals_json'] = standard_out
    df['review_notice'] = NOTICE
    return df

def personas(df):
    mp = df.groupby(['MP_NAME','CONSTITUENCY']).size().idxmax()
    state = df.STATE_NAME.value_counts().index[0]
    cluster = df[df.STATE_NAME.eq(state)].CONSTITUENCY.value_counts().head(3).index.tolist()
    return [dict(id='mp_office',role='MP Office',label=mp[0],jurisdiction_summary=mp[1],filter={'MP_NAME':[mp[0]],'CONSTITUENCY':[mp[1]]}),
            dict(id='district_authority',role='District Authority',label='Constituency cluster',jurisdiction_summary=f'{", ".join(cluster)} · {state}. Demo grouping, not an official district boundary.',filter={'STATE_NAME':[state],'CONSTITUENCY':cluster}),
            dict(id='state_nodal',role='State Nodal Authority',label=state,jurisdiction_summary=f'All loaded works in {state}',filter={'STATE_NAME':[state]}),
            dict(id='ministry',role='Ministry',label='Loaded corpus',jurisdiction_summary=f'{df.STATE_NAME.nunique()} states · {df[["STATE_NAME","CONSTITUENCY"]].drop_duplicates().shape[0]} constituencies. Partial coverage.',filter={})]

def main():
    default_root=ROOT/'mplads_india'
    # This copied workspace has attachment folders but its CSVs remain in the original sibling.
    if not any(default_root.rglob('works_with_images.csv')) and (ROOT.parent/'sih/mplads_india').exists():
        default_root=ROOT.parent/'sih/mplads_india'
    parser = argparse.ArgumentParser(); parser.add_argument('--root',default=os.environ.get('NAZAR_DATA_ROOT',str(default_root)))
    args=parser.parse_args(); df=load_corpus(args.root)
    DATA.mkdir(exist_ok=True)
    print(f'Loaded {len(df)} real works',flush=True)

    # The sanctioned-table join (works_sanctioned.csv, via pipelines.ingest — same
    # code the canonical CSV snapshot uses) is what makes the entitlement_pace
    # signal and the whole inefficiency engine possible: it's the only place
    # RECOMMENDATION_DATE / SANCTION_DATE / SANCTION_AMOUNT and sanctioned-but-not-
    # yet-completed works exist. Optional — degrades to "no data" if it's missing.
    universe = None
    try:
        universe, ingest_summary = build_works(Path(args.root))
        print(f'Sanctioned-table join: {ingest_summary["sanctioned_rows"]} sanctioned records '
              f'({ingest_summary["sanctioned_only_rows"]} not yet completed)', flush=True)
        # Data-quality alerts and field lineage — same build_works call the
        # canonical CSV snapshot (pipelines/ingest.py) uses, so the backend's
        # /quality endpoints see exactly what fed entitlement/inefficiency too.
        write_json(DATA/'quality_alerts.json', ingest_summary['quality_alerts'])
        write_json(DATA/'lineage.json', ingest_summary['lineage'])
        write_json(DATA/'work_directory.json', ingest_summary['work_directory'])
        write_json(ROOT/'reports/quality.json', {'run_timestamp': ingest_summary['run_timestamp'],
                    'detector_version': (ingest_summary['quality_alerts'][0]['detector_version']
                                          if ingest_summary['quality_alerts'] else None),
                    'alert_counts': ingest_summary['quality_alert_counts'],
                    'total_alerts': len(ingest_summary['quality_alerts'])})
        print(f"Data quality: {len(ingest_summary['quality_alerts'])} alerts "
              f"({ingest_summary['quality_alert_counts']})", flush=True)
    except (ValueError, FileNotFoundError) as exc:
        print(f'Sanctioned-table join unavailable ({exc}); entitlement_pace, /inefficiency and /quality will show no data.', flush=True)
        write_json(DATA/'quality_alerts.json', [])
        write_json(DATA/'lineage.json', {})
        write_json(DATA/'work_directory.json', {})
    entitlement = entitlement_totals(universe)

    images, errors=extract_images(df); print(f'Extracted {len(images)} attachments; {len(errors)} failures',flush=True)
    inventory = build_image_inventory(images, errors)
    write_json(ROOT/'reports/image_inventory.json', inventory)
    print(f'Image inventory: {inventory["decodable_files"]} decodable, {inventory["invalid_or_missing_files"]} invalid, '
          f'{inventory["exact_duplicate_image_groups"]} exact-duplicate groups, {inventory["below_minimum_dimension_count"]} '
          f'below-minimum-dimension (watermark-shaped)', flush=True)
    pairs,image_matches,stats=photo_duplicates(images)
    print(json.dumps({k:(len(v) if k in ('suppressed_common_components','tier1_watermark_groups') else v)
                       for k,v in stats.items()}),flush=True)
    write_json(DATA/'image_matches.json', image_matches)
    pairs += text_duplicates(df); print(f'{len(pairs)} total evidence pairs',flush=True)
    scored=score_works(df,pairs,entitlement)
    scored.to_parquet(DATA/'scored_works.parquet',index=False)
    write_json(DATA/'duplicate_pairs.json',pairs); write_json(DATA/'personas.json',personas(df)); write_json(DATA/'images.json',images)
    stats.update(corpus_size=len(df),source_root=str(Path(args.root).resolve()),run_date=datetime.now(timezone.utc).isoformat(),extraction_errors=errors,
                 missing_evidence_fraction=float(df.image_count.eq(0).mean()),peer_sizes=scored.groupby('peer_group_key').peer_size.first().describe().to_dict())
    write_json(ROOT/'reports/pipeline.json',stats)
    print(f'Peer sizes: {stats["peer_sizes"]}; missing evidence: {stats["missing_evidence_fraction"]:.1%}',flush=True)

    # Case consolidation (Phase 3): a fixed, recorded as_of_date - never an
    # unstated "now" buried inside a detector - carried through inefficiency
    # AND into every case's audit trail below.
    as_of_date = pd.Timestamp.now().normalize()
    inefficiency_findings = []
    if universe is not None:
        inefficiency_findings, ineff_stats = build_inefficiency(universe, as_of_date)
        write_json(DATA/'inefficiency.json', inefficiency_findings)
        write_json(ROOT/'reports/inefficiency.json', ineff_stats)
        print(f'Inefficiency: {ineff_stats["long_open_flagged"]} long-open / {ineff_stats["long_open_candidates"]} candidates '
              f'({ineff_stats["long_open_insufficient_peers"]} insufficient-peer), '
              f'{ineff_stats["late_sanction_flagged"]} late-sanctioned / {ineff_stats["late_sanction_candidates"]} '
              f'({ineff_stats["late_sanction_fraction"]:.1%})', flush=True)
    else:
        write_json(DATA/'inefficiency.json', [])

    quality_severities_by_work = defaultdict(list)
    for a in (ingest_summary['quality_alerts'] if universe is not None else []):
        if a['work_id']: quality_severities_by_work[a['work_id']].append(a['severity'])
    signals_by_work = defaultdict(list)
    context_by_work = {}
    for row in scored.itertuples():
        signals_by_work[row.WORK_ID].extend(json.loads(row.standard_signals_json))
        context_by_work[row.WORK_ID] = {'work_description': row.WORK_DESCRIPTION, 'mp_name': row.MP_NAME,
                                          'state_name': row.STATE_NAME, 'constituency': row.CONSTITUENCY,
                                          'work_category': getattr(row, 'WORK_CATEGORY', None),
                                          'actual_amount': None if pd.isna(row.ACTUAL_AMOUNT) else float(row.ACTUAL_AMOUNT)}
    for finding in inefficiency_findings:
        if not finding['WORK_ID']: continue
        signals_by_work[finding['WORK_ID']].extend(standardize_inefficiency_signals(finding))
        context_by_work.setdefault(finding['WORK_ID'], {'work_description': finding['WORK_DESCRIPTION'],
                                                          'mp_name': finding['MP_NAME'], 'state_name': finding['STATE_NAME'],
                                                          'constituency': finding['CONSTITUENCY'], 'work_category': None,
                                                          'actual_amount': None})
    case_candidates = [c for wid, sigs in signals_by_work.items()
                       for c in [build_case_candidate(wid, sigs, context=context_by_work[wid],
                                                       quality_alert_severities=quality_severities_by_work.get(wid, []))]
                       if c is not None]
    write_json(DATA/'case_candidates.json', case_candidates)
    print(f'Case consolidation: {sum(len(v) for v in signals_by_work.values())} raw signal instances across '
          f'{len(signals_by_work)} works -> {len(case_candidates)} reviewable cases', flush=True)

if __name__=='__main__': main()
