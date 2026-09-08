# Blueprint reference

Extracted from MPLADS_Implementation_Blueprint.docx. Source text is historical product guidance; measured corrections are in DATA_REALITY.md and DECISIONS.md.

MPLADS Anomaly & Fraud Intelligence Platform

Complete Implementation Blueprint

SIH 2026 — Problem Statement 26102

AI-powered detection of anomalies, fraud, and inefficiencies in MPLADS scheme implementation

Locked feature set — 8 detection engines + investigator dashboard, Internal Round MVP; Grand Finale and Future Scope layers designed but not built for the internal round.

Executive Summary

This blueprint implements the feature set locked on 2026-09-07: 8 detection/scoring engines feeding one fused risk score, an investigator dashboard (NAZAR District Command Centre), and a human-feedback calibration loop — built entirely on data actually scraped from mplads.mospi.gov.in (2,682 works across 49 constituencies and counting, plus real completed-work photos). No fraud labels exist anywhere for MPLADS, so the whole detection stack is unsupervised + rule-augmented, validated by a synthetic fraud-injection harness built from real CAG-audit case patterns rather than guessed heuristics.

Locked Feature Groups

🟢 Internal Round — build now

Feature

Tagline

PolicyCode MPLADS (Rule Engine)

Every MPLADS guideline, turned into a check the system runs automatically.

Isolation Forest + Fraud-Injection Validator

Finds the outlier no single rule was written to catch — and proves it by catching planted fraud first.

Photo-Reuse Engine (pHash + SIFT/ORB)

If a photo already exists somewhere else in MPLADS, we'll find it.

NLP Duplicate-Work Engine

Catches the same asset claimed twice, even in different words, a year apart.

Idle Sanctioned-Fund Detector

Money sanctioned, nothing built — flagged before it's forgotten.

Fund-Absorption Forecast

Warns which MPs and states are on track to leave their budget unused, months before the fiscal year closes.

Risk Fusion Engine

One number, fully explained — never a black-box score.

Human-Feedback Calibration Engine

Every dismissed alert makes the next one more accurate.

NAZAR District Command Centre

The single screen where every signal above becomes an officer's next action.

🔵 Grand Finale — design now, build after qualification

Feature

Tagline

Illegal State-Transition Detector

Flags a project that was completed before it was ever sanctioned.

Version-History Integrity Monitor

Notices when a record changes quietly, not just when it's wrong.

Source-Freshness Monitor

Tells the difference between "nothing happened" and "the data stopped arriving."

JanNirikshan

Lets the citizens who live next to the asset confirm it's actually there.

Outgoing-MP Closure Tracker

Keeps watch on unfinished works after the MP who sanctioned them has left office.

SatelliteScout

Checks from orbit whether a claimed structure was ever really built.

DINOv2 Near-Duplicate-Scene + CLIP Category-Mismatch

Recognizes the same physical site in a different photo, and catches a photo that doesn't match its claimed work type.

Benford's Law Agency Check

Digit patterns that don't occur in nature are a sign the numbers were written, not recorded.

Government Cost Baselines

Prices every work against the government's own official rate card, not just its peers.

Ongoing CAG Report Mining

Every year's audit findings become next year's detection rule.

🟣 Future Scope — production, pending government data access

Feature

Tagline

Sanction-Limit Breach Detector

Catches spending past what was ever approved — once a real sanction ceiling exists in the data.

eSAKSHI–PFMS Reconciliation

Matches what the portal claims was paid against what the treasury actually paid.

Underbid-Then-Escalate / Change-Order Creep Monitor

Catches the contract that was won cheap and quietly made expensive.

Shared Contact / Shared-Address Cluster Detector

Finds "different" vendors sharing the same phone number or office.

Cross-Scheme Duplicate Detector

Stops the same work being funded twice by two different schemes.

Coordinate-Jitter Detector

Catches an asset re-registered at a suspiciously nearby location to dodge a duplicate check.

Image-Manipulation Risk Detector

Looks for signs a completion photo was digitally altered.

Probabilistic Record-Linkage Engine

Follows one project across every government system that touched it.

Pass-Through Vendor Detector

Flags a vendor who receives funds and immediately moves most of them onward.

DocShield

Reads the invoice, the certificate, and the sanction letter, and checks they agree.

GrievanceFusion

Turns scattered citizen complaints into one case file per project.

Exception Control Tower / Deadline Exception Governor

One place where every deadline extension and cost revision needs a real sign-off.

Statutory Charge Checker

Verifies the tax and statutory deductions on an invoice actually match the rules.

BidRing Radar

Looks for the same small group of bidders winning contracts in a suspicious rotation.

GeM Award Mirror

Cross-checks MPLADS purchases against what they cost on the government's own marketplace.

ClauseGuard

Reads a contract before it's signed and flags the clause nobody noticed.

Guideline Change Impact Engine

When a rule changes, shows exactly which ongoing projects it now affects.

🔴 Removed

Feature

Why

One-Year Completion Breach

46% of current sample already exceeds 365 days on the fiscal-year proxy — unusable as a hard rule without exception-approval data we don't have.

Vendor / IDA-Concentration Monitor

Dropped at the user's explicit request.

EXIF Integrity Checker

Dead on real data — the portal strips all photo metadata before we ever see it, confirmed by inspecting real scraped photos.

RACI Responsibility Hub

A project-management tool, not a fraud or anomaly detector — doesn't trace back to a real MPLADS detection problem.

Part A — Final Product Architecture

Frontend

React 18 + TypeScript + Vite. Recharts/Nivo for charts, no mapping library in the MVP (no real coordinates yet — Leaflet reserved for the Grand Finale satellite/geocoding work).

