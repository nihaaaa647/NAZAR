"""NAZAR prototype. Persona scope comes from a server-verified, signed and
expiring JWT (backend/auth.py) - never from a request parameter or a
client-supplied persona_id - and every protected endpoint enforces
jurisdiction scoping (default-deny: an empty match list, not an admin flag,
is what gives Ministry national access) rather than relying on the frontend
to hide what a role shouldn't see."""
from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Literal
import json, os, secrets, shutil, sqlite3, uuid
import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend import auth
from pipeline.image_evidence import CLASSIFICATIONS, CLASSIFICATION_MEANINGS
from pipeline.jurisdiction import matches as jurisdiction_matches
from pipeline.satellite_eligibility import (CHANGE_DETECTED_LANGUAGE, NO_CHANGE_LANGUAGE,
                                             check_eligibility as check_satellite_eligibility)

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
def _postgres_reachable(url):
    # A bad/sleeping/unset-credential Postgres URL must not take the whole demo
    # down (login writes an audit row, so every request would 500). Probe once at
    # import; on failure fall back to SQLite and say so loudly in the logs.
    try:
        import psycopg
        with psycopg.connect(url,connect_timeout=10) as con: con.execute('SELECT 1')
        return True
    except Exception as exc:
        print(f'[db] NAZAR_DATABASE_URL unusable ({type(exc).__name__}: {exc}) - falling back to SQLite; reviewer decisions will not persist across restarts.')
        return False
if DATABASE_URL and not _postgres_reachable(DATABASE_URL): DATABASE_URL=None
PLACEHOLDER='%s' if DATABASE_URL else '?'
def ph(sql): return sql.replace('?',PLACEHOLDER)
# investigations has no auto-increment id; SELECT * order is exactly this.
INVESTIGATION_COLUMNS=('work_id','persona_id','decision','reason','decided_at')

# Fixed demo accounts, one per persona. Override for a deployment with NAZAR_USERS
# as "persona_id:user_id:password,persona_id:user_id:password,..." — otherwise
# these makeshift credentials unlock each view. Never shipped to the browser:
# the frontend bundle has no credential list at all (see frontend/src/App.tsx) —
# they're documented in the README (a repo file, not the deployed app) only.
# Hashed with Argon2id at load time below; only the hash is ever kept in memory
# or compared against, and login failures are never logged with the attempted
# password (see audit_event calls in /auth/login).
DEFAULT_USERS={'mp_office':('mp.office','mp-lookcloser-24'),
               'district_authority':('district.authority','district-lookcloser-24'),
               'state_nodal':('state.nodal','state-lookcloser-24'),
               'ministry':('ministry','ministry-lookcloser-24')}

# Plain-English name for each review signal, matched to the frontend and used by
# GET /signals and the ?signal= filter on GET /works.
SIGNAL_LABELS={'cost_peer':'Amount vs activity peers','missing_evidence':'Completion evidence',
               'anomaly':'Statistical anomaly',
               'photo_identical':'Identical image evidence','photo_similar':'Visually similar, keypoint-confirmed',
               'text_exact':'Exact cross-year description','text_similar':'Similar cross-year description',
               'entitlement_pace':'Entitlement pace (sourced, advisory)'}

def load_users():
    """user_id -> {persona_id, password_hash, role}. Passwords are hashed
    once here with Argon2id (backend/auth.hash_password) and the plaintext is
    discarded immediately after — nothing downstream ever sees it again."""
    raw=os.environ.get('NAZAR_USERS')
    entries=dict(DEFAULT_USERS)
    if raw:
        entries={}
        for part in raw.split(','):
            pid,user_id,password=part.split(':',2)
            entries[pid.strip()]=(user_id.strip(),password.strip())
    users={}
    for persona_id,(user_id,password) in entries.items():
        users[user_id]={'persona_id':persona_id,'password_hash':auth.hash_password(password)}
    return users

@contextmanager
def connection():
    """Rows are plain tuples on both backends (sqlite3's and psycopg's own
    defaults) — callers that need column names zip INVESTIGATION_COLUMNS
    themselves rather than relying on a backend-specific row factory."""
    if DATABASE_URL:
        import psycopg
        con=psycopg.connect(DATABASE_URL,autocommit=True)
    else:
        con=sqlite3.connect(DB,isolation_level=None)  # autocommit, to match Postgres above
    try:
        yield con
    finally:
        con.close()

def backup_before_migration(new_tables):
    """Phase 3 mandatory safeguard #3: before a schema migration touches an
    EXISTING local database, copy it aside with a timestamp and report the
    path. Only meaningful for the local SQLite file - a remote NAZAR_DATABASE_URL
    can't be file-copied from here, so that case is a documented limitation,
    not silently skipped-and-forgotten (see docs/DECISIONS.md's Phase 3 entry).
    A fresh/empty DB (no file yet) needs no backup - there's nothing to lose.
    Also skipped when EVERY table in `new_tables` already exists (this exact
    migration already ran before, on a previous startup) - but NOT skipped
    just because some overlap exists: a bug fixed here in Phase 4 had this
    check as `new_tables & existing` (any overlap at all), which wrongly
    skipped the backup for Phase 4's own new tables the moment Phase 3's
    `cases` table already existed - the correct check is "is every table in
    `new_tables` already present," i.e. `new_tables <= existing` (subset)."""
    if DATABASE_URL:
        print('[migration] NAZAR_DATABASE_URL is set - skipping local file backup '
              '(back up the remote database yourself before deploying this migration).', flush=True)
        return None
    if not DB.exists() or DB.stat().st_size == 0:
        return None
    with connection() as con:
        existing = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if new_tables <= existing:
        return None  # every one of these tables already exists - nothing new to migrate, nothing to back up for
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_path = DB.with_name(f'{DB.stem}.backup-{timestamp}{DB.suffix}')
    shutil.copy2(DB, backup_path)
    print(f'[migration] Backed up existing database to {backup_path} before creating {sorted(new_tables)}', flush=True)
    return backup_path

