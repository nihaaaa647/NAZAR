# NAZAR — Tech stack: what runs today vs. what is planned

SIH 2026, Problem Statement 26102 (MoSPI) — "AI-powered detection of anomalies,
fraud and inefficiencies in MPLADS scheme implementation."

This document has two halves:

1. **Current stack** — every technology actually in the repository and running
   today, verified against `requirements.txt`, `frontend/package.json`, and the
   code in `scripts/`, `backend/`, `pipelines/` and `frontend/src/`.
2. **Planned stack** — the target architecture for the full product, drawn from
   `docs/blueprint.md` (Parts A/F), `feature_plan.md` and `astra/PHASE_*.md`,
   split into the *Internal-round MVP target*, the *Grand Finale* layer and the
   *Production / Future Scope* layer.

Where the two disagree, the current stack is the truth and the difference is
called out. The guiding constraint on both is the master prompt's rule: reach for
heavy infrastructure or ML only when a simpler, explainable construction provably
cannot do the job.

---

## Part 1 — Current stack (what runs today)

The prototype today is a single-machine, batch-scored, read-only review tool:
CSV/Parquet in, a FastAPI service + React dashboard out, SQLite only for the
reviewer's own Confirm/Dismiss notes.

### 1.1 Languages & runtimes

| Layer | Technology | Version | Notes |
|---|---|---|---|
| Backend / ML / pipeline | **Python** | 3.12.14 | Blueprint assumed 3.13 + full ML stack; the verified runtime is 3.12 with the Phase-0/1 packages only (`docs/DATA_REALITY.md` F8). |
| Frontend | **TypeScript** | ~5.8.3 | `tsc -b` in the build step. |
| Frontend runtime | **Node.js** (dev/build only) | — | Not part of the served runtime; Vite builds static assets. |
| Shell / ops | PowerShell (primary), Bash | — | Windows 11 dev machine. |

### 1.2 Data ingestion & scraping (pre-existing, unchanged)

| Purpose | Technology | Where |
|---|---|---|
| Portal scrape (per-constituency REST pull from `mplads.mospi.gov.in`) | `requests` + a hand-rolled polite client (0.6 s delay, capped retries, exponential backoff) | `mplads_common.py`, `mplads_india_downloader.py`, `backfill_sanctioned.py`, `mplads_telangana*.py` |
| Resumable progress | JSON progress files (`_progress.json`) | scraper scripts |
| Raw output | Per-constituency `works_with_images.csv`, `works_sanctioned.csv` + attachment files (mostly PDF-wrapped JPEG scans) | `mplads_india/**` (git-ignored) |

The scrapers are treated as frozen: not parallelised, not sped up.

### 1.3 Data layer (current)

| Concern | Technology | Notes |
|---|---|---|
| Canonical dataset | **CSV** (`data/canonical/works.csv`) via `pipelines/ingest.py` | Deterministic snapshot, atomic single-file replace, joins completed + sanctioned on `WORK_RECOMMENDATION_DTL_ID`. **No database** — the operator explicitly chose "CSV files for now" (`docs/DECISIONS.md`). |
| Scored pipeline output | **Parquet** (`data/scored_works.parquet`) | Read into memory by the API at startup. |
| Pipeline artefacts | JSON (`data/duplicate_pairs.json`, `data/images.json`, `data/personas.json`, `reports/pipeline.json`, `reports/evaluation.json`) | |
| Image cache | Extracted JPEG bytes on disk (`data/image_cache/`), keyed by size + mtime | |
| Reviewer decisions | **SQLite** (`data/investigations.sqlite3`), stdlib `sqlite3` | One table: `investigations(work_id, persona_id, decision, reason, decided_at)`. This is the *only* database in the running system. |
| Dataframes / columnar | **pandas** 3.0.1, **NumPy** 2.3.5, **pyarrow** 25.0.1 | |

### 1.4 Scoring pipeline / "engines" (current)

All in `scripts/pipeline.py`, run once as a batch over the local corpus
(5,611 completed works, 5 states, 79 constituencies). Detailed in
`docs/ENGINES_EXPLAINED.md`.