Screens: Dashboard Home (risk-ranked work feed), Work Detail (risk card + evidence tabs: Rules / Anomaly / Photos / Duplicates), Alerts Queue, Investigation Form (Confirm/Dismiss/Needs-Investigation), Analytics (fund-utilization trend, agency drill-down), Data Health badge (Source-Freshness Monitor).

Role-scoped views: MP office (own constituency), State Nodal Authority (state-wide), District Authority (district-wide), Ministry (national) — same components, server-side jurisdiction filtering.

Backend

FastAPI (Python) — same language as the ML stack, so model/rule code and the API share types with no serialization boundary.

Pydantic schemas for request/response validation; RBAC middleware scopes every query by the caller's jurisdiction.

Background jobs: the pipeline run (ingest → features → engines → fusion) is a scheduled/manually-triggered batch job (APScheduler or a simple cron), not a message-queue system — unnecessary complexity at this data volume and demo scale.

JWT-based auth.

Data Layer

PostgreSQL — works, risk scores, alerts, investigations, users, audit log.

Filesystem storage for photos in the demo (S3-compatible object storage in production).

Parquet for the raw/consolidated pipeline output — already the pattern in pipeline/consolidate.py, kept as-is.

Deliberately NOT included in the MVP stack: PostGIS (no real coordinate data yet), Neo4j (no real vendor/graph data yet), a vector database (corpus small enough for in-memory cosine similarity — FAISS is a Future Scope item once national scale is real), Redis (no caching need at demo traffic). Each is called out at its Future Scope trigger condition rather than added speculatively.

Part B — Complete AI/ML Architecture

One full specification per locked internal-round engine. Every field below is answered against data we actually have — see the Data Reality Check already recorded in project memory.

Engine 1 — PolicyCode MPLADS (Rule Engine)

Every MPLADS guideline, turned into a check the system runs automatically.

Field

Detail

Objective

Encode MPLADS/GFR guideline clauses as deterministic, explainable checks that run on every work with zero training data.

Input

Single work record (WORK_CATEGORY, ACTUAL_AMOUNT, ACTUAL_END_DATE, LETTER_NO, FILE_STATUS, image_count, WORK_DESCRIPTION) plus its category/state peer group.

Required DB columns

work.actual_amount, work.actual_end_date, work.sanction_date_proxy, work.file_status, work.image_count, work.category_state_key, work.work_description

Data preparation

Parse LETTER_NO into mp_code/fy_start_year/fy_end_year via regex; compute sanction_date_proxy, duration_days, days_to_fy_end (already built in pipeline/consolidate.py).

Features engineered

Peer-group cost-per-unit z-score/MAD, days_to_fy_end, duration_days percentile within category_state_key, image_count vs category norm, GFR Rule 163 cluster sum.

Algorithm / model

Deterministic rules + peer-group statistics (z-score, MAD, percentile). No ML.

Why this algorithm

Government reviewers need a citable, reproducible reason ("Rule 163", "z-score 3.1"), not a black-box probability; needs zero labelled data.

Training process

None. Thresholds come from GFR/MPLADS guideline text; peer-group statistics recompute on every pipeline run.

Inference process

Evaluate every rule per work row on each batch pipeline run.

Threshold

Sub-10L structuring: amount in ₹9,00,000–9,99,999. Cost outlier: |z| > 2.5 or MAD > 3. Fast completion: duration_days below category 5th percentile.

Output

Boolean flag per rule + rule name + short explanation string, per work.

Confidence / risk score

Rule-trigger count feeds Risk Fusion as a 0–1 "compliance risk" signal, severity-floored for Rule-163 / missing-image hits.

Explainability (example)

"Flagged: amount ₹9,89,000 is within 1.1% of the ₹10,00,000 sanction-scrutiny threshold (Sub-10L structuring rule)."

False-positive handling

Peer-group thresholds validated against real state/category distributions before demo; officer can dismiss with a reason, which feeds the Calibration Engine.

Evaluation metric

Rule-trigger rate vs a manual audit sample; recall on synthetic fraud-injection cases shaped like each rule.

Retraining strategy

N/A (rules); peer-group statistics auto-recompute as more data arrives.

Demo implementation

Runs on the full scraped dataset; results cached in the risk_signal table.

Production implementation

Same logic, triggered on new-work ingestion from the real MPLADS/eSAKSHI feed instead of a batch scrape.



Engine 2 — Isolation Forest Anomaly Engine + Synthetic Fraud-Injection Validator

Finds the outlier no single rule was written to catch — and proves it by catching planted fraud first.

Field

Detail

Objective

Catch multivariate outliers no single rule would trip, and prove detection capability without real fraud labels.

Input

Engineered numeric feature vector per work.

Required DB columns

actual_amount (normalized), cost-per-unit z-score, duration_days, image_count, days_to_fy_end, rule_flag_count.

Data preparation

Per category_state_key normalization/scaling (RobustScaler — resists outlier-skewed means).

Features engineered

The 6 features above, one row per work.

Algorithm / model

scikit-learn IsolationForest, fit separately per WORK_CATEGORY (unit costs differ structurally by category).

Why this algorithm

Unsupervised, handles multivariate outliers, needs no labels, fast on this data volume, explainable via path-length anomaly score + SHAP.

Training process

Fit on the full feature matrix per category; contamination parameter set from an expected outlier rate (~2–5%), not tuned to any label.

Inference process

score_samples() per work → anomaly score; re-fit on each pipeline run as more data arrives.

Threshold

anomaly_score below the category-specific 5th percentile → flagged; severity bands from the score distribution.

Output

anomaly_score (continuous), is_anomaly (bool), top contributing features.

Confidence / risk score

