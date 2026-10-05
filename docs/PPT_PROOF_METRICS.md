# NAZAR — PPT-safe proof metrics

_As of 2026-09-28 (Phase 5 section K). Every number below is reproduced
from a real pipeline run against the real (partial, 5-state) local corpus —
never invented, never extrapolated beyond what was actually measured.
**Do not quote any number here as "accuracy" or as a national statistic —
see the warning at the bottom of each section.**_

## Corpus scale

| Metric | Value | Command | Notes |
|---|---:|---|---|
| Completed-work records | 5,611 | `python scripts/pipeline.py` | 5 states: Bihar, Telangana, Andhra Pradesh, Arunachal Pradesh, Assam |
| Sanctioned-work records (full universe) | 11,832 | same | 6,221 with no completed-work match yet |
| Detector version | `pipeline-scoring-v2` | `data/case_candidates.json` (`fired_signals[].detector_version`) | |
| Threshold version | `thresholds-v1` | same | |

⚠️ **Partial geographic coverage — not a national finding.** 5 of 28+
states/UTs. Do not present any count here as representative of MPLADS
nationally.

## Tests

| Metric | Value | Command |
|---|---:|---|
| Total tests passing | 210 (0 failing) | `python -m pytest -q` |
| New tests added this phase (Phase 5) | 24 | `tests/test_production_security.py` (9), `tests/test_pdf_extraction.py` (5), `tests/test_satellite_reconciliation.py` (4), `tests/test_image_calibration_sample.py` (2), 4 new in `tests/test_cases.py` |

_Exact count reproducible with `python -m pytest --collect-only -q`; run
timestamp 2026-09-28._

## Image evidence (real corpus)

| Metric | Value | Command | Notes |
|---|---:|---|---|
| Attachment references | 4,229 | `python scripts/pipeline.py` | writes `reports/image_inventory.json` |
| Decodable | 4,144 | same | up from 3,963 pre-Phase-5 — see PDF recovery below |
| Invalid/unrecoverable (Phase 5 A.4 classifies why) | 85 | same | `unsupported_image_format`: 79, `pdf_without_extractable_image`: 6 |
| **Recovered via real PDF parsing (Phase 5 A.4)** | **181** | same | genuine embedded rasters PyMuPDF found that the old byte-scan missed — never a rendered page, only real embedded images (`classify_pdf_failure`) |
| PDF-attachment recovery rate | 181/266 = 68.0% | same | of the attachments that failed before Phase 5, this fraction now decode |
| Unique images by content hash | 3,752 | same | |
| Exact-duplicate image groups | 80 | same | |
| Unique cross-work image pairs ORB-evaluated | 254 | `data/image_matches.json` | |
| `confirmed_visual_correspondence` | 205 | same | requires human review — **not** duplicate/fraud by itself |
| `rejected_watermark` (zero risk) | 20 | same | |
| `rejected_generic_similarity` (zero risk) | 29 | same | |

⚠️ **These are counts, not a precision/recall measurement.** No claim is
made here about what fraction of the 194 `confirmed_visual_correspondence`
pairs are, on human review, actually duplicated evidence — see
`docs/DETECTOR_VALIDATION.md`: real-pair precision remains unmeasured
pending `reports/image_calibration_sample.csv` adjudication.

## Case consolidation and calibration (Phase 5 A.2)

| Metric | Value | Command |
|---|---:|---|
| Raw signal instances (before consolidation) | 50,499 | `python scripts/pipeline.py` |
| Consolidated review cases | 2,893 | same — unchanged by Phase 5's calibration (nothing deleted) |
| `review_tier = actionable` (default queue) | 2,326 | `reports/case_calibration.json` |
| `review_tier = systemic_cohort` | 567 | same |
| Cases created by `late_sanction` alone | 640 (22.1% of all cases) | same |
| Cases combining `late_sanction` + an independent signal | 2,060 (71.2%) | same |

⚠️ These are pipeline-computed counts on the 5-state corpus, reproducible
via `python scripts/pipeline.py` then reading `reports/case_calibration.json`
— not a claim about fraud prevalence or a validated detection rate.

## Synthetic calibration (regression guard, not real-world evidence)

| Metric | Value | Command |
|---|---:|---|
| Synthetic image-evidence controls | 8/8 matched expected classification | `python scripts/evaluate_image_evidence.py` → `reports/image_evidence_calibration.json` |

⚠️ **Explicitly synthetic** — every case in this set is labelled
`SYNTHETIC calibration set - not derived from or representative of real
MPLADS attachments` in its own output file. Never quote this as real-corpus
accuracy.

## What this project does NOT claim

- No number here is called "accuracy" without the labelled evaluation set
  it was measured against named alongside it (per this phase's mandatory
  instruction).
- No feature declares fraud; `confirmed_visual_correspondence` means
  geometric correspondence requiring human review.
- No satellite result states a project "was not built" — only
  `change_visible` / `no_reliable_change_visible`, both requiring human
  review.
- No deployment metric (latency, uptime) is reported here — no live
  deployment exists from this development environment; see
  `docs/DEPLOYMENT.md`.
