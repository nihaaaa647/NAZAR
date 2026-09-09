# How NAZAR scores a work — rules, statistics, computer vision, and text matching

This document explains, in plain language, what the scoring pipeline
(`scripts/pipeline.py`) actually does today. It is written against the code that
runs, not the aspirational design in `docs/blueprint.md`. Where the blueprint
promises something that is not built (SIFT/ORB, sentence-transformer embeddings,
a trained forecast model), that is called out explicitly.

Everything here runs **once, as a batch**, over the local corpus
(5,611 completed works, 5 states, 79 constituencies). There is no training on
fraud labels because no fraud labels exist for MPLADS anywhere. Every output is a
*computational signal that needs human review* — never a finding.

---

## 0. The shape of the data

Each row is one completed MPLADS work. The fields the scorer leans on:

| Field | Meaning | Notes |
|---|---|---|
| `ACTUAL_AMOUNT` | rupee value of the work | No quantity/unit field exists, so "cost per unit" is the **same number** as amount — disclosed, not hidden. |
| `WORK_DESCRIPTION` | free-text description | Used for the text-duplicate check. |
| `ACTIVITY_NAME` | work type, e.g. "roads", "street lights" | Prefixed with a sanction code that is stripped to get `activity_norm`. |
| `STATE_NAME`, `MP_NAME`, `CONSTITUENCY` | jurisdiction | `MP_NAME` scopes the text check; state scopes the peer group. |
| `LETTER_NO` | sanction letter, e.g. `LN/MP18129/2024-2025/3` | Regex-parsed into MP code + fiscal-year start/end. Stray tabs/spaces are cleaned first. |
| `ACTUAL_END_DATE` | completion date | Parsed as `%d-%b-%Y`. |
| `image_count` | attachments listed in the source CSV | "Listed", not "successfully downloaded" — the two differ. |
| `local_image_filenames` | `;`-separated attachment files | PDFs and JPEGs on disk. |

Derived once at load: `activity_norm`, `description_norm` (lower-cased,
whitespace collapsed), `fy_start_year`/`fy_end_year` from the letter number.

---

## 1. The peer group — "compared to what?"

Almost every statistic is relative. Before any rule runs, each work is assigned a
**peer group** using a fallback ladder (`score_works` in `pipeline.py`):

1. **`activity + " | " + state`** — e.g. "ROADS | BIHAR" — *if* that combination
   has **≥ 10 works**. This is the preferred key: unit costs genuinely vary by
   region and work type.
2. Otherwise **`activity` alone** (all states), if that has ≥ 10 works.
3. Otherwise **"Whole corpus"** — everyone.

The minimum of 10 keeps the median and spread statistically meaningful. In this
corpus the resulting peer groups mostly land at or above that floor, with the
whole-corpus bucket catching the long tail of rare activities.

For each peer group the pipeline computes:

- **median amount** — the typical value, robust to a few huge outliers (unlike a
  mean).
- **MAD** (median absolute deviation) — the median of `|amount − median|`. A
  robust substitute for standard deviation.

---

## 2. Rule / statistics engine

Three deterministic rules plus one statistical-outlier model. Each produces
`{flag, raw, score, reason}` where `score` is 0–1 and feeds the fused risk score.

### 2.1 Cost-vs-peers (`cost_rule`) — a robust z-score

**Concept.** A z-score answers "how many spreads from typical is this?"
Ordinary z-score is `(value − mean) / std_dev`. NAZAR uses the **robust** form so
that a handful of extreme works don't distort the yardstick:

```
scale   = 1.4826 × MAD          (the 1.4826 makes MAD comparable to a std-dev
                                 for normal-ish data)
amount_z = (amount − median) / scale
```

If a peer group has **zero MAD** (every work billed exactly the same, which
happens with round sanctioned amounts), `scale` falls back to 10 % of the median
(floor 1) so we never divide by zero or call everything infinitely anomalous.

**Flag:** `|amount_z| > 2.5`.
**Score:** `min(|amount_z| / 6, 1)` — grows with deviation, capped at 1 (reached
at z = 6).
**Reason string:** *"Amount ₹X is unusually high/low compared to N peers in
&lt;group&gt;."*

`cost_per_unit_z` is set equal to `amount_z` because there is no quantity field —
this is stated in the output, not disguised as a second independent signal.