Min-max normalized anomaly_score feeds Risk Fusion as "statistical anomaly risk" (0–1).

Explainability (example)

SHAP values per feature — "cost-per-unit z-score contributed +0.41 to this work's anomaly score, the largest single contributor."

False-positive handling

Contamination rate capped low; dismissed flags logged and their feature values checked against future contamination tuning.

Evaluation metric

Precision@K and recall on the synthetic fraud-injection harness — planted CAG-shaped cases with known ground truth. This is the project's actual answer to "how do you know it works without labels."

Retraining strategy

Re-fit on each full pipeline run (batch); no online learning in the MVP.

Demo implementation

Fit + score offline, cached in risk_signal; injection harness runs on a separate evaluation copy, never mixed into the real dashboard.

Production implementation

Scheduled retrain (e.g. monthly); contamination rate recalibrated from confirmed-alert history via the Human-Feedback Calibration Engine.



Engine 3 — Photo-Reuse Engine (pHash + SIFT/ORB) — "Project Doppelgänger: Image"

If a photo already exists somewhere else in MPLADS, we'll find it.

Field

Detail

Objective

Detect the same photograph reused across different works or claims — the real CAG-documented phantom/duplicate-claim pattern.

Input

Every downloaded completed-work photo (local_image_filenames).

Required DB columns

work_image.filename, work_image.work_id.

Data preparation

Load images, compute a perceptual hash per image.

Features engineered

64-bit pHash (DCT-based) per image.

Algorithm / model

imagehash pHash for a full-corpus pairwise Hamming-distance scan; OpenCV SIFT/ORB keypoint matching as a confirmation pass, run only on pHash-flagged candidate pairs.

Why this algorithm

pHash is robust to recompression/resize/minor crop and needs no training; SIFT/ORB gives stronger, harder-to-dispute evidence for a specific pair without the O(n²) cost of running it on the whole corpus.

Training process

None — both are deterministic classical CV, not trained models.

Inference process

Hash every new photo on ingestion; Hamming distance ≤ 8 → candidate pair → SIFT/ORB confirmation → match / no-match.

Threshold

Hamming distance ≤ 8 bits (near-duplicate), ≤ 2 bits (near-exact); SIFT inlier ratio ≥ 0.3 confirms.

Output

duplicate_pair rows: work_id_a, work_id_b, match_type, similarity_score, confirmed (bool).

Confidence / risk score

Confirmed cross-work-id pairs get a severity-floor "near-certain" contribution regardless of other signals.

Explainability (example)

Side-by-side photo pair with Hamming distance and SIFT keypoint overlay shown in the dashboard.

False-positive handling

Same-work multi-angle photos are expected and excluded (same work_id); only cross-work_id matches flagged; SIFT confirmation exists specifically to cut pHash false positives before they reach an officer.

Evaluation metric

Precision on synthetic image-reuse injection cases (a real photo cloned onto a different work_id) plus manual spot-check.

Retraining strategy

N/A (deterministic); hash index rebuilt as new photos ingest.

Demo implementation

Full photo corpus hashed offline, candidate pairs precomputed and cached.

Production implementation

Hash computed at photo-upload time in the real MPLADS asset-upload flow, checked against the full national index in real time.



Engine 4 — NLP Duplicate-Work Engine (cross-year) — "Project Doppelgänger: Text"

Catches the same asset claimed twice, even in different words, a year apart.

Field

Detail

Objective

Catch the same asset claimed again in a later fiscal year under different wording (real CAG case: a ₹45.2L renovation claimed twice).

Input

WORK_DESCRIPTION text, grouped per MP/constituency, across all fiscal years.

Required DB columns

work.work_description, work.mp_code, work.constituency_id, work.fy_start_year.

Data preparation

Lowercase/clean text, strip boilerplate phrasing.

Features engineered

Sentence-transformer embedding (all-MiniLM-L6-v2) per work_description.

Algorithm / model

Sentence-Transformer embeddings + cosine-similarity clustering (agglomerative, distance threshold), scoped per MP/constituency and across fiscal years, not just within one.

Why this algorithm

A pretrained embedding model needs no MPLADS-specific training data, captures paraphrase-level similarity beyond keyword match, and cross-year scoping is exactly what catches the documented fraud pattern.

Training process

None — pretrained model used purely for inference (embedding extraction).

Inference process

Embed all descriptions per MP/constituency, cluster by cosine distance, check cluster-sum amounts against the GFR Rule 163 sanction threshold.

Threshold

Cosine similarity ≥ 0.82 → same-cluster candidate; Rule 163 flag if a cluster's combined amount crosses ₹10L while individual works stay under it.

Output

duplicate_pair rows (match_type = text_semantic), cluster_id, similarity_score.

Confidence / risk score

Cross-year cluster hits get severity-floor treatment, same as confirmed photo matches.

Explainability (example)

"This work's description is 89% semantically similar to WORK_ID 121183, recommended in FY2023-24 for the same constituency."

False-positive handling

Same-year repeated standard-category descriptions (many similar road works in one constituency) are common and not inherently fraud; cross-year scoping plus amount/photo corroboration is required before "high" severity.

Evaluation metric

Recall on synthetic cross-year duplicate-claim injection cases; manual review of top clusters.

Retraining strategy

N/A (pretrained); re-embed and re-cluster on each pipeline run.

Demo implementation

Batch embedding + clustering over the full corpus, cached cluster table.

Production implementation

Incremental embedding on new-work ingestion, approximate nearest-neighbour index (e.g. FAISS) for national-scale lookup instead of full pairwise comparison.



Engine 5 — Idle Sanctioned-Fund Detector

Money sanctioned, nothing built — flagged before it's forgotten.

Field

