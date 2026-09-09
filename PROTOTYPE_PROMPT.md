# NAZAR Prototype — Single-Pass Build Prompt (GPT-6 Astra)

A separate, much larger prompt pack exists at `astra/` for a full production build (real
multi-account auth, Postgres, Docker, 8 phases) — **ignore it, do not open it.** This file is
the whole brief, meant to be pasted once and built in one sitting. Do not open
`MPLADS_Implementation_Blueprint.docx` either. Work at `reasoning.effort: medium`.

**This is a scaled-down build, not a stripped one.** Cut engineering overhead (real auth,
Postgres, migrations, Docker, a full test suite, multi-session state tracking). Do **not**
cut the features that make this a winnable demo: four real, differentiated user views;
gated perceptual-hash duplicate detection alongside byte-identical matching; a genuinely
polished UI. Budget realistically **2.5-3 hours** of your own working time for this scope —
say so up front if you think it will run longer, but do not silently drop scope to hit a
smaller number.

## MISSION

In the repo at `C:\Users\Niharika\python\sih`, build NAZAR: a real, end-to-end anomaly/
fraud-signal detector over the MPLADS work data already scraped into `mplads_india/`, with
four hardcoded stakeholder personas (MP office, District Authority, State Nodal Authority,
Ministry) each seeing a genuinely different, correctly-scoped view of the same underlying
data — no login, no passwords, just a persona picker, because that's what the problem
statement's audience actually requires and a real auth system is not worth building in this
timebox. Done = a pipeline scores the real corpus, a FastAPI server serves it, a polished
React frontend lets someone pick a persona, browse a risk-ranked list scoped to that
persona's jurisdiction, open a work and see real evidence (including a genuine
byte-identical *or* perceptually-similar duplicate photo pair rendered side by side), submit
Confirm/Dismiss, and see a fraud-injection validation report proving the detectors catch
something real. No fabricated numbers anywhere.

## HARD CONSTRAINTS

1. **Never accuse.** No UI/API string may assert a named person or agency committed fraud.
   Use "flagged for review", "anomalous vs peers", "duplicate evidence detected". Every
   flagged work shows a line saying this is a computational signal needing human review.
2. **Never fabricate a legal citation.** No real source → label it an unsourced heuristic,
   in the code and in the UI.
3. **Do not touch the scraper.** `mplads_common.py` / `mplads_india_downloader.py` stay
   untouched and unrun. Use whatever is already in `mplads_india/` right now.
4. **No secrets, no fabricated/mock data in the shipping path.**
5. **The word "Nirikshak" must never appear anywhere.** This project is **NAZAR**.
6. **No real authentication.** No passwords, no JWT, no session security. Four **hardcoded**
   personas, selected by clicking a card — this is a demo-view convenience, not access
   control, and the UI should not pretend otherwise (no fake "login" copy implying security).
7. **Minimal new dependencies, chosen for speed of install, not avoided altogether.**
   Backend: `fastapi`, `uvicorn` if missing (already-installed `pandas`, `numpy`,
   `scikit-learn`, `scipy`, `pillow`, `pyarrow` cover everything else — **pHash needs no new
   package**, see below). Frontend: a standard Vite + React + TypeScript scaffold, plus
   `recharts` and (optional) `lucide-react` — both small, fast, standard installs. Do **not**
   install `sentence-transformers`, `imagehash` (you're hand-rolling pHash instead, see
   below), `shap`, `torch`-dependent extras, OCR/tesseract, `pymupdf`/`pypdf`,
   SQLAlchemy/Alembic, or a component-library megapackage.

## OUT OF SCOPE — do not build these

