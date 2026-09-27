# Satellite verification + vendor network module — implementation plan

Status: **Built and verified end-to-end on real data as of 2026-09-25**
(§1-§8: harvest, imagery, change detection, overlay, vendor network,
fusion, evaluation, and a live backend + frontend Satellite tab with
real before/after imagery rendering). See
`docs/SATELLITE_MODULE_DATA_REALITY.md` for measured results and
`docs/DECISIONS.md` for the source substitutions (OSM + public AWS Earth
Search in place of the Bhuvan/PMGSY/Copernicus sources originally named
below, both of which turned out to be credential-gated). §6's fusion
scores this module's own synthetic population
(`ml/fusion/satellite_fusion.py`), not the real corpus's `score_works` -
see that module's docstring for why. Sample scale is qualitative (10
assets with real imagery, 151 total synthetic works), not corpus-wide -
see the data-reality doc for exactly what was and wasn't validated.
Extends the thin/stretch satellite item in
`feature_plan.md` (§7) into a demoable module with real coordinate/imagery
grounding, plus a new vendor/payment fraud track. Written before any code
exists so scope and honesty framing are fixed up front, the same way
`docs/DATA_REALITY.md` and `docs/STATE.md` fix measured/unmeasured claims
before engines get built on top of them.

## 0. What this module is and is not

- It is a demonstration that the risk-fusion architecture (`pipeline.py:
  score_works`) can absorb a geospatial signal and a procurement-network
  signal, validated against **real satellite imagery and real geotagged
  assets from a public non-MPLADS scheme**, with a synthetic MPLADS
  paperwork layer fabricated on top.
- It is **not** a claim that any specific MP, IDA, or vendor in the demo
  data is real, and not a claim that real MPLADS geotags were used. The
  pitch and any on-screen labelling must say this plainly — do not let a
  judge infer real MPLADS records are involved.
- Like every other engine in this project: computational signal, never a
  finding. No fraud labels exist for this data any more than for the rest
  of MPLADS, so validation is again synthetic-injection-based, not
  ground-truth classification.

## 1. Coordinate + imagery sourcing (new: `pipeline/harvest_geotags.py`)

Source candidates, in order of expected accessibility (verify each with a
short spike before committing build time — do not assume portal access
works until a sample pull succeeds):

1. **Bhuvan NREGA** geotagged MGNREGA assets (ISRO) — closest analog to
   MPLADS works (roads, ponds, check-dams, community buildings), ships with
   before/after-style photo evidence and coordinates.
2. **PMGSY road network** (OMMAS / PMGSY-GRRIS) — real road coordinates and
   construction status; a subset was reportedly released as open data
   (~7 lakh geo-tagged facilities) — check whether that extract is still
   downloadable before relying on the live portal.
3. Fallback / supplement: PMAY-G geotagged housing, Jal Jeevan Mission
   dashboards — same pattern, different work categories, useful if #1/#2
   don't yield enough volume or category variety.

Output of this step: `data/geotags/sourced_assets.csv` with, at minimum,
`asset_id, lat, lon, source_scheme, category, photo_url_or_path,
observed_date`. Record `source_scheme` explicitly — this field is what
keeps the "borrowed ground truth, fabricated paperwork" framing honest and
auditable later.

**Open risk, flag before building further:** these are portal UIs, not
clean APIs. Time-box a 20–30 minute spike per source to confirm bulk pull
is realistic; if both stall, this module's coordinate count may end up
small enough that it's a qualitative demo (dozens of sites), not a
corpus-scale one — decide the target count from what's actually pullable,
not the other way around.

## 2. Real imagery retrieval (new: `pipeline/fetch_satellite_pairs.py`)

- Sentinel-2 (Copernicus Open Access Hub / Sentinel Hub) or ISRO Bhuvan
  imagery for each sourced coordinate, two dates spanning a plausible
  construction window (use the source scheme's own `observed_date` as one
  anchor where available).
- Cache raw tiles under `data/satellite_cache/` keyed by
  `asset_id_t1.tif` / `asset_id_t2.tif` — same caching discipline as the
  existing `data/image_cache/`.
- Resolution/coverage caveats go straight into this module's own
  `DATA_REALITY`-style note once pulled — don't assume Sentinel-2's ~10m
  resolution resolves small MPLADS-scale works (a streetlight, a small
  culvert) before checking a sample.