Detail

Objective

Flag works where money is committed but execution shows no completion evidence for an unusually long time — the "inefficiency" half of the problem statement's title, distinct from fraud.

Input

Non-complete FILE_STATUS works, sanction_date_proxy.

Required DB columns

work.file_status, work.sanction_date_proxy, work.category_state_key.

Data preparation

Filter to FILE_STATUS != complete; compute days_since_sanction = today − sanction_date_proxy.

Features engineered

days_since_sanction, category peer-group percentile of days_since_sanction among still-incomplete works.

Algorithm / model

Statistical percentile threshold vs peer group (same family as Engine 1, kept separate because it targets incomplete, not completed, works).

Why this algorithm

Simple, explainable, no labels; the anomaly is a plain magnitude comparison, not a multivariate pattern, so IsolationForest would be overkill.

Training process

None.

Inference process

Recompute days_since_sanction and peer percentile on every pipeline run.

Threshold

days_since_sanction > category_state_key 90th percentile among incomplete works.

Output

idle_days, peer_percentile, flag.

Confidence / risk score

Feeds Risk Fusion as "inefficiency risk," weighted lower than fraud-pattern signals — it is explicitly not a fraud accusation.

Explainability (example)

"This work has been unexecuted for 412 days — longer than 90% of comparable Rural Roads works in Maharashtra."

False-positive handling

Legitimate long-gestation works exist (land acquisition, monsoon delays); labelled "needs inquiry," never "fraud," and the officer can attach a dismissal reason.

Evaluation metric

Correlation with officer-confirmed "stalled work" designations once feedback accumulates.

Retraining strategy

N/A.

Demo implementation

Computed at dashboard load from the cached work table.

Production implementation

Same computation, refreshed daily against a live FILE_STATUS feed.



Engine 6 — Fund-Absorption Forecast

Warns which MPs and states are on track to leave their budget unused, months before the fiscal year closes.

Field

Detail

Objective

Predict which MPs/states are unlikely to fully utilise their MPLADS entitlement in the current cycle — directly answers the "inefficiencies" half of the problem-statement title at a portfolio level.

Input

Per-MP/state completed-work amounts over time, the known public MPLADS per-MP entitlement.

Required DB columns

work.actual_amount, work.actual_end_date, work.mp_code, work.state_name.

Data preparation

Aggregate ACTUAL_AMOUNT by MP/state/quarter; utilization_rate = cumulative spend ÷ entitlement.

Features engineered

Quarterly utilization_rate time series per MP/state.

Algorithm / model

Simple trend extrapolation — moving average / linear regression on utilization_rate over available quarters. Not deep learning; too little history per MP to justify it.

Why this algorithm

Only a handful of data points exist per MP so far; a simple, auditable trend line is honest about the data volume and easy for a Ministry official to sanity-check.

Training process

Fit a per-MP (or per-state, when MP-level history is too thin) linear trend on observed quarterly utilization.

Inference process

Extrapolate to fiscal-year-end, compare to the 100% target.

Threshold

Projected year-end utilization < 60% → "at risk of underutilization" flag.

Output

projected_utilization_pct, trend_direction, flag.

Confidence / risk score

Feeds a state-level "inefficiency" dashboard KPI, not the per-work fraud risk score.

Explainability (example)

"At the current pace, this MP is projected to utilise 54% of their FY2025-26 entitlement — utilization has held at 49–58% for the last 3 quarters."

False-positive handling

Shown explicitly as a forecast with a confidence band, never as a certainty.

Evaluation metric

MAE against actual year-end utilization once a full fiscal year of data exists.

Retraining strategy

Recompute trend on each pipeline run as new quarters land.

Demo implementation

Computed from the currently scraped (partial-year) data, caveated in the UI as low-confidence given short history.

Production implementation

Same method, materially more accurate with multi-year history.



Engine 7 — Risk Fusion Engine

One number, fully explained — never a black-box score.

Field

Detail

Objective

Combine every engine's normalized signal into one explainable per-work risk score.

Input

risk_signal rows from Engines 1, 2, 3, 4, 5 for a given work_id.

Required DB columns

risk_signal.normalized_score, risk_signal.engine_name, risk_signal.detail_json.

Data preparation

Ensure every engine's output is normalized to 0–1 before fusion.

Features engineered

None beyond the signals themselves.

Algorithm / model

Weighted sum with a severity floor: Risk = Σ(weight_i × signal_i), overridden to ≥ 81 ("Critical") if any near-certain signal fires (confirmed cross-work photo match, confirmed Rule 163 cluster, confirmed cross-year duplicate claim).

Why this algorithm

One strong, near-certain signal shouldn't be diluted into "Moderate" by three quiet, unrelated signals — the severity floor matches investigator intuition; the weighted sum keeps the whole thing explainable, with no black-box aggregation model.

Training process

Initial weights are expert/rule-defined from the CAG-case severity ranking; not learned in the MVP.

Inference process

Recompute per work_id on every pipeline run.

Threshold

0–30 Low · 31–60 Moderate · 61–80 High · 81–100 Critical.

Output

risk_score (0–100), severity_band, contributing_signals[].

Confidence / risk score

Is itself the output.

Explainability (example)

The full risk-score card shown in Part J — reasons listed signal-by-signal.

False-positive handling

Every contributing signal is shown individually so an officer disputes a specific signal, not an opaque total.

Evaluation metric

Precision@Top-K alerts against a manual audit sample; investigator acceptance rate once feedback accumulates.

Retraining strategy

Weights recalibrated (not "trained") by the Human-Feedback Calibration Engine.

Demo implementation

Recomputed at each pipeline run, cached in risk_score table.

Production implementation

