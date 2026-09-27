# NAZAR — Project Features

_As of 2026-09-22_

NAZAR is an evidence-led review tool for MPLADS (MP Local Area Development Scheme) works — it scores works for risk/inefficiency, verifies photo evidence, and routes flagged items through a multi-persona reviewer workflow.

## Data & Scoring

**Fraud risk score** (`scripts/pipeline.py`): 8 weighted signals per work, summed and capped at 0–100, banded Low/Moderate/High/Critical.

| Signal | Weight | What it catches |
| --- | --- | --- |
| `photo_identical` | 25 | Byte-identical completion photos reused across different works (Tier 1) |
| `text_exact` | 20 | Identical normalized work description for the same MP across fiscal years |
| `cost_peer` | 15 | Amount is a statistical outlier (z > 2.5) vs. peers in the same activity × state group |
| `anomaly` | 15 | IsolationForest multivariate outlier on amount, cost/unit, and photo count |
| `photo_similar` | 10 | Near-duplicate photos (perceptual hash), counted only if ORB + RANSAC keypoint-confirms the match (≥100 good matches, ≥20% inlier ratio) — cuts false positives from similar-looking but different scans |
| `missing_evidence` | 5 | Zero completion photos attached |
| `text_similar` | 5 | >90% description similarity for the same MP across fiscal years |
| `entitlement_pace` | 5 | MP's total sanctioned amount in a fiscal year exceeds the ₹5 crore/year nominal MPLADS entitlement (advisory — entitlement is non-lapsable, so this alone isn't proof) |

Severity is forced to **Critical** if `photo_identical` or `text_exact` fires, or score > 80 — regardless of the weighted total.

A `round_amount` heuristic ("amount suspiciously close to a round lakh figure") was removed — no statistical or sourced regulatory basis, never validated, and round sanctioned amounts are routine in government budgeting. See `docs/DECISIONS.md`.

- **Data ingest** (`pipelines/ingest.py`) — joins completed + sanctioned records into `data/canonical/works.csv`
- **Duplicate detection** — byte-identical and perceptual-hash reused photos, plus duplicated work descriptions across fiscal years
- **Evaluation harness** (`scripts/evaluate.py`) — synthetic fraud-injection tests measuring detector sensitivity
- Data prep/QA utilities: `prepare_deploy_data.py`, `profile_data.py`, `check_prototype.py`
- Anomaly modeling via scikit-learn IsolationForest; pandas/NumPy/SciPy for stats

## Photo / Evidence Verification

- **ORB keypoint confirmation** (OpenCV) — secondary check on Tier-2 perceptual-hash photo matches to reduce false positives
- Image caching pipeline (`data/images.json`, `data/image_cache/`)

## Inefficiency Signals (separate engine, separate population)

Runs against the full sanctioned universe (including 6,000+ sanctioned-but-not-completed works the fraud engine never sees), sourced to MPLADS Guidelines 2023 — not heuristics.

| Signal | Threshold | What it catches |
| --- | --- | --- |
| `idle_flag` | Days since sanction, z > 2.5 vs. activity × state peers | Sanctioned but never completed, held open unusually long vs. similar works |
| `late_flag` | Sanction lag > 75 days | Sanctioned more than 75 days after the recommendation was received (sourced MPLADS deadline) |

Kept entirely separate from the fraud `risk_score`/`severity_band` — different weighting, different language, no overlap.

## Reviewer Workflow (Backend — `backend/main.py`, FastAPI)

- HMAC-signed bearer tokens carrying `{persona, jurisdiction}`; server-side jurisdiction filtering on every query
- Four personas: MP Office, District Authority, State Nodal Authority, Ministry
- Reviewer **Confirm / Dismiss** decisions with required reason, stored in SQLite or optional Postgres (Neon)
- Ministry confirmation promotes a work to "Confirmed," visible across every jurisdiction that contains it
- REST endpoints: auth, works, signals, duplicates, confirmed works, inefficiency, investigations, summary, evaluation

## Frontend Views (`frontend/src/App.tsx` — React 19 + TS + Vite + Recharts)

- Login → Overview: review queue + work-detail modal
- Inefficiency tab: idle-funds/late-sanction queue, stats, filterable and paginated table
- Confirmed tab: Ministry-confirmed works scoped to jurisdiction
- **Related-entities view** — repeat-pattern surfacing by MP and by implementing agency
- Severity badges and "computational signal, not proof" disclaimers on flagged evidence

## Infra / Deployment

- `render.yaml` — backend on Render; frontend prepped for Vercel, with single-origin fallback via FastAPI serving `frontend/dist`
- `docker/` — containerization support
- `.env.example` — config template (DB URL, secrets)
- Optional Postgres/Neon via `NAZAR_DATABASE_URL`; SQLite by default

## Other

- State-specific MPLADS scraper scripts (India-wide + Telangana)
- `notebooks/`, `eval/`, `ml/`, `astra/` — exploration and evaluation directories
- `tests/` + pytest suite
- `docs/` — documentation index