| Signal | Technique | Library |
|---|---|---|
| Cost-vs-peers | Robust z-score (median / MAD) over an `activity_norm × state` peer group with a fallback ladder | NumPy / pandas |
| Missing completion evidence | `image_count == 0` advisory | pandas |
| Suspicious round amount | Distance-to-lakh-multiple heuristic (explicitly **not** a sourced legal rule) | pandas |
| Multivariate outlier | **`sklearn.ensemble.IsolationForest`** (+ `RobustScaler`), fit once on the whole corpus, `contamination=0.05`, `n_estimators=150`, `random_state=42` | scikit-learn 1.9.0 |
| Photo reuse — Tier 1 | MD5 byte-identity across `work_id`s, gated by a 150 px min-dimension floor | hashlib, Pillow |
| Photo reuse — Tier 2 | DCT perceptual hash (`phash`) + Hamming distance, adaptive threshold, Union-Find clustering, common-template suppression | `scipy.fftpack.dct`, NumPy, Pillow 12.3.0 |
| Text duplicate — exact | Normalized description match across fiscal years, scoped per MP | pandas |
| Text duplicate — near | **`difflib.SequenceMatcher`** ratio > 0.90 | stdlib |
| PDF → JPEG extraction | Byte-scan for `FF D8 FF … FF D9` markers (no PDF library) | stdlib + Pillow |
| Risk fusion | Deterministic weighted sum (weights sum to 100) + severity floor | plain Python |

**Not built yet** (blueprint promises these; code does not have them): SIFT/ORB
keypoint confirmation, sentence-transformer embeddings, per-category model
fitting, SHAP, idle-fund detector (Engine 5), fund-absorption forecast
(Engine 6), the calibration loop (Engine 8). `sentence-transformers`, `torch`,
`opencv`, `imagehash` and `shap` are **not installed**.

### 1.5 Validation harness (current)

| Purpose | Technology | Where |
|---|---|---|
| Synthetic fraud-injection sensitivity check | Clones real rows into CAG-shaped patterns, re-runs the *same* detector functions, isolated under `reports/synthetic/`, never enters the shipping dataset | `scripts/evaluate.py` |
| Patterns tested | Image reuse (10/10), cross-year duplicate claim (10/10), high-amount-no-evidence (missing 10/10, Isolation Forest 7/10) | `reports/evaluation.json` |

### 1.6 Backend API (current)

| Concern | Technology | Version | Notes |
|---|---|---|---|
| Web framework | **FastAPI** | 0.141.1 | `backend/main.py`, single file |
| ASGI server | **uvicorn** | 0.52.4 | |
| Validation | **Pydantic** | (bundled with FastAPI) | request/response models |
| Auth | **HMAC-SHA256 signed bearer token**, stdlib only | — | *Not* JWT. One fixed demo account per persona, 8 h TTL, `Authorization: Bearer`. No signup / reset / password hashing / per-user accounts. `NAZAR_USERS` / `NAZAR_AUTH_SECRET` env overrides. |
| Authorization | Per-request jurisdiction filter from the token's persona (`scope()` / `work()` in `backend/main.py`) | — | Enforced server-side, in the query layer. |
| Static hosting | `fastapi.staticfiles` serves `frontend/dist` when present | — | Single-origin deploy: API + UI on one port. |
| Data access | In-memory list from Parquet + `sqlite3` for investigations | — | No ORM. |
| Test client | **httpx** | 0.28.1 | |

Endpoints today: `/auth/login`, `/auth/me`, `/personas`, `/signals`, `/works`,
`/works/{id}`, `/works/{id}/duplicates`, `/image/{work_id}/{filename}`,
`/investigations`, `/summary`, `/evaluation`. (Blueprint Part E lists more —
`/alerts`, `/feedback`, `/analytics/*`, `/health` — not implemented.)

### 1.7 Frontend (current)

