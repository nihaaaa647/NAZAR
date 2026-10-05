# NAZAR — SIH demo script

_As of 2026-09-28 (Phase 5 section J). ~3 minutes, against the real local
pipeline output (or the deployed prototype once `docs/DEPLOYMENT.md`'s
blockers are cleared) — no disconnected mock data. Demo credentials are in
`README.md`'s "Sign-in and the four personas" table, never in this file or
the frontend bundle._

## Primary demo (≈3 minutes)

1. **Sign in as District Authority.** Point out: no role picker — the
   account *is* the role, jurisdiction is enforced server-side on every
   request, not just hidden in the UI.
2. **Open the Cases tab** (`GET /cases`, default `review_tier=actionable`
   queue). Point out the queue is already filtered to evidence-supported
   cases — a late-sanction-only delay under the severe threshold lives in
   a separate systemic/cohort view, not mixed in here (Phase 5 A.2
   calibration).
3. **Open one consolidated case** with two independent signals (e.g. a
   `cost_peer` + `photo_identical` case). Read the "why flagged" list aloud
   — each line is a specific, explained signal, not a black-box score.
   Point out `anomaly_priority`/`inefficiency_priority` are tracked
   separately and never summed together.
4. **Open its Image Evidence tab** (side-by-side originals). Show either:
   - a **watermark-gated** pair: point out the masked border region and
     that the classification is `rejected_watermark` — zero risk
     contribution, still visible as evidence, never silently discarded; or
   - an **ORB-confirmed** pair: show the match-line overlay and RANSAC
     inlier count, and say explicitly: *"confirmed visual correspondence
     means these images require human review — it does not mean duplicate,
     and it does not mean fraud."*
5. **Record a human decision** on the case (e.g. "Escalate for
   investigation" with a reason). Point out there is no "Declare Fraud"
   button anywhere in the product.
6. **Switch to Ministry view** (log out, sign in as Ministry). Open the
   same case — show the decision, the reviewer's name/role, and the
   timestamp now visible in its history.
7. **Show the Audit tab** (Ministry-only) — the access pattern and the
   decision both appear as audit events.
8. **Show the Data Quality tab** — one alert where a raw value was
   ambiguous (e.g. `X.XX Lakh` bucket) with `cost_peer`/`round_amount`-style
   analysis marked unavailable for that record, zero fraud-risk
   contribution, alongside its transformation lineage.
9. **Show the Inefficiency tab** — point out it's a structurally separate
   population and endpoint from the fraud queue, with its own "long-open
   work" language (never "idle funds"), and the 45-day late-sanction
   explanation text exactly as a reviewer would read it.

## Second example: NAZAR refuses to score unreliable evidence (short)

Open a work with a **corrupt or unavailable image**
(`reports/image_inventory.json`'s `invalid_file_categories` breakdown has
real examples — e.g. `pdf_without_extractable_image` or
`encrypted_document`). Show that:
- the attachment is classified by *why* it failed (Phase 5 A.4), not
  silently dropped;
- it never becomes a fabricated "photo" — a PDF with no embedded raster
  stays `pdf_without_extractable_image`/`document_page`, never rasterized
  into a fake completion photo;
- the case (if one exists for that work) shows this as an
  `unavailable_checks` entry with a stated reason, not a missing/blank
  field a reviewer has to guess about.

## What NOT to depend on live during the primary demo

- Any live external API call (satellite imagery, geocoding) — use the
  cached, already-fetched Sentinel-2 imagery in `data/satellite_cache/`
  (real, licensed under the provider's terms, attribution shown in the UI)
  rather than a fresh fetch that could fail or time out on stage.
- A specific case ID — pick one from a fresh `GET /cases` response
  shortly before presenting, since case IDs are deterministic but the
  *set* of cases regenerates with each pipeline run.
