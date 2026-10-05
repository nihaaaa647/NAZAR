# NAZAR — Detector validation status

_As of 2026-09-28 (Phase 5). "Validated" below means measured against a
labelled set and disclosed as such — never "should work" or "looks right."_

## Image-match detector (pHash candidate retrieval + ORB/RANSAC confirmation)

**Synthetic regression set** (`scripts/evaluate_image_evidence.py`, 8 cases,
explicitly labelled `SYNTHETIC calibration set - not derived from or
representative of real MPLADS attachments`): exact duplicate, resized/
recompressed, minor crop, watermark-only, unrelated generic infrastructure,
legitimate before/after, low-texture, corrupted file. All 8 matched their
expected classification on the last run (`reports/image_evidence_calibration.json`).
This is a **regression guard** — it proves the code didn't silently break,
not that real-world precision is any particular number.

**Real-pair sample** (`reports/image_calibration_sample.csv`, Phase 5 A.1):
38 real pairs stratified by classification × pHash-distance bucket ×
matched-area-coverage bucket, drawn from the 1,788 pairs in
`data/image_matches.json`. `human_label`/`reviewer_reason` columns are
**blank**. Two strata the Phase 5 brief asked for are not currently
distinguishable in this pipeline's output and are disclosed rather than
faked:
- **same-work pairs** — `photo_duplicates()` only ever compares images
  across *different* `work_id`s; same-work comparison was never
  separately implemented (`pipeline/image_evidence.py`'s own module
  docstring flags this as future work, "same-work as separate context").
- **work category / low-texture** — not carried into `image_matches.json`
  per pair.

> **Real-pair precision remains unmeasured.** Until a person fills in
> `reports/image_calibration_sample.csv` (or a larger version of it) by
> actually looking at each pair, no accuracy/precision number for the real
> corpus should be quoted anywhere — PPT included.

## Watermark-rejection

Measured on the real corpus (`reports/image_inventory.json`,
`data/image_matches.json`, one real pipeline run): of 239 unique-image ORB
evaluations, 17 classified `rejected_watermark`, 28 `rejected_generic_similarity`,
194 `confirmed_visual_correspondence`. All watermark/generic rejections are
zero-risk by construction (`detection_contract.py`'s `effective_score` only
allows nonzero for `status=='fired'`) — verified by
`tests/test_photo_signal_standardization.py`.

On the synthetic calibration set specifically, the watermark-only control
case landed on `rejected_generic_similarity` rather than `rejected_watermark`
in one run (both are zero-risk outcomes; the label depends on background
texture crowding the watermark text out of ORB's top-1500 keypoints) — see
`docs/DECISIONS.md`'s Phase 4 entry for the honest writeup of this finding,
including the `watermark_only_zero_risk_rate` metric added specifically
because it's the number that actually matters (both labels are safe).

## Case-volume calibration (Phase 5 A.2)

See `docs/DECISIONS.md`'s "Phase 5 A.2" entry and `reports/case_calibration.json`
for the full before/after distribution. Summary: 2,888 total cases
(unchanged — nothing deleted), `late_sanction` fires on 93.4% of them,
644 (22.3%) fire from `late_sanction` alone. A new `review_tier` field
(`'actionable'` vs `'systemic_cohort'`, threshold `LATE_SANCTION_SEVERE_DAYS_OVER
= 225` days, an explicitly-disclosed judgment call not a validated cutoff)
moves 571 of those into the systemic/cohort view, leaving 2,317 in the
default actionable queue.

## Satellite change-detection

`ml/cv/satellite_change.py`'s NDVI-delta + normalized-pixel-diff baseline
has no formal precision/recall measurement against ground truth in this
corpus — `eval/satellite_ground_truth.csv` exists as a labelled comparison
set but was built by the concurrent satellite-module work in this repo, not
scored against the change-detection output as part of Phase 5. Reported
here as **unmeasured**, not assumed passing. The eligibility gate
(`pipeline/satellite_eligibility.py`) is independently unit-tested
(`tests/test_satellite_eligibility.py`, 12 tests, every gate + every
declared status + the forbidden-claim guard) — that governs *whether* a
result is shown, not whether the result itself is accurate.

## Never validated as "accuracy"

No number in this project is called "accuracy" without a clearly labelled
evaluation set attached to it, per Phase 5's explicit instruction. Where a
number IS reported (e.g. the 8/8 synthetic calibration match, the 194/239
real ORB confirmations), it's reported as exactly what was measured on
exactly what set — never extrapolated to "the model is N% accurate."