Same fusion logic, weights periodically recalibrated from accumulated investigator decisions.



Engine 8 — Human-Feedback Calibration Engine

Every dismissed alert makes the next one more accurate.

Field

Detail

Objective

Learn from confirmed/dismissed alerts to reduce recurring false positives, without treating every dismissal as ground truth.

Input

investigation.decision (confirmed / dismissed / needs_investigation) and the risk_signal contributions behind that alert.

Required DB columns

investigation.decision, investigation.reason_text, risk_signal.engine_name, risk_signal.normalized_score.

Data preparation

Join investigation outcomes back to the signals that produced the original alert.

Features engineered

Per-engine confirm-rate and dismiss-rate over a rolling window.

Algorithm / model

Simple weight recalibration — nudge each engine's Risk Fusion weight up or down proportional to its confirm-rate vs. a neutral baseline (bounded, not a full supervised classifier).

Why this algorithm

With confirms/dismissals realistically in the tens-to-hundreds range for a hackathon demo, a full supervised classifier would overfit; a bounded, explainable weight nudge is honest about data volume and directly answers the judge question "does it improve."

Training process

Recompute per-engine confirm-rate on a rolling window after each new decision; cap the adjustment per cycle (e.g. ±10%) so one batch of dismissals can't swing the system.

Inference process

Adjusted weights feed back into Engine 7 on the next fusion run.

Threshold

Minimum N = 10 decisions per engine before its weight is allowed to move from the expert-set default.

Output

Updated per-engine weight; confirm-rate / dismiss-rate dashboard panel.

Confidence / risk score

Not itself a score — a meta-layer over Engine 7.

Explainability (example)

"Missing-Images rule weight reduced from 0.20 to 0.17 after 14/40 recent flags were dismissed as 'photos pending upload, not phantom work.'"

False-positive handling

This is the false-positive-handling mechanism for the whole platform.

Evaluation metric

Trend of investigator dismiss-rate over time (should fall as calibration runs).

Retraining strategy

Rolling-window recompute, e.g. weekly or every N new decisions.

Demo implementation

Seeded with a small set of demo investigator decisions to show the weight-adjustment mechanic live.

Production implementation

Same mechanism at real investigator-decision volume, with a Ministry-level override on any weight change beyond the cap.



Part C — Complete Data Pipeline

Stage

What happens

Public Data

mplads.mospi.gov.in internal REST API, per-constituency scrape.

Ingestion

mplads_india_downloader.py — resumable via _progress.json, writes per-constituency works_with_images.csv + photos.

Schema Validation

New Schema/Value Validator pass: reject/flag negative amounts, malformed dates, unparseable LETTER_NO, impossible FY sequences.

Cleaning

Whitespace/tab stripping in LETTER_NO (real records contain stray whitespace mid-string), text normalization (upper-case, trim).

Normalization

state_norm / ida_norm / mp_norm / category_norm; category_state_key peer-group key.

Entity Resolution

MP/IDA/state name normalization (already handled); no cross-system linkage yet — only one source system is available.

Feature Engineering

sanction_date_proxy, duration_days, days_to_fy_end, has_images, plus the idle-fund and utilization aggregates added for Engines 5–6.

Detection Engines

Engines 1–5 run per work / per photo / per description cluster.

Risk Aggregation

Engine 7 — Risk Fusion.

Explainability

Each engine's detail_json rendered into an officer-readable reason string.

Alert Generation

risk_score ≥ 61 (High/Critical) creates an alert row.

Investigator Review

NAZAR Command Centre dashboard.

Feedback

investigation.decision written back.

Model/Rule Improvement

Engine 8 — Human-Feedback Calibration.

Part D — Database Design

Table

Primary Key

Key attributes / relationships

mp

mp_id

mp_name, mp_code, state_name, tenure_start, tenure_end (nullable — populated only when Outgoing-MP Closure Tracker, Grand Finale, is built)

constituency

constituency_id

constituency_name, state_name, FK mp_id → mp

implementing_agency

ida_id

ida_name, ida_type (district_collector/municipal/zilla_parishad/trust/cooperative/other — CAG case flag: non-standard IDA type), state_name

work

work_id

FK constituency_id, FK ida_id, work_category, activity_name, work_description, letter_no, mp_code, fy_start_year, fy_end_year, sanction_date_proxy, actual_end_date, actual_amount, file_status, average_rating, duration_days, days_to_fy_end, category_state_key, source_csv, ingested_at

work_image

image_id

FK work_id, filename, phash, exif_present (bool — always false on current real data)

duplicate_pair

pair_id

FK work_id_a, FK work_id_b, match_type (photo_exact/photo_near/text_semantic), similarity_score, confirmed (bool), status

risk_signal

signal_id

FK work_id, engine_name, raw_score, normalized_score, rule_triggered (bool), detail_json

risk_score

work_id (FK)

overall_score, severity_band, computed_at, contributing_signals_json, FK model_version_id

alert

alert_id

FK work_id, FK risk_score_id, severity, status (open/assigned/reviewed), created_at

investigation

investigation_id

FK alert_id, FK reviewer_user_id, decision (confirmed/dismissed/needs_investigation), reason_text, decided_at

feedback

feedback_id

FK investigation_id, engine_name, weight_adjustment_json, applied_at

model_version

model_version_id

engine_name, trained_at, params_json, eval_metrics_json

fraud_injection_case

case_id

pattern_name, FK source_work_id (nullable), FK injected_work_id, ground_truth_label, detected (bool), detected_by_engine, run_id — isolated to an evaluation schema, never joined into user-facing views

user_account

user_id

name, role (mp_office/state_nodal/district_authority/ministry/admin), jurisdiction_scope, email

audit_log

