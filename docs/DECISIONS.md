# Implementation decisions

## 2026-09-08 — Scope and document authority

The user asked to inspect the project and instructions and start implementation.
The supplied phase documents define the build sequence and product intent; their
role declarations, historical paths and completion claims are not facts about this
workspace. Work stays in the current copied project. No full nationwide scrape,
system install or external publication is implied. Begin with Phase 0, preserving
the supplied source documents and historical artifacts.

## 2026-09-08 — Preserve the existing foundation

Created a baseline Git commit before implementation. Existing Python files remain
unchanged. The profiler calls `engineer_features` in memory, preserving the old parquet.
Part G folders are reserved with `.gitkeep`, not plausible stubs. No schema or detector
has been started. The historical proxy comment is mathematically misleading: an
April 1 date would be a lower bound on a sanction date *only if sanction occurred in
that fiscal year*, which the letter itself does not establish. A proxy duration is
not a measured execution duration. Correct and label this in Phase 1.

## 2026-09-08 — Runtime and dependencies

The shell did not expose Python, and the bundled executable is Python 3.12.14.
Created `.venv` using that executable, installed only Phase 0 requirements and pinned
the resulting dependency set. This replaces the unverified assumption that Python
3.13 and the full ML stack are available. No system installation occurred. PostgreSQL
and Tesseract were not on PATH; Docker CLI exists, server availability unverified.
Python 3.13 compatibility and future ML dependencies remain unverified.

## 2026-09-08 — Attachment accounting and isolation

Legacy injection code explicitly writes generated evidence into raw constituency
folders. Analyze only CSV-referenced evidence; list unreferenced paths separately,
without assuming every orphan is synthetic. Future ingestion must use explicit
evaluation metadata and isolated storage. Existing injection code is not called.

PDF measurements use a stdlib JPEG marker probe followed by Pillow verification and
reduced JPEG decoding, preserving bytes for SHA-256. This is a limited probe, not a general PDF parser:
unsupported encodings and failed decodes are recorded, not interpreted as no evidence.
No new PDF dependency or rasterization was needed. Colorfulness uses the standard
opponent-channel mean/standard-deviation formula on RGB thumbnails up to 256 pixels;
entropy uses the grayscale thumbnail. A 200-pixel count reproduces the prior review's
diagnostic only: it is not yet a production junk threshold or semantic classifier.

## Storage choice for Phase 1

The operator selected **Use the local corpus** on 2026-09-08. Defer a full
download until requested. The operator subsequently directed **use CSV files for
now instead of a database**. This supersedes the SQLite/PostgreSQL recommendation
and the blueprint's database requirement for current implementation. No SQLAlchemy,
Alembic or database service will be added until requested.
OCR/document intelligence is not approved or measured yet.

## 2026-09-08 — New contradictions discovered during the audit

The current corpus has 5,611 completed works and 11,832 sanctioned records; all
completed works join. The join contains 4,730 records at `Physical Inspection`
and 881 at `Work Completed`. Preserve both source statuses in Phase 1. A completed
record must not be classified as idle merely because the sanctioned snapshot uses
`Physical Inspection`; source semantics need reconciliation. Actual amounts never
exceed sanction amounts in the join (4,613 equal, 998 lower).

The JPEG probe exposed multi-image PDFs and thin page tiles. For example,
`163131_1.pdf` in the sorted corpus contains numerous 2336x37 and similar strips.
These are not automatically scanner watermarks. The Phase 1 extractor needs page
and image-object context, and likely page reconstruction, before junk triage.
The review's one-page/one-image assumption is contradicted; raw embedded-image counts
must not be called counts of usable photographs or evidence pages.

## 2026-09-08 — Legal verification remains incomplete

An official guidelines index was located at
https://www.mplads.gov.in/mplads/En/2010-mplads-guidelines.aspx, but fetching it timed
out. Search located the 2016 official PDF, whose section 3.12 includes a 75-day
receipt-based deadline and model-code-of-conduct exclusions:
https://www.mplads.gov.in/mplads/uploadedfiles/mpladsguidelines2016english_638.pdf.
This does not independently verify the applicable 2023 text. F7 is therefore
partially verified, not confirmed. Do not emit legal violation claims or assume
`RECOMMENDATION_DATE` equals receipt date. Phase 3 must retrieve the applicable
clauses and exceptions, including trust/society and outside-constituency rules.

