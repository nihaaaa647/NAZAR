# NAZAR execution state

## Current phase

Phase 0 implementation started on 2026-09-08. This is a foundation increment;
the full product definition of done has not been met.

## Phase checklist

- Phase 0: baseline committed; source review, scaffolding, pinned local environment,
  read-only profiler and parser/inventory tests implemented. Full CSV/attachment audit
  completed and inspected; DATA_REALITY.md reconciles F1–F8. Phase 0's broader
  verification is partial: pHash priors, semantic class proportions and current legal
  clauses remain explicitly unverified; fresh-machine reproduction is not claimed.
- Phase 1: not started. Database choice pending; canonical schema, idempotent ingestion,
  image extraction/triage, OCR prevalence and peer assignment remain.
- Phase 2: not started. Existing legacy injector is unsuitable for production;
  isolated evaluation storage and metrics remain.
- Phases 3–4: no detectors implemented or evaluated.
- Phase 5: no fusion, alerts, calibration, authentication or scoped API.
- Phase 6: no dashboard.
- Phase 7: no deployment, security validation or clean-machine full-stack reproduction.

## Blueprint contradictions to carry into Phase 1

1. `WORK_CATEGORY` is nearly constant. Derive activity taxonomy before forming peers;
   no cost-per-unit claim without an actual quantity/unit denominator.
2. PDF files can contain many images and page tiles, not one photograph each.
   Preserve source/page/object provenance; do not blindly label every thin strip junk.
3. Directory inventory includes unreferenced files. Legacy synthetic outputs must be
   isolated from real evidence. CSV linkage is the current profiler's analysis boundary.
4. Every current completed work joins to sanction data. Use real sanction dates;
   retain clearly labelled proxies only for future unjoined records.
5. `FILE_STATUS` tracks attachment availability. `FLAG` and `AVERAGE_RATING` are
   constant in completed data; omit them from detector features.
6. Joined sanctioned status says Physical Inspection for 4,730 completed records.
   Reconcile completed membership and sanctioned stage before idle-funds logic.
7. Tenure dates use portal timestamps; other dates use day-month-abbreviation-year.
8. Zero sanction overruns are a measured control, not evidence that all works are sound.
9. Fiscal-year coverage spans 2024, 2025 and 2026 letter starts; incomplete coverage
   and incomplete years do not support strong forecasts or national conclusions.
10. A 75-day date gap alone is not a sourced legal breach; recommendation versus
    receipt date and applicable exclusions need verification. The INR 10 lakh
    scrutiny threshold remains unsourced. Other proposed legal ceilings remain unverified.
11. GPS pixel overlays and semantic image classes have not been measured here.
    Nonempty EXIF exists in 3,501 decoded images, contradicting universal stripping;
    the tags' GPS/capture-time usefulness remains unverified.
12. Python 3.13 and the installed ML stack described in F8 are not available in this
    execution environment. Verified runtime is Python 3.12.14 with Phase 0 packages.
13. District scope cannot be inferred from an implementing-agency display name without
    a validated district/constituency mapping. Phase 1 must establish jurisdiction provenance.

## Self-check and honest gaps

- Architecture: Phase 0 tools match the intended foundation. Deviations and newly
  measured contradictions are in DECISIONS.md; schema work has not begun.
- Wiring: raw CSV -> profiler -> measured report exists. No risk signals, API or screen
  exist, so an end-to-end work-to-dashboard trace is not yet possible.
- Tests: 14 tests passed; `pip check` passed. Final run evidence is below.
- Synthetic isolation: inventory test proves unreferenced files are not analyzed.
  This is not the required future repository/API synthetic-row isolation guarantee.
- Language: new reports describe measurements and make no accusations. Historical
  source documents and the legacy injector retain outdated wording and assumptions;
  they are preserved references, not user-facing output templates.
- Regressions: existing scrapers and feature code unchanged. No government requests,
  data download, progress reset, model fit or production write was performed.
- Simplicity: no backend or detector dependencies installed early; no plausible stubs.
- Unverified: OCR, semantic triage, pHash distribution, general PDF extraction,
  guideline 2023 clauses, clean-machine setup on other operating systems, future ML
  dependencies, Docker daemon, PostgreSQL and the full application.

## Operator decisions

The operator selected **Use the local corpus**. The database question is pending;
recommend SQLite locally/PostgreSQL in Docker for the demo. That recommendation
is not recorded as approval. Finish independent Phase 0 work and leave schema
work unstarted until the database decision is resolved.

## Next action

Resolve storage choice, close remaining source/attachment verification gaps and
begin Phase 1 from measured data. Use the approved local corpus. Do not reuse the
old one-image extraction or automatic thin-image junk assumptions.

## Executed validation

- Baseline commit: `57abf15` (`Phase 0: preserve supplied project baseline`).
- Fresh project-local environment installation succeeded; exact installed versions
  are pinned in requirements.txt. `python -m pip check`: exit 0, no broken requirements.
- `python scripts/profile_data.py`: exit 0, 457.90 seconds. Saved exact summary:
  `reports/profile_summary.txt`; full output: `reports/data_profile.json`.
  Inspected 5,611 completed / 11,832 sanctioned rows, 100% join, zero overruns,
  21,978 decoded images, 232 unreferenced paths and no missing referenced paths.
- `python -m pytest -q`: exit 0, **14 passed in 1.36s** after the final profiler change.
- All existing and new Python source files parsed successfully using `ast.parse`.
- A real tiled PDF (`Andhra Pradesh/AMALAPURAM(SC)/163131_1.pdf`) has 235 JPEG
  streams. Opened three extracted strips; they show narrow scanned-paper fragments,
  not a sufficient basis for a scanner-watermark or usable-page classification.
- New source files inspected; historical scraper and consolidation files unchanged.
  No full product test, detector evaluation or live API/UI validation is claimed.