@asynccontextmanager
async def lifespan(app):
    app.state.works=json.loads(pd.read_parquet(DATA/'scored_works.parquet').to_json(orient='records'))
    for r in app.state.works:
        r['_flagged']=sorted(k for k,v in json.loads(r['signals_json']).items() if v.get('flag'))
    app.state.by_id={r['WORK_ID']:r for r in app.state.works}
    app.state.personas=json.loads((DATA/'personas.json').read_text(encoding='utf-8'))
    app.state.pairs=json.loads((DATA/'duplicate_pairs.json').read_text(encoding='utf-8'))
    app.state.images={(r['work_id'],r['filename']) for r in json.loads((DATA/'images.json').read_text(encoding='utf-8'))}
    # Inefficiency (long-open work / late sanctioning) is a wholly separate population
    # and artifact from the fraud-scored works above — see scripts/pipeline.py's
    # build_inefficiency. Optional: [] / {} if the sanctioned-table join wasn't
    # available when the pipeline last ran.
    ineff_path=DATA/'inefficiency.json'
    app.state.inefficiency=json.loads(ineff_path.read_text(encoding='utf-8')) if ineff_path.exists() else []
    meta_path=ROOT/'reports/inefficiency.json'
    app.state.inefficiency_meta=json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {}
    # Satellite/vendor-network module (docs/SATELLITE_VENDOR_MODULE_PLAN.md) - its
    # own synthetic population (real OSM coordinates + real Sentinel-2 imagery for
    # Branch A, real small-category MPLADS costs for Branch B, fictional MP/IDA/
    # vendor names throughout - see docs/SATELLITE_MODULE_DATA_REALITY.md). Not
    # joined onto app.state.works or jurisdiction-scoped: none of this module's
    # fictional MP names match a real persona's filter, so the usual scope()
    # would silently show every persona nothing. All optional - the app runs
    # without this module's outputs, same as inefficiency.json above.
    def _clean_nan(records):
        # DataFrame.where(pd.notna(df),None) doesn't reliably scrub NaN out of
        # object-dtype columns (mixed str/NaN, e.g. Branch B's blank asset_id) -
        # sanitize per-record instead, since json.dumps rejects a bare float nan.
        for r in records:
            for k,v in r.items():
                if isinstance(v,float) and v!=v: r[k]=None
        return records
    sat_path=DATA/'canonical/satellite_works_scored.csv'
    app.state.satellite_works=_clean_nan(pd.read_csv(sat_path).to_dict('records')) if sat_path.exists() else []
    for r in app.state.satellite_works:
        r['work_id']=str(r['work_id'])
        r['signals']=json.loads(r.pop('signals_json')) if r.get('signals_json') else {}
    app.state.satellite_by_id={r['work_id']:r for r in app.state.satellite_works}
    # Phase 5 section B: reconcile the eligibility gate (pipeline/satellite_
    # eligibility.py) with the actual change-detection model (ml/cv/
    # satellite_change.py) - its output previously existed only as a CSV
    # never read by this backend, so a reviewer never saw whether NAZAR's own
    # NDVI/pixel-diff model found a change, only the eligibility gate. Keyed
    # by asset_id (ml/cv/satellite_change.py's asset_id == this CSV's asset_id).
    sat_change_path=DATA/'canonical/satellite_change_results.csv'
    app.state.satellite_change_by_asset=({str(r['asset_id']):r for r in _clean_nan(pd.read_csv(sat_change_path).to_dict('records'))}
                                          if sat_change_path.exists() else {})
    sat_manifest_path=DATA/'satellite_cache/manifest.json'
    app.state.satellite_asset_ids=(set(json.loads(sat_manifest_path.read_text(encoding='utf-8')).keys())
                                    if sat_manifest_path.exists() else set())
    vendor_path=DATA/'canonical/vendor_network.csv'
    app.state.vendor_network=_clean_nan(pd.read_csv(vendor_path).to_dict('records')) if vendor_path.exists() else []
    # Data-quality alerts + field lineage (pipeline/data_quality.py,
    # pipeline/lineage.py, run inside pipelines.ingest.build_works — see
    # scripts/pipeline.py). A wholly separate artifact from the fraud-scored
    # works above: never joined onto signals_json/risk_score, never filtered
    # by persona jurisdiction (same "shared for context" convention as
    # duplicate evidence — a data-quality issue on a sanctioned-only record
    # that never even reaches app.state.works still needs to be visible to
    # someone). Optional, like inefficiency.json above.
    qa_path=DATA/'quality_alerts.json'
    app.state.quality_alerts=json.loads(qa_path.read_text(encoding='utf-8')) if qa_path.exists() else []
    lineage_path=DATA/'lineage.json'
    app.state.lineage=json.loads(lineage_path.read_text(encoding='utf-8')) if lineage_path.exists() else {}
    app.state.quality_by_id={a['id']:a for a in app.state.quality_alerts}
    # work_id/record key -> {mp_name, state_name, constituency}, covering
    # every canonical row (including sanctioned-only ones that never reach
    # app.state.works) - what GET /quality/lineage/{work_id} scopes against.
    wd_path=DATA/'work_directory.json'
    app.state.work_directory=json.loads(wd_path.read_text(encoding='utf-8')) if wd_path.exists() else {}
    app.state.users=load_users()
    app.state.dummy_password_hash=auth.hash_password(secrets.token_urlsafe(32))
    app.state.pair_index={}
    for p in app.state.pairs:
        for wid in set(p['work_ids']): app.state.pair_index.setdefault(wid,[]).append(p)
    # Related-entities view: an isolated flag reads as noise; the same MP or
    # implementing agency turning up on several OTHER flagged works reads as a
    # pattern. Indexed once here, not per request — 5,611 rows, trivial either
    # way, but the request-time helper (related_entities) shouldn't rebuild it.
    app.state.by_mp=defaultdict(list); app.state.by_ida=defaultdict(list)
    for r in app.state.works:
        if r.get('MP_NAME'): app.state.by_mp[r['MP_NAME']].append(r)
        if r.get('IDA_NAME'): app.state.by_ida[r['IDA_NAME']].append(r)
    app.state.corpus_flag_rate=sum(r['severity_band']!='Low' for r in app.state.works)/len(app.state.works) if app.state.works else 0.0
    # Phase 3 case candidates (pipeline/cases.py, generated by scripts/pipeline.py's
    # main()) - the descriptive/evidence side of a case. Workflow state (status,
    # history) lives only in the `cases` SQL table below, keyed by the same
    # deterministic case_id, so a pipeline rerun can update evidence without ever
    # touching a reviewer's decision (see the merge loop after table creation).
    cc_path=DATA/'case_candidates.json'
    app.state.case_candidates=json.loads(cc_path.read_text(encoding='utf-8')) if cc_path.exists() else []
    app.state.case_by_id={c['case_id']:c for c in app.state.case_candidates}
    # Phase 4 image evidence - descriptive data (images.json/image_matches.json)
    # regenerates every pipeline run, same pattern as case_candidates above.
    im_path=DATA/'image_matches.json'
    app.state.image_matches=json.loads(im_path.read_text(encoding='utf-8')) if im_path.exists() else []
    app.state.image_match_by_id={m['match_id']:m for m in app.state.image_matches}
    app.state.last_migration_backup=backup_before_migration(
        {'cases','case_history','reviewer_notes','case_context_snapshots','image_match_reviews','case_review_sessions'})
    with connection() as con:
        con.execute('CREATE TABLE IF NOT EXISTS investigations (work_id TEXT, persona_id TEXT, decision TEXT, reason TEXT, decided_at TEXT, PRIMARY KEY(work_id,persona_id))')
        con.execute('CREATE TABLE IF NOT EXISTS quality_resolutions (alert_id TEXT PRIMARY KEY, status TEXT, reason TEXT, persona_id TEXT, decided_at TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS revoked_tokens (jti TEXT PRIMARY KEY, expires_at INTEGER)')
        # Append-only: every row here is written once by audit_event() and
        # never updated or deleted by any endpoint - the log itself is the
        # record, including of denied/failed attempts.
        con.execute('CREATE TABLE IF NOT EXISTS audit_events (id TEXT PRIMARY KEY, event_type TEXT, user_id TEXT, '
                     'persona_id TEXT, role TEXT, entity_type TEXT, entity_id TEXT, action TEXT, reason TEXT, '
                     'before_state TEXT, after_state TEXT, success INTEGER, detail TEXT, created_at TEXT)')
        # Workflow STATE only - descriptive/evidence fields live in
        # app.state.case_candidates (regenerated every pipeline run); this row
        # is what makes a case's reviewer decision survive a rerun.
        con.execute('CREATE TABLE IF NOT EXISTS cases (case_id TEXT PRIMARY KEY, work_id TEXT, status TEXT, '
                     'source TEXT, created_at TEXT, updated_at TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS case_history (id TEXT PRIMARY KEY, case_id TEXT, from_status TEXT, '
                     'to_status TEXT, action TEXT, user_id TEXT, persona_id TEXT, role TEXT, reason TEXT, created_at TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS reviewer_notes (id TEXT PRIMARY KEY, case_id TEXT, user_id TEXT, '
                     'persona_id TEXT, role TEXT, note TEXT, created_at TEXT)')
        # Phase 4 A.2: immutable context snapshot for a MANUALLY escalated case
        # only (an auto-detected case's context is always available fresh from
        # app.state.case_candidates, regenerated every pipeline run - it never
        # needs a snapshot). Deliberately NOT a copy of the full work record:
        # just enough to redisplay the case if it's ever opened again, plus a
        # reference back to the source work_id for anyone who wants more.
        con.execute('CREATE TABLE IF NOT EXISTS case_context_snapshots (case_id TEXT PRIMARY KEY, work_id TEXT, '
                     'title TEXT, description TEXT, mp_name TEXT, state_name TEXT, constituency TEXT, '
                     'work_category TEXT, actual_amount REAL, source TEXT, data_mode TEXT, escalation_reason TEXT, '
                     'created_by TEXT, created_by_role TEXT, created_at TEXT, source_record_ref TEXT)')
        # Phase 4 section G "reviewer outcomes" - append-only, one row per
        # reviewer action on one image match (never a "declare fraud" action -
        # see IMAGE_REVIEW_ACTIONS). Current status for a match is just its
        # latest row; nothing here is ever updated or deleted.
        con.execute('CREATE TABLE IF NOT EXISTS image_match_reviews (id TEXT PRIMARY KEY, match_id TEXT, action TEXT, '
                     'reason TEXT, note TEXT, user_id TEXT, persona_id TEXT, role TEXT, before_state TEXT, '
                     'after_state TEXT, created_at TEXT)')
        # Phase 4 section K - explicit review-session timing, so "cases
        # resolved per investigator-hour" can come from recorded active
        # duration instead of being inferred from raw case age.
        con.execute('CREATE TABLE IF NOT EXISTS case_review_sessions (id TEXT PRIMARY KEY, case_id TEXT, user_id TEXT, '
                     'persona_id TEXT, started_at TEXT, ended_at TEXT)')
        # Reconstruct manually-escalated cases from their snapshot so they
        # survive a restart even though they were never in case_candidates.json
        # (which only ever holds auto-detected candidates).
        snapshot_rows=con.execute('SELECT case_id,work_id,title,description,mp_name,state_name,constituency,'
                                    'work_category,actual_amount,source,data_mode,escalation_reason,created_by,'
                                    'created_by_role,created_at,source_record_ref FROM case_context_snapshots').fetchall()
        for row in snapshot_rows:
            (case_id,work_id,title,description,mp_name,state_name,constituency,work_category,actual_amount,
             source,data_mode,escalation_reason,created_by,created_by_role,created_at,source_record_ref)=row
            if case_id in app.state.case_by_id: continue  # already present (shouldn't happen, but never overwrite)
            candidate={'case_id':case_id,'work_id':work_id,
                       'context':{'work_description':description,'mp_name':mp_name,'state_name':state_name,
                                  'constituency':constituency,'work_category':work_category,'actual_amount':actual_amount},
                       'clusters_fired':[],'anomaly_priority':0.0,'inefficiency_priority':0.0,
                       'evidence_completeness':None,'source_data_confidence':None,'signal_codes':[],
                       'fired_signals':[],'candidate_signals':[],'unavailable_checks':[],
                       'what_happened':title or description,'why_flagged':[f'Manually escalated by {created_by_role}: {escalation_reason}'],
                       'recommended_action':'Reviewer-initiated - see escalation reason.','fingerprint':None,
                       'detector_version':'manual-escalation-v1','data_mode':data_mode,'source':source,
                       'source_record_ref':source_record_ref}
            app.state.case_candidates.append(candidate)
            app.state.case_by_id[case_id]=candidate
        # Merge: a case_id already in the table keeps its status/history
        # untouched (this IS the suppression rule - a dismissed case whose
        # evidence hasn't materially changed regenerates the same case_id and
        # is simply left alone); a new case_id is inserted as NEW. Nothing here
        # ever updates or deletes an existing row.
        existing_ids={r[0] for r in con.execute('SELECT case_id FROM cases').fetchall()}
        now=datetime.now(timezone.utc).isoformat()
        new_rows=[(c['case_id'],c['work_id'],'NEW',c.get('source','auto_detection'),now,now)
                  for c in app.state.case_candidates if c['case_id'] not in existing_ids]
        if new_rows:
            # psycopg's Connection has no executemany (sqlite3's does) - the cursor has it on both.
            # One transaction: in autocommit mode each row would otherwise be its own
            # commit, which took minutes to seed ~4k cases on a remote Postgres.
            con.execute('BEGIN')
            try:
                con.cursor().executemany(ph('INSERT INTO cases VALUES (?,?,?,?,?,?)'),new_rows)
                con.execute('COMMIT')
            except Exception:
                con.execute('ROLLBACK'); raise
    yield

app=FastAPI(title='NAZAR review prototype',lifespan=lifespan)

# CORS: only relevant when the frontend is deployed separately from this API
# (e.g. Vercel + Render). Auth is a bearer token, not a cookie, so a wildcard
# origin carries no CSRF risk; set NAZAR_CORS_ORIGINS to a comma-separated list
# to lock it to specific origins instead. Same-origin deployment (this app
# serving frontend/dist itself, the README default) needs no CORS at all.
if os.environ.get('NAZAR_ENV', 'development') == 'production' and os.environ.get('NAZAR_CORS_ORIGINS', '*').strip() == '*':
    raise RuntimeError('NAZAR_CORS_ORIGINS must name the real frontend origin(s) (comma-separated) when '
                        'NAZAR_ENV=production - refusing to start with wildcard CORS in production.')
_cors_origins=[o.strip() for o in os.environ.get('NAZAR_CORS_ORIGINS','*').split(',') if o.strip()]
app.add_middleware(CORSMiddleware,allow_origins=_cors_origins,allow_methods=['*'],allow_headers=['*'])

