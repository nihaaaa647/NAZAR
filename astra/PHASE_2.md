# PHASE 2 — Evaluation Harness First

Assumes the repository produced by Phase 1: canonical database loaded, attachments extracted
and triaged, peer groups assigned.

## OBJECTIVE

Build the fraud-injection harness and the metrics framework **before** any detector exists,
so that every detector is born measurable and no threshold is ever tuned by vibes.

## WHY THIS PHASE COMES HERE

There are no fraud labels. The project's entire answer to "how do you know it works" is
planted, CAG-shaped cases with known ground truth. If the harness is built after the
detectors, the injection patterns get quietly shaped to what the detectors already catch,
and the evaluation becomes theatre. Building it first makes it an honest test.

## CONTEXT

Source patterns: the CAG-documented mechanisms in project memory
(`cag_fraud_patterns.md`) and `feature_plan.md` section 2 — phantom/non-executed works,
fictitious measurement-book entries and short-executed works, duplicate claims across
financial years, non-standard implementing agencies, excess payment for substandard
materials, anticipatory/unauthorised sanctioning, image reuse, broken sequencing.
Blueprint Part O governs isolation; Part P governs which metric matters per engine.

## TASKS

1. **`ml/evaluation/fraud_injection.py`.** For each pattern: clone real rows from the corpus,
   mutate them into the documented fraud shape with parameters drawn from real case
   magnitudes, tag them with `is_synthetic`, the pattern name and the ground-truth label, and
   write them to the isolated `fraud_injection_case` table plus an evaluation copy of the
   dataset. Patterns to implement, at minimum:
   - structuring (one work split into several sub-threshold works, same agency, tight window)
   - phantom work (completed, high amount, zero or junk-only attachments)
   - cross-year duplicate claim (same asset reworded, one to two years apart)
   - image reuse (a real attachment byte-copied onto a different work)
   - short execution (actual materially below sanctioned, implausibly fast)
   - broken sequencing (completion before sanction, or sanction before recommendation)
   - non-standard implementing agency (trust/society/cooperative in place of a district body)
   - sanction-deadline breach (recommendation to sanction far beyond 75 days)
2. **Isolation, proven.** Injected rows carry `is_synthetic = true`, live in a separate
   schema or table, and are excluded at the repository/query layer — not by a UI filter.
   Write the test that proves a synthetic row cannot appear in a default `/works` result
   now, before the API exists, as a repository-layer test.
3. **`ml/evaluation/metrics.py`.** Per-pattern recall, precision@K, per-engine flag rate over
   the real corpus, and a false-positive-rate estimate. Include a baseline: what a random
   ranking, and a rank-by-amount ranking, would score. A detector that cannot beat
   "sort by amount descending" is not yet a detector.
4. **`scripts/run_evaluation.py`** produces `reports/evaluation.md` — regenerable, with the
   run date, corpus size, injection counts, and every metric. At this phase it legitimately
   reports zeros with "no detectors implemented yet"; that is the point.
5. Extend `docs/DECISIONS.md` with the parameters chosen for each pattern and the real case
   that justifies each parameter.

## CONSTRAINTS

- Injected cases must be **plausible**, not cartoonish. A phantom work priced at ₹99 crore
  proves nothing. Draw magnitudes from the corpus's real distributions.
- Injection is deterministic under a fixed seed, and the seed is recorded in the report.
- The harness never writes to the production tables.
- Do not design patterns around detectors you have not written yet.

## VALIDATION

- Run the injector; print counts per pattern; **manually read five injected rows per pattern**
  and confirm each is realistic and correctly labelled.
- The isolation test passes and fails correctly when deliberately broken (break it, watch the
  test fail, fix it).
- `reports/evaluation.md` generates cleanly.

## COMPLETION CRITERIA

- All eight patterns implemented, seeded, deterministic and documented.
- Metrics module computes recall, precision@K and both baselines against any supplied ranking.
- The synthetic-isolation guarantee is enforced at the query layer and covered by a test.
- `reports/evaluation.md` regenerates from one command.

## INSPECT BEFORE MOVING ON

For each pattern, write one sentence in `docs/DECISIONS.md` stating which engine should catch
it and roughly what recall would be a credible result. Recording that expectation now is what
stops you from grading on a curve later.