### 2.2 Missing completion evidence (`missing_rule`)

**Flag:** `image_count == 0` (no attachments listed in the source data).
**Score:** 1.0 if flagged, else 0.
**Reason:** advisory only — it notes that *listed* attachments are missing, and
that download failures are tracked separately (~35.6 % of works have no
source-listed evidence in this corpus, so this is a weak cue by itself).

### 2.3 Suspicious round amount (`round_rule`)

**Concept.** Genuine cost figures rarely land exactly on ₹1,00,000 boundaries;
numbers that were *written* rather than *measured* often do.

```
distance = |amount / 100000 − round(amount / 100000)|
flag     = amount ≥ 100000 AND distance ≤ 0.01
```

i.e. within 1 % of an exact lakh multiple. **Score:** 1.0 / 0.
The reason string explicitly says this is a heuristic with **no verified legal
threshold** — there is no sourced ₹10 L scrutiny rule in the data, so NAZAR does
not claim one.

### 2.4 Isolation Forest — multivariate outlier (`sklearn.ensemble.IsolationForest`)

**Concept.** The rules above each look at one number. An Isolation Forest looks
at several at once and finds rows that are *jointly* unusual — a combination that
no single rule describes. It builds many random trees that repeatedly split the
data on random features at random thresholds; points that get "isolated" in very
few splits are outliers (short average path length → high anomaly score).

**Inputs (3 features per work):** `amount_z`, `cost_per_unit_z` (= `amount_z`),
`image_count`. These are passed through `RobustScaler` (centres on the median,
scales by the interquartile range) so the forest isn't dominated by raw scale.

**Parameters:** `contamination = 0.05` (expect ~5 % outliers — an assumption, not
a tuned value), `n_estimators = 150`, `random_state = 42` for reproducibility.
Fit on the whole corpus at once (the blueprint's "fit per category" is not
implemented).

**Outputs:**
- `anomaly_raw = −decision_function(x)` — higher means more anomalous.
- `anomaly_score` — the percentile rank of `anomaly_raw` (0–1), so it reads as
  "more unusual than X % of works".
- **Flag:** `anomaly_raw > 0`, i.e. the forest's own boundary classifies the row
  as an outlier.

**Explanation.** For the reason string the pipeline separately computes, within
the peer group, a plain per-feature z-score for the work and names the feature
with the largest absolute deviation: *"…a statistical outlier compared to peers,
largely due to its amount."* (This is a lightweight stand-in for SHAP, which the
blueprint mentions but which is not a dependency.)

---

## 3. Computer-vision engine — photo reuse

Goal: find the same photograph attached to two different works. Two tiers, both
**classical / deterministic** — no trained model, no SIFT/ORB (the blueprint's
keypoint-confirmation pass is not implemented).

### 3.1 Getting an image out of the attachment

Attachments are mostly scanned **PDFs**. `extract_images`:

1. Resolves each filename under its constituency folder, rejecting any path that
   escapes that folder (path-traversal guard).
2. If the file starts with `%PDF`, it carves the embedded JPEG by byte-scanning
   from the first `FF D8 FF` (JPEG start-of-image) to the last `FF D9`
   (end-of-image). If a file has no such marker it is logged as an extraction
   failure (266 such failures in this corpus).
3. Opens the JPEG with Pillow, records `width`, `height`, an **MD5** of the exact
   bytes, and a **perceptual hash** (below).
4. Caches everything in `data/image_cache/` keyed by file size + mtime, so
   re-runs are fast.

### 3.2 The perceptual hash (`phash`)

**Concept.** An MD5 changes completely if a single byte changes. A *perceptual*
hash stays almost the same when an image is re-saved, resized, or lightly
cropped — it captures what the image *looks like*, not its bytes.

NAZAR's implementation (DCT-based, the standard "pHash"):

1. Convert to greyscale, resize to **32×32** (Lanczos).
2. Take the **2-D discrete cosine transform** (`scipy.fftpack.dct`) — this moves
   the image into frequency space; the top-left corner holds the coarse
   structure, which is what survives compression and scaling.
3. Keep the top-left **8×8** block, drop the very first coefficient (the overall
   brightness / DC term).