# Phase 5 section E: request-size limit + basic security headers. No request
# body this API accepts (all POST/PUT bodies are small JSON review actions,
# never a file upload — evidence images are served read-only from a fixed
# local cache, never uploaded through this API) should ever need to be large;
# a large Content-Length is rejected before the body is read at all.
MAX_REQUEST_BODY_BYTES=1_000_000
@app.middleware('http')
async def _security_middleware(request:Request,call_next):
    content_length=request.headers.get('content-length')
    if content_length and int(content_length)>MAX_REQUEST_BODY_BYTES:
        return JSONResponse({'detail':'Request body too large'},status_code=413)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    return response

def persona(pid):
    p=next((p for p in app.state.personas if p['id']==pid),None)
    if p is None: raise HTTPException(404,'Unknown persona')
    return p

def audit_event(event_type,*,user_id=None,persona_id=None,role=None,entity_type=None,entity_id=None,
                 action=None,reason=None,before_state=None,after_state=None,success=True,detail=None):
    """Append one immutable row. Never called with a password, signing secret
    or full token - callers pass only a jti (see /auth/logout) or a user_id,
    never the bearer token string itself."""
    with connection() as con:
        con.execute(ph('INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)'),
                    (uuid.uuid4().hex,event_type,user_id,persona_id,role,entity_type,entity_id,action,reason,
                     json.dumps(before_state) if before_state is not None else None,
                     json.dumps(after_state) if after_state is not None else None,
                     1 if success else 0,detail,datetime.now(timezone.utc).isoformat()))

UNAUTHENTICATED=HTTPException(401,'Sign in to continue',headers={'WWW-Authenticate':'Bearer'})
FORBIDDEN=lambda detail='Outside this account’s jurisdiction':HTTPException(403,detail)

def current_persona(authorization:str=Header(default='')):
    """Verifies a server-signed, expiring JWT (backend/auth.py) — the token's
    signature, expiry and revocation status are all checked here; nothing
    about scope is ever taken from the request itself. Returns the persona
    dict (role/jurisdiction/filter) plus the authenticated user_id, so every
    caller downstream gets both "what can this account see" and "who is
    this" without re-deriving either from client input."""
    scheme,_,token=authorization.partition(' ')
    if scheme.lower()!='bearer' or not token: raise UNAUTHENTICATED
    try:
        claims=auth.decode_token(token)
    except auth.TokenError:
        raise UNAUTHENTICATED
    with connection() as con:
        revoked=con.execute(ph('SELECT 1 FROM revoked_tokens WHERE jti=?'),(claims['jti'],)).fetchone()
    if revoked: raise UNAUTHENTICATED
    try:
        p=persona(claims['persona_id'])
    except HTTPException:
        raise UNAUTHENTICATED
    return {**p,'user_id':claims['sub'],'jti':claims['jti']}

class Credentials(BaseModel):
    user_id:str=Field(min_length=1,max_length=200)
    password:str=Field(min_length=1,max_length=200)

# Phase 5 section E: login rate limiting. In-memory sliding window keyed by
# client IP - a single-process limiter, which is a real limitation for a
# multi-worker deployment (each worker has its own memory, so the effective
# limit multiplies by worker count); documented in docs/KNOWN_LIMITATIONS.md
# rather than solved with a shared store this prototype doesn't otherwise need.
LOGIN_RATE_LIMIT_MAX_ATTEMPTS=10
LOGIN_RATE_LIMIT_WINDOW_SECONDS=300
_login_attempts:dict[str,list[float]]={}

def _check_login_rate_limit(client_ip:str):
    now=datetime.now(timezone.utc).timestamp()
    attempts=[t for t in _login_attempts.get(client_ip,[]) if now-t<LOGIN_RATE_LIMIT_WINDOW_SECONDS]
    if len(attempts)>=LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(429,'Too many login attempts - try again later.')
    attempts.append(now)
    _login_attempts[client_ip]=attempts

@app.post('/auth/login')
def login(body:Credentials,request:Request):
    client_ip=request.client.host if request.client else 'unknown'
    _check_login_rate_limit(client_ip)
    account=app.state.users.get(body.user_id)
    # Verify against a fixed dummy hash even on an unknown user_id, so a
    # login attempt for a nonexistent account takes the same time as one for
    # a real account with a wrong password — a real account's existence
    # can't be inferred by timing.
    password_hash=account['password_hash'] if account else app.state.dummy_password_hash
    valid=auth.verify_password(password_hash,body.password) and account is not None
    if not valid:
        audit_event('login_failure',user_id=body.user_id,success=False,detail='Incorrect user ID or password')
        raise HTTPException(401,'Incorrect user ID or password')
    token,jti,expires_at=auth.create_token(body.user_id,account['persona_id'],persona(account['persona_id'])['role'])
    audit_event('login_success',user_id=body.user_id,persona_id=account['persona_id'],
                role=persona(account['persona_id'])['role'],detail=f'jti={jti}')
    return {'token':token,'expires_in':expires_at-int(datetime.now(timezone.utc).timestamp()),'persona':persona(account['persona_id'])}

@app.get('/auth/me')
def auth_me(me:dict=Depends(current_persona)): return me

@app.post('/auth/logout')
def logout(me:dict=Depends(current_persona)):
    with connection() as con:
        con.execute(ph('INSERT INTO revoked_tokens VALUES (?,?) ON CONFLICT(jti) DO NOTHING'),
                    (me['jti'],int(datetime.now(timezone.utc).timestamp())+auth.TOKEN_TTL))
    audit_event('logout',user_id=me['user_id'],persona_id=me['id'],role=me['role'],detail=f"jti={me['jti']}")
    return {'ok':True}

def filter_matches(row_get, filters, field_map=None):
    """Default-deny jurisdiction check shared by every scope_*() below: an
    empty `filters` dict (Ministry) matches everything via `all([])`; a
    non-empty one requires every field to normalized-match at least one
    allowed value (pipeline/jurisdiction.py - trim/casefold/alias table, a
    documented demo-grade fallback, not a stable government identifier)."""
    field_map = field_map or {}
    return all(jurisdiction_matches(row_get(field_map.get(k, k)), values) for k, values in filters.items())

def scope(pid):
    filters=persona(pid)['filter']
    return [r for r in app.state.works if filter_matches(r.get, filters)]

def work(wid,pid=None):
    row=app.state.by_id.get(wid)
    if row is None: raise HTTPException(404,'Work not found')
    if pid and not filter_matches(row.get, persona(pid)['filter']):
        audit_event('access_denied',persona_id=pid,role=persona(pid)['role'],entity_type='work',
                     entity_id=wid,action='read',success=False,detail='work outside persona jurisdiction')
        raise FORBIDDEN()
    return row

def brief(row):
    fields=['WORK_ID','WORK_DESCRIPTION','MP_NAME','CONSTITUENCY','STATE_NAME','ACTUAL_AMOUNT','risk_score','severity_band','review_notice','fy_start_year','image_count']
    return {k:row.get(k) for k in fields}

def related_entities(row):
    """An isolated flag reads as noise; the same MP or implementing agency
    turning up on several OTHER flagged works reads as a pattern — the
    blueprint's "which related entities" card, built from data every work
    already carries, no new detector. Corpus-wide, not jurisdiction-scoped —
    same "shared for context" convention as duplicate evidence."""
    def block(key,index):
        name=row.get(key)
        if not name: return None
        peers=index.get(name,[])
        if len(peers)<2: return None  # nothing to call a pattern with just this one work
        flagged=[r for r in peers if r['severity_band']!='Low']
        rate=len(flagged)/len(peers)
        others=sorted((r for r in flagged if r['WORK_ID']!=row['WORK_ID']),key=lambda r:r['risk_score'],reverse=True)[:5]
        return {'name':name,'total_works':len(peers),'flagged_works':len(flagged),'flag_rate':round(rate,3),
                'corpus_flag_rate':round(app.state.corpus_flag_rate,3),
                'multiplier':round(rate/app.state.corpus_flag_rate,1) if app.state.corpus_flag_rate else None,
                'other_flagged_works':[brief(r) for r in others]}
    return {'mp':block('MP_NAME',app.state.by_mp),'ida':block('IDA_NAME',app.state.by_ida)}

@app.get('/personas')
def get_personas(): return app.state.personas

# --- Phase 5 section F: operational endpoints. None require auth - a load
# balancer / uptime check has no token, and none of these leak secrets or
# internal filesystem paths (only versions, counts and capability labels). ---

@app.get('/health')
def health():
    """Process alive - does not touch the database or check that data
    finished loading (that's /ready). A load balancer uses this to decide
    whether to kill/restart the process, not whether to route traffic to it."""
    return {'status': 'ok'}

@app.get('/ready')
def ready():
    """Database reachable AND the data this app needs to serve real requests
    actually loaded (not just that the process started). A load balancer
    should NOT route traffic here until this returns 200."""
    checks = {}
    try:
        with connection() as con:
            con.execute('SELECT 1')
        checks['database'] = 'ok'
    except Exception as exc:
        checks['database'] = f'error: {exc}'
    checks['scored_works_loaded'] = 'ok' if getattr(app.state, 'works', None) else 'missing'
    checks['personas_loaded'] = 'ok' if getattr(app.state, 'personas', None) else 'missing'
    all_ok = all(v == 'ok' for v in checks.values())
    return JSONResponse({'ready': all_ok, 'checks': checks}, status_code=200 if all_ok else 503)

@app.get('/version')
def version():
    """Detector/schema/threshold versions actually embedded in the loaded
    data (never hardcoded separately from what the pipeline run that
    produced this data actually used) - a reviewer or auditor can trust this
    reflects what scored the works they're looking at, not a changelog that
    can drift from the code. NAZAR_BUILD_COMMIT is set by the deploy
    platform (e.g. Render's RENDER_GIT_COMMIT); 'unknown' locally is honest,
    not a placeholder to be filled in later."""
    sample_signal = next((s for c in app.state.case_candidates for s in c.get('fired_signals', [])), None)
    return {
        'build_commit': os.environ.get('NAZAR_BUILD_COMMIT') or os.environ.get('RENDER_GIT_COMMIT') or 'unknown',
        'case_schema_version': 'cases-v1',
        'detector_version': sample_signal.get('detector_version') if sample_signal else 'unknown',
        'threshold_version': sample_signal.get('threshold_version') if sample_signal else 'unknown',
        'image_preprocessing_version': next(iter({i.get('preprocessing_version') for i in getattr(app.state, 'image_matches', [])} - {None}), 'unknown'),
        'database': 'postgres' if DATABASE_URL else 'sqlite',
    }

