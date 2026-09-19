"""NAZAR prototype. Persona scope now comes from a signed session token, not a
request parameter; the accounts are fixed demo logins, one per persona."""
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import base64, hashlib, hmac, json, os, sqlite3, time
import pandas as pd
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

NOTICE='Computational signal — needs human review.'
ROOT=Path(__file__).resolve().parents[1]
# NAZAR_DATA_DIR lets a deployment point at a data snapshot that lives outside the
# code checkout (e.g. scripts/prepare_deploy_data.py's trimmed bundle on a host
# with no room, or no need, for the full local pipeline output).
DATA=Path(os.environ.get('NAZAR_DATA_DIR', str(ROOT/'data')))
# Reviewer decisions (the only writable store). NAZAR_DATABASE_URL (a Postgres
# connection string, e.g. from Neon) takes over when set — needed for any host
# without a persistent disk, where a local SQLite file resets on every cold
# start. Unset locally: falls back to the SQLite file at NAZAR_DB_PATH, same as
# before. Never commit a real NAZAR_DATABASE_URL — it belongs in the host's
# own env var store (Render dashboard), not in render.yaml or .env.example.
DATABASE_URL=os.environ.get('NAZAR_DATABASE_URL')
DB=Path(os.environ.get('NAZAR_DB_PATH', str(DATA/'investigations.sqlite3')))
PLACEHOLDER='%s' if DATABASE_URL else '?'
def ph(sql): return sql.replace('?',PLACEHOLDER)
# investigations has no auto-increment id; SELECT * order is exactly this.
INVESTIGATION_COLUMNS=('work_id','persona_id','decision','reason','decided_at')

# Fixed demo accounts, one per persona. Override for a deployment with NAZAR_USERS
# as "persona_id:user_id:password,persona_id:user_id:password,..." — otherwise
# these makeshift credentials (also listed in the README) unlock each view.
DEFAULT_USERS={'mp_office':('mp.office','mp-lookcloser-24'),
               'district_authority':('district.authority','district-lookcloser-24'),
               'state_nodal':('state.nodal','state-lookcloser-24'),
               'ministry':('ministry','ministry-lookcloser-24')}
AUTH_SECRET=os.environ.get('NAZAR_AUTH_SECRET','nazar-prototype-demo-secret').encode()
TOKEN_TTL=int(os.environ.get('NAZAR_TOKEN_TTL','28800'))  # 8h demo session

# Plain-English name for each review signal, matched to the frontend and used by
# GET /signals and the ?signal= filter on GET /works.
SIGNAL_LABELS={'cost_peer':'Amount vs activity peers','missing_evidence':'Completion evidence',
               'round_amount':'Round-number heuristic','anomaly':'Statistical anomaly',
               'photo_identical':'Identical image evidence','photo_similar':'Visually similar, keypoint-confirmed',
               'text_exact':'Exact cross-year description','text_similar':'Similar cross-year description',
               'entitlement_pace':'Entitlement pace (sourced, advisory)'}

def load_users():
    raw=os.environ.get('NAZAR_USERS')
    if not raw: return dict(DEFAULT_USERS)
    out={}
    for part in raw.split(','):
        pid,user_id,password=part.split(':',2)
        out[pid.strip()]=(user_id.strip(),password.strip())
    return out

def _b64(raw:bytes): return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
def _unb64(txt:str): return base64.urlsafe_b64decode(txt+'='*(-len(txt)%4))
def _sign(payload:str): return _b64(hmac.new(AUTH_SECRET,payload.encode(),hashlib.sha256).digest())

def issue_token(persona_id):
    payload=_b64(json.dumps({'sub':persona_id,'exp':int(time.time())+TOKEN_TTL}).encode())
    return f'{payload}.{_sign(payload)}'

