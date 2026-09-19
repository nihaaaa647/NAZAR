"""Read-only corpus scoring. All thresholds are review heuristics, not legal rules."""
from __future__ import annotations
import argparse, hashlib, io, itertools, json, os, re, sys
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import cv2
import numpy as np
import pandas as pd
from PIL import Image
from scipy.fftpack import dct
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.consolidate import parse_letter_no
from pipelines.ingest import build_works
DATA = ROOT / 'data'
NOTICE = 'Computational signal — needs human review.'
# Scanner-app footers ("Scanned with OKEN Scanner", CamScanner logo) are short wide
# strips well below this floor. They repeat byte-for-byte across unrelated works, so
# without this gate they dominate both photo tiers as spurious "reused image" evidence.
MIN_IMAGE_DIM = 150
# Sourced MPLADS Guidelines 2023 thresholds (mplads.gov.in "Pocket Book on MPLADS
# Guidelines"; PIB release on the Revised MPLADS Guidelines 2023) — not heuristics.
# See astra/FINDINGS_TO_VERIFY.md F7 and docs/DECISIONS.md for what was checked
# and why the trust/society ceiling and outside-constituency cap are NOT included
# here: this corpus can only partially link IDA entity type and MP home district,
# and a wrong "sourced" flag is worse than no flag.
MPLADS_ENTITLEMENT_PER_FY = 5_00_00_000  # Rs 5 crore per MP per fiscal year, released as two Rs 2.5 crore installments.
SANCTION_DEADLINE_DAYS = 75              # works must be sanctioned within 75 days of receipt of recommendation.
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
# candidates confirmed. See docs/DECISIONS.md (2026-09-19).
ORB_MIN_GOOD_MATCHES = 100
ORB_MIN_INLIER_RATIO = 0.2
ORB_RATIO_TEST = 0.75  # Lowe's ratio test on the two nearest descriptor matches.

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
    df['ACTUAL_AMOUNT'] = pd.to_numeric(df.ACTUAL_AMOUNT, errors='coerce')
    df['image_count'] = pd.to_numeric(df.image_count, errors='coerce').fillna(0)
    df['actual_end_date'] = pd.to_datetime(df.ACTUAL_END_DATE, format='%d-%b-%Y', errors='coerce').dt.strftime('%Y-%m-%d').fillna('')
    df['is_synthetic'] = False
    return df

def jpeg_from_pdf(raw):
    i, j = raw.find(b'\xff\xd8\xff'), raw.rfind(b'\xff\xd9')
    return raw[i:j+2] if i >= 0 and j > i else None

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
                errors.append({'file': name, 'error': 'Outside source directory'}); continue
            try:
                stat = path.stat()
                key = str(path)
                stamp = [stat.st_size, stat.st_mtime_ns]
                item = old.get(key)
                if not item or item['stamp'] != stamp or not (cache / item['filename']).exists():
                    raw = path.read_bytes()
                    jpeg = jpeg_from_pdf(raw) if raw.startswith(b'%PDF') else raw
                    if not jpeg: raise ValueError('No embedded JPEG found')
                    with Image.open(io.BytesIO(jpeg)) as img:
                        img.load()
                        digest = hashlib.md5(jpeg).hexdigest()
                        item = {'stamp': stamp, 'filename': digest + '.jpg', 'md5': digest,
                                'width': img.width, 'height': img.height, 'phash': phash(img)}
                    (cache / item['filename']).write_bytes(jpeg)
                manifest[key] = item
                images.append({**item, 'work_id': str(row['WORK_ID']), 'source_filename': name.strip()})
            except (OSError, ValueError) as exc:
                errors.append({'file': str(path), 'error': str(exc)})
    write_json(manifest_path, manifest)
    return images, errors

