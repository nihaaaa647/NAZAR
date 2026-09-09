"""Synthetic sensitivity check. Injected rows never enter the shipping dataset."""
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.pipeline import DATA,ROOT,extract_images,is_photo_evidence,photo_duplicates,text_duplicates,score_works,write_json

def main():
    baseline=pd.read_parquet(DATA/'scored_works.parquet')
    images=json.loads((DATA/'images.json').read_text(encoding='utf-8'))
    rng=np.random.default_rng(42)
    synthetic=[]; image_caught=0; text_caught=0; missing_caught=0; anomaly_caught=0
    # Seed image-reuse trials only from real completion photos, not scanner-app
    # watermark strips — those are gated out of the detector by design.
    photo_by_work={}
    for x in images:
        if is_photo_evidence(x): photo_by_work.setdefault(x['work_id'],x)
    image_rows=baseline[baseline.WORK_ID.isin(photo_by_work)]
    text_rows=baseline[baseline.description_norm.ne('') & baseline.fy_start_year.notna()]
    trials=min(10,len(image_rows),len(text_rows),len(baseline))
    if not trials: raise ValueError('Insufficient real seed rows for validation')
    target=ROOT/'reports/synthetic'; target.mkdir(parents=True,exist_ok=True)
    # Reuse actual detector functions on isolated baseline+injection trials.
    for i in range(trials):
        source=image_rows.iloc[int(rng.integers(len(image_rows)))].copy()
        original=photo_by_work[source.WORK_ID]
        source['WORK_ID']=f'SYNTH-IMAGE-{i}'; source['is_synthetic']=True; source['pattern']='Image reuse'
        copied=target/f'{source.WORK_ID}.jpg'; copied.write_bytes((DATA/'image_cache'/original['filename']).read_bytes())
        source['local_image_filenames']=copied.name; source['_source_csv']=str(target/'injected_works.csv'); source['image_count']=1
        extracted,errors=extract_images(pd.DataFrame([source]),cache=target/'image_cache')
        assert not errors and len(extracted)==1
        injection=extracted[0]
        found,_=photo_duplicates([original,injection]); image_caught+=any(p['tier']=='photo_identical' and source.WORK_ID in p['work_ids'] for p in found)
        synthetic.append(source)
        source=text_rows.iloc[int(rng.integers(len(text_rows)))].copy(); orig=source.copy()
        source['WORK_ID']=f'SYNTH-TEXT-{i}'; source['is_synthetic']=True; source['pattern']='Cross-year duplicate claim'
        source['fy_start_year']+=1; source['ACTUAL_AMOUNT']*=1+float(rng.choice([-1,1])*rng.uniform(.05,.1))
        found=text_duplicates(pd.DataFrame([orig,source]),near=False)
        text_caught+=any(p['tier']=='text_exact' and source.WORK_ID in p['work_ids'] for p in found); synthetic.append(source)
        source=baseline.iloc[int(rng.integers(len(baseline)))].copy()
        peers=baseline[baseline.peer_group_key.eq(source.peer_group_key)]
        source['WORK_ID']=f'SYNTH-PHANTOM-{i}'; source['is_synthetic']=True; source['pattern']='High amount, no evidence'
        source['ACTUAL_AMOUNT']=max(float(peers.ACTUAL_AMOUNT.max())*5,1000000)
        source['image_count']=0; source['local_image_filenames']=''; synthetic.append(source)
    injected=pd.DataFrame(synthetic)
    # Remove baseline-derived scores; score_works recalculates peers and forest on the augmented evaluation copy.
    augmented=pd.concat([baseline,injected[injected.pattern.eq('High amount, no evidence')]],ignore_index=True)
    scored=score_works(augmented,[])
    for row in scored[scored.is_synthetic].to_dict('records'):
        sig=json.loads(row['signals_json']); missing_caught+=sig['missing_evidence']['flag']; anomaly_caught+=sig['anomaly']['flag']
    # Keep only source/injection values, never misleading stale baseline scores.
    injected.drop(columns=['signals_json','risk_score','severity_band','anomaly_raw','anomaly_score','amount_z','cost_per_unit_z','peer_size','peer_group_key'],errors='ignore').to_parquet(target/'injected_works.parquet',index=False)
    patterns=[{'name':'Image reuse','detector':'Byte-identical extracted image matching','caught':image_caught,'trials':trials,'recall':image_caught/trials},
              {'name':'Cross-year duplicate claim','detector':'Exact normalized cross-year description matching','caught':text_caught,'trials':trials,'recall':text_caught/trials},
              {'name':'High amount, no evidence','detector':'Missing evidence advisory','caught':missing_caught,'trials':trials,'recall':missing_caught/trials,'anomaly_caught':anomaly_caught,'anomaly_recall':anomaly_caught/trials}]
    report={'run_date':datetime.now(timezone.utc).isoformat(),'corpus_size':len(baseline),'seed':42,'patterns':patterns,
            'limitations':'Synthetic sensitivity only; not real-world precision, a fraud finding, or pHash validation. Missing-evidence recall is expected by construction. Ten trials per pattern; the anomaly model is refit on a separate augmented copy.'}
    write_json(ROOT/'reports/evaluation.json',report)
    lines=['# NAZAR injection validation',f'Run: {report["run_date"]}',f'Real corpus: {len(baseline):,} works. Seed: 42.', '', '| Pattern | Caught / trials | Recall | Detector |','|---|---:|---:|---|']
    for p in patterns: lines.append(f'| {p["name"]} | {p["caught"]}/{p["trials"]} | {p["recall"]:.0%} | {p["detector"]} |')
    lines.extend(['',f'High-amount/no-evidence Isolation Forest recall: {anomaly_caught}/{trials} ({anomaly_caught/trials:.0%}).',report['limitations'],'All injected rows and copied attachments are isolated under reports/synthetic/.'])
    (ROOT/'reports/evaluation.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