def read_token(token):
    try:
        payload,sig=token.split('.',1)
        if not hmac.compare_digest(sig,_sign(payload)): return None
        claims=json.loads(_unb64(payload))
    except (ValueError,json.JSONDecodeError): return None
    return claims.get('sub') if claims.get('exp',0)>time.time() else None

@contextmanager
def connection():
    """Rows are plain tuples on both backends (sqlite3's and psycopg's own
    defaults) — callers that need column names zip INVESTIGATION_COLUMNS
    themselves rather than relying on a backend-specific row factory."""
    if DATABASE_URL:
        con=psycopg.connect(DATABASE_URL,autocommit=True)
    else:
        con=sqlite3.connect(DB,isolation_level=None)  # autocommit, to match Postgres above
    try:
        yield con
    finally:
        con.close()

@asynccontextmanager
async def lifespan(app):
    app.state.works=json.loads(pd.read_parquet(DATA/'scored_works.parquet').to_json(orient='records'))
    for r in app.state.works:
        r['_flagged']=sorted(k for k,v in json.loads(r['signals_json']).items() if v.get('flag'))
    app.state.by_id={r['WORK_ID']:r for r in app.state.works}
    app.state.personas=json.loads((DATA/'personas.json').read_text(encoding='utf-8'))
    app.state.pairs=json.loads((DATA/'duplicate_pairs.json').read_text(encoding='utf-8'))
    app.state.images={(r['work_id'],r['filename']) for r in json.loads((DATA/'images.json').read_text(encoding='utf-8'))}
    # Inefficiency (idle funds / late sanctioning) is a wholly separate population
    # and artifact from the fraud-scored works above — see scripts/pipeline.py's
    # build_inefficiency. Optional: [] / {} if the sanctioned-table join wasn't
    # available when the pipeline last ran.
    ineff_path=DATA/'inefficiency.json'
    app.state.inefficiency=json.loads(ineff_path.read_text(encoding='utf-8')) if ineff_path.exists() else []
    meta_path=ROOT/'reports/inefficiency.json'
    app.state.inefficiency_meta=json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    app.state.users=load_users()
    app.state.pair_index={}
    for p in app.state.pairs:
        for wid in set(p['work_ids']): app.state.pair_index.setdefault(wid,[]).append(p)
    with connection() as con:
        con.execute('CREATE TABLE IF NOT EXISTS investigations (work_id TEXT, persona_id TEXT, decision TEXT, reason TEXT, decided_at TEXT, PRIMARY KEY(work_id,persona_id))')
    yield

app=FastAPI(title='NAZAR review prototype',lifespan=lifespan)

# CORS: only relevant when the frontend is deployed separately from this API
# (e.g. Vercel + Render). Auth is a bearer token, not a cookie, so a wildcard
# origin carries no CSRF risk; set NAZAR_CORS_ORIGINS to a comma-separated list
# to lock it to specific origins instead. Same-origin deployment (this app
# serving frontend/dist itself, the README default) needs no CORS at all.
_cors_origins=[o.strip() for o in os.environ.get('NAZAR_CORS_ORIGINS','*').split(',') if o.strip()]
app.add_middleware(CORSMiddleware,allow_origins=_cors_origins,allow_methods=['*'],allow_headers=['*'])

def persona(pid):
    p=next((p for p in app.state.personas if p['id']==pid),None)
    if p is None: raise HTTPException(404,'Unknown persona')
    return p

UNAUTHENTICATED=HTTPException(401,'Sign in to continue',headers={'WWW-Authenticate':'Bearer'})

def current_persona(authorization:str=Header(default='')):
    scheme,_,token=authorization.partition(' ')
    pid=read_token(token) if scheme.lower()=='bearer' and token else None
    if not pid: raise UNAUTHENTICATED
    return persona(pid)

class Credentials(BaseModel):
    user_id:str=Field(min_length=1,max_length=200)
    password:str=Field(min_length=1,max_length=200)