@app.get('/capabilities')
def capabilities():
    """Phase 5 section K's CAPABILITY_MATRIX categories, machine-readable -
    docs/CAPABILITY_MATRIX.md is the human-readable version of the same
    claims; keep both in sync by hand, this endpoint doesn't generate the
    doc. Never claims something is implemented that isn't wired to real
    data in this running process."""
    return {
        'IMPLEMENTED_PUBLIC_DATA': [
            'cost_peer', 'anomaly', 'missing_evidence', 'text_exact', 'text_similar',
            'entitlement_pace', 'long_open_work', 'late_sanction', 'photo_identical',
            'photo_similar (ORB/RANSAC confirmed)', 'data_quality_alerts', 'case_consolidation',
            'jurisdiction_rbac', 'audit_log', 'review_workflow',
        ],
        'DERIVED_PUBLIC_DATA': ['satellite_change_screening (OpenStreetMap coords + Sentinel-2, Branch A demo scope)',
                                 'vendor_network_patterns'],
        'SYNTHETIC_DEMONSTRATION': ['image_evidence_calibration_set (8 labeled controls)'],
        'AUTHORISED_DATA_REQUIRED': ['real_release_spent_balance_for_idle_funds', 'real_geotagged_coordinates_at_scale'],
        'IN_DEVELOPMENT': ['real_pair_precision_adjudication (Phase 5 A.1 - see docs/DETECTOR_VALIDATION.md)'],
        'UNAVAILABLE': ['cases_resolved_per_investigator_hour (no recorded review-session data yet)'],
    }

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

SignalName=Literal['cost_peer','missing_evidence','anomaly','photo_identical','photo_similar','text_exact','text_similar','entitlement_pace']

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
    result['related']=related_entities(r)
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
def get_inefficiency(me:dict=Depends(current_persona),type:Literal['long_open','late','all']='all',
                      sort:Literal['days_since_sanction','sanction_lag_days']='days_since_sanction',
                      q:str='',offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200)):
    """Long-open-work and late-sanction findings — never mixed with /works,
    /summary, signals_json or risk_score. A different population too: most of
    these records (the long-open ones) have no completed work and so never
    appear in /works at all. A block's own `status` can be 'fired', 'clear' or
    'unavailable' (Phase 3 standard contract) - only 'fired' counts as flagged
    here; 'unavailable' blocks are never treated as a flagged or a clear result."""
    rows=scope_inefficiency(me['id'])
    if q: rows=[r for r in rows if q.lower() in ' '.join(str(r.get(k,'')) for k in
                ['RECORD_ID','WORK_ID','WORK_DESCRIPTION','MP_NAME','CONSTITUENCY']).lower()]
    def fired(r,key): b=r.get(key); return bool(b and b.get('status')=='fired')
    type_counts={'long_open':sum(1 for r in rows if fired(r,'long_open_work')),
                 'late':sum(1 for r in rows if fired(r,'late_sanction')),
                 'all':len(rows)}
    if type=='long_open': rows=[r for r in rows if fired(r,'long_open_work')]
    elif type=='late': rows=[r for r in rows if fired(r,'late_sanction')]
    def sort_key(r):
        block=r.get('long_open_work') if sort=='days_since_sanction' else r.get('late_sanction')
        return (block or {}).get(sort,-1)
    rows=sorted(rows,key=sort_key,reverse=True)
    return {'total':len(rows),'type_counts':type_counts,'items':rows[offset:offset+limit]}

@app.get('/inefficiency/summary')
def inefficiency_summary(me:dict=Depends(current_persona)):
    rows=scope_inefficiency(me['id'])
    long_open=[r for r in rows if r.get('long_open_work') and r['long_open_work'].get('status')=='fired']
    late=[r for r in rows if r.get('late_sanction') and r['late_sanction'].get('status')=='fired']
    meta=app.state.inefficiency_meta
    return {'candidates':len(rows),'long_open_flagged':len(long_open),'late_flagged':len(late),
            'long_open_amount':sum(r['sanction_amount'] or 0 for r in long_open),
            'late_sanction_review_days':meta.get('late_sanction_review_days'),
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
    # persona_id/user_id come only from the verified token (me, via
    # current_persona) - never from the request body, so a client can't
    # attribute a decision to a different reviewer or a different persona.
    persona_id=me['id']
    work(body.work_id,persona_id)
    with connection() as con:
        previous=con.execute(ph('SELECT decision FROM investigations WHERE work_id=? AND persona_id=?'),(body.work_id,persona_id)).fetchone()
    now=datetime.now(timezone.utc).isoformat()
    with connection() as con:
        con.execute(ph('INSERT INTO investigations VALUES (?,?,?,?,?) ON CONFLICT(work_id,persona_id) DO UPDATE SET decision=excluded.decision,reason=excluded.reason,decided_at=excluded.decided_at'),(body.work_id,persona_id,body.decision,body.reason,now))
    audit_event('evidence_decision',user_id=me['user_id'],persona_id=persona_id,role=me['role'],
                entity_type='work',entity_id=body.work_id,action=body.decision,reason=body.reason,
                before_state={'decision':previous[0]} if previous else None,after_state={'decision':body.decision})
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

# --- Satellite/vendor-network module (docs/SATELLITE_VENDOR_MODULE_PLAN.md) ---
# Auth-gated (must be signed in, like every other endpoint) but NOT jurisdiction-
# scoped: this module's MP_NAME/IDA_NAME are fictional DEMO placeholders (see
# docs/SATELLITE_MODULE_DATA_REALITY.md), so no real persona's filter could ever
# match a real row here without either hiding everything from everyone or faking
# a jurisdiction match - both worse than being explicit that this view is
# corpus-wide and reused Confirm/Dismiss is the only place jurisdiction already
# matters (the investigations table itself, keyed by persona_id like any other
# work_id there).
SAT_NOTICE='Computational signal — needs human review. Real OpenStreetMap coordinates and real Sentinel-2 imagery for Branch A; MP/IDA/vendor names are fictional throughout.'

@app.get('/satellite/works')
def satellite_works(me:dict=Depends(current_persona),branch:Literal['A','B']|None=None,
                     severity:Literal['Low','Moderate','High','Critical']|None=None,
                     offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200)):
    rows=app.state.satellite_works
    if branch: rows=[r for r in rows if r['branch']==branch]
    if severity: rows=[r for r in rows if r['severity_band']==severity]
    rows=sorted(rows,key=lambda r:r['risk_score'],reverse=True)
    fields=['work_id','branch','category','MP_NAME','IDA_NAME','WORK_DESCRIPTION','area_name','ACTUAL_AMOUNT',
            'risk_score','severity_band','asset_id','lat','lon','source_scheme','vendor_id']
    return {'total':len(rows),'notice':SAT_NOTICE,
            'items':[{k:r.get(k) for k in fields} for r in rows[offset:offset+limit]]}

@app.get('/satellite/{work_id}')
def satellite_work(work_id:str,me:dict=Depends(current_persona)):
    r=app.state.satellite_by_id.get(work_id)
    if r is None: raise HTTPException(404,'Satellite work not found')
    result=dict(r)
    asset_id=r.get('asset_id')
    if r.get('branch')=='A' and asset_id:
        manifest_path=DATA/'satellite_cache/manifest.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
        entry=manifest.get(asset_id)
        # Phase 4 section J: the eligibility gate, run on whatever this
        # pipeline actually tracks today. Two inputs this corpus doesn't yet
        # score anywhere (cloud cover per-asset, imagery-to-project-timeline
        # skew) are passed as None - "not checked", never faked as passing -
        # so `eligible` here means "cleared every gate this system can
        # currently evaluate", not "cleared every gate in the abstract".
        scheme=(r.get('source_scheme') or '').lower()
        geocode_confidence=0.8 if scheme and 'seed' not in scheme else (0.5 if scheme else None)
        # Phase 5 section B: both previously-hardcoded-None checks now use
        # real data where it exists. cloud_cover_pct: the worse (higher) of
        # the two scenes' eo:cloud_cover (pipeline/fetch_satellite_pairs.py
        # already stores it per-scene, already percent-scale - just never
        # read here before). imagery_date_skew_days: how far the "after"
        # scene's capture date is from the work's own claimed completion
        # date (ACTUAL_END_DATE) - imagery from years off the actual
        # construction window can't meaningfully screen it. Either stays
        # None (honestly "not checked") when the underlying date/field is
        # missing or unparseable - never guessed.
        cloud_cover_pct=None
        if entry and entry.get('t1') and entry.get('t2'):
            c1,c2=entry['t1'].get('cloud_cover'),entry['t2'].get('cloud_cover')
            if c1 is not None and c2 is not None: cloud_cover_pct=max(c1,c2)
        imagery_date_skew_days=None
        if entry and entry.get('t2') and r.get('ACTUAL_END_DATE'):
            try:
                t2_date=pd.to_datetime(entry['t2']['datetime']).tz_localize(None)
                end_date=pd.to_datetime(r['ACTUAL_END_DATE'],format='%d-%b-%Y')
                imagery_date_skew_days=abs((t2_date-end_date).days)
            except (ValueError,TypeError): pass
        eligibility=check_satellite_eligibility(
            has_coordinates=r.get('lat') is not None and r.get('lon') is not None,
            geocode_confidence=geocode_confidence,
            has_before_image=bool(entry and entry.get('t1')), has_after_image=bool(entry and entry.get('t2')),
            imagery_date_skew_days=imagery_date_skew_days, cloud_cover_pct=cloud_cover_pct, asset_category=r.get('category'))
        result['satellite_eligibility']={'status':eligibility.status,'reason':eligibility.reason,
            'resolution_m':eligibility.resolution_m,'asset_min_visible_size_m':eligibility.asset_min_visible_size_m,
            'cloud_cover_pct':eligibility.cloud_cover_pct,'geocode_confidence':eligibility.geocode_confidence,
            'imagery_date_skew_days':imagery_date_skew_days}
        # Only an 'eligible' work's change-detection result is ever shown -
        # every other status is a reason the check couldn't be attempted,
        # never "no change found". change_visible/no_reliable_change_visible
        # are the only two outcomes a reviewer sees; the exact language is
        # from pipeline/satellite_eligibility.py so it's never paraphrased
        # into something stronger (e.g. "not built").
        result['change_result']=None
        if eligibility.status=='eligible':
            change=app.state.satellite_change_by_asset.get(asset_id)
            if change is not None:
                detected=bool(change.get('change_detected'))
                result['change_result']={
                    'outcome':'change_visible' if detected else 'no_reliable_change_visible',
                    'message':CHANGE_DETECTED_LANGUAGE if detected else NO_CHANGE_LANGUAGE,
                    'confidence':change.get('confidence'),'ndvi_delta':change.get('ndvi_delta'),
                    'pixel_diff_score':change.get('pixel_diff_score'),
                    'method':'NDVI delta + normalized pixel diff (ml/cv/satellite_change.py)',
                    'limitations':'A screening result, not proof of completion or absence - never a fraud finding.'}
        # The displayed image and the NDVI signal can come from different
        # real sources with different dates (see
        # pipeline/fetch_highres_quicklooks.py) - t1_date/t2_date describe
        # what the JPEG actually shows (Esri World Imagery Wayback, if
        # upgraded; falls back to the Sentinel-2 capture date otherwise),
        # never the Sentinel-2 date the pixels weren't taken on.
        result['imagery']={'satellite_verification_applicable':True,
            't1_date':entry['t1'].get('rgb_datetime',entry['t1']['datetime'][:10]) if entry else None,
            't2_date':entry['t2'].get('rgb_datetime',entry['t2']['datetime'][:10]) if entry else None,
            'image_source':entry['t1'].get('rgb_source','sentinel-2-l2a') if entry else None,
            'ndvi_t1_date':entry['t1']['datetime'][:10] if entry else None,
            'ndvi_t2_date':entry['t2']['datetime'][:10] if entry else None,
            't1_image':f'/satellite/image/{asset_id}/t1' if entry else None,
            't2_image':f'/satellite/image/{asset_id}/t2' if entry else None} if entry else \
            {'satellite_verification_applicable':True,'note':'No imagery fetched yet for this asset.'}
    else:
        # Branch B: never render as missing evidence - it was never satellite-
        # checkable to begin with (docs/SATELLITE_VENDOR_MODULE_PLAN.md #4).
        result['satellite_eligibility']={'status':'asset_below_resolution',
            'reason':'This work category is not satellite-visible by design (Branch B).','resolution_m':None,
            'asset_min_visible_size_m':None,'cloud_cover_pct':None,'geocode_confidence':None}
        result['imagery']={'satellite_verification_applicable':False,
            'note':'Satellite verification not applicable to this work category.'}
    result['vendor']=next((v for v in app.state.vendor_network if v['vendor_id']==r.get('vendor_id')),None)
    with connection() as con:
        invs=[dict(zip(INVESTIGATION_COLUMNS,x)) for x in con.execute(ph('SELECT * FROM investigations WHERE work_id=?'),(work_id,)).fetchall()]
    result['investigations']=invs
    result['review_notice']=SAT_NOTICE
    return result