log_id

FK user_id, action, entity_type, entity_id, timestamp, ip_address

Part E — API Design

Method

Path

Purpose / Role / Backend component

GET

/works

List/filter/sort works by risk, category, state, MP — role-scoped by jurisdiction. → work + risk_score tables.

GET

/works/{id}

Full work record. All roles (jurisdiction-checked).

GET

/works/{id}/risk

Fused risk score + contributing signals with explanations. → Engine 7 output.

GET

/works/{id}/duplicates

Photo and text duplicate matches for this work. → Engines 3–4.

GET

/alerts

Open/assigned/reviewed alert queue, role-scoped. District Authority / Ministry.

GET

/alerts/{id}

Single alert detail with full evidence bundle.

POST

/investigations

Record Confirm/Dismiss/Needs-Investigation decision + reason. Reviewer roles. → feeds Engine 8.

POST

/feedback

Manual override on an engine's per-alert weight contribution (admin-only escape hatch).

GET

/analytics/fund-utilization

Per-MP/state utilization trend and forecast. → Engine 6.

GET

/analytics/agencies/{id}

Per-IDA work volume, amount distribution, flag rate.

GET

/dashboard/summary

NAZAR Command Centre landing-page aggregates.

GET

/health

Pipeline data-freshness status. → Source-Freshness Monitor (Grand Finale).

POST

/auth/login

JWT issuance.

Part F — Complete Software Stack

Category

Technology

Why we need it

Frontend

React + TypeScript + Vite

Component-driven dashboard with role-scoped views; Vite keeps the dev loop fast for a hackathon timeline.

Frontend

Recharts

Fund-utilization trend charts, risk-distribution histograms — no need for a heavier viz library at this scale.

Backend

FastAPI (Python)

Shares a language with the ML stack — no serialization boundary between model output and API response; auto-generates OpenAPI docs for the judge Q&A.

Backend

Pydantic

Request/response validation, doubles as the Schema/Value Validator's typed contract.

Database

PostgreSQL

Relational integrity for works/risk/alerts/investigations; mature, no exotic ops burden.

Database

SQLAlchemy / SQLModel + Alembic

ORM + versioned migrations.

Data Engineering

pandas, pyarrow (Parquet)

Already the pattern in pipeline/consolidate.py — kept, not replaced.

ML — Rules/Stats

NumPy / SciPy

z-score, MAD, percentile computations for Engines 1 and 5.

ML — Anomaly

scikit-learn (IsolationForest)

Engine 2 — unsupervised multivariate outlier detection.

ML — Explainability

SHAP

Per-feature contribution explanations for Engine 2's anomaly scores.

NLP

sentence-transformers (all-MiniLM-L6-v2)

Engine 4 — cross-year semantic duplicate clustering, pretrained, no fine-tuning needed.

Computer Vision

imagehash (pHash), OpenCV (SIFT/ORB)

Engine 3 — photo-reuse detection, both deterministic, no training.

Auth

JWT (python-jose), passlib

Stateless auth + password hashing.

Deployment

Docker Compose

One-command demo spin-up; Kubernetes is explicitly not used — unjustified complexity at this scale.

Testing

pytest, pytest-cov

Unit tests for rule thresholds and the fusion formula, which are exactly the pieces a judge may probe.

Version Control

Git / GitHub

Standard.

Monitoring

Structured logging + /health endpoint

Backs the Source-Freshness Monitor without a dedicated observability stack.

Part G — Project Folder Structure

mplads-ai/|-- frontend/                # React + TS dashboard|   |-- src/components/      # WorkCard, RiskBadge, EvidenceTabs, AlertsQueue|   |-- src/pages/           # Dashboard, WorkDetail, Alerts, Analytics|   `-- src/api/             # typed API client|-- backend/                 # FastAPI app|   |-- app/api/             # routers: works, alerts, investigations, analytics, auth|   |-- app/models/          # SQLAlchemy models (Part D)|   |-- app/schemas/         # Pydantic request/response schemas|   |-- app/services/        # risk fusion, calibration, jurisdiction scoping|   `-- app/core/            # config, auth, RBAC middleware|-- ml/|   |-- rules/               # Engine 1 + 5 (PolicyCode MPLADS, Idle-Fund)|   |-- anomaly/             # Engine 2 (IsolationForest)|   |-- nlp/                 # Engine 4 (duplicate-work clustering)|   |-- cv/                  # Engine 3 (pHash + SIFT/ORB)|   |-- forecast/            # Engine 6 (fund-absorption trend)|   |-- fusion/              # Engine 7|   |-- calibration/         # Engine 8|   `-- evaluation/          # fraud_injection.py + synthetic-case harness|-- pipelines/|   |-- consolidate.py       # already built — Phase 0 feature foundation|   `-- run_pipeline.py      # orchestrates ingestion -> engines -> fusion|-- data/                    # mplads_india/, mplads_images/ (gitignored, scrape output)|-- notebooks/               # EDA, threshold tuning, injection-harness validation|-- tests/|-- docs/|-- docker/`-- README.md

Part H — Model Development Plan

What actually gets trained vs. not

Component

Category

Detail

PolicyCode MPLADS (Engine 1)

Rule-based, no model

Thresholds sourced from GFR/MPLADS guideline text and recomputed peer statistics — never "trained."

Idle-Fund Detector (Engine 5)

Rule-based, no model

Percentile threshold vs peer group.

Isolation Forest (Engine 2)

Trained (fit), unsupervised

Fit per WORK_CATEGORY on engineered features; re-fit each pipeline run; no labels used.

Fund-Absorption Forecast (Engine 6)

Trained (fit), simple regression

Per-MP/state linear trend fit on observed quarterly utilization.