@app.post('/auth/login')
def login(body:Credentials):
    match=next((pid for pid,(uid,pw) in app.state.users.items()
                if hmac.compare_digest(uid,body.user_id) and hmac.compare_digest(pw,body.password)),None)
    if not match: raise HTTPException(401,'Incorrect user ID or password')
    return {'token':issue_token(match),'expires_in':TOKEN_TTL,'persona':persona(match)}

@app.get('/auth/me')
def auth_me(me:dict=Depends(current_persona)): return me

def scope(pid):
    filters=persona(pid)['filter']
    return [r for r in app.state.works if all(r[k] in values for k,values in filters.items())]

def work(wid,pid=None):
    row=app.state.by_id.get(wid)
    if row is None: raise HTTPException(404,'Work not found')
    if pid and not all(row[k] in values for k,values in persona(pid)['filter'].items()):
        raise HTTPException(404,'Work outside this demo view')
    return row

def brief(row):
    fields=['WORK_ID','WORK_DESCRIPTION','MP_NAME','CONSTITUENCY','STATE_NAME','ACTUAL_AMOUNT','risk_score','severity_band','review_notice','fy_start_year','image_count']
    return {k:row.get(k) for k in fields}

@app.get('/personas')
def get_personas(): return app.state.personas

def compute_statuses():
    """work_id -> status from all investigations. A Ministry decision is final and
    order-independent: Confirm -> 'Confirmed', Dismiss -> 'Dismissed'. Any decision
    by a narrower persona, with no Ministry decision yet, is 'Under Review'."""
    with connection() as con:
        investigations=con.execute('SELECT work_id, persona_id, decision FROM investigations').fetchall()
    statuses,ministry={}, {}
    for wid,pid,decision in investigations:
        if pid=='ministry': ministry[wid]=decision
        else: statuses.setdefault(wid,'Under Review')
    for wid,decision in ministry.items():
        statuses[wid]='Confirmed' if decision=='Confirm' else 'Dismissed'
    return statuses

STATUSES=('Flagged','Under Review','Confirmed','Dismissed')

def ministry_confirmations():
    """work_id -> the Ministry's Confirm row (reason + decided_at), if any."""
    with connection() as con:
        rows=con.execute("SELECT * FROM investigations WHERE persona_id='ministry' AND decision='Confirm'").fetchall()
    return {r[0]:dict(zip(INVESTIGATION_COLUMNS,r)) for r in rows}

SignalName=Literal['cost_peer','missing_evidence','round_amount','anomaly','photo_identical','photo_similar','text_exact','text_similar','entitlement_pace']

@app.get('/signals')
def get_signals(me:dict=Depends(current_persona)):
    """Review-signal keys, their labels, and how many works in this view carry each."""
    rows=scope(me['id'])
    return [{'key':k,'label':l,'flagged':sum(k in r['_flagged'] for r in rows)} for k,l in SIGNAL_LABELS.items()]

@app.get('/works')
def get_works(me:dict=Depends(current_persona),severity:Literal['Low','Moderate','High','Critical']|None=None,signal:SignalName|None=None,status:str='Flagged',sort:Literal['risk','amount']='risk',q:str='',offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200)):
    persona_id=me['id']
    if status not in STATUSES: status='Flagged'
    rows=scope(persona_id)
    if severity: rows=[r for r in rows if r['severity_band']==severity]
    if signal: rows=[r for r in rows if signal in r['_flagged']]
    if q: rows=[r for r in rows if q.lower() in ' '.join(str(r.get(k,'')) for k in ['WORK_ID','WORK_DESCRIPTION','MP_NAME','CONSTITUENCY']).lower()]
    statuses=compute_statuses()
    all_rows_statuses={r['WORK_ID']:statuses.get(r['WORK_ID'],'Flagged') for r in rows}
    counts={s:sum(v==s for v in all_rows_statuses.values()) for s in STATUSES}
    rows=[r for r in rows if statuses.get(r['WORK_ID'],'Flagged')==status]
    rows.sort(key=lambda r:(r['risk_score'] if sort=='risk' else r['ACTUAL_AMOUNT'] or 0,r['WORK_ID']),reverse=True)
    with connection() as con:
        decisions=dict(con.execute(ph('SELECT work_id,decision FROM investigations WHERE persona_id=?'),(persona_id,)).fetchall())
    return {'total':len(rows),'status_counts':counts,'items':[{**brief(r),'decision':decisions.get(r['WORK_ID']),'status':statuses.get(r['WORK_ID'],'Flagged')} for r in rows[offset:offset+limit]]}