@app.get('/satellite/image/{asset_id}/{tag}')
def satellite_image(asset_id:str,tag:Literal['t1','t2']):
    # Unauthenticated, same reasoning as /image/{work_id}/{filename}: <img> tags
    # can't send Authorization, and this is demo evidence, not sensitive data.
    # Phase 5 section E path-traversal fix: unlike /image/{work_id}/{filename}
    # (which only ever serves a filename already validated against
    # app.state.images), asset_id here used to go straight into a filesystem
    # path with no allowlist check - a backslash-containing asset_id (a
    # literal path separator on Windows, though not on Linux) could escape
    # satellite_cache/. Now checked against the real known asset ids AND the
    # resolved path is confirmed to still live inside satellite_cache/, so
    # neither an unknown asset_id nor a crafted one can reach another file.
    if asset_id not in app.state.satellite_asset_ids:
        raise HTTPException(404,'Satellite image not found')
    cache_dir=(DATA/'satellite_cache').resolve()
    path=(cache_dir/f'{asset_id}_{tag}_rgb.jpg').resolve()
    if not path.is_relative_to(cache_dir) or not path.exists():
        raise HTTPException(404,'Satellite image not found')
    return FileResponse(path,media_type='image/jpeg')

@app.get('/vendor-network')
def vendor_network(me:dict=Depends(current_persona),flagged_only:bool=False):
    rows=app.state.vendor_network
    if flagged_only: rows=[v for v in rows if v['network_risk_score']>0.3]
    return {'total':len(rows),'notice':SAT_NOTICE,'items':rows}

# --- Data quality (rupee normalization / data-quality alerts / lineage) ---
# Alerts contribute zero to fraud risk and are never merged into signals_json
# or risk_score - see pipeline/data_quality.py. Jurisdiction-scoped like every
# other endpoint below (Phase 2): each alert carries the mp_name/state_name/
# constituency of the row it came from (set in run_quality_checks), so the
# same persona['filter'] default-deny matching used for /works applies here
# too - an empty filter (Ministry) still means national access, a narrow
# filter still excludes anything whose jurisdiction can't be matched.
# Resolutions persist in their own table, keyed by the alert's stable id
# (source+work_id+field+quality_code+raw-value fingerprint -
# pipeline/data_quality.alert_id), so a resolution survives the next
# pipeline rerun as long as the underlying raw value didn't change; if it
# did, the previous id's resolution row is left untouched as history and a
# new, currently-open alert appears for the new value.
QUALITY_NOTICE='Data-quality issues reduce analytical confidence; they are not evidence of fraud.'
QualityStatus=Literal['open','resolved','dismissed']
QualitySeverity=Literal['info','warning','critical']
QUALITY_FIELD_MAP={'MP_NAME':'mp_name','STATE_NAME':'state_name','CONSTITUENCY':'constituency'}

def scope_quality(pid):
    filters=persona(pid)['filter']
    return [a for a in app.state.quality_alerts if filter_matches(a.get,filters,QUALITY_FIELD_MAP)]

def quality_resolutions():
    with connection() as con:
        rows=con.execute('SELECT alert_id,status,reason,persona_id,decided_at FROM quality_resolutions').fetchall()
    return {r[0]:{'status':r[1],'reason':r[2],'resolved_by':r[3],'resolved_at':r[4]} for r in rows}

def quality_alert_view(alert,resolutions):
    res=resolutions.get(alert['id'])
    if res: return {**alert,'status':res['status'],'resolution_reason':res['reason'],'resolved_by':res['resolved_by'],'resolved_at':res['resolved_at']}
    return {**alert,'resolution_reason':None,'resolved_by':None,'resolved_at':None}

@app.get('/quality/alerts')
def quality_alerts(me:dict=Depends(current_persona),severity:QualitySeverity|None=None,
                    quality_code:str|None=None,status:QualityStatus|None=None,work_id:str|None=None,
                    include_info:bool=False,q:str='',offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200)):
    resolutions=quality_resolutions()
    rows=[quality_alert_view(a,resolutions) for a in scope_quality(me['id'])]
    if severity: rows=[r for r in rows if r['severity']==severity]
    elif not include_info: rows=[r for r in rows if r['severity']!='info']  # default: actionable warning/critical only
    if quality_code: rows=[r for r in rows if r['quality_code']==quality_code]
    if work_id: rows=[r for r in rows if r['work_id']==work_id]
    if status: rows=[r for r in rows if r['status']==status]
    if q: rows=[r for r in rows if q.lower() in ' '.join(str(r.get(k,'')) for k in ['work_id','field','raw_value','explanation']).lower()]
    severity_rank={'critical':0,'warning':1,'info':2}
    # Stable sort: severity, then work_id, then the alert's own id - so
    # pagination never reshuffles rows between requests.
    rows.sort(key=lambda r:(severity_rank.get(r['severity'],3),r['work_id'] or '',r['id']))
    counts={'severity':{s:sum(1 for r in rows if r['severity']==s) for s in ('critical','warning','info')},
            'status':{s:sum(1 for r in rows if r['status']==s) for s in ('open','resolved','dismissed')}}
    return {'total':len(rows),'records_affected':len({r['work_id'] for r in rows if r['work_id']}),
            'counts':counts,'notice':QUALITY_NOTICE,'items':rows[offset:offset+limit]}

@app.get('/quality/alerts/groups')
def quality_alert_groups(me:dict=Depends(current_persona),severity:QualitySeverity|None=None):
    """Repeated low-severity issues collapsed by root cause (quality_code +
    field), for a UI's expandable "informational issues" section - a count
    and one sample, not thousands of near-identical rows."""
    resolutions=quality_resolutions()
    rows=[quality_alert_view(a,resolutions) for a in scope_quality(me['id'])]
    if severity: rows=[r for r in rows if r['severity']==severity]
    groups:dict[str,dict]={}
    for r in rows:
        g=groups.setdefault(r['group_key'],{'group_key':r['group_key'],'quality_code':r['quality_code'],
                                              'field':r['field'],'severity':r['severity'],'count':0,
                                              'open_count':0,'sample_explanation':r['explanation'],'sample_alert_id':r['id']})
        g['count']+=1
        if r['status']=='open': g['open_count']+=1
    return {'groups':sorted(groups.values(),key=lambda g:g['count'],reverse=True)}

@app.get('/quality/alerts/{alert_id}')
def quality_alert_detail(alert_id:str,me:dict=Depends(current_persona)):
    alert=app.state.quality_by_id.get(alert_id)
    if alert is None: raise HTTPException(404,'Quality alert not found')
    if alert not in scope_quality(me['id']):
        audit_event('access_denied',user_id=me['user_id'],persona_id=me['id'],role=me['role'],
                     entity_type='quality_alert',entity_id=alert_id,action='read',success=False)
        raise FORBIDDEN()
    result=quality_alert_view(alert,quality_resolutions())
    result['lineage']=app.state.lineage.get(alert['work_id'],[]) if alert['work_id'] else []
    result['notice']=QUALITY_NOTICE
    return result

def _work_jurisdiction(work_id):
    return app.state.work_directory.get(work_id)

@app.get('/quality/lineage/{work_id}')
def quality_lineage(work_id:str,me:dict=Depends(current_persona)):
    entries=app.state.lineage.get(work_id)
    if entries is None: raise HTTPException(404,'No lineage recorded for this work')
    jurisdiction=_work_jurisdiction(work_id) or {}
    filters=persona(me['id'])['filter']
    if not filter_matches(jurisdiction.get,filters,QUALITY_FIELD_MAP):
        audit_event('access_denied',user_id=me['user_id'],persona_id=me['id'],role=me['role'],
                     entity_type='lineage',entity_id=work_id,action='read',success=False)
        raise FORBIDDEN()
    return {'work_id':work_id,'entries':entries}

class QualityResolution(BaseModel):
    status:Literal['resolved','dismissed']
    reason:str=Field(min_length=1,max_length=4000)
    @field_validator('reason')
    @classmethod
    def reason_not_blank(cls,value):
        if not value.strip(): raise ValueError('A reason is required')
        return value.strip()

