# NAZAR — Measured Data Findings (verify before relying on any of it)

Produced by an architecture review on 2026-09-07 against the repository at
`C:\Users\Niharika\python\sih`. Every number below was **measured**, not assumed.

Astra: re-measure each one in Phase 0 and write the confirmed/corrected results to
`docs/DATA_REALITY.md`. If a finding here turns out to be wrong, the file you write wins —
say so explicitly rather than silently diverging.

## Corpus state at review time

| Fact | Value |
|---|---|
| `works_with_images.csv` files | 76 constituencies, 5 states (Bihar 2711, AP 1065, Telangana 929, Arunachal 221, Assam 207) |
| Completed-work rows | 5,133 (0 duplicate WORK_ID, 0 duplicate WORK_RECOMMENDATION_DTL_ID) |
| `works_sanctioned.csv` files | 8 constituencies, 1,763 rows (backfill incomplete) |
| `_progress.json` | 90 constituencies done for completed, 8 for sanctioned, of ~543 nationally |
| `mplads_india/_consolidated/master_works.parquet` | STALE — 2,682 rows, predates current scrape |
| Attachment files on disk | 3,083 pdf, 826 jpg/jpeg, 1 docx |

## F1 — WORK_CATEGORY is near-constant; the real taxonomy is in ACTIVITY_NAME

`WORK_CATEGORY`: `Normal/Others` 5063, `Repair and Renovation` 69, `Trust and Society` 1.
98.6% one value. Any peer group keyed on it (`category_state_key`) is effectively just
"state", and "fit IsolationForest per WORK_CATEGORY" is one global model wearing a costume.

`ACTIVITY_NAME` holds the real MPLADS activity taxonomy, prefixed with a work-sanction
reference: `WS/MP18002/2025-2026/197316-Construction of roads, link roads, pathways...`.
Strip `^WS/MP\d+/\d{4}-\d{4}/\d+-` and you get **205 distinct activities**:
roads 1007, lighting of public spaces 522, street lights 510, community halls 397,
tube-wells/borewells 383, hand pumps 264, laboratories 178, library books 156, boundary
walls 147, furniture 134, drinking-water pipelines 104, drains 94, CCTV 93, ...

**Implication:** peer grouping, cost-per-unit z-scores, duration percentiles and the
anomaly model must key on a derived `activity_norm` (+ state), not `WORK_CATEGORY`.

## F2 — The "photos" are overwhelmingly PDF-wrapped scanned documents

Every sampled `.pdf` is `%PDF-1.5`, single page, **zero fonts**, exactly one `/DCTDecode`
stream — a JPEG in a PDF envelope. Extract the JPEG directly (byte scan from `FF D8 FF`
to the final `FF D9`, or PyMuPDF/pypdf image extraction). No rasterisation, no quality loss,
original bytes preserved — which matters, because byte-identity is the strongest evidence
tier in F4.

Corpus composition (random sample n=367 of all attachments, after JPEG extraction):

- ~24% tiny strips, min dimension < 200px — scanner-app watermarks
  ("Scanned with OKEN Scanner" banner at 642x81; CamScanner "CS" logo). **Junk.**
- ~66% low-saturation scanned paperwork: **Measurement Book pages**, Completion Reports,
  Work Completion Certificates, itemised Specification/Estimate sheets carrying
  quantity/rate/amount tables, and photo-collage sheets.
- ~10% colour site photographs.

Only 648 of 5,133 rows (12.6%) have a `.jpg/.jpeg` attachment. **3,550 usable images exist
once the PDFs are unwrapped** — 4.4x the naive raster count.

**Implication:** an image pipeline that globs `*.jpg` sees 22% of the evidence. And the
dominant evidence type is a government document, not a landscape photo — which maps directly
onto the CAG-documented "fictitious measurement-book entries" pattern already in project
memory. This is an opportunity, not a setback.

## F3 — GPS coordinates and capture timestamps are burned into the pixels

Project memory records "EXIF stripped by the portal" — true for EXIF **metadata**, false for
the image content. Multiple sampled photos carry GPS Map Camera / NPSS overlays rendered
into the image itself, e.g. `Lat 25.963287 Long 86.47899 ... Bihar, India ...
04/01/2026 04:27 PM GMT +05:30` alongside a Google Maps thumbnail. One sampled work carried
a stamp dated November 2023 against a 2024-25 letter number.

**Implication:** OCR of the overlay recovers latitude, longitude and capture date for a
subset of works. That revives geo-plausibility checks, photo-date-vs-completion-date checks,
a genuine map view, and makes satellite/coordinate-jitter work feasible — all of which the
blueprint parked as unbuildable. Prevalence is **UNMEASURED**. Measure it in Phase 1 before
promising anything downstream of it.

## F4 — Real cross-work duplicate evidence exists, and a false-positive trap sits next to it

Across 3,550 extracted images:

- **70 cross-work byte-identical (MD5) groups.** Real, indisputable, near-certain.
  Examples: WORK_ID 174291 vs 174304 share three identical attachments
  (`242982_1/2/3.pdf` vs `242985_1/3/2.pdf`) in AMALAPURAM(SC); 174334 vs 174347 share
  three (`177924_*` vs `231972_*`).