def keypoint_confirm(path_a, path_b):
    """ORB descriptor matching + RANSAC homography, distinguishing a genuinely
    matched photo/document (the same scene or page, re-saved/cropped/recompressed)
    from two images that only look alike at pHash's coarse 8x8-DCT resolution —
    e.g. two different measurement-book pages on the same printed form. Returns
    a dict with the raw evidence even when unconfirmed, so an unconfirmed pair
    can still show its numbers rather than a bare no."""
    img_a = cv2.imread(str(path_a), cv2.IMREAD_GRAYSCALE)
    img_b = cv2.imread(str(path_b), cv2.IMREAD_GRAYSCALE)
    empty = {'good_matches': 0, 'inliers': 0, 'inlier_ratio': 0.0, 'confirmed': False}
    if img_a is None or img_b is None: return empty
    orb = cv2.ORB_create(nfeatures=1500)
    kp_a, des_a = orb.detectAndCompute(img_a, None)
    kp_b, des_b = orb.detectAndCompute(img_b, None)
    if des_a is None or des_b is None or len(kp_a) < 10 or len(kp_b) < 10: return empty
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(des_a, des_b, k=2)
    good = [m for m, n in (pair for pair in matches if len(pair) == 2) if m.distance < ORB_RATIO_TEST * n.distance]
    if len(good) < 4: return {**empty, 'good_matches': len(good)}
    src = np.float32([kp_a[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_b[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    inliers = int(mask.sum()) if mask is not None else 0
    inlier_ratio = inliers / len(good)
    confirmed = len(good) >= ORB_MIN_GOOD_MATCHES and inlier_ratio >= ORB_MIN_INLIER_RATIO
    return {'good_matches': len(good), 'inliers': inliers, 'inlier_ratio': round(inlier_ratio, 3), 'confirmed': confirmed}

def photo_duplicates(images, image_dir=DATA / 'image_cache'):
    pairs, groups = [], defaultdict(list)
    for item in images: groups[item['md5']].append(item)
    def pair(a, b, tier, **extra):
        return {'tier': tier, 'work_ids': [a['work_id'], b['work_id']], 'images': [a, b], **extra}
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
        pairs.extend(pair(a, b, 'photo_identical') for a, b in itertools.combinations(values, 2))
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
    keypoint_evaluated = keypoint_confirmed_groups = 0
    for i, j, distance in candidates:
        if len(memberships[find(i)]) > 6: continue
        # One ORB pass per unique image pair, not per expanded work pair — several
        # work_ids can share the same underlying MD5-deduped image on either side.
        confirmation = keypoint_confirm(image_dir / gated[i]['filename'], image_dir / gated[j]['filename'])
        keypoint_evaluated += 1
        if confirmation['confirmed']: keypoint_confirmed_groups += 1
        for a, b in itertools.product(groups[gated[i]['md5']], groups[gated[j]['md5']]):
            if a['work_id'] != b['work_id']:
                pairs.append(pair(a, b, 'photo_similar', hamming_distance=distance,
                                   keypoint_confirmed=confirmation['confirmed'],
                                   keypoint_good_matches=confirmation['good_matches'],
                                   keypoint_inliers=confirmation['inliers'],
                                   keypoint_inlier_ratio=confirmation['inlier_ratio']))
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
             'threshold_reason': 'Half the measured lower 1% Hamming distance, constrained to 2–6; heuristic, not proof.',
             'tier3_unique_image_pairs_evaluated': keypoint_evaluated,
             'tier3_keypoint_confirmed_pairs': keypoint_confirmed_groups,
             'tier3_method': f'ORB (nfeatures=1500) + Lowe ratio test ({ORB_RATIO_TEST}) + RANSAC homography; '
                              f'confirmed if good_matches>={ORB_MIN_GOOD_MATCHES} and inlier_ratio>={ORB_MIN_INLIER_RATIO} '
                              f'— both thresholds measured against a 60-pair random negative control, see docs/DECISIONS.md.'}
    return pairs, stats

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
    cost-peer rule and the idle-funds duration check — same fallback ladder, same
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

def round_rule(amount):
    distance = abs(amount / 100000 - round(amount / 100000)) if np.isfinite(amount) else 1
    flag = bool(amount >= 100000 and distance <= .01)
    return {'flag': flag, 'raw': float(distance), 'score': float(flag),
            'reason': f'Amount ₹{amount:,.0f} is a suspicious round number. This is a heuristic flag with no verified legal threshold.'}

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

def idle_funds_signal(universe, run_date):
    """Works sanctioned but with no completed record yet, held open unusually long
    versus their activity x state peers. Disjoint by construction from the
    fraud-scored completed corpus — every row here has no completed record."""
    idle = universe[~universe.has_completed_record & universe.has_sanctioned_record].copy()
    idle = idle.dropna(subset=['sanction_date', 'activity_norm', 'state_name'])
    idle['days_since_sanction'] = (run_date - idle.sanction_date).dt.days
    z, group_key, sizes, _ = peer_z(idle, 'days_since_sanction', 'activity_norm', 'state_name')
    idle['duration_z'], idle['peer_group_key'], idle['peer_size'] = z, group_key, sizes
    idle['flag'] = idle.duration_z > 2.5
    return idle

def late_sanction_signal(universe):
    """Recommendation-to-sanction gap versus the sourced 75-day guideline. Applies
    to every sanctioned record regardless of completion status."""
    late = universe.dropna(subset=['recommendation_date', 'sanction_date']).copy()
    late['sanction_lag_days'] = (late.sanction_date - late.recommendation_date).dt.days
    late['flag'] = late.sanction_lag_days > SANCTION_DEADLINE_DAYS
    return late

def build_inefficiency(universe, run_date):
    """Inefficiency findings — kept entirely separate from the fraud signals_json /
    risk_score / severity_band: a different artifact, a different population (this
    includes 6,000+ sanctioned-but-not-completed works the fraud corpus never
    sees), no shared weighting, no shared severity language."""
    idle = idle_funds_signal(universe, run_date)
    late = late_sanction_signal(universe)
    merged = (universe
              .merge(idle[['record_id', 'days_since_sanction', 'duration_z', 'peer_group_key', 'peer_size', 'flag']]
                     .rename(columns={'peer_group_key': 'idle_peer_group', 'peer_size': 'idle_peer_size', 'flag': 'idle_flag'}),
                     on='record_id', how='left')
              .merge(late[['record_id', 'sanction_lag_days', 'flag']].rename(columns={'flag': 'late_flag'}),
                     on='record_id', how='left'))
    merged['idle_flag'] = merged.idle_flag.fillna(False)
    merged['late_flag'] = merged.late_flag.fillna(False)
    flagged = merged[merged.idle_flag | merged.late_flag].copy()
    flagged = flagged.sort_values(['idle_flag', 'days_since_sanction', 'late_flag', 'sanction_lag_days'],
                                   ascending=False, na_position='last')

    def row_to_finding(r):
        idle_block = None
        if pd.notna(r.days_since_sanction):
            idle_block = {'flag': bool(r.idle_flag), 'days_since_sanction': int(r.days_since_sanction),
                           'peer_group': r.idle_peer_group, 'peer_size': int(r.idle_peer_size),
                           'reason': (f'Sanctioned {int(r.days_since_sanction)} days ago with no completion record yet — '
                                      f'unusually long versus {int(r.idle_peer_size)} peers in {r.idle_peer_group}.'
                                      if r.idle_flag else
                                      f'Sanctioned {int(r.days_since_sanction)} days ago with no completion record yet; '
                                      f'within the usual range for {int(r.idle_peer_size)} peers in {r.idle_peer_group}.')}
        late_block = None
        if pd.notna(r.sanction_lag_days):
            over = int(r.sanction_lag_days) - SANCTION_DEADLINE_DAYS
            late_block = {'flag': bool(r.late_flag), 'sanction_lag_days': int(r.sanction_lag_days),
                          'reason': (f'Sanctioned {int(r.sanction_lag_days)} days after the recommendation was received — '
                                     f'exceeds the MPLADS Guidelines 2023 {SANCTION_DEADLINE_DAYS}-day sanctioning window by {over} days.'
                                     if r.late_flag else
                                     f'Sanctioned {int(r.sanction_lag_days)} days after recommendation — within the '
                                     f'{SANCTION_DEADLINE_DAYS}-day window.')}
        text = lambda v: None if pd.isna(v) else str(v)
        return {'RECORD_ID': str(r.record_id), 'WORK_ID': text(r.work_id),
                'MP_NAME': text(r.mp_name), 'CONSTITUENCY': text(r.constituency), 'STATE_NAME': text(r.state_name),
                'ACTIVITY_NAME': text(r.activity_name), 'WORK_DESCRIPTION': text(r.work_description),
                'is_completed': bool(r.has_completed_record),
                'sanction_amount': None if pd.isna(r.sanction_amount) else float(r.sanction_amount),
                'sanction_date': None if pd.isna(r.sanction_date) else r.sanction_date.strftime('%Y-%m-%d'),
                'recommendation_date': None if pd.isna(r.recommendation_date) else r.recommendation_date.strftime('%Y-%m-%d'),
                'idle_funds': idle_block, 'late_sanction': late_block}

    findings = [row_to_finding(r) for r in flagged.itertuples()]
    stats = {'sanctioned_universe_rows': int(len(universe)), 'completed_rows': int(universe.has_completed_record.sum()),
             'sanctioned_only_rows': int((~universe.has_completed_record & universe.has_sanctioned_record).sum()),
             'idle_candidates': int(len(idle)), 'idle_flagged': int(idle.flag.sum()),
             'late_sanction_candidates': int(len(late)), 'late_sanction_flagged': int(late.flag.sum()),
             'late_sanction_fraction': float(late.flag.mean()) if len(late) else None,
             'sanction_deadline_days': SANCTION_DEADLINE_DAYS, 'run_date': run_date.strftime('%Y-%m-%d'),
             'source': 'MPLADS Guidelines 2023 — works must be sanctioned within 75 days of receipt of recommendation.'}
    return findings, stats

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
    for p in pairs:
        if p['tier'] == 'photo_similar' and not p.get('keypoint_confirmed'):
            for wid in set(p['work_ids']): unconfirmed_similar[wid] += 1
            continue
        for wid in set(p['work_ids']): index[wid][p['tier']] += 1
    signals_out, risks, bands = [], [], []
    for i,row in df.iterrows():
        signals = {'cost_peer': cost_rule(row.amount_z,row.peer_group_key,int(row.peer_size),row.ACTUAL_AMOUNT),
                   'missing_evidence': missing_rule(row.image_count), 'round_amount': round_rule(row.ACTUAL_AMOUNT)}
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
        # Evidence has the most weight; missing/round/entitlement_pace are weak advisory
        # cues (entitlement_pace deliberately low — see entitlement_rule for why a
        # single-year total above the nominal cap isn't proof of anything by itself).
        # Floors preserve strong-match visibility. Nominal weights sum to 105, not 100
        # — entitlement_pace was added without re-weighting the other seven (see
        # docs/DECISIONS.md); risk_score is capped at 100 below.
        weights = dict(cost_peer=15, missing_evidence=5, round_amount=5, anomaly=15, photo_identical=25,
                        photo_similar=10, text_exact=20, text_similar=5, entitlement_pace=5)
        risk = round(min(sum(weights[k]*v['score'] for k,v in signals.items()), 100), 2)
        band = ('Critical' if signals['photo_identical']['flag'] or signals['text_exact']['flag'] or risk>80
                else 'High' if risk>60 else 'Moderate' if risk>30 else 'Low')
        signals_out.append(json.dumps(signals, ensure_ascii=False)); risks.append(risk); bands.append(band)
    df['signals_json'],df['risk_score'],df['severity_band'] = signals_out,risks,bands
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
    except (ValueError, FileNotFoundError) as exc:
        print(f'Sanctioned-table join unavailable ({exc}); entitlement_pace and /inefficiency will show no data.', flush=True)
    entitlement = entitlement_totals(universe)

    images, errors=extract_images(df); print(f'Extracted {len(images)} attachments; {len(errors)} failures',flush=True)
    pairs,stats=photo_duplicates(images)
    print(json.dumps({k:(len(v) if k in ('suppressed_common_components','tier1_watermark_groups') else v)
                       for k,v in stats.items()}),flush=True)
    pairs += text_duplicates(df); print(f'{len(pairs)} total evidence pairs',flush=True)
    scored=score_works(df,pairs,entitlement)
    scored.to_parquet(DATA/'scored_works.parquet',index=False)
    write_json(DATA/'duplicate_pairs.json',pairs); write_json(DATA/'personas.json',personas(df)); write_json(DATA/'images.json',images)
    stats.update(corpus_size=len(df),source_root=str(Path(args.root).resolve()),run_date=datetime.now(timezone.utc).isoformat(),extraction_errors=errors,
                 missing_evidence_fraction=float(df.image_count.eq(0).mean()),peer_sizes=scored.groupby('peer_group_key').peer_size.first().describe().to_dict())
    write_json(ROOT/'reports/pipeline.json',stats)
    print(f'Peer sizes: {stats["peer_sizes"]}; missing evidence: {stats["missing_evidence_fraction"]:.1%}',flush=True)

    if universe is not None:
        findings, ineff_stats = build_inefficiency(universe, pd.Timestamp.now().normalize())
        write_json(DATA/'inefficiency.json', findings)
        write_json(ROOT/'reports/inefficiency.json', ineff_stats)
        print(f'Inefficiency: {ineff_stats["idle_flagged"]} idle / {ineff_stats["idle_candidates"]} candidates, '
              f'{ineff_stats["late_sanction_flagged"]} late-sanctioned / {ineff_stats["late_sanction_candidates"]} '
              f'({ineff_stats["late_sanction_fraction"]:.1%})', flush=True)
    else:
        write_json(DATA/'inefficiency.json', [])

if __name__=='__main__': main()
