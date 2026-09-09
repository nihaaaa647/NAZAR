# NAZAR execution state

_Last refreshed: 2026-09-09._

## Current phase

A working end-to-end prototype exists: raw corpus → batch scorer → in-memory
FastAPI service → role-scoped React dashboard, with a synthetic validation
harness. This covers a **compressed slice of blueprint Phases 1–6** — the
canonical data layer, the evaluation harness, four of the scoring engines, risk
fusion, the scoped API, and a single-screen dashboard. It is **not** the full
product: three engines, the calibration loop, a database server, real per-role
aggregation and deployment (Phase 7) are not built.

Every output is a *computational signal that needs human review* — never a
finding. There is no trained fraud model; MPLADS has no fraud labels.

## What runs today

| Area | State | Where |
|---|---|---|
| Corpus audit | Read-only profiler, measured findings reconciled | `scripts/profile_data.py`, `docs/DATA_REALITY.md`, `reports/data_profile.json` |
| Canonical ingestion | Deterministic single-file CSV snapshot, completed ⨝ sanctioned, atomic replace | `pipelines/ingest.py` → `data/canonical/works.csv` |
| Batch scorer | 8 signals + weighted risk score + severity band, one pass over 5,611 works | `scripts/pipeline.py` → `data/scored_works.parquet` |
| Engine 1 (rules) | Round-amount **heuristic only** (labelled, unsourced); missing-evidence advisory | `pipeline.py: round_rule`, `missing_rule` |
| Engine 2 (anomaly) | `IsolationForest`, one global fit, `contamination=0.05`; z-score stands in for SHAP | `pipeline.py: score_works` |
| Engine 3 (photo reuse) | Tier 1 MD5 identity + Tier 2 DCT pHash / Hamming, dimension floor, common-template suppression. **No SIFT/ORB.** | `pipeline.py: photo_duplicates` |
| Engine 4 (text duplicates) | Exact normalized match + `difflib` near-match across fiscal years, per MP. **No embeddings.** | `pipeline.py: text_duplicates` |
| Engine 7 (fusion) | Deterministic weighted sum (weights sum to 100) + severity floor | `pipeline.py: score_works` |
| Evaluation harness | Synthetic fraud injection, reuses the real detector functions, isolated under `reports/synthetic/` | `scripts/evaluate.py` → `reports/evaluation.json` |
| Auth | HMAC-SHA256 signed bearer token, one fixed demo account per persona, 8 h TTL. **Not JWT.** | `backend/main.py` |
| Authorization | Per-request jurisdiction filter from the token's persona, enforced in the query layer | `backend/main.py: scope`, `work` |
| API | `/auth/*`, `/personas`, `/signals`, `/works`, `/works/{id}`, `/works/{id}/duplicates`, `/confirmed`, `/image/*`, `/investigations`, `/summary`, `/evaluation` | `backend/main.py` (single file) |
| Reviewer decisions | SQLite, one `investigations` table; Confirm/Dismiss with a required reason, per persona | `data/investigations.sqlite3` |
| Status model | `Flagged` → `Under Review` → Ministry `Confirmed` / `Dismissed` (Ministry decisions are final); a `/confirmed` page per jurisdiction | `backend/main.py: compute_statuses`, `frontend/src/App.tsx` |
| Dashboard | Login → Overview (queue, filters, severity chart, work-detail modal) + Confirmed page | `frontend/src/App.tsx` (single file), React 19 + Vite + Recharts |
| Smoke checks | API / auth / scope / input-validation / SQLite-restart checks + evidence contact sheets | `scripts/check_prototype.py` |
| Tests | 4 pytest files: consolidate, ingest, profiler, photo dedup | `tests/` |

Verified behaviour and measured numbers are in `reports/verification.md` and
`reports/evaluation.md`.

## What is still missing

- **Engine 5 (idle funds)** and **Engine 6 (fund-absorption forecast)** — not
  built. Need `WORK_STAGE` + real `SANCTION_DATE` reconciliation first.
- **Engine 8 (calibration loop)** — not built.
- **Engine 1** has no sourced legal rules (75-day deadline, ₹5 cr entitlement,
  ₹75 L trust ceiling, ₹25 L outside-constituency limit). The applicable 2023
  MPLADS guideline text is not verified; the ₹10 L scrutiny threshold stays an
  unsourced heuristic.
- **Engine 2**: one global Isolation Forest fit, not per activity family; no SHAP
  attribution.