## 3. Change-detection signal (new: `ml/cv/satellite_change.py`)

- **Baseline (build first):** NDVI / pixel-diff between t1/t2 tiles per
  asset. Zero training, explainable, matches the "human-in-loop, not
  auto-verdict" posture already used for photo-reuse confirmation.
- **Stretch:** pretrained Siamese change-detection network (OSCD/LEVIR-CD
  weights) for a confidence score instead of a raw diff — only worth doing
  if the baseline demo works and time remains.
- Output: `{asset_id, change_detected: bool, confidence, review_required:
  true}` — always routed to the reviewer workflow via the same
  Confirm/Dismiss pattern as other engines (`backend/main.py`), never
  auto-scored into `risk_score` without a human step, consistent with how
  this project already treats photo/text signals as advisory.

## 4. Synthetic MPLADS overlay (extend `pipeline/fraud_injection.py`)

For each sourced asset, generate a fabricated MPLADS-shaped record: MP
name, IDA, sanctioned amount (drawn from the real cost distribution
already profiled in `DATA_REALITY.md`, not invented), vendor, payment
dates, claimed completion date and status.

### Branch split by work category

Satellite change-detection only means something for categories where a
footprint change is physically plausible to see from orbit. The measured
category breakdown of the actual MPLADS corpus is majority small/indoor
work — applying imagery patterns there would be fabricating a signal for
work that was never detectable in the first place. So the overlay splits
into two branches, not one:

- **Branch A — satellite-visible categories** (roads, large community
  halls, check-dams, and similar plausible-footprint-change work): gets
  the coordinate/imagery-based patterns from step 3.
  - *Phantom work*: claim attached to a coordinate with no detected
    change.
  - *Coordinate reuse*: same real coordinate (or one within a few metres)
    used across ≥2 fabricated work IDs.
  - *Backdated completion*: claimed completion date precedes the real
    imagery's observed change date.
- **Branch B — non-visible categories** (street lights, small bore wells,
  indoor renovation, equipment installs — the majority of the actual
  corpus per the measured category breakdown): no imagery involved at
  all. Fraud is injected using the patterns the existing engines already
  target — photo/text duplication, cost outliers, structuring, missing
  evidence, entitlement pacing — same as the non-satellite fraud track.

**Sampling ratio (deliberately not corpus-representative):** Branch A
should make up roughly 30–40% of this module's new synthetic works —
oversampled relative to its true ~minority share of the real category
breakdown, specifically to showcase the satellite feature. The remaining
~60–70% is Branch B, sampled to look like normal, representative works
data rather than a fraud-heavy set. This ratio is a demo/build choice,
not a claim about real-world category or fraud prevalence — call it out
alongside the other synthetic-data framing in §0, and keep the per-branch
recall reporting in §7 so the oversampling doesn't get mistaken for a
"most works are satellite-checkable" claim.

Two label classes per branch, both mechanically constructed (no need to
find real failed projects):

- **Genuine:** Branch A overlay attached to an asset where step 3 shows
  real change (claim matches evidence); Branch B overlay with no injected
  pattern.
- **Injected fraud:** per-branch pattern lists above, extending the
  existing CAG-sourced pattern list.

**UI implication:** Branch B works must render as "satellite verification
not applicable," never as missing evidence — a streetlight can't have
imagery it was never capable of producing, and flagging it as if evidence
is missing would be a false flag baked into the module itself. The fusion
weight (§6) excludes Branch B works from the satellite-signal sum
entirely, rather than zeroing the term, so it doesn't silently pull the
score down for work that was never eligible for the check.

Output: `data/canonical/satellite_works.csv`, same shape family as the
existing `works.csv` join, with an added `source_scheme`, `branch`
(`A`/`B`), and `ground_truth_pattern` column (kept out of anything the
scorer sees — evaluation-only, same separation the existing evaluation
harness already enforces).

## 5. Vendor / payment network signal (new: `ml/anomaly/vendor_network.py`)

Fabricated vendor/payment ledger over the same synthetic works (real
financial data isn't public, so this whole track is synthetic by
necessity, same as most of §4). Patterns to inject, each independently
togglable in the evaluation harness the way existing patterns are:

- Vendor concentration (one vendor, disproportionate share of one MP's
  works)
- Shell-vendor signature (registration date immediately before first win)
- Bid collusion (near-identical quoted prices across nominally
  independent vendors, same work category/window)
- Split invoicing (same vendor + MP, multiple amounts just under the
  existing ₹10L structuring threshold within a short window — reuses the
  logic already in the structuring rule rather than duplicating it)
- Round-tripping (payments to related-looking shell entities)

Build a simple vendor↔MP↔IDA↔asset graph; score vendor centrality among
flagged works (same instinct as the Elliptic/PageRank approach from the
separate fraud-network competition project, reused here rather than
reinvented). Output: `{vendor_id, network_risk_score, contributing_works[]}`.

**Scope: both branches.** The graph is built over all synthetic works,
Branch A and Branch B alike — a fraud ring plausibly spans
satellite-visible and non-visible work types for the same MP/IDA, so
scoping vendor-network patterns to Branch A only would miss exactly the
kind of cross-category collusion this signal exists to catch.

## 6. Fusion integration (`pipeline.py: score_works`)

Add two advisory signals to the existing weighted-sum table
(`docs/PROJECT_FEATURES.md`'s signal table), each:

- Normalized 0–1 like every other track
- Given a provisional weight, not a load-bearing one, until the synthetic
  validation harness (below) reports a real per-pattern recall number —
  do not hardcode a "high-confidence" weight before that measurement
  exists, matching how `entitlement_pace` was deliberately hedged in
  `docs/DECISIONS.md`
- Kept out of the Critical-severity floor initially (same caution applied
  to unverified signals elsewhere in this project) until reviewed
- The satellite signal is only summed for Branch A works; Branch B works
  exclude it from the weighted total entirely (not zeroed) so the absence
  of imagery never depresses or otherwise affects their score, matching
  the "satellite verification not applicable" framing from §4

## 7. Evaluation (extend `scripts/evaluate.py`)

Add the new injected patterns (§4, §5) to the existing synthetic-injection
harness; report per-pattern recall the same way the current harness does
for photo/text/cost patterns. This is the actual evidence for "does this
catch anything," not a demo screenshot — same standard the project already
holds itself to.

Report recall **separately per branch** (Branch A imagery patterns vs.
Branch B non-imagery patterns), not pooled — a pooled number could hide
one branch underperforming behind the other, and per-branch numbers are
what proves the module isn't just cherry-picking a favorable subset of
the corpus to demo against.

## 8. Backend + frontend surface

- Backend: two read endpoints following the existing single-file
  `backend/main.py` pattern and jurisdiction-scoping convention —
  `/satellite/{work_id}` (change-detection result + review status),
  `/vendor-network` (flagged vendor list + linked works). Reviewer
  Confirm/Dismiss reuses the existing `investigations` table/flow, not a
  new one.
- Frontend: one new tab, styled like the existing Inefficiency/Confirmed
  tabs — before/after image pair + change-detection verdict + "computational
  signal, not proof" disclaimer (reuse the exact disclaimer language already
  used elsewhere in the dashboard) for Branch A works, a plain "satellite
  verification not applicable" state (never rendered as missing evidence)
  for Branch B works, plus a vendor-network view echoing the existing
  related-entities view, covering both branches.

## Build order

Matches the existing core/differentiator/stretch tiering convention from
`feature_plan.md`:

- **Core (needed for the module to demo at all):** §1 (coordinate
  sourcing spike), §2 (imagery pull), §3 baseline (NDVI diff), §4
  (synthetic overlay + 3 injected patterns), §7 (evaluation numbers).
- **Differentiator:** §5 (vendor network), §6 (fusion integration), §8
  (backend/frontend surface).
- **Stretch:** §3's Siamese CNN upgrade, PMAY-G/JJM source expansion,
  EXIF-timestamp cross-check on the imagery itself.

## Open questions to settle before starting §1

- Real time budget for the portal-access spike — if both Bhuvan NREGA and
  PMGSY stall, is a qualitative demo (dozens of hand-picked sites) an
  acceptable fallback, or does the pitch need corpus-scale numbers?
- Is this being built as a working prototype addition or an idea/PPT-round
  slide concept for now? Changes whether §5–§8 are worth starting before
  §1–§4 are proven out.