4. Compare each remaining value to the **median** of that block → 1 bit each →
   pack into a **64-bit hash** (hex string).

Two images are compared by **Hamming distance**: the number of bit positions
that differ. 0 = perceptually identical; small = very similar; large = unrelated.

### 3.3 The dimension gate (`MIN_IMAGE_DIM = 150`)

Scanner apps ("Scanned with OKEN Scanner", CamScanner) stamp a **thin footer
strip** that is byte-identical across totally unrelated works. Without a filter
those strips dominate the results as fake "reused image" evidence. So any image
whose **smaller side is < 150 px** is treated as a scanner artifact: logged, not
used as evidence. (`data/reports/pipeline.json` records 15 such watermark groups
suppressed in the last run.)

### 3.4 Tier 1 — `photo_identical` (byte-identical)

Group images by **MD5**. If one MD5 appears under **two or more different
`work_id`s** *and* the image clears the dimension gate → emit a pair per
work-id combination, tier `photo_identical`.

Last run: **64 cross-work groups**. This proves *the extracted bytes are equal* —
not that a claim is improper. Legitimately shared documents (a common measurement
book, an estimate, a receipt) also match, and the reason string says so.

### 3.5 Tier 2 — `photo_similar` (perceptually close)

1. Take one representative per MD5 group, keep those past the dimension gate
   (**2,830 images** last run).
2. Compute the Hamming distance for **every pair**, building a histogram of the
   whole distance distribution.
3. **Adaptive threshold:** `min(6, max(2, first_percentile_distance // 2))`.
   In words: half of the 1st-percentile Hamming distance, clamped to the range
   2–6. Last run this resolved to **6**. The pipeline states plainly this is a
   heuristic low-tail cutoff, *not* proof of reuse.
4. Keep candidate pairs with distance ≤ threshold.
5. **Union-Find clustering:** connect all candidate pairs into components.
6. **Common-template suppression:** any component spanning **more than 6 works**
   is a shared blank form layout, not reuse of a specific photo — the whole
   component is dropped (40 components suppressed last run).
7. Remaining **cross-`work_id`** pairs are emitted as `photo_similar` with their
   Hamming distance. Last run: **161,121 raw candidate pairs → 3,882 after the
   dimension gate → 234 after all gates.**

Manual spot-checks (`reports/visual_qa/`, `reports/verification.md`) found the
tier-2 pairs were real completion/inspection reports on **matching form layouts**
— sometimes with *different* text filled in. Visual similarity of a form is not
proof of reused content; that is why this tier carries low weight and says
"inspect manually".

---

## 4. Text engine — duplicate-work claims (`text_duplicates`)

Goal: catch the same asset claimed again in a **later fiscal year** under
slightly different wording.

> **What this is not:** despite the blueprint, there are **no sentence-transformer
> embeddings and no semantic similarity model**. `sentence-transformers` is not
> installed. This engine is exact + fuzzy **string** matching. It is honest about
> paraphrase: it will miss a genuine reword that shares few characters.

Procedure:

1. Group works by **`MP_NAME`** (a duplicate claim is by the same MP).
2. Within each MP, bucket rows by **`description_norm`** — the description
   lower-cased, trimmed, and with internal whitespace collapsed to single
   spaces. Only rows with a non-empty description and a known fiscal year.
3. **`text_exact`:** two rows in the *same* `description_norm` bucket, with
   **different `fy_start_year`** and different `WORK_ID` → emit a pair,
   `similarity = 1.0`.
4. **`text_similar`:** for two *different* description buckets that between them
   span more than one fiscal year, run Python's
   **`difflib.SequenceMatcher`** — a longest-matching-contiguous-subsequence
   ratio in [0, 1]. Cheap pre-filters (`real_quick_ratio`, `quick_ratio`) reject
   obvious non-matches first; then if the true `ratio > 0.90`, emit pairs across
   the fiscal-year boundary with `similarity = ratio`.

Last run: **767 exact cross-year pairs, 980 near pairs.** Many similar road-work
descriptions in one constituency are normal, so — like the photo tiers — this is
a lead, not a verdict. Same-year repeats are deliberately excluded.

---

## 5. Risk fusion — one number, fully itemised

`score_works` collects every signal for a work into a dict and computes a
**weighted sum** (no black-box model):