@app.post('/quality/alerts/{alert_id}/resolve')
def resolve_quality_alert(alert_id:str,body:QualityResolution,me:dict=Depends(current_persona)):
    alert=app.state.quality_by_id.get(alert_id)
    if alert is None: raise HTTPException(404,'Quality alert not found')
    if alert not in scope_quality(me['id']):
        audit_event('access_denied',user_id=me['user_id'],persona_id=me['id'],role=me['role'],
                     entity_type='quality_alert',entity_id=alert_id,action='resolve',success=False)
        raise FORBIDDEN()
    previous=quality_resolutions().get(alert_id)
    now=datetime.now(timezone.utc).isoformat()
    with connection() as con:
        con.execute(ph('INSERT INTO quality_resolutions VALUES (?,?,?,?,?) ON CONFLICT(alert_id) DO UPDATE SET status=excluded.status,reason=excluded.reason,persona_id=excluded.persona_id,decided_at=excluded.decided_at'),
                    (alert_id,body.status,body.reason,me['id'],now))
    audit_event('quality_alert_resolved',user_id=me['user_id'],persona_id=me['id'],role=me['role'],
                entity_type='quality_alert',entity_id=alert_id,action=body.status,reason=body.reason,
                before_state={'status':previous['status']} if previous else {'status':'open'},
                after_state={'status':body.status})
    return quality_alert_view(app.state.quality_by_id[alert_id],{alert_id:{'status':body.status,'reason':body.reason,'resolved_by':me['id'],'resolved_at':now}})

@app.get('/quality/summary')
def quality_summary(me:dict=Depends(current_persona)):
    rows=[quality_alert_view(a,quality_resolutions()) for a in scope_quality(me['id'])]
    return {'total':len(rows),'records_affected':len({r['work_id'] for r in rows if r['work_id']}),
            'severity':{s:sum(1 for r in rows if r['severity']==s) for s in ('critical','warning','info')},
            'status':{s:sum(1 for r in rows if r['status']==s) for s in ('open','resolved','dismissed')},
            'notice':QUALITY_NOTICE}

# --- Audit log (Phase 2) --- append-only; Ministry only (national role), same
# least-privilege reasoning as any other cross-jurisdiction aggregate view.
@app.get('/audit')
def audit_log(me:dict=Depends(current_persona),event_type:str|None=None,user_id:str|None=None,
              offset:int=Query(0,ge=0),limit:int=Query(50,ge=1,le=200)):
    if me['id']!='ministry':
        audit_event('access_denied',user_id=me['user_id'],persona_id=me['id'],role=me['role'],
                     entity_type='audit_log',action='read',success=False,detail='non-Ministry role attempted /audit')
        raise FORBIDDEN('Audit history is national-role only')
    clauses,params=[],[]
    if event_type: clauses.append('event_type=?'); params.append(event_type)
    if user_id: clauses.append('user_id=?'); params.append(user_id)
    where=(' WHERE '+' AND '.join(clauses)) if clauses else ''
    with connection() as con:
        total=con.execute(ph(f'SELECT COUNT(*) FROM audit_events{where}'),params).fetchone()[0]
        cols=['id','event_type','user_id','persona_id','role','entity_type','entity_id','action','reason',
              'before_state','after_state','success','detail','created_at']
        rows=con.execute(ph(f'SELECT {",".join(cols)} FROM audit_events{where} ORDER BY created_at DESC LIMIT ? OFFSET ?'),
                          params+[limit,offset]).fetchall()
    items=[dict(zip(cols,r)) for r in rows]
    for item in items:
        item['success']=bool(item['success'])
        for k in ('before_state','after_state'):
            item[k]=json.loads(item[k]) if item[k] else None
    return {'total':total,'items':items}

# --- Cases (Phase 3) ---
# A case is a consolidated, reviewable unit (pipeline/cases.py) - never a raw
# alert count. Descriptive/evidence fields (context, fired/candidate signals,
# priorities, unavailable checks) come from app.state.case_candidates,
# regenerated every pipeline run; workflow STATE (status, history, notes)
# lives only in the `cases`/`case_history`/`reviewer_notes` SQL tables and is
# never touched by a rerun unless the case_id itself changes (which only
# happens when the underlying evidence materially changes - see
# pipeline/cases.case_id).
WORKFLOW_STATUSES = ('NEW', 'TRIAGED', 'UNDER_REVIEW', 'INFORMATION_REQUESTED', 'REFERRED',
                      'RESOLVED_NO_ISSUE', 'RESOLVED_CORRECTIVE_ACTION', 'CLOSED')
ALLOWED_TRANSITIONS = {
    'NEW': {'TRIAGED', 'RESOLVED_NO_ISSUE'},
    'TRIAGED': {'UNDER_REVIEW', 'RESOLVED_NO_ISSUE'},
    'UNDER_REVIEW': {'INFORMATION_REQUESTED', 'REFERRED', 'RESOLVED_NO_ISSUE', 'RESOLVED_CORRECTIVE_ACTION'},
    'INFORMATION_REQUESTED': {'UNDER_REVIEW', 'RESOLVED_NO_ISSUE'},
    'REFERRED': {'RESOLVED_NO_ISSUE', 'RESOLVED_CORRECTIVE_ACTION'},
    'RESOLVED_NO_ISSUE': {'CLOSED', 'UNDER_REVIEW'},          # UNDER_REVIEW here = reopen
    'RESOLVED_CORRECTIVE_ACTION': {'CLOSED', 'UNDER_REVIEW'},  # reopen
    'CLOSED': {'UNDER_REVIEW'},                                # reopen
}
# Reopening = any transition FROM a resolved/closed status - always requires a reason,
# regardless of the target, on top of the target-specific set below.
TERMINAL_STATUSES = {'RESOLVED_NO_ISSUE', 'RESOLVED_CORRECTIVE_ACTION', 'CLOSED'}
REASON_REQUIRED_TARGETS = {'RESOLVED_NO_ISSUE', 'RESOLVED_CORRECTIVE_ACTION', 'REFERRED'}
# District/MP handle first-line triage and dismissal; escalation (referral),
# final corrective-action determination, closure and reopening a resolved
# case are reserved for State Nodal / Ministry - the same "higher authority
# for final determination" reasoning as Confirm being Ministry-final in
# Phase 1's investigations workflow.
ROLE_ALLOWED_TARGETS = {
    'mp_office': {'TRIAGED', 'UNDER_REVIEW', 'INFORMATION_REQUESTED', 'RESOLVED_NO_ISSUE'},
    'district_authority': {'TRIAGED', 'UNDER_REVIEW', 'INFORMATION_REQUESTED', 'RESOLVED_NO_ISSUE'},
    'state_nodal': {'TRIAGED', 'UNDER_REVIEW', 'INFORMATION_REQUESTED', 'REFERRED', 'RESOLVED_NO_ISSUE',
                     'RESOLVED_CORRECTIVE_ACTION', 'CLOSED'},
    'ministry': set(WORKFLOW_STATUSES) - {'NEW'},
}
CASE_FIELD_MAP = {'MP_NAME': 'mp_name', 'STATE_NAME': 'state_name', 'CONSTITUENCY': 'constituency'}

def scope_cases(pid):
    filters = persona(pid)['filter']
    return [c for c in app.state.case_candidates if filter_matches(c['context'].get, filters, CASE_FIELD_MAP)]

def case_db_row(case_id):
    with connection() as con:
        row = con.execute(ph('SELECT case_id,work_id,status,source,created_at,updated_at FROM cases WHERE case_id=?'), (case_id,)).fetchone()
    return None if row is None else dict(zip(('case_id', 'work_id', 'status', 'source', 'created_at', 'updated_at'), row))

def case_view(candidate, db_row):
    return {**candidate, 'status': db_row['status'], 'source': db_row['source'],
            'created_at': db_row['created_at'], 'updated_at': db_row['updated_at']}

def get_case_or_404(case_id):
    candidate = app.state.case_by_id.get(case_id)
    db_row = case_db_row(case_id)
    if candidate is None or db_row is None:
        raise HTTPException(404, 'Case not found')
    return candidate, db_row

def require_case_scope(candidate, me):
    if candidate not in scope_cases(me['id']):
        audit_event('access_denied', user_id=me['user_id'], persona_id=me['id'], role=me['role'],
                     entity_type='case', entity_id=candidate['case_id'], action='read', success=False)
        raise FORBIDDEN()