| Concern | Technology | Version | Notes |
|---|---|---|---|
| UI library | **React** | 19.1.0 | Blueprint said React 18; repo is on 19. |
| Build tool / dev server | **Vite** | 6.3.5 | `@vitejs/plugin-react` 4.5; dev proxy to `127.0.0.1:8000` in `vite.config.ts` |
| Language | TypeScript 5.8 | | |
| Charts | **Recharts** | 3.0.0 | bar charts on the dashboard |
| Icons | **lucide-react** | 0.468.0 | |
| Styling | Hand-written `src/style.css` (bundled) **+ Tailwind Play CDN** (`cdn.tailwindcss.com` in `index.html`) | — | Optional Google Fonts. Core CSS works offline; CDN is a network dependency. |
| State | React hooks only (no Redux despite `node_modules` presence) | — | App is one `App.tsx`. |

The app is currently a **single screen** (login → overview dashboard with a
work-detail modal). Blueprint's Work Detail page, Alerts Queue, Analytics and
Data Health screens are not built as separate routes.

### 1.8 Testing & tooling (current)

| Purpose | Technology |
|---|---|
| Python tests | **pytest** 9.1.1 (`tests/test_consolidate.py`, `test_profile_data.py`, `test_ingest.py`, `test_photo_duplicates.py`) |
| Env pinning | `requirements.txt` with exact pins; project-local `.venv` |
| Data audit | `scripts/profile_data.py` (read-only profiler → `reports/data_profile.json`) |
| Prototype smoke checks | `scripts/check_prototype.py` |
| Version control | Git (branch `master`; PRs against `main`) |
| Date parsing | `python-dateutil` |

### 1.9 What is deliberately absent today

No PostgreSQL, no SQLAlchemy/Alembic, no JWT, no Docker/Docker Compose running,
no APScheduler, no Redis, no Neo4j, no PostGIS, no FAISS/vector DB, no
`sentence-transformers`, no OpenCV, no `torch`, no SHAP, no Tesseract/OCR, no
mapping library, no CI. Every one of these is either a later-phase item or
explicitly excluded at this scale.

---

## Part 2 — Planned stack

### 2.1 Internal-round MVP target (blueprint Parts A & F, `astra/PHASE_2–7`)

This is the "finish the eight engines + real dashboard + deployment" target. It
is the same shape as today, with the gaps filled and the infrastructure the
blueprint specified.

