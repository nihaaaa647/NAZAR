"""Read-only corpus scoring. All thresholds are review heuristics, not legal rules."""
from __future__ import annotations
import argparse, hashlib, io, itertools, json, os, re, sys
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
from scipy.fftpack import dct
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.consolidate import parse_letter_no
DATA = ROOT / 'data'
NOTICE = 'Computational signal — needs human review.'
# Scanner-app footers ("Scanned with OKEN Scanner", CamScanner logo) are short wide
# strips well below this floor. They repeat byte-for-byte across unrelated works, so
# without this gate they dominate both photo tiers as spurious "reused image" evidence.
MIN_IMAGE_DIM = 150

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

def photo_duplicates(images):
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
    for i, j, distance in candidates:
        if len(memberships[find(i)]) > 6: continue
        for a, b in itertools.product(groups[gated[i]['md5']], groups[gated[j]['md5']]):
            if a['work_id'] != b['work_id']:
                pairs.append(pair(a, b, 'photo_similar', hamming_distance=distance))
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
             'threshold_reason': 'Half the measured lower 1% Hamming distance, constrained to 2–6; heuristic, not proof.'}
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

def cost_rule(z, group, size, amount):
    return {'flag': bool(abs(z)>2.5), 'raw': float(z), 'score': min(abs(float(z))/6,1),
            'reason': f'Amount ₹{amount:,.0f} is unusually {"high" if z>0 else "low"} compared to {size} peers in {group}.'}

def missing_rule(count):
    return {'flag': bool(count == 0), 'raw': int(count), 'score': float(count == 0),
            'reason': f'{int(count)} source-listed attachments. Missing completion evidence is advisory; unavailable downloads are tracked separately.'}

def round_rule(amount):
    distance = abs(amount / 100000 - round(amount / 100000)) if np.isfinite(amount) else 1
    flag = bool(amount >= 100000 and distance <= .01)
    return {'flag': flag, 'raw': float(distance), 'score': float(flag),
            'reason': f'Amount ₹{amount:,.0f} is a suspicious round number. This is a heuristic flag with no verified legal threshold.'}

def score_works(df, pairs):
    df = df.copy()
    keys = df.activity_norm + ' | ' + df.STATE_NAME
    counts = keys.map(keys.value_counts())
    activities = df.activity_norm.map(df.activity_norm.value_counts())
    df['peer_group_key'] = np.where(counts>=10,keys,np.where(activities>=10,df.activity_norm,'Whole corpus'))
    med=pd.Series(0.,index=df.index); mad=med.copy(); peer_sizes=med.copy(); populations={}
    for key, assigned in df.groupby('peer_group_key'):
        example=assigned.iloc[0]
        eligible=(df.activity_norm.eq(example.activity_norm) & df.STATE_NAME.eq(example.STATE_NAME)) if key==example.activity_norm+' | '+example.STATE_NAME else df.activity_norm.eq(example.activity_norm) if key==example.activity_norm else pd.Series(True,index=df.index)
        populations[key]=eligible
        amounts=df.loc[eligible,'ACTUAL_AMOUNT']; median=amounts.median()
        med.loc[assigned.index]=median; mad.loc[assigned.index]=(amounts-median).abs().median(); peer_sizes.loc[assigned.index]=int(eligible.sum())
    # Zero MAD: use a 10% median scale to avoid zero/infinite deviations on constant peers.
    scale = (1.4826*mad).where(mad>0,med.abs().mul(.1).clip(lower=1))
    df['amount_z'] = ((df.ACTUAL_AMOUNT-med)/scale).fillna(0)
    df['cost_per_unit_z'] = df.amount_z
    df['peer_size'] = peer_sizes.astype(int)
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
    index = defaultdict(lambda: defaultdict(int))
    for p in pairs:
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
            signals[tier] = {'flag': n>0,'raw':n,'score':float(n>0),
                             'reason': f'{n} linked evidence pairs: '+ {'photo_identical':'identical extracted image bytes; shared templates may also match.', 'photo_similar':'visually similar images after size and common-template gates; inspect manually.', 'text_exact':'same normalized description for this MP across fiscal years.', 'text_similar':'description similarity above 90% for this MP across fiscal years.'}[tier]}
        # Evidence has most weight; missing/round signals are weak advisory cues. Floors preserve strong-match visibility.
        weights = dict(cost_peer=15, missing_evidence=5, round_amount=5, anomaly=15, photo_identical=25, photo_similar=10, text_exact=20, text_similar=5)
        risk = round(sum(weights[k]*v['score'] for k,v in signals.items()),2)
        band = 'Critical' if signals['photo_identical']['flag'] or signals['text_exact']['flag'] or risk>80 else 'High' if risk>60 else 'Moderate' if risk>30 else 'Low'
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
    images, errors=extract_images(df); print(f'Extracted {len(images)} attachments; {len(errors)} failures',flush=True)
    pairs,stats=photo_duplicates(images)
    print(json.dumps({k:(len(v) if k in ('suppressed_common_components','tier1_watermark_groups') else v)
                       for k,v in stats.items()}),flush=True)
    pairs += text_duplicates(df); print(f'{len(pairs)} total evidence pairs',flush=True)
    scored=score_works(df,pairs)
    scored.to_parquet(DATA/'scored_works.parquet',index=False)
    write_json(DATA/'duplicate_pairs.json',pairs); write_json(DATA/'personas.json',personas(df)); write_json(DATA/'images.json',images)
    stats.update(corpus_size=len(df),source_root=str(Path(args.root).resolve()),run_date=datetime.now(timezone.utc).isoformat(),extraction_errors=errors,
                 missing_evidence_fraction=float(df.image_count.eq(0).mean()),peer_sizes=scored.groupby('peer_group_key').peer_size.first().describe().to_dict())
    write_json(ROOT/'reports/pipeline.json',stats)
    print(f'Peer sizes: {stats["peer_sizes"]}; missing evidence: {stats["missing_evidence_fraction"]:.1%}',flush=True)

if __name__=='__main__': main()