@app.get('/works/{work_id}')
def get_work(work_id:str,me:dict=Depends(current_persona)):
    r=work(work_id,me['id'])
    result={k:v for k,v in r.items() if not k.startswith('_') and k!='signals_json'}
    result['signals']=json.loads(r['signals_json'])
    with connection() as con:
        invs=[dict(zip(INVESTIGATION_COLUMNS,x)) for x in con.execute(ph('SELECT * FROM investigations WHERE work_id=?'),(work_id,)).fetchall()]
    for inv in invs:
        p=persona(inv['persona_id'])
        inv['persona_role']=p['role']
        inv['persona_label']=p['label']
    result['investigations']=invs
    result['status']=compute_statuses().get(work_id,'Flagged')
    return result

@app.get('/confirmed')
def confirmed(me:dict=Depends(current_persona)):
    """Works the Ministry has confirmed, within this persona's jurisdiction, newest
    first. Each item carries the Ministry's recorded reason and the time it was set."""
    rows=scope(me['id'])
    conf=ministry_confirmations()
    items=[{**brief(r),'ministry_reason':conf[r['WORK_ID']]['reason'],
            'confirmed_at':conf[r['WORK_ID']]['decided_at']}
           for r in rows if r['WORK_ID'] in conf]
    items.sort(key=lambda x:x['confirmed_at'],reverse=True)
    return {'total':len(items),'amount':sum(x['ACTUAL_AMOUNT'] or 0 for x in items),'items':items}

def scope_inefficiency(pid):
    filters=persona(pid)['filter']
    return [r for r in app.state.inefficiency if all(r.get(k) in values for k,values in filters.items())]

@app.get('/inefficiency')
def get_inefficiency(me:dict=Depends(current_persona),type:Literal['idle','late','all']='all',
                      sort:Literal['days_since_sanction','sanction_lag_days']='days_since_sanction',
                      q:str='',offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200)):
    """Idle-funds and late-sanction findings — never mixed with /works, /summary,
    signals_json or risk_score. A different population too: most of these records
    (the idle ones) have no completed work and so never appear in /works at all."""
    rows=scope_inefficiency(me['id'])
    if q: rows=[r for r in rows if q.lower() in ' '.join(str(r.get(k,'')) for k in
                ['RECORD_ID','WORK_ID','WORK_DESCRIPTION','MP_NAME','CONSTITUENCY']).lower()]
    type_counts={'idle':sum(1 for r in rows if r['idle_funds'] and r['idle_funds']['flag']),
                 'late':sum(1 for r in rows if r['late_sanction'] and r['late_sanction']['flag']),
                 'all':len(rows)}
    if type=='idle': rows=[r for r in rows if r['idle_funds'] and r['idle_funds']['flag']]
    elif type=='late': rows=[r for r in rows if r['late_sanction'] and r['late_sanction']['flag']]
    def sort_key(r):
        block=r['idle_funds'] if sort=='days_since_sanction' else r['late_sanction']
        return block[sort] if block else -1
    rows=sorted(rows,key=sort_key,reverse=True)
    return {'total':len(rows),'type_counts':type_counts,'items':rows[offset:offset+limit]}