@app.get('/cases')
def list_cases(me: dict = Depends(current_persona), signal_code: str | None = None, signal_family: Literal['anomaly', 'inefficiency'] | None = None,
               status: str | None = None, state_name: str | None = None, constituency: str | None = None,
               work_category: str | None = None, min_evidence_completeness: float | None = None,
               sort: Literal['priority', 'evidence_completeness', 'created_at'] = 'priority',
               review_tier: Literal['actionable', 'systemic_cohort', 'all'] | None = None,
               q: str = '', offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    candidates = scope_cases(me['id'])
    views = [case_view(c, case_db_row(c['case_id'])) for c in candidates]
    views = [v for v in views if v['status'] is not None]  # defensive: db row always exists post-merge
    review_tier_counts = {'actionable': sum(1 for v in views if v.get('review_tier', 'actionable') == 'actionable'),
                           'systemic_cohort': sum(1 for v in views if v.get('review_tier') == 'systemic_cohort')}
    if review_tier and review_tier != 'all':
        views = [v for v in views if v.get('review_tier', 'actionable') == review_tier]
    elif review_tier is None:
        # Phase 5 A.2 default queue: a late-sanction-only case that isn't
        # exceptionally severe stays out of the default actionable queue -
        # UNLESS a reviewer has already engaged with it (status != NEW),
        # which is this case's form of "a reviewer manually escalates it".
        views = [v for v in views if v.get('review_tier', 'actionable') == 'actionable' or v['status'] != 'NEW']
    if signal_code: views = [v for v in views if signal_code in v['signal_codes'] or any(s['signal_code'] == signal_code for s in v['fired_signals'])]
    if signal_family: views = [v for v in views if any(s['signal_family'] == signal_family for s in v['fired_signals'])]
    if status: views = [v for v in views if v['status'] == status]
    if state_name: views = [v for v in views if jurisdiction_matches(v['context'].get('state_name'), [state_name])]
    if constituency: views = [v for v in views if jurisdiction_matches(v['context'].get('constituency'), [constituency])]
    if work_category: views = [v for v in views if jurisdiction_matches(v['context'].get('work_category'), [work_category])]
    if min_evidence_completeness is not None: views = [v for v in views if v['evidence_completeness'] >= min_evidence_completeness]
    if q:
        ql = q.lower()
        views = [v for v in views if ql in ' '.join(str(x) for x in
                 (v['work_id'], v['context'].get('work_description'), v['context'].get('mp_name'))).lower()]
    sort_key = {'priority': lambda v: v['anomaly_priority'] + v['inefficiency_priority'],
                'evidence_completeness': lambda v: v['evidence_completeness'],
                'created_at': lambda v: v['created_at']}[sort]
    views.sort(key=lambda v: (sort_key(v), v['case_id']), reverse=True)
    counts = {s: sum(1 for v in views if v['status'] == s) for s in WORKFLOW_STATUSES}
    return {'total': len(views), 'status_counts': counts, 'review_tier_counts': review_tier_counts, 'items': views[offset:offset + limit]}

@app.get('/cases/{case_id}')
def get_case(case_id: str, me: dict = Depends(current_persona)):
    candidate, db_row = get_case_or_404(case_id)
    require_case_scope(candidate, me)
    return case_view(candidate, db_row)

@app.get('/cases/{case_id}/history')
def case_history(case_id: str, me: dict = Depends(current_persona)):
    """District/State/MP users see the action history of cases WITHIN THEIR
    SCOPE (not the global /audit log, which stays Ministry-only) - the same
    row-level data, filtered to one case a persona is already allowed to view."""
    candidate, _ = get_case_or_404(case_id)
    require_case_scope(candidate, me)
    with connection() as con:
        rows = con.execute(ph('SELECT id,from_status,to_status,action,user_id,persona_id,role,reason,created_at '
                               'FROM case_history WHERE case_id=? ORDER BY created_at ASC'), (case_id,)).fetchall()
    cols = ('id', 'from_status', 'to_status', 'action', 'user_id', 'persona_id', 'role', 'reason', 'created_at')
    return {'case_id': case_id, 'items': [dict(zip(cols, r)) for r in rows]}

class CaseTransition(BaseModel):
    to_status: Literal[*WORKFLOW_STATUSES]
    reason: str | None = Field(default=None, max_length=4000)

@app.post('/cases/{case_id}/transition')
def transition_case(case_id: str, body: CaseTransition, me: dict = Depends(current_persona)):
    candidate, db_row = get_case_or_404(case_id)
    require_case_scope(candidate, me)
    current, target = db_row['status'], body.to_status
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise HTTPException(422, f'Cannot move a case from {current} to {target}')
    if target not in ROLE_ALLOWED_TARGETS.get(me['id'], set()):
        audit_event('access_denied', user_id=me['user_id'], persona_id=me['id'], role=me['role'],
                     entity_type='case', entity_id=case_id, action=f'transition:{target}', success=False)
        raise FORBIDDEN(f'{me["role"]} may not set a case to {target}')
    reopening = current in TERMINAL_STATUSES
    reason_required = target in REASON_REQUIRED_TARGETS or reopening
    if reason_required and not (body.reason or '').strip():
        raise HTTPException(422, 'A reason is required for this transition')
    now = datetime.now(timezone.utc).isoformat()
    with connection() as con:
        con.execute(ph('UPDATE cases SET status=?,updated_at=? WHERE case_id=?'), (target, now, case_id))
        con.execute(ph('INSERT INTO case_history VALUES (?,?,?,?,?,?,?,?,?,?)'),
                    (uuid.uuid4().hex, case_id, current, target, 'reopen' if reopening else 'transition',
                     me['user_id'], me['id'], me['role'], body.reason, now))
    audit_event('status_change', user_id=me['user_id'], persona_id=me['id'], role=me['role'],
                entity_type='case', entity_id=case_id, action=target, reason=body.reason,
                before_state={'status': current}, after_state={'status': target})
    return case_view(candidate, case_db_row(case_id))

class CaseEscalation(BaseModel):
    work_id: str
    reason: str = Field(min_length=1, max_length=4000)
    @field_validator('reason')
    @classmethod
    def reason_not_blank(cls, value):
        if not value.strip(): raise ValueError('A reason is required')
        return value.strip()

@app.post('/cases/escalate')
def escalate_case(body: CaseEscalation, me: dict = Depends(current_persona)):
    """A reviewer's own judgment call, independent of the automatic
    strong-signal / two-medium-cluster rule - always requires a reason, and
    is scoped to works the caller can already see (no escalating a work
    outside your own jurisdiction)."""
    row = work(body.work_id, me['id'])  # 404/403 exactly like any other work lookup
    now = datetime.now(timezone.utc).isoformat()
    case_id = f'manual-{uuid.uuid4().hex[:16]}'
    description = row.get('WORK_DESCRIPTION')
    context = {'work_description': description, 'mp_name': row.get('MP_NAME'), 'state_name': row.get('STATE_NAME'),
               'constituency': row.get('CONSTITUENCY'), 'work_category': None, 'actual_amount': row.get('ACTUAL_AMOUNT')}
    candidate = {'case_id': case_id, 'work_id': body.work_id, 'context': context,
                 'clusters_fired': [], 'anomaly_priority': 0.0, 'inefficiency_priority': 0.0,
                 'evidence_completeness': None, 'source_data_confidence': None, 'signal_codes': [],
                 'fired_signals': [], 'candidate_signals': [], 'unavailable_checks': [],
                 'what_happened': description, 'why_flagged': [f'Manually escalated by {me["role"]}: {body.reason}'],
                 'recommended_action': 'Reviewer-initiated - see escalation reason.', 'fingerprint': None,
                 'detector_version': 'manual-escalation-v1', 'data_mode': 'real', 'source': 'manual_escalation',
                 'source_record_ref': f'/works/{body.work_id}'}
    app.state.case_candidates.append(candidate)
    app.state.case_by_id[case_id] = candidate
    with connection() as con:
        con.execute(ph('INSERT INTO cases VALUES (?,?,?,?,?,?)'), (case_id, body.work_id, 'NEW', 'manual_escalation', now, now))
        con.execute(ph('INSERT INTO case_history VALUES (?,?,?,?,?,?,?,?,?,?)'),
                    (uuid.uuid4().hex, case_id, None, 'NEW', 'manual_escalation', me['user_id'], me['id'], me['role'], body.reason, now))
        # Phase 4 A.2: immutable snapshot so this case reconstructs after a
        # restart - case_candidates.json never contains manual escalations.
        con.execute(ph('INSERT INTO case_context_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)'),
                    (case_id, body.work_id, description, description, context['mp_name'], context['state_name'],
                     context['constituency'], context['work_category'], context['actual_amount'], 'manual_escalation',
                     'real', body.reason, me['user_id'], me['role'], now, f'/works/{body.work_id}'))
    audit_event('manual_escalation', user_id=me['user_id'], persona_id=me['id'], role=me['role'],
                entity_type='case', entity_id=case_id, action='escalate', reason=body.reason, after_state={'status': 'NEW'})
    return case_view(candidate, case_db_row(case_id))

class ReviewerNote(BaseModel):
    note: str = Field(min_length=1, max_length=4000)
    @field_validator('note')
    @classmethod
    def note_not_blank(cls, value):
        if not value.strip(): raise ValueError('A note is required')
        return value.strip()

@app.post('/cases/{case_id}/notes')
def add_case_note(case_id: str, body: ReviewerNote, me: dict = Depends(current_persona)):
    candidate, _ = get_case_or_404(case_id)
    require_case_scope(candidate, me)
    now = datetime.now(timezone.utc).isoformat()
    note_id = uuid.uuid4().hex
    with connection() as con:
        con.execute(ph('INSERT INTO reviewer_notes VALUES (?,?,?,?,?,?,?)'),
                    (note_id, case_id, me['user_id'], me['id'], me['role'], body.note, now))
    audit_event('note_created', user_id=me['user_id'], persona_id=me['id'], role=me['role'],
                entity_type='case', entity_id=case_id, action='note', reason=body.note)
    return {'id': note_id, 'case_id': case_id, 'user_id': me['user_id'], 'role': me['role'], 'note': body.note, 'created_at': now}

@app.get('/cases/{case_id}/notes')
def list_case_notes(case_id: str, me: dict = Depends(current_persona)):
    candidate, _ = get_case_or_404(case_id)
    require_case_scope(candidate, me)
    with connection() as con:
        rows = con.execute(ph('SELECT id,user_id,persona_id,role,note,created_at FROM reviewer_notes '
                               'WHERE case_id=? ORDER BY created_at ASC'), (case_id,)).fetchall()
    cols = ('id', 'user_id', 'persona_id', 'role', 'note', 'created_at')
    return {'case_id': case_id, 'items': [dict(zip(cols, r)) for r in rows]}

@app.get('/metrics')
def operational_metrics(me: dict = Depends(current_persona)):
    """Every number here is derived from stored reviewer activity
    (case_history) - if the data needed for a metric doesn't exist,
    it's reported `unavailable`, never invented (Phase 3 instructions, §7)."""
    scoped_ids = {c['case_id'] for c in scope_cases(me['id'])}
    if not scoped_ids:
        return {'open_reviewable_cases': 0, 'cases_resolved': 0, 'median_time_to_first_review': 'unavailable',
                'median_case_resolution_time': 'unavailable', 'cases_resolved_per_investigator_hour': 'unavailable',
                'dismissal_rate_by_signal': {}, 'escalation_rate_by_signal': {}, 'raw_signals_consolidated_per_case': 'unavailable'}
    with connection() as con:
        placeholders = ','.join(['?'] * len(scoped_ids))
        case_rows = con.execute(ph(f'SELECT case_id,status,created_at,updated_at FROM cases WHERE case_id IN ({placeholders})'),
                                 list(scoped_ids)).fetchall()
        history_rows = con.execute(ph(f'SELECT case_id,to_status,created_at FROM case_history WHERE case_id IN ({placeholders}) ORDER BY created_at ASC'),
                                    list(scoped_ids)).fetchall()
    cases_by_id = {r[0]: {'status': r[1], 'created_at': r[2], 'updated_at': r[3]} for r in case_rows}
    first_move, resolved_at = {}, {}
    for case_id, to_status, created_at in history_rows:
        if case_id not in first_move: first_move[case_id] = created_at
        if to_status in TERMINAL_STATUSES: resolved_at.setdefault(case_id, created_at)
    def hours_between(a, b):
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 3600
    open_count = sum(1 for c in cases_by_id.values() if c['status'] not in TERMINAL_STATUSES)
    resolved_count = sum(1 for c in cases_by_id.values() if c['status'] in TERMINAL_STATUSES)
    first_review_hours = [hours_between(cases_by_id[cid]['created_at'], ts) for cid, ts in first_move.items() if cid in cases_by_id]
    resolution_hours = [hours_between(cases_by_id[cid]['created_at'], ts) for cid, ts in resolved_at.items() if cid in cases_by_id]
    dismissed = defaultdict(int); escalated = defaultdict(int); total_by_signal = defaultdict(int)
    for c in scope_cases(me['id']):
        codes = {s['signal_code'] for s in c['fired_signals']}
        status = cases_by_id.get(c['case_id'], {}).get('status')
        for code in codes:
            total_by_signal[code] += 1
            if status == 'RESOLVED_NO_ISSUE': dismissed[code] += 1
            if status in ('REFERRED', 'RESOLVED_CORRECTIVE_ACTION'): escalated[code] += 1
    raw_signal_total = sum(len(c['fired_signals']) for c in scope_cases(me['id']))
    # Phase 4 section K: only ever computed from explicit, recorded active
    # review-session duration - never inferred from case age.
    with connection() as con:
        placeholders = ','.join(['?'] * len(scoped_ids))
        session_rows = con.execute(ph(f'SELECT case_id,started_at,ended_at FROM case_review_sessions '
                                       f'WHERE case_id IN ({placeholders}) AND ended_at IS NOT NULL'), list(scoped_ids)).fetchall()
    total_active_hours = sum((datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds() / 3600
                              for _, started, ended in session_rows)
    per_investigator_hour = round(resolved_count / total_active_hours, 3) if total_active_hours > 0 else 'unavailable'
    return {
        'open_reviewable_cases': open_count, 'cases_resolved': resolved_count,
        'median_time_to_first_review': round(median(first_review_hours), 1) if first_review_hours else 'unavailable',
        'median_case_resolution_time': round(median(resolution_hours), 1) if resolution_hours else 'unavailable',
        'cases_resolved_per_investigator_hour': per_investigator_hour,
        'dismissal_rate_by_signal': {k: round(dismissed[k] / v, 3) for k, v in total_by_signal.items()},
        'escalation_rate_by_signal': {k: round(escalated[k] / v, 3) for k, v in total_by_signal.items()},
        'raw_signals_consolidated_per_case': round(raw_signal_total / len(scoped_ids), 2) if scoped_ids else 'unavailable',
    }

# --- Review-session timing (Phase 4 section K) ---
# "Do not infer investigator effort from total case age." These two endpoints
# are the explicit alternative: a reviewer starts a timed session on a case,
# ends it, and only THAT recorded active duration - never case creation-to-
# resolution wall-clock time - feeds cases_resolved_per_investigator_hour
# above. No session data recorded anywhere yet in this prototype, so that
# metric stays 'unavailable' until some exist (see operational_metrics).
@app.post('/cases/{case_id}/review-session/start')
def start_review_session(case_id: str, me: dict = Depends(current_persona)):
    candidate, _ = get_case_or_404(case_id)
    require_case_scope(candidate, me)
    session_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    with connection() as con:
        con.execute(ph('INSERT INTO case_review_sessions VALUES (?,?,?,?,?,?)'),
                    (session_id, case_id, me['user_id'], me['id'], now, None))
    return {'session_id': session_id, 'case_id': case_id, 'started_at': now}

@app.post('/cases/{case_id}/review-session/{session_id}/end')
def end_review_session(case_id: str, session_id: str, me: dict = Depends(current_persona)):
    candidate, _ = get_case_or_404(case_id)
    require_case_scope(candidate, me)
    with connection() as con:
        row = con.execute(ph('SELECT user_id,started_at,ended_at FROM case_review_sessions WHERE id=? AND case_id=?'),
                           (session_id, case_id)).fetchone()
        if row is None: raise HTTPException(404, 'Review session not found')
        if row[0] != me['user_id']: raise FORBIDDEN('Only the reviewer who started a session may end it')
        if row[2] is not None: raise HTTPException(422, 'Session already ended')
        now = datetime.now(timezone.utc).isoformat()
        con.execute(ph('UPDATE case_review_sessions SET ended_at=? WHERE id=?'), (now, session_id))
    active_hours = (datetime.fromisoformat(now) - datetime.fromisoformat(row[1])).total_seconds() / 3600
    return {'session_id': session_id, 'case_id': case_id, 'started_at': row[1], 'ended_at': now, 'active_hours': round(active_hours, 3)}

# --- Image Evidence Workspace (Phase 4 sections B-I) ---
# Descriptive/metric data (app.state.image_matches) is regenerated every
# pipeline run from pipeline/image_evidence.py's classify_image_pair - never
# recomputed inside a request (mandatory safeguard #4). Reviewer decisions
# live in image_match_reviews, append-only, keyed by the deterministic
# match_id so a decision survives a rerun unless the underlying images,
# preprocessing or detector version materially changed (a changed version
# produces a different match_id entirely - see pipeline/image_evidence.py).
IMAGE_REVIEW_ACTIONS = ('confirm_visual_correspondence', 'dismiss_watermark', 'dismiss_generic_similarity',
                        'mark_legitimate_before_after', 'mark_corrected_resubmitted', 'request_original_image',
                        'request_site_inspection', 'escalate_for_investigation', 'add_note')
# Deliberately absent from IMAGE_REVIEW_ACTIONS: any "declare fraud" action.
# confirm_visual_correspondence means exactly CLASSIFICATION_MEANINGS says -
# geometric correspondence requiring review, never a fraud finding.

def _match_jurisdiction_ok(match, pid):
    filters = persona(pid)['filter']
    ja = app.state.work_directory.get(match['work_id_a']) or {}
    jb = app.state.work_directory.get(match['work_id_b']) or {}
    return filter_matches(ja.get, filters, CASE_FIELD_MAP) and filter_matches(jb.get, filters, CASE_FIELD_MAP)

def scope_image_matches(pid):
    return [m for m in app.state.image_matches if _match_jurisdiction_ok(m, pid)]

def image_match_reviews(match_id):
    with connection() as con:
        rows = con.execute(ph('SELECT id,action,reason,note,user_id,persona_id,role,created_at FROM '
                               'image_match_reviews WHERE match_id=? ORDER BY created_at ASC'), (match_id,)).fetchall()
    cols = ('id', 'action', 'reason', 'note', 'user_id', 'persona_id', 'role', 'created_at')
    return [dict(zip(cols, r)) for r in rows]

def image_match_view(match):
    reviews = image_match_reviews(match['match_id'])
    return {**match, 'latest_action': reviews[-1]['action'] if reviews else None, 'review_count': len(reviews)}

@app.get('/images/matches')
def list_image_matches(me: dict = Depends(current_persona), classification: str | None = None,
                        risk_eligible: bool | None = None, work_id: str | None = None,
                        offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    matches = [image_match_view(m) for m in scope_image_matches(me['id'])]
    if classification: matches = [m for m in matches if m['classification'] == classification]
    if risk_eligible is not None: matches = [m for m in matches if m['risk_eligible'] == risk_eligible]
    if work_id: matches = [m for m in matches if work_id in (m['work_id_a'], m['work_id_b'])]
    matches.sort(key=lambda m: (m['risk_eligible'], m['match_id']), reverse=True)
    counts = {c: sum(1 for m in matches if m['classification'] == c) for c in CLASSIFICATIONS}
    return {'total': len(matches), 'classification_counts': counts, 'items': matches[offset:offset + limit]}

@app.get('/images/matches/{match_id}')
def get_image_match(match_id: str, me: dict = Depends(current_persona)):
    match = app.state.image_match_by_id.get(match_id)
    if match is None: raise HTTPException(404, 'Image match not found')
    if not _match_jurisdiction_ok(match, me['id']):
        audit_event('access_denied', user_id=me['user_id'], persona_id=me['id'], role=me['role'],
                     entity_type='image_match', entity_id=match_id, action='read', success=False,
                     detail='one or both paired works are outside this account’s jurisdiction')
        raise FORBIDDEN('One or both works in this pair are outside your jurisdiction - route this to a role with access to both (e.g. Ministry).')
    result = image_match_view(match)
    result['reviews'] = image_match_reviews(match_id)
    result['classification_meaning'] = CLASSIFICATION_MEANINGS.get(match['classification'])
    return result

@app.get('/images/matches/{match_id}/reviews')
def get_image_match_reviews(match_id: str, me: dict = Depends(current_persona)):
    match = app.state.image_match_by_id.get(match_id)
    if match is None: raise HTTPException(404, 'Image match not found')
    if not _match_jurisdiction_ok(match, me['id']): raise FORBIDDEN()
    return {'match_id': match_id, 'items': image_match_reviews(match_id)}

class ImageMatchReview(BaseModel):
    action: Literal[*IMAGE_REVIEW_ACTIONS]
    reason: str | None = Field(default=None, max_length=4000)
    note: str | None = Field(default=None, max_length=4000)

@app.post('/images/matches/{match_id}/review')
def review_image_match(match_id: str, body: ImageMatchReview, me: dict = Depends(current_persona)):
    match = app.state.image_match_by_id.get(match_id)
    if match is None: raise HTTPException(404, 'Image match not found')
    if not _match_jurisdiction_ok(match, me['id']):
        audit_event('access_denied', user_id=me['user_id'], persona_id=me['id'], role=me['role'],
                     entity_type='image_match', entity_id=match_id, action=f'review:{body.action}', success=False)
        raise FORBIDDEN('One or both works in this pair are outside your jurisdiction.')
    previous = image_match_reviews(match_id)
    before_status = previous[-1]['action'] if previous else None
    now = datetime.now(timezone.utc).isoformat()
    with connection() as con:
        con.execute(ph('INSERT INTO image_match_reviews VALUES (?,?,?,?,?,?,?,?,?,?,?)'),
                    (uuid.uuid4().hex, match_id, body.action, body.reason, body.note, me['user_id'], me['id'], me['role'],
                     json.dumps({'action': before_status}), json.dumps({'action': body.action}), now))
    audit_event('image_match_reviewed', user_id=me['user_id'], persona_id=me['id'], role=me['role'],
                entity_type='image_match', entity_id=match_id, action=body.action, reason=body.reason or body.note,
                before_state={'action': before_status}, after_state={'action': body.action})
    return image_match_view(match)

if (ROOT/'frontend/dist').exists():
    app.mount('/',StaticFiles(directory=ROOT/'frontend/dist',html=True),name='frontend')