Sentence-Transformer (Engine 4)

Pretrained, inference-only

all-MiniLM-L6-v2 used purely to embed text; no fine-tuning.

pHash / SIFT / ORB (Engine 3)

Deterministic, not a model

Classical CV — hashing and keypoint matching, no learning involved.

Risk Fusion (Engine 7)

Rule-based (expert weights)

Not trained in the MVP; weights are CAG-severity-ranked defaults.

Calibration (Engine 8)

Lightweight statistical update

Bounded weight nudge from confirm/dismiss rates — deliberately not a supervised classifier, given realistic feedback volume.

Part I — Hybrid Detection Engine

Every work is scored by all five detection engines independently, then combined by the Risk Fusion Engine (Part B, Engine 7). Disagreement between detectors is resolved by the severity floor, not by averaging it away — a single near-certain signal always dominates.

Worked example

Engine

Signal on this work

Contribution

PolicyCode MPLADS

GFR Rule 163 split-work cluster confirmed

Near-certain — triggers severity floor

Isolation Forest

Moderate multivariate anomaly (score in the 8th percentile)

Weighted contribution, not decisive alone

Photo-Reuse

No match found

0 contribution

NLP Duplicate-Work

No cross-year cluster found

0 contribution

Idle-Fund

Not applicable (work is complete)

0 contribution

Result: Overall Risk = Critical (81+), driven by the Rule 163 severity floor even though only one of five engines fired strongly — matching how a human investigator would actually weigh one confirmed guideline violation against several quiet, inconclusive signals.

Part J — Explainable AI

What an officer sees on a flagged work's risk card, end to end:

Section

What appears

WHAT happened

Risk: 87/100 — Critical. "Road resurfacing work, Pune, flagged for cost outlier and unusually fast completion."

WHY it was flagged

Reason 1: Cost per unit is 2.6x the district median for this category. Reason 2: Completed in 41 days — faster than 95% of comparable works. Reason 3: Isolation Forest anomaly score in the top 4% for this category.

WHICH evidence

Linked photo thumbnails, the specific peer-group comparison chart, the exact rule text cited (Rule 163 / Sub-10L threshold, where relevant).

HOW unusual

Percentile position shown directly against the real peer distribution, not just a raw score.

WHICH related entities

Same implementing agency's other flagged works; any duplicate_pair matches (photo or text).

WHAT to investigate

A suggested action line generated from the specific signals that fired, e.g. "Verify invoiced material quantities against photographed scope before payment release."

Nothing on this card is a black-box probability — every number traces to a named rule, a named peer-group statistic, or a SHAP feature contribution the officer can click into.

Part K — Human-in-the-Loop

Alert  -> Officer Review (NAZAR Command Centre, Alerts Queue)    -> Evidence (risk card, Part J)      -> Decision: Confirm / Dismiss / Needs Investigation  (+ reason_text)        -> investigation row written          -> feedback row derived            -> Engine 8 recomputes per-engine confirm-rate              -> Engine 7 weights nudged (capped +/-10% per cycle)                -> next pipeline run uses updated weights

This closes the loop the master brief calls out explicitly: dismissals reduce a specific engine's influence over time, but no single batch of dismissals can swing the system past the cap, and a dismissal is never silently treated as proof of "not fraud" — it only ever adjusts a weight, never deletes or suppresses the underlying signal from the audit trail.

Part L — Security Architecture

Control

Approach

Authentication

JWT-based session tokens.

RBAC

Role + jurisdiction_scope on every user; backend middleware filters every query, not just the UI.

Encryption

TLS in transit; at-rest encryption on the PostgreSQL volume.

Secure APIs

Pydantic request validation on every endpoint; no raw SQL string interpolation (ORM-parameterized queries only).

Audit logs

audit_log table records every view of sensitive work detail and every investigation decision, with user, action, entity, timestamp.

Model access controls

Only the pipeline service account can trigger re-fit/re-score; API keys never exposed to the frontend.

Input validation

Pydantic schemas + the Schema/Value Validator pass at ingestion.

Rate limiting

Basic per-IP/per-token throttle at the API gateway layer.

Secrets management

.env for the demo; a proper secrets manager (e.g. Vault) is a Future Scope item for real government deployment.

Data minimization

No citizen PII is collected beyond what the public MPLADS portal itself already publishes.

On blockchain

Explicitly not used. Tamper-evidence for record history is handled by the audit_log table and the Version-History Integrity Monitor's content hashing (Grand Finale) — the same property blockchain would provide, without its latency, complexity, or governance overhead.

Part M — Implementation Roadmap

Stage

Deliverable

Depends on

Tier

1 — Data

Finish full-India scrape; run consolidate.py; add Schema/Value Validator pass

mplads_india_downloader.py (in progress)

Internal MVP

2 — Detection Engines

Engines 1–6 implemented and unit-tested against the consolidated parquet

Stage 1

Internal MVP

3 — Backend

FastAPI models/schemas/services; risk_signal + risk_score + alert tables populated by a pipeline run

Stage 2

Internal MVP

4 — Frontend

Dashboard Home, Work Detail with risk card, Alerts Queue

Stage 3 (API contract)

Internal MVP

5 — Integration

Engine 7 fusion wired end-to-end; Engine 8 calibration loop with seeded demo decisions

Stages 2–4

Internal MVP

6 — Explainability

Risk-card evidence tabs, SHAP contribution display, rule-citation strings

Stage 5

Internal MVP

7 — Demo

Scripted walkthrough (Part Q), seeded fraud-injection cases for the live "how do we know it works" moment

Stage 6

Internal MVP

Post-qualification