- **Engine 3**: no keypoint (SIFT/ORB) inlier confirmation; no PDF→image triage
  stage (`junk_watermark` / `scanned_document` / `site_photo` / `photo_collage`).
- **Engine 4**: no sentence-transformer embeddings, no cross-MP clustering.
- **Database**: CSV + Parquet + a single SQLite table. No PostgreSQL /
  SQLAlchemy / Alembic.
- **Auth**: fixed demo accounts only — no JWT, password hashing, signup, reset or
  per-user accounts. Personas are a single jurisdiction filter, not real per-role
  aggregation with distinct landing views.
- **Dashboard**: one screen + a modal + the Confirmed page. Blueprint's separate
  Work Detail route, Alerts Queue, Analytics and Data Health screens are not
  built.
- **Deployment**: no Docker Compose, no `/health`, no structured logging, no CI.
- **Verification gaps carried forward**: pHash priors, semantic image-class
  proportions, OCR prevalence, current legal clauses, and clean-machine
  reproduction on other operating systems are all still unverified.

The target architecture for closing these is in `docs/TECH_STACK.md` (Part 2).

## Blueprint contradictions to keep in mind

1. `WORK_CATEGORY` is nearly constant. Peer groups use a derived
   `activity_norm × state` taxonomy; no cost-per-unit claim is made without a
   quantity denominator (there is none, so amount == cost-per-unit input, and
   that is disclosed).
2. PDF files can contain many images and page tiles, not one photograph each.
   Source/page/object provenance is preserved; thin strips are gated by a
   150 px min-dimension floor, not blindly labelled junk.
3. The directory inventory includes unreferenced files. CSV linkage is the
   analysis boundary; legacy synthetic outputs are isolated from real evidence.
4. Every current completed work joins to sanction data. Real sanction dates are
   used; labelled proxies are retained only for future unjoined records.
5. `FILE_STATUS` tracks attachment availability. `FLAG` and `AVERAGE_RATING` are
   constant in completed data and are omitted from detector features.
6. Joined sanctioned status reads `Physical Inspection` for 4,730 completed
   records. Completed membership vs sanctioned stage must be reconciled before
   any idle-funds logic.
7. Tenure dates use portal timestamps; other dates use day-month-abbreviation-year.
8. Zero sanction overruns is a measured control, not evidence that all works are
   sound.
9. Fiscal-year coverage spans 2024–2026 letter starts; incomplete coverage does
   not support strong forecasts or national conclusions.
10. A 75-day date gap alone is not a sourced legal breach. The ₹10 L scrutiny
    threshold and other proposed ceilings remain unsourced/unverified.
11. GPS pixel overlays and semantic image classes are not measured here. Nonempty
    EXIF exists in 3,501 decoded images, contradicting universal stripping; the
    tags' usefulness is unverified.
12. Verified runtime is Python 3.12 with the Phase-0/1 packages. Python 3.13 and
    the full ML stack in F8 are not available here.
13. District scope is a demo grouping, not an inferred official boundary. Real
    jurisdiction provenance is a prerequisite for any district-level claim.

## Honest gaps

- **End-to-end trace**: raw CSV → scorer → parquet → API → dashboard → recorded
  decision now works and is checked in `reports/verification.md`. The gap is
  breadth (5 states) and depth (4 engines), not wiring.
- **Language**: reports and UI copy describe computational signals and make no
  accusations. The `Confirmed` surface deliberately uses stronger wording than
  the rest of the app but keeps the "review decision, not a court finding"
  caveat. Historical phase docs under `astra/` and the legacy injector retain
  outdated wording — they are preserved references, not output templates.
- **Regressions**: the scrapers and consolidation code are unchanged; no
  government request, data download, progress reset, model retrain or production
  write was performed.
- **Reproduction**: verified on the Windows dev machine. Clean-machine setup on
  macOS/Linux and the full Docker stack are not claimed.

## Next actions

1. Reconcile completed-vs-sanctioned stage, then build Engine 5 (idle funds) and
   Engine 6 (absorption forecast).
2. Retrieve and cite the applicable 2023 MPLADS clauses; turn Engine 1 into
   sourced rules with the unsourced heuristics clearly labelled.
3. Decide the database (SQLite → PostgreSQL) and move the system of record off
   CSV/Parquet when a second writer or real RBAC aggregation is needed.
4. Split the dashboard into the blueprint's screen set; add `/health` and
   structured logging for a deployment story.