@app.get('/inefficiency/summary')
def inefficiency_summary(me:dict=Depends(current_persona)):
    rows=scope_inefficiency(me['id'])
    idle=[r for r in rows if r['idle_funds'] and r['idle_funds']['flag']]
    late=[r for r in rows if r['late_sanction'] and r['late_sanction']['flag']]
    meta=app.state.inefficiency_meta
    return {'candidates':len(rows),'idle_flagged':len(idle),'late_flagged':len(late),
            'idle_amount':sum(r['sanction_amount'] or 0 for r in idle),
            'sanction_deadline_days':meta.get('sanction_deadline_days'),
            'late_sanction_fraction_corpus_wide':meta.get('late_sanction_fraction'),
            'source':meta.get('source'),'scope':persona(me['id'])['jurisdiction_summary'],
            'review_notice':NOTICE}

@app.get('/works/{work_id}/duplicates')
def duplicates(work_id:str,me:dict=Depends(current_persona)):
    work(work_id,me['id'])
    return app.state.pair_index.get(work_id,[])

@app.get('/image/{work_id}/{filename}')
def image(work_id:str,filename:str):
    # Served without a token: <img> tags cannot send Authorization, and linked
    # evidence is deliberately shared across jurisdictions. Still pair-checked.
    if (work_id,filename) not in app.state.images: raise HTTPException(404,'Image not found')
    return FileResponse(DATA/'image_cache'/filename,media_type='image/jpeg')

class Investigation(BaseModel):
    work_id:str
    decision:Literal['Confirm','Dismiss']
    reason:str=Field(min_length=1,max_length=4000)
    @field_validator('reason')
    @classmethod
    def reason_not_blank(cls,value):
        if not value.strip(): raise ValueError('A reason is required')
        return value.strip()

@app.post('/investigations')
def investigate(body:Investigation,me:dict=Depends(current_persona)):
    persona_id=me['id']
    work(body.work_id,persona_id)
    now=datetime.now(timezone.utc).isoformat()
    with connection() as con:
        con.execute(ph('INSERT INTO investigations VALUES (?,?,?,?,?) ON CONFLICT(work_id,persona_id) DO UPDATE SET decision=excluded.decision,reason=excluded.reason,decided_at=excluded.decided_at'),(body.work_id,persona_id,body.decision,body.reason,now))
    return {**body.model_dump(),'persona_id':persona_id,'decided_at':now}

@app.get('/summary')
def summary(me:dict=Depends(current_persona)):
    persona_id=me['id']
    rows=scope(persona_id)
    with connection() as con:
        reviewed={r[0] for r in con.execute(ph('SELECT work_id FROM investigations WHERE persona_id=?'),(persona_id,)).fetchall()}
    counts={band:sum(r['severity_band']==band for r in rows) for band in ['Critical','High','Moderate','Low']}
    statuses=compute_statuses()
    return {'total':len(rows),'severity':counts,'states':len({r['STATE_NAME'] for r in rows}),
            'confirmed':sum(statuses.get(r['WORK_ID'])=='Confirmed' for r in rows),
            'constituencies':len({(r['STATE_NAME'],r['CONSTITUENCY']) for r in rows}),
            'amount':sum(r['ACTUAL_AMOUNT'] or 0 for r in rows),'reviewed':sum(r['WORK_ID'] in reviewed for r in rows),
            'photo_matches':sum(any(p['tier'].startswith('photo_') for p in app.state.pair_index.get(r['WORK_ID'],[])) for r in rows),
            'scope':persona(persona_id)['jurisdiction_summary'],'review_notice':NOTICE}

@app.get('/evaluation')
def evaluation():
    path=ROOT/'reports/evaluation.json'
    if not path.exists(): raise HTTPException(503,'Run scripts/evaluate.py to generate validation results')
    return json.loads(path.read_text(encoding='utf-8'))

if (ROOT/'frontend/dist').exists():
    app.mount('/',StaticFiles(directory=ROOT/'frontend/dist',html=True),name='frontend')

