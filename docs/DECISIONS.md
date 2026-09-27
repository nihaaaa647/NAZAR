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

## 2026-09-25 — Satellite module: source deviation from the plan

`docs/SATELLITE_VENDOR_MODULE_PLAN.md` §1 named Bhuvan NREGA and PMGSY
GRRIS/OMMAS as the coordinate sources, and Copernicus Open Access Hub /
Sentinel Hub as the imagery source. Both stalled during the access spike
the plan itself calls for:

- Bhuvan NREGA's bulk export requires portal login credentials issued
  only to BDOs/DPCs (government field staff) — not publicly self-serve.
- PMGSY GRRIS/OMMAS and PMAY-G are hosted on `.nic.in` domains that were
  unreachable from this environment's network; separately, PMGSY's public
  "7 lakh geotagged facilities" release is markets/schools/hospitals near
  roads, not the road-work asset records with before/after status the
  module needs.
- Copernicus Data Space Ecosystem's catalog search is public and no-auth,
  but every pixel asset — including the small quicklook JPEG — requires
  an OAuth token from a free account. Creating that account on the user's
  behalf is out of scope for this agent.

Substituted, without weakening the "real, not fabricated" requirement:
OpenStreetMap via the Overpass API for coordinates (public, no account,
covers dam/community_centre/named-road categories directly), and
Element84's Earth Search STAC API against the public AWS Open Data
`sentinel-cogs` bucket for imagery (same Sentinel-2 L2A archive Copernicus
serves, no account, confirmed reachable and returning real pixel data).
Both are cited by `source_scheme` on every row so this is auditable. Real
sample pulled 2026-09-25: 49 OpenStreetMap assets (2 dams, 40 community
centres, 7 named roads) in Telangana, real before/after Sentinel-2 crops
fetched for each. This is a qualitative, hand-picked-region sample, not
corpus-scale — matches the plan's own stated fallback for when the named
sources stall (§ "Open questions to settle before starting §1").

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

## 2026-09-25 — Data trust layer: amount normalization, quality alerts, lineage

Every amount was silently coerced with `pd.to_numeric(..., errors='coerce')` -
a value that couldn't parse just became `NaN` with no record of what the raw
text actually said, and there was nowhere for a reviewer to see "this record
has a problem" separately from "this record scored high on fraud risk." Both
gaps close together: `pipeline/amount_normalize.py` replaces the coercion
with a `Decimal`-based parser (never `float`, so a normalized value is exact
to the paisa) that resolves plain rupee figures, Indian comma grouping
(`12,34,567`), and Rs./₹/INR-prefixed thousand/lakh/crore text (`5 Lakh`,
`₹12.5 Cr`, `2Cr`) — the actual corpus (`mplads_india/**/works_*.csv`) turns
out to use only the first of these (checked directly: no comma grouping, no
unit words, no currency symbols in any `ACTUAL_AMOUNT`/`SANCTION_AMOUNT`
value across the full corpus), but a future source file in either format now
normalizes correctly instead of silently mis-parsing.

The normalizer never infers a missing/ambiguous unit from the number's
magnitude — a value with conflicting unit words (`5 lakh crore`) comes back
`ambiguous_unit` with `normalized_inr=None`, not a guess. `pipelines.ingest.
build_works` uses this for `actual_amount`/`sanction_amount` (same NaN-on-
failure contract as before, so `scripts/pipeline.py`'s existing cost-based
detectors already exclude anything that didn't resolve — no detector code
had to change) and records `{raw, unit, parsed, normalized, unit_source,
status, transformation_version}` per amount.

`pipeline/data_quality.py` turns the ingestion pipeline's existing per-row
validation codes (already computed for `validation_issues` — completion-
before-sanction, missing amounts, attachment problems, etc.) plus the new
amount-normalization statuses into standalone alert objects: `work_id`,
`quality_code`, `severity`, `field`, `raw_value`, `explanation`,
`affected_analyses` (which fraud signals the issue would corrupt if it were
silently used), `recommended_action`, `status`, `detector_version`. Each
alert's `id` is a stable hash of `(work_id, quality_code, field)`, so a
reviewer's resolution survives the next pipeline rerun as long as that same
problem is still detected. These alerts contribute nothing to `risk_score`
or `signals_json` — enforced structurally, not by convention: they live in
their own file (`data/quality_alerts.json`) and their own backend endpoints
(`/quality/*`), never merged into `app.state.works`.

`pipeline/lineage.py` records, for every normalized amount and date field,
`source -> raw field/value -> transformation -> normalized value -> version
-> timestamp` — reproducible by construction (same raw input always
produces the same lineage entries, module the run timestamp; see
`tests/test_data_quality.py::test_lineage_reproducibility`).

Resolutions persist in their own SQLite/Postgres table
(`quality_resolutions`, same dual-backend `connection()`/`ph()` pattern as
`investigations`), requiring a reason, same as a fraud-signal Confirm/
Dismiss. Alerts were originally served corpus-wide (no persona filter) on
the reasoning that many land on sanctioned-only records outside
`app.state.works` entirely — Phase 2 (below) revisits this: alerts now carry
their own jurisdiction and are scoped like everything else.

## 2026-09-25/26 — Phase 2: data-quality hardening, real auth, backend-enforced RBAC

### Alert-volume investigation and the stale-vs-incomplete fix

