# NAZAR — Capability matrix

_As of 2026-09-28 (Phase 5). Machine-readable form: `GET /capabilities` on the
running backend — keep both in sync by hand; this file is not generated from
the endpoint._

Categories, as specified by Phase 5:

- **IMPLEMENTED_PUBLIC_DATA** — runs today, against the real public MPLADS corpus.
- **DERIVED_PUBLIC_DATA** — runs today, but the underlying corpus is public
  MPLADS data joined with a second public source (OpenStreetMap, Sentinel-2)
  rather than MPLADS alone.
- **SYNTHETIC_DEMONSTRATION** — real code, but exercised only on a labelled
  synthetic/demo dataset, not the real corpus.
- **AUTHORISED_DATA_REQUIRED** — the code exists but cannot run meaningfully
  without a data field this public corpus doesn't have.
- **IN_DEVELOPMENT** — started, not complete.
- **UNAVAILABLE** — not implemented, or implemented but structurally empty
  until a precondition (e.g. recorded usage) is met.

| Capability | Category | Notes |
|---|---|---|
| `cost_peer` (peer-relative cost z-score) | IMPLEMENTED_PUBLIC_DATA | `scripts/pipeline.py` |
| `anomaly` (Isolation Forest) | IMPLEMENTED_PUBLIC_DATA | one global fit, `contamination=0.05` |
| `missing_evidence` | IMPLEMENTED_PUBLIC_DATA | advisory-weight only |
| `text_exact` / `text_similar` | IMPLEMENTED_PUBLIC_DATA | exact + `difflib` fuzzy, no embeddings |
| `entitlement_pace` | IMPLEMENTED_PUBLIC_DATA | sourced (MPLADS Guidelines 2023 ₹5cr/MP/yr), deliberately hedged |
| `long_open_work` | IMPLEMENTED_PUBLIC_DATA | peer-relative duration z-score; not "idle funds" — no released/spent-balance field exists |
| `late_sanction` | IMPLEMENTED_PUBLIC_DATA | 45-day Phase 3 review indicator; see `docs/DECISIONS.md` for the unresolved 75-day citation discrepancy |
| `photo_identical` (MD5) / `photo_similar` (pHash+ORB+RANSAC) | IMPLEMENTED_PUBLIC_DATA | watermark-masked; candidate-only stays unscored |
| `data_quality_alerts` | IMPLEMENTED_PUBLIC_DATA | rupee/lakh/crore normalization, zero fraud-risk contribution |
| `case_consolidation` + `review_tier` | IMPLEMENTED_PUBLIC_DATA | deterministic case IDs, Phase 5 A.2 calibration |
| `jurisdiction_rbac` | IMPLEMENTED_PUBLIC_DATA | default-deny, server-enforced, Argon2id + JWT |
| `audit_log` | IMPLEMENTED_PUBLIC_DATA | append-only, every access-denial + reviewer action |
| `review_workflow` (8-state cases, image-match reviews) | IMPLEMENTED_PUBLIC_DATA | no "declare fraud" action anywhere |
| `satellite_change_screening` | DERIVED_PUBLIC_DATA | Branch A demo scope only: OpenStreetMap-sourced coordinates + real Sentinel-2 imagery; MP/IDA/vendor names in the satellite demo dataset are fictional (see `docs/SATELLITE_MODULE_DATA_REALITY.md`) |
| `vendor_network_patterns` | DERIVED_PUBLIC_DATA | same fictional-identity caveat as above |
| `image_evidence_calibration_set` | SYNTHETIC_DEMONSTRATION | 8 labelled synthetic controls (`scripts/evaluate_image_evidence.py`) — a regression guard, not evidence of real-world precision |
| `real_pair_precision` | IN_DEVELOPMENT | Phase 5 A.1 stratified sample exists (`reports/image_calibration_sample.csv`, `scripts/build_image_calibration_sample.py`) but is **unfilled** — no human adjudication has occurred; real-pair precision is unmeasured |
| `real_release_spent_balance_for_idle_funds` | AUTHORISED_DATA_REQUIRED | this corpus has no released/spent-balance field; `long_open_work` is a duration proxy, not a financial "idle funds" claim |
| `real_geotagged_coordinates_at_scale` | AUTHORISED_DATA_REQUIRED | satellite screening at MPLADS scale needs authorised geotagged project records, not OpenStreetMap seed coordinates |
| `cloud_cover_check` / `imagery_timeline_skew_check` | IMPLEMENTED_PUBLIC_DATA | Phase 5 section B: wired from real per-scene STAC `eo:cloud_cover` and `ACTUAL_END_DATE` — previously hardcoded to "not checked" |
| `cases_resolved_per_investigator_hour` | UNAVAILABLE | requires recorded `case_review_sessions` data; stays `"unavailable"` until reviewers actually use the review-session start/end endpoints |
| Deployed live prototype (Vercel/Render/Neon) | UNAVAILABLE (this environment) | no deployment credentials/accounts available in this development environment — see `docs/DEPLOYMENT.md` for exactly what's configured vs. blocked |

## Never claimed, anywhere

- No feature automatically declares fraud. `photo_similar`/`confirmed_visual_correspondence`
  mean *geometric correspondence requiring human review*, not duplication or fraud.
- Satellite screening never states a project "was not built" (`FORBIDDEN_CLAIM`
  in `pipeline/satellite_eligibility.py`, asserted never-emitted by
  `tests/test_satellite_eligibility.py`).
- `late_sanction` is a computational timeline check, never "fraud" or "proven
  non-compliance" (exact wording enforced by `tests/test_...` and this file).