Illegal state-transition, Version-History Monitor, Source-Freshness Monitor, JanNirikshan, SatelliteScout, DINOv2/CLIP

Internal MVP complete

Grand Finale

Government deployment

PFMS/eSAKSHI integration, PostGIS, Neo4j vendor graphs, DocShield, GeM mirror

Real government data-sharing access

Production

Part N — Team Division

Track

Owns

Can run in parallel with

AI/ML — Detection

Engines 1, 2, 5 (rules + anomaly), fraud-injection harness

Frontend (Stage 4) once API contracts from Stage 3 are stubbed

AI/ML — NLP/CV

Engines 3, 4, 6, Part I fusion logic

Backend (Stage 3) once feature schemas from Stage 2 are fixed

Backend

FastAPI app, DB schema (Part D), API (Part E), RBAC

ML tracks, once the risk_signal schema is agreed

Frontend

Dashboard, risk card, alerts queue, analytics charts

Backend, against a mocked API until Stage 3 lands

Data Engineering

Scrape completion, consolidate.py extensions, Schema Validator

Everything — this gates Stage 2, so front-load it

Docs / Research

CAG case sourcing (ongoing), guideline citations for PolicyCode rules

All tracks, continuous

Presentation / Demo

Part Q narrative, live demo script, slide deck

Ramps up in the final week, pulls from every track's output

Part O — Demo Data Strategy

Category

What it is, in this project

Real Public Data

Every WORK_CATEGORY, ACTUAL_AMOUNT, WORK_DESCRIPTION, IDA_NAME, MP_NAME, and completed-work photo — scraped live from mplads.mospi.gov.in.

Derived Data

duration_days, days_to_fy_end, category_state_key, cost-per-unit z-scores, risk_score, all rule flags — computed from the real fields above, not fabricated.

Joined External Data

Grand Finale only: MP tenure-end dates (public parliamentary records) for the Outgoing-MP Closure Tracker; PWD Schedule-of-Rates for absolute cost baselines.

Synthetic Demonstration Data

fraud_injection_case rows only — cloned/modified real rows shaped like documented CAG patterns, explicitly tagged is_synthetic and isolated to an evaluation schema/copy. Never mixed into the live dashboard's default view; the demo exposes them only behind an explicit "Show validation cases" toggle, clearly labelled as synthetic on screen.

Part P — Evaluation Framework

Engine

Metric

Why it matters

Isolation Forest + injection harness

Precision@K, Recall on synthetic CAG-shaped cases

The honest, label-free answer to "does the anomaly model actually work."

Photo-Reuse (pHash+SIFT)

Precision on synthetic reuse cases + manual spot-check

False accusations of photo fraud are reputationally costly — precision matters more than recall here.

NLP Duplicate-Work

Recall on synthetic cross-year duplicate cases

Missing a real duplicate claim is the costlier error than an extra review.

Fund-Absorption Forecast

MAE vs. actual year-end utilization

Standard forecast-accuracy metric, reportable once a full fiscal year of data exists.

Risk Fusion

Precision@Top-K alerts, false-positive rate

What determines whether officers keep trusting the queue.

Human-Feedback Calibration

Investigator dismiss-rate trend over time

Direct evidence the system improves rather than statically flagging the same false positives forever.

Part Q — SIH Winning Narrative

One-line product description

An explainable, hybrid AI platform that turns MPLADS' own public data into risk-ranked, evidence-backed alerts for fraud, duplication, and stalled fund utilization.

30-second pitch

MPLADS moves thousands of crores through thousands of works every year, and today the only way to catch a phantom road or a reused photo is a manual audit, months after the money is gone. We built a platform that reads the same public MPLADS data every citizen can see, and automatically flags cost outliers, duplicate-work claims, and reused photographs — with a plain-language reason for every flag, not a black-box score.

60-second technical pitch

There are no fraud labels anywhere in MPLADS data, so we didn't build a classifier — we built a hybrid stack: guideline-encoded rules for citable compliance violations, an Isolation Forest for multivariate cost/timing outliers, perceptual hashing plus SIFT keypoint matching to catch reused completion photos, and cross-year sentence-embedding clustering to catch the same asset claimed twice. Every signal is fused into one risk score with a severity floor so one confirmed violation isn't diluted by noise. And because there's no ground truth, we validate the whole pipeline by injecting synthetic cases shaped exactly like real CAG-audit findings and measuring what we actually catch — which is also how the system keeps improving, through a human-feedback loop that recalibrates engine weights from officers' own confirm/dismiss decisions.

Why existing monitoring is insufficient

MPLADS' own public portal exposes the data but does no analysis on it; officer-level review is manual, un-scaled, and has no way to catch cross-year or cross-photo patterns a human reviewing one file at a time would never notice.

Why our hybrid approach is better

No single technique — rules alone, or ML alone — covers both the guideline-citable violations Ministry officials need and the subtle multivariate/visual patterns rules can't express. Combining them, with an explicit severity floor, gets both without pretending either one alone is sufficient.

Real-world impact

Turns a reactive, audit-cycle-later process into a running early-warning system for the exact fraud patterns CAG has already documented at scale — phantom works, fictitious measurement-book entries, duplicate claims, tender-avoidance clustering.

Government scalability

Built against the real national MPLADS data shape from day one (543 constituencies), with explicit, labelled integration points (PFMS, eSAKSHI, GeM) for the data we don't have yet rather than fabricated features pretending we do.

What we can actually demonstrate

A live risk-ranked dashboard over real scraped works and real photos; a confirmed photo-reuse or cross-year-duplicate pair surfaced from the real corpus; the fraud-injection harness run live, showing the model catch planted CAG-shaped cases in real time; an officer dismissing a flag and the calibration engine visibly adjusting a weight.