| Signal | Weight | What earns full score |
|---|---:|---|
| `photo_identical` | 25 | ≥ 1 byte-identical cross-work image |
| `text_exact` | 20 | ≥ 1 identical cross-year description |
| `cost_peer` | 15 | scaled by `min(\|z\|/6, 1)` |
| `anomaly` (Isolation Forest) | 15 | forest flags the row (`score` = percentile) |
| `photo_similar` | 10 | ≥ 1 perceptually-close cross-work image |
| `missing_evidence` | 5 | `image_count == 0` |
| `round_amount` | 5 | within 1 % of a lakh multiple, ≥ ₹1 L |
| `text_similar` | 5 | ≥ 1 description > 90 % similar cross-year |

```
risk_score = Σ (weight × score)          → 0–100 (weights sum to 100)
```

Evidence signals (identical bytes / identical text) dominate on purpose;
missing-evidence and round-amount are deliberately weak advisory cues.

### Severity band — with a "severity floor"

```
Critical  if photo_identical flag OR text_exact flag OR risk_score > 80
High      if risk_score > 60
Moderate  if risk_score > 30
Low       otherwise
```

The **floor** is the key design choice: one confirmed byte-identical photo or one
identical cross-year description forces **Critical** even if the arithmetic total
is modest. This matches how a reviewer actually weighs one hard match against
several vague signals — and it is why some Critical works show a *lower* weighted
score than some High works (noted in `reports/verification.md`).

Last run severity distribution: **484 Critical · 0 High · 421 Moderate ·
4,706 Low**.

Every work carries its full `signals_json` (each signal's flag, raw value, 0–1
score, and human-readable reason) so the dashboard can show the itemised "why",
never just a total.

---

## 6. Validation without labels — the injection harness (`scripts/evaluate.py`)

Because there is no ground truth, the pipeline is tested by **planting synthetic
cases shaped like known fraud patterns** and checking the *same detector
functions* catch them. Injected rows are isolated under `reports/synthetic/` and
**never enter the shipping dataset**.

Three patterns, 10 trials each, seed 42:

| Pattern | How it's built | Detector under test | Last result |
|---|---|---|---|
| Image reuse | copy a real work's photo onto a new `SYNTH-IMAGE-n` row | `photo_duplicates` tier 1 | **10/10** |
| Cross-year duplicate claim | copy a real row, bump `fy_start_year` +1, jitter the amount ±5–10 % | `text_duplicates` exact | **10/10** |
| High amount, no evidence | real row, amount = 5× peer max (min ₹10 L), `image_count = 0` | missing-evidence advisory / Isolation Forest | missing **10/10**; Isolation Forest **7/10** |

**Honest limitations** (stated in the report itself): this measures
*sensitivity to constructed cases only* — not real-world precision, not a fraud
finding, not pHash accuracy. Missing-evidence recall is 100 % by construction
(the injector sets `image_count = 0`). The Isolation Forest is re-fit on the
augmented copy, and catching 7/10 deliberately-extreme outliers shows the model
is doing roughly what's expected, no more.

---

## 7. What is deliberately NOT built (blueprint vs. reality)

| Blueprint claim | Reality in the code |
|---|---|
| SIFT/ORB keypoint confirmation of photo matches | Not implemented — pHash + Hamming only. |
| Sentence-transformer (`all-MiniLM-L6-v2`) semantic text clustering | Not implemented — exact + `difflib` fuzzy string matching. |
| Isolation Forest fit per work category | Fit once on the whole corpus. |
| SHAP feature attributions | Approximated by a per-feature peer z-score. |
| Fund-absorption forecast (Engine 6), idle-fund detector (Engine 5) | Not in `pipeline.py`. |
| Human-feedback calibration loop adjusting weights (Engine 8) | Decisions are stored (`investigations.sqlite3`); weights are static. |
| GFR Rule 163 / ₹10 L legal thresholds | No legal rule is sourced or implemented; the round-amount rule is explicitly a heuristic. |
| PostgreSQL, JWT, RBAC middleware | SQLite; HMAC-signed bearer token; jurisdiction filter applied server-side per request. |

The guiding principle across the whole prototype: **surface a signal, cite the
exact reason, and leave the judgement to a human.** Nothing here is a fraud
determination.
