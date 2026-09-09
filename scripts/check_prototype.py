"""Lightweight reproducible smoke checks; no test framework or shipping test records."""
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.pipeline import DATA,ROOT,cost_rule,missing_rule,round_rule,photo_duplicates,phash
from PIL import Image,ImageDraw,ImageOps

def main():
    assert missing_rule(0)['flag'] and not missing_rule(1)['flag']
    assert cost_rule(3,'test peer group',10,100000)['flag']
    assert round_rule(200000)['flag'] and not round_rule(0)['flag']
    assert not round_rule(250000)['flag']
    assert len(phash(Image.new('RGB',(200,200),'white')))==16
    a={'work_id':'a','md5':'a','filename':'a.jpg','width':140,'height':400,'phash':'00'*8}
    b={**a,'work_id':'b','md5':'b'}
    matches,_=photo_duplicates([a,b]); assert not matches
    common=[{**a,'work_id':str(i),'md5':str(i),'width':400} for i in range(7)]
    matches,stats=photo_duplicates(common); assert not matches and len(stats['suppressed_common_components'])==1
    with tempfile.TemporaryDirectory() as temp:
        os.environ['NAZAR_DB_PATH']=str(Path(temp)/'reviews.sqlite3')
        from fastapi.testclient import TestClient
        from backend.main import app,DEFAULT_USERS
        def auth(client,persona_id):
            uid,pw=DEFAULT_USERS[persona_id]
            response=client.post('/auth/login',json={'user_id':uid,'password':pw}); assert response.status_code==200
            body=response.json(); assert body['persona']['id']==persona_id
            return {'Authorization':f'Bearer {body["token"]}'}
        with TestClient(app) as client:
            personas=client.get('/personas').json(); assert len(personas)==4
            assert client.get('/works').status_code==401                                    # no token
            assert client.get('/works',headers={'Authorization':'Bearer not.a.token'}).status_code==401
            assert client.post('/auth/login',json={'user_id':'nobody','password':'wrong'}).status_code==401
            counts={}
            for p in personas:
                headers=auth(client,p['id'])
                response=client.get('/works',headers=headers); assert response.status_code==200
                body=response.json(); counts[p['id']]=body['total']
                for row in body['items']:
                    assert all(row[k] in values for k,values in p['filter'].items())
                summary=client.get('/summary',headers=headers).json()
                assert summary['total']==body['total']==sum(summary['severity'].values())
            assert len(set(counts.values()))==4
            ministry=auth(client,'ministry')
            # Signal filter: /works?signal=<key> keeps only works whose that signal fired.
            signals=client.get('/signals',headers=ministry).json(); assert len(signals)==8
            flagged_signal=next(s['key'] for s in signals if 0<s['flagged']<client.get('/works',headers=ministry).json()['total'])
            filtered=client.get(f'/works?signal={flagged_signal}&limit=200',headers=ministry).json()
            assert filtered['total']==next(s['flagged'] for s in signals if s['key']==flagged_signal)
            sample=client.get(f'/works/{filtered["items"][0]["WORK_ID"]}',headers=ministry).json()
            assert sample['signals'][flagged_signal]['flag']
            assert client.get('/works?signal=not_a_signal',headers=ministry).status_code==422
            wid=client.get('/works',headers=ministry).json()['items'][0]['WORK_ID']
            assert client.get(f'/works/{wid}',headers=ministry).status_code==200
            assert client.get(f'/works/{wid}').status_code==401
            assert client.get(f'/works/{wid}/duplicates',headers=ministry).status_code==200
            # A narrower persona cannot reach a work outside its jurisdiction.
            assert client.get(f'/works/{wid}',headers=auth(client,'mp_office')).status_code==404
            image=json.loads((DATA/'images.json').read_text(encoding='utf-8'))[0]
            response=client.get(f'/image/{image["work_id"]}/{image["filename"]}'); assert response.status_code==200 and response.headers['content-type']=='image/jpeg'
            for decision in ['Confirm','Dismiss']:
                response=client.post('/investigations',headers=ministry,json={'work_id':wid,'decision':decision,'reason':'Automated local persistence check; no substantive assessment.'})
                assert response.status_code==200
                assert client.get(f'/works/{wid}',headers=ministry).json()['investigations'][0]['decision']==decision
            assert client.post('/investigations',headers=ministry,json={'work_id':wid,'decision':'Confirm','reason':' '}).status_code==422
            assert client.post('/investigations',json={'work_id':wid,'decision':'Confirm','reason':'x'}).status_code==401
            assert client.get('/works/no-such-work',headers=ministry).status_code==404
            assert client.get('/works?severity=invalid',headers=ministry).status_code==422
            assert client.get('/image/unknown/unknown.jpg').status_code==404
            ev=client.get('/evaluation'); assert ev.status_code==200 and len(ev.json()['patterns'])==3
            assert client.get('/').status_code==200
        # A fresh app lifespan must reload the same SQLite record.
        with TestClient(app) as client:
            assert client.get(f'/works/{wid}',headers=auth(client,'ministry')).json()['investigations'][0]['decision']=='Dismiss'
    print('All endpoint, scope, gating, input validation, static frontend and SQLite restart checks passed.')
    print(json.dumps(counts))
    pairs=json.loads((DATA/'duplicate_pairs.json').read_text(encoding='utf-8'))
    qa=ROOT/'reports/visual_qa'; qa.mkdir(parents=True,exist_ok=True)
    for tier in ['photo_identical','photo_similar']:
        chosen=[]; seen=set()
        for p in pairs:
            if p['tier']==tier and not set(p['work_ids']) & seen:
                chosen.append(p); seen.update(p['work_ids'])
            if len(chosen)==5: break
        canvas=Image.new('RGB',(1000,430*len(chosen)), '#edf1e7'); draw=ImageDraw.Draw(canvas)
        for row,p in enumerate(chosen):
            for col,item in enumerate(p['images']):
                with Image.open(DATA/'image_cache'/item['filename']) as original:
                    thumbnail=ImageOps.contain(original,(485,385))
                    canvas.paste(thumbnail,(col*500+(500-thumbnail.width)//2,row*430+35))
                draw.text((col*500+12,row*430+10),f'{tier} | work {item["work_id"]} | {item["width"]}x{item["height"]}',fill='black')
        canvas.save(qa/f'{tier}.jpg')
        print(f'Visual QA: {qa/tier}.jpg')

if __name__=='__main__': main()
