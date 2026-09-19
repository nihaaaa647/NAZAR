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

## 2026-09-09 — Ministry confirmations get their own status and view

A Ministry `Confirm` previously collapsed to `Under Review`, indistinguishable
from a junior persona's comment. `compute_statuses` now recognises a fourth
status, `Confirmed`, set only by the Ministry's `Confirm` row and, like
`Dismissed`, order-independent and final (a `STATUSES` tuple drives the status
param, the tab list and the `status_counts` dict). `GET /confirmed` returns the
Ministry-confirmed works inside the caller's jurisdiction, newest first, each
carrying the Ministry's recorded reason and decision time; `GET /summary` gains a
`confirmed` count and `GET /works/{id}` now returns `status`. The frontend adds a
second workspace page ("Confirmed") listing those works with the Ministry's
reason, a red `Confirmed` queue tab and row tag, and — in a narrower persona's
view — a banner stating the work was flagged as a potential fraud concern and
confirmed by the Ministry. The wording is deliberately stronger than the rest of
the app; every confirmed surface still carries the standing caveat that a
confirmation is a review decision, not a court finding of misconduct.

## 2026-09-09 — Cost-vs-peers is one-sided (high only)

`cost_rule` flagged `abs(z) > 2.5`, so a work billed far *below* its activity/state
peers was flagged "unusually low" and contributed the full cost_peer weight (15)
to the risk score. Only an amount *above* peers is a spending concern here, so the
rule now flags `z > 2.5` only and scores `min(max(z, 0) / 6, 1)` — the low side
contributes nothing. A below-peers amount still shows an informational reason
string in the work detail, just no flag. Effect on the current corpus: cost_peer
flags 940 → 467, Moderate band 421 → 201 (the low-amount works were sitting at
Moderate purely on this signal). The Isolation Forest still sees `amount_z`
unchanged, so a genuinely tiny outlier can still surface as a statistical anomaly.

## 2026-09-19 — Split deploy: Vercel (frontend) + Render (backend)

Vercel is serverless — no persistent disk, no long-running process — so it can't
run the FastAPI backend (writes `investigations.sqlite3`, serves
`data/image_cache/`). The split is frontend on Vercel, backend on Render (a free
web service, chosen over Fly/Railway for the simplest native-Python + GitHub
Blueprint flow), talking over CORS with a bearer token (no cookies, so a
wildcard origin carries no CSRF risk — `NAZAR_CORS_ORIGINS` still lets it be
locked down).

Neither the 7.1 GB raw corpus nor the 5.6 GB local `data/image_cache/` (3,574
images) is in git or going on a free host. Only 355 of those images are ever
actually served — the ones `duplicate_pairs.json` evidence pairs reference.
`scripts/prepare_deploy_data.py` copies just those, downscaled to <=1400px/q82,
into a committed 63 MB `deploy_data/` snapshot (no Git LFS needed); everything
else (works, signals, evidence pairs, personas) is copied byte-exact. The
backend's data directory is now configurable (`NAZAR_DATA_DIR`, previously
hardcoded to `ROOT/'data'`) so a deployment can point at this snapshot without
touching local dev.

Render's free plan has no persistent disk: `deploy_data/` (part of the deployed
code) survives restarts, but `investigations.sqlite3` does not — decisions reset
on the next cold start after the service idles out. Accepted for a demo;
documented in the README rather than solved with a hosted DB, which is a bigger
change than this deploy needed.

Local main and origin/main had also diverged (a README landed on GitHub outside
this session while local carried an unpushed "Confirmed status" backend
feature) — merged with no conflicts (identical README content on both sides)
and pushed before any of the above.

## 2026-09-19 — P0: a real inefficiency engine, and sourced entitlement thresholds

The problem statement (26102) names "inefficiencies" and "delayed projects" as
first-class alongside fraud; nothing in the pipeline measured either. The
5,611-row corpus `scripts/pipeline.py` scores is completed-work-only by
construction, so it structurally cannot represent an unfinished, still-idle
work — that population (6,221 sanctioned records with no completed record)
only exists in `works_sanctioned.csv`, which the fraud pipeline never read.

**Inefficiency engine (new, deliberately separate from fraud).**
`scripts/pipeline.py` now also loads the sanctioned-table join via
`pipelines.ingest.build_works` (the same code `data/canonical/works.csv`
uses) and computes two sourced signals over that full 11,832-record
universe — a different population from, and never merged into, the
completed-only fraud corpus:
- **Idle funds**: sanctioned, no completed record yet, held open further past
  its activity×state peers than `peer_z`'s one-sided robust z (same
  fallback ladder, same "only slower than peers counts" convention as
  `cost_peer`) allows — 397 of 6,221 candidates.
