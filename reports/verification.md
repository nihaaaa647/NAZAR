# NAZAR prototype verification — 2026-09-08

Real corpus: 5,611 completed works from 79 constituency CSVs in five states. The copied workspace had attachments but no completed CSVs; the existing sibling `sih/mplads_india` was read without running or editing the scraper. Source root and extraction failures are recorded in `pipeline.json`.

- Personas verified in the API and browser: MP office 476 works; district constituency cluster 553; Bihar state 2,711; ministry loaded corpus 5,611. Every returned list row was checked against its persona filter.
- 3,963 extracted attachments, 3,574 unique extracted images, 266 extraction failures. Missing source-listed evidence: 35.6% of works.
- Tier 1: 79 cross-work groups / 2,282 pairs. This establishes identical extracted bytes, not an improper claim: legitimate shared documents also match.
- Tier 2: measured Hamming percentiles 1/5/25/50/75/95 = 20/24/28/30/34/38. Conservative threshold 6. Candidates fell from 161,121 before gating to 3,882 after dimension gating; suppressing 40 connected components spanning more than six works left 234 cross-work pairs.
- Five distinct pairs from each photo tier were inspected in `visual_qa/`. Tier-1 samples included identical measurement books, a water-tank site photograph, an estimate and a receipt. Tier-2 samples were full completion/inspection reports, not scanner strips. Several had different text on matching form layouts: visual similarity is not proof of reused content. No SIFT/ORB confirmation was attempted, as scoped.
- Cross-year description evidence: 767 exact pairs and 980 near pairs. Blank descriptions and unknown fiscal years are excluded.
- Peer population sizes are at least 10, with full-activity and full-corpus fallback populations. No quantity field exists; amount and cost-per-unit input are explicitly disclosed as the same amount proxy.
- Severity distribution: 484 Critical, 0 High, 421 Moderate, 4,706 Low. Severity floors can make Critical works have a lower weighted score. No counts were filled in for empty bands.
- All endpoint smoke checks passed, including invalid persona/work/image inputs, invalid severity, whitespace-only review reasons, image media type, frontend serving, scoped summaries, and SQLite persistence across a new application lifespan. Smoke checks use a temporary database.
- Browser work details opened: 121156 (both image tiers rendered separately), 131226 (visually similar completion reports), 86128 (exact cross-year text). Confirm and Dismiss with required reasons were saved and recovered after reopening. Browser decisions are isolated in `browser_reviews.sqlite3`, not the delivered review database.
- Browser validation screen displayed 10/10 image-reuse recall, 10/10 cross-year-text recall, and 10/10 missing-evidence recall. Isolation Forest caught 7/10 high-amount/no-evidence injections. Synthetic data is isolated under `synthetic/`; results do not measure real-world precision or pHash accuracy.
- React/TypeScript production build passed. Vite reports a non-blocking bundle-size advisory because charts are bundled. The core stylesheet is local; Tailwind CDN and optional web fonts require a network connection.

Reproduce with `scripts/pipeline.py`, `scripts/evaluate.py`, `scripts/check_prototype.py` and `npm --prefix frontend run build`. Earlier user-authored ingestion documentation is preserved in `docs/INGESTION_README.md`.
