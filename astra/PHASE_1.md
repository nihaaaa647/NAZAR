# PHASE 1 — Canonical Data Layer and Attachment Pipeline

Assumes the repository produced by Phase 0: git initialised, environment pinned,
`docs/DATA_REALITY.md` written from your own measurements, contradictions listed in
`docs/STATE.md`.

## OBJECTIVE

Turn scattered CSVs and 3,900 opaque attachment files into one canonical, validated,
queryable dataset — including the extracted, triaged, hashed image corpus that every later
CV detector depends on. After this phase, no engine ever touches a raw CSV again.

## CONTEXT

`pipeline/consolidate.py` already parses `LETTER_NO`, derives fiscal-year bounds,
`sanction_date_proxy`, `duration_days`, `days_to_fy_end`, `has_images` and the normalised
text columns. It is good code with accurate comments. Extend it; do not rewrite it.

The corrections that land in this phase: `activity_norm` as the real taxonomy (Correction 1),
PDF-wrapped JPEG extraction and triage (Correction 2), the sanctioned-table join with real
dates and `WORK_STAGE` (Correction 4), and dropping dead columns (Correction 5).

## TASKS

1. **Canonical schema.** Implement blueprint Part D as SQLAlchemy models with Alembic
   migrations, amended by `docs/DATA_REALITY.md`: add `activity_norm`, `sanction_amount`,
   `sanction_date`, `recommendation_date`, `work_stage`, `peer_group_key`; drop
   `average_rating` and `flag`; rename `file_status` to something that says what it is
   (attachment presence). Add to `work_image`: `media_class`, `sha256`, `phash`,
   `width`, `height`, `entropy`, `extracted_from_pdf`, and the OCR fields from task 4.
2. **Ingestion.** `pipelines/ingest.py`: walk both CSV families, union columns defensively
   (files genuinely differ in schema — `consolidate.py` explains why), join completed to
   sanctioned on `WORK_RECOMMENDATION_DTL_ID`, load into the database idempotently
   (re-running must not duplicate rows), and write the consolidated parquet as before.
3. **Schema/Value Validator** (blueprint Part C): reject or flag negative and zero amounts,
   unparseable dates, unparseable `LETTER_NO`, completion dates preceding sanction dates,
   and sanction dates preceding recommendation dates. Validation outcomes are recorded per
   row, not silently dropped — an invalid record is itself a signal.
4. **Attachment extraction and triage** — `pipelines/attachments.py`:
   - Extract the embedded JPEG from each PDF (byte-scan or PyMuPDF/pypdf). Cache extracted
     bytes; do not re-extract on every run.
   - Compute `sha256`, pHash, dimensions and Shannon entropy per image.
   - Classify `media_class` into `junk_watermark` (below the dimension floor, or matching a
     known scanner-app watermark hash), `scanned_document`, `site_photo`, `photo_collage`.
     Derive the rules from measured distributions, not from my description of them.
   - Handle unreadable attachments (~5% failed extraction in the prior review) without
     aborting the run; count and report them.
5. **Measure the GPS-overlay prevalence** (Correction 8). Attempt OCR on a stratified sample
   of `site_photo` images. Report: what fraction carry a parseable `Lat`/`Long` overlay, what
   fraction carry a parseable capture timestamp, and the accuracy you observed by eye on a
   sample. Write the number into `docs/DATA_REALITY.md`. Then put ASK #2 to the operator with
   this measurement attached — you now have the evidence they need to decide.
   If no tesseract binary is available, say so, propose options, and do not silently skip
   the measurement.
6. Extend `scripts/profile_data.py` to profile the loaded database, so the profile stays
   truthful as the corpus grows.

## CONSTRAINTS

- Idempotent. Re-running ingestion over a grown corpus updates rather than duplicates.
- The full attachment pass over ~3,900 files must complete in reasonable time and be
  resumable; a crash at file 3,000 must not cost the first 3,000.
- No detector logic in this phase. Hashes and classifications only — no pair-finding.
- Peer-group assignment (`peer_group_key`) is computed here with the fallback ladder from
  Correction 1, and the size of every resulting group is reported.

## VALIDATION

- Ingestion run over the full corpus; row counts reconciled against
  `scripts/profile_data.py` and any discrepancy explained.
- `media_class` distribution printed; **open and look at 10 images per class** and report
  whether the classifier is right. Do not trust the counts alone.
- Join rate reported; unjoined completed rows counted and explained.
- Peer-group size distribution printed, with the count of works falling to each fallback level.
- Tests: `LETTER_NO` parser, date parsing (`%d-%b-%Y`), fiscal-year boundary logic, PDF JPEG
  extraction against a real file, validator rules, idempotent re-ingestion.
- Error paths exercised: a deliberately corrupted PDF, a CSV row with a missing image file,
  an empty peer group.

## COMPLETION CRITERIA

- One command loads the entire corpus into the database from scratch, and running it twice
  changes nothing.
- Every attachment has a `media_class`, `sha256`, and — where meaningful — a pHash.
- Every work has a `peer_group_key` and a validation status.
- GPS-overlay prevalence is measured and recorded; ASK #2 is with the operator.
- `docs/DATA_REALITY.md` and `docs/STATE.md` updated; tests pass; committed.

## INSPECT BEFORE MOVING ON

Query the database directly. Pick five works at random and read every field against their
source CSV row and their attachment files on disk. Confirm the canonical record tells the
truth about each one.