- **Late sanctioning**: sanctioned more than 75 days after the recommendation
  was received (MPLADS Guidelines 2023, cited in `astra/FINDINGS_TO_VERIFY.md`
  F7) — 5,864 of 11,832 sanctioned records (49.6%), true and disclosed as a
  systemic rate, not suppressed for being common.

Output is a wholly separate artifact (`data/inefficiency.json`,
`reports/inefficiency.json`), a separate backend surface (`GET /inefficiency`,
`GET /inefficiency/summary`, jurisdiction-scoped like `/works` but never
touching `signals_json`/`risk_score`/`severity_band`), and a separate frontend
tab ("Inefficiency", its own stat cards, its own table, its own "days idle" /
"sanction lag" language) — structurally impossible to blend with the fraud
severity bands, per the explicit instruction not to mix them.

**Sourced entitlement signal, deliberately hedged (`entitlement_pace`).**
The ₹5 crore/MP/fiscal-year entitlement (MPLADS Guidelines 2023, "released as
two ₹2.5 crore installments") is real and citable, computed from the same
sanctioned universe. First cut flagged it as a "breach" at weight 15 in the
Critical floor: 2,514 of 5,611 completed works (44.8%) lit up, because a
handful of high-volume MPs (one alone: 476 completed works) dominate both the
completed corpus and the entitlement total. On inspection this overclaimed —
**MPLADS entitlement is non-lapsable and carries forward across an MP's
tenure**, so a single fiscal year's sanctioned total above ₹5cr is exactly
what legitimate catch-up on an under-used prior year looks like, not proof of
a limit breach. This corpus has no wired-through tenure-start date to test
the real cumulative cap. Rather than ship a sourced-sounding but potentially
wrong "breach" claim — the same mistake F7 already caught once in the
blueprint's fake ₹10L rule — `entitlement_pace` stays in `signals_json` as a
real, low-weight (5, same tier as `missing_evidence`/`round_amount`), **not**
Critical-floor signal, with a reason string that names the carry-forward
caveat explicitly. The `₹75 lakh trust/society ceiling` and `₹25 lakh
outside-constituency cap` from the same FINDINGS_TO_VERIFY table are not
implemented at all: this corpus can only "partially" link IDA entity type and
MP home district, and a wrong sourced flag is worse than no flag — same
reasoning, applied before writing any code for those two.

**Refactor, not just addition.** `score_works`'s inline peer-group
median/MAD/z-score block became `peer_z()`, a shared helper now used by both
`cost_peer` and the idle-funds duration check. Verified byte-identical output
against the pre-refactor inline code on the full corpus before relying on it
(max abs diff 0.0) — see the numbers this replaced, unchanged, in
`docs/ENGINES_EXPLAINED.md` §2.1.

**Net effect on the fraud side**: `entitlement_pace` flags 2,514 works (44.8%,
expected given the carry-forward caveat — it's advisory context, not a rare
anomaly) but at weight 5 and outside the floor, severity bands barely moved
(Critical 404→404 unchanged; Moderate 201→235, +34 works nudged up by the
extra low weight). `cost_peer`, `photo_*`, `text_*`, `anomaly`,
`missing_evidence`, `round_amount` are untouched.

## 2026-09-19 — Optional Postgres for reviewer decisions (Neon)

Render's free plan has no persistent disk: `investigations.sqlite3` survives
while the service is awake and resets on the next cold start after 15
minutes idle. A demo revisited later would show every Confirm/Dismiss gone —
worth fixing before treating a deploy as the one shown to anyone, not after.

`backend/main.py`'s `connection()` now takes a `NAZAR_DATABASE_URL` env var:
set, it connects to Postgres via `psycopg` (autocommit, one connection per
request — the Neon URL used is the pooled one, built for exactly this
pattern); unset, it falls back to the existing local SQLite file, unchanged.
The five call sites needed two changes, not a rewrite: a `ph()` helper
translates `?` placeholders to `%s` for Postgres (SQLite and Postgres both
already speak the same `INSERT ... ON CONFLICT (...) DO UPDATE SET
col=excluded.col` and `CREATE TABLE IF NOT EXISTS` syntax — no SQL rewrite
needed there), and rows are read as plain tuples on both backends (both
drivers' own defaults) zipped against a fixed `INVESTIGATION_COLUMNS` tuple
instead of a backend-specific row factory (`sqlite3.Row` is gone from the
file). No ORM, no migrations — the schema is one 5-column table; a full
SQLAlchemy/Alembic migration (`docs/TECH_STACK.md`'s planned MVP target) is
real work this fix didn't need.

Verified against a live, freshly created Neon project (Postgres database
service only — Object storage / Functions / AI gateway / Neon Auth are
unused and were left off): logged in, confirmed a work, read it back in a
**separate Python process** (proving it's the database persisting, not
in-process state), confirmed the SQLite path is still byte-for-byte the same
locally (`check_prototype.py` unchanged, all green). Test data cleared from
Neon before handoff.

**The connection string itself is never committed.** `render.yaml` declares
`NAZAR_DATABASE_URL` with `sync: false` — Render prompts for it during
Blueprint setup and stores it only in its own env var store, never in git.
`.env.example` documents the variable with a placeholder, not a real value.

## 2026-09-19 — ORB keypoint confirmation for Tier-2 photo matches

Tier 2 (`photo_similar`) was pHash-only: "visually similar" at the coarse
8x8-DCT resolution, explicitly labelled "inspect manually" because a shared
blank form layout produces the same low Hamming distance as a genuinely
reused photo. That's the weakest evidence the review queue showed, and it was
the highest-leverage fix available: confirming or rejecting each Tier-2
candidate with real geometric feature matching (`keypoint_confirm`, ORB +
BFMatcher + Lowe ratio test + RANSAC homography) turns a hand-wave into a
number a reviewer can trust.

**Thresholds measured, not guessed**, against this corpus's 229 unique
Tier-2 candidate pairs and a 60-pair negative control of random unrelated
images (same method the pHash threshold itself was calibrated with):
`good_matches` alone nearly separated the two populations (negative control
max 98, real candidates' 5th percentile 106); `inlier_ratio` is **not**
trustworthy at low match counts on its own — the negative control reached
inlier_ratio 1.0 in places, because a handful of correspondences lets RANSAC
fit a degenerate homography to all of them by chance. Combined rule
(`good_matches >= 100 and inlier_ratio >= 0.2`): 0/60 negative-control
false-confirms, 197/229 (86.0%) of real candidates confirmed.

Hand-read both outcomes on the real corpus
(`reports/visual_qa/photo_similar_confirmed.jpg` /
`..._unconfirmed.jpg`). Confirmed pairs are genuinely matching inspection
reports and completion certificates. Unconfirmed pairs are the predicted
failure mode exactly: the same blank government estimate/certificate
template filled in with different work names, villages and amounts — a real
pHash match, correctly not confirmed as photo reuse.

Only confirmed pairs now count toward `photo_similar`'s flag/score
(`score_works` tracks confirmed and unconfirmed counts separately).
Unconfirmed candidates are not hidden — they stay in
`data/duplicate_pairs.json` and the Evidence viewer, honestly labelled
"visually similar, unconfirmed," just excluded from the risk score. Effect
on this corpus: 234 Tier-2 pairs, 202 confirmed; severity bands barely moved
(Moderate 235 -> 233) since `photo_similar` carries a modest weight (10) and
most affected works already carried other signals.

**Dependency note**: added `opencv-python-headless` (not `opencv-python` —
the GUI build pulls in system libraries like libGL that aren't present on
Render's Linux build image, and this pipeline never opens a window).
`opencv-python-headless==4.12.0.88` caps at `numpy<2.3.0`, conflicting with
the `numpy==2.3.5` pandas/scipy/scikit-learn already need; `4.14.0.94`
relaxes that cap to `numpy>=2` with no ceiling and resolves cleanly — used
that instead. Verified with a full `pip install -r requirements.txt` into a
clean venv, not just an incremental install into an already-populated one
(the latter silently hid the conflict).

## 2026-09-19 — Related-entities view (repeat-pattern, no new detector)

Every signal scored one work in isolation — nowhere did the review queue show
"this MP has 30 other flagged works" or "this agency's flag rate is 8x the
corpus average," even though that's exactly the shape of thing that reads as
a real pattern rather than statistical noise. This is pure presentation over
data every work already carries (MP_NAME, IDA_NAME, severity_band) — no new
detector, no pipeline change, computed once at backend startup
(`app.state.by_mp` / `by_ida`, grouped from the already-loaded
`scored_works.parquet`) and served inside the existing `GET /works/{id}`
response as a `related` block.

For each of MP and implementing agency: total works, flagged works
(`severity_band != 'Low'`), flag rate, the rate compared to the corpus-wide
average as a multiplier, and up to 5 of that entity's other flagged works
(by risk score) to drill into. A block is omitted (not zeroed) when the
entity has fewer than 2 works — nothing to call a pattern with just the one
work being viewed. Corpus-wide, not jurisdiction-scoped, same convention as
duplicate evidence ("shared for context," with the caveat stated in the UI).

First real result, unprompted: MP "VIJAYLAKSHMI DEVI" — 88 of 95 works
flagged (93%, 8.2x the corpus average of 11%), with a visible run of
near-identical "FOR OPEN GYM" / "CONSTRUCTION OF PCC ROAD" claims at
near-identical amounts. An implementing agency case reached 8.0x. Exactly
the kind of finding an isolated per-work flag never surfaces.

Explicitly labelled as context, not proof, in the UI: a high flag rate for
one MP can also mean that MP does unusually large volume (more works, more
chances for any one signal to fire) — investigate each work on its own
evidence, same caveat every other signal in this system carries.
