# NAZAR — Data provenance

_As of 2026-09-28 (Phase 5). This file says WHERE each dataset comes from
and what kind of claim it can support. For measured corpus statistics
(row counts, join rates, missingness), see `docs/DATA_REALITY.md` — this
file doesn't repeat those numbers, it classifies the sources._

## Public MPLADS data (real)

- **Source:** MPLADS scheme public portal records (completed-work CSVs +
  sanctioned-work CSVs), scraped separately and **not redistributed in this
  repository** (git-ignored, per `README.md`'s Data section).
- **Coverage:** 5 states (Bihar, Telangana, Andhra Pradesh, Arunachal
  Pradesh, Assam) — partial geographic coverage, not a national sample. See
  `docs/DATA_REALITY.md` for exact row/join counts.
- **What it can support:** every `IMPLEMENTED_PUBLIC_DATA` capability in
  `docs/CAPABILITY_MATRIX.md` — cost/anomaly/duplicate/inefficiency
  detection, case consolidation, the review workflow.
- **What it cannot support:** a released/spent-balance figure (so
  `long_open_work` is a duration proxy, never "idle funds" in the literal
  financial sense), or geotagged coordinates at scale (satellite screening
  uses a separate, smaller, OpenStreetMap-sourced set — see below).

## Attachment images (real, from the public corpus)

- **Source:** image/PDF attachments referenced by the completed-work CSVs,
  extracted by `scripts/pipeline.py: extract_images`/`classify_pdf_failure`.
- **Provenance kept per image:** source filename, work ID, content hash
  (MD5), decode/validation status, and (Phase 5 A.4) an explicit failure
  category when extraction fails — see `reports/image_inventory.json`.
- **What it cannot support:** a claim that an embedded raster is
  necessarily a completion photograph rather than a letterhead/logo — a
  raster below `MIN_IMAGE_DIM` recovered from a PDF is tagged
  `document_page`, never silently treated as photographic evidence.

## Satellite/vendor demonstration data (mixed — real imagery, fictional identities)

- **Coordinates:** real OpenStreetMap points for real infrastructure
  categories (roads, dams, boreholes, etc. — see
  `pipeline/fetch_satellite_pairs.py`, `docs/SATELLITE_MODULE_DATA_REALITY.md`).
- **Imagery:** real Sentinel-2 L2A scenes (via a STAC API), with real
  per-scene `eo:cloud_cover` and acquisition dates stored in
  `data/satellite_cache/manifest.json`.
- **MP names, IDA names, vendor names, and the risk narrative connecting
  them:** **fictional**, generated for Branch A/B demonstration purposes —
  see `docs/SATELLITE_MODULE_DATA_REALITY.md` for the full disclosure and
  `SAT_NOTICE` (`backend/main.py`), which is returned on every satellite/
  vendor-network API response so this is never silently presented as real.
- **What it can support:** a demonstration of the satellite-screening
  *workflow* (eligibility gating, change detection, review UI) against
  real coordinates and real imagery.
- **What it cannot support:** any claim about a real MP, real implementing
  agency, or real vendor — the demonstration's narrative layer is
  synthetic by construction, disclosed in-product, not just in this file.

## Synthetic calibration/evaluation sets

- `scripts/evaluate_image_evidence.py` (8 cases) and
  `scripts/evaluate.py`/`pipeline/fraud_injection.py`'s injected fraud
  patterns are **entirely synthetic**, generated to exercise specific code
  paths (exact duplicate, watermark-only, cost-structuring, etc.) — never
  derived from or representative of a real MPLADS attachment or a real
  fraud case. Every output file from these (`reports/image_evidence_calibration.json`,
  `reports/evaluation.json`) is labelled as synthetic in its own contents.

## Authorised-data-required capabilities

Listed explicitly in `docs/CAPABILITY_MATRIX.md`'s `AUTHORISED_DATA_REQUIRED`
row — real released/spent-balance figures and real geotagged project
records at MPLADS scale. Neither is available in the public corpus this
prototype was built against; both would require government-authorised data
access to implement for real, not just as a demonstration.