- Only **2,439 distinct pHashes for 3,550 images** — 31% collide.
- One pHash bucket holds **176 images across 20+ constituencies and 5 states.** These are
  the scanner-watermark strips. Not fraud. Reporting them as a 176-way reuse ring would
  destroy the platform's credibility in front of a judge on the first click.
- At the blueprint's Hamming <= 8 threshold: **3,687 cross-work pairs.** Unusable as-is.

**Implication:** tier the evidence. MD5 identity = near-certain (severity floor). pHash
near-duplicate only behind an entropy/variance floor, a minimum-dimension floor, and a hard
cap on bucket size. SIFT/ORB confirmation before anything reaches an officer.

## F5 — works_sanctioned.csv is far richer than the blueprint assumes

Columns absent from the completed table: `SANCTION_AMOUNT`, `SANCTION_DATE`,
`RECOMMENDATION_DATE`, `WORK_STAGE`, `TENURE_START_DATE`, `TENURE_END_DATE`,
`HOUSE_OF_PARLIAMENT`, `TENURE`.

`WORK_STAGE` values: Physical Inspection 681, Sanction 563, Work Completed 335,
Work partially Completed 136, Vendor Identification 42, Time Estimation 6 — a real
workflow state machine.

Join on `WORK_RECOMMENDATION_DTL_ID`: all 929 Telangana completed rows matched a sanctioned
row. `ACTUAL_AMOUNT - SANCTION_AMOUNT`: **zero overruns**, 551 exact, 378 underspends
(largest -404,979). The portal appears to enforce the ceiling.

**Implication:** (a) the `sanction_date_proxy` = 1-Apr hack is unnecessary for joined rows —
use the real `SANCTION_DATE`, and keep the proxy only as a documented fallback;
(b) a "sanction-limit breach" detector will find zero and must be reported as a
verified-clean control, never dressed up as a headline; (c) the meaningful signals here are
*underspend vs sanction* (short execution — a real CAG pattern) and *stage latency*.

## F6 — Dead and misread columns

- `AVERAGE_RATING`: 0.0 for all 5,133 rows. Dead — do not model it, do not show it.
- `FLAG`: constant 3 ("Works Completed"). Dead.
- `FILE_STATUS`: `True` (3,231) or NaN (1,902) — it tracks **attachment presence**, not work
  status. 1,902 rows (37%) have zero attachments. Engine 5's "filter to
  `FILE_STATUS != complete`" rests on a misreading; the real status field is `WORK_STAGE`
  in the sanctioned table.
- `ACTUAL_AMOUNT` minimum is 0 (12 rows at <= ₹1).
- 717 of 5,133 amounts are exact ₹1,00,000 multiples — relevant to digit-distribution work.

## F7 — The blueprint's headline rule is not a real MPLADS rule

The "sub-₹10L structuring" rule cites a "₹10,00,000 sanction/scrutiny threshold". No such
threshold appears in the MPLADS Guidelines 2023, and 759 works in this corpus exceed ₹10L.
546 works fall in ₹9L-₹10L, which is a distribution artefact until something proves otherwise.

Real, citable rules, scored against data actually held:

| Rule | Source | Data needed | Have it? |
|---|---|---|---|
| ₹5 crore per MP per annum entitlement, released as 2 x ₹2.5 cr | MPLADS Guidelines 2023 | amounts per MP per FY | yes |
| **Works must be sanctioned within 75 days of receipt of recommendation** | MPLADS Guidelines 2023 | RECOMMENDATION_DATE, SANCTION_DATE | yes — in the sanctioned table |
| ₹75 lakh ceiling for assets built by trusts and societies | MPLADS Guidelines 2023 | IDA entity type + amount | partially (parse IDA_NAME) |
| ₹25 lakh/yr outside own constituency; ₹1 crore anywhere for calamity relief | MPLADS Guidelines 2023 | MP constituency vs IDA district | partially |
| 15% of entitlement to SC-inhabited areas, 7.5% to ST-inhabited areas | MPLADS Guidelines 2023 | area demographics — **not** the (SC)/(ST) constituency reservation tag | **no — do not fake this** |
| A demand must not be split into small quantities to avoid higher sanction authority | GFR 2017 Rule 163 | description clusters + amounts | yes, but the threshold is unproven |

The 75-day sanction rule is the single strongest addition available: hard, dated, citable,
measurable, and completely absent from the current blueprint.

Cite in code comments: mplads.gov.in "Pocket Book on MPLADS Guidelines"; PIB release on the
Revised MPLADS Guidelines 2023.

## F8 — Environment

Python 3.13.7. Installed: pandas, numpy, scikit-learn, scipy, pyarrow, torch 2.10 (**CPU
only, no CUDA**), opencv, shap, fastapi, transformers, onnxruntime, pytesseract, Pillow.
Missing: imagehash, sentence-transformers, pymupdf/pypdf, easyocr.
`pytesseract` is installed but **there is no tesseract binary on PATH** — the Python wrapper
alone does nothing. No git repository. No requirements.txt, pyproject.toml, or lockfile of
any kind. Windows 11, PowerShell primary shell.
