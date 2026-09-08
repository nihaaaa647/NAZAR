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

## Pending choices for Phase 1

The operator selected **Use the local corpus** on 2026-09-08. Defer a full
download until requested. Recommend SQLAlchemy-portable SQLite for development,
PostgreSQL in Docker for the demo, if the operator accepts the database deviation.
Do not select a database or begin schema work until that choice is resolved.
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