Real password auth / JWT / sessions · PostgreSQL, Docker, Alembic migrations, an ORM · SHAP
explanations · sentence-transformer embeddings · SIFT/ORB keypoint confirmation (see the
duplicate-tier section — this one is cut for being genuinely time-heavy relative to payoff
in this budget, not because it's unimportant; say so if you skip it) · OCR / GPS extraction /
satellite anything · the idle-fund detector, fund-absorption forecast, or calibration/
weight-recalibration math · `works_sanctioned.csv` (not needed for this scope) · a formal
`pytest` suite · `docs/STATE.md`/`docs/DECISIONS.md`-style long-run tracking (a short README
is enough).

## DATA FACTS — trust these, spend 5-10 minutes spot-checking a few, don't re-derive them

- Load every `mplads_india/**/works_with_images.csv` that currently exists (`glob`), union
  columns, concat. Whatever subset has been scraped so far is fine — do not wait for more.
- **`WORK_CATEGORY` is ~99% one value** (`Normal/Others`) — useless as a peer group. The real
  taxonomy is in `ACTIVITY_NAME`, prefixed like
  `WS/MP18002/2025-2026/197316-Construction of roads...`. Strip it with
  `re.sub(r"^WS/MP\d+/\d{4}-\d{4}/\d+-", "", name)` → ~200 real activities. Use
  `activity_norm × STATE_NAME` as the peer group, falling back to `activity_norm` alone or
  the whole corpus when a group is too small (check with `.groupby().size()` first; ~10 is a
  reasonable floor — verify against what you actually load, don't just trust that number).
- **The "photos" are mostly PDFs, and every sampled PDF is one JPEG in a PDF wrapper**
  (scanned Measurement Books, completion certificates, some real site photos). Extract the
  embedded JPEG yourself, no new library needed:
  ```python
  def jpeg_from_pdf(raw: bytes) -> bytes | None:
      i = raw.find(b"\xff\xd8\xff")
      j = raw.rfind(b"\xff\xd9")
      return raw[i:j+2] if i >= 0 and j > i else None
  ```
  A `.jpg`/`.jpeg` file's bytes are already a JPEG. Attachments live next to each CSV;
  filenames are in `local_image_filenames` (semicolon-separated), resolved relative to the
  CSV's own folder.
- `LETTER_NO` looks like `LN/MP18129/2024-2025/3`, occasionally with stray whitespace
  mid-string. `re.sub(r"\s+", "", letter_no)` then
  `re.match(r"^LN/MP(\d+)/(\d{4})-(\d{4})/(\d+)$", cleaned)` gets `mp_code`,
  `fy_start_year`, `fy_end_year`. Reuse `pipeline/consolidate.py`'s `parse_letter_no` rather
  than reinventing it.
- `ACTUAL_END_DATE` parses with `format="%d-%b-%Y"`.
- Real signal already confirmed present in this exact corpus: dozens of byte-identical
  attachments reused across **different** `WORK_ID`s, a meaningfully larger set of
  *perceptually*-similar (not byte-identical) images across different works once junk
  scanner-app watermark strips are filtered out, and hundreds of exact-duplicate
  `WORK_DESCRIPTION` cases across different fiscal years for the same MP. All three are your
  demo's strongest moments — build all three.
- **Warning from a prior measurement pass, so you don't repeat the mistake**: a *naive*
  perceptual-hash scan on this corpus (no dimension floor, no bucket-size cap, a fixed
  Hamming ≤ 8) produced a single 176-image "duplicate" bucket that was entirely scanner-app
  watermark strips ("Scanned with OKEN Scanner", "CamScanner" logo) spanning five states —
  not fraud, just a common banner. The gating in the duplicate-detection section below exists
  specifically to prevent you from reproducing that. Don't skip it to save time; it's maybe
  15 minutes of work and it's the difference between a credible demo and an embarrassing one.

## WHAT TO BUILD

### 1. Pipeline (`scripts/pipeline.py`)

Loads the corpus, derives `activity_norm`, `peer_group_key` (with fallback), `fy_start_year`,
cleans `WORK_DESCRIPTION` (strip/lower/collapse whitespace), then:

**a. Rules** (3, each a function returning a 0/1 flag + normalized score + a plain-English
reason string with real numbers in it):
- **Cost-per-unit peer outlier** — robust z-score (or MAD) of `ACTUAL_AMOUNT` within
  `peer_group_key`. Flag `z > 2.5` only — a high amount is the concern; an unusually low
  amount is reported for context but never flagged and adds nothing to the score (see
  `docs/DECISIONS.md`, 2026-09-09). State the peer group and its size in the reason.
- **Missing completion evidence** — `image_count == 0`. Low weight, explicitly advisory
  (~35-40% of the corpus will trip this — say so).
- **Round-number clustering** — `ACTUAL_AMOUNT` an exact or near (~1%) multiple of ₹1,00,000.
  Label explicitly as an **unsourced heuristic** — there is no verified MPLADS legal
  threshold backing it.

**b. Anomaly score** — one global `sklearn.ensemble.IsolationForest` (`contamination=0.05`)
over `[amount_z, cost_per_unit_z, image_count]` (RobustScaler first). Explanation: report
which input feature is furthest (z-score) from its peer group's mean.

**c. Duplicate evidence — two tiers, both required, kept distinct end to end:**

- **Tier 1 — byte-identical (photo reuse).** Extract every attachment's JPEG bytes, MD5-hash
  them, group by hash, keep groups spanning more than one `WORK_ID`. Apply the same
  `min(width, height) >= 150` floor as Tier 2 — byte-identical scanner-app footer strips
  ("Scanned with OKEN Scanner", CamScanner logo) repeat across unrelated works and would
  otherwise surface as fake "identical image evidence" pairs (see `docs/DECISIONS.md`,
  2026-09-09). Cache extracted bytes/hashes to `data/image_cache/` so re-running the
  pipeline doesn't re-extract everything.

- **Tier 2 — perceptual near-duplicate, gated.** No new package — hand-roll a DCT pHash with
  what's already installed:
  ```python
  from PIL import Image
  from scipy.fftpack import dct
  import numpy as np

  def phash(img: Image.Image) -> bytes:
      a = np.asarray(img.convert("L").resize((32, 32), Image.LANCZOS), dtype=float)
      d = dct(dct(a, axis=0, norm="ortho"), axis=1, norm="ortho")[:8, :8]
      v = d.flatten()[1:]
      return np.packbits(v > np.median(v)).tobytes()
  ```
  Gate **before** comparing, or you will reproduce the 176-image watermark bucket:
  - Skip images whose `min(width, height) < 150px` (catches the scanner-badge strips).
  - Group by hash (or by low Hamming distance — see below), and if a group spans **more than
    ~6 distinct `WORK_ID`s**, treat it as a common template/watermark, not evidence — log it,
    don't surface it as a duplicate pair.
  - Compute pairwise Hamming distances *between gated hashes only*, print the distribution
    (`describe()` / percentiles), and pick a threshold that visibly separates a small
    near-duplicate cluster from the bulk. Do not default to a textbook value like ≤ 8 without
    checking — on the ungated corpus that specific threshold produced thousands of junk
    pairs. A tighter threshold (e.g. ≤ 4-6) is likely closer to right here, but confirm from
    what you actually see.
  - Every Tier-2 pair is labelled in the UI as "visually similar" — never merged into the
    "byte-identical" language of Tier 1.
  - **Tier 3 (SIFT/ORB keypoint confirmation) is out of scope** — it's a real quality
    upgrade over Tier 2 but the tuning (inlier ratio, overlay rendering) genuinely doesn't
    pay for itself in this timebox once Tier 1 + a well-gated Tier 2 already give two solid,
    distinct evidence tiers.

**d. Cross-year duplicate description.** Normalize `WORK_DESCRIPTION`
(`.strip().lower()`, collapse whitespace). Exact matches: group by `(MP_NAME, normalized_text)`,
keep groups spanning more than one `fy_start_year`. Then, stdlib-only (no new dependency),
also catch *near*-duplicates: within each MP's descriptions, compare pairs across different
`fy_start_year` with `difflib.SequenceMatcher(None, a, b).ratio()`, flag pairs above ~0.9.
Keep exact and near-duplicate results distinguishable in the output.

**e. Fusion** — weighted sum of normalized signals into `risk_score` (0-100), with a
**severity floor**: a Tier-1 photo match or an exact cross-year duplicate forces
`severity_band = "Critical"` regardless of the weighted sum. Bands: 0-30 Low, 31-60
Moderate, 61-80 High, 81-100 Critical. Pick starting weights yourself; record your reasoning
in a one-line comment.

**f. Personas.** After scoring, derive four **real, data-grounded** personas and write them
to `data/personas.json`:
- **`mp_office`** — the MP with the most works in the loaded corpus. Scope: that
  `MP_NAME`/`CONSTITUENCY`.
- **`district_authority`** — pick 2-3 real constituencies within one state that has several.
  **There is no real district column in this data** — do not invent one or imply an official
  administrative boundary. Label it honestly, e.g. `"District Authority — <Constituency A>
  & <Constituency B> cluster, <State>"`. Scope: those constituencies.
- **`state_nodal`** — the state with the most works loaded. Scope: that `STATE_NAME`.
- **`ministry`** — every work currently loaded. Scope: all of it, labelled with real coverage
  (states and constituency count actually present) — never implied as national.

Each persona object: `{id, role, label, jurisdiction_summary, filter}` where `filter` is
whatever `pandas` query the backend needs to scope `/works` to that persona.

**g. Output.** `data/scored_works.parquet` (one row per work: identifying fields, every
signal's raw + normalized value, `risk_score`, `severity_band`, reason strings),
`data/duplicate_pairs.json` (photo Tier-1, photo Tier-2, and text pairs, each tagged with its
tier and the work_ids involved), `data/personas.json`.

### 2. Fraud-injection check (`scripts/evaluate.py`, imports from `pipeline.py`)

Three synthetic patterns, cloned from real rows with a fixed seed, tagged `is_synthetic=True`,
kept in a **separate** file — never merged into `data/scored_works.parquet`:
- **Image reuse** — clone a row to a new fake `WORK_ID`, copy a real attachment's bytes onto
  it unchanged (should trip Tier 1).
- **Cross-year duplicate claim** — clone a row, same MP and description, `fy_start_year + 1`,
  amount nudged ±5-10% (should trip the text-duplicate check).
- **Phantom-ish work** — clone a row, zero out attachments/`image_count`, keep the amount high
  relative to its peer group (should trip missing-evidence + likely the anomaly score).

Measure recall per pattern, write `reports/evaluation.md`: run date, corpus size, each
pattern's recall and which detector caught it. Honest zeros are fine — don't hide them.

### 3. Backend (`backend/main.py`, a couple of files is fine — keep it flat)

FastAPI, loads `data/scored_works.parquet`, `data/duplicate_pairs.json`, `data/personas.json`
into memory at startup. SQLite via stdlib `sqlite3` for one mutable table:
`investigations(work_id, persona_id, decision, reason, decided_at)`.

- `GET /personas` — the 4 personas.
- `GET /works?persona_id=&severity=&sort=risk` — ranked list, **filtered server-side** by the
  persona's scope. (No enforcement beyond this filter — there's no real auth, so don't build
  more security than that; this is correct data-flow, not access control, and should be
  described that way if you leave a comment about it.)
- `GET /works/{work_id}` — full record: every signal, its reason, its normalized value,
  `risk_score`, `severity_band`.
- `GET /works/{work_id}/duplicates` — photo (both tiers) and text pairs involving this work,
  tier named in the response.
- `GET /image/{work_id}/{filename}` — streams the extracted JPEG bytes.
- `POST /investigations` — `{work_id, persona_id, decision, reason}` → SQLite.
- `GET /summary?persona_id=` — counts scoped to that persona; for `ministry`, state actual
  coverage plainly.
- `GET /evaluation` — `reports/evaluation.md`'s numbers as JSON.

Mount the built frontend as static files from the same app so `uvicorn backend.main:app
--port 8000` serves everything after one `npm run build`.

### 4. Frontend — React + TypeScript + Vite, and it should actually look good

`npm create vite@latest frontend -- --template react-ts`. Styling: Tailwind via the CDN play
script (`<script src="https://cdn.tailwindcss.com"></script>` in `index.html`) — this is the
fast path to a polished look without a PostCSS setup; use a full Tailwind install instead
only if you have time to spare. `recharts` for at least one real chart (severity distribution
on the dashboard). `lucide-react` for icons if you want them — small, optional. A router is
your call — `react-router-dom` for real navigation, or simple state-based view switching if
that's faster; either is fine, don't deliberate on it.

Screens:
- **Sign in** — a landing screen with an email-style login. One fixed account per persona
  (`POST /auth/login` → HMAC-signed session token); the account decides the role and
  jurisdiction, so there is no role picker. The token is attached to every request and a 401
  returns to this screen. Superseded the earlier no-token persona picker — see
  `docs/DECISIONS.md` (2026-09-09). This is the payoff for "multiple users, different views":
  make it look intentional, like a proper landing screen.
- **Dashboard** — risk-ranked list/table scoped to the active persona (`GET /works?persona_id=`),
  a severity filter, a coverage line stating what this persona's scope actually covers, and
  the severity-distribution chart. A visible "switch view" control to go back to Persona
  Select.
- **Work Detail** — risk score/band (a clear visual badge, not just a number), every signal's
  reason in plain language, duplicate evidence rendered as real side-by-side images via
  `/image/...` with the tier stated in words ("identical file" vs "visually similar"),
  Confirm/Dismiss with a required reason, immediate feedback that the decision was recorded.
- **Validation** — a panel or screen pulling `GET /evaluation`: the 3 injected patterns and
  their measured recall, in plain language. This is a genuinely persuasive demo moment.

Every risk indicator carries a short, visible "computational signal — needs human review"
line. No accusatory language anywhere. Loading and empty states on every view — no blank
screens while a fetch is in flight.

## IF YOU'RE RUNNING SHORT ON TIME, CUT IN THIS ORDER

1. `react-router-dom` (use state-based view switching instead) and `lucide-react` (skip
   icons).
2. The near-duplicate (`difflib`) pass on descriptions — keep the exact-match cross-year
   check, which is free and already strong.
3. The Recharts chart — keep the ranked list and badges, drop the chart.

**Never cut:** the 4 personas with real jurisdictions, Tier 1 *and* the gated Tier 2 photo
duplicate detection, the rule engine, fusion + ranked list, the React+Tailwind UI (not plain
HTML), Confirm/Dismiss persisting, and the fraud-injection evaluation (even if only 1 of the
3 patterns survives real time pressure, keep at least one).

## VALIDATION — lightweight, run it and look, don't build test infrastructure

- Run the pipeline; print row counts, peer-group size distribution, Tier-1 group count,
  Tier-2 candidate count **before and after gating** (show the gate actually did something),
  and the chosen Hamming threshold with the distribution that justified it.
- **Open 5 Tier-1 pairs and 5 Tier-2 pairs and look at the actual images.** Confirm Tier-2
  isn't secretly full of watermark strips before trusting it.
- Start the server, hit each endpoint once, look at a real response body.
- In a browser: pick each of the 4 personas in turn and confirm the dashboard genuinely
  differs (different work counts, different scope line) — this is the core feature, verify
  it actually works, don't assume it from the code.
- Click into 3 different works, view the duplicate evidence, submit one Confirm and one
  Dismiss, confirm they persist.
- A handful of inline `assert` statements on the rule/gating functions is enough — no
  `pytest` suite required.

## DEFINITION OF DONE

1. `python scripts/pipeline.py` runs over the real corpus and produces scored output,
   gated Tier-1+Tier-2 duplicates, and `data/personas.json` built from real data.
2. `python scripts/evaluate.py` produces `reports/evaluation.md` with real recall numbers.
3. `npm run build` in `frontend/`, then `uvicorn backend.main:app --port 8000` serves both
   the API and the built frontend from one process.
4. In a browser: Persona Select shows 4 real, distinct personas; picking each one produces a
   visibly different, correctly-scoped dashboard; a work detail view shows real signals and
   at least one real Tier-1 and one real Tier-2 duplicate pair rendered side by side;
   Confirm/Dismiss persists; the Validation panel shows real measured recall.
5. No accusatory language, no fabricated citation, no "Nirikshak", no plain unstyled HTML,
   no numbers you didn't compute.
6. A 20-line `README.md`: what this is, the commands to build and run it, and honest
   limitations (no real auth — persona is a demo convenience, not security; small corpus
   slice; heuristic thresholds; synthetic validation only; district grouping is a real-data
   stand-in, not an official boundary).

Start now. Read `pipeline/consolidate.py` for parsing logic you can reuse, skim 3-4 real rows
of one `works_with_images.csv`, then start on `scripts/pipeline.py`. Everything you need is
above — don't re-derive it.
