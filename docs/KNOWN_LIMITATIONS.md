# NAZAR — Known limitations

_As of 2026-09-28 (Phase 5). This file exists so limitations are stated
once, honestly, instead of being scattered across code comments a reader
might miss — see `docs/DECISIONS.md` for the reasoning behind each one._

## Detection

- **Real-pair image-match precision is unmeasured.** The 8-case synthetic
  set (`scripts/evaluate_image_evidence.py`) is a regression guard, not
  evidence about the real corpus. `reports/image_calibration_sample.csv`
  (Phase 5 A.1) draws a real stratified sample but its `human_label` column
  is **blank** — no adjudication has occurred yet.
- **Watermark masking is geometric (border-region), not OCR-based.** A
  watermark placed in the image centre, or an unfamiliar scanner template
  whose text sits outside the masked border strips, would not be masked and
  could inflate ORB keypoint matches. `pipeline/image_evidence.py`'s
  masking only covers the top/bottom border fraction.
- **`long_open_work` and `late_sanction` are duration proxies, not financial
  or legal findings.** This corpus has no released/spent-balance field
  (`long_open_work`) and the 45-day review window has an unresolved
  discrepancy against an earlier 75-day citation (`late_sanction`) — see
  `docs/DECISIONS.md`'s Phase 3/4 entries. Neither claims fraud or proven
  non-compliance.
- **Priority-band skew.** `review_tier` (Phase 5 A.2) fixes which cases
  reach the default queue, but the underlying `anomaly_priority`/
  `inefficiency_priority` numeric bands still skew toward "critical"
  (95.5% of all cases) because `late_sanction`'s score distribution is
  itself right-skewed toward its cap. See `docs/DECISIONS.md`'s Phase 5 A.2
  entry.

## Satellite screening

- **Branch A demo scope only.** Coordinates are OpenStreetMap-sourced
  (real), Sentinel-2 imagery is real, but MP/IDA/vendor names in the
  satellite demo dataset are fictional — see
  `docs/SATELLITE_MODULE_DATA_REALITY.md`. Production verification at
  MPLADS scale requires authorised, geotagged project records this public
  corpus does not have.
- **Change detection is NDVI-delta + pixel-diff, not a trained model.**
  `ml/cv/satellite_change.py`'s baseline can be fooled by seasonal
  vegetation change unrelated to construction; both signals must agree past
  a threshold specifically to reduce (not eliminate) that false-positive
  mode.
- Only `change_visible` / `no_reliable_change_visible` ever reach a
  reviewer; every other eligibility status is a reason the check could not
  be attempted, never "no change found."

## Review-effort metrics

- **`cases_resolved_per_investigator_hour` starts empty by design** — it is
  computed only from recorded `case_review_sessions` start/end events
  (never inferred from case age), and no reviewer has used those endpoints
  in this development environment yet.

## Security / production hardening

- **Login rate limiting is a single-process, in-memory sliding window**
  (`backend/main.py: _login_attempts`). A multi-worker deployment (e.g.
  Render running >1 uvicorn worker) would give each worker its own
  counter, effectively multiplying the limit by worker count. A shared
  store (Redis, or the database) would fix this; not built, since this
  prototype's default deployment is single-worker.
- **CORS defaults to wildcard (`*`) outside `NAZAR_ENV=production`.**
  Production refuses to start with a wildcard (Phase 5 section E), but
  `render.yaml` as committed still ships `NAZAR_CORS_ORIGINS=*` as a
  placeholder pending the real Vercel URL — see `docs/DEPLOYMENT.md`.
- **No automated dependency vulnerability scan has been run** in this
  environment (no network access to a vulnerability database). `pip list`
  and `requirements.txt` are pinned; a `pip-audit` or `safety` pass is
  recommended before a real deployment, not performed here.
- **SSRF surface:** no API endpoint accepts an arbitrary URL for
  server-side fetching. Satellite/vendor imagery fetching
  (`pipeline/fetch_satellite_pairs.py`) is an offline pipeline script run
  by a developer, not an API request handler — so it is not reachable by
  an untrusted request, but it also means its own credential/URL handling
  was not re-audited as part of this phase's API-surface security pass.

## Deployment

- **No live prototype, backend, or public repository URL exists from this
  development environment** — no Vercel/Render/Neon/GitHub account access
  is available here. See `docs/DEPLOYMENT.md` for exactly what is
  configured (build commands, env var contracts, operational endpoints)
  versus what remains blocked on real credentials.
- **Evidence-file deployment is trimmed.** `scripts/prepare_deploy_data.py`
  ships a subset (`deploy_data/`) sized for a free-tier host, not the full
  local corpus — see that script and `docs/DEPLOYMENT.md` for the exact
  selection method and resulting demo limitations.

## PDF/attachment extraction

- `classify_pdf_failure` (Phase 5 A.4) only recovers a genuine **embedded**
  raster image from a PDF — it never rasterizes/renders a page to
  manufacture a photo, so a scanned document with no embedded image stays
  correctly unavailable to image matching (`pdf_without_extractable_image`
  or `document_page`), by design, not as a gap.
