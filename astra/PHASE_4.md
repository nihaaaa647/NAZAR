# PHASE 4 — Learned and Similarity Engines: Anomaly, Photo Reuse, Text Duplicates

Assumes the repository produced by Phase 3: deterministic engines running and measured,
`risk_signal` populated, evaluation report live.

## OBJECTIVE

Implement blueprint Engines 2, 3 and 4 — the signals rules cannot express — with the
false-positive controls the real corpus demands.

## CONTEXT

Correction 3 is the load-bearing one here. The prior review measured 70 genuine cross-work
byte-identical groups (real evidence, and the demo's best moment) sitting alongside a single
pHash bucket of 176 scanner-watermark strips and 3,687 cross-work pairs at Hamming ≤ 8. The
difference between a credible system and an embarrassing one is entirely in the gating.

## TASKS

1. **Engine 2 — Isolation Forest** (`ml/anomaly/`).
   - Features: normalised amount, cost-per-unit robust z-score within peer group,
     `duration_days`, usable attachment count (junk excluded), `days_to_fy_end`,
     `rule_flag_count`, and — where available — sanction-to-completion latency and
     underspend ratio. Scale with `RobustScaler`.
   - Fit per activity family (Correction 1), not per `WORK_CATEGORY`. Where a family is too
     small to fit, fall back and record which model scored each work.
   - `contamination` set from a stated prior, not tuned until the output looks right. Record
     the reasoning.
   - SHAP per-feature contributions for every flagged work, persisted for the UI.
   - Persist a `model_version` row per fit: params, timestamp, evaluation metrics.
2. **Engine 3 — Duplicate evidence** (`ml/cv/`), three tiers, kept distinct end to end:
   - **Tier 1 — byte identity.** SHA-256 groups spanning different `work_id`s. Near-certain;
     feeds the severity floor. Exclude same-work multi-angle attachments.
   - **Tier 2 — perceptual near-duplicate.** pHash Hamming distance, but only over images
     that pass the entropy floor, the minimum-dimension floor and the `media_class` filter
     (`junk_watermark` excluded entirely), and only from hash buckets under a size cap.
     Choose the Hamming threshold from the measured distance distribution on *gated* images,
     not from the blueprint's 8.
   - **Tier 3 — keypoint confirmation.** SIFT (or ORB) inlier ratio on Tier-2 candidates
     only. A pair reaches an officer as "confirmed" only after Tier 1 or Tier 3.
   - Store keypoint-overlay or side-by-side artefacts for the evidence tab.
   - Report separately: within-constituency, cross-constituency and cross-state matches.
     Cross-state duplicate paperwork is a materially stronger claim than two similar photos
     in one district.
3. **Engine 4 — NLP duplicate work** (`ml/nlp/`).
   - `sentence-transformers` `all-MiniLM-L6-v2` over cleaned `work_description`, scoped per
     MP and per constituency, **across fiscal years**. Verify the package installs on
     Python 3.13 before committing to it; if it does not, ask before substituting.
   - Agglomerative clustering on cosine distance. Set the threshold from the measured
     similarity distribution — note that 722 descriptions in this corpus are *exactly*
     duplicated, and repeated standard phrasing for genuinely different works is common.
     Same-year near-identical descriptions are normal; cross-year repetition is the signal.
   - GFR 2017 Rule 163 split-work check: near-identical descriptions from the same MP or
     agency within a short window, individually small, summing past a sanction threshold.
     The threshold is unproven for MPLADS — implement it parameterised and label the claim
     honestly.
   - Extract quantities and units from descriptions where present ("500 mtr", "2 km") for a
     real cost-per-unit denominator; report what fraction of descriptions yield one.
4. Run the harness. Update `reports/evaluation.md` with per-pattern recall and
   precision@K for each engine, against the Phase-2 baselines.

## CONSTRAINTS

- Every duplicate pair carries its tier and the numeric evidence for it. The UI must be able
  to say *why* this pair is near-certain rather than merely similar.
- Do not report a duplicate group larger than a sane cap as a single finding without
  investigating what is actually in it first.
- Do not tune `contamination` or the similarity threshold against the injected cases — that
  is fitting to your own test set. Set them from the real distribution, then measure.
- Cache embeddings and hashes; the pipeline must not recompute the whole corpus on every run.
- Precision matters more than recall for photo reuse (blueprint Part P) — a false accusation
  of photo fraud against a named agency is the most costly error this system can make.

## VALIDATION

- **Open the top 20 duplicate pairs and look at them.** Report how many are genuine, how many
  are junk, and what the gating missed. This is the single most important check in the phase.
- The 176-image watermark bucket, or its equivalent in the current corpus, is demonstrably
  excluded — show the before/after counts.
- Anomaly score distribution plotted per activity family; the top 10 anomalies read by hand
  and assessed.
- Text clusters: read the top 20 cross-year clusters and report how many are genuine
  duplicate-asset claims versus normal repeated phrasing.
- Timing: full CV and NLP pass over the corpus, wall-clock recorded.
- Tests: hash gating, tier assignment, same-work exclusion, cluster scoping, SHAP output shape.

## COMPLETION CRITERIA

- Three engines run over the full corpus and populate `risk_signal` and `duplicate_pair`.
- Tiered duplicate evidence with the gating in place and its effect measured.
- Measured per-pattern recall and precision@K in `reports/evaluation.md`, compared to the
  random and sort-by-amount baselines.
- Your hand-inspection results are written down, including the failures.

## INSPECT BEFORE MOVING ON

State plainly in `docs/STATE.md` how many of the top 20 duplicate pairs you would show to a
District Collector. If that number is low, fix the gating before proceeding — everything
downstream inherits this credibility.