| Category | Planned technology | Delta vs. today |
|---|---|---|
| **Database** | **PostgreSQL** + **SQLAlchemy / SQLModel** + **Alembic** migrations | Replaces CSV/Parquet/SQLite as the system of record. Tables per blueprint Part D: `work`, `work_image`, `duplicate_pair`, `risk_signal`, `risk_score`, `alert`, `investigation`, `feedback`, `model_version`, `fraud_injection_case`, `user_account`, `audit_log`. SQLite kept as the SQLAlchemy-portable local-dev fallback. |
| **Pipeline output** | Parquet retained for the raw/consolidated pipeline stage | unchanged pattern |
| **Auth** | **JWT** (`python-jose`) + **passlib** password hashing | replaces the HMAC demo token |
| **RBAC** | Role + `jurisdiction_scope` on every user; middleware filters every query; four distinct login classes (MP office / District Authority / State Nodal / Ministry) + Admin, each with a different landing view and aggregation level | today's single-filter persona scoping becomes real per-role aggregation |
| **Batch orchestration** | **APScheduler** or cron — scheduled/manual "ingest → features → engines → fusion" run | no message queue (Celery/RabbitMQ) at this scale |
| **Rule engine (Engine 1)** | Deterministic checks with **sourced** citations: 75-day recommendation-to-sanction deadline, ₹5 cr per-MP entitlement, ₹75 L trust/society ceiling, ₹25 L outside-constituency limit. Unsourced ₹10 L rule stays a labelled heuristic. | today only has the round-amount heuristic |
| **Anomaly (Engine 2)** | scikit-learn `IsolationForest` **fit per activity family**, `contamination` justified from a plotted distribution; **SHAP** for per-feature attribution | today: one global fit, z-score stand-in for SHAP |
| **Photo reuse (Engine 3)** | `imagehash` pHash primary scan **+ OpenCV SIFT/ORB** inlier confirmation on candidate pairs only; PDF→image **triage stage** classifying `junk_watermark` / `scanned_document` / `site_photo` / `photo_collage` | today: hand-rolled pHash, MD5 tier, byte-scan extraction, no keypoint pass |
| **Text duplicates (Engine 4)** | **`sentence-transformers` (`all-MiniLM-L6-v2`)** embeddings + agglomerative cosine clustering across fiscal years; in-memory cosine (no FAISS at this scale) | today: exact + `difflib` string matching only |
| **Idle funds (Engine 5)** | Percentile threshold on `days_since_sanction` vs peer group, built on `WORK_STAGE` + real `SANCTION_DATE` | not built today |
| **Absorption forecast (Engine 6)** | Per-MP/state linear trend / moving average on quarterly utilisation vs the ₹5 cr entitlement, with a confidence band, labelled low-confidence | not built today |
| **Risk fusion (Engine 7)** | Weighted sum + severity floor (already the current approach) — formalised, weights from CAG severity ranking | essentially exists |
| **Calibration (Engine 8)** | Bounded per-engine weight nudge from rolling confirm/dismiss rates (min N=10 decisions, ±10 %/cycle cap) — not a supervised classifier | not built today |
| **Backend framework** | FastAPI + Pydantic | unchanged |
| **Frontend** | React + TypeScript + Vite + **Recharts / Nivo**; full screen set: Dashboard Home, Work Detail (Rules / Anomaly / Photos / Duplicates tabs), Alerts Queue, Investigation Form, Analytics, Data Health badge | today: one screen + modal |
| **Deployment** | **Docker Compose** (backend, frontend, Postgres, pipeline runner) — one command from a clean checkout. **No Kubernetes.** | not running today |
| **Testing** | pytest + **pytest-cov**; unit tests on thresholds, fusion, jurisdiction scoping, parsers, synthetic isolation; integration tests on the API; ≥1 end-to-end ingestion→alert test | today: 4 unit test files |
| **Observability** | Structured logging + `/health` endpoint (feeds the Source-Freshness Monitor) — no dedicated APM stack | not built today |
| **Secrets** | `.env` + committed `.env.example` | partially (env overrides exist) |
| **Storage (photos)** | Filesystem in the demo; **S3-compatible object storage** in production | filesystem today |

Deliberately still excluded at MVP scale: PostGIS, Neo4j, a vector database,
Redis, FAISS, Kubernetes, blockchain — each documented with the Future-Scope
trigger condition that would justify it.

### 2.2 Grand Finale layer (design now, build after qualification)

New capabilities and the technology each introduces:

| Feature | New technology / method |
|---|---|
| Illegal State-Transition Detector | temporal/state-machine checks on sanction vs completion ordering (no new infra) |
| Version-History Integrity Monitor | content hashing of record versions (the "tamper-evidence without blockchain" answer) |
| Source-Freshness Monitor | freshness metrics on the ingest feed behind `/health` |
| **JanNirikshan** (citizen asset confirmation) | public-facing lightweight web/mobile capture flow |
| Outgoing-MP Closure Tracker | join against public parliamentary tenure-end records |
| **SatelliteScout** | **Sentinel-2 (Copernicus / Sentinel Hub)** or **ISRO Bhuvan** before/after imagery, NDVI / pixel-diff change detection — every result to a human-review queue, never an auto-verdict |
| DINOv2 near-duplicate-scene + CLIP category-mismatch | **DINOv2** (self-supervised ViT) embeddings + cosine clustering; **CLIP** zero-shot image-vs-category — pretrained, CPU inference, low-weight/advisory |
| Benford's Law agency check | `scipy.stats` chi-square vs Benford curve, per-IDA (n ≥ 30) |
| Government Cost Baselines | ingest State PWD Schedule-of-Rates (SSR/DSR) + PMGSY per-km costs (scattered PDFs) |
| Ongoing CAG Report Mining | recurring document ingestion from `cag.gov.in` audit reports |
| Mapping (once real coordinates exist) | **Leaflet** — explicitly reserved for this layer, not the MVP |
| OCR / document intelligence (conditional) | **Tesseract** OCR over scanned Measurement Books / completion certificates / GPS pixel overlays — gated on a Phase-1 prevalence measurement; needs a system-level binary and operator sign-off |