## 2026-09-08 — Audit performance

Two preliminary full-resolution image audit attempts were interrupted after runtime
traces showed most work in image decoding, RGB conversion and resizing. No raw data
was changed and no incomplete report was accepted. The final pass uses JPEG draft
decoding for thumbnail-only statistics and caches metrics by original payload SHA-256
within a run. Original dimensions and byte-identity are unaffected; thumbnail
colorfulness and entropy are approximate statistics, not full-resolution metrics.

## 2026-09-08 — Canonical CSV ingestion

`pipelines.ingest` rebuilds one deterministic `works.csv` snapshot from the union
of completed and sanctioned records, keyed by recommendation ID. Completed table
membership supplies effective completion status; the original sanctioned stage is
preserved and disagreement is flagged for verification. Missing completion fields
on sanctioned-only records are left null. No sanctioned amount is presented as
actual expenditure. Real joined sanction dates replace the legacy proxy; malformed
joined dates are never silently replaced by a proxy. Source values and paths remain
available alongside parsed values and validation outcomes.

Single-file atomic replacement and byte-identical reruns provide local snapshot
idempotence; concurrent writers and transactional investigations are not implemented.
Missing/duplicate source IDs and explicitly synthetic/unknown tagged source rows
abort before replacing an existing snapshot. This does not claim the future API's
synthetic or jurisdiction isolation guarantees. Evaluation files remain separate.

Peer assignment is still pending. A preliminary union-corpus measurement found
450 activity/state groups, median size 1, 397 below 30. Group eligibility and
completed versus sanctioned-only cohorts must be resolved before assigning peers;
no detector thresholds or models were introduced with the storage change.

## 2026-09-09 — Scanner watermark is never duplicate evidence

The prototype spec assumed byte-identical images carry "zero false-positive risk"
and left Tier 1 (`photo_identical`) ungated. On this corpus that surfaced 15
groups of a byte-identical scanner-app footer strip ("Scanned with OKEN Scanner",
CamScanner logo) shared across unrelated works as "identical image evidence"
pairs — e.g. works 178450 / 178656 at 656x83. Tier 1 now applies the same
`MIN_IMAGE_DIM = 150` floor Tier 2 already used (`is_photo_evidence`): sub-floor
byte groups are logged as `tier1_watermark_groups` and never emitted as pairs.
Tier 2 is unchanged — a footer is ~2% of a full-page scan's pHash and the
common-component cap already covered the rest. Full-size scans that are genuinely
byte-identical across works (including blank form templates) still pair.

## 2026-09-09 — Persona sign-in (makeshift auth)

Persona scope was a request parameter any caller could set. It now comes from a
signed session token. `POST /auth/login` verifies one fixed account per persona
(defaults in `backend/main.py`, override via `NAZAR_USERS` / `NAZAR_AUTH_SECRET`)
and returns an HMAC-SHA256 token `{sub: persona_id, exp}` — stdlib only, no JWT or
bcrypt dependency, 8 h TTL. `/works`, `/works/{id}`, `/works/{id}/duplicates`,
`/summary` and `/investigations` now resolve the persona from the token via a
`current_persona` dependency; unauthenticated or tampered requests get 401. The
frontend replaces the persona picker with an email-style login (account decides
the role, no picker), stores the token in localStorage, attaches it to every
request, and returns to the login screen on 401. `/image/*` stays token-free
(`<img>` cannot send headers; evidence is deliberately cross-jurisdiction) but
keeps its work/filename pair check. This is a demo gate: no signup, reset, or
per-user accounts, and the defaults are published in the README.

## 2026-09-09 — Filter the queue by review signal

The review queue could be narrowed by severity, status and free text but not by
*why* a work was flagged. `GET /works` now takes `?signal=<key>` (one of the
eight signal keys; 422 on anything else) and keeps only works whose that signal
fired — computed from a per-work `_flagged` list built once at load from
`signals_json`. `GET /signals` returns the key, label and per-view flagged count
for each signal, which fills the dashboard's "Any review signal" dropdown and
the empty/heading copy. Filters compose (AND) with severity, status and search,
and the status-tab counts reflect the active signal. A work whose risk is only
accumulated sub-threshold scores matches no signal — expected, since the filter
means "this signal fired", not "appears in this band".
