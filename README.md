# NAZAR

**Evidence-led review tool for MPLADS works.** NAZAR scores completed MPLADS works
for unusual patterns, links the supporting evidence, and puts a human reviewer in
front of every signal. A flag is an invitation to look closer — never a finding of
misconduct.

Built for Smart India Hackathon 2026, Problem Statement **26102** (MoSPI):
*"AI-powered detection of anomalies, fraud and inefficiencies in MPLADS scheme
implementation."*

> **Scope note.** This is a prototype on a partial corpus (5 states, 79
> constituencies). Thresholds are review heuristics, not legal rules. There is no
> trained fraud model — MPLADS has no fraud labels — so every signal is
> unsupervised, rule-based or statistical, and needs human judgement. See
> [Limitations](#limitations).

## Contents

- [What it does](#what-it-does)
- [Architecture at a glance](#architecture-at-a-glance)
- [Quick start](#quick-start)
- [Development mode](#development-mode)
- [Deploy (Vercel + Render)](#deploy-vercel--render)
- [Sign-in and the four personas](#sign-in-and-the-four-personas)
- [The review workflow](#the-review-workflow)
- [Scoring signals](#scoring-signals)
- [HTTP API](#http-api)
- [Configuration](#configuration)
- [Data and how to regenerate it](#data-and-how-to-regenerate-it)
- [Tests and checks](#tests-and-checks)
- [Validation results](#validation-results)
- [Project layout](#project-layout)
- [Limitations](#limitations)
- [Documentation index](#documentation-index)

## What it does

- Ingests scraped MPLADS completed-work records plus their PDF/JPEG attachments.
- Runs a one-pass batch scorer (`scripts/pipeline.py`) that produces, per work:
  eight computational signals, a 0–100 risk score, and a severity band
  (Low / Moderate / High / Critical).
- Detects reused completion photos (byte-identical and perceptual-hash) and
  work descriptions duplicated across fiscal years.
- Serves a role-scoped review dashboard: each of the four MPLADS authority levels
  (MP Office, District Authority, State Nodal Authority, Ministry) signs in to its
  own jurisdiction.
- Lets a reviewer record a **Confirm** or **Dismiss** decision, with a required
  reason, on any work.
- When the **Ministry** confirms a work it moves to a `Confirmed` status and
  appears on a dedicated **Confirmed** page for every authority whose jurisdiction
  contains it — surfaced on the MP's own view as a confirmed concern, with the
  Ministry's recorded reason.
- Ships a synthetic fraud-injection harness (`scripts/evaluate.py`) that measures
  detector sensitivity without ever touching the real dataset.

## Architecture at a glance

```
raw corpus (CSV + attachments — scraped separately, git-ignored, not redistributed)
    │
    ├─ pipelines/ingest.py ──► data/canonical/works.csv     deterministic snapshot (completed ⨝ sanctioned)
    │
    └─ scripts/pipeline.py ──► data/scored_works.parquet    signals + risk score + severity band
                               data/duplicate_pairs.json    evidence links (reused photos, duplicate text)
                               data/personas.json           role → jurisdiction filter
                               data/images.json + data/image_cache/
                               reports/pipeline.json
       scripts/evaluate.py ──► reports/evaluation.json/.md   synthetic sensitivity report

backend/main.py   FastAPI + uvicorn  (single file)
    • loads the parquet + JSON into memory at startup
    • HMAC-signed bearer token carries {persona, jurisdiction}
    • every query is filtered server-side by the token's jurisdiction
    • SQLite (data/investigations.sqlite3) is the only writable store: reviewer decisions
    • serves frontend/dist when built → API + UI on one origin, one port

frontend/   React 19 + TypeScript + Vite + Recharts
    • Overview: login → review queue + work-detail modal
    • Confirmed: Ministry-confirmed works for the signed-in jurisdiction
```

**Stack:** Python 3.12, pandas / NumPy / pyarrow, scikit-learn (`IsolationForest`),
SciPy, Pillow; FastAPI / uvicorn / Pydantic; React 19 / Vite 6 / Recharts /
lucide-react. No database server, no JWT, no Docker, no deep-learning
dependencies. Full inventory and the planned production stack:
[`docs/TECH_STACK.md`](docs/TECH_STACK.md).

## Quick start

**Prerequisites:** Windows dev machine (commands below use `cmd` / PowerShell),
Python 3.12, Node.js 18+.

The raw MPLADS corpus is **not** in the repository (scraped government data,
git-ignored). You need either the corpus folder (`mplads_india/`) or a prebuilt
`data/` directory. **If `data/scored_works.parquet` already exists, skip steps 3–4.**

```cmd
:: 1. Python environment (skip if .venv is already present)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

:: 2. Frontend dependencies
npm --prefix frontend install

:: 3. Score every work. Point at the corpus with --root PATH or NAZAR_DATA_ROOT;
::    defaults to .\mplads_india, then ..\sih\mplads_india. No scraper is run.
.venv\Scripts\python.exe scripts\pipeline.py

:: 4. Generate the synthetic validation report (optional; /evaluation needs it)
.venv\Scripts\python.exe scripts\evaluate.py

:: 5. Build the frontend
npm --prefix frontend run build

:: 6. Run — API and UI on one port
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

Open **http://127.0.0.1:8000** and sign in.

macOS / Linux: identical steps with `.venv/bin/python` and forward slashes.

## Development mode

Run the backend and the Vite dev server separately for hot reload:

```cmd
:: terminal 1 — API with autoreload
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000 --reload

:: terminal 2 — Vite dev server on http://127.0.0.1:5173, proxying API paths to :8000
npm --prefix frontend run dev
```

Open **http://127.0.0.1:5173**. The list of API paths the dev server proxies lives
in [`frontend/vite.config.ts`](frontend/vite.config.ts) — add new backend routes
there as well, or the dev server will 404 them.

## Deploy (Vercel + Render)

Vercel is serverless (no persistent disk, no long-running process), so it can
only host the **frontend**. The **backend** — FastAPI + SQLite + the image cache
— needs somewhere that keeps a process and a filesystem alive; this repo is set
up for **Render** (a free web service works). They talk to each other over CORS.

The raw corpus is 7.1 GB and the full local `data/image_cache/` is 5.6 GB —
neither is in git and neither is going on a free host. Only 355 of its 3,574
images are ever actually shown (the ones referenced by `duplicate_pairs.json`
evidence); [`scripts/prepare_deploy_data.py`](scripts/prepare_deploy_data.py)
copies just those, downscaled, into a **63 MB** `deploy_data/` snapshot — small
enough to commit directly, no Git LFS needed. Nothing about scoring or evidence
changes; only the pixels served for "open full-resolution evidence" get smaller.

```cmd
:: 1. Build the deploy snapshot (needs data/ from the Quick start steps above)
.venv\Scripts\python.exe scripts\prepare_deploy_data.py
git add deploy_data && git commit -m "Add deploy data snapshot" && git push
```

**Backend → Render:**
1. [dashboard.render.com](https://dashboard.render.com) → **New → Blueprint** →
   connect this repo. Render reads [`render.yaml`](render.yaml) and creates a
   `nazar-api` web service: `NAZAR_DATA_DIR=deploy_data`,
   `NAZAR_AUTH_SECRET` auto-generated, CORS open (`*`) by default.
2. Deploy. Copy the resulting URL, e.g. `https://nazar-api.onrender.com`.
3. Free-plan caveat: the filesystem is ephemeral and the service sleeps after
   15 minutes idle. `deploy_data/` (read-only) survives every restart because
   it's part of the deployed code; `investigations.sqlite3` (review decisions)
   does **not** — it resets on the next cold start. Fine for a demo; move
   `NAZAR_DB_PATH` onto a paid plan's persistent Disk, or swap SQLite for a
   hosted DB, if decisions must survive that.

**Frontend → Vercel:**
1. [vercel.com/new](https://vercel.com/new) → import this repo → set
   **Root Directory** to `frontend` (Vercel auto-detects the Vite build).
2. Add an environment variable `VITE_API_BASE` = the Render URL from above, no
   trailing slash (e.g. `https://nazar-api.onrender.com`). Empty/unset means
   "same origin as the frontend," which is wrong once they're on separate hosts.
3. Deploy. Once you have the Vercel URL, go back to Render and tighten
   `NAZAR_CORS_ORIGINS` from `*` to that exact URL.

Sign in with the same [demo accounts](#sign-in-and-the-four-personas) as local.

## Sign-in and the four personas

Sign-in is a **makeshift demo gate**, not identity management: one fixed account
per persona, verified server-side, which issues an HMAC-SHA256 signed bearer token
(8 h TTL) carrying the role and jurisdiction. There is no role picker — the
account *is* the role.

| Persona | User ID | Password | Sees |
|---|---|---|---|
| MP Office | `mp.office` | `mp-lookcloser-24` | one MP's works in one constituency (NIZAMABAD) |
| District Authority | `district.authority` | `district-lookcloser-24` | a 3-constituency cluster in Bihar (demo grouping, not an official boundary) |
| State Nodal Authority | `state.nodal` | `state-lookcloser-24` | all loaded works in Bihar |
| Ministry | `ministry` | `ministry-lookcloser-24` | the whole loaded corpus (5 states, 79 constituencies) |

Jurisdiction is enforced server-side on every request. Override the accounts with
`NAZAR_USERS` and **always** set `NAZAR_AUTH_SECRET` for any shared deployment
(see [Configuration](#configuration)).

## The review workflow

1. **Queue.** Each persona lands on its jurisdiction's review queue, ranked by
   risk score. Filter by severity band, by status
   (`Flagged` / `Under Review` / `Confirmed` / `Dismissed`), or by *which* signal
   fired ("Any review signal").
2. **Work detail.** Open a work to see every signal with its plain-language
   reason, the risk breakdown, and side-by-side evidence pairs (reused photos,
   duplicate descriptions). Linked evidence is shown across jurisdictions for
   context.
3. **Record a decision.** Confirm or Dismiss with a required free-text reason.
   Decisions are stored per persona in SQLite.
4. **Status transitions.**
   - A decision by a narrower persona → `Under Review`.
   - **Ministry Confirm → `Confirmed`** (final). The work appears on the
     **Confirmed** page for every persona whose jurisdiction contains it; on the
     MP's view it is shown as a confirmed potential-fraud concern, with the
     Ministry's reason.
   - **Ministry Dismiss → `Dismissed`** (final).

   Every confirmed surface keeps the standing caveat: a confirmation is a review
   decision, not a court finding of misconduct.

## Scoring signals

`scripts/pipeline.py` runs once, as a batch, over the local corpus. Full
explanation with the maths: [`docs/ENGINES_EXPLAINED.md`](docs/ENGINES_EXPLAINED.md).

| Signal | What it checks | Method | Weight |
|---|---|---|---:|
| `cost_peer` | amount far **above** its activity×state peers (one-sided — a low amount is shown for context, never flagged) | robust z-score (median / MAD), peer-group fallback ladder, min 10 peers | 15 |
| `anomaly` | multivariate outlier vs peers | `sklearn` IsolationForest, one global fit, `contamination=0.05`, `n_estimators=150` | 15 |
| `photo_identical` | the same completion photo reused across works | MD5 byte-identity, ≥ 150 px min-dimension floor (scanner-app footers gated out) | 25 |
| `photo_similar` | visually near-identical photos | DCT perceptual hash + Hamming distance, adaptive threshold, common-template suppression | 10 |
| `text_exact` | identical work description in another fiscal year, same MP | normalized string match | 20 |
| `text_similar` | > 90 % similar description across fiscal years, same MP | `difflib.SequenceMatcher` | 5 |
| `missing_evidence` | zero source-listed attachments (advisory) | `image_count == 0` | 5 |
| `round_amount` | amount suspiciously close to a lakh multiple (heuristic, no sourced legal basis) | distance-to-multiple | 5 |

**Risk score** = weighted sum of the normalized signal scores (0–100).
**Severity band:** *Critical* if a `photo_identical` or `text_exact` match is
present or risk > 80; *High* > 60; *Moderate* > 30; otherwise *Low*.

*Not built yet* (the blueprint promises these; the code does not have them):
SIFT/ORB keypoint confirmation, sentence-transformer embeddings, per-category
model fitting, SHAP, an idle-fund detector, a fund-absorption forecast, and the
calibration loop.

## HTTP API

Every route except `/auth/login` and `/image/*` requires
`Authorization: Bearer <token>`. `/image/*` is token-free by design (an `<img>`
tag cannot send headers) but is still work/filename pair-checked. Interactive docs
at `/docs` while the server runs.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/login` | `{user_id, password}` → `{token, expires_in, persona}` |
| `GET` | `/auth/me` | resolve the current persona from the token |
| `GET` | `/personas` | all persona definitions |
| `GET` | `/signals` | signal keys, labels, and per-view flagged counts |
| `GET` | `/works` | review queue. Query: `severity`, `signal`, `status`, `sort` (`risk`\|`amount`), `q`, `offset`, `limit`. Returns `items` + `status_counts`. |
| `GET` | `/works/{id}` | one work: all signals, evidence, decision history, current status |
| `GET` | `/works/{id}/duplicates` | evidence pairs linked to this work |
| `GET` | `/confirmed` | Ministry-confirmed works in this jurisdiction, newest first, with the Ministry's reason and confirmation time |
| `GET` | `/image/{work_id}/{filename}` | an extracted attachment JPEG |
| `POST` | `/investigations` | `{work_id, decision: Confirm\|Dismiss, reason}` — upsert per persona |
| `GET` | `/summary` | jurisdiction KPIs: totals, severity histogram, confirmed count, amount, photo matches |
| `GET` | `/evaluation` | the synthetic validation report (503 until `scripts/evaluate.py` has run) |

## Configuration

All variables are optional; the defaults work out of the box for a local demo.
Template: [`.env.example`](.env.example) — it is **not** auto-loaded.

| Variable | Default | Purpose |
|---|---|---|
| `NAZAR_DATA_ROOT` / `--root` | `./mplads_india`, then `../sih/mplads_india` | where the pipeline reads raw `works_with_images.csv` files |
| `NAZAR_CANONICAL_ROOT` | `data/canonical` | canonical snapshot output directory |
| `NAZAR_DB_PATH` | `<data dir>/investigations.sqlite3` | reviewer-decisions SQLite file |
| `NAZAR_DATA_DIR` | `./data` | where the backend reads `scored_works.parquet` / `*.json` / `image_cache/` from — point this at `deploy_data/` for the trimmed deploy snapshot |
| `NAZAR_AUTH_SECRET` | `nazar-prototype-demo-secret` | HMAC token signing key — **set this for any shared deployment** |
| `NAZAR_USERS` | built-in demo accounts | `persona_id:user:pass,...` to override the logins |
| `NAZAR_TOKEN_TTL` | `28800` (8 h) | session token lifetime, in seconds |
| `NAZAR_CORS_ORIGINS` | `*` | comma-separated allowed origins — only matters when the frontend is deployed separately from this API (see [Deploy](#deploy-vercel--render)) |
| `VITE_API_BASE` *(frontend build-time)* | *(empty = same origin)* | the backend's URL, when the frontend is deployed separately — see [`frontend/.env.example`](frontend/.env.example) |

## Data and how to regenerate it

- The **raw corpus** (`mplads_india/`, `mplads_images/`) is scraped government
  data: git-ignored, not redistributed here. The scrapers
  (`mplads_*_downloader*.py`, `mplads_common.py`) are frozen and are **not** part
  of running this prototype.
- **Generated artifacts** (`data/`, `reports/synthetic/`, `frontend/dist/`) are
  git-ignored. Rebuild them:

```cmd
.venv\Scripts\python.exe -m pipelines.ingest        :: canonical CSV snapshot (optional — pipeline.py reads raw CSVs directly)
.venv\Scripts\python.exe scripts\pipeline.py         :: score every work
.venv\Scripts\python.exe scripts\evaluate.py         :: synthetic validation report
```

Current snapshot: **5,611 completed works**, 5 states, 79 constituencies
(Bihar 2,711 · Telangana 1,407 · Andhra Pradesh 1,065 · Arunachal Pradesh 221 ·
Assam 207). About 36 % of works have no listed attachment; a handful of PDFs fail
JPEG extraction and are logged in `reports/pipeline.json`. Measured corpus facts:
[`docs/DATA_REALITY.md`](docs/DATA_REALITY.md).

## Tests and checks

```cmd
.venv\Scripts\python.exe -m pytest -q                 :: unit tests: consolidate, ingest, profiler, photo dedup
.venv\Scripts\python.exe scripts\check_prototype.py   :: API / auth / scope / SQLite smoke checks + evidence contact sheets
.venv\Scripts\python.exe scripts\profile_data.py      :: read-only corpus audit → reports/data_profile.json
npm --prefix frontend run build                       :: TypeScript type-check + production bundle
```

## Validation results

`scripts/evaluate.py` clones real rows into CAG-shaped fraud patterns, re-runs the
**same** detector functions, and keeps every injected row and copied attachment
isolated under `reports/synthetic/`. Latest run (seed 42, 10 trials per pattern):

| Injected pattern | Detector | Recall |
|---|---|---:|
| Reused completion photo | byte-identical image match | 10 / 10 |
| Cross-year duplicate claim | exact normalized description match | 10 / 10 |
| High amount, no evidence | missing-evidence advisory | 10 / 10 |
| High amount, no evidence | Isolation Forest | 7 / 10 |

This is **synthetic sensitivity only** — not real-world precision and not a fraud
finding. Full reports: [`reports/evaluation.md`](reports/evaluation.md),
[`reports/verification.md`](reports/verification.md).

## Project layout

```
backend/main.py           FastAPI app (single file): auth, queue, work detail, decisions, /confirmed
frontend/src/App.tsx       React app (single file): login, dashboard, work modal, Confirmed page
frontend/vite.config.ts    dev-server API proxy allowlist
scripts/
  pipeline.py              batch scorer — signals, risk, bands, evidence pairs
  evaluate.py              synthetic fraud-injection sensitivity harness
  profile_data.py          read-only corpus audit
  check_prototype.py       API / SQLite smoke checks
  prepare_deploy_data.py   builds the trimmed deploy_data/ snapshot (see Deploy)
pipelines/ingest.py        deterministic canonical CSV snapshot (completed ⨝ sanctioned)
pipeline/consolidate.py    feature engineering, letter-number parsing
data/                      generated: scored_works.parquet, *.json, image_cache/, investigations.sqlite3
deploy_data/               committed: 355-image, 63 MB deploy snapshot — see Deploy
render.yaml                Render Blueprint for the backend
reports/                   generated: pipeline.json, evaluation.*, data_profile.json, verification.md
docs/                      TECH_STACK, ENGINES_EXPLAINED, DATA_REALITY, DECISIONS, blueprint, STATE
tests/                     pytest unit tests
astra/                     original phase briefs (historical — role and completion claims are not facts about this repo)
```

## Limitations

- **Not a fraud finding.** No fraud labels exist for MPLADS, so nothing here is
  trained on or predicts fraud. Every output is a computational signal for human
  review.
- **Partial corpus.** 5 states, 79 constituencies — no national conclusions.
- **Heuristic thresholds.** The round-amount rule and the pHash cutoff are review
  heuristics with no verified legal basis. No 2023 MPLADS guideline clauses are
  encoded.
- **Demo auth.** Fixed accounts; no signup, reset, password hashing, or per-user
  accounts. HMAC token, not JWT.
- **Amount ≠ unit cost.** MPLADS data has no quantity field, so "cost per unit" is
  the same number as the amount — disclosed, not hidden.
- **District clusters are a demo grouping**, not official boundaries.
- **Evidence extraction is limited** to byte-preserved embedded JPEGs; other PDF
  encodings are counted as extraction failures, not treated as "no evidence".
- **No SIFT/ORB, OCR, embeddings, or legal inference.** Validation is synthetic
  only.
- The Tailwind Play CDN and Google Fonts referenced in `frontend/index.html` are
  network dependencies; the core stylesheet is bundled and works offline.

## Documentation index

| Doc | Contents |
|---|---|
| [`docs/TECH_STACK.md`](docs/TECH_STACK.md) | every technology running today, plus the planned MVP / Grand Finale / production stack |
| [`docs/ENGINES_EXPLAINED.md`](docs/ENGINES_EXPLAINED.md) | how each signal is computed, in plain language, against the real code |
| [`docs/DATA_REALITY.md`](docs/DATA_REALITY.md) | measured facts about the corpus |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | dated implementation decisions and their rationale |
| [`docs/blueprint.md`](docs/blueprint.md) | full product design (aspirational; not all built) |
| [`docs/STATE.md`](docs/STATE.md) | phase checklist and known gaps |
| [`docs/INGESTION_README.md`](docs/INGESTION_README.md) | preserved earlier ingestion notes |