### 2.3 Production / Future Scope layer (pending real government data access)

These are blocked on data-sharing agreements, not engineering. Technology
implications:

| Feature cluster | Technology it would add |
|---|---|
| eSAKSHI–PFMS reconciliation, Sanction-Limit Breach, Statutory Charge Checker, Exception Control Tower | integrations with government financial systems (PFMS, eSAKSHI); rules engine extensions |
| Shared-Contact / Shared-Address clusters, Probabilistic Record-Linkage, Pass-Through Vendor, BidRing Radar | **Neo4j** (or equivalent graph store) for vendor/entity graphs; probabilistic record-linkage libraries |
| Coordinate-Jitter Detector | **PostGIS** for spatial queries once real coordinates exist |
| Cross-Scheme Duplicate Detector | cross-dataset entity resolution at national scale — **FAISS** (or another ANN index) for nearest-neighbour lookup instead of pairwise |
| Image-Manipulation Risk Detector | Error Level Analysis / forensic CV (higher false-positive complexity) |
| DocShield, ClauseGuard, GrievanceFusion, GeM Award Mirror, Guideline Change Impact | document-understanding models, contract NLP, marketplace-price scraping/APIs |
| National scale generally | object storage (S3), a proper secrets manager (e.g. **Vault**), horizontal API scaling, per-IP/token rate limiting at a gateway |

### 2.4 Explicitly rejected across all layers

| Rejected | Reason (from blueprint / master prompt) |
|---|---|
| **Blockchain** | audit-log table + version hashing give the same tamper-evidence without the latency/governance overhead |
| **Kubernetes** | unjustified complexity at demo/pilot scale; Docker Compose is enough |
| **Redis** | no caching need at demo traffic |
| **Message queue (Celery/Kafka/RabbitMQ)** | batch pipeline at this data volume doesn't need it |
| **A trained fraud classifier** | there are no fraud labels anywhere in MPLADS data — the whole stack is unsupervised / rule-based / deterministic by necessity |
| **GPU / `torch` CUDA** | the target machines are CPU-only |
| **EXIF integrity checker** | portal strips most photo metadata before scrape (though some EXIF and pixel-burned GPS survive — see `docs/DATA_REALITY.md` F3) |
| **ResNet50-ImageNet embeddings** | cluster by object category, not instance identity — wrong bias; DINOv2 replaces it |

---

## Summary — the one-paragraph version

**Today:** Python 3.12, pandas/NumPy/pyarrow for data, a single-file
`scikit-learn` + `scipy` + `Pillow` batch scorer, CSV + Parquet + a tiny SQLite
notes table, a one-file FastAPI service with an HMAC demo token and server-side
jurisdiction filtering, and a one-screen React 19 + Vite + Recharts dashboard.
Validation is a synthetic injection harness. No database server, no JWT, no
Docker, no deep-learning dependencies.

**Planned MVP:** same languages and frameworks, plus PostgreSQL/SQLAlchemy/Alembic,
JWT auth, real per-role RBAC, APScheduler batch runs, the five missing engines
(SHAP, per-family Isolation Forest, `imagehash` + OpenCV SIFT/ORB, `sentence-transformers`,
idle-fund and forecast models, calibration loop), a full multi-screen dashboard,
and Docker Compose deployment.

**Grand Finale & Production:** Leaflet + Sentinel-2/Bhuvan satellite checks,
DINOv2/CLIP, Tesseract OCR, Benford checks, CAG-report mining, then — only with
real government data access — Neo4j vendor graphs, PostGIS, FAISS, PFMS/eSAKSHI/GeM
integrations, and object storage + Vault for national scale. Blockchain and
Kubernetes stay out at every layer.
