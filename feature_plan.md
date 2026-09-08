# MPLADS Anomaly Engine — Feature Plan

SIH Problem Statement 26102. No fraud labels exist anywhere in this data (or realistically anywhere for MPLADS), so the whole approach is unsupervised/rule-augmented, not classification. Every detector below produces a normalized signal that feeds one fused per-work risk score — see [problem_statement.txt](problem_statement.txt) for the source brief and `pipeline/consolidate.py` for the Phase 0 feature-engineering foundation these all build on.

## 1. Rule-based flags (no training data needed, most explainable)

- **Fiscal year-end dumping** — share of an MP/IDA's completions in the last ~45 days of the fiscal year, vs. peer average.
- **Sub-₹10L structuring** — `ACTUAL_AMOUNT` sitting just under the ₹10,00,000 sanction/scrutiny threshold.
- **Missing images** — marked complete (`FILE_STATUS`) with zero or below-category-norm `image_count`.
- **Cost-per-unit outliers** — z-score / MAD vs. peers within the same `WORK_CATEGORY` + state (`category_state_key`).
- **Sanction-to-completion gap too short** — `duration_days` below the category's low percentile (implausibly fast execution).

## 2. Isolation Forest + synthetic fraud injection

- scikit-learn `IsolationForest` over the engineered feature vector (normalized amount, cost-per-unit z-score, duration, image count, days-to-fiscal-year-end, rule-flag count), fit per `WORK_CATEGORY`. Catches multivariate outliers no single rule would trip.
- **Validation harness** — since there's no ground truth, `fraud_injection.py` clones real rows into shapes matching real CAG-documented patterns (structuring, phantom work, cross-year duplicate claim, tender-avoidance clustering, non-standard IDA, overpayment, image reuse, broken sequencing), tags them, mixes them into an evaluation copy, and measures per-pattern recall — the honest answer to "how do you know this catches anything without labels." See `memory/cag_fraud_patterns.md` for the sourced cases and parameters.

## 3. Computer vision

Runs on the "Works Completed" photos most competing teams won't have bothered to scrape.

**3a. Photo reuse (exact/near-duplicate)**
- Primary scan: **perceptual hash (pHash, DCT-based)** via `imagehash`, pairwise Hamming distance across every `WORK_ID`'s photos. Robust to recompression/resize/minor crop, no training, cheap enough for the full corpus.
- **Confirmation step: SIFT/ORB keypoint matching**, run only on the candidate pairs pHash already flagged (not the full corpus — O(n²) keypoint matching is too expensive at scale). Gives stronger, harder-to-dispute evidence for a specific pair before it reaches the dashboard.
- Rejected: exact hashing (MD5/SHA — breaks on any recompression), PDQ hash (built for adversarial evasion, overkill for lazy reuse rather than deliberate hash-dodging).

**3b. Near-duplicate scene (same physical site, different angle/photo)**
- **DINOv2 (self-supervised ViT) embeddings + cosine similarity clustering.** Revised from an initial ResNet50-ImageNet plan: classification-trained embeddings cluster by object *category* ("this is a road"), not *instance identity* ("this is the same stretch of road"), which is exactly the wrong bias for this task and would false-positive on any two similar-looking roads. DINOv2 is trained specifically for retrieval/copy-detection without labels — same deployment cost as ResNet50 (pretrained, load-and-embed, no fine-tuning), objectively the better tool for this job.

**3c. Category mismatch**
- **CLIP zero-shot** — image vs. `WORK_CATEGORY` text-prompt similarity. No training data needed, works directly against the free-text category names we already have.
- Caveat: CLIP was trained on general web images/captions, not government infrastructure photos, and `WORK_CATEGORY` itself is often coarse (`"Normal/Others"` in real sample rows) — treat this as a low-weight/advisory signal, spot-check against ~100–200 hand-labeled images before trusting it in the risk fusion.

**Noted but out of scope for v1:** EXIF forensics (camera/GPS/timestamp vs. claimed completion date — cheap, worth adding later), external reverse-image search against the open web (catches stock photos that never repeat within our own corpus, needs paid API calls), forgery/tamper detection (Error Level Analysis — meaningfully higher complexity/false-positive rate).

## 4. NLP on work descriptions

- Sentence-transformer embeddings (`all-MiniLM-L6-v2`) of `WORK_DESCRIPTION`, clustered **across fiscal years, not just within one** — catches the same asset claimed as "renovated" repeatedly.
- Cluster medians replace the flat category-mean cost baseline in the Phase 1 outlier rule with a semantically-grouped one.
- **GFR 2017, Rule 163 split-work detector** — confirmed rule text: a demand "should not be divided into small quantities to make piece-meal purchases to avoid the necessity of obtaining sanction of higher authority." Cluster near-identical descriptions from the same MP/IDA within a short date window; if individual amounts stay under the sanction threshold but the cluster's *sum* crosses it, flag as a citable Rule 163 violation.
- Regex quantity/unit extraction from descriptions ("500 mtr", "2 km") where present, for a true cost-per-unit-of-measurement instead of a per-category proxy.

## 5. Benford's Law

First- and second-digit distribution of `ACTUAL_AMOUNT` per IDA (`n ≥ 30` gate), chi-square test against Benford's expected curve. Agency-level flag (not per-work) — an agency whose amounts deviate sharply is a forensic-accounting signal that figures were fabricated/adjusted rather than reported from real invoices.

## 6. Government cost baselines

State PWD Schedule of Rates (SSR/DSR) + PMGSY per-km road costs — public but scattered across state portals as PDFs. Gives an absolute overpricing figure independent of peer comparison, upgrading the Phase 1 cost rule. Mostly data-collection effort, not modeling.

## 7. Satellite verification (conditional, human-in-the-loop)

Only for works whose constituency + description geocode to a confident coordinate — coverage will be thin, limited to well-known addresses. Sentinel-2 (Copernicus/Sentinel Hub) or ISRO Bhuvan before/after imagery, simple NDVI/pixel-diff change detection rather than a trained model. **Every result routes to a human-review queue, never an auto-verdict** — automated change detection is error-prone at this resolution, so its job is to surface "needs a human look," not decide.

## 8. CAG report mining

Ongoing, not a one-time step. State Audit Reports on cag.gov.in document real MPLADS/local-body irregularities every year (phantom works, fictitious measurement-book entries, tender-avoidance clustering, non-standard implementing agencies). Each confirmed pattern justifies a rule/feature *and* supplies realistic parameters for the Phase 2 synthetic-injection harness. Sourced cases so far live in `memory/cag_fraud_patterns.md`.

## 9. Risk fusion

Every track normalizes to 0–1. Weighted sum with a severity floor for near-certain patterns (phantom work, Rule 163 clusters, cross-constituency image reuse) so one strong signal isn't diluted by three quiet ones. Output per work: `{work_id, risk_score, severity, contributing_signals[], explanation}` — the record the problem statement's "risk-based alerts... decision-support dashboards" requirement actually needs.

---
*Build-order tiers: **core** (needed for a working demo) = Phases 0, 1, 2, 9. **Differentiator** (sets this apart) = Phase 3, 4, 5, 8. **Stretch** (pitch-worthy if time allows) = Phase 6, 7.*