Phase 1 produced 4,748 alerts, 4,730 of them (99.6%) `source_record_stale_or_incomplete`.
Investigating *why* (grouping by the record's own `sanctioned_work_stage`)
found every one of those 4,730 shared the exact same value: `'Physical
Inspection'`. Not drift, not staleness, not 4,730 independent anomalies —
one structural fact about the sanctioned-table CSV export: its own
`WORK_STAGE` field is never updated to `'Work Completed'`, portal-wide, once
a completed-table record exists for the same work. The corpus carries no
per-record update timestamp and no defensible "expected update interval,"
so calling this staleness would have been an unsupported inference exactly
like the amount-unit-from-magnitude guess Phase 1 refused to make. Renamed
to `sanctioned_stage_incomplete`, severity dropped from `warning` to `info`,
and `affected_analyses` set to `[]` — correctly, since the canonical
`work_stage` this app actually reads is already overridden to `'Work
Completed'` whenever `has_completed_record` is true
(`pipelines/ingest.py`); only the sanctioned table's own shadow copy of the
field lags, and nothing downstream ever reads that copy.

Total alert count is unchanged post-fix (4,748 — renaming/re-severing a code
doesn't delete real findings), but the actionable picture changes
completely:

| | before | after |
|---|---|---|
| `source_record_stale_or_incomplete` (warning) | 4,730 | — |
| `sanctioned_stage_incomplete` (info) | — | 4,730 |
| `amount_zero` (warning) | 18 | 18 |
| **default queue** (`GET /quality/alerts`, no explicit severity) | 4,748 | **18** |
| informational, collapsed to 1 root-cause group | 0 | 4,730 |

`GET /quality/alerts` now defaults to excluding `info` severity unless the
caller explicitly asks for it (`severity=info` or `include_info=true`) — a
reviewer's default queue is the 18 amount-quality problems that actually
need a decision, not 4,748 rows dominated by one repeated structural note.
`GET /quality/alerts/groups` collapses repeated low-severity alerts by
`group_key` (`quality_code|field`) into one row with a count, an open-count
and a sample explanation, for the frontend's collapsible "Informational
issues" section (`frontend/src/App.tsx`'s `DataQuality` component) instead
of a 4,730-row table nobody would read. `GET /quality/summary` now reports
`records_affected` (distinct `work_id`s) alongside `total` (raw alert
count) — 4,748 alerts, 4,736 affected records; the two numbers answering
different questions ("how many *problems*" vs "how many *works* need
attention") were conflated in Phase 1's single `total`.

### Stable alert identity, extended

Phase 1's `alert_id` was `(work_id, quality_code, field)` — stable across
reruns as long as nothing about the record changed, but also stable
*through* a genuine change to the underlying value, which would silently
keep an old resolution attached to a now-different problem. `alert_id` now
folds in a short fingerprint of the raw value itself:
`(work_id, quality_code, field, sha1(raw_value)[:8])`. Reran with
byte-identical inputs, ids are byte-identical (
`tests/test_data_quality.py::test_resolution_survives_identical_rerun`).
Change the raw value and a *different* id is generated
(`::test_raw_value_change_creates_new_alert_and_keeps_history`) — the old
id's row in `quality_resolutions` is never touched (nothing ever deletes
from that table), so a prior resolution's reason/reviewer/timestamp stays
queryable as history against the old id, while a fresh, open alert appears
under the new id for the new value. This is deliberately asymmetric with
`investigations` (keyed by `work_id, persona_id`, no value fingerprint) —
a fraud-review decision is about the *work*, which doesn't change identity
when one field's raw text is corrected; a quality alert is about the
*value*, which does.

### Real authentication (`backend/auth.py`)

Replaced Phase 1's plaintext-compare + hand-rolled HMAC token with Argon2id
(`argon2-cffi`) for password hashing and signed, expiring JWTs (`PyJWT`,
HS256). `NAZAR_AUTH_SECRET` unset now generates a random secret at process
start (rather than falling back to a hardcoded string that would ship in
every install) — documented in the README as **required** for any
deployment running more than one backend process, since each process would
otherwise mint its own secret and reject every other process's tokens.
Login always runs `argon2.verify` against either the real account's hash or
a fixed dummy hash for an unknown `user_id` (`app.state.dummy_password_hash`,
generated once at startup) — so a login attempt for a nonexistent account
takes the same code path and roughly the same time as one for a real
account with the wrong password, rather than short-circuiting before any
hash comparison. `POST /auth/logout` revokes the token's `jti` in a
`revoked_tokens` table, checked on every request in `current_persona` — the
only state a "session" has beyond the JWT itself.

Demo credentials are documented in the README only. The frontend's login
page used to ship a clickable list of all four accounts with their
passwords baked into the JS bundle (`DEMO_ACCOUNTS`) — removed; the bundle
now contains zero credentials.

### Backend-enforced RBAC, and 403 vs 404

`GET /works/{id}` already 404'd for a work outside the caller's persona
filter in Phase 1 — correct behavior, wrong status code for "you're
authenticated and the thing exists, but not for you": that's now `403`
(`FORBIDDEN`, a `HTTPException` factory so every 403 site can pass its own
detail message), while a `work_id` that genuinely doesn't exist anywhere
stays `404`. The same distinction now applies to every quality endpoint.

Quality alerts previously had no jurisdiction fields at all (Phase 1's
"shared for context" design, above) — `run_quality_checks` now stamps
`mp_name`/`state_name`/`constituency` from the row it came from onto every
alert, and `scope_quality(persona_id)` filters exactly like `scope()` does
for `/works`, through the same `persona['filter']` dicts already in
`personas.json` (`QUALITY_FIELD_MAP` bridges the `MP_NAME`/`STATE_NAME`/
`CONSTITUENCY` filter keys to the alert's lowercase field names). An empty
filter (Ministry) still matches every alert by construction — default-deny
is the *absence* of a narrowing filter, not a special admin flag, so
Ministry's national access and a narrow persona's exclusion both fall out
of the same one `all(...)` check.

`GET /quality/lineage/{work_id}` has no alert to read jurisdiction from when
the work has zero quality issues, so ingestion now also writes
`data/work_directory.json` — `work_id -> {mp_name, state_name,
constituency}` for *every* canonical row, alert or not, including
sanctioned-only rows that never reach `app.state.works`. This is the one
new pipeline artifact Phase 2 added purely for RBAC's sake.

**MP/district/state identity is still name-string matching, not a stable
ID** — `personas.json`'s filters compare `MP_NAME`/`STATE_NAME`/
`CONSTITUENCY` text, unchanged from Phase 1. The corpus does carry a
genuinely stable numeric MP identifier (`mp_code`, parsed from `LETTER_NO`
by `pipeline/consolidate.py`'s `parse_letter_no`) but it was never wired
into jurisdiction filtering, and wiring it in now would silently change
which works four fixed demo accounts can see without a corresponding real
mp_code-to-persona mapping to seed it from. Documented here and in the
README rather than left implicit, per the instruction not to pretend a
demo-grade mechanism is production-grade: a real deployment needs an actual
MP/district/state directory (e.g. Election Commission constituency codes,
or this corpus's own `mp_code` once a trustworthy code-to-person mapping
exists), not string equality on a name field that can differ by a stray
space or a transliteration choice.

### Reviewer attribution and audit logging

`POST /investigations` and `POST /quality/alerts/{id}/resolve` already
derived `persona_id` from the verified token (`me['id']`, from
`current_persona`) in Phase 1 — never from the request body, so this part
of "D. Secure reviewer actions" was already correct going in. What Phase 2
adds: `current_persona` now also carries `user_id` (the JWT's `sub`, the
actual login account — `persona_id` and `user_id` are 1:1 in this app's
one-account-per-role model, but audit events record both so the log reads
"user X, acting as role Y" rather than conflating the two), and every
state-changing action writes an append-only row to a new `audit_events`
table via `audit_event()`: `login_success`/`login_failure` (never with the
attempted password), `logout`, `access_denied` (every 403 site), `evidence_
decision` (Confirm/Dismiss, with before/after `decision`), and `quality_
alert_resolved` (with before/after `status`). `GET /audit` exposes this
log, Ministry-only (national role, same least-privilege reasoning as any
other cross-jurisdiction aggregate view) — nothing updates or deletes a row
once written.

### Port configuration

`.claude/launch.json` ran `uvicorn` on `8017`; `frontend/vite.config.ts`'s
dev proxy defaulted to `8000` — silently broken (every proxied request hit
`ECONNREFUSED`) until whichever side happened to be overridden to match.
Both now default to `8000`; `vite.config.ts` reads `NAZAR_DEV_API_PORT` (or
`VITE_API_PROXY_TARGET` for a full URL override) so a non-default local
port only needs setting in one place.

### Role-permission matrix

| Endpoint group | MP Office | District Authority | State Nodal | Ministry |
|---|---|---|---|---|
| `/works*`, `/summary`, `/confirmed`, `/inefficiency*` | own MP + constituency | assigned district cluster | assigned state | national |
| `/quality/*` | own MP + constituency | assigned district cluster | assigned state | national |
| `/investigations` (Confirm/Dismiss) | own scope only (`work()` 403s outside it) | own scope only | own scope only | own scope only (still national) |
| `/quality/alerts/{id}/resolve` | own scope only | own scope only | own scope only | own scope only (still national) |
| `/audit` | 403 | 403 | 403 | 200 |
| `/satellite/*`, `/vendor-network` | authenticated, corpus-wide (unchanged from Phase 1 — fictional MP/IDA names, no real jurisdiction to scope by; see `docs/SATELLITE_MODULE_DATA_REALITY.md`) | same | same | same |
| `/image/*`, `/satellite/image/*` | unauthenticated by design (`<img>` can't send headers); pair/asset-checked, not jurisdiction-checked | same | same | same |

## 2026-09-26 — Phase 3: detection contract, inefficiency rework, case consolidation

### Alert-volume investigation, again: case creation started far too eager

First full run under the new standard contract produced 4,872 cases from
5,611 works (87%). Grouping by which signals combined found the driver
immediately: `missing_evidence` fires on 35.6% of the corpus (zero
attachments) with a flag that is binary - `score=1.0` whenever it fires -
and the standardization code was passing that raw score straight into
`strength_of()`, which buckets anything >=0.67 as `'strong'`. A single
missing-evidence flag was independently opening a case, 88 times over, for
exactly the reason the original Phase 1 risk model never let it: that
model weighted `missing_evidence` at 5 of a possible 105 points precisely
because a work having zero listed photos is common and weak evidence on
its own. Phase 3's contract asks for a normalized 0-1 score, but "fired"
and "important" are different questions - a raw pass/fail flag reaching its
own maximum doesn't mean the underlying evidence is strong.

Fix: `IMPORTANCE_WEIGHTS` in `scripts/pipeline.py` re-uses the *exact same*
per-signal weights the original `risk_score` formula already had (not
duplicated by decision - re-read from the one place this was already
settled), normalized against the largest weight (`photo_identical`=25) before
bucketing into weak/medium/strong. `missing_evidence` (weight 5) now maxes
out at score 0.2 - always `'weak'`, never independently case-eligible,
exactly matching its original low-weight intent. `photo_identical`/
`text_exact` (weights 25/20, the two signals that already set the
Phase 1 "Critical severity floor" on their own) still reach `'strong'`
alone - the importance weighting reproduces that pre-existing judgment
rather than overriding it. Re-running dropped the count to 2,745 (Phase 3's other
required investigations - alert-volume, cost-detector-exclusion,
inefficiency/fraud separation - are in the Phase 1/2 entries above and the
"Inefficiency rework" section below).

A second calibration pass was needed for `late_sanction`/`long_open_work`:
the first version gave every flagged record a floor of 0.34 ("medium")
regardless of how far past the threshold it was. With the Phase 3-mandated
45-day window, 65.2% of all sanctioned records are late at all - a floor
that made two-thirds of the corpus "medium" by construction defeats the
entire point of a strength bucket. Replaced with a plain clipped
excess-ratio (`(lag - threshold) / threshold`, 0 at the line, growing
toward 1.0 the further past it), so a record barely over 45 days scores
near 0 (`weak`) and one far past it scores high (`strong`) - see
`_bucketed_score` in `scripts/pipeline.py`. Final count after both fixes:
**2,745 cases from 5,611 works (49%)** - still high, but now driven
overwhelmingly by `late_sanction`'s genuinely high base rate at the
instructed 45-day bar (2,664 of the 2,745 cases involve it), not by a
calibration bug. Whether 45 or 75 days is the right review indicator for
this corpus is exactly the open question flagged below - a follow-up
should re-run this count at 75 days for comparison before treating 49% as
the real answer.

### Late-sanctioning threshold: 45 vs. 75 days, unresolved

Phase 1/2 cited and used a 75-day recommendation-to-sanction window
(`SANCTION_DEADLINE_DAYS`, sourced to "MPLADS Guidelines 2023" per
`docs/DECISIONS.md`'s earlier entries). Phase 3's brief instructs "the
official 45-day timeline" instead. Both numbers plausibly come from real
MPLADS Guidelines material (district-level vs. full-pipeline steps in the
sanctioning process could genuinely have different sub-windows), but this
session did not independently re-verify a primary source for 45 specifically
- it is used here because the Phase 3 instructions say to, not because it
was freshly confirmed against a guideline document. `LATE_SANCTION_REVIEW_DAYS
= 45` now drives `late_sanction_signal`; `SANCTION_DEADLINE_DAYS = 75` is
kept only as a legacy constant so anyone auditing the original citation can
still find it. **A human should verify which window is correct against the
actual MPLADS Guidelines text before this number is treated as authoritative
in a real deployment** - this is the single largest driver of Phase 3's case
volume (above), so getting it wrong in either direction meaningfully changes
how many works look like a problem.

### Inefficiency rework: `long_open_work`, not "idle funds"

Renamed `idle_funds_signal`/the `idle_funds` finding key to
`long_open_work_signal`/`long_open_work` throughout the pipeline, backend
API (`/inefficiency`'s `type=idle` query param is now `type=long_open`) and
frontend. This corpus has no released-amount or spent-balance field for any
sanctioned-but-incomplete work - only a sanction date - so there was never a
financial basis to say money is "idle." The finding is exactly what the data
supports: this work has been open longer than comparable peers. Every
sanctioned/dated candidate now gets a finding row (not just flagged ones):
`long_open_work`/`late_sanction` blocks carry an explicit `status` of
`'fired'`/`'clear'`/`'unavailable'`, and peer definition/sample
size/median/threshold-in-days are stored on the block (not just a bare
z-score) per the Phase 3 spec. A record missing its start date gets
`'unavailable'` with a stated reason - never a fiscal-year-start substitute
standing in as if it were the real date (this was already true of the
existing `duration_basis='fiscal_year_proxy'` field elsewhere in the
pipeline for a *different* duration calculation; `late_sanction` specifically
never had a proxy path to begin with, and Phase 3 keeps it that way).
`MIN_PEER_SIZE=10` gates `long_open_work`: fewer comparable peers marks the
detector unavailable rather than computing a threshold off an unreliable
sample (in the real corpus, 0 of 6,221 long-open candidates hit this floor -
peer groups are large enough throughout, but the check exists for whatever
corpus doesn't have that luxury).

### Standard detection contract (`pipeline/detection_contract.py`)

Every detector - the eight existing fraud/anomaly rules, the two
inefficiency rules - now also emits a standardized record:
`work_id, signal_code, signal_family, status, score, strength, available,
unavailable_reason, detector_version, threshold_version, evidence,
explanation, recommended_action, source, data_mode, cluster`. This is
additive, not a replacement: `signals_json`/`risk_score`/`severity_band`
(Phase 1's shape, everything the existing frontend/tests read) are
byte-for-byte unchanged; the standardized form lives in a new
`standard_signals_json` column, built by `standardize_fraud_signals`/
`standardize_inefficiency_signals` directly from the same already-computed
`signals` dict and `build_inefficiency` finding - no detector's evidence or
number was re-derived, only re-labelled.

`status` distinguishes `'clear'` (ran, found nothing - a real negative) from
`'unavailable'` (couldn't run at all, e.g. no matched sanctioned-table row
for `entitlement_pace`) from `'data_quality_failure'` (couldn't run
*specifically because* a data-quality problem blocked it, e.g.
`cost_peer`/`round_amount` on a work whose amount came back
`ambiguous_unit`/`unparseable` from Phase 1's normalizer) from
`'candidate_only'` (evidence exists - an unconfirmed visually-similar photo
pair - but never counts toward a case on its own). Getting these apart
matters for case consolidation below: an `'unavailable'` `entitlement_pace`
must never silently read as "this MP's pace is fine," and a
`'candidate_only'` photo match must never single-handedly open a case the
way a confirmed one can.

### Cases (`pipeline/cases.py` + `backend/main.py`)

A **case** is what a reviewer actually acts on - never a raw alert. Created
when one `'fired'` signal reaches `'strong'`, or two or more `'fired'`
`'medium'`-strength signals come from different **clusters** (`CLUSTERS` in
`pipeline/cases.py`: `cost_peer`/`round_amount`/`anomaly` all measure "the
amount looks off" and collapse into one `cost_anomaly` cluster;
`photo_identical`/`photo_similar` into `photo_duplication`; etc.) - three
correlated "amount looks off" signals firing at once must not read as three
independent findings, but a cost anomaly plus a photo match genuinely are
independent kinds of evidence. Case priority uses only the strongest signal
per cluster (`cluster_max` in `build_case_candidate`) while retaining every
fired/candidate signal as evidence - a work can have both `cost_peer` and
`round_amount` fired and flagged for review, but priority isn't double-counted
for what's really one underlying observation.

Two priority numbers are tracked and never summed together:
`anomaly_priority` (from anomaly-family clusters) and
`inefficiency_priority` (from `late_sanction`/`long_open_work`) - a case can
be opened from inefficiency signals alone, but that never inflates the
fraud-suspicion number, per the instruction not to mix the two. Two further
dimensions, also kept separate from both priority numbers: `evidence_completeness`
(what fraction of this work's signals could even run - an
`'unavailable'`-heavy work is less analyzable, not less suspicious) and
`source_data_confidence` (downgraded when the work has open data-quality
alerts - critical severity drops it to 0.2, warning to 0.5 - so a case built
partly on a record with a known data defect is visibly flagged as such,
without that defect ever touching the anomaly/inefficiency scores
themselves).

**Case identity**: `case_id = sha1(work_id, sorted(clusters_fired),
fingerprint, detector_version)`, where `fingerprint` is a hash of every
fired/candidate signal's `(code, status, strength)` - deliberately *not*
including raw float scores, so score jitter between identical reruns can
never change a case's id (`tests/test_cases.py::
test_case_id_unaffected_by_unavailable_or_clear_signal_noise`), but a signal
flipping from `clear` to `fired` (or vice versa) does (`::
test_case_id_changes_when_material_evidence_changes`). **Suppression**:
`backend/main.py`'s lifespan merges freshly-generated candidates into the
`cases` SQL table by `case_id` - a case_id already present keeps its
`status`/history completely untouched; only a genuinely new `case_id`
(meaning materially different evidence) gets inserted as `NEW`. A dismissed
case whose evidence hasn't changed regenerates the identical `case_id` on
every rerun and is simply left alone - it never reappears as a fresh `NEW`
case. If the evidence *does* change materially, the old `case_id`'s row
(and its full history) stays in the database as-is; a new row is created
for the new evidence state. Nothing is ever deleted.

### Workflow, RBAC extension, and jurisdiction normalization

`NEW -> TRIAGED -> UNDER_REVIEW -> INFORMATION_REQUESTED -> REFERRED ->
RESOLVED_NO_ISSUE/RESOLVED_CORRECTIVE_ACTION -> CLOSED`, plus reopening
(any resolved/closed status back to `UNDER_REVIEW`). `ALLOWED_TRANSITIONS`
enforces the graph; `ROLE_ALLOWED_TARGETS` reserves `REFERRED`,
`RESOLVED_CORRECTIVE_ACTION`, `CLOSED` and reopening for State Nodal/Ministry
- the same "higher authority for final determination" reasoning Phase 1's
Ministry-only Confirm already established. A reason is required for
dismissal/referral/resolution/reopening/manual escalation, never for the
earlier triage moves - enforced in `transition_case`, not left to the
frontend.

Jurisdiction matching (`scope()`/`scope_quality()`/the new `scope_cases()`)
now runs through `pipeline/jurisdiction.py`: trim, casefold, and a short,
explicitly documented alias table (`ORISSA`->`ODISHA`, `PONDICHERRY`->
`PUDUCHERRY`, etc. - official renames only, sourced in a comment, not a
guess). This is still name-string matching, not a stable government
identifier - documented as such in the README rather than presented as
production-grade (the corpus's own `mp_code`, parsed from `LETTER_NO`,
exists and is genuinely stable, but isn't wired into `personas.json`'s
filters; doing that without a real mp_code-to-account mapping to seed from
would just move the same demo-grade assumption somewhere less visible).

### Mandatory safeguards, mechanically

- **No destructive operations**: every new table is `CREATE TABLE IF NOT
  EXISTS`; the case-candidate merge only ever `INSERT`s a case_id that isn't
  already present.
- **Tests use isolated databases**: every Phase 3 test fixture points
  `NAZAR_DB_PATH` at a `tmp_path` file (same pattern Phase 2's fixtures
  already established) - `tests/test_cases_api.py::
  test_temporary_database_is_isolated_from_real_data` asserts this directly.
- **Backup before migration**: `backup_before_migration()` in
  `backend/main.py` copies the existing local SQLite file to
  `<name>.backup-<UTC timestamp>.sqlite3` before creating `cases`/
  `case_history`/`reviewer_notes`, and only when those tables don't already
  exist (so a second startup doesn't re-back-up a file it's already
  migrated). Confirmed against the real local database when this phase's
  backend was first started under the new schema:
  `data/investigations.backup-20260926T051804Z.sqlite3`. A remote
  `NAZAR_DATABASE_URL` can't be file-copied from this process - documented
  as a limitation, not silently skipped (the function prints and returns
  `None` rather than pretending it backed something up).
- **Production auth-secret gate**: `backend/auth.py` raises `RuntimeError`
  at import time when `NAZAR_ENV=production` and `NAZAR_AUTH_SECRET` is
  unset; otherwise unset emits a `UserWarning` (visible in process logs,
  not swallowed) rather than starting silently on a per-process random
  secret. Tested via subprocess (`tests/test_cases_api.py::
  test_production_mode_fails_without_auth_secret`) since it's raised at
  module import time, before any test fixture could intercept it in-process.
- **Synthetic data stays labelled**: `data_mode` on every standardized
  signal defaults to `'real'`, set to `'synthetic_demo'` only when the
  source row's `is_synthetic` flag is true - the satellite/vendor module's
  own fictional-data labelling (`SAT_NOTICE`, `docs/SATELLITE_MODULE_DATA_REALITY.md`)
  is untouched and remains the primary disclosure for that module.
- **18-actionable-alert Data Quality default preserved**: no change to
  `QUALITY_DETECTOR_VERSION`, the `include_info` default, or the frontend's
  default severity tabs - `tests/test_quality_api.py` (unchanged) still
  passes.

## 2026-09-27 — Phase 4: image evidence intelligence, conditional satellite screening

### A. Corrections carried over from Phase 3

- **Late-sanction wording**: `late_sanction`'s `reason` now says "Exceeded the
  45-day administrative sanction/rejection timeline" verbatim, with an
  explicit "not a finding of fraud or proven non-compliance" disclaimer in
  the same string, per the Phase 4 instructions. The 45-day threshold itself
  is unchanged from Phase 3 - the correction was wording, not the number.
  This corpus has no distinct rejection-date field (only a sanction date),
  so `end_date` is always the sanction date; documented directly in the
  code comment rather than implying rejections are separately tracked.
- **Manual-case persistence**: see section "Case context snapshots" below.
- **`long_open_work` terminology**: already correct as of Phase 3 - swept
  the repo for stray `idle_funds`/`idle_flag` references and found one,
  `scripts/check_prototype.py` (a manual smoke-test script, not part of the
  pytest suite), fixed for consistency.

### Alert-volume investigation, once more: image-similarity scoring was miscalibrated

Standardizing `photo_similar` initially reused Phase 3's `_importance_scaled`
helper (the original risk-model weight, 10 of 105 points, normalized against
`photo_identical`'s 25) - producing a *standardized* score of 0.4 for a
genuinely ORB+RANSAC-confirmed cross-work match, which `strength_of()`
buckets as `'medium'`, not `'strong'`. Phase 4 explicitly instructs that a
confirmed cross-work correspondence is "eligible as one strong review
signal." Fixed: a `'fired'` `photo_similar` standardized signal now scores
1.0 (full strength) regardless of the original risk-model weight - that
weight still governs `risk_score`/`severity_band` exactly as before (Phase
1's numbers are untouched), but the Phase 3/4 standardized-contract score is
a separate, additive metadata field, and Phase 4's instruction take
precedence over reusing Phase 3's importance-scaling verbatim for this one
signal. Caught by `tests/test_photo_signal_standardization.py`.

A second, smaller miscalibration in the same pass: `pipeline/detection_
contract.make_signal` let a `'candidate_only'` status carry a nonzero score
(0.34, a fixed "something's there" placeholder) even though Phase 4 section
D is explicit - "a pHash match alone must remain unscored." Fixed:
`effective_score` is now `0.0` for every status except `'fired'`. This never
changed the visible case-consolidation outcome (`pipeline/cases.py` only
reads `fired` signals' scores for priority/creation, and always did), but it
was a real contract violation sitting unread rather than acted on - fixed
because "unscored" should mean the field is actually zero, not just unused
by every current caller.

### Image evidence pipeline (`pipeline/image_evidence.py`)

Replaces `scripts/pipeline.py`'s old `keypoint_confirm` (a bare confirmed/
not-confirmed ORB check) with `classify_image_pair`, which returns one of six
classifications (`candidate_only`, `confirmed_visual_correspondence`,
`rejected_watermark`, `rejected_generic_similarity`, `insufficient_features`,
`processing_failed`) plus every metric behind that classification (good
matches, inliers, inlier ratio, matched-area coverage, keypoints excluded by
masking). `photo_duplicates` is adapted, not rewritten - the exact same
pHash union-find candidate clustering, dimension gating and common-template
suppression from Phase 1 feed into the new classifier; `data/duplicate_
pairs.json`'s shape is unchanged (a few fields added) so the existing
Evidence viewer and `tests/test_photo_duplicates.py` needed no rework beyond
one tuple-unpacking fix.

**Watermark masking** (`watermark_mask_regions`): a heuristic top/bottom
border-strip mask (10% of image height each), not OCR text-region detection
- every scanner-app watermark sample seen in this corpus (OKEN Scanner
footer, CamScanner logo) sits along a horizontal edge, so geometry alone
catches it without adding a new OCR dependency. Keypoints inside the mask
are excluded from ORB matching entirely, before any comparison happens (not
filtered after the fact). Documented limitation: a watermark placed
elsewhere on the page (a diagonal center stamp, say) would not be caught by
this specific heuristic.

**Distinguishing rejection reasons** (`classify_image_pair`'s two-pass
design): a masked ORB pass is what determines risk eligibility; when it does
NOT confirm, a second unmasked probe pass decides whether that's because
there was genuinely nothing there (`rejected_generic_similarity`/
`insufficient_features`) or because the only real correspondence was inside
the excluded watermark/border region (`rejected_watermark`) - so a reviewer
sees *why* a pair was rejected, not just that it was. Verified against a
synthetic negative control built specifically to prove the masking is doing
real work: two images with different random content but identical watermark
text confirm as a strong match with masking disabled
(`test_masking_disabled_shows_strong_raw_correspondence_from_watermark_text`)
and correctly reject as `rejected_watermark` with masking enabled - proving
the rejection isn't just "nothing was ever going to match here."

**Matched-area coverage** is a third, independent gate alongside good-match-
count and inlier-ratio (both carried over from Phase 1's measured 100/0.2
thresholds): a match whose inliers occupy less than 5% of the smaller
image's area is rejected as `rejected_generic_similarity` even if it clears
the other two bars - a corner stamp or repeated form header can rack up
enough raw keypoint matches to look confirmed by count alone; requiring the
correspondence to actually span a meaningful fraction of the frame catches
that. `MIN_MATCHED_AREA_COVERAGE = 0.05` is a first calibration pass (one
constructed test case, `test_matched_area_below_floor_is_rejected_not_
confirmed`), not measured against a full calibration set - see "Remaining
limitations" in the completion report.

**Deterministic ids**: `image_id` is just the content MD5 (already
content-addressed, unchanged from Phase 1); `match_id` hashes
`(sorted(image_id_a, image_id_b), preprocessing_version, detector_version)` -
order-independent and stable across reruns with unchanged inputs, but a
*different* id the moment either version bumps (a materially different
pipeline gets a fresh identity, never silently reinterprets old evidence
under a new meaning).

### Image evidence persistence (`backend/main.py`)

Same split as cases (Phase 3): descriptive/metric data
(`app.state.image_matches`, from `data/image_matches.json`, regenerated every
pipeline run) versus reviewer decisions (`image_match_reviews`, an
append-only SQL table keyed by `match_id`, migrated with a database backup
exactly like the Phase 3 tables). Nine reviewer actions
(`IMAGE_REVIEW_ACTIONS`) - confirm visual correspondence, dismiss as
watermark, dismiss as generic similarity, mark legitimate before/after, mark
corrected/resubmitted, request original image, request site inspection,
escalate for investigation, add note - deliberately excluding any
"declare fraud" action (`tests/test_image_matches_api.py::
test_review_action_cannot_declare_fraud` asserts the FastAPI enum itself
rejects it, not just that the UI doesn't offer it).

**RBAC across both paired works**: `_match_jurisdiction_ok` requires BOTH
`work_id_a` and `work_id_b` to pass the caller's persona filter (via
`app.state.work_directory`, the same all-canonical-rows lookup Phase 2/3's
quality-alert scoping already uses) - a match with one in-scope and one
out-of-scope work is entirely hidden from a narrow-jurisdiction persona
(`GET /images/matches`) and 403s on direct access
(`GET /images/matches/{id}`), never partially revealed. Ministry (empty
filter, matches everything) is the "route to a role with access to both"
fallback the Phase 4 brief asks for - no separate routing/escalation
mechanism was built beyond that; a District/State persona who needs to act
on a cross-jurisdiction match has to escalate through Ministry today.

### Case integration - one cluster, already correct by construction

Phase 3's `pipeline/cases.py` already mapped `photo_identical` and
`photo_similar` to one `photo_duplication` cluster - Phase 4's "use one
image-similarity cluster in case consolidation" and "pHash and ORB must not
count as two independent signals" fall out of that existing design with no
changes needed to `pipeline/cases.py` itself. What changed is entirely on
the signal-generation side (above): `photo_similar`'s status/score now
correctly reflects the six-way classification instead of a bare confirmed
flag, and reviewer dismissal already suppresses via the same case_id
determinism Phase 3 built (an image-match review doesn't change signal
status by itself - a rerun with the same classification regenerates the
same case_id, so a dismissed case stays dismissed regardless of what a
reviewer records against the underlying image match).

### Conditional satellite screening (`pipeline/satellite_eligibility.py`)

A **standalone, additive** eligibility gate - deliberately does not modify
`ml/cv/satellite_change.py`, `pipeline/fetch_satellite_pairs.py`,
`pipeline/satellite_fraud_injection.py` or `ml/fusion/satellite_fusion.py`,
all of which already implement substantial real, working scaffolding for
this project's Branch A/B satellite module (real OSM coordinates, real
Sentinel-2 imagery, Branch A/B eligibility by category, NaN-not-zero
exclusion for ineligible rows - see `docs/SATELLITE_MODULE_DATA_REALITY.md`
and `docs/SATELLITE_VENDOR_MODULE_PLAN.md`). Those files were understood to
be under active parallel development in this same repository during this
session (a concurrent agent surfaced satellite/vendor work mid-session) -
editing them risked clobbering in-progress work neither visible nor owned
by this thread of work, so the Phase 4 gate was built as a new module
callers can adopt without anyone needing to touch those files.

`check_eligibility` runs seven independent gates in the order the Phase 4
brief lists them (coordinates present -> geocode confidence -> imagery
present -> imagery-to-project-timeline alignment -> cloud cover -> asset
category resolvability -> asset size vs. resolution) and returns exactly one
of the seven statuses (`eligible` or one of six non-eligible reasons), never
a risk score. Two inputs this corpus doesn't yet compute anywhere
(per-asset cloud cover downstream of the STAC query, and a project-timeline-
to-imagery-date skew) are wired to `None` in the one place this session did
integrate the gate (`GET /satellite/{work_id}` in `backend/main.py`) -
`None` skips that gate rather than failing it, which is honest about what
isn't measured but means `eligible` there means "cleared every gate this
system can currently evaluate," not "cleared every conceivable gate."
Documented as a limitation, not fixed, given how much of that scoring
already lives in files this session avoided touching.

**Asset-category matching** uses substring keywords
(`_visible_size_for_category`) rather than an exact lookup, because the real
corpus's own category strings are free text ("Installing tube-wells and
borewells", "Street lights", "Setting up of laboratories") - verified
directly against `data/canonical/satellite_works_scored.csv`'s actual
category column, not assumed. Categories with no matching keyword return
`inconclusive` rather than being guessed as either resolution.

### Review-time measurement (section K)

`case_review_sessions` (start/end timestamps, one row per session) is the
only thing `cases_resolved_per_investigator_hour` in `GET /metrics` is ever
computed from - `median_time_to_first_review`/`median_case_resolution_time`
still use case age (that's what they're explicitly *for*), but
investigator-hour throughput never infers effort from wall-clock case age.
No historical session data exists for the real corpus (this feature starts
now, forward-only) - `cases_resolved_per_investigator_hour` reports
`'unavailable'` for the real deployment until reviewers actually start using
`POST /cases/{id}/review-session/start`+`/end`, exactly as instructed rather
than backfilling a synthetic number to make the metric look populated.

### Mandatory safeguards, mechanically

- **No destructive operations, tests fully isolated**: every Phase 4 test
  fixture uses `tmp_path` for both the database and (via synthetic images
  written by OpenCV, never the real `data/image_cache/`) any image files -
  `tests/test_image_evidence.py` never touches the real image cache at all.
- **Backup before migration**: `backup_before_migration`'s tracked table set
  extended to include `case_context_snapshots`, `image_match_reviews`,
  `case_review_sessions` - same backup-once-per-schema-change behavior as
  Phase 3, verified against the real local database again this phase. **A
  real bug was found and fixed here**: the skip condition was `new_tables &
  existing` (skip if ANY overlap) instead of `new_tables <= existing` (skip
  only if EVERY new table already exists) - which meant the moment Phase 3's
  `cases` table already existed, Phase 4's genuinely-new tables
  (`case_context_snapshots`, `image_match_reviews`, `case_review_sessions`)
  got created with no backup at all. No actual data was lost in this
  session's testing (the new tables were empty; `CREATE TABLE IF NOT EXISTS`
  never touches other tables), but the safeguard itself was silently
  non-functional for any partial-overlap migration, which is the common
  case for an incremental schema change. Fixed to the subset check, with a
  regression test specifically for partial overlap
  (`tests/test_migration_backup.py::test_partial_overlap_still_triggers_backup`)
  so this can't silently regress again.
- **Expensive operations stay batch-only**: `classify_image_pair` (ORB+
  RANSAC) and `build_image_inventory` only ever run inside `scripts/
  pipeline.py`'s `main()` - no FastAPI endpoint recomputes anything from raw
  images; `GET /images/matches*` only ever reads `data/image_matches.json`,
  already computed.
- **Zero risk until confirmation**: enforced twice over - `classify_image_
  pair` only sets `risk_eligible=True` for `confirmed_visual_correspondence`,
  and `standardize_fraud_signals`'s `photo_similar` only sets a nonzero score
  when `status=='fired'` (which itself only happens when the underlying pair
  was risk-eligible). `tests/test_photo_signal_standardization.py` and
  `tests/test_image_matches_api.py::test_candidate_only_and_watermark_are_
  zero_risk_by_construction` check both layers.
- **No "declare fraud" anywhere**: neither `IMAGE_REVIEW_ACTIONS` nor any
  workflow status name in `WORKFLOW_STATUSES` (Phase 3) contains a fraud
  declaration; `CLASSIFICATION_MEANINGS` and the satellite `CHANGE_DETECTED_
  LANGUAGE`/`NO_CHANGE_LANGUAGE` constants are asserted never to state
  non-existence or fraud as a finding.

## 2026-09-27 — Removed `round_amount`

Dropped the round-number heuristic (`pipeline.py: round_rule`) from the
fraud risk score, the `cost_anomaly` case cluster, and every signal-code
list in `pipeline/data_quality.py`. Unlike every other signal, it never had
a statistical basis (like `cost_peer`'s z-score or `anomaly`'s Isolation
Forest) or a sourced regulatory basis (like `entitlement_pace`'s MPLADS
Guidelines citation) — its own reason string already admitted "a heuristic
flag with no verified legal threshold." It was also never validated: the
`pipeline/fraud_injection.py` recall harness injects patterns for
structuring, cost outliers, duplicates, sequencing breaks, and more, but
never a round-number pattern, so no evidence existed that this signal ever
caught anything. Real-world confound: round sanctioned amounts are routine
in Indian government budgeting (schedule-of-rates estimates, standard
budget line items) for entirely legitimate reasons, so "round number" alone
was a weak, likely high-false-positive cue riding at the same weight as
better-justified signals.

Nominal signal weights now sum to exactly 100 (previously 105, capped) -
`risk_score`'s `min(sum, 100)` cap is now a no-op headroom guard rather than
something the weights actually rely on. `ml/fusion/satellite_fusion.py`
(the satellite module's own scorer, see the 2026-09-25 entry above) had
reimplemented the same heuristic for its synthetic population and was
updated to match - dropped there too, not just in the real pipeline.